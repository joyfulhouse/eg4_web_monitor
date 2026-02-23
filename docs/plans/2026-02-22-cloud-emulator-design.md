# Cloud Emulator (CloudEmitter) Design

**Date**: 2026-02-22
**Status**: Approved
**Scope**: pylxpweb library + minimal HA config flow changes

## Problem

When users replace the physical EG4 WiFi dongle with a Waveshare RS485 adapter (direct Modbus TCP), the cloud monitoring portal at monitor.eg4electronics.com stops receiving data. Users lose:

- Remote monitoring via the EG4 app/web dashboard
- Cloud-initiated parameter changes (remote settings)
- Cloud-orchestrated firmware updates
- Historical data reporting

## Solution

A `CloudEmitter` class in pylxpweb that acts as a **virtual WiFi dongle**, maintaining a TCP connection to the EG4 cloud ingestion server and forwarding register data using the same binary protocol as the physical dongle.

## Architecture

### High-Level Data Flow

```
Inverter ──RS485──> Waveshare ──Modbus TCP──> pylxpweb (HA)
                                                  │
                                          BaseInverter.refresh()
                                           reads registers, caches
                                                  │
                                          CloudEmitter (background task)
                                           reads cached raw registers
                                           builds 0xC2 frames
                                                  │
                                          TCP connection
                                                  │
                                                  ▼
                                    us2.solarcloudsystem.com:4346
```

### Key Design Decisions

1. **Standalone asyncio task in pylxpweb** — not tied to HA refresh cycle
2. **Zero additional Modbus reads** — reads from raw register snapshot stashed during normal HA polling
3. **Fresh reads for cloud commands only** — 0xC3 GET_PARAM and 0xC4 SET_PARAM bypass cache
4. **Auto-detected dongle serial** — from cloud API `InverterInfo.datalogSn`, not user-entered
5. **No PIN required** — TCP ingestion server authenticates by serial only (PIN is for one-time app registration)

## Protocol Details

### Frame Format (all transports share this)

```
[A1 1A] [ver_lo ver_hi] [frame_len_lo frame_len_hi] [addr] [func] [serial x10] [payload...] [CRC16]
  0-1       2-3                  4-5                   6      7       8-17          18+
```

- `frame_length` = total_size - 6
- `addr` = always 1
- `func` = 0xC1 (heartbeat), 0xC2 (data), 0xC3 (get param), 0xC4 (set param)
- CRC-16/Modbus (init=0xFFFF, poly=0xA001)

### Heartbeat (0xC1) — 19 bytes

```
[A1 1A] [01 00] [0D 00] [01] [C1] [serial x10] [05]
```

- Sent on connect (first packet) and every 18 seconds of silence
- Status byte = 0x05
- Cloud does NOT echo heartbeats (unlike local/BLE)

### Data Transmission (0xC2)

Payload = verbatim Modbus RTU response bytes:

```
[slave_addr=1] [func_code] [byte_count] [register_data...] [CRC16]
```

Per poll cycle, the CloudEmitter sends:
1. Holding registers 0-79 (func=0x03, 1 frame)
2. Input registers 0-126 (func=0x04, frame 1 of 3)
3. Input registers 127-253 (func=0x04, frame 2 of 3)
4. Input registers 254-380 (func=0x04, frame 3 of 3)

### Cloud Commands (0xC3/0xC4)

Received from cloud server when user changes settings via web dashboard:

- **0xC3 GET_PARAM**: Fresh register read via transport (bypass snapshot)
- **0xC4 SET_PARAM**: Write register via transport, invalidate HA parameter cache
- **Dongle-internal codes** (0, 1, 3, 4, 6, 9, 0x0C, 0x0D, 0x11, 0x12, 0x14): ACK without action (these configured the physical dongle, not the inverter)

### Timing

| Parameter | Value | Source |
|-----------|-------|--------|
| Data push interval | ~100 seconds | Firmware `data_period * 100` |
| Heartbeat trigger | 18 seconds of silence | `HeartbeatTimer` decompilation |
| Heartbeat timeout | 19 seconds → reconnect | `HeartbeatTimer` decompilation |
| Connect timeout | 1 second | `TCPClientApp_Init` decompilation |

## Raw Register Snapshot

### Problem

The CloudEmitter needs raw register values (uint16 arrays), but `BaseInverter.refresh()` produces parsed data objects (`InverterRuntimeData`, `InverterEnergyData`). Parsing is lossy — reconstructing original register bytes from parsed data is error-prone.

### Solution

Transports stash raw register values as a side-effect of normal reads:

```python
# In BaseModbusTransport._read_registers():
values = result.registers[:]
# Stash for CloudEmitter
reg_type = "input" if input_registers else "holding"
for i, val in enumerate(values):
    self._register_snapshot[reg_type][address + i] = val
return values
```

The snapshot is a `dict[str, dict[int, int]]` mapping register type to address-value pairs. The CloudEmitter reads this snapshot to build 0xC2 frames without triggering additional Modbus reads.

DongleTransport needs the same stashing in `_read_input_registers` and `_read_holding_registers`.

## CloudEmitter Class

### Location

```
pylxpweb/src/pylxpweb/
├── cloud/
│   ├── __init__.py
│   ├── emitter.py        # CloudEmitter class
│   ├── frames.py         # Frame building (0xA1/0x1A protocol)
│   └── protocol.py       # CRC-16, frame parsing, constants
```

### Lifecycle

```python
class CloudEmitter:
    def __init__(
        self,
        dongle_serial: str,           # 10-digit serial from cloud API
        transport: InverterTransport,  # For fresh reads on cloud commands
        host: str = "us2.solarcloudsystem.com",
        port: int = 4346,
        data_period: float = 100.0,
    ): ...

    async def start(self) -> None:
        """Start background TCP connection and data forwarding."""

    async def stop(self) -> None:
        """Stop background task and close TCP connection."""

    @property
    def is_connected(self) -> bool:
        """Whether TCP connection to cloud is active."""
```

### Main Loop

```python
async def _run_loop(self):
    while self._running:
        try:
            await self._connect()
            await self._send_heartbeat()     # First packet on connect
            await self._data_and_command_loop()
        except (ConnectionError, asyncio.TimeoutError):
            await asyncio.sleep(5)           # Reconnect backoff

async def _data_and_command_loop(self):
    last_data_send = time.monotonic()
    while self._connected:
        now = time.monotonic()

        # Send data if period elapsed
        if now - last_data_send >= self._data_period:
            await self._emit_data()
            last_data_send = now

        # Send heartbeat if silent too long
        if now - self._last_send_time >= 18.0:
            await self._send_heartbeat()

        # Check for incoming commands (non-blocking, 1s timeout)
        await self._receive_commands(timeout=1.0)
```

### Data Emission (0xC2)

```python
async def _emit_data(self):
    snapshot = self._transport._register_snapshot
    input_regs = snapshot.get("input", {})
    holding_regs = snapshot.get("holding", {})

    if not input_regs and not holding_regs:
        return  # No data yet (HA hasn't polled)

    # Build and send holding register frame (0-79)
    if holding_regs:
        frame = self._build_data_frame(
            func_code=0x03,
            start_reg=0,
            registers=holding_regs,
            max_reg=79,
        )
        await self._send_frame(frame)

    # Build and send input register frames (0-380 in chunks of 127)
    if input_regs:
        for chunk_start in range(0, 381, 127):
            chunk_end = min(chunk_start + 126, 380)
            frame = self._build_data_frame(
                func_code=0x04,
                start_reg=chunk_start,
                registers=input_regs,
                max_reg=chunk_end,
            )
            await self._send_frame(frame)
```

### Command Handling (0xC3/0xC4)

```python
# Dongle-internal SET_PARAM codes (not forwarded to inverter)
_DONGLE_INTERNAL_CODES = {0, 1, 3, 4, 6, 9, 0x0C, 0x0D, 0x11, 0x12, 0x14}

async def _handle_get_param(self, frame):
    """Fresh register read for cloud-requested data."""
    values = await self._transport.read_parameters(
        frame.start_param, frame.param_count
    )
    response = self._build_param_response(frame, values)
    await self._send_frame(response)

async def _handle_set_param(self, frame):
    """Write register and invalidate HA cache."""
    if frame.param_code in self._DONGLE_INTERNAL_CODES:
        await self._send_ack(frame)
        return
    await self._transport.write_parameters(
        {frame.register: frame.value}
    )
    # Invalidate HA's parameter cache
    if self._inverter is not None:
        self._inverter._parameters_cache_time = None
```

## HA Integration Changes

### Config Flow

Minimal changes to `config_flow/`:

1. When cloud credentials are available AND local transport is configured
2. Auto-fetch `InverterInfo.datalogSn` for the inverter
3. Store as `CONF_DONGLE_SERIAL` in config entry data
4. No user-facing input field for serial (auto-populated)

### Options Flow

Add toggle in options flow:

- "Enable cloud data reporting" (default: disabled)
- Only shown when connection type is `local` or `hybrid` AND `CONF_DONGLE_SERIAL` is available

### Coordinator

When cloud reporting is enabled:

```python
# In coordinator setup:
if self._data_validation_enabled and self._dongle_serial:
    emitter = CloudEmitter(
        dongle_serial=self._dongle_serial,
        transport=inverter._transport,
    )
    await emitter.start()
    # Store for cleanup
    self._cloud_emitter = emitter
```

On unload: `await self._cloud_emitter.stop()`

## Security Model

1. **Auto-detect only** — dongle serial comes from cloud API, not user input
2. **Cloud API authentication** — only returns serials the user owns
3. **No PIN needed** — TCP ingestion uses serial-only authentication
4. **No fabrication possible** — user cannot enter arbitrary serial

## Testing Plan

### Unit Tests (pylxpweb)

- Frame building: verify 0xA1/0x1A prefix, CRC-16, field positions
- Heartbeat: verify 19-byte format, status byte, serial encoding
- Data frames: verify 0xC2 payload matches Modbus RTU format
- Register snapshot: verify stashing during reads
- Command parsing: verify 0xC3/0xC4 frame parsing
- Connection lifecycle: connect, heartbeat, data, reconnect on failure

### Integration Tests (HA)

- Config flow: auto-detection of dongle serial
- Options flow: cloud reporting toggle
- Coordinator: emitter start/stop lifecycle
- Coordinator: emitter stop on unload

### Manual Validation

- Compare cloud dashboard data with local HA data
- Verify cloud-initiated parameter changes propagate to HA
- Verify heartbeat keeps connection alive
- Test reconnection after network interruption

## Open Questions

1. **serverId mapping**: `DatalogListItem.serverId` likely maps to TCP server hostname (e.g., `us{id}.solarcloudsystem.com`). Need to verify with real API data.
2. **Register group selection**: The firmware selects group 0 vs 1 based on inverter register 26 bits 4:1. Need to determine which group applies to EG4 inverters.
3. **SSL/TLS**: `dongle_ssl.solarcloudsystem.com:4348` exists for TLS connections. Should we prefer TLS over plain TCP?
