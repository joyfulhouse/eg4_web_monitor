#!/usr/bin/env python3
"""Firmware reverse engineering analysis for EG4 inverter Para/DSP binaries.

Performs:
1. Shared register map extraction and decoding (0x404-0x2936)
2. Config metadata decoding (0x021-0x03D)
3. Binary comparison (18kPV vs FlexBOSS)
4. DSP code structure analysis (TI C28x)
5. Block checksum scheme extraction

Output: docs/reference/firmware_re/
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
FW_DIR = BASE_DIR / "scratchpad" / "firmware"
OUT_DIR = BASE_DIR / "docs" / "reference" / "firmware_re"

FW_18KPV = FW_DIR / "18kpv_fAAB-xx27_Para375_20260330.bin"
FW_FLEX = FW_DIR / "flexboss21_fAAB-xx27_Para075_20260330.bin"

# Region boundaries
HEADER_START = 0x000
HEADER_END = 0x005
CONFIG_START = 0x021
CONFIG_END = 0x03D
REGMAP_START = 0x404
REGMAP_END = 0x2936
DSP_CODE_START = 0x3231

# Block checksum
BLOCK_SIZE = 771
DATA_PER_BLOCK = 769
CHECKSUM_BYTES = 2

# Known EG4 register info for cross-reference
KNOWN_HOLDING_REGISTERS: dict[int, dict[str, object]] = {
    # System
    0: {"name": "hold_model_low", "scale": 1, "desc": "Model info low word"},
    1: {"name": "hold_model_high", "scale": 1, "desc": "Model info high word"},
    9: {"name": "com_protocol_version", "scale": 1},
    10: {"name": "controller_version", "scale": 1},
    15: {"name": "modbus_address", "scale": 1, "min": 1, "max": 247},
    16: {"name": "language", "scale": 1, "min": 0, "max": 1},
    19: {"name": "device_type_code", "scale": 1},
    # Function enable register 21
    21: {
        "name": "function_enable_1",
        "scale": 1,
        "desc": "Bitfield: EPS/AC/green/discharge/charge",
    },
    # Scheduling
    22: {"name": "time1_start_h", "scale": 1, "min": 0, "max": 23},
    23: {"name": "time1_start_m", "scale": 1, "min": 0, "max": 59},
    24: {"name": "time1_end_h", "scale": 1, "min": 0, "max": 23},
    25: {"name": "time1_end_m", "scale": 1, "min": 0, "max": 59},
    # Power control
    64: {"name": "pv_charge_power", "scale": 1, "min": 0, "max": 100, "unit": "%"},
    65: {
        "name": "discharge_power_percent",
        "scale": 1,
        "min": 0,
        "max": 100,
        "unit": "%",
    },
    66: {"name": "ac_charge_power", "scale": 1, "min": 0, "max": 15000, "unit": "W"},
    67: {"name": "ac_charge_soc_limit", "scale": 1, "min": 0, "max": 100, "unit": "%"},
    # Battery control
    101: {"name": "charge_current", "scale": 1, "min": 0, "max": 140, "unit": "A"},
    102: {"name": "discharge_current", "scale": 1, "min": 0, "max": 140, "unit": "A"},
    105: {
        "name": "ongrid_discharge_soc",
        "scale": 1,
        "min": 10,
        "max": 90,
        "unit": "%",
    },
    # Green mode
    110: {
        "name": "register_110",
        "scale": 1,
        "desc": "Green mode bitfield at bit 14 (#476)",
    },
    125: {
        "name": "offgrid_discharge_soc",
        "scale": 1,
        "min": 0,
        "max": 100,
        "unit": "%",
    },
    # Extended
    179: {
        "name": "function_enable_ext1",
        "scale": 1,
        "desc": "Extended function bitfield 1",
    },
    233: {
        "name": "function_enable_ext2",
        "scale": 1,
        "desc": "Extended function bitfield 2",
    },
}


@dataclass
class RegisterEntry:
    """Decoded register definition from firmware."""

    offset_in_region: int
    raw_bytes: bytes
    reg_number: int = -1
    reg_type: int = 0
    default_value: int = 0
    min_value: int = 0
    max_value: int = 0
    scale_factor: int = 1
    flags: int = 0
    known_name: str = ""


@dataclass
class BlockChecksum:
    """One checksum block from the firmware."""

    block_index: int
    file_offset: int
    data_start: int
    data_end: int
    checksum_offset: int
    checksum_value: int
    data: bytes = field(repr=False, default=b"")


@dataclass
class C28xFunction:
    """Detected function boundary in C28x code."""

    start_offset: int
    end_offset: int
    size: int
    ret_type: str  # "RET", "LRET", "IRET"


def load_firmware(path: Path) -> bytes:
    """Load firmware binary."""
    return path.read_bytes()


# ============================================================================
# Task 1: Register Map Extraction
# ============================================================================


def extract_register_map(data: bytes) -> str:
    """Extract and analyze the shared register map region."""
    region = data[REGMAP_START : REGMAP_END + 1]
    lines: list[str] = []
    lines.append("# Shared Register Map Analysis (0x404-0x2936)")
    lines.append(f"# Region size: {len(region)} bytes ({len(region):#x})")
    lines.append("")

    # Raw hex dump (first 256 bytes and last 64)
    lines.append("## Raw Hex Dump (first 512 bytes)")
    lines.append("```")
    for i in range(0, min(512, len(region)), 16):
        hex_str = " ".join(f"{b:02x}" for b in region[i : i + 16])
        ascii_str = "".join(
            chr(b) if 32 <= b < 127 else "." for b in region[i : i + 16]
        )
        lines.append(f"  {REGMAP_START + i:04x}: {hex_str:<48s}  {ascii_str}")
    lines.append("```")
    lines.append("")

    # Pattern analysis - try different record sizes
    lines.append("## Structure Pattern Analysis")
    lines.append("")

    # Look for repeating structures by analyzing byte-level patterns
    # TI C28x is 16-bit word-addressed, so try 2-byte (word) granularity
    words = []
    for i in range(0, len(region) - 1, 2):
        words.append(struct.unpack_from("<H", region, i)[0])

    lines.append(f"Total 16-bit words: {len(words)}")
    lines.append("")

    # Frequency analysis of word values
    word_freq = Counter(words)
    lines.append("### Most common 16-bit words")
    lines.append("| Value (hex) | Value (dec) | Count | Notes |")
    lines.append("|-------------|-------------|-------|-------|")
    for val, cnt in word_freq.most_common(30):
        note = ""
        if val == 0xFFFF:
            note = "Unprogrammed flash"
        elif val == 0x0000:
            note = "Zero"
        elif val == 0x8AA9:
            note = "Potential marker/sync"
        elif val == 0x0734:
            note = "Frequent - possible opcode"
        elif val in (0x01, 0x0A, 0x64, 0x03E8):
            note = f"Scale factor? (1/{val})"
        lines.append(f"| 0x{val:04X} | {val:>5d} | {cnt:>5d} | {note} |")
    lines.append("")

    # Try to identify record boundaries by looking for repeating marker patterns
    lines.append("### Marker Pattern Search")
    lines.append("")

    # Look for 0x8AA9 as a potential record delimiter
    marker_positions = [i for i, w in enumerate(words) if w == 0x8AA9]
    if marker_positions:
        lines.append(f"Found 0x8AA9 at {len(marker_positions)} word positions")
        # Analyze gaps between markers
        gaps = [
            marker_positions[i + 1] - marker_positions[i]
            for i in range(len(marker_positions) - 1)
        ]
        gap_freq = Counter(gaps)
        lines.append("Gap distribution between 0x8AA9 markers:")
        for gap, cnt in sorted(gap_freq.items()):
            lines.append(f"  Gap {gap} words ({gap * 2} bytes): {cnt} occurrences")
        lines.append("")

        # Show context around first 10 markers
        lines.append("### Context around first 15 marker (0x8AA9) positions")
        lines.append("```")
        for idx, pos in enumerate(marker_positions[:15]):
            # Show 8 words before and 8 words after
            start = max(0, pos - 6)
            end = min(len(words), pos + 8)
            word_strs = []
            for j in range(start, end):
                marker = " <<" if j == pos else ""
                word_strs.append(f"{words[j]:04X}{marker}")
            lines.append(
                f"  [{idx:3d}] word {pos:4d} (byte {pos * 2:#06x}): "
                + " ".join(word_strs)
            )
        lines.append("```")
        lines.append("")

    # Try other potential markers
    for marker in [0xFF20, 0x0144, 0xFFF8, 0x5005, 0x88A9, 0xA0C4, 0xCCC4]:
        positions = [i for i, w in enumerate(words) if w == marker]
        if 10 < len(positions) < 500:
            gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
            gap_freq = Counter(gaps)
            lines.append(
                f"Marker 0x{marker:04X}: {len(positions)} occurrences, "
                f"gaps: {dict(sorted(gap_freq.items()))}"
            )

    lines.append("")

    # Attempt structured record decoding
    lines.append("## Structured Record Decoding Attempts")
    lines.append("")

    # Try interpreting as C28x DSP configuration registers
    # Format hypothesis: this is TI C28x code that processes register definitions
    # Look for sequential register number references
    lines.append("### Sequential Value Search (potential register numbers)")
    lines.append("")

    # Find sequences where consecutive words increment by 1
    seq_starts: list[tuple[int, int]] = []
    run_start = 0
    run_len = 1
    for i in range(1, len(words)):
        if words[i] == words[i - 1] + 1 and words[i] < 300:
            run_len += 1
        else:
            if run_len >= 3:
                seq_starts.append((run_start, run_len))
            run_start = i
            run_len = 1
    if run_len >= 3:
        seq_starts.append((run_start, run_len))

    if seq_starts:
        lines.append(
            f"Found {len(seq_starts)} sequential runs (3+ consecutive incrementing values < 300):"
        )
        for start, length in seq_starts[:20]:
            vals = [words[start + j] for j in range(length)]
            lines.append(
                f"  Word {start} (byte {start * 2:#06x}): "
                f"{vals[0]}-{vals[-1]} (len {length})"
            )
    else:
        lines.append(
            "No sequential incrementing runs found (register numbers may not be stored linearly)"
        )
    lines.append("")

    # Look for known register values as potential defaults/limits
    lines.append("### Known Value Search")
    lines.append("")
    known_vals = {
        100: "100% (max percentage)",
        90: "90% (on-grid SOC cutoff max)",
        140: "140A (max charge/discharge current)",
        15000: "15000W (max AC charge power)",
        247: "247 (max Modbus address)",
        18000: "18000W (18kPV rating)",
        21000: "21000W (FlexBOSS21 rating)",
        12000: "12000W (12kPV rating)",
        6000: "6000W (6000XP rating)",
        5000: "5000W (common limit)",
        48: "48V (battery nominal voltage)",
        520: "52.0V (÷10, battery float voltage)",
        560: "56.0V (÷10, battery max charge voltage)",
        600: "60.0Hz frequency",
        500: "50.0Hz frequency (÷10)",
        2400: "240.0V (÷10)",
        1200: "120.0V (÷10)",
    }
    for val, desc in sorted(known_vals.items()):
        positions = [i for i, w in enumerate(words) if w == val]
        if positions:
            lines.append(
                f"  Value {val} ({desc}): found at word positions "
                + ", ".join(str(p) for p in positions[:10])
                + (f" ... (+{len(positions) - 10} more)" if len(positions) > 10 else "")
            )
    lines.append("")

    # Try to decode as C28x instruction sequences
    lines.append("### C28x Instruction Analysis of Register Region")
    lines.append("")
    lines.append("This region may contain C28x code that implements register handling.")
    lines.append("Common C28x opcodes in this region:")
    lines.append("")

    # C28x common opcodes
    c28x_opcodes = {
        0x0734: "MOVL XAR6,#imm32 (partial)",
        0xFF20: "MOV AH,#imm (or branch offset)",
        0x0144: "AND AL,#imm16 (partial)",
        0xFFF8: "MOV *SP++,#-8 or SPM prefix",
        0x5005: "MOVZ AR0,#imm (partial)",
        0x88A9: "possible data / immediate value",
        0xCCC4: "MOVL *XAR4,ACC or similar",
        0xA0C4: "MOVL ACC,*XAR4",
        0xB600: "MOVH *+XAR6[0],ACC",
        0x7EC4: "MOVL *XAR4,P",
        0xC3C4: "MOVL ACC,*XAR4",
        0x5002: "MOVZ AR0,@imm",
    }
    for opcode, desc in sorted(c28x_opcodes.items()):
        cnt = sum(1 for w in words if w == opcode)
        if cnt > 0:
            lines.append(f"  0x{opcode:04X}: {cnt:4d} occurrences - {desc}")
    lines.append("")

    # This region is likely C28x CODE, not a data table
    # Let's do a deeper C28x disassembly-style analysis
    lines.append("### Hypothesis: This region is C28x DSP code, not a raw data table")
    lines.append("")
    lines.append(
        "The high frequency of values like 0x8AA9, 0xFF20, 0x0734, 0xCCC4 suggests"
    )
    lines.append(
        "this is compiled C28x code (register load/store operations), not a flat"
    )
    lines.append(
        "table of register definitions. The register map is likely encoded as code"
    )
    lines.append(
        "that initializes register default values, validates ranges, and applies"
    )
    lines.append("scaling factors programmatically.")
    lines.append("")

    # Look for embedded 16-bit constants that match known register defaults
    lines.append("### Embedded Constants Analysis")
    lines.append("")

    # Extract all immediate values from MOVL/MOV patterns
    # C28x: MOV AH,#imm16 = 0xFF20 followed by imm16
    immediates: list[tuple[int, int]] = []
    for i in range(len(words) - 1):
        if words[i] == 0xFF20:  # MOV AH,#imm16
            immediates.append((i + 1, words[i + 1]))
        elif words[i] == 0x0144:  # potential immediate load
            if i + 1 < len(words):
                immediates.append((i + 1, words[i + 1]))

    lines.append(f"Found {len(immediates)} immediate values from MOV/load patterns")
    imm_freq = Counter(v for _, v in immediates)
    lines.append("Most common immediate values:")
    lines.append("| Value (hex) | Value (dec) | Count | Possible Meaning |")
    lines.append("|-------------|-------------|-------|------------------|")
    for val, cnt in imm_freq.most_common(40):
        meaning = ""
        if val == 0:
            meaning = "Zero/clear"
        elif val == 100:
            meaning = "100% max"
        elif val == 0xFFFF:
            meaning = "All bits set / -1"
        elif val <= 255 and val > 0:
            meaning = f"Register address {val}? or constant"
        elif val in known_vals:
            meaning = known_vals[val]
        elif val % 10 == 0 and val <= 10000:
            meaning = f"Possibly {val / 10:.0f} (÷10 scaled)"
        lines.append(f"| 0x{val:04X} | {val:>5d} | {cnt:>5d} | {meaning} |")
    lines.append("")

    # Full hex dump of last 256 bytes of region
    lines.append("## Raw Hex Dump (last 256 bytes of region)")
    lines.append("```")
    tail_start = max(0, len(region) - 256)
    for i in range(tail_start, len(region), 16):
        hex_str = " ".join(f"{b:02x}" for b in region[i : i + 16])
        ascii_str = "".join(
            chr(b) if 32 <= b < 127 else "." for b in region[i : i + 16]
        )
        lines.append(f"  {REGMAP_START + i:04x}: {hex_str:<48s}  {ascii_str}")
    lines.append("```")

    return "\n".join(lines)


# ============================================================================
# Task 2: Config Metadata
# ============================================================================


def decode_config_metadata(data: bytes) -> str:
    """Decode the 28-byte config metadata region."""
    region = data[CONFIG_START : CONFIG_END + 1]
    lines: list[str] = []
    lines.append("# Config Metadata Analysis (0x021-0x03D)")
    lines.append(f"# Region size: {len(region)} bytes")
    lines.append("")

    # Raw dump
    lines.append("## Raw Bytes")
    lines.append("```")
    hex_str = " ".join(f"{b:02x}" for b in region)
    lines.append(f"  {hex_str}")
    lines.append("```")
    lines.append("")

    # Parse as 16-bit words (little-endian, TI C28x convention)
    lines.append("## Parsed as 16-bit LE words")
    lines.append("| Offset | Hex | Decimal | Notes |")
    lines.append("|--------|-----|---------|-------|")
    for i in range(0, len(region) - 1, 2):
        word = struct.unpack_from("<H", region, i)[0]
        abs_offset = CONFIG_START + i
        note = ""
        # Try to identify fields
        if i == 0:
            note = f"First byte pair: 0x{region[0]:02X} 0x{region[1]:02X}"
        if word == 0x028F:
            note = "Possible version: 2.143 or config flags"
        if word == 0x00DE:
            note = "222 decimal - possible register count or size"
        if word == 0x4812:
            note = "Matches header magic fragment (48 12)"
        if word == 0x59A8:
            note = "Matches header magic fragment (59 A8)"
        if word == 0x428F:
            note = "Possible version or checksum"
        if word == 0x0802:
            note = "Possible flags: 0x08=bit3, 0x02=bit1"
        if word == 0x0076:
            note = "118 decimal - possible block/section count"
        if word == 0x4814:
            note = "Header magic fragment (48 14)"
        if word == 0x6C76:
            note = "27766 decimal"
        if word == 0x40E1:
            note = "16609 decimal"
        if word == 0x34FE:
            note = "13566 decimal"
        if word == 0x8200:
            note = "33280 decimal / 0x82=bit7+bit1"
        if word == 0x0006:
            note = "6 - possible section/block count"
        lines.append(
            f"| 0x{abs_offset:03X} (+{i:2d}) | 0x{word:04X} | {word:>5d} | {note} |"
        )
    lines.append("")

    # Parse as big-endian too for comparison
    lines.append("## Parsed as 16-bit BE words")
    lines.append("| Offset | Hex | Decimal | Notes |")
    lines.append("|--------|-----|---------|-------|")
    for i in range(0, len(region) - 1, 2):
        word = struct.unpack_from(">H", region, i)[0]
        abs_offset = CONFIG_START + i
        note = ""
        if word == 0xFFFE:
            note = "Near-max (config erased?)"
        if word == 0xFE02:
            note = "Possible config version"
        lines.append(
            f"| 0x{abs_offset:03X} (+{i:2d}) | 0x{word:04X} | {word:>5d} | {note} |"
        )
    lines.append("")

    # Interpret the header magic fragments
    lines.append("## Magic Byte Analysis")
    lines.append("")
    lines.append("Header at 0x000: `00 00 48 14 59` (known magic)")
    lines.append(
        f"Config at 0x021: starts with `{' '.join(f'{b:02x}' for b in region[:6])}`"
    )
    lines.append("")
    lines.append("Notable patterns:")
    lines.append(
        "- Bytes 0x027-0x02A: `48 12 59 A8` — variant of header magic `48 14 59`"
    )
    lines.append("  (0x4812 vs 0x4814 differ by 2, possibly config vs app identifier)")
    lines.append("- Byte 0x031: `48 14` — exact header magic fragment")
    lines.append("- Region 0xFF padding fills 0x005-0x020 and 0x03E-0x0403")
    lines.append("")

    # Try reading as individual bytes with field guesses
    lines.append("## Field Hypothesis")
    lines.append("```")
    lines.append(
        f"  Offset 0x021: 0x{region[0]:02X} = {region[0]:<3d}  — FF padding end marker?"
    )
    lines.append(
        f"  Offset 0x022: 0x{region[1]:02X} = {region[1]:<3d}  — Config format version major?"
    )
    lines.append(
        f"  Offset 0x023: 0x{region[2]:02X} = {region[2]:<3d}  — Config type/category (0x02=Para)?"
    )
    lines.append(
        f"  Offset 0x024: 0x{region[3]:02X} = {region[3]:<3d}  — Config sub-version?"
    )
    lines.append(f"  Offset 0x025: 0x{region[4]:02X} = {region[4]:<3d}  — Padding/zero")
    lines.append(
        f"  Offset 0x026: 0x{region[5]:02X} = {region[5]:<3d}  — Block count or size field (222)?"
    )
    lines.append(f"  Offset 0x027: 0x{region[6]:02X} = {region[6]:<3d}  — Padding/zero")
    lines.append(
        f"  Offset 0x028-0x02B: Config magic `{' '.join(f'{b:02x}' for b in region[7:11])}`"
    )
    lines.append(
        f"  Offset 0x02C-0x02F: `{' '.join(f'{b:02x}' for b in region[11:15])}` — Checksum/flags?"
    )
    lines.append(
        f"  Offset 0x030-0x033: `{' '.join(f'{b:02x}' for b in region[15:19])}` — Section offsets?"
    )
    lines.append(
        f"  Offset 0x034-0x037: `{' '.join(f'{b:02x}' for b in region[19:23])}` — App magic + version?"
    )
    lines.append(
        f"  Offset 0x038-0x03B: `{' '.join(f'{b:02x}' for b in region[23:27])}` — Checksums?"
    )
    lines.append(
        f"  Offset 0x03C-0x03D: `{' '.join(f'{b:02x}' for b in region[27:29]) if len(region) > 28 else 'N/A'}` — Terminal?"
    )
    lines.append("```")

    return "\n".join(lines)


# ============================================================================
# Task 3: Binary Comparison
# ============================================================================


def compare_firmwares(data_18k: bytes, data_flex: bytes) -> str:
    """Byte-level comparison of 18kPV vs FlexBOSS."""
    lines: list[str] = []
    lines.append("# Firmware Comparison: 18kPV vs FlexBOSS21")
    lines.append("")
    lines.append(f"18kPV size:    {len(data_18k):>10,d} bytes")
    lines.append(f"FlexBOSS size: {len(data_flex):>10,d} bytes")
    lines.append(f"Size delta:    {len(data_18k) - len(data_flex):>+10,d} bytes")
    lines.append("")

    min_len = min(len(data_18k), len(data_flex))

    # Find all differences
    diffs: list[tuple[int, int, int]] = []
    for i in range(min_len):
        if data_18k[i] != data_flex[i]:
            diffs.append((i, data_18k[i], data_flex[i]))

    # Extra bytes
    if len(data_18k) > min_len:
        for i in range(min_len, len(data_18k)):
            diffs.append((i, data_18k[i], -1))
    elif len(data_flex) > min_len:
        for i in range(min_len, len(data_flex)):
            diffs.append((i, -1, data_flex[i]))

    lines.append(f"Total byte differences: {len(diffs)}")
    lines.append("")

    # Categorize by region
    regions = {
        "Header (0x000-0x005)": (0x000, 0x006),
        "FF Padding (0x006-0x020)": (0x006, 0x021),
        "Config Metadata (0x021-0x03D)": (0x021, 0x03E),
        "FF Padding (0x03E-0x403)": (0x03E, 0x404),
        "Shared Register Region (0x404-0x2936)": (0x404, 0x2937),
        "Gap (0x2937-0x3230)": (0x2937, 0x3231),
        "DSP Code (0x3231+)": (0x3231, max(len(data_18k), len(data_flex))),
    }

    lines.append("## Differences by Region")
    lines.append("| Region | Offset Range | Diff Count |")
    lines.append("|--------|-------------|------------|")
    for name, (start, end) in regions.items():
        count = sum(1 for offset, _, _ in diffs if start <= offset < end)
        lines.append(f"| {name} | 0x{start:04X}-0x{end - 1:04X} | {count} |")
    lines.append("")

    # Analyze block checksum diffs in register region
    reg_diffs = [(o, a, b) for o, a, b in diffs if REGMAP_START <= o < REGMAP_END]
    if reg_diffs:
        lines.append("## Register Region Differences (detailed)")
        lines.append("")

        # Categorize as checksum or data
        checksum_diffs: list[tuple[int, int, int]] = []
        data_diffs: list[tuple[int, int, int]] = []

        for offset, val_18k, val_flex in reg_diffs:
            # Check if this offset falls on a block checksum position
            block_idx = offset // BLOCK_SIZE
            pos_in_block = offset % BLOCK_SIZE
            if pos_in_block >= DATA_PER_BLOCK:
                checksum_diffs.append((offset, val_18k, val_flex))
            else:
                data_diffs.append((offset, val_18k, val_flex))

        lines.append(f"- Block checksum differences: {len(checksum_diffs)}")
        lines.append(f"- Actual data differences: {len(data_diffs)}")
        lines.append("")

        if data_diffs:
            lines.append("### Data Differences (non-checksum)")
            lines.append("| Offset | Block | PosInBlock | 18kPV | FlexBOSS | Notes |")
            lines.append("|--------|-------|------------|-------|----------|-------|")
            for offset, val_18k, val_flex in data_diffs:
                block_idx = offset // BLOCK_SIZE
                pos_in_block = offset % BLOCK_SIZE
                note = ""
                # Check if this is a case diff (lowercase vs uppercase)
                if abs(val_18k - val_flex) == 32:
                    note = f"Case diff: '{chr(val_18k)}' vs '{chr(val_flex)}'"
                elif 0x20 <= val_18k < 0x7F and 0x20 <= val_flex < 0x7F:
                    note = f"ASCII: '{chr(val_18k)}' vs '{chr(val_flex)}'"
                lines.append(
                    f"| 0x{offset:04X} | {block_idx} | {pos_in_block} | "
                    f"0x{val_18k:02X} | 0x{val_flex:02X} | {note} |"
                )
            lines.append("")

    # DSP code differences
    dsp_diffs = [(o, a, b) for o, a, b in diffs if o >= DSP_CODE_START]
    lines.append("## DSP Code Region Differences")
    lines.append(f"Total byte differences in DSP region: {len(dsp_diffs)}")
    lines.append("")

    if dsp_diffs:
        # Group into contiguous runs
        runs: list[list[tuple[int, int, int]]] = []
        current_run: list[tuple[int, int, int]] = [dsp_diffs[0]]
        for d in dsp_diffs[1:]:
            if d[0] == current_run[-1][0] + 1:
                current_run.append(d)
            else:
                runs.append(current_run)
                current_run = [d]
        runs.append(current_run)

        lines.append(f"Grouped into {len(runs)} contiguous difference regions")
        lines.append("")

        # Show first 40 runs with details
        lines.append("### Difference Regions (first 40)")
        lines.append("| # | Start | End | Size | Notes |")
        lines.append("|---|-------|-----|------|-------|")
        for i, run in enumerate(runs[:40]):
            start = run[0][0]
            end = run[-1][0]
            size = len(run)
            note = ""

            # Check if this looks like calibration constants
            if size == 2:
                val_18k = (run[0][1] << 8) | run[1][1] if len(run) >= 2 else run[0][1]
                val_flex = (run[0][2] << 8) | run[1][2] if len(run) >= 2 else run[0][2]
                # Try LE
                val_18k_le = (
                    run[0][1] | (run[1][1] << 8) if len(run) >= 2 else run[0][1]
                )
                val_flex_le = (
                    run[0][2] | (run[1][2] << 8) if len(run) >= 2 else run[0][2]
                )
                note = f"BE: {val_18k} vs {val_flex}, LE: {val_18k_le} vs {val_flex_le}"
                # Check for power ratings
                for v in [val_18k, val_flex, val_18k_le, val_flex_le]:
                    if v in (18000, 21000, 12000, 6000, 1800, 2100):
                        note += f" *** POWER RATING {v}W ***"
            elif size <= 8:
                vals_18k = bytes(d[1] for d in run if d[1] >= 0)
                vals_flex = bytes(d[2] for d in run if d[2] >= 0)
                # Check for ASCII strings
                if all(0x20 <= b < 0x7F for b in vals_18k) and all(
                    0x20 <= b < 0x7F for b in vals_flex
                ):
                    note = f"ASCII: '{vals_18k.decode('ascii')}' vs '{vals_flex.decode('ascii')}'"
                else:
                    note = f"18k: {vals_18k.hex()} flex: {vals_flex.hex()}"

            lines.append(
                f"| {i:3d} | 0x{start:05X} | 0x{end:05X} | {size:4d} | {note} |"
            )
        lines.append("")

        # Search for power rating values
        lines.append("## Power Rating Value Search")
        lines.append("")
        power_values = {
            18000: "18kPV rated power",
            21000: "FlexBOSS21 rated power",
            12000: "12kPV rated power",
            6000: "6000XP rated power",
            5000: "5kW common limit",
            15000: "15kW AC charge max",
        }

        for target, desc in sorted(power_values.items()):
            # Search as 16-bit LE word
            target_le = struct.pack("<H", target & 0xFFFF)
            target_be = struct.pack(">H", target & 0xFFFF)

            # Also try 32-bit
            struct.pack("<I", target)
            struct.pack(">I", target)

            for name, fw_data in [("18kPV", data_18k), ("FlexBOSS", data_flex)]:
                positions_le = []
                positions_be = []
                pos = 0
                while True:
                    idx = fw_data.find(target_le, pos)
                    if idx == -1:
                        break
                    positions_le.append(idx)
                    pos = idx + 1
                pos = 0
                while True:
                    idx = fw_data.find(target_be, pos)
                    if idx == -1:
                        break
                    positions_be.append(idx)
                    pos = idx + 1

                if positions_le or positions_be:
                    lines.append(
                        f"  {target} ({desc}) in {name}: "
                        f"LE at {[f'0x{p:05X}' for p in positions_le[:5]]}, "
                        f"BE at {[f'0x{p:05X}' for p in positions_be[:5]]}"
                    )

        lines.append("")

        # Voltage/frequency threshold search
        lines.append("## Voltage/Frequency Threshold Search")
        lines.append("")

        thresholds = {
            2400: "240.0V (÷10, US split-phase)",
            1200: "120.0V (÷10, US L-N)",
            2300: "230.0V (÷10, EU L-N)",
            4160: "416.0V (÷10, bus voltage)",
            600: "60.0Hz (÷10) or 60Hz raw",
            500: "50.0Hz (÷10) or 50Hz raw",
            6000: "60.00Hz (÷100)",
            5000: "50.00Hz (÷100)",
            5600: "56.0V (÷10, battery charge cutoff)",
            4800: "48.0V (÷10, battery nominal)",
            5200: "52.0V (÷10, battery float)",
        }

        for target, desc in sorted(thresholds.items()):
            target_bytes = struct.pack("<H", target)
            for name, fw_data in [("18kPV", data_18k), ("FlexBOSS", data_flex)]:
                # Only search DSP region
                dsp_region = fw_data[DSP_CODE_START:]
                positions = []
                pos = 0
                while True:
                    idx = dsp_region.find(target_bytes, pos)
                    if idx == -1:
                        break
                    positions.append(DSP_CODE_START + idx)
                    pos = idx + 1
                if positions:
                    lines.append(
                        f"  {target} ({desc}) in {name} DSP: "
                        f"{len(positions)} hits, first at "
                        + ", ".join(f"0x{p:05X}" for p in positions[:5])
                    )

    return "\n".join(lines)


# ============================================================================
# Task 4: DSP Code Structure
# ============================================================================


def analyze_dsp_structure(data: bytes, name: str) -> str:
    """Analyze TI C28x DSP code structure."""
    lines: list[str] = []
    lines.append(f"# DSP Code Structure Analysis: {name}")
    lines.append("")

    dsp_region = data[DSP_CODE_START:]
    lines.append(f"DSP region starts at: 0x{DSP_CODE_START:04X}")
    lines.append(
        f"DSP region size: {len(dsp_region):,d} bytes ({len(dsp_region) // 2:,d} words)"
    )
    lines.append("")

    # Parse as 16-bit words
    words = []
    for i in range(0, len(dsp_region) - 1, 2):
        words.append(struct.unpack_from("<H", dsp_region, i)[0])

    # Count functions by finding RET/LRET/IRET instructions
    # C28x: RET = 0x0006 (some encodings), LRET = 0x0007, IRET = 0x0001
    # More accurate: RET can be 0xFF69, LRETC = 0x0007, LRET = 0x0006
    # Common C28x return encodings:
    ret_opcodes = {
        0xFF69: "LRETR (return from call, pop RPC)",
        0x0006: "LRET (long return)",
        0x0007: "LRETC (conditional long return)",
        0x0076: "RET (near return) [verify]",
    }

    lines.append("## Function Boundary Analysis")
    lines.append("")

    for opcode, desc in ret_opcodes.items():
        positions = [i for i, w in enumerate(words) if w == opcode]
        lines.append(f"Opcode 0x{opcode:04X} ({desc}): {len(positions)} occurrences")

    lines.append("")

    # Use LRETR (0xFF69) as primary function terminator
    lretr_positions = [i for i, w in enumerate(words) if w == 0xFF69]

    if lretr_positions:
        # Estimate function sizes from gaps between LRETR
        func_sizes = []
        for i in range(len(lretr_positions) - 1):
            size = (lretr_positions[i + 1] - lretr_positions[i]) * 2
            func_sizes.append(size)

        if func_sizes:
            lines.append(f"Estimated function count (by LRETR): {len(lretr_positions)}")
            lines.append(
                f"Average function size: {sum(func_sizes) / len(func_sizes):.0f} bytes"
            )
            lines.append(
                f"Median function size: {sorted(func_sizes)[len(func_sizes) // 2]} bytes"
            )
            lines.append(f"Min function size: {min(func_sizes)} bytes")
            lines.append(f"Max function size: {max(func_sizes)} bytes")
            lines.append("")

            # Function size distribution
            lines.append("### Function Size Distribution")
            size_buckets = Counter()
            for s in func_sizes:
                if s <= 16:
                    size_buckets["  0-16   bytes"] += 1
                elif s <= 64:
                    size_buckets[" 17-64   bytes"] += 1
                elif s <= 256:
                    size_buckets[" 65-256  bytes"] += 1
                elif s <= 1024:
                    size_buckets["257-1024 bytes"] += 1
                else:
                    size_buckets["1025+    bytes"] += 1

            lines.append("| Size Range | Count |")
            lines.append("|------------|-------|")
            for bucket in sorted(size_buckets.keys()):
                lines.append(f"| {bucket} | {size_buckets[bucket]} |")
            lines.append("")

    # Code vs data ratio
    lines.append("## Code vs Data Estimation")
    lines.append("")

    # Count instruction-like patterns vs data-like patterns
    # Instructions tend to have specific bit patterns
    # Data tends to be more uniform or contain ASCII
    instruction_count = 0
    data_count = 0
    ascii_count = 0

    for w in words:
        # Heuristic: common C28x instructions have specific high nibbles
        high = (w >> 12) & 0xF
        if high in (0x0, 0x1, 0x2, 0x5, 0x7, 0x8, 0xA, 0xB, 0xC, 0xF):
            instruction_count += 1
        else:
            data_count += 1
        # Check for ASCII pairs
        low_byte = w & 0xFF
        high_byte = (w >> 8) & 0xFF
        if 0x20 <= low_byte < 0x7F and 0x20 <= high_byte < 0x7F:
            ascii_count += 1

    total = instruction_count + data_count
    lines.append(
        f"Instruction-like words: {instruction_count:,d} ({instruction_count / total * 100:.1f}%)"
    )
    lines.append(f"Data-like words: {data_count:,d} ({data_count / total * 100:.1f}%)")
    lines.append(
        f"ASCII-pair words: {ascii_count:,d} ({ascii_count / total * 100:.1f}%)"
    )
    lines.append("")

    # Extract embedded strings
    lines.append("## Embedded Strings")
    lines.append("")

    # Search for ASCII strings (min length 4)
    strings_found: list[tuple[int, str]] = []
    i = 0
    while i < len(dsp_region):
        if 0x20 <= dsp_region[i] < 0x7F:
            start = i
            while i < len(dsp_region) and 0x20 <= dsp_region[i] < 0x7F:
                i += 1
            length = i - start
            if length >= 4:
                s = dsp_region[start:i].decode("ascii", errors="replace")
                strings_found.append((DSP_CODE_START + start, s))
        else:
            i += 1

    lines.append(f"Found {len(strings_found)} ASCII strings (4+ chars)")
    lines.append("")
    if strings_found:
        lines.append("| Offset | Length | String |")
        lines.append("|--------|--------|--------|")
        for offset, s in strings_found[:100]:
            # Escape pipe characters for markdown
            safe_s = s.replace("|", "\\|")
            lines.append(f"| 0x{offset:05X} | {len(s):>4d} | `{safe_s[:80]}` |")
    lines.append("")

    # Look for lookup tables (repeated structures with small increments)
    lines.append("## Lookup Table Detection")
    lines.append("")

    # Find regions where consecutive words form arithmetic progressions
    table_candidates: list[
        tuple[int, int, int, int]
    ] = []  # start, length, first_val, step
    i_word = 0
    while i_word < len(words) - 4:
        step = words[i_word + 1] - words[i_word]
        if 0 < abs(step) < 100:  # Reasonable step size for lookup table
            length = 2
            while (
                i_word + length < len(words)
                and words[i_word + length] - words[i_word + length - 1] == step
            ):
                length += 1
            if length >= 6:
                table_candidates.append((i_word, length, words[i_word], step))
                i_word += length
                continue
        i_word += 1

    if table_candidates:
        lines.append(
            f"Found {len(table_candidates)} potential lookup tables (6+ entries, constant step)"
        )
        lines.append(
            "| Word Offset | Byte Offset | Length | Start Val | Step | End Val |"
        )
        lines.append(
            "|-------------|-------------|--------|-----------|------|---------|"
        )
        for woff, length, first_val, step in table_candidates[:30]:
            byte_off = DSP_CODE_START + woff * 2
            end_val = first_val + (length - 1) * step
            lines.append(
                f"| {woff:>5d} | 0x{byte_off:05X} | {length:>4d} | "
                f"{first_val:>5d} | {step:>+4d} | {end_val:>5d} |"
            )
    else:
        lines.append("No constant-step lookup tables detected.")
    lines.append("")

    # Word frequency analysis for DSP region
    lines.append("## Word Frequency (DSP Region)")
    lines.append("")
    word_freq = Counter(words)
    lines.append("| Value (hex) | Count | % | Possible Meaning |")
    lines.append("|-------------|-------|---|------------------|")
    for val, cnt in word_freq.most_common(30):
        pct = cnt / len(words) * 100
        meaning = ""
        if val == 0xFFFF:
            meaning = "Unprogrammed flash / NOP"
        elif val == 0xFF69:
            meaning = "LRETR (function return)"
        elif val == 0x0000:
            meaning = "NOP / zero data"
        elif val == 0x7625:
            meaning = "C28x branch/call?"
        lines.append(f"| 0x{val:04X} | {cnt:>6d} | {pct:>5.2f} | {meaning} |")

    return "\n".join(lines)


# ============================================================================
# Task 5: Checksum Scheme
# ============================================================================


def extract_checksums(data_18k: bytes, data_flex: bytes) -> str:
    """Extract and analyze the block checksum scheme."""
    lines: list[str] = []
    lines.append("# Block Checksum Scheme Analysis")
    lines.append("")
    lines.append(
        f"Block size: {BLOCK_SIZE} bytes ({DATA_PER_BLOCK} data + {CHECKSUM_BYTES} checksum)"
    )
    lines.append("")

    for name, data in [("18kPV", data_18k), ("FlexBOSS", data_flex)]:
        total_blocks = len(data) // BLOCK_SIZE
        remainder = len(data) % BLOCK_SIZE

        lines.append(f"## {name}")
        lines.append(f"File size: {len(data):,d} bytes")
        lines.append(f"Complete blocks: {total_blocks}")
        lines.append(f"Remainder: {remainder} bytes")
        lines.append("")

        blocks: list[BlockChecksum] = []
        for i in range(total_blocks):
            block_start = i * BLOCK_SIZE
            data_start = block_start
            data_end = block_start + DATA_PER_BLOCK
            cksum_offset = data_end
            cksum_val = struct.unpack_from(">H", data, cksum_offset)[0]
            block_data = data[data_start:data_end]

            blocks.append(
                BlockChecksum(
                    block_index=i,
                    file_offset=block_start,
                    data_start=data_start,
                    data_end=data_end,
                    checksum_offset=cksum_offset,
                    checksum_value=cksum_val,
                    data=block_data,
                )
            )

        lines.append("### Block Table (all blocks)")
        lines.append(
            "| Block | File Offset | Checksum | Checksum (LE) | Data Sum16 | XOR w/0xA7E7 |"
        )
        lines.append(
            "|-------|-------------|----------|---------------|------------|--------------|"
        )

        for blk in blocks:
            # Try various checksum algorithms
            # Simple sum of all bytes mod 65536
            byte_sum = sum(blk.data) & 0xFFFF
            # XOR with key
            xor_key = blk.checksum_value ^ 0xA7E7

            # Try LE interpretation of checksum
            cksum_le = struct.unpack_from("<H", data, blk.checksum_offset)[0]

            lines.append(
                f"| {blk.block_index:>3d} | 0x{blk.file_offset:05X} | "
                f"0x{blk.checksum_value:04X} | 0x{cksum_le:04X} | "
                f"0x{byte_sum:04X} | 0x{xor_key:04X} |"
            )
        lines.append("")

    # Cross-model checksum comparison
    lines.append("## Cross-Model Checksum Comparison")
    lines.append("")

    n_blocks_18k = len(data_18k) // BLOCK_SIZE
    n_blocks_flex = len(data_flex) // BLOCK_SIZE
    min_blocks = min(n_blocks_18k, n_blocks_flex)

    lines.append("### XOR Between Matching Block Checksums")
    lines.append(
        "| Block | 18kPV Checksum | FlexBOSS Checksum | XOR | Data Identical? |"
    )
    lines.append(
        "|-------|----------------|-------------------|-----|-----------------|"
    )

    xor_values = []
    for i in range(min_blocks):
        ck_18k = struct.unpack_from(">H", data_18k, i * BLOCK_SIZE + DATA_PER_BLOCK)[0]
        ck_flex = struct.unpack_from(">H", data_flex, i * BLOCK_SIZE + DATA_PER_BLOCK)[
            0
        ]
        xor_val = ck_18k ^ ck_flex
        xor_values.append(xor_val)

        # Check if data is identical
        data_18k_block = data_18k[i * BLOCK_SIZE : i * BLOCK_SIZE + DATA_PER_BLOCK]
        data_flex_block = data_flex[i * BLOCK_SIZE : i * BLOCK_SIZE + DATA_PER_BLOCK]
        identical = data_18k_block == data_flex_block

        lines.append(
            f"| {i:>3d} | 0x{ck_18k:04X} | 0x{ck_flex:04X} | "
            f"0x{xor_val:04X} | {'Yes' if identical else 'No'} |"
        )

    lines.append("")

    # Verify 0xA7E7 key hypothesis
    lines.append("### XOR Key 0xA7E7 Verification")
    lines.append("")
    constant_xor = all(v == xor_values[0] for v in xor_values if v != 0)
    if constant_xor and xor_values[0] != 0:
        lines.append(f"All non-zero XOR values are constant: 0x{xor_values[0]:04X}")
    else:
        unique_xors = set(xor_values)
        lines.append(f"XOR values are NOT constant. Unique values: {len(unique_xors)}")
        xor_freq = Counter(xor_values)
        for val, cnt in xor_freq.most_common(10):
            lines.append(f"  0x{val:04X}: {cnt} blocks")
    lines.append("")

    # Try to identify the checksum algorithm
    lines.append("## Checksum Algorithm Analysis")
    lines.append("")

    # Test various algorithms on first few blocks of 18kPV
    algorithms = {}
    for i in range(min(5, n_blocks_18k)):
        block_start = i * BLOCK_SIZE
        block_data = data_18k[block_start : block_start + DATA_PER_BLOCK]
        stored_cksum = struct.unpack_from(">H", data_18k, block_start + DATA_PER_BLOCK)[
            0
        ]

        # Algorithm 1: Simple byte sum mod 65536
        byte_sum = sum(block_data) & 0xFFFF
        algorithms.setdefault("byte_sum", []).append(
            (i, stored_cksum, byte_sum, stored_cksum ^ byte_sum)
        )

        # Algorithm 2: Word sum (16-bit LE words)
        word_sum = 0
        for j in range(0, len(block_data) - 1, 2):
            word_sum = (word_sum + struct.unpack_from("<H", block_data, j)[0]) & 0xFFFF
        algorithms.setdefault("word_sum_le", []).append(
            (i, stored_cksum, word_sum, stored_cksum ^ word_sum)
        )

        # Algorithm 3: Word sum (16-bit BE words)
        word_sum_be = 0
        for j in range(0, len(block_data) - 1, 2):
            word_sum_be = (
                word_sum_be + struct.unpack_from(">H", block_data, j)[0]
            ) & 0xFFFF
        algorithms.setdefault("word_sum_be", []).append(
            (i, stored_cksum, word_sum_be, stored_cksum ^ word_sum_be)
        )

        # Algorithm 4: XOR of all bytes
        byte_xor = 0
        for b in block_data:
            byte_xor ^= b
        algorithms.setdefault("byte_xor", []).append(
            (i, stored_cksum, byte_xor & 0xFFFF, stored_cksum ^ (byte_xor & 0xFFFF))
        )

        # Algorithm 5: XOR of all 16-bit LE words
        word_xor = 0
        for j in range(0, len(block_data) - 1, 2):
            word_xor ^= struct.unpack_from("<H", block_data, j)[0]
        algorithms.setdefault("word_xor_le", []).append(
            (i, stored_cksum, word_xor, stored_cksum ^ word_xor)
        )

        # Algorithm 6: CRC-16/CCITT
        crc = 0xFFFF
        for b in block_data:
            crc ^= b << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        algorithms.setdefault("crc16_ccitt", []).append(
            (i, stored_cksum, crc, stored_cksum ^ crc)
        )

        # Algorithm 7: CRC-16/Modbus
        crc_mod = 0xFFFF
        for b in block_data:
            crc_mod ^= b
            for _ in range(8):
                if crc_mod & 0x0001:
                    crc_mod = (crc_mod >> 1) ^ 0xA001
                else:
                    crc_mod >>= 1
        algorithms.setdefault("crc16_modbus", []).append(
            (i, stored_cksum, crc_mod, stored_cksum ^ crc_mod)
        )

        # Algorithm 8: Simple complement of byte sum
        complement = (~byte_sum + 1) & 0xFFFF
        algorithms.setdefault("complement_byte_sum", []).append(
            (i, stored_cksum, complement, stored_cksum ^ complement)
        )

        # Algorithm 9: Word sum with seed 0xA7E7
        word_sum_seeded = 0xA7E7
        for j in range(0, len(block_data) - 1, 2):
            word_sum_seeded = (
                word_sum_seeded + struct.unpack_from("<H", block_data, j)[0]
            ) & 0xFFFF
        algorithms.setdefault("word_sum_seeded_a7e7", []).append(
            (i, stored_cksum, word_sum_seeded, stored_cksum ^ word_sum_seeded)
        )

        # Algorithm 10: XOR all words then XOR with 0xA7E7
        word_xor_keyed = word_xor ^ 0xA7E7
        algorithms.setdefault("word_xor_keyed_a7e7", []).append(
            (i, stored_cksum, word_xor_keyed, stored_cksum ^ word_xor_keyed)
        )

    for algo_name, results in algorithms.items():
        lines.append(f"### Algorithm: {algo_name}")
        lines.append("| Block | Stored | Computed | XOR |")
        lines.append("|-------|--------|----------|-----|")
        constant_diff = True
        first_xor = results[0][3]
        for blk_i, stored, computed, xor_diff in results:
            if xor_diff != first_xor:
                constant_diff = False
            match = "MATCH!" if stored == computed else ""
            lines.append(
                f"| {blk_i} | 0x{stored:04X} | 0x{computed:04X} | 0x{xor_diff:04X} {match} |"
            )
        if constant_diff:
            lines.append(
                f"**Constant XOR offset: 0x{first_xor:04X}** (algorithm may be correct with key)"
            )
        elif any(s == c for _, s, c, _ in results):
            lines.append("**Direct match found on some blocks!**")
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    """Run all analysis tasks."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading firmware files...")
    data_18k = load_firmware(FW_18KPV)
    data_flex = load_firmware(FW_FLEX)
    print(f"  18kPV:    {len(data_18k):>10,d} bytes")
    print(f"  FlexBOSS: {len(data_flex):>10,d} bytes")

    # Task 1: Register Map
    print("\n[1/5] Extracting shared register map...")
    result = extract_register_map(data_18k)
    (OUT_DIR / "01_register_map.md").write_text(result)
    print(f"  Written to {OUT_DIR / '01_register_map.md'}")

    # Task 2: Config Metadata
    print("\n[2/5] Decoding config metadata...")
    result = decode_config_metadata(data_18k)
    (OUT_DIR / "02_config_metadata.md").write_text(result)
    print(f"  Written to {OUT_DIR / '02_config_metadata.md'}")

    # Task 3: Binary Comparison
    print("\n[3/5] Comparing firmwares...")
    result = compare_firmwares(data_18k, data_flex)
    (OUT_DIR / "03_firmware_comparison.md").write_text(result)
    print(f"  Written to {OUT_DIR / '03_firmware_comparison.md'}")

    # Task 4: DSP Structure (both)
    print("\n[4/5] Analyzing DSP code structure...")
    for name, fw_data, suffix in [
        ("18kPV", data_18k, "18kpv"),
        ("FlexBOSS21", data_flex, "flexboss"),
    ]:
        result = analyze_dsp_structure(fw_data, name)
        fname = f"04_dsp_structure_{suffix}.md"
        (OUT_DIR / fname).write_text(result)
        print(f"  Written to {OUT_DIR / fname}")

    # Task 5: Checksum Scheme
    print("\n[5/5] Extracting checksum scheme...")
    result = extract_checksums(data_18k, data_flex)
    (OUT_DIR / "05_checksum_scheme.md").write_text(result)
    print(f"  Written to {OUT_DIR / '05_checksum_scheme.md'}")

    print("\nAll analysis complete!")
    print(f"Output directory: {OUT_DIR}")


if __name__ == "__main__":
    main()
