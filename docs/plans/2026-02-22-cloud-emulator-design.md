# Cloud Emulator (CloudEmitter) Design

**Date**: 2026-02-22 (updated 2026-02-23)
**Status**: Design approved, pending traffic capture validation
**Scope**: pylxpweb library + HA config flow changes (hybrid mode only)

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

### Frame Format (TCP Cloud Transport)

```
[A1 1A] [ver_lo ver_hi] [frame_len_lo frame_len_hi] [addr] [func] [serial x10] [payload...]
  0-1       2-3                  4-5                   6      7       8-17          18+
```

- `frame_length` = total_size - 6
- `addr` = always 1
- `func` = 0xC1 (heartbeat), 0xC2 (data), 0xC3 (get param), 0xC4 (set param)
- **No trailing CRC-16** on TCP cloud frames (confirmed via firmware decompilation)
- CRC-16/Modbus only exists within Modbus RTU payloads inside 0xC2 frames

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

## Pre-Implementation: Traffic Capture Phase

**BLOCKING**: Implementation MUST NOT begin until traffic capture is complete and analyzed.

The firmware decompilation gives us the protocol spec, but we need to observe real
dongle-to-cloud traffic to confirm:
- Exact byte sequences for each frame type
- Ordering and timing of data frames within a poll cycle
- Cloud server responses (if any) to data frames
- Any handshake or session negotiation we may have missed
- Register group selection (group 0 vs 1 vs 2)
- serverId-to-hostname mapping

### Capture Method: Packet Capture (tcpdump/Wireshark)

```
Dongle ──WiFi──> Router ──> us2.solarcloudsystem.com:4346
                   │
                   └── tcpdump/Wireshark captures TCP stream
                       Filter: host us2.solarcloudsystem.com and port 4346
```

### Capture Script

```bash
# On a host that can see dongle traffic (router, mirror port, or HA host)
sudo tcpdump -i any host us2.solarcloudsystem.com and port 4346 -w dongle_capture.pcap -v

# Or filter by dongle IP if known:
sudo tcpdump -i any host 192.168.1.XXX and port 4346 -w dongle_capture.pcap -v
```

### Analysis Script

Write a Python script to parse the pcap and decode 0xA1/0x1A frames:
- Decode each frame (func code, serial, payload)
- For 0xC2 frames: decode Modbus RTU payload (func, start reg, register values)
- For 0xC1 frames: verify heartbeat format and timing
- Log any server→dongle frames (commands, acks, etc.)
- Calculate actual data_period timing between poll cycles
- Identify which register groups are sent

### Deliverables

- `scratchpad/firmware/dongle_capture.pcap` — raw packet capture
- `scratchpad/firmware/TRAFFIC_ANALYSIS.md` — decoded frame analysis
- Confirmation/correction of protocol assumptions from decompilation

## Feature Gating

### pylxpweb Level

CloudEmitter is an **explicit opt-in** API. It never auto-starts.

```python
# Enable cloud reporting on an inverter
inverter.enable_cloud_reporting(dongle_serial="BA12345678")

# Disable
await inverter.disable_cloud_reporting()

# Check status
inverter.cloud_reporting_enabled  # bool
inverter.cloud_emitter  # CloudEmitter | None
```

**Requirements to enable:**
- Local transport attached (`inverter._transport is not None`)
- Valid 10-digit `dongle_serial`
- If either is missing → raises `ValueError`

### HA Level — Hybrid Mode Only

Cloud reporting is ONLY available in **hybrid mode** because it requires both:
- **Cloud credentials** — to fetch `InverterInfo.datalogSn` and verify dongle ownership
- **Local transport** — to read registers for forwarding

Pure local mode has no cloud credentials → cannot verify dongle ownership.
Pure cloud mode has no local transport → no registers to forward.

### Prerequisites

1. User MUST first register their physical dongle via the EG4 app (serial + check code)
2. User configures HA in hybrid mode (cloud creds + local Modbus/dongle)
3. During config flow, `InverterInfo.datalogSn` is auto-fetched and mapped to the correct inverter
4. Options flow shows "Enable cloud data reporting" toggle (disabled by default)
5. Toggle includes a warning: "Your WiFi dongle must be registered with EG4 before enabling"

## HA Integration Changes

### Config Flow

During hybrid mode setup:

1. After station/plant selection, fetch `InverterInfo` list for the selected station
2. For each inverter, extract `datalogSn` from `InverterInfo`
3. Store mapping `{inverter_serial: datalogSn}` as `CONF_DONGLE_SERIAL_MAP` in config entry data
4. No user-facing input — auto-populated from cloud API

### Options Flow

Add toggle in options flow:

- "Enable cloud data reporting" (default: **disabled**)
- **Only shown when `connection_type == "hybrid"` AND `CONF_DONGLE_SERIAL_MAP` is present**
- Includes i18n warning text about dongle registration prerequisite

### Coordinator

When cloud reporting is enabled:

```python
# In coordinator setup (after first successful poll):
if self._cloud_reporting_enabled and self._dongle_serial_map:
    for inverter in self._inverters.values():
        dongle_sn = self._dongle_serial_map.get(inverter.serial_number)
        if dongle_sn and inverter._transport is not None:
            inverter.enable_cloud_reporting(dongle_serial=dongle_sn)
```

On unload:
```python
for inverter in self._inverters.values():
    await inverter.disable_cloud_reporting()
```

## Security Model

1. **Hybrid mode only** — requires cloud credentials proving account ownership
2. **Auto-detect only** — dongle serial from cloud API `InverterInfo.datalogSn`, not user input
3. **Registration prerequisite** — physical dongle must be registered first (serial + check code)
4. **No fabrication possible** — user cannot enter arbitrary serial
5. **No PIN in transit** — TCP ingestion uses serial-only (PIN is for one-time registration)

## Testing Plan

### Unit Tests (pylxpweb)

- Frame building: verify 0xA1/0x1A prefix, CRC-16, field positions
- Heartbeat: verify 19-byte format, status byte, serial encoding
- Data frames: verify 0xC2 payload matches Modbus RTU format
- Register snapshot: verify stashing during reads
- Command parsing: verify 0xC3/0xC4 frame parsing
- Connection lifecycle: connect, heartbeat, data, reconnect on failure
- Feature gating: enable/disable API, ValueError when prerequisites missing

### Integration Tests (HA)

- Config flow: auto-detection of dongle serial map (hybrid mode)
- Config flow: toggle NOT shown in local-only or cloud-only modes
- Options flow: cloud reporting toggle with prerequisite check
- Coordinator: emitter start/stop lifecycle
- Coordinator: emitter stop on unload

### Manual Validation

- Compare cloud dashboard data with local HA data
- Verify cloud-initiated parameter changes propagate to HA
- Verify heartbeat keeps connection alive
- Test reconnection after network interruption

## Open Questions

1. **serverId mapping**: `DatalogListItem.serverId` likely maps to TCP server hostname (e.g., `us{id}.solarcloudsystem.com`). Traffic capture should confirm.
2. **Register group selection**: The firmware selects group 0 vs 1 based on inverter register 26 bits 4:1. Traffic capture should confirm which group EG4 inverters use.
3. **SSL/TLS**: `dongle_ssl.solarcloudsystem.com:4348` exists. Should we prefer TLS?
4. **Cloud server responses**: Does the cloud send anything back for 0xC2 data frames, or is it fire-and-forget? Traffic capture will answer.
5. **Multi-inverter mapping**: With parallel groups, does each inverter have its own dongle, or does one dongle serve the whole plant? Need to verify `datalogSn` cardinality.
