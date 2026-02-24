# Cloud Emulator (CloudEmitter) Design

**Date**: 2026-02-22 (updated 2026-02-24, pcap-validated)
**Status**: Design approved, traffic capture validates protocol
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
- Status byte = 0x01 for inverters, 0x05 for GridBOSS (pcap-confirmed)
- Cloud DOES echo heartbeats back (same status byte, ~20ms later)

### Data Transmission (0xC2)

**IMPORTANT UPDATE (2026-02-24)**: LuxPower/EG4 inverters use a **proprietary extended
Modbus format**, NOT standard Modbus RTU. Both request and response embed a 10-byte
inverter serial. The dongle forwards these verbatim — no transformation.

Payload structure:
```
[modbus_len_lo modbus_len_hi] [extended_modbus_response...]
        2 bytes (LE)               modbus_len bytes
```

Extended Modbus response format (271 bytes for 127 input regs):
```
[slave=01] [func] [inverter_serial x10] [start_reg 2B LE] [byte_count] [data...] [CRC16 2B]
    1        1          10                     2              1          254          2
```

**CRITICAL UPDATE (pcap 2026-02-24): Dual polling model confirmed.**

**Holding registers — Cloud-initiated (reactive):**
The cloud sends READ_HOLDING requests; the emitter must RESPOND to them.

| # | Direction | Func | Start Reg | Count | Request | Response |
|---|-----------|------|-----------|-------|---------|----------|
| 1 | cloud→emitter | 0x03 | 0 | 127 | 38 bytes | 291 bytes |
| 2 | cloud→emitter | 0x03 | 127 | 127 | 38 bytes | 291 bytes |
| 3 | cloud→emitter | 0x03 | 240 | 127 | 38 bytes | 291 bytes |

**Input registers — Emitter-initiated (proactive push):**

| # | Direction | Func | Start Reg | Count | 0xC2 Frame |
|---|-----------|------|-----------|-------|------------|
| 1 | emitter→cloud | 0x04 | 0 | 127 | 291 bytes |
| 2 | emitter→cloud | 0x04 | 127 | 127 | 291 bytes |
| 3 | emitter→cloud | 0x04 | 254 | 127 | 291 bytes |
| 4* | emitter→cloud | 0x04 | 5000 | 127 | 291 bytes |

*Battery data is conditional (sent when battery cycle counter changes)

**Write operations (cloud→emitter→inverter):**
Cloud sends WRITE_SINGLE (0x06) as a 0xC2 frame. Pattern: read-then-write.
Emitter must forward to inverter and echo the WRITE back to cloud.

**Register 2032 probes:**
Cloud probes reg 2032 on all devices. Return exception code 3 for inverters.

The CloudEmitter must **reconstruct** the extended Modbus response format from
cached register values, embedding the inverter serial and computing CRC-16/Modbus
over the full extended frame. **All values are little-endian** (not big-endian).

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

**Additional requirement (2026-02-24)**: The CloudEmitter also needs the **inverter serial** (10 ASCII digits) to embed in the extended Modbus response frames. This is already available from `inverter.serial_number` in pylxpweb.

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
    last_input_push = time.monotonic()
    while self._connected:
        now = time.monotonic()

        # Push input registers autonomously (all device types — pcap-confirmed)
        if now - last_input_push >= self._data_period:
            await self._push_input_registers()
            last_input_push = now

        # Send heartbeat if silent too long
        if now - self._last_send_time >= 18.0:
            await self._send_heartbeat()

        # Receive and handle cloud commands (READ requests, WRITE, etc.)
        # Cloud-initiated holding register reads are handled here
        await self._receive_and_dispatch(timeout=1.0)
```

### Autonomous Input Push (0xC2, all device types)

```python
async def _push_input_registers(self):
    """Push input register data to cloud (autonomous, all devices).
    Second pcap capture confirmed GridBOSS also pushes input registers."""
    snapshot = self._transport._register_snapshot
    input_regs = snapshot.get("input", {})
    if not input_regs:
        return

    for chunk_start in (0, 127, 254):
        frame = self._build_extended_modbus_frame(
            func_code=0x04, start_reg=chunk_start, count=127,
            registers=input_regs,
        )
        await self._send_c2_frame(frame)

    # Battery data (conditional, inverters only — GridBOSS has no batteries)
    if not self._is_gridboss and self._has_battery_data:
        frame = self._build_extended_modbus_frame(
            func_code=0x04, start_reg=5000, count=127,
            registers=input_regs,
        )
        await self._send_c2_frame(frame)

### Cloud-Initiated Read Handler

async def _handle_cloud_read(self, request_frame):
    """Respond to cloud READ_HOLDING/READ_INPUT request.
    Cloud sends 18-byte extended Modbus request, we respond with data."""
    func_code = request_frame.modbus_func
    start_reg = request_frame.start_reg
    # Always respond with 127 registers (firmware behavior)
    count = 127
    reg_type = "holding" if func_code == 0x03 else "input"
    snapshot = self._transport._register_snapshot.get(reg_type, {})

    # Special case: register 2032 → exception code 3
    if start_reg == 2032 and not self._is_gridboss:
        await self._send_exception(func_code, start_reg, exception_code=3)
        return

    frame = self._build_extended_modbus_frame(
        func_code=func_code, start_reg=start_reg, count=count,
        registers=snapshot,
    )
    await self._send_c2_frame(frame)

### Cloud-Initiated Write Handler (with safety guardrails)

# Whitelist of registers safe to forward WRITE_SINGLE to inverter.
# ONLY registers observed in pcap captures or documented in CLAUDE.md
# register map are included. All other writes are BLOCKED.
_WRITABLE_REGISTERS: frozenset[int] = frozenset({
    20,   # GridBOSS smart port status (bit-packed)
    21,   # Control bits (EPS, AC charge, forced charge/discharge)
    64,   # PV charge power (0-100%)
    65,   # Discharge power (0-100%)
    66,   # AC charge power (0-100%)
    67,   # AC charge SOC limit (0-100%)
    74,   # Parameter (observed write in pcap)
    101,  # Charge current (amps)
    102,  # Discharge current (amps)
    105,  # On-grid SOC cutoff (10-90%)
    106,  # Off-grid SOC cutoff (0-100%)
    110,  # Green/off-grid mode bit field
})

async def _handle_cloud_write(self, request_frame):
    """Forward WRITE_SINGLE from cloud to inverter, with safety checks.

    CRITICAL: Only whitelisted registers are forwarded. Unknown registers
    and non-WRITE_SINGLE function codes are rejected with an exception.
    Firmware upgrade writes are NOT yet documented and MUST be blocked.
    """
    reg = request_frame.register

    # Block non-WRITE_SINGLE function codes (e.g., WRITE_MULTI 0x10)
    if request_frame.func_code != 0x06:
        _LOGGER.warning(
            "CloudEmitter: BLOCKED unknown write — func=0x%02X reg=%d "
            "value=0x%04X (%d) serial=%s slave=%d. "
            "If this is a legitimate cloud operation, please report at "
            "https://github.com/joyfulhouse/eg4_web_monitor/issues "
            "with this log line so we can add support.",
            request_frame.func_code, reg, request_frame.value,
            request_frame.value, request_frame.inverter_serial,
            request_frame.slave_addr,
        )
        await self._send_exception(request_frame.func_code, reg, exception_code=1)
        return

    # Block writes to unwhitelisted registers
    if reg not in self._WRITABLE_REGISTERS:
        _LOGGER.warning(
            "CloudEmitter: BLOCKED write to unknown register — func=0x%02X "
            "reg=%d value=0x%04X (%d) serial=%s slave=%d. "
            "If this is a legitimate cloud operation, please report at "
            "https://github.com/joyfulhouse/eg4_web_monitor/issues "
            "with this log line so we can add support.",
            request_frame.func_code, reg, request_frame.value,
            request_frame.value, request_frame.inverter_serial,
            request_frame.slave_addr,
        )
        await self._send_exception(request_frame.func_code, reg, exception_code=1)
        return

    # Forward to inverter via transport
    await self._transport.write_register(reg, request_frame.value)
    # Echo the write frame back to cloud (confirmation)
    await self._send_frame(request_frame.raw_bytes)

def _build_extended_modbus_frame(
    self,
    func_code: int,
    inverter_serial: str,
    start_reg: int,
    registers: dict[int, int],
    max_reg: int,
) -> bytes:
    """Build extended Modbus response frame.

    Format: [slave][func][serial 10B][start_reg 2B LE]
            [byte_count][data LE...][CRC16 LE]
    ALL fields are little-endian (confirmed by pcap 2026-02-24).
    """
    count = max_reg - start_reg + 1
    byte_count = count * 2

    body = bytearray()
    body.append(self._slave_addr)  # slave_addr (0 for inverters, 1 for GridBOSS)
    body.append(func_code)         # function code
    body.extend(inverter_serial.encode("ascii").ljust(10, b"\x00"))
    body.extend(start_reg.to_bytes(2, "little"))
    body.append(byte_count)

    # Register data (little-endian — NOT standard Modbus big-endian)
    for reg in range(start_reg, start_reg + count):
        val = registers.get(reg, 0)
        body.extend(val.to_bytes(2, "little"))

    # CRC-16/Modbus over entire extended body
    crc = compute_crc16(bytes(body))
    body.extend(crc.to_bytes(2, "little"))

    return bytes(body)
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

### Write Safety (CRITICAL)

6. **Whitelist-only writes** — Only WRITE_SINGLE (0x06) to known, documented registers
   is forwarded to the inverter. All other writes are rejected with Modbus exception.
7. **No WRITE_MULTI** — Bulk writes (func 0x10) are blocked until documented and tested.
8. **No firmware writes** — Firmware upgrade protocol is not yet documented.
   Any writes to unrecognized registers (especially 2032+) are blocked.
9. **Logging** — All blocked writes are logged at WARNING level for audit trail.
10. **Expandable whitelist** — New registers can be added to `_WRITABLE_REGISTERS`
    after pcap verification and documentation in TRAFFIC_ANALYSIS.md.

## Testing Plan

### Unit Tests (pylxpweb)

- Frame building: verify 0xA1/0x1A prefix, frame_length, field positions
- Heartbeat: verify 19-byte format, status byte, serial encoding
- Extended Modbus: verify 271-byte format with embedded serial, start_reg, CRC-16
- Data frames: verify 0xC2 payload = [modbus_len LE][extended_modbus_response]
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
