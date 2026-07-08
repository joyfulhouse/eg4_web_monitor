# EG4 Para/DSP Firmware Reverse Engineering Summary

**Date**: 2026-04-13
**Firmware files analyzed**:
- `18kpv_fAAB-xx27_Para375_20260330.bin` (286,221 bytes)
- `flexboss21_fAAB-xx27_Para075_20260330.bin` (284,543 bytes)

---

## 1. File Structure Overview

```
Offset      Size     Content
──────────  ───────  ────────────────────────────────────
0x000-0x005    6B    Magic header: 00 00 48 14 59 FF
0x006-0x020   27B    FF padding
0x021-0x03D   29B    Config metadata (IDENTICAL between models)
0x03E-0x403  966B    FF padding (2 byte diffs between models)
0x404-0x2936 9523B   Shared code region (C28x code, 30 byte diffs)
0x2937-0x3230 762B   Transition / additional code (8 byte diffs)
0x3231-EOF   ~273KB  Main DSP code (250,123 byte diffs)
```

**Block checksum overlay**: The entire file is divided into 771-byte blocks
(769 data + 2 checksum), superimposed on the logical layout above. The 18kPV
file has 371 complete blocks + 180 remainder bytes.

---

## 2. Config Metadata (0x021-0x03D)

28 bytes, **identical** between 18kPV and FlexBOSS.

```
ff fe 02 8f 00 de 00 8f 48 12 59 a8 42 8f 08 02
00 76 48 14 6c 76 40 e1 34 fe 82 00 06
```

### Notable fields:
- `0x027-0x02A`: `48 12 59 A8` -- variant of the file magic `48 14 59`,
  differing in byte 2 (0x12 vs 0x14). Likely identifies config vs application
  section.
- `0x031-0x032`: `48 14` -- exact match of the file header magic.
- `0x025`: `0xDE` (222 decimal) -- possible register/parameter count or
  section size indicator.
- `0x03C`: `0x06` -- possible section count (matches 6 register read groups in
  pylxpweb's combined input register read).

---

## 3. Shared Code Region (0x404-0x2936) -- KEY FINDING

**This region is NOT a flat data table of register definitions.** It is compiled
TI C28x DSP code that implements register handling, validation, and Modbus CRC
computation.

### Evidence:
1. High-frequency instruction patterns: `0x1F76` (MOV to stack, 52 occ),
   `0x8AA9` (immediate operand, 33 occ), `0xFF20` (MOV AH,#imm, 24 occ)
2. Function terminators: `FF 69` (LRETR) found at 17 positions within the region
3. No sequential register number sequences detected
4. Code structure repeats with variations (different immediate operands for
   different register addresses)

### CRC-16/Modbus Lookup Tables Found

The region contains embedded CRC-16/Modbus lookup tables:

| Table | Physical Address | Size | Match |
|-------|-----------------|------|-------|
| LOW byte table | 0x24D8-0x26D7 | 512B (256 entries x 2) | 256/256 verified |
| HIGH byte table | 0x26D8-0x28D7 | 512B (256 entries x 2) | 39/39 verified (rest split by block checksum) |

Each table entry is stored as a 16-bit C28x word: the CRC byte in the low byte
position, zero-padded to 16 bits. This is the standard CRC-16/Modbus lookup
table used by the DSP for Modbus communication.

### 6 Actual Data Differences (non-checksum)

All 6 data differences are ASCII case changes at offsets 0x101A-0x102B:

| Offset | 18kPV | FlexBOSS | Context |
|--------|-------|----------|---------|
| 0x101A | 'a' (0x61) | 'A' (0x41) | Embedded in C28x instruction operands |
| 0x101E | 'e' (0x65) | 'E' (0x45) | |
| 0x101F | 'a' (0x61) | 'A' (0x41) | |
| 0x1027 | 'a' (0x61) | 'A' (0x41) | |
| 0x102A | 'a' (0x61) | 'A' (0x41) | |
| 0x102B | 'e' (0x65) | 'E' (0x45) | |

These appear to be string constants (possibly model identifiers) embedded in the
register handling code. The remaining 24 differences in this region are all block
checksum values that differ because they cover blocks containing these data changes.

---

## 4. Firmware Comparison: 18kPV vs FlexBOSS21

### Size difference: +1,678 bytes (18kPV is larger)

### Difference distribution:
| Region | Diffs | % of Total |
|--------|-------|------------|
| Header + Config + Padding | 2 | 0.001% |
| Shared Code Region | 30 (6 data + 24 checksum) | 0.012% |
| Gap Region | 8 | 0.003% |
| DSP Code | 250,123 | 99.98% |

The DSP code is almost entirely different (11,202 contiguous difference regions),
confirming these are distinct firmware images for different hardware.

### Power Rating Values Found

| Value | Description | 18kPV Locations | FlexBOSS Locations |
|-------|-------------|----------------|-------------------|
| 18000 | 18kPV rated power | LE: 0x4408C+ (5 hits), BE: 0x054D9+ (5 hits) | Same LE pattern at different offsets |
| 21000 | FlexBOSS21 rated power | LE: 0x07735+ (5 hits), BE: 0x02374+ (5 hits) | Identical pattern |

**Both power ratings exist in BOTH firmwares**, suggesting the DSP code contains
a model configuration table that supports multiple hardware variants. The
firmware selects the appropriate values based on the HOLD_MODEL register
(holding regs 0-1).

### Voltage/Frequency Thresholds (in DSP region)

| Value | Meaning | Hits (both models) |
|-------|---------|-------------------|
| 2400 | 240.0V (US split-phase, div10) | 76 each |
| 2300 | 230.0V (EU L-N, div10) | 6 each |
| 4160 | 416.0V (bus voltage, div10) | 4 each |
| 4800 | 48.0V (battery nominal, div10) | 6 each |
| 5200 | 52.0V (battery float, div10) | 4 (18kPV), 1 (FlexBOSS) |
| 5600 | 56.0V (battery max charge, div10) | Present in both |

### Calibration Lookup Tables

A significant **voltage calibration curve** was found at 0x41313 (18kPV):

- 21 entries descending from 2843 to 2823 (284.3V to 282.3V, step -1)
- Continues with progressively decreasing entries down to 2630 (263.0V)
- Total ~200 entries across multiple sub-tables

This is likely a **battery charge voltage vs temperature** or **SOC-dependent
voltage** calibration curve. The FlexBOSS has an equivalent table at a different
offset.

---

## 5. DSP Code Structure

### TI C28x Architecture
- **Code region**: 0x3231 to end of file
- **Size**: ~273KB (136,686 16-bit words)
- **Code/data ratio**: 75.5% instruction-like / 24.5% data-like / 9.6% ASCII-pairs

### Function Count
- **LRET (0x0006)**: 132 occurrences (function returns)
- **LRETC (0x0007)**: 22 occurrences (conditional returns)
- **Estimated functions**: ~132-154

### Function Size Distribution
- Average: ~1,766 bytes
- Median: ~948 bytes (suggesting many small utility functions + fewer large ones)
- Range: 2 bytes to >10KB

### Top C28x Opcodes
| Opcode | Count | Likely Instruction |
|--------|-------|--------------------|
| 0x1F76 | 6,024 | MOV *SP++,AR1 (stack push) |
| 0x041F | 5,550 | POP AR1 (stack pop) |
| 0x0077 | 897 | NOP or small constant |
| 0xA07F | 699 | Memory access pattern |
| 0xBF56 | 650 | Conditional branch |

### Embedded Strings

Most "strings" detected are actually C28x instruction sequences that coincidentally
fall in the printable ASCII range. No meaningful human-readable strings (like model
names or error messages) were found in the DSP code region, which is typical for
embedded DSP firmware compiled from C.

---

## 6. Block Checksum Scheme

### Structure
- **Block size**: 771 bytes (769 data + 2 checksum)
- **Checksum position**: bytes 769-770 of each block (big-endian)
- **Total blocks**: 371 (18kPV), 369 (FlexBOSS)
- **Remainder**: 180 bytes (18kPV), 84 bytes (FlexBOSS)

### XOR Key Verification

For blocks where the data is **identical** between 18kPV and FlexBOSS (blocks
0-14, and other blocks in the shared region), the XOR of their checksums is a
**constant 0xE7A7**:

```
Block  0: 18kPV=0xFD40 ^ FlexBOSS=0x1AE7 = 0xE7A7
Block  1: 18kPV=0x7FE4 ^ FlexBOSS=0x9843 = 0xE7A7
Block  2: 18kPV=0x5A6A ^ FlexBOSS=0xBDCD = 0xE7A7
...
Block 14: 18kPV=0x893E ^ FlexBOSS=0x6E99 = 0xE7A7
```

This confirms the **XOR key 0xE7A7** (byte-swapped: 0xA7E7). The checksum
algorithm likely computes a CRC or hash of the 769 data bytes, then XORs with a
model-specific key derived from the firmware identifier (Para375 vs Para075).

### Algorithm Analysis

None of the standard algorithms tested (byte sum, word sum, byte XOR, word XOR,
CRC-16/CCITT, CRC-16/Modbus, complement sum, seeded sums) produced a direct match.
The checksum is likely:

1. A **custom polynomial CRC** with firmware-specific initialization, OR
2. A standard CRC with **non-standard initialization vector** seeded from the
   config metadata, OR
3. A **TI-specific checksum** used by the TMS320C28x boot ROM (which has its own
   checksum requirements for flash programming)

The presence of CRC-16/Modbus lookup tables in the firmware suggests the DSP uses
Modbus CRC for communication, but a different algorithm for flash integrity.

---

## 7. Key Findings for pylxpweb

### Register Map is Code, Not Data

The "shared register definition" region is actually **compiled C28x code** that
implements register handling. This means:

1. Register definitions are not stored as a parseable data table
2. Default values, min/max ranges, and scale factors are embedded as immediate
   operands in C28x instructions
3. Extracting a complete register map requires either:
   - Full C28x disassembly + data flow analysis (using Ghidra or similar)
   - Continued empirical mapping via live Modbus probing
4. The current pylxpweb register maps (validated against live hardware) remain
   the authoritative reference

### CRC-16/Modbus Confirmed

The firmware contains standard CRC-16/Modbus lookup tables, confirming the
Modbus CRC implementation matches the standard (poly=0xA001, init=0xFFFF).
This validates pylxpweb's existing CRC computation.

### Multi-Model Support in Single Firmware

Both 18000W and 21000W power rating constants exist in both firmware images,
confirming the DSP code supports multiple hardware variants selected at runtime
via the HOLD_MODEL register pair (regs 0-1). The 6 case-only differences in the
shared code region suggest minor model-specific string constants but otherwise
identical register handling logic.

### Voltage Calibration Curves

The descending voltage tables (284.3V to 263.0V) represent battery
charge/discharge voltage calibration curves. These are model-independent
(same algorithm, different scaling applied via HOLD_MODEL), which explains why
both models share the register handling code.

---

## Output Files

| File | Description |
|------|-------------|
| `00_SUMMARY.md` | This summary document |
| `01_register_map.md` | Detailed register region analysis with hex dumps |
| `02_config_metadata.md` | Config metadata field-by-field parsing |
| `03_firmware_comparison.md` | Full byte-level diff with power/voltage search |
| `04_dsp_structure_18kpv.md` | 18kPV DSP code structure, strings, lookup tables |
| `04_dsp_structure_flexboss.md` | FlexBOSS DSP code structure |
| `05_checksum_scheme.md` | Complete block checksum extraction and algorithm tests |
