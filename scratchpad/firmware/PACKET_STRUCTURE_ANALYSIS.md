# Dongle→Cloud Packet Structure Deep Analysis

**Date**: 2026-02-24
**Source**: Ghidra decompilation of E_V2_10.bin (ESP32-C3, v2.10)
**Purpose**: Document exact packet structure to prevent serial ban from malformed data

---

## 1. Complete Data Flow: RS485 → Cloud TCP

### Architecture Overview

The dongle is a **transparent bridge** between the inverter (RS485) and the cloud (TCP). There is NO data transformation — raw Modbus RTU response bytes from the inverter are wrapped in 0xA1/0x1A frames and sent verbatim to the cloud.

```
Inverter ──RS485 19200 8N1──> Dongle ──TCP──> us2.solarcloudsystem.com:4346

RS485 Flow:
  RS485App_MainHandler (state machine, 0x4200ae70)
    ├── State 0 (IDLE): Send holding register read request
    │     └── BuildPacket(func=0x03, start_reg, count) → RS485Service_SendMessage
    │         Callback: RS485_DataCallback (FUN_ram_4200ab1c)
    ├── State 1 (WAITING): Wait for RS485 response
    ├── State 2 (COMPLETE): Reset group index to 0, back to IDLE
    ├── State 3 (UNSUPPORTED): Try next group index, back to IDLE
    └── State 4 (DATA_READY): Poll timer, battery read, data emit
          ├── Battery data read: input reg 5000, count 127
          │     Callback: LAB_ram_4200aaec (RS485_DataReadyCallback)
          ├── Poll timer check: NVS_GetParam(0) * 1000 ms
          └── On timer fire:
                ├── FUN_ram_4200ac04(LAB_ram_4200aaec) → holding register reads
                └── FUN_ram_4200acca(LAB_ram_4200aaec) → input register reads
```

### Key Insight: The Data Send Path

The RS485 module is a **queued message service**. When you call:
- `RS485Service_SendMessage(rs485_handle, &callback_struct)` (FUN_ram_4200ca48)

It queues a Modbus request (built by `BuildPacket`/FUN_ram_4200de8c). The RS485 service task (`rs485_service_task` at DAT_ram_4200c4cc) dequeues messages, sends them over UART, and when responses arrive, invokes the callback.

The callback `LAB_ram_4200aaec` is **not a standalone function** — it's a jump label within the `RS485App_MainHandler` function at offset 0x4200aaec. Ghidra couldn't decompile it as a separate function because it's mid-function. However, from the state machine analysis, we know:

1. The callback receives the raw Modbus RTU response bytes
2. It wraps them in a 0xA1/0x1A frame with function code 0xC2
3. It sends via `DataProcess_Send` (FUN_ram_42009c02)
4. `DataProcess_Send` calls the transport-specific send callback (stored at offset 0x00 in the DataProcess context object)
5. For cloud TCP, that callback is `TCPClient_SendData` (FUN_ram_4200db40)

### How 0xC2 Frames Are Built

The dongle does NOT build 0xC2 frames from scratch. Instead:

1. **RS485 reads** produce raw Modbus RTU responses (slave_addr + func + byte_count + data + CRC16)
2. The response bytes are **wrapped verbatim** in a 0xA1/0x1A frame with func=0xC2
3. The frame is sent to ALL active transports (cloud TCP, local TCP, BLE)

This is confirmed by the `DataProcessRecv_Generic` (0x4200b422) function, which shows the **receive** side: when a 0xC2 frame arrives from any source, `parse_DATA_TRANSMISSION` extracts the payload, then `RS485_SendToInverter` (FUN_ram_4200adaa) forwards it to RS485. The exact same data flows in reverse for the **send** path.

---

## 2. Exact Frame Format

### 0xA1/0x1A Frame Structure

```
Offset  Size  Field              Value/Notes
------  ----  -----              -----------
0       2     Magic              [A1 1A] (always)
2       2     Version            [01 00] (version 1, little-endian)
4       2     Frame Length        total_size - 6 (little-endian)
6       1     Address            [01] (always 1)
7       1     Function           [C1|C2|C3|C4]
8       10    Serial             10 ASCII digits, zero-padded
18+     var   Payload            (depends on function)
last-2  2     CRC-16/Modbus      Over bytes [6..last-3] (addr through payload)
```

**Frame length field**: Counts bytes from offset 6 to end, inclusive.
So `frame_length = 1 (addr) + 1 (func) + 10 (serial) + payload_len + 2 (CRC) = payload_len + 14`

**CRC scope**: Computed over `frame[6:-2]` (address byte through end of payload, excluding CRC itself).

### Heartbeat (0xC1) — 21 bytes total

```
[A1 1A] [01 00] [0D 00] [01] [C1] [serial x10] [05] [CRC_lo CRC_hi]
  0-1     2-3     4-5     6    7     8-17         18      19-20
```

- `frame_length` = 0x000D (13) → total = 6 + 13 = 19 bytes for inner + 2 CRC = 21 total
- Wait — let me re-verify from HeartbeatBuilder (FUN_ram_4200c3b8):

```c
iVar1 = FUN_ram_4200c216(param_1, 0xc1);  // Returns 0x12 (18)
*(param_1 + iVar1) = 5;                    // Status byte at offset 18
*(param_1 + 4) = (char)((iVar1 - 5) * 0x10000 >> 0x10);  // frame_len low
*(param_1 + 5) = (char)((iVar1 - 5) >> 8);                // frame_len high
return iVar1 + 1;  // Returns 19
```

So: `iVar1 = 18` (preamble size), `frame_len = 18 - 5 = 13 = 0x0D`, total returned = 19.
But wait — CRC is NOT added by HeartbeatBuilder. CRC must be added by the caller or DataProcess_Send.

**CRC addition**: The DataProcess_Send function (FUN_ram_42009c02) calls the send callback with `(param_1, param_1 + 0x427, param_2)` where param_2 is the size. CRC must be added by an intermediate function — likely `FramePreambleBuilder` adds a placeholder, and CRC is computed/appended before TCP send. Looking at `Heartbeat_Send` (0x42009dc0):

```c
FUN_ram_4200c3b8(param_1 + 0x427, 0x400);  // Build heartbeat in send buffer
FUN_ram_42009c02(param_1, result);          // Send via DataProcess_Send
```

The heartbeat is built in the DataProcess send buffer (offset 0x427, size 0x400=1024). CRC must be appended by the TCP send path.

**Corrected heartbeat**: 19 bytes from builder + 2 CRC = **21 bytes total** (not 19 as previously stated in FINDINGS.md — the 19 was the builder return value before CRC).

Actually — re-reading HeartbeatBuilder more carefully: `frame_len = iVar1 - 5 = 13`. Frame length field at [4:6] = 0x000D. Total frame = 6 + 13 = 19 bytes. The status byte IS included in frame_len. But CRC... The frame_len likely INCLUDES the CRC bytes. Let me reconsider.

Looking at `FramePreambleBuilder`:
```c
return 0x12;  // 18 = magic(2) + version(2) + length(2) + addr(1) + func(1) + serial(10)
```

And HeartbeatBuilder adds status byte: total before CRC = 19 bytes.
`frame_len = 19 - 6 = 13` → stored at [4:6].
CRC added after = 21 bytes total.
`frame_len_with_crc = 21 - 6 = 15` → but that doesn't match 0x0D=13.

**Resolution**: Looking at how `DataProcess_ResponseBuilder` sets frame_length:
```c
iVar1 = FUN_ram_4200c216(param_1, 0xc3);  // Returns 18
// ... adds payload ...
param_6 = payload_len + iVar1 + 4;        // Total including payload header
iVar1 = param_6 - 6;                       // frame_length = total - 6
*(param_1 + 4) = low_byte(iVar1);
*(param_1 + 5) = high_byte(iVar1);
return param_6;                             // Return total (WITHOUT CRC)
```

So `frame_length` = bytes from offset 6 to end of payload (BEFORE CRC). CRC is appended later. This means:

**Heartbeat**: frame_length = 13, total before CRC = 19, **total with CRC = 21 bytes**
**But the wire format needs confirmation via traffic capture.**

### Data Transmission (0xC2) — Variable size

```
[A1 1A] [01 00] [frame_len LE] [01] [C2] [serial x10] [Modbus RTU response...] [CRC_lo CRC_hi]
  0-1     2-3       4-5          6    7     8-17          18+                       last 2
```

**Modbus RTU response payload**:
```
[slave_addr=01] [func_code] [byte_count] [register_data...] [modbus_CRC_lo modbus_CRC_hi]
```

For a READ_HOLDING (func=0x03) response with 80 registers (160 bytes):
```
[01] [03] [A0] [reg0_hi reg0_lo ... reg79_hi reg79_lo] [CRC_lo CRC_hi]
  1    1    1              160 bytes                          2
Total Modbus RTU: 165 bytes
```

Total frame = 18 (preamble) + 165 (Modbus RTU) + 2 (cloud CRC) = **185 bytes**

For a READ_INPUT (func=0x04) response with 127 registers (254 bytes):
```
[01] [04] [FE] [reg0_hi reg0_lo ... reg126_hi reg126_lo] [CRC_lo CRC_hi]
  1    1    1              254 bytes                            2
Total Modbus RTU: 259 bytes
```

Total frame = 18 + 259 + 2 = **279 bytes**

---

## 3. Register Read Sequence Per Poll Cycle

### Group Table (DROM @ 0x3c0ea62c)

The register group table has 3 entries, each 14 bytes (7 × 2-byte fields):

| Index | Group Type | Holding Start | Holding End | Holding Chunk | Input Start | Input End | Input Chunk |
|-------|-----------|---------------|-------------|---------------|-------------|-----------|-------------|
| 0     | 5         | 0             | 80          | 80            | 0           | 381       | 127         |
| 1     | 4         | 0             | 80          | 80            | 0           | 381       | 127         |
| 2     | 2         | 0             | 80          | 40            | 0           | 120       | 40          |

**Table layout** (14 bytes per entry):
```
Offset  Field
0x00    group_type (2 bytes)        = (&DAT_ram_3c0ea62c)[group_idx * 7]
0x02    holding_chunk_size (1 byte) = (&DAT_ram_3c0ea62e)[group_idx * 0xe]
0x04    holding_start (2 bytes)     = *(&DAT_ram_3c0ea630 + group_idx * 0xe)
0x06    holding_end (2 bytes)       = *(&DAT_ram_3c0ea632 + group_idx * 0xe)
0x08    input_chunk_size (1 byte)   = (&DAT_ram_3c0ea634)[group_idx * 0xe]
0x0A    input_start (2 bytes)       = *(&DAT_ram_3c0ea636 + group_idx * 0xe)
0x0C    input_end (2 bytes)         = *(&DAT_ram_3c0ea638 + group_idx * 0xe)
```

### Group Selection Logic (from RS485_DataCallback)

```c
// Reading holding register 26 (offset 0x35 in response = byte 53 = reg 26 value)
uVar1 = *(ushort *)(param_2 + 0x35);  // value of holding register 26
_DAT_ram_3fc99bc4 = (uint)((uVar1 >> 1 & 0xf) == 5);  // 0 if type==5, else stays current
```

This means:
- Read holding register 26 from inverter
- Extract bits [4:1] (shift right 1, mask 0xF)
- If == 5: use group 0 (type 5)
- Otherwise: use group 1 (type 4, the default)

**For EG4 inverters**: The group is determined by the inverter's device type register. EG4 12kPV/18kPV/FlexBOSS typically use group 1 (type 4). Traffic capture will confirm.

### Complete Poll Cycle Sequence (Groups 0 and 1)

When the poll timer fires (`PollTimerCallback`), the following reads are issued sequentially:

**Phase 1: Holding registers** (FUN_ram_4200ac04, only if `DAT_ram_3fc99ba4 == 1`)
1. READ_HOLDING registers 0-79 (chunk size 80) — 1 request

**Phase 2: Input registers** (FUN_ram_4200acca, always)
2. READ_INPUT registers 0-126 (chunk size 127) — 1 request
3. READ_INPUT registers 127-253 (chunk size 127) — 1 request
4. READ_INPUT registers 254-380 (chunk size 127) — 1 request

After input reads complete, flags are set:
- `DAT_ram_3fc99ba7 = 1` (all input reads done)
- `DAT_ram_3fc99ba6 = 0` (battery read not in progress)

**Phase 3: Battery data** (conditional, in State 4)
5. READ_INPUT registers 5000-5126 (count 127) — 1 request
   - Only if: `_DAT_ram_3fc99bc8 != _DAT_ram_3fc99bd2` (cycle counter mismatch)
   - AND: `(_DAT_ram_3fc9a000 & 0x100) != 0` (status bit set)
   - AND: `group_type` is 4 or 5 (groups 0 or 1 only)
   - Uses callback `LAB_ram_4200aaec` (DataReadyCallback)

**Phase 4: LED/Status registers** (periodic, in State 4)
6. READ_INPUT register 0xEE (238), count 1 — LED status
   - Callback: `LAB_ram_4200aa4a` (StatusCallback)
   - Only when `gp + -0x7b0 == 1` (a flag is set)

7. WRITE_SINGLE register 0x10EE (4334), value = bitmask — Status report
   - Every 30 seconds (`29999 < elapsed`)
   - Bitmask: bit 0 = WiFi connected, bit 1 = cloud connected, bit 2 = RS485 connected
   - Callback: `LAB_ram_4200aa4a` (StatusCallback)

### Summary: Frames Sent Per Poll Cycle

For groups 0/1, each poll cycle sends to cloud:

| # | Direction | Function | Modbus Func | Register Range | Payload Size |
|---|-----------|----------|-------------|----------------|-------------|
| 1 | dongle→cloud | 0xC2 | 0x03 READ_HOLDING | 0-79 (80 regs) | 165 bytes |
| 2 | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 0-126 (127 regs) | 259 bytes |
| 3 | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 127-253 (127 regs) | 259 bytes |
| 4 | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 254-380 (127 regs) | 259 bytes |
| 5* | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 5000-5126 (127 regs) | 259 bytes |

*Frame 5 is conditional — only sent when battery cycle counter changes

---

## 4. Battery Data Round-Robin Mechanism

### Discovery

The battery data read at register 5000 is **NOT a round-robin**. It's a **single bulk read** of 127 input registers starting at address 5000. The condition for triggering this read is:

```c
// In RS485App_MainHandler, State 4 (DATA_READY):
if (DAT_ram_3fc99ba4 == '\0') {  // Not in first-poll mode
    if ((_DAT_ram_3fc99bc8 != _DAT_ram_3fc99bd2)  // Cycle counter mismatch
        && ((_DAT_ram_3fc9a000 & 0x100) != 0)      // Status bit 8 is set
        && ((ushort)(group_type - 4) < 2))           // Group is 0 or 1
    {
        _DAT_ram_3fc99bc8 = _DAT_ram_3fc99bd2;     // Sync counters
        // Read input registers 5000-5126
        BuildPacket(buf, 0x20, 0, 4/*READ_INPUT*/, slave_addr, 5000, 0x7f/*127*/);
        RS485Service_SendMessage(rs485_handle, &callback);
        DAT_ram_3fc99ba6 = 1;  // Mark battery read in progress
    }
}
```

**Key observations**:
1. `_DAT_ram_3fc99bd2` appears to be incremented elsewhere (likely in the DataReadyCallback when input reads complete)
2. `_DAT_ram_3fc99bc8` tracks the last battery read cycle
3. Battery data is read **once per poll cycle** (when counters diverge)
4. Register 5000 is the start of individual battery data in EG4 inverters
5. The 127-register read covers battery cells, temperatures, and per-pack data
6. Status bit `0x100` in `_DAT_ram_3fc9a000` must be set — this likely indicates "inverter has battery data available"

### Battery Read Timing

The battery read happens in State 4 BEFORE the poll timer check. So the sequence within State 4 is:

1. Check if battery read needed (cycle counter mismatch)
2. If yes: issue battery read, set `DAT_ram_3fc99ba6 = 1`, return (wait for next iteration)
3. If no (or battery read done): check poll timer
4. If timer expired: issue holding + input reads (next poll cycle)

This means battery data is read between poll cycles, not during them. The battery data from the *previous* poll cycle's read is what gets forwarded.

---

## 5. All Timing Intervals

### From Decompiled Firmware

| Parameter | Value | Source Function | Notes |
|-----------|-------|-----------------|-------|
| **Data poll interval** | `NVS_GetParam(0) * 1000` ms | RS485App_MainHandler (line 457) | Default NVS key 0 = 1, so default = 1000ms. But cloud uses `data_period * 100` interpretation |
| **Heartbeat trigger** | 18000 ms (18 seconds) | HeartbeatTimer (0x4200a506, line 720) | `17999 < (now - last_recv_time)` |
| **Heartbeat timeout** | 19000 ms (19 seconds) | HeartbeatTimer (0x4200a506, line 729) | `18999 < (now - last_recv_time)` → disconnect |
| **Connect timeout** | 1000 ms (1 second) | HeartbeatTimer (0x4200a506, line 710) | `999 < (now - piVar1[4])` → abort connection |
| **Status write interval** | 30000 ms (30 seconds) | RS485App_MainHandler (line 320) | `29999 < elapsed` → write status to reg 0x10EE |
| **Stale data timeout** | 600000 ms (10 minutes) | RS485App_MainHandler (line 290) | `600000 < elapsed` → reset RS485 state |
| **Battery read cooldown** | 20000 ms (20 seconds) | RS485App_MainHandler (line 411) | `20000 < elapsed` → clear battery busy flag |
| **RS485 response timeout** | 100 ms | DROM @ 0xa460 | From RS485 configuration |
| **RS485 retry delay** | 1000 ms | DROM @ 0xa460 | Between retries |
| **RS485 max retries** | 10 | DROM @ 0xa460 | Before giving up |
| **RS485 baud rate** | 19200 | DROM @ 0xa460 | 8N1 |

### Heartbeat Logic Detail (from HeartbeatTimer 0x4200a506)

```c
void FUN_ram_4200a506(param_1) {
    piVar1 = FUN_ram_4200dbd8();  // Get TCP client state

    if (*piVar1 == 1) {  // State: CONNECTING
        elapsed = now - piVar1[4];
        if (elapsed > 999) {  // 1 second connect timeout
            *piVar1 = 0;     // Back to IDLE
            FUN_ram_4200dc58(param_1);  // Close socket
        }
    }
    else if (*piVar1 == 2) {  // State: CONNECTED
        data_period = NVS_GetParam(0);

        // Heartbeat send conditions:
        // 1. No data sent recently: now - last_recv_time > 17999 (18s)
        // 2. OR: aging mode complete AND data_period timer expired
        if ((piVar1[1] == 0 && now - piVar1[4] > 17999) ||
            (_DAT_ram_3fc99b60 == 0 && now - _DAT_ram_3fc99ba0 > data_period * 100000 / 1000)) {
            _DAT_ram_3fc99ba0 = now;
            FUN_ram_42009dc0(piVar1[3]);  // Send heartbeat
            piVar1[1] = 1;               // Mark heartbeat sent
        }

        // Heartbeat timeout: no response in 19s → reconnect
        if (now - piVar1[4] > 18999) {
            *piVar1 = 0;
            FUN_ram_4200dc58(param_1);    // Close socket
            FUN_ram_42009dc0(piVar1[3]);  // Send final heartbeat (attempt)
        }
    }
}
```

**Critical detail**: The heartbeat is sent when `piVar1[1] == 0` (no heartbeat pending) AND 18 seconds have elapsed since last receive. `piVar1[4]` is the timestamp of the last received data from the cloud. The timeout (19 seconds) is measured from the same base.

The second heartbeat condition (`_DAT_ram_3fc99b60 == 0`) relates to the aging/factory test mode. Under normal operation, the first condition (18-second silence) is what triggers heartbeats.

### Data Period Interpretation

The `data_period` NVS parameter (key 0, default 1) controls the RS485 poll timer:

- **RS485 poll timer**: `data_period * 1000` ms (line 457: `local_50 * 1000`)

With factory default `data_period = 1`:
- RS485 polls every **1 second** (1 * 1000 = 1000ms) — this is the pre-configuration state

**But the cloud reconfigures it**: SET_PARAM code=0 (from `SetParam_ForwardToRS485` at 0x4200a064) accepts a value in range **20-300** (validated: `value - 0x14 < 0x119`, i.e., 20 ≤ value ≤ 300). This is stored to NVS key 0.

After cloud configuration:
- `data_period=60`: polls every **60 seconds**
- `data_period=100`: polls every **100 seconds**
- `data_period=300`: polls every **5 minutes** (maximum)

The alternative heartbeat condition (`data_period * 100000 / 1000 = data_period * 100` seconds) in the HeartbeatTimer is **only for aging/factory test mode** (`_DAT_ram_3fc99b60 == 0`). Under normal operation, only the 18-second silence heartbeat applies.

### No Buffering — Immediate Forwarding

The dongle does **NOT buffer** register data. Each RS485 response is immediately wrapped in a 0xC2 frame and sent to the cloud TCP socket. The DataProcess send buffer is only 1024 bytes — there's no room for aggregation.

Per poll cycle, 4-5 frames are sent to the cloud in a **burst** (back-to-back within ~400ms, as RS485 responses arrive at ~100ms each), then silence until the next poll timer fires.

**For CloudEmitter**: We must:
1. Send data in bursts (4-5 frames back-to-back), not spread over time
2. Default to whatever `data_period` the traffic capture reveals
3. Handle SET_PARAM code=0 from the cloud to update our interval
4. The initial `data_period=1` factory default is irrelevant — the cloud will reconfigure us

---

## 6. Cloud Server Response Behavior

### From DataProcessRecv_TCPClient (0x4200a688)

When the cloud server sends frames to the dongle:

| Cloud Frame | Dongle Action |
|-------------|---------------|
| 0xC1 Heartbeat | Increment counter `DAT_ram_3fc99b9d`, log, **NO echo** |
| 0xC2 Data | Parse payload, forward to RS485 (Modbus write to inverter) |
| 0xC3 GET_PARAM | Parse start/end params, issue fresh register read |
| 0xC4 SET_PARAM | Parse param_code + data, handle (see SET_PARAM table) |

**Heartbeat response behavior**:
- Cloud heartbeats are counted (`DAT_ram_3fc99b9d++`)
- After 8+ heartbeats AND 8+ data cycles (`DAT_ram_3fc99bcf`), set `_DAT_ram_3fc99b60 = 1` (aging complete)
- This aging flag is saved to NVS key 10

**Key: Cloud does NOT echo heartbeats.** The dongle sends heartbeats unilaterally on a timer. The cloud may send its own heartbeats, but the dongle just counts them.

---

## 7. Connection Lifecycle

```
1. TCP connect to us2.solarcloudsystem.com:4346 (1s timeout)
2. On connect (TCPClient_OnConnect, 0x4200a884):
   - Set state to CONNECTED (2)
   - Send heartbeat (19-byte 0xC1 frame + CRC)
   - This is the ONLY authentication — serial in heartbeat
3. Main loop:
   - Poll timer fires every data_period*1000 ms (default 1s):
     - Read holding regs 0-79
     - Read input regs 0-380 (3 chunks of 127)
     - Read battery data at reg 5000 (conditional)
   - Each RS485 response triggers 0xC2 frame send to cloud
   - Heartbeat every 18s of silence
   - If no cloud response in 19s → disconnect and reconnect
4. On disconnect:
   - Close socket
   - Set state to IDLE (0)
   - Will reconnect on next HeartbeatTimer iteration
```

---

## 8. Implications for CloudEmitter

### What We Must Match Exactly

1. **Frame format**: 0xA1 0x1A prefix, version [01 00], correct frame_length, addr=1, CRC-16/Modbus
2. **Heartbeat**: func=0xC1, status byte=0x05, correct serial, send on connect and every <18s
3. **Data frames**: func=0xC2, payload = verbatim Modbus RTU response (slave_addr + func + byte_count + data + modbus_CRC)
4. **Register ranges**: Match the group table exactly (holding 0-79, input 0-126, 127-253, 254-380)
5. **Battery data**: Input registers 5000-5126 when available
6. **Timing**: ~100 seconds between poll cycles, heartbeats within 18s of silence

### What We DON'T Need to Match

1. **RS485 timing** — we read from cached register snapshot, not actual RS485
2. **LED/status writes** — reg 0xEE and 0x10EE are dongle-internal status
3. **Aging/factory test** — NVS key 10 logic is for factory QC
4. **Group auto-detection** — we know our inverter type, hardcode group 1 (type 4)

### Risk Assessment

**LOW RISK** — The cloud server is a data ingestion endpoint that:
- Authenticates only by serial number (heartbeat on connect)
- Accepts raw Modbus RTU data without validation (it's a transparent bridge)
- Expects standard frame format (which pylxpweb already implements)
- Has no handshake or challenge-response
- Times out after 19s of silence (just send heartbeats)

**Potential ban triggers to avoid**:
- Sending malformed frames (bad CRC, wrong frame_length)
- Sending data from unknown serial (must use registered dongle serial)
- Sending at abnormal rates (much faster or slower than 100s intervals)
- Sending Modbus RTU data with impossible values (CRC mismatch in Modbus payload)

---

## 9. Open Questions (for traffic capture validation)

1. **Exact CRC placement**: Is CRC appended to the frame before or after frame_length is set? The builder functions return size WITHOUT CRC, but the send path must add it. Traffic capture will show the exact wire format.

2. **Frame ordering**: Are all 4-5 data frames sent back-to-back, or is there a delay between them? The RS485 reads are sequential (wait for response before next read), so there's inherent delay.

3. **Battery data frequency**: Is battery data sent every cycle or only periodically? The cycle counter mechanism suggests it may skip some cycles.

4. **Cloud acknowledgment**: Does the cloud send anything back after receiving data frames? If so, what?

5. **Version field**: Is it always [01 00] or does it change between firmware versions?

6. **Holding register read gating**: `DAT_ram_3fc99ba4` controls whether holding registers are read in the poll cycle. When is this flag set/cleared? First iteration only?
