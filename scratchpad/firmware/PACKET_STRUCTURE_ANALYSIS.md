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

1. The callback receives the raw extended Modbus response bytes (271 bytes for 127 regs)
2. It forwards verbatim to 3 transports (cloud, local TCP, BLE) via `FUN_ram_42009df6`
3. `FUN_ram_42009df6` wraps in 0xC2 frame: `FramePreambleBuilder(0xC2)` + 2-byte LE length + raw data
4. Calls `DataProcess_Send` (FUN_ram_42009c02) which invokes the transport-specific send callback
5. For cloud TCP, that callback is `TCPClient_SendData` (FUN_ram_4200db40)

### How 0xC2 Frames Are Built (UPDATED 2026-02-24)

**Key Discovery**: The inverters use a **proprietary extended Modbus protocol**, NOT standard
Modbus RTU. Both request and response embed a 10-byte inverter serial.

1. **RS485 reads** produce extended Modbus responses (271 bytes for 127 input regs):
   `[slave 0x01][func][serial 10B][start_reg 2B LE][byte_count][data...][CRC16 2B]`
2. `RS485_DataReadyCallback` (0x4200aaec, 48 bytes) is pure forwarding — NO transformation
3. It calls `FUN_ram_42009df6` on each transport handle with the raw response data
4. `FUN_ram_42009df6` (62 bytes) wraps in 0xC2 frame: 18-byte preamble + 2-byte LE modbus_len + raw data
5. Frame is sent to ALL active transports (cloud TCP, local TCP, BLE)

**Decompiled RS485_DataReadyCallback** (from GhidraForceDecompile.java):
```c
void RS485_DataReadyCallback(undefined4 param_1, undefined4 param_2, int param_3) {
    if (param_3 != 0) {
        FUN_ram_4200a8a2(param_2, param_3);  // Cloud (if state==2)
        FUN_ram_4200b6ee(param_2, param_3);  // Local TCP (if client exists)
        FUN_ram_4200935a(param_2, param_3);  // BLE (always)
    }
}
```

**Transport Forward Functions** (from GhidraTransportForward.java):
- Cloud (0x4200a8a2, 42B): Gates on `_DAT_ram_3fc96b1c == 2` (connected)
- Local (0x4200b6ee, 38B): Gates on `_DAT_ram_3fc96b58 != 0` (client exists)
- BLE (0x4200935a, 28B): Always forwards (no gate)

All three call `FUN_ram_42009df6(transport_handle, data_ptr, data_len)`.

**rs485_service_task Response Validation** (0x4200c4cc, 1252 bytes):
```c
if (iVar2 == 0x10f) {            // Response == 271 bytes
    if (pcVar3[1] == '\x04') {   // func == READ_INPUT
        if (pcVar3[0xe] == -2) { // byte_count == 0xFE (254)
            cVar8 = pcVar3[0xc]; // start_reg_lo
            // Dispatch based on start register range:
            // 0x0000 = input 0-126 (extracts battery_count)
            // 0x00FE = input 254+
            // 0x1388 = battery 5000+
```

---

## 2. Exact Frame Format

### 0xA1/0x1A Frame Structure (TCP Cloud Transport)

**IMPORTANT**: CRC-16 is NOT used on TCP cloud frames. See Section 11 for full evidence.

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
                                 *** NO TRAILING CRC ***
```

**Frame length field**: Counts bytes from offset 6 to end of payload, inclusive.
So `frame_length = 1 (addr) + 1 (func) + 10 (serial) + payload_len = payload_len + 12`
And `total_size = 6 + frame_length = 18 + payload_len`

### Heartbeat (0xC1) — 19 bytes total

```
[A1 1A] [01 00] [0D 00] [01] [C1] [serial x10] [05]
  0-1     2-3     4-5     6    7     8-17         18
```

- `frame_length` = 0x000D (13) → total = 6 + 13 = **19 bytes**
- From HeartbeatBuilder (FUN_ram_4200c3b8):

```c
iVar1 = FUN_ram_4200c216(param_1, 0xc1);  // Returns 0x12 (18) — preamble
*(param_1 + iVar1) = 5;                    // Status byte at offset 18
*(param_1 + 4) = (char)((iVar1 - 5) * 0x10000 >> 0x10);  // frame_len low = 13
*(param_1 + 5) = (char)((iVar1 - 5) >> 8);                // frame_len high = 0
return iVar1 + 1;  // Returns 19 — this IS the final send size
```

DataProcess_Send passes this 19 directly to TCPClient_SendData → send(). No CRC added.

**Traffic capture should confirm: heartbeat = exactly 19 bytes (no trailing CRC).**

### Data Transmission (0xC2) — Variable size

```
[A1 1A] [01 00] [frame_len LE] [01] [C2] [serial x10] [modbus_len LE] [Modbus RTU response...]
  0-1     2-3       4-5          6    7     8-17           18-19          20+
```

**Note**: 0xC2 has a 2-byte LE length prefix at offset 18-19 before the Modbus RTU data.
This was confirmed by `parse_DATA_TRANSMISSION` (0x4200c402) which reads `modbus_len` at
`payload + 0x12` (offset 18 from frame start) and validates `modbus_len + 0x14 == frame_len`.

**Extended Modbus response payload** (inside the 0xC2 frame):

**IMPORTANT**: LuxPower/EG4 inverters use a proprietary EXTENDED Modbus format, NOT standard
Modbus RTU. The extended format embeds a 10-byte inverter serial in both request and response.

**Extended Modbus Request** (18 bytes, built by BuildPacket at 0x4200de8c):
```
[slave=01] [func] [serial x10] [start_reg 2B LE] [count 2B LE] [CRC16 2B]
    1        1        10             2                 2             2     = 18 bytes
```

**Extended Modbus Response** (271 bytes for 127 input regs):
```
[slave=01] [func] [serial x10] [start_reg 2B LE] [byte_count] [data...] [CRC16 2B]
    1        1        10             2               1          254          2     = 271 bytes
```

For a READ_HOLDING (func=0x03) response with 80 registers (160 bytes):
```
[01] [03] [serial x10] [start_reg 2B LE] [A0] [reg_data x160] [CRC_lo CRC_hi]
  1    1      10              2              1       160               2
Total extended Modbus: 177 bytes
```

Total 0xC2 frame = 18 (preamble) + 2 (modbus_len) + 177 = **197 bytes**

For a READ_INPUT (func=0x04) response with 127 registers (254 bytes):
```
[01] [04] [serial x10] [start_reg 2B LE] [FE] [reg_data x254] [CRC_lo CRC_hi]
  1    1      10              2              1       254               2
Total extended Modbus: 271 bytes (0x10F)
```

Total 0xC2 frame = 18 + 2 + 271 = **291 bytes**

Note: The CRC-16/Modbus within the extended response is computed over the entire extended
frame (slave + func + serial + start_reg + byte_count + data = 269 bytes for input regs),
NOT just the standard Modbus fields.

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

**Holding registers (cloud-initiated reads):**

| # | Direction | Function | Modbus Func | Register Range | Extended Response | 0xC2 Frame |
|---|-----------|----------|-------------|----------------|-------------------|------------|
| 1 | cloud→dongle | 0xC2 | 0x03 READ_HOLDING | 0-126 (127 regs) | 18 bytes (request) | 38 bytes |
| 2 | cloud→dongle | 0xC2 | 0x03 READ_HOLDING | 127-253 (127 regs) | 18 bytes (request) | 38 bytes |
| 3 | cloud→dongle | 0xC2 | 0x03 READ_HOLDING | 240-366 (127 regs) | 18 bytes (request) | 38 bytes |

Each request generates a 291-byte response (271-byte extended Modbus response).

**Input registers (dongle-initiated autonomous push):**

| # | Direction | Function | Modbus Func | Register Range | Extended Response | 0xC2 Frame |
|---|-----------|----------|-------------|----------------|-------------------|------------|
| 1 | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 0-126 (127 regs) | 271 bytes | 291 bytes |
| 2 | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 127-253 (127 regs) | 271 bytes | 291 bytes |
| 3 | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 254-380 (127 regs) | 271 bytes | 291 bytes |
| 4* | dongle→cloud | 0xC2 | 0x04 READ_INPUT | 5000-5126 (127 regs) | 271 bytes | 291 bytes |

*Frame 4 is conditional — only sent when battery cycle counter changes

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

**UPDATED (pcap 2026-02-24): Cloud DOES echo heartbeats.** The dongle sends heartbeats,
and the cloud echoes them back with the same status byte (~20ms later). The firmware
code only counts received heartbeats (no special echo handling), so this echo serves
as a keepalive confirmation. The dongle uses receipt of ANY frame to reset its 18s
heartbeat timer.

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

1. **Frame format**: 0xA1 0x1A prefix, version [01 00], correct frame_length, addr=1, NO trailing CRC
2. **Heartbeat**: func=0xC1, status byte=0x05, correct serial, send on connect and every <18s
3. **Data frames**: func=0xC2, payload = `[modbus_len 2B LE][extended_modbus_response...]`
   - Extended response includes 10-byte inverter serial embedded at offset 2-11
   - CRC-16/Modbus is part of the extended response (NOT on the 0xA1 frame wrapper)
4. **Register ranges**: Match the group table exactly (holding 0-79, input 0-126, 127-253, 254-380)
5. **Battery data**: Input registers 5000-5126 when available
6. **Timing**: ~100 seconds between poll cycles, heartbeats within 18s of silence
7. **Extended Modbus format**: 271-byte responses (not standard 259-byte Modbus RTU)

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

## 9. Receive-Side Behavior (Cloud → Dongle)

### TCP Client Architecture

The TCP client runs as an FreeRTOS task spawned by `TCPClient_Start` (0x4200dd3e). The main loop
lives in `FUN_ram_4200d67c` (1182 bytes) and follows a standard BSD socket pattern:

```
TCPClient_Start
  └── xTaskCreate(FUN_ram_4200d67c, "tcp_client", stack=0x1000, priority=5)

FUN_ram_4200d67c (main loop — runs forever):
  do {
    1. Wait for WiFi STA connected (poll callback every 1000ms)
    2. DNS resolution: getaddrinfo(host, port_str)
    3. socket(AF_INET, SOCK_STREAM, 0)
    4. setsockopt: TCP_NODELAY=1, SO_KEEPIDLE=60, SO_KEEPINTVL=5, SO_KEEPCNT=3
    5. connect(socket, addr)
    6. On success:
       - Set state: connected=1, alive=1
       - Call OnConnect callback (sends initial heartbeat)
       - Allocate recv buffer: malloc(max_recv_size + 1)
       - Enter recv loop:
         while (connected) {
           select(socket, timeout=100ms)
           if (readable) {
             bytes = recv(socket, buffer, max_recv_size)
             if (bytes <= 0) → break (disconnect)
             Log: "Recv: " + hex dump
             Call recv_callback(tcp_client, buffer, bytes)  // → frame parser
           }
           // Check if host/port changed → reconnect if so
         }
       - Free recv buffer
    7. On failure:
       - Sleep: connect_timeout * 100 / 1000 ms
    8. Close socket, loop back to step 1
  } while (true);
```

### Socket Configuration (from line 5746-5753)

```c
// TCP_NODELAY = 1 (disable Nagle algorithm)
setsockopt(socket, IPPROTO_TCP/*0xfff*/, TCP_NODELAY/*8*/, &one, 4);
// SO_KEEPIDLE = 60 seconds (idle before first keepalive)
setsockopt(socket, SOL_SOCKET/*6*/, SO_KEEPIDLE/*3*/, &sixty, 4);
// SO_KEEPINTVL = 5 seconds (between keepalives)
setsockopt(socket, SOL_SOCKET/*6*/, SO_KEEPINTVL/*4*/, &five, 4);
// SO_KEEPCNT = 3 (keepalive probes before disconnect)
setsockopt(socket, SOL_SOCKET/*6*/, SO_KEEPCNT/*5*/, &three, 4);
```

**CloudEmitter implication**: We should set the same socket options, especially TCP_NODELAY.

### Receive Callback Chain

```
Raw TCP recv(buffer, len)
  └── param_1[0] callback = FUN_ram_4200a66a (30 bytes, registered via PTR_FUN_ram_4200a66a)
        └── Frame parser (extracts 0xA1/0x1A frames from TCP stream)
              └── DataProcessRecv_TCPClient (FUN_ram_4200a688)
                    ├── 0xC1: Count heartbeat, check aging, NO echo
                    ├── 0xC2: parse_DATA_TRANSMISSION → RS485_SendToInverter
                    ├── 0xC3: parse_GET_PARAM → GetParam_ForwardToRS485
                    └── 0xC4: parse_SET_PARAM → SetParam_ForwardToRS485
```

**Key observation**: The TCP recv gives raw bytes to a registered callback. This callback
(`FUN_ram_4200a66a`, 30 bytes — confirmed thin wrapper in decompiled_missing.c) gets the
DataProcess context from `TCPClient_GetState()` at offset 0x0C, then calls
`DataProcess_FrameParser` (FUN_ram_42009c16, 426 bytes). The frame parser is a byte-by-byte
streaming state machine with 5 states and a 500ms idle timeout (see Section 10). It does
**NOT validate CRC** — it dispatches frames purely based on the frame_length field.
On frame completion, it calls `DataProcessRecv_TCPClient` via the callback at offset 0x04
of the DataProcess context, with `(dp_ctx, func_code, buffer_ptr)`.

### Frame Reception State Machine

The `DataProcessRecv_TCPClient` (0x4200a688, 508 bytes) is the cloud TCP dispatch function.
On EVERY received frame:

```c
void DataProcessRecv_TCPClient(dp_ctx, func_code, payload_ptr, payload_len) {
    piVar1 = get_connection_state();

    // 1. Force state to CONNECTED on any received frame
    if (*piVar1 != 2) { *piVar1 = 2; }

    // 2. Reset heartbeat pending flag
    piVar1[1] = 0;

    // 3. Stamp last-receive time (used by HeartbeatTimer for timeout)
    piVar1[4] = get_tick_count();

    // 4. Dispatch by function code
    switch (func_code) { ... }
}
```

**Critical for CloudEmitter**: ANY received frame resets the heartbeat timer. This means:
- If the cloud sends us frames (commands, heartbeats), we don't need to send heartbeats
- The 18-second heartbeat trigger is relative to `piVar1[4]` (last receive time)
- The 19-second timeout is also relative to `piVar1[4]`
- If the cloud goes silent for >19s, the dongle disconnects and reconnects

### OnConnect Callback (0x4200a884)

```c
void TCPClient_OnConnect(tcp_client, buffer, len) {
    dp_ctx = get_dataprocess_context();
    // Send pre-built data from dp_ctx offset 0x08
    TCPClient_SendData(*(dp_ctx + 8), buffer, len);
}
```

This is only 30 bytes. It calls `TCPClient_SendData` with data from the DataProcess context at
offset 0x08. This appears to be a pending buffer — the HeartbeatTimer likely pre-builds the
heartbeat into this buffer, so OnConnect sends whatever is already queued.

**Alternative interpretation**: Looking at `DataProcess_Create` (0x4200a494):
```c
memcpy(dp_ctx, callbacks, 8);  // Copy OnConnect + OnRecv function pointers
```

Offset 0x08 would then be a "pending send" field, set by `HeartbeatTimer` before connect.
The OnConnect sends the initial heartbeat that was pre-built.

### 0xC1 Heartbeat Receive (Cloud → Dongle)

```c
case 0xC1:
    if (DAT_ram_3fc99b9d != 0xFF) {
        DAT_ram_3fc99b9d++;  // Increment heartbeat counter (caps at 255)
    }
    // Aging logic: after 8+ heartbeats AND 8+ data cycles, mark aging complete
    if (_DAT_ram_3fc99b60 == 0      // Not yet marked
        && DAT_ram_3fc99b9d > 8     // >8 heartbeats received
        && DAT_ram_3fc99bcf > 8)    // >8 data cycles completed
    {
        _DAT_ram_3fc99b60 = 1;
        NVS_SetParam(10, &_DAT_ram_3fc99b60, 4);  // Save aging result
    }
    // Log only — NO echo, NO response
```

**CloudEmitter implication**: We don't need to respond to cloud heartbeats. Just count them
for completeness. The aging logic is for factory QC only.

### 0xC2 Data Receive (Cloud → Dongle → Inverter)

```c
case 0xC2:
    iVar2 = parse_DATA_TRANSMISSION(payload_ptr, payload_len, &modbus_data, &modbus_len);
    if (iVar2 == 0) {
        RS485_SendToInverter(modbus_data, modbus_len, &LAB_ram_4200a4ec, dp_ctx);
    }
```

The cloud can send 0xC2 frames **to the dongle**, which forwards the Modbus RTU data to the
inverter via RS485. The callback `LAB_ram_4200a4ec` (a jump label within HeartbeatTimer)
presumably handles the RS485 response — likely forwarding it back to the cloud as another 0xC2.

**CloudEmitter implication**: If the cloud sends us a 0xC2, we need to:
1. Extract the Modbus RTU payload
2. Forward it to the inverter via our transport
3. Send the response back as a 0xC2 frame to the cloud

This is used for **firmware updates** — the cloud pushes firmware data to the inverter through
the dongle as Modbus writes. This is the cloud-orchestrated inverter firmware update path.

### 0xC3 GET_PARAM Receive (Cloud → Dongle)

#### Payload Parser (parse_GET_PARAM, 0x4200c468, 58 bytes)

```c
int parse_GET_PARAM(payload, payload_len, *start_param, *end_param) {
    if (payload == NULL || start_param == NULL || end_param == NULL) return -1;
    if (payload_len < 0x14) return -1;  // Need at least 20 bytes

    *start_param = *(uint16_t*)(payload + 0x12);  // offset 18: start param code (LE)
    if (payload_len > 0x15) {  // If at least 22 bytes
        *end_param = *(uint16_t*)(payload + 0x14);  // offset 20: end param code (LE)
    } else {
        *end_param = *start_param;  // Single param = start
    }
    return 0;
}
```

**Frame layout for GET_PARAM request from cloud**:
```
Offset in payload  Field
0x12 (18)          start_param_code (uint16 LE)
0x14 (20)          end_param_code (uint16 LE, optional — defaults to start)
```

Wait — those offsets are from the FRAME start, not the payload start. The parse functions receive
`param_3, param_4` which are the frame data pointer and frame data length from the dispatch.
Looking at the dispatch code: `FUN_ram_4200c468(param_3, param_4, &uStack_28, &uStack_24)`
where param_3/param_4 come from the frame parser. So offset 0x12 from the frame data start
means offset 18 = right after the preamble. The param codes are at the start of the payload.

**Corrected GET_PARAM payload** (after the 18-byte preamble):
```
Offset  Field
0       start_param_code (uint16 LE)
2       end_param_code (uint16 LE, optional)
```

#### Response Handler (GetParam_ForwardToRS485, 0x42009e34, 560 bytes)

This function iterates from `start_param` to `end_param`, building a response for each param code:

```c
void GetParam_ForwardToRS485(dp_ctx, start_param, end_param) {
    if (dp_ctx == 0) return -1;

    do {
        if (end_param < start_param) return 0;  // Done

        log("GetParam ParamCode=%u", start_param);

        switch (start_param) {
            case 0:   // data_period → read NVS key 0, return 2 bytes
            case 1:   // serial → read NVS key 9, return 10 bytes
            case 4:   // WiFi SSID+password → read NVS 5+6, format as CSV
            case 5:   // WiFi scan results → call FUN_ram_4200763c
            case 6:   // Cloud server → read NVS 7+8, format as CSV
            case 7:   // Firmware version → return "V2.10"
            case 8:   // OTA status → return DAT_ram_3fc99bd6 (1 byte)
            case 0x0B: // Aging status → return 5 (constant)
            case 0x0E: // WiFi password → read NVS key 2
            case 0x0F: // DHCP flag → read NVS key 4
            case 0x10: // IP config → call FUN_ram_42007774 (format IP info)
            case 0x14: // SoftAP flag → read NVS key 0x10
            default:   // Unknown → skip, increment start_param
        }

        // Build response frame:
        frame_size = DataProcess_ResponseBuilder(
            dp_ctx + 0x427,    // send buffer
            0x400,             // buffer size
            dp_ctx + 0x1C,     // serial
            start_param,       // param code
            response_data,     // data
            response_len       // length
        );
        DataProcess_Send(dp_ctx, frame_size);

        start_param++;
    } while (true);
}
```

**CloudEmitter implication**: When the cloud sends GET_PARAM, we need to respond with:
- Param 0: our configured data_period
- Param 1: our dongle serial
- Param 7: firmware version string (e.g., "V2.10")
- Param 8: OTA status (0 = idle)
- Other params: return sensible defaults or skip

The response uses `DataProcess_ResponseBuilder` (0x4200c260) which builds a 0xC3 response frame:

```
[A1 1A] [ver] [frame_len] [01] [C3] [serial x10] [param_code LE] [data_len LE] [data...] [CRC16]
```

### 0xC4 SET_PARAM Receive (Cloud → Dongle)

#### Payload Parser (parse_SET_PARAM, 0x4200c42a, 62 bytes)

```c
int parse_SET_PARAM(payload, payload_len, *param_code, *data_ptr, *data_len) {
    if (payload == NULL || data_ptr == NULL || data_len == NULL) return -1;
    if (payload_len < 0x16) return -1;  // Need at least 22 bytes

    *param_code = *(uint16_t*)(payload + 0x12);  // Param code (uint16 LE)
    data_length = *(uint16_t*)(payload + 0x14);   // Data length (uint16 LE)
    *data_len = data_length;

    if (data_length + 0x16 != payload_len) return -1;  // Length mismatch
    *data_ptr = payload + 0x16;  // Data starts at offset 22
    return 0;
}
```

**SET_PARAM payload** (after 18-byte preamble):
```
Offset  Field
0       param_code (uint16 LE)
2       data_length (uint16 LE)
4+      data bytes (data_length bytes)
```

#### Response (ACK/NACK)

After processing SET_PARAM, the handler calls `FUN_ram_4200c2e2` (96 bytes, not decompiled)
which builds a SET_PARAM response frame:

```c
// From SetParam_ForwardToRS485 (0x4200a064), at the END of each code handler:
// On success: uVar7 = 0
// On param error: uVar7 = 1
// On unknown code: uVar7 = 4
// On NVS write error: uVar7 = 3

LAB_ram_4200a094:
    frame_size = FUN_ram_4200c2e2(
        dp_ctx + 0x427,  // send buffer
        0x400,           // buffer size
        dp_ctx + 0x1C,   // serial
        param_code,      // echo back the param code
        result_code      // 0=success, 1=param error, 3=NVS error, 4=unknown code
    );
    if (frame_size > 0) {
        DataProcess_Send(dp_ctx, frame_size);
    }
```

**SET_PARAM response** (0xC4 frame with result code):
```
[A1 1A] [ver] [frame_len] [01] [C4] [serial x10] [param_code LE] [result_code] [CRC16]
```

Result codes:
- `0x00` = success
- `0x01` = parameter validation error
- `0x03` = NVS write failure
- `0x04` = unknown/unsupported param code

#### Complete SET_PARAM Code Table with Response Behavior

| Code | Purpose | Response | Notes |
|------|---------|----------|-------|
| 0 | Set data poll period | ACK(0) on success | Range 20-300, saved to NVS key 0 |
| 1 | Set dongle serial | ACK(0) on success | 10 bytes, [0-9A-Z], saved to NVS key 9 |
| 3 | Factory reset | ACK(0) | Requires byte = 0xA5, calls NVS_InitDefaults |
| 4 | Set WiFi SSID/password | ACK(0) on success | CSV: "ssid,password", saved to NVS 5+6 |
| 6 | Set cloud server | ACK(0) on success | CSV: "host,port", saved to NVS 7+8, reinit TCP |
| 9 | Dongle OTA URL | ACK(0) | Up to 200 bytes URL, triggers esp_https_ota |
| 0x0C | Set WiFi channel+pass | ACK(0) on success | CSV: "channel,password", saved to NVS 4+2 |
| 0x0D | Reboot | (no response — reboots) | Requires byte = 0xA5, calls esp_restart() |
| 0x11 | Set static IP | ACK(0) on success | CSV: "ip,gateway,mask", saves NVS 11-14 |
| 0x12 | Enable DHCP | ACK(0) on success | Requires byte = 0xA5, sets NVS key 14 |
| 0x14 | Set SoftAP flag | ACK(0) on success | 0=AP on, else=AP off, saved to NVS key 16 |
| Other | Unknown | ACK(4) | Returns "unsupported" result code |

**CloudEmitter implication**: We must:
1. Always send an ACK response for SET_PARAM (except code 0x0D reboot which doesn't respond)
2. For dongle-internal codes (0, 1, 3, 4, 6, 9, 0x0C, 0x0D, 0x11, 0x12, 0x14): ACK without action
3. For codes that ARE inverter register writes (any code not in the list above): forward to inverter
4. The response frame is func=0xC4 with param_code echoed back + result byte

**Wait — there's a subtle issue**: ALL documented SET_PARAM codes are dongle-internal. The
firmware doesn't show any code that forwards SET_PARAM to the inverter. Register writes
from the cloud to the inverter are done via 0xC2 (DATA_TRANSMISSION) which carries Modbus
write commands (func 0x06 WRITE_SINGLE or 0x10 WRITE_MULTI).

### 0xC2 for Cloud→Inverter Writes

When the cloud wants to write a register on the inverter, it sends a 0xC2 frame containing
a Modbus write command:

```
Cloud→Dongle 0xC2:
  payload = [01] [06] [reg_hi reg_lo] [value_hi value_lo] [CRC_lo CRC_hi]
            slave  WRITE_SINGLE   register        value       modbus CRC
```

The dongle forwards this verbatim to RS485 via `RS485_SendToInverter` (0x4200adaa):

```c
void RS485_SendToInverter(modbus_data, modbus_len, callback, dp_ctx) {
    rs485_handle = _DAT_ram_3fc96b30;
    if (rs485_handle == 0) return -1;

    // Allocate callback struct: [callback_func, dp_ctx, data..., data_len]
    cb_struct = malloc(modbus_len + 0x0C);
    cb_struct[0] = callback;     // LAB_ram_4200a4ec
    cb_struct[1] = dp_ctx;       // For sending response back
    memcpy(cb_struct + 3, modbus_data, modbus_len);
    cb_struct[2] = modbus_len;

    RS485Service_SendMessage(rs485_handle, cb_struct);
    free(cb_struct);
}
```

The callback `LAB_ram_4200a4ec` receives the RS485 response and presumably wraps it in a
0xC2 frame to send back to the cloud as confirmation.

**CloudEmitter implication**: If the cloud sends a 0xC2 containing a Modbus write:
1. Extract the Modbus RTU command from the payload
2. Execute it on the inverter via our transport
3. Wrap the response in a 0xC2 frame and send back to the cloud

---

## 10. Frame Parser Details

### parse_DATA_TRANSMISSION (0x4200c402, 40 bytes)

```c
int parse_DATA_TRANSMISSION(frame_data, frame_len, *payload_ptr, *payload_len) {
    if (frame_data == 0 || frame_len <= 0x12) return -1;

    // Read payload length from frame offset 0x12 (within frame data)
    modbus_len = *(uint16_t*)(frame_data + 0x12);
    *payload_len = modbus_len;

    // Verify: modbus_len + 0x14 == frame_len (payload starts at 0x14)
    if (modbus_len + 0x14 != frame_len) return -1;

    *payload_ptr = frame_data + 0x14;  // Modbus RTU data starts at offset 20
    return 0;
}
```

**0xC2 payload structure** (within the frame data passed to parser):
```
Offset  Field
0x12    modbus_data_length (uint16 LE)
0x14+   modbus_rtu_data (modbus_data_length bytes)
```

This means the 0xC2 frame payload is:
```
[modbus_len_lo modbus_len_hi] [modbus_rtu_bytes...]
```

NOT just raw Modbus RTU bytes — there's a 2-byte length prefix!

**This is a critical correction from our earlier understanding**. The design doc assumed
the 0xC2 payload was verbatim Modbus RTU. But there's actually a 2-byte little-endian
length field prefixed to the Modbus RTU data.

### DataProcess_FrameParser (0x42009c16, 426 bytes) — Decompiled

Streaming byte-by-byte parser. Context structure at `param_1`:
- `offset 0x00`: send callback function pointer
- `offset 0x04`: dispatch callback function pointer
- `offset 0x08`: parser state (0-4)
- `offset 0x0A`: version / field at state 2 position 3
- `offset 0x0C`: frame_length (stored at state 3)
- `offset 0x0E`: buffer position (uint16)
- `offset 0x10`: last-activity timestamp (for 500ms stale timeout)
- `offset 0x14`: transport context pointer
- `offset 0x18`: mutex
- `offset 0x1C`: serial (10 bytes)
- `offset 0x27`: receive buffer (1024 bytes, 0x400)
- `offset 0x2E`: func code byte position within buffer

**State machine**:
```
State 0: Wait for 0xA1 → transition to state 1
State 1: Wait for 0x1A → transition to state 2 (any other byte → back to state 0)
State 2: Collect version bytes
         At buffer position 3: store low byte at offset 0x0A
         At buffer position 4: combine into version at offset 0x0A → transition to state 3
State 3: Collect frame_length bytes
         At buffer position 5: store low byte at offset 0x0C
         At buffer position 6: combine into frame_length at offset 0x0C → transition to state 4
State 4: Collect payload bytes
         When buffer_pos > frame_length + 5:
           Extract func_code from buffer[0x2E - 0x27] = offset 7 within buffer
           Dispatch: callback(dp_ctx, func_code, buffer)
           Reset to state 0
```

500ms stale timeout: If current_time - last_activity > 499ms, reset buffer_pos and state to 0.
Internal buffer: 1024 bytes (0x400) at offset 0x27. No CRC validation.

### parse_SET_PARAM (0x4200c42a, 62 bytes)

Already documented above in section 9.

### parse_GET_PARAM (0x4200c468, 58 bytes)

Already documented above in section 9.

---

## 11. CRC-16 on Cloud TCP Frames — RESOLVED: NOT USED

### Definitive Finding

**CRC-16/Modbus is NOT appended to 0xA1/0x1A frames on the TCP cloud transport.**

This was determined by tracing every function in the send path:

#### Evidence Chain

1. **Frame builders do NOT add CRC**:
   - `HeartbeatBuilder` (0x4200c3b8): Returns 19 bytes, no CRC call
   - `DataProcess_ResponseBuilder` (0x4200c260): Returns total without CRC
   - `SetParam_ResponseBuilder` (0x4200c2e2): Returns 21 bytes, no CRC call
   - `FramePreambleBuilder` (0x4200c216): Returns 18 bytes, no CRC call

2. **DataProcess_Send (0x42009c02, 20 bytes) passes builder's size directly**:
   ```c
   void DataProcess_Send(dp_ctx, frame_size) {
       if (dp_ctx->send_callback != NULL) {
           dp_ctx->send_callback(dp_ctx, dp_ctx->send_buffer, frame_size);
       }
   }
   ```
   No CRC computation between builder and send callback.

3. **TCPClient_SendData (0x4200db40, 152 bytes) sends raw buffer**:
   ```c
   void TCPClient_SendData(tcp_obj, buffer, length) {
       if (tcp_obj->socket >= 0 && tcp_obj->state == 1) {
           int result = send(tcp_obj->socket, buffer, length, 0);
           if (result < 0) { log_error(); }
           else { DataProcess_LogPacket("Send: ", buffer, length); }
       }
   }
   ```
   No CRC added before `send()`.

4. **TCPServer_MainHandler (0x4200d3ec) — local TCP server — also no CRC**:
   Direct `send()` call without CRC computation.

5. **ComputeCRC16 (0x4200de42) is ONLY called from BuildPacket (0x4200de8c)**:
   `BuildPacket` builds Modbus RTU frames for RS485 UART. It is never called
   from any cloud frame code. Grep across all decompiled code confirms exactly
   one call site.

6. **DataProcess_FrameParser (0x42009c16) does NOT validate CRC on receive**:
   The streaming parser dispatches frames when `buffer_pos > frame_length + 5`.
   No CRC verification anywhere in the 426-byte function.

#### Where CRC IS Used

CRC-16/Modbus IS present in two places:
- **Modbus RTU payloads** inside 0xC2 DATA_TRANSMISSION frames (this is the standard
  Modbus CRC on the inverter communication, not the cloud frame wrapper)
- **RS485 Modbus requests** built by `BuildPacket` for dongle→inverter UART communication

#### Corrected Frame Format

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
                                 *** NO TRAILING CRC ***
```

`frame_length` = addr(1) + func(1) + serial(10) + payload_len = payload_len + 12
`total_size` = 6 + frame_length = 18 + payload_len

#### Corrected Heartbeat (0xC1) — 19 bytes total (NOT 21)

```
[A1 1A] [01 00] [0D 00] [01] [C1] [serial x10] [05]
  0-1     2-3     4-5     6    7     8-17         18
```
frame_length = 13 (0x0D), total = 19 bytes.

#### Impact on CloudEmitter Implementation

The CloudEmitter MUST NOT append CRC-16 to cloud TCP frames. The `decode_cloud_frames.py`
pcap analysis script must be updated to NOT expect trailing CRC bytes.

**Traffic capture will provide final confirmation** — if frames are exactly 19 bytes for
heartbeats (not 21), the no-CRC finding is confirmed.

---

## 12. Extended Modbus Protocol (BREAKTHROUGH — 2026-02-24)

### Discovery

From decompiling `RS485_DataReadyCallback` (GhidraForceDecompile.java) and
`TransportForward_Cloud/Local/BLE` (GhidraTransportForward.java), we proved that
the LuxPower/EG4 inverters use a **proprietary extended Modbus protocol** — not
standard Modbus RTU.

### Evidence

1. **BuildPacket** (0x4200de8c) builds 18-byte requests with embedded serial:
   ```
   buf[0] = slave_addr     // param_3
   buf[1] = func_code      // param_4
   memcpy(buf+2, serial, 10)  // param_5 (inverter serial)
   buf[12:14] = start_reg  // param_6 (uint16 LE)
   buf[14:16] = count      // param_7 (uint16 LE)
   buf[16:18] = CRC16      // computed over buf[0:16]
   ```

2. **rs485_service_task** (0x4200c4cc, 1252 bytes) validates 271-byte responses:
   - `pcVar3[0]` = slave_addr
   - `pcVar3[1]` = func_code (checked against 0x04, 0x21-0x23)
   - `pcVar3[2:12]` = inverter serial (10 bytes)
   - `pcVar3[12:14]` = start_register (uint16 LE) — used for dispatch
   - `pcVar3[14]` = byte_count (0xFE=254 for 127 regs)
   - `pcVar3[15:269]` = register data (254 bytes)
   - `pcVar3[269:271]` = CRC-16/Modbus (validated by `FUN_ram_4200de42`)

3. **RS485_DataReadyCallback** (0x4200aaec, 48 bytes) is pure forwarding:
   - Receives (context, raw_data_ptr, raw_data_len) from rs485_service_task
   - Calls 3 transport forwards with the SAME raw data — no transformation

4. **Transport forwards** call `FUN_ram_42009df6(transport_handle, data, len)`:
   - 62-byte function that wraps raw data in 0xC2 frame
   - Uses FramePreambleBuilder + 2-byte LE length prefix + memcpy

### CRC Scope

CRC-16/Modbus is computed over the full 269-byte extended request (16 bytes) or response
(269 bytes for 127 input regs). It is NOT computed over just the standard Modbus fields.

The dongle validates CRC on received RS485 responses:
```c
uVar5 = FUN_ram_4200de42(pcVar3, iVar2 - 2U & 0xffff);  // CRC over all but last 2 bytes
if (uVar5 == *(ushort *)(pcVar3 + iVar2 + -2)) {          // Compare with last 2 bytes
```

### Implications for CloudEmitter

To build a valid 0xC2 frame, the CloudEmitter must:
1. Read register data from the inverter via local Modbus transport
2. **Reconstruct** the 271-byte extended response format (adding serial + start_reg)
3. Compute CRC-16/Modbus over the 269-byte body
4. Wrap in 0xC2 frame: `[preamble 18B][modbus_len 2B LE][extended_response 271B]`

The CloudEmitter **cannot** send standard Modbus RTU responses — the cloud server
expects the extended format with embedded serial.

---

## 13. Open Questions (for traffic capture validation)

### Resolved (2026-02-24)

1. ~~**CRC placement**~~ → **RESOLVED**: No CRC on TCP cloud frames.
2. ~~**0xC2 payload format**~~ → **RESOLVED**: `[modbus_len 2B LE][extended_modbus_response]`.
   Extended response includes 10-byte serial. NOT standard Modbus RTU.
3. ~~**Data transformation**~~ → **RESOLVED**: None. RS485_DataReadyCallback is pure forwarding.
   Raw 271-byte extended response from inverter → 0xC2 frame → cloud.
4. ~~**SET_PARAM for register writes**~~ → **RESOLVED**: All SET_PARAM codes are dongle-internal.
   Inverter register writes use 0xC2 DATA_TRANSMISSION with Modbus WRITE_SINGLE (0x06).

### Resolved by pcap (2026-02-24 capture)

5. ~~**Holding register polling**~~ → **RESOLVED**: Cloud INITIATES all holding register
   reads. Dongle only pushes input registers autonomously. Dual polling model.
6. ~~**Cloud→dongle 0xC2 frequency**~~ → **RESOLVED**: Cloud sends READ_HOLDING requests
   continuously, plus WRITE_SINGLE for parameter changes. Not just firmware updates.
7. ~~**Register value endianness**~~ → **RESOLVED**: ALL fields in extended Modbus are
   little-endian, including register values. Confirmed by comparing READ response
   values with WRITE values and known register semantics (GridBOSS reg 20 = 2).
8. ~~**Extended Modbus CRC scope**~~ → **RESOLVED**: CRC covers all bytes before the last 2.
   All 74 frames in capture show CRC OK.
9. ~~**Cloud heartbeat echo**~~ → **RESOLVED**: Cloud DOES echo heartbeats back (same status
   byte). This contradicts firmware analysis which said "NO echo". The dongle counts
   received heartbeats but the cloud sends them too.
10. ~~**Register 2032 (0x7F0)**~~ → **RESOLVED**: Cloud probes reg 2032 on all devices.
    Inverters return exception 0x83 code=3. GridBOSS returns 127 regs (first=0x1C02).
    Likely firmware update or capability detection.

### Still Open

1. **Version field**: Is it always [01 00] or does firmware version affect it?
2. **Frame ordering/timing**: Input reg pushes are back-to-back (~1.2s between chunks).
   Holding reg reads are cloud-paced (~1.5s between request-response pairs).
3. **Autonomous push interval**: Only one input push seen per device in 41.7s
   capture. Second capture (firmware check, ~60s) also showed input pushes.
   Likely ~60-100s between push cycles. Need longer capture to confirm.
4. **Heartbeat status byte meaning**: DJ43404815 (GridBOSS) = 0x05, BC34000380 = 0x01.
   What do these values indicate?
5. **Initial data_period**: No SET_PARAM observed in capture. Need connection
   establishment capture to see initial configuration.
6. **GridBOSS input push** — RESOLVED: GridBOSS DOES push input registers
   (confirmed in second capture). All device types push autonomously.
