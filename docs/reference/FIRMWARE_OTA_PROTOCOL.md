# EG4 Inverter OTA Firmware Upgrade Protocol

## Overview

EG4 inverters receive firmware updates over-the-air (OTA) through the cloud server.
The entire firmware transfer occurs over the existing persistent TCP connection between
the WiFi dongle and the cloud ingestion server — no separate HTTP download or additional
connections are established.

**Capture date**: 2026-04-13
**Devices upgraded**: EG4 18kPV (serial 4512670118), EG4 FlexBOSS21 (serial 52842P0581)
**Firmware version**: fAAB-2525 → fAAB-2727

## Network Architecture

```
EG4 Cloud Server (3.101.7.137:4346)
        │
        │  TCP persistent connection
        │  (same connection used for normal polling)
        │
   ┌────┴────┐
   │  WiFi   │  dongle serial: BC34000380 (18kPV)
   │  Dongle │  dongle serial: BC33600194 (FlexBOSS21)
   └────┬────┘
        │  RS485 / internal bus
        │
   ┌────┴────┐
   │Inverter │  inverter serial: 4512670118 / 52842P0581
   └─────────┘
```

The dongle maintains a persistent TCP connection to the cloud server on port 4346.
During normal operation, the dongle pushes input register data autonomously and the
cloud server issues holding register reads/writes. During a firmware upgrade, the cloud
server uses the same connection to push firmware chunks using proprietary Modbus-like
function codes 0x21 (init) and 0x22 (data).

## Packet Capture Setup

Dongles are on a separate VLAN, so traffic is only visible from the UniFi Dream Machine
gateway. Captures are performed via SSH to the UDM running tcpdump.

### Capture Command

```bash
# SSH to UDM and start capture (no timeout, no port filter)
ssh root@172.16.0.1 "nohup tcpdump -i any -s 0 -U -w /tmp/capture.pcap host <DONGLE_IP> &"

# Download when complete
scp root@172.16.0.1:/tmp/capture.pcap .
```

Key flags:
- `-i any` — capture on all interfaces (dongle VLAN bridge may vary)
- `-s 0` — full packet capture, no truncation (firmware payloads are 811 bytes)
- `-U` — packet-buffered output, flush each packet immediately
- `host <IP>` — no port filter (captures all dongle traffic)

### Capture Script

`scripts/capture_firmware_upgrade.sh` automates the full workflow:

```bash
# Verify connectivity (dry run)
./scripts/capture_firmware_upgrade.sh --ip 10.100.1.8 --verify

# Start capture (runs until Ctrl+C)
./scripts/capture_firmware_upgrade.sh --ip 10.100.1.8

# With auto-stop duration
./scripts/capture_firmware_upgrade.sh --ip 10.100.1.8 --duration 1800
```

### SLL2 Deduplication

The UDM's `tcpdump -i any` produces Linux cooked capture v2 (SLL2, link type 276)
with 20-byte headers. Each packet appears on multiple interfaces (e.g., `eth10.52`
and `br52`), causing duplicates. The extraction tools deduplicate by tracking
`(src_ip, dst_ip, tcp_seq, data_len)` tuples.

## OTA Protocol Specification

### Cloud Protocol Frame Format

All communication uses the standard EG4 cloud protocol frame:

```
Offset  Size  Field
0       2     Magic: 0xA1 0x1A
2       2     Version (typically 0x00 0x01)
4       2     Frame length (uint16 LE) — total_size - 6
6       1     Address byte
7       1     Function code (0xC1=heartbeat, 0xC2=data)
8       10    Dongle serial (ASCII, e.g., "BC34000380")
18      N     Payload (function-specific)
```

No trailing CRC on TCP frames (confirmed via firmware decompilation).

### Extended Modbus Format (within 0xC2 payload)

The 0xC2 data payload wraps an extended Modbus frame:

```
Offset  Size  Field
0       2     Modbus data length (uint16 LE)
2       1     Slave address (always 0)
3       1     Modbus function code
4       10    Inverter serial (ASCII, e.g., "4512670118")
14      2     Start register / sequence number (uint16 LE)
16      N     Function-specific data
```

### Firmware Upgrade Sequence

The upgrade follows a strict sequence for each firmware file:

```
1. Cloud reads holding registers 0-366 (current state snapshot)
2. Cloud writes to reg 21 (mode/flag register)
3. Cloud reads firmware version regs 7-10 (pre-upgrade version)
4. Cloud reads hardware revision regs 244-245
5. Cloud sends INIT frame (0x21) — announces firmware transfer
6. Cloud sends DATA chunks (0x22) — sequential firmware data
7. Dongle ACKs each chunk
8. Final chunk contains firmware ID + CRC-16 trailer
9. Repeat steps 5-8 for second firmware file
10. Inverter reboots and applies new firmware
```

### Function 0x21 — Firmware Init

Sent cloud→dongle to announce a new firmware transfer pass.

```
Extended Modbus header (14 bytes):
  [0]     Slave (0x00)
  [1]     Function (0x21)
  [2:12]  Inverter serial (10 ASCII bytes)
  [12:14] Firmware type ID bytes 0-1 (uint16 LE)

Metadata (10 bytes):
  [14:16] Firmware type ID bytes 2-3
  [16:18] Total chunk count (uint16 LE)
  [18:24] Firmware hash (6 bytes)
```

Total frame: 24 bytes modbus data.

**Observed init frames:**

| Pass | Firmware File | Type ID | Chunk Count | Hash |
|------|--------------|---------|-------------|------|
| 1 (App) | FAAB-27xx_20260330_App.hex | `EAA1` (45 41 41 31) | 462 | `6e142537aa72` (18kPV) / `6e1425370b05` (FlexBOSS) |
| 2 (Para/18kPV) | fAAB-xx27_Para375_20260330.hex | `a2ea` (61 32 65 61) | 373 | `d46b813d3d5d` |
| 2 (Para/FlexBOSS) | fAAB-xx27_Para075_20260330.hex | `A2EA` (41 32 45 41) | 371 | `7f08349659e9` |

The init frame hash differs between models even for the same App firmware, suggesting
it may include model-specific metadata or a combined hash of both passes.

### Function 0x22 — Firmware Data Chunk

Sent cloud→dongle with firmware binary data.

**Regular data chunk (cloud→dongle, 791 bytes modbus data):**

```
Extended Modbus header (14 bytes):
  [0]     Slave (0x00)
  [1]     Function (0x22)
  [2:12]  Inverter serial
  [12:14] Chunk sequence number (uint16 LE, 1-based)

Chunk header (6 bytes):
  [14]    Firmware type byte (0x42=App, 0x02=Para)
  [15]    Sub-command (0x04=data)
  [16:18] Page count (uint16 LE, typically 3 for full chunks)
  [18:20] Page address (uint16 LE, increments by page_count)

Firmware data (771 bytes for regular chunks):
  [20:791] Raw firmware binary data
```

Total cloud→dongle frame: 811 bytes (6 frame header + 2 modbus_len + 791 modbus data).

**Dongle ACK (dongle→cloud, 17 bytes modbus data):**

```
  [0]     Slave (0x00)
  [1]     Function (0x22)
  [2:12]  Inverter serial
  [12:14] ACK value (related to byte offset)
```

Total ACK frame: 37 bytes.

**Final chunk (cloud→dongle, variable size):**

The last chunk in each pass (sequence == chunk_count from init) contains a 6-byte
trailer after the firmware data:

```
  [...-6:-2]  Firmware type ID (4 bytes, matches init frame)
  [-2:]       CRC-16 (2 bytes, uint16 LE)
```

### Timing Characteristics

| Metric | Value |
|--------|-------|
| Chunk transmission interval | ~0.5s per chunk |
| Chunks per burst | ~13 before pause |
| Pause between bursts | ~20s (coincides with polling cycle) |
| Total time per pass (462 chunks) | ~12-15 minutes |
| Total upgrade time (2 passes) | ~25-30 minutes |

### Retransmissions

The cloud server retransmits:
- Init frames (0x21): sent 2x for pass 1, 4x for pass 2
- Last data chunk: retransmitted if ACK not received within timeout
- The last chunk of each burst is retransmitted at the start of the next burst

Deduplication by (chunk_sequence, pass_number) is required during extraction.

## Firmware Files

### fAAB-2727 App Firmware (FAAB-27xx_20260330_App.hex)

| Property | Value |
|----------|-------|
| Size | 353,026 bytes (344.8 KB) |
| Chunks | 462 (461 data + 1 final) |
| Base address | 0x10000 (flash page 256) |
| Architecture | ARM Thumb-2 (likely Cortex-M series) |
| Entropy | 6.55 bits/byte (compiled code, not encrypted) |
| Identical | Same binary for 18kPV and FlexBOSS21 |

Notable strings: `DSPBOOTFLASH`, `FreedWON`, `HINAESS`

### fAAB-2727 Parameter Table — 18kPV (fAAB-xx27_Para375_20260330.hex)

| Property | Value |
|----------|-------|
| Size | 286,221 bytes (279.5 KB) |
| Chunks | 373 (372 data + 1 final) |
| Base address | 0x80000 (flash page 2048) |
| Content | Configuration/calibration data |
| Entropy | 6.61 bits/byte |
| 0xFF regions | Large erased flash sections (parameter slots) |

### fAAB-2727 Parameter Table — FlexBOSS21 (fAAB-xx27_Para075_20260330.hex)

| Property | Value |
|----------|-------|
| Size | 284,543 bytes (277.9 KB) |
| Chunks | 371 (370 data + 1 final) |
| Base address | 0x80000 (flash page 2048) |
| Content | Configuration/calibration data |
| Entropy | 6.61 bits/byte |

The parameter tables differ between models (375 vs 075, different chunk counts and
content) while the App firmware is identical.

## Extraction Tools

### decode_cloud_frames.py

Decodes raw cloud protocol frames from a pcap capture. Shows frame-by-frame log
with timestamps, directions, function codes, register ranges, and CRC validation.

```bash
uv run python scripts/decode_cloud_frames.py <pcap_file>
```

### extract_firmware_from_pcap.py

Extracts firmware binaries from OTA upgrade pcap captures. Splits multi-pass
upgrades, validates chunk counts and firmware IDs, outputs both raw binary and
Intel HEX formats.

```bash
uv run python scripts/extract_firmware_from_pcap.py <pcap_file>
```

Output per pass:
- `.bin` — raw firmware binary
- `.hex` — Intel HEX with base address from page metadata

### capture_firmware_upgrade.sh

Automated pcap capture script for the UDM gateway. Supports verify mode,
custom dongle IPs, and optional duration limits.

```bash
./scripts/capture_firmware_upgrade.sh --ip <dongle_ip> [--verify] [--duration <seconds>]
```

## File Inventory

### Packet Captures

| File | Size | Device | Contents |
|------|------|--------|----------|
| `18kpv_firmware_upgrade_complete.pcap` | 2.2 MB | 18kPV | Full OTA: App (462 chunks) + Para375 (373 chunks) |
| `flexboss21_firmware_upgrade_complete.pcap` | 2.1 MB | FlexBOSS21 | Full OTA: App (462 chunks) + Para075 (371 chunks) |

### Extracted Firmware — 18kPV

| File | Size | Format | Pass |
|------|------|--------|------|
| `18kpv_FAAB-27xx_20260330_App.bin` | 353 KB | Raw binary | App firmware |
| `18kpv_FAAB-27xx_20260330_App.hex` | 971 KB | Intel HEX | App firmware |
| `18kpv_fAAB-xx27_Para375_20260330.bin` | 286 KB | Raw binary | Parameter table |
| `18kpv_fAAB-xx27_Para375_20260330.hex` | 787 KB | Intel HEX | Parameter table |

### Extracted Firmware — FlexBOSS21

| File | Size | Format | Pass |
|------|------|--------|------|
| `flexboss21_FAAB-27xx_20260330_App.bin` | 353 KB | Raw binary | App firmware |
| `flexboss21_FAAB-27xx_20260330_App.hex` | 971 KB | Intel HEX | App firmware |
| `flexboss21_fAAB-xx27_Para075_20260330.bin` | 285 KB | Raw binary | Parameter table |
| `flexboss21_fAAB-xx27_Para075_20260330.hex` | 783 KB | Intel HEX | Parameter table |

### Utilities

| File | Purpose |
|------|---------|
| `scripts/capture_firmware_upgrade.sh` | Automated UDM-based pcap capture |
| `scripts/capture_cloud_traffic.sh` | General cloud protocol capture (port 4346 only) |
| `scripts/decode_cloud_frames.py` | Cloud protocol frame decoder |
| `scripts/extract_firmware_from_pcap.py` | Firmware binary extractor from pcap |
| `scripts/download_dongle_firmware.py` | Download dongle firmware from LuxPower server |

## Dongle Network Mapping

| Device | Dongle Serial | Dongle IP | Dongle MAC | Inverter Serial | Cloud Server |
|--------|--------------|-----------|------------|-----------------|-------------|
| 18kPV | BC34000380 | 10.100.1.8 | 00:30:60:6c:66:a6 | 4512670118 | 3.101.7.137:4346 |
| FlexBOSS21 | BC33600194 | 10.100.1.164 | 00:30:6a:6c:64:a6 | 52842P0581 | 3.101.7.137:4346 |
| GridBOSS | DJ43404815 | 10.100.12.175 | b0:81:84:0e:85:dc | 4524850115 | 13.56.41.37:4346 |

MAC prefixes: `00:30:60` and `00:30:6a` are WIZnet (W7500 chip), `b0:81:84` is Espressif (ESP32).

## Open Questions

1. **CRC algorithm**: The 2-byte CRC in the final chunk does not match standard CRC-16/Modbus,
   CRC-16/CCITT, CRC-16/XMODEM, or simple checksums. May be a custom polynomial or the data
   boundary within each chunk needs fine adjustment (off by 1-3 bytes).

2. **Init frame hash**: The 6-byte hash in the 0x21 init frame differs between models for the
   same App firmware. Purpose unknown — may be a combined hash of both passes or include
   model-specific salt.

3. **Page addressing**: The page_addr field in chunk headers increments by page_count (typically 3)
   per chunk, suggesting 256-byte flash pages. Base address 0x10000 for App and 0x80000 for
   parameters suggests an ARM MCU with flash at 0x08000000 (bootloader) + 0x08010000 (app) +
   0x08080000 (params).

4. **Firmware type byte**: `0x42` for App firmware, `0x02` for Parameter table. The relationship
   between this byte and the firmware type ID in the init frame is unclear.
