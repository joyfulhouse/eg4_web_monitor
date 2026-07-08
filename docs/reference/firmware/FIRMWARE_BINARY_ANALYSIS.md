# EG4 Inverter Firmware Binary Analysis

**Analysis date**: 2026-04-13
**Firmware version**: fAAB-2727 (FAAB-27xx_20260330)
**Devices**: EG4 18kPV (4512670118), EG4 FlexBOSS21 (52842P0581)

## Architecture: Dual-Processor System

The EG4 inverter firmware reveals a **dual-processor architecture**:

### ARM Cortex-M4 — Communications Processor

- **File**: `FAAB-27xx_20260330_App.hex` (353,026 bytes at flash 0x10000)
- **ISA**: ARM Thumb-2 with VFP floating-point and DSP multiply extensions
- **MCU**: STM32 family, 512KB flash (identified by "512KEAA1" string + DSB SY instruction)
- **Role**: Communications processor — WiFi dongle interface, Modbus RTU/TCP, cloud protocol
- **Evidence**: 152 BX LR instructions, 585 PUSH/688 POP, 4 DSB SY barriers, 97 VFP prefixes, 201 SMULL/UMULL/MLA

The ARM core is the **boot master** — the string "DSPBOOTFLASH" indicates it loads the
DSP firmware from flash into the power conversion processor.

### TI C28x DSP — Power Conversion Processor

- **File**: `fAAB-xx27_ParaXXX_20260330.hex` (284-286 KB at flash 0x80000)
- **ISA**: TI C28x (C2000 family) — 32-bit fixed-point DSP
- **Role**: Power conversion — MPPT, grid synchronization, battery management, switching control
- **Evidence**: 907 MOVW DP (0x76xx) instructions in first 43KB, plus MOV ACC, ADD ACC, CLRC,
  MOVL XAR, RPT, B_cond patterns throughout

Despite the filename "Para" (parameter), these files are **complete DSP firmware images**
with embedded calibration constants, not simple key-value parameter tables.

### Likely Hardware Platform

The dual-processor design is consistent with:
- **TI Concerto** (F28M35x/F28M36x): ARM Cortex-M3 + C28x on single die
- **Two-chip design**: STM32 + separate TI C2000 DSP
- Inter-processor communication via UART-A and UART-B channels
  (evidenced by `NOTB`/`UARB` protocol markers in firmware)

## Memory Map

### App Firmware (ARM Cortex-M4)

Flash address range: `0x08010000` - `0x08066302` (353,026 bytes)

No standard ARM vector table at the start — the bootloader resides at `0x08000000`-`0x0800FFFF`
and is not included in OTA images. The App binary begins directly with code/data.

| Region | Flash Offset | Size | Content |
|--------|-------------|------|---------|
| Initial code + data | 0x10000-0x13700 | 14 KB | Startup, data tables |
| FF gap | 0x13700-0x13900 | 512 B | Erased flash padding |
| Main code | 0x13900-0x29A00 | 88 KB | Primary application |
| Extended code | 0x29B00-0x2F200 | 22 KB | Continued code |
| Zero padding | 0x2F200-0x2F900 | 1.8 KB | Section boundary |
| Comm handlers | 0x2F900-0x3C100 | 50 KB | Communication logic |
| Zero padding | 0x3C100-0x3C900 | 2 KB | Section boundary |
| Largest code block | 0x3C900-0x5E500 | 135 KB | Core application |
| Final section | 0x5E600-0x66300 | 31 KB | Tail code + data |

### Para Firmware (TI C28x DSP)

Flash address range: `0x08080000` - `0x080C5E0D` (18kPV: 286,221 bytes)

| Region | Offset | Size | Content |
|--------|--------|------|---------|
| Header | 0x000-0x005 | 5 B | Magic: `00 00 48 14 59` |
| 0xFF padding | 0x006-0x020 | 26 B | Erased flash |
| Config metadata | 0x021-0x03D | 28 B | Configuration header (identical between models) |
| 0xFF padding | 0x03E-0x403 | 966 B | Erased flash |
| Register definitions | 0x404-0x2936 | 9.3 KB | Shared Modbus register map structures |
| DSP code (small) | 0x3231-0xD93D | 42 KB | DSP instruction code |
| 0xFF gap | 0xD93E-0xDCDB | 926 B | Erased flash |
| DSP code (large) | 0xDCDC-0x45C13 | 224 KB | Main DSP program + calibration |
| Zero trailer | End-28 | 28 B | Zero padding |

## String Analysis

### OEM Brand Table (App offset 0x1A500-0x1A5E0)

The firmware supports multiple brands from a single binary:

| String | Brand | Market |
|--------|-------|--------|
| `FreedWON` | Freedom Won | South Africa |
| `HINAESS` | HINAESS Energy | China (domestic) |
| `eTower` | eTower | Europe / Australia |
| `EG4-LL` | EG4 Electronics | US (LL = Luxpower Link) |

Brand selection is likely determined by serial number prefix patterns embedded in firmware.

### Platform Identifiers

| String | Location | Interpretation |
|--------|----------|---------------|
| `Q3500` | 0x2C08C | Luxpower internal platform code |
| `Q3500,001,03,05,09,07,00,1,+,` | 0x2C08C | Platform capability descriptor |
| `FAABFAABFAAB` | Various | Firmware family code (3x for alignment/verification) |
| `512KEAA1` | Near DSB SY | MCU flash size (512KB) + silicon revision |
| `DSPBOOTFLASH` | 0x1A4E0 | ARM core loads DSP firmware from flash |

### Serial/Part Number Patterns (App offset 0x1A519-0x1A590)

| Pattern | Type |
|---------|------|
| `2532540001`, `3092280001`, `3260000000` | 10-digit numeric part codes |
| `5312600001`, `5314280001`, `2492570001` | Additional part codes |
| `52060E0150`, `52642P0151`, `52642P0205` | PCB revision codes (model-rev-variant) |
| `xxx6xxxxxx`, `xxx0xxxxxx` | Serial number format templates (position 4 = model discriminator) |

### Protocol Markers

| String | Location | Interpretation |
|--------|----------|---------------|
| `NOTB` | 0x1F1AF | UART busy/idle arbitration token |
| `NOTBUARB` | 0x2EDFB | UART-B channel arbitration |
| `QD0`, `Q1`, `QS` | Near config | Luxpower proprietary serial protocol commands |

## Cross-Model Comparison

### App Firmware: Code-Identical with Model-Keyed Checksums

The 18kPV and FlexBOSS21 App binaries are **functionally identical**. Every byte of
actual code and data is the same. The only differences are **integrity check values**
embedded at regular intervals:

```
Block structure: Every 771 bytes (769 data + 2 check bytes)
Total checksum positions: 461
Positions with constant XOR delta: 458 of 461 (99.3%)
XOR key between models: 0xA7E7
Outlier positions (sector boundaries): 3 (keys: 0xA5D6, 0x0231, 0x9B4E)
```

The XOR key `0xA7E7` is derived from the model/parameter identifier (Para375 vs Para075).
This is a **firmware signing mechanism**: the same code binary is "personalized" for each
model by computing block checksums with a model-specific seed.

**Implication**: The cloud server must compute checksums with the correct model key to
produce a valid firmware image. This prevents accidental cross-model firmware flashing.

### Parameter Tables: Fundamentally Different

| Metric | Value |
|--------|-------|
| Size difference | 1,678 bytes (18kPV larger) |
| Comparable region | 284,543 bytes |
| Identical bytes | 36,058 (12.7%) |
| Different bytes | 248,485 (87.3%) |

The Para tables contain **entirely different DSP code and calibration data** because:
- Different power stage configurations (18kPV = 18kW, FlexBOSS21 = 21kW)
- Different voltage/current thresholds and switching parameters
- Different MPPT tracking algorithms tuned for each power rating
- Different battery charge curves

Only the shared register definitions region (0x404-0x2936) and header are identical.

### Naming Convention

| Para Name | Model | Chunk Count |
|-----------|-------|-------------|
| Para375 | 18kPV | 373 |
| Para075 | FlexBOSS21 | 371 |

The number encodes the model variant, not a parameter count.

## OTA Integrity Scheme

### Block Checksums

The firmware binary contains per-block integrity values:

```
Every 771 bytes:
  [769 bytes of firmware data] [2 bytes checksum]

Checksum = f(block_data) XOR model_key

Model keys (derived from Para identifier):
  18kPV (Para375):    one set of checksums
  FlexBOSS21 (Para075): same checksums XOR 0xA7E7
```

The checksum function `f()` is **not** any standard CRC-16 variant (Modbus, CCITT,
XMODEM), simple sum, XOR-16, or Fletcher-16. It appears to be a custom algorithm.

### Per-Chunk CRC (Final Chunk Trailer)

Each OTA transfer pass ends with a final chunk containing:
- 4-byte firmware type ID (matches init frame)
- 2-byte CRC-16

This CRC also uses a non-standard algorithm. The same CRC algorithm is used for both
App and Para files.

### Security Implications

1. The model-keyed checksum prevents cross-model flashing via OTA
2. The checksum algorithm is proprietary (not easily reproducible)
3. No encryption — the firmware is transmitted in cleartext
4. No code signing with public-key cryptography

## Key Takeaways for Integration Development

### 1. Identical ARM Firmware Across Models

The 18kPV and FlexBOSS21 run **identical ARM communication firmware**. All Modbus
register handling, cloud API communication, and WiFi dongle protocol code is shared.
This means:
- Register maps are the same across models (for the ARM-managed registers)
- Cloud protocol behavior is model-independent
- Bug fixes in one model's communication layer apply to all models

### 2. Model-Specific Behavior Lives in the DSP

All behavioral differences between inverter models come from the Para (DSP) image:
- Power ratings and limits
- Grid synchronization parameters
- Battery charge/discharge curves
- MPPT algorithm tuning
- Voltage/current thresholds

### 3. Multi-Brand Platform

The Q3500 platform serves FreedWON, HINAESS, eTower, and EG4 brands from a single
firmware binary. Brand is determined by serial number prefix, not firmware variant.

### 4. Register Map Shared Between Processors

The Para file contains shared register definitions at offset 0x404-0x2936 (9.3 KB)
that are identical between models. This is the canonical register map that both the
ARM communication processor and C28x DSP agree on — a valuable reference for
understanding undocumented registers.

## File Reference

| File | Size | Architecture | Content |
|------|------|-------------|---------|
| `18kpv_FAAB-27xx_20260330_App.bin` | 353 KB | ARM Cortex-M4 | Communication firmware |
| `flexboss21_FAAB-27xx_20260330_App.bin` | 353 KB | ARM Cortex-M4 | Communication firmware (identical) |
| `18kpv_fAAB-xx27_Para375_20260330.bin` | 286 KB | TI C28x DSP | 18kPV power conversion + calibration |
| `flexboss21_fAAB-xx27_Para075_20260330.bin` | 285 KB | TI C28x DSP | FlexBOSS21 power conversion + calibration |

See [FIRMWARE_OTA_PROTOCOL.md](FIRMWARE_OTA_PROTOCOL.md) for the OTA transfer protocol,
capture methodology, and extraction tools.
