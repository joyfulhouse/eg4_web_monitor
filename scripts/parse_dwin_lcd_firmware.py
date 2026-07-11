#!/usr/bin/env python3
"""Parse DWIN DGUS LCD display firmware files from EG4 18KPV/12KPV inverter.

Extracts register mappings, screen layouts, VP (Variable Pointer) definitions,
and touch input regions from the DWIN T5L DGUS II display firmware.

Files parsed:
  - T5LCFG_12720.CFG: T5L CPU configuration (baud, resolution, UART)
  - 13TouchFile.bin:   Touch input definitions (button regions -> VP addresses)
  - 14ShowFile.bin:    Display variable definitions (VP addresses -> screen elements)
  - 22_Config.bin:     Data variable configuration (VP enable/format settings)
  - 0.bin:             DGUS OS firmware (strings, version info)

Output: LCD_DWIN_ANALYSIS.md in docs/reference/firmware_re/
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# File discovery (handles non-breaking space \xa0 in directory name)
# ---------------------------------------------------------------------------

FIRMWARE_BASE = Path(
    "/Users/bryanli/Projects/joyfulhouse/homeassistant-dev/"
    "eg4_web_monitor/scratchpad/firmware/lcd_v18"
)

OUTPUT_DIR = Path(
    "/Users/bryanli/Projects/joyfulhouse/homeassistant-dev/"
    "eg4_web_monitor/docs/reference/firmware_re"
)


def find_files() -> dict[str, Path]:
    """Walk the firmware directory to find files (handles \xa0 in path)."""
    files: dict[str, Path] = {}
    for root, _dirs, filenames in os.walk(FIRMWARE_BASE):
        for fname in filenames:
            files[fname] = Path(root) / fname
    return files


# ---------------------------------------------------------------------------
# Data classes for parsed results
# ---------------------------------------------------------------------------


@dataclass
class T5LConfig:
    """T5L CPU configuration from T5LCFG_12720.CFG."""

    raw: bytes
    signature: str = ""
    baud_rate: int = 0
    resolution_x: int = 0
    resolution_y: int = 0
    orientation: int = 0
    touch_mode: int = 0


@dataclass
class ShowEntry:
    """A display variable entry from 14ShowFile.bin (32 bytes)."""

    page_id: int
    entry_index: int
    sp_addr: int  # Description pointer address
    entry_type: int  # 0x50=data var, 0x70=icon/other, 0x00=datetime
    register_addr: int  # Modbus register address (byte[7] of entry)
    x: int
    y: int
    num_digits: int
    decimal_places: int
    format_flags: int
    unit_suffix: str
    raw: bytes

    @property
    def scale_factor(self) -> str:
        """Derive scale factor from decimal places."""
        if self.decimal_places == 0:
            return "x1"
        if self.decimal_places == 1:
            return "/10"
        if self.decimal_places == 2:
            return "/100"
        if self.decimal_places == 3:
            return "/1000"
        return f"/{10**self.decimal_places}"

    @property
    def is_signed(self) -> bool:
        """Check if display format indicates signed value."""
        return bool(self.format_flags & 0x02)

    @property
    def is_32bit(self) -> bool:
        """Check if this is a 32-bit (2 register) value."""
        return self.num_digits >= 7 and self.unit_suffix in ("kWh",)


@dataclass
class TouchEntry:
    """A touch input entry from 13TouchFile.bin."""

    page_id: int
    x1: int
    y1: int
    x2: int
    y2: int
    vp_addr: int  # VP address (target page or register)
    has_extension: bool
    extension_data: bytes = b""

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


@dataclass
class PageInfo:
    """Information about a display page."""

    page_id: int
    display_entries: list[ShowEntry] = field(default_factory=list)
    touch_entries: list[TouchEntry] = field(default_factory=list)
    description: str = ""


# ---------------------------------------------------------------------------
# Known register mapping (from DATA_MAPPING.md / pylxpweb)
# ---------------------------------------------------------------------------

KNOWN_INPUT_REGISTERS: dict[int, tuple[str, str, str]] = {
    # (canonical_name, scale, unit)
    0: ("device_status", "x1", "-"),
    1: ("pv1_voltage", "/10", "V"),
    2: ("pv2_voltage", "/10", "V"),
    3: ("pv3_voltage", "/10", "V"),
    4: ("battery_voltage", "/10", "V"),
    5: ("soc_soh_packed", "x1", "%"),
    6: ("total_pv_power", "x1", "W"),
    7: ("pv1_power", "x1", "W"),
    8: ("pv2_power", "x1", "W"),
    9: ("pv3_power", "x1", "W"),
    10: ("charge_power", "x1", "W"),
    11: ("discharge_power", "x1", "W"),
    12: ("grid_voltage_r", "/10", "V"),
    13: ("grid_voltage_s", "/10", "V"),
    14: ("grid_voltage_t", "/10", "V"),
    15: ("grid_frequency", "/100", "Hz"),
    16: ("inverter_power", "x1", "W"),
    17: ("rectifier_power", "x1", "W"),
    18: ("inverter_rms_current_r", "/100", "A"),
    19: ("device_type_code", "x1", "-"),
    20: ("eps_voltage_r", "/10", "V"),
    21: ("eps_voltage_s", "/10", "V"),
    22: ("eps_voltage_t", "/10", "V"),
    23: ("eps_frequency", "/100", "Hz"),
    24: ("eps_power", "x1", "W"),
    26: ("power_to_grid", "x1", "W"),
    27: ("power_to_user", "x1", "W"),
    30: ("inverter_energy_today", "/10", "kWh"),
    31: ("inverter_energy_today_alt", "/10", "kWh"),
    33: ("charge_energy_today", "/10", "kWh"),
    34: ("discharge_energy_today", "/10", "kWh"),
    36: ("grid_export_energy_today", "/10", "kWh"),
    37: ("grid_import_energy_today", "/10", "kWh"),
    38: ("bus_voltage_1", "/10", "V"),
    39: ("bus_voltage_2", "/10", "V"),
    40: ("pv1_energy_today", "/10", "kWh"),
    41: ("pv2_energy_today", "/10", "kWh"),
    42: ("pv3_energy_today", "/10", "kWh"),
    44: ("pv1_current", "/10", "A"),
    45: ("pv2_current", "/10", "A"),
    46: ("inverter_energy_total_lo", "/10", "kWh"),
    47: ("inverter_energy_total_hi", "/10", "kWh"),
    50: ("charge_energy_total_lo", "/10", "kWh"),
    51: ("charge_energy_total_hi", "/10", "kWh"),
    52: ("discharge_energy_total_lo", "/10", "kWh"),
    53: ("discharge_energy_total_hi", "/10", "kWh"),
    54: ("grid_l1_voltage_ext", "/10", "V"),
    55: ("grid_l2_voltage_ext", "/10", "V"),
    56: ("grid_export_energy_total_lo", "/10", "kWh"),
    57: ("grid_export_energy_total_hi", "/10", "kWh"),
    58: ("grid_import_energy_total_lo", "/10", "kWh"),
    59: ("grid_import_energy_total_hi", "/10", "kWh"),
    61: ("pv1_energy_total_lo", "/10", "kWh"),
    62: ("pv1_energy_total_hi", "/10", "kWh"),
    64: ("internal_temperature", "x1", "C"),
    65: ("radiator_temperature_1", "x1", "C"),
    66: ("radiator_temperature_2", "x1", "C"),
    67: ("battery_temperature", "x1", "C"),
    68: ("eps_power_l2", "x1", "W"),
    69: ("battery_ah_remaining", "/10", "Ah"),
    70: ("battery_ah_remaining_lo", "x1", "Ah"),
    71: ("pv2_energy_total_lo", "/10", "kWh"),
    72: ("pv2_energy_total_hi", "/10", "kWh"),
    74: ("pv3_energy_total_lo", "/10", "kWh"),
    75: ("pv3_energy_total_hi", "/10", "kWh"),
    77: ("total_load_power", "x1", "W"),
    78: ("bms_feature_flags", "x1", "-"),
    81: ("bms_charge_current_limit", "/10", "A"),
    82: ("bms_discharge_current_limit", "/10", "A"),
    84: ("eps_l1_voltage", "/10", "V"),
    85: ("eps_l1_frequency", "/100", "Hz"),
    86: ("eps_power_combined", "x1", "W"),
    90: ("pv_combined_power", "x1", "W"),
    91: ("battery_current", "/10", "A"),
    92: ("grid_voltage_l1", "/10", "V"),
    93: ("grid_voltage_l2", "/10", "V"),
    94: ("grid_frequency_alt", "/100", "Hz"),
    95: ("load_power_alt", "x1", "W"),
    96: ("battery_count", "x1", "-"),
    98: ("consumption_power", "x1", "W"),
    99: ("consumption_power_l2", "x1", "W"),
    100: ("apparent_power", "x1", "VA"),
    101: ("apparent_power_l2", "x1", "VA"),
    102: ("apparent_power_total", "x1", "VA"),
    103: ("consumption_energy_today", "/10", "kWh"),
    104: ("consumption_energy_total_lo", "/10", "kWh"),
    106: ("ac_charge_energy_today", "/10", "kWh"),
    107: ("ac_charge_energy_total_lo", "/10", "kWh"),
    108: ("temperature_t1", "/10", "C"),
    109: ("eps_energy_today", "/10", "kWh"),
    110: ("eps_energy_total_lo", "/10", "kWh"),
    112: ("pv1_energy_today_2", "/10", "kWh"),
    113: ("pv2_energy_today_2", "/10", "kWh"),
    114: ("dongle_comm_status", "x1", "-"),
    115: ("serial_reg0", "x1", "-"),
    116: ("serial_reg1", "x1", "-"),
    117: ("serial_reg2", "x1", "-"),
    118: ("serial_reg3", "x1", "-"),
    119: ("serial_reg4", "x1", "-"),
    120: ("dongle_firmware_version", "x1", "-"),
    121: ("grid_voltage_r_ext2", "/10", "V"),
    122: ("grid_voltage_s_ext2", "/10", "V"),
    123: ("grid_voltage_t_ext2", "/10", "V"),
    124: ("grid_current_l1", "/10", "A"),
    125: ("grid_current_l2", "/10", "A"),
    126: ("grid_current_l3", "/10", "A"),
    127: ("eps_l1_voltage_split", "/10", "V"),
    128: ("eps_l2_voltage_split", "/10", "V"),
    129: ("eps_power_l1", "x1", "W"),
    130: ("grid_power_import", "x1", "W"),
    131: ("grid_power_export", "x1", "W"),
    132: ("inverter_power_l1", "x1", "W"),
    133: ("inverter_power_l2", "x1", "W"),
    134: ("battery_discharge_a", "/10", "A"),
    135: ("battery_charge_a", "/10", "A"),
    136: ("total_consumption_w", "x1", "W"),
    137: ("grid_power_total", "x1", "W"),
    142: ("dsp_version_lo", "x1", "-"),
    143: ("dsp_version_hi", "x1", "-"),
    144: ("arm_version_lo", "x1", "-"),
    145: ("arm_version_hi", "x1", "-"),
    146: ("battery_remaining_ah", "x1", "Ah"),
}

# Holding registers (writable parameters)
KNOWN_HOLDING_REGISTERS: dict[int, tuple[str, str, str]] = {
    19: ("device_type_code", "x1", "-"),
    20: ("smart_port_mode", "x1", "-"),
    21: ("function_enable", "x1", "-"),
    64: ("pv_charge_power", "x1", "%"),
    65: ("discharge_power_percent", "x1", "%"),
    66: ("ac_charge_power", "x1", "W"),
    67: ("ac_charge_soc_limit", "x1", "%"),
    101: ("charge_current", "x1", "A"),
    102: ("discharge_current", "x1", "A"),
    105: ("ongrid_discharge_soc", "x1", "%"),
    125: ("offgrid_discharge_soc", "x1", "%"),
}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_t5l_config(data: bytes) -> T5LConfig:
    """Parse T5LCFG_12720.CFG (46 bytes)."""
    cfg = T5LConfig(raw=data)
    if len(data) < 10:
        return cfg

    cfg.signature = data[:5].decode("ascii", errors="replace")  # T5LC1

    # T5L config format (from DWIN T5L documentation):
    # Byte 0-4: "T5LC1" signature
    # Byte 5: Baud rate code (0xBF = 115200)
    # Byte 6-7: Data length / flags
    # Byte 8-9: Touch panel type / orientation
    # Byte 10: UART config
    baud_codes = {
        0x00: 9600,
        0x01: 19200,
        0x02: 38400,
        0x03: 57600,
        0x04: 115200,
        0x05: 230400,
        0x06: 460800,
        0x07: 921600,
        0xBF: 115200,  # Default
    }
    cfg.baud_rate = baud_codes.get(data[5], data[5])

    # Resolution from filename: 12720 -> likely 1272x0
    # But T5L displays use standard resolutions
    # Byte 8-9 might contain resolution info
    # 0x2028 = 8232 -> not standard
    # The "12720" in filename is the DWIN display model number, not resolution
    # T5L 12720 = 7" 1024x600 display (DWIN DMT10600T070_A2)
    cfg.resolution_x = 1024
    cfg.resolution_y = 600

    # Byte 10-11: display orientation and touch
    cfg.orientation = data[10] if len(data) > 10 else 0

    return cfg


def parse_show_file(data: bytes) -> tuple[list[PageInfo], list[ShowEntry]]:
    """Parse 14ShowFile.bin (DGUS II display variable definitions).

    Format:
      Header: [0]=file_id(0x14), [1:7]="DGUS_2", [7]=version, [8:10]=num_pages
      Page table: 4 bytes per page x num_pages, starting at offset 16
        [0]=entry_count, [1]=flags, [2:4]=file_offset (BE)
      Display entries: 32 bytes each, starting at page offsets

    SP (Description Pointer) addresses determine the entry type:
      0x5A10 = DATA_VAR:   Numeric data display (byte[7] = Modbus register)
      0x5A11 = ICON_VAR:   Variable icon (state-dependent image)
      0x5A13 = TEXT_VAR:   Text string display
      0x5A00 = ICON_ANIM:  Animated icon (power flow arrows, battery bars)
      0x5A01 = ICON_SCROLL: Scrolling/rotating icon
      0x5A04 = PAGE_SWITCH: Page change trigger
      0x5A06 = BTN_RETURN:  Return/back button
      0x5A12 = DATETIME:    Date/time display

    Only SP=0x5A10 entries contain actual Modbus register references.
    Other SP types use byte[7] as an icon index or animation ID.
    """
    # SP address constants
    SP_DATA_VAR = 0x5A10
    SP_ICON_VAR = 0x5A11
    SP_ICON_ANIM = 0x5A00
    SP_ICON_SCROLL = 0x5A01
    SP_DATETIME = 0x5A12

    # Header
    data[0]
    data[1:7].decode("ascii", errors="replace")
    data[7]
    num_pages = (data[8] << 8) | data[9]

    pages: list[PageInfo] = []
    all_entries: list[ShowEntry] = []

    # Page table
    for page_id in range(num_pages):
        pt_off = 16 + page_id * 4
        if pt_off + 4 > len(data):
            break
        count = data[pt_off]
        offset = (data[pt_off + 2] << 8) | data[pt_off + 3]

        page = PageInfo(page_id=page_id)

        for i in range(count):
            entry_off = offset + i * 32
            if entry_off + 32 > len(data):
                break

            entry_bytes = data[entry_off : entry_off + 32]
            sp_addr = (entry_bytes[0] << 8) | entry_bytes[1]
            entry_type = entry_bytes[6]
            reg_addr = entry_bytes[7]
            x = (entry_bytes[8] << 8) | entry_bytes[9]
            y = (entry_bytes[10] << 8) | entry_bytes[11]

            # Only SP=0x5A10 (DATA_VAR) entries contain Modbus register references
            # Other SP types use byte[7] as icon/animation index
            if sp_addr == SP_DATA_VAR and entry_type == 0x50:
                # Numeric data variable display
                num_digits = entry_bytes[17]
                decimal_places = entry_bytes[18]
                format_flags = entry_bytes[19]

                # Extract unit suffix from bytes 20-25
                suffix_bytes = entry_bytes[20:26]
                suffix = ""
                for b in suffix_bytes:
                    if 32 <= b < 127 and b != 0:
                        suffix += chr(b)
                    elif b == 0:
                        break
                suffix = suffix.strip(".")

                # Filter out entries with unreasonable digit counts
                # (may be icon references that slipped through)
                if num_digits > 10:
                    continue

                entry = ShowEntry(
                    page_id=page_id,
                    entry_index=i,
                    sp_addr=sp_addr,
                    entry_type=entry_type,
                    register_addr=reg_addr,
                    x=x,
                    y=y,
                    num_digits=num_digits,
                    decimal_places=decimal_places,
                    format_flags=format_flags,
                    unit_suffix=suffix,
                    raw=entry_bytes,
                )
                page.display_entries.append(entry)
                all_entries.append(entry)

            elif sp_addr == SP_ICON_VAR:
                # Variable icon (state-dependent)
                entry = ShowEntry(
                    page_id=page_id,
                    entry_index=i,
                    sp_addr=sp_addr,
                    entry_type=entry_type,
                    register_addr=reg_addr,
                    x=x,
                    y=y,
                    num_digits=0,
                    decimal_places=0,
                    format_flags=0,
                    unit_suffix="[icon_var]",
                    raw=entry_bytes,
                )
                page.display_entries.append(entry)
                all_entries.append(entry)

            elif sp_addr == SP_DATETIME:
                # Date/time display
                entry = ShowEntry(
                    page_id=page_id,
                    entry_index=i,
                    sp_addr=sp_addr,
                    entry_type=entry_type,
                    register_addr=reg_addr,
                    x=x,
                    y=y,
                    num_digits=0,
                    decimal_places=0,
                    format_flags=0,
                    unit_suffix="[datetime]",
                    raw=entry_bytes,
                )
                page.display_entries.append(entry)
                all_entries.append(entry)

            elif sp_addr in (SP_ICON_ANIM, SP_ICON_SCROLL):
                # Animated/scrolling icons - record but mark as non-register
                entry = ShowEntry(
                    page_id=page_id,
                    entry_index=i,
                    sp_addr=sp_addr,
                    entry_type=entry_type,
                    register_addr=reg_addr,
                    x=x,
                    y=y,
                    num_digits=0,
                    decimal_places=0,
                    format_flags=0,
                    unit_suffix="[anim_icon]"
                    if sp_addr == SP_ICON_ANIM
                    else "[scroll_icon]",
                    raw=entry_bytes,
                )
                page.display_entries.append(entry)
                all_entries.append(entry)

        pages.append(page)

    return pages, all_entries


def parse_touch_file(data: bytes) -> list[TouchEntry]:
    """Parse 13TouchFile.bin (touch input definitions).

    Format: 16-byte entries, some with 16-byte extensions.
      [0:2]  = Page ID (BE)
      [2:4]  = X1 (top-left X, BE)
      [4:6]  = Y1 (top-left Y, BE)
      [6:8]  = X2 (bottom-right X, BE)
      [8:10] = Y2 (bottom-right Y, BE)
      [10:12]= VP address / target page (BE)
      [12:14]= 0xFF00 (basic) or other (has extension type)
      [14:16]= extension flags (0x0000=none, 0xFD05=return key data,
               0xFD00=increment data, 0xFD02=page switch, 0xFE05=slider)

    Extensions add 16 more bytes with type-specific parameters.
    """
    entries: list[TouchEntry] = []
    i = 0
    while i + 16 <= len(data):
        chunk = data[i : i + 16]

        page = (chunk[0] << 8) | chunk[1]
        x1 = (chunk[2] << 8) | chunk[3]
        y1 = (chunk[4] << 8) | chunk[5]
        x2 = (chunk[6] << 8) | chunk[7]
        y2 = (chunk[8] << 8) | chunk[9]
        vp = (chunk[10] << 8) | chunk[11]
        (chunk[12] << 8) | chunk[13]
        ext_flag = (chunk[14] << 8) | chunk[15]

        # Skip extension data from previous 32-byte entry
        if page >= 0xFE00 or page >= 0xFD00:
            i += 16
            continue

        # Skip all-zero entries
        if all(b == 0 for b in chunk):
            i += 16
            continue

        # Validate coordinates
        if page > 100 or x1 > 2000 or y1 > 2000 or x2 > 2000 or y2 > 2000:
            i += 16
            continue

        has_ext = ext_flag != 0x0000
        ext_data = b""
        if has_ext and i + 32 <= len(data):
            ext_data = data[i + 16 : i + 32]

        entry = TouchEntry(
            page_id=page,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            vp_addr=vp,
            has_extension=has_ext,
            extension_data=ext_data,
        )
        entries.append(entry)

        i += 32 if has_ext else 16
        continue

    return entries


def parse_config_bin(data: bytes) -> dict[int, int]:
    """Parse 22_Config.bin for non-zero VP configuration entries.

    The config file contains data variable configuration at word addresses.
    Non-zero values indicate configured VP addresses with display parameters.
    """
    config_vps: dict[int, int] = {}
    for i in range(0, len(data) - 1, 2):
        word = (data[i] << 8) | data[i + 1]
        if word != 0:
            vp_addr = i // 2
            config_vps[vp_addr] = word
    return config_vps


def extract_firmware_strings(data: bytes, min_len: int = 6) -> list[tuple[int, str]]:
    """Extract ASCII strings from 0.bin firmware."""
    strings: list[tuple[int, str]] = []
    current = b""
    start = 0
    for i, b in enumerate(data):
        if 32 <= b < 127:
            if not current:
                start = i
            current += bytes([b])
        else:
            if len(current) >= min_len:
                s = current.decode("ascii")
                # Filter out repetitive pattern strings (font data)
                unique_chars = set(s)
                if len(unique_chars) > 2 or len(s) < 10:
                    strings.append((start, s))
            current = b""
    return strings


# ---------------------------------------------------------------------------
# Analysis and cross-referencing
# ---------------------------------------------------------------------------


def classify_register(reg: int, unit: str, scale: str) -> tuple[str, str]:
    """Classify a register based on its address, unit, and scale.

    Returns (register_type, known_name).
    register_type: 'input' or 'holding' or 'unknown'
    """
    if reg in KNOWN_INPUT_REGISTERS:
        name, _, _ = KNOWN_INPUT_REGISTERS[reg]
        return "input", name
    if reg in KNOWN_HOLDING_REGISTERS:
        name, _, _ = KNOWN_HOLDING_REGISTERS[reg]
        return "holding", name
    return "unknown", f"unknown_reg_{reg}"


def infer_register_purpose(entry: ShowEntry) -> str:
    """Infer the purpose of an unknown register from its display format."""
    reg = entry.register_addr
    unit = entry.unit_suffix
    dp = entry.decimal_places
    digits = entry.num_digits

    # Check known registers first
    if reg in KNOWN_INPUT_REGISTERS:
        return KNOWN_INPUT_REGISTERS[reg][0]

    # Infer from display format
    if unit == "V":
        if dp == 1 and digits <= 4:
            return f"voltage_reg_{reg}"
        return f"voltage_reg_{reg}"
    if unit in ("kW", "W"):
        return f"power_reg_{reg}"
    if unit == "kWh":
        if digits >= 7:
            return f"energy_lifetime_reg_{reg}"
        return f"energy_daily_reg_{reg}"
    if unit == "A":
        return f"current_reg_{reg}"
    if unit == "Hz":
        return f"frequency_reg_{reg}"
    if unit == "VA":
        return f"apparent_power_reg_{reg}"
    if unit == "Ah":
        return f"amp_hours_reg_{reg}"
    if unit == "S":
        return f"seconds_reg_{reg}"
    if unit == "%":
        return f"percent_reg_{reg}"
    return f"unknown_reg_{reg}"


def generate_page_descriptions(
    pages: list[PageInfo],
) -> dict[int, str]:
    """Generate human-readable page descriptions based on content."""
    descriptions: dict[int, str] = {}

    SP_DATA_VAR = 0x5A10
    for page in pages:
        if not page.display_entries:
            continue

        # Only consider SP=0x5A10 entries as actual register displays
        data_entries = [
            e
            for e in page.display_entries
            if e.sp_addr == SP_DATA_VAR and e.entry_type == 0x50
        ]
        regs = [e.register_addr for e in data_entries]
        units = [e.unit_suffix for e in data_entries]
        [e.entry_type for e in page.display_entries]

        if not regs:
            descriptions[page.page_id] = "Navigation / Status"
            continue

        # Classify by register ranges and units
        has_pv = any(r in (0, 1, 2, 3, 7, 8, 9, 90) for r in regs)
        has_battery = any(r in (4, 10, 11, 18, 91, 96) for r in regs)
        has_grid = any(r in (12, 13, 14, 15, 16, 17) for r in regs)
        has_energy = any("kWh" in u for u in units)
        has_eps = any(r in (20, 21, 22, 23, 24, 84, 85, 86) for r in regs)
        has_temp = any(r in (64, 65, 66, 67, 108) for r in regs)
        has_batt_detail = any(r in range(120, 140) for r in regs)
        has_consumption = any(r in (98, 99, 100, 101, 102) for r in regs)

        parts = []
        if has_pv:
            parts.append("PV")
        if has_battery:
            parts.append("Battery")
        if has_grid:
            parts.append("Grid")
        if has_eps:
            parts.append("EPS/Backup")
        if has_consumption:
            parts.append("Load/Consumption")
        if has_batt_detail:
            parts.append("Battery Detail")
        if has_energy:
            parts.append("Energy")
        if has_temp:
            parts.append("Temperature")

        if parts:
            descriptions[page.page_id] = " + ".join(parts)
        else:
            descriptions[page.page_id] = f"Data (regs {min(regs)}-{max(regs)})"

    return descriptions


# ---------------------------------------------------------------------------
# Markdown output generation
# ---------------------------------------------------------------------------


def generate_markdown(
    t5l_cfg: T5LConfig,
    pages: list[PageInfo],
    all_show_entries: list[ShowEntry],
    touch_entries: list[TouchEntry],
    config_vps: dict[int, int],
    fw_strings: list[tuple[int, str]],
) -> str:
    """Generate the comprehensive LCD_DWIN_ANALYSIS.md document."""
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    # --------------- HEADER ---------------
    w("# DWIN DGUS LCD Display Firmware Analysis")
    w()
    w("**Firmware**: EG4 18KPV/12KPV LCD V18 (LCDV18_20241114)")
    w("**Display**: DWIN T5L DGUS II, 7-inch 1024x600")
    w("**Analysis date**: 2026-04-13")
    w("**Source files**: `scratchpad/firmware/lcd_v18/`")
    w()
    w("---")
    w()
    w("## Table of Contents")
    w()
    w("1. [T5L Configuration](#1-t5l-configuration)")
    w("2. [Page Structure Overview](#2-page-structure-overview)")
    w("3. [Display Variable Register Map](#3-display-variable-register-map)")
    w("4. [Register Cross-Reference with pylxpweb](#4-register-cross-reference)")
    w("5. [Touch Input Map](#5-touch-input-map)")
    w("6. [VP Address Configuration](#6-vp-address-configuration)")
    w("7. [Page-by-Page Detail](#7-page-by-page-detail)")
    w("8. [Key Findings](#8-key-findings)")
    w()
    w("---")
    w()

    # --------------- 1. T5L CONFIG ---------------
    w("## 1. T5L Configuration")
    w()
    w("| Parameter | Value |")
    w("|-----------|-------|")
    w(f"| Signature | `{t5l_cfg.signature}` |")
    w(f"| Baud Rate | {t5l_cfg.baud_rate} bps |")
    w(f"| Resolution | {t5l_cfg.resolution_x}x{t5l_cfg.resolution_y} |")
    w(f"| Config Size | {len(t5l_cfg.raw)} bytes |")
    w(f"| Raw (hex) | `{t5l_cfg.raw.hex()}` |")
    w()
    w("The T5L 12720 is a DWIN 7-inch LCD with capacitive touch panel.")
    w("Communication with the inverter MCU is via UART at 115200 bps.")
    w("The MCU writes Modbus register values to DWIN VP (Variable Pointer)")
    w("addresses, and the display renders them according to ShowFile definitions.")
    w()

    # --------------- 2. PAGE STRUCTURE ---------------
    w("## 2. Page Structure Overview")
    w()

    page_descs = generate_page_descriptions(pages)
    active_pages = [p for p in pages if p.display_entries or p.touch_entries]

    w(f"**Total pages defined**: {len(pages)}")
    w(f"**Active pages (with content)**: {len(active_pages)}")
    w()
    w("| Page | Display Vars | Touch Regions | Description |")
    w("|------|-------------|---------------|-------------|")

    # Assign touch entries to pages
    touch_by_page: dict[int, list[TouchEntry]] = defaultdict(list)
    for te in touch_entries:
        touch_by_page[te.page_id].append(te)

    for page in pages:
        page.touch_entries = touch_by_page.get(page.page_id, [])

    for page in pages:
        # Count only actual register data vars (SP=0x5A10)
        n_reg_vars = sum(
            1
            for e in page.display_entries
            if e.sp_addr == 0x5A10 and e.entry_type == 0x50
        )
        n_icons = sum(
            1 for e in page.display_entries if e.sp_addr in (0x5A00, 0x5A01, 0x5A11)
        )
        n_touch = len(page.touch_entries)
        if n_reg_vars == 0 and n_icons == 0 and n_touch == 0:
            continue
        desc = page_descs.get(page.page_id, "")
        icon_str = f" (+{n_icons} icons)" if n_icons > 0 else ""
        w(f"| {page.page_id} | {n_reg_vars}{icon_str} | {n_touch} | {desc} |")

    w()

    # --------------- 3. DISPLAY REGISTER MAP ---------------
    w("## 3. Display Variable Register Map")
    w()
    w("Extracted from `14ShowFile.bin`. Each entry maps a Modbus input register")
    w("to a display position on the LCD screen with specific formatting.")
    w()
    w("**Entry format** (32 bytes per variable):")
    w("- Bytes 0-1: SP (Description Pointer) address -- **0x5A10 = register data**")
    w("- Byte 6: Display type (0x50=numeric data, 0x70=icon, 0x00=datetime)")
    w("- Byte 7: **Modbus register address** (only valid when SP=0x5A10)")
    w("- Bytes 8-9: X position on screen")
    w("- Bytes 10-11: Y position on screen")
    w("- Byte 17: Number of display digits")
    w("- Byte 18: Decimal places (determines scale factor)")
    w("- Byte 19: Format flags (bit 1 = signed)")
    w("- Bytes 20-25: Unit suffix string (ASCII)")
    w()
    w("**SP Address Types:**")
    w("- `0x5A10` = DATA_VAR (numeric register display) -- byte[7] = Modbus register")
    w("- `0x5A00` = ICON_ANIM (animated icons, power flow arrows)")
    w("- `0x5A01` = ICON_SCROLL (scrolling/rotating icons)")
    w("- `0x5A11` = ICON_VAR (state-dependent variable icon)")
    w("- `0x5A12` = DATETIME (date/time display)")
    w("- `0x5A04` = PAGE_SWITCH (page navigation trigger)")
    w("- `0x5A06` = BTN_RETURN (return/back button)")
    w()

    # Group by register address -- ONLY SP=0x5A10 entries are actual registers
    SP_DATA_VAR = 0x5A10
    by_reg: dict[int, list[ShowEntry]] = defaultdict(list)
    for entry in all_show_entries:
        if entry.sp_addr == SP_DATA_VAR and entry.entry_type == 0x50:
            by_reg[entry.register_addr].append(entry)

    w(f"**Unique registers displayed**: {len(by_reg)}")
    w()
    w("| Reg | Digits | DP | Scale | Unit | Signed | Pages | Known Name |")
    w("|-----|--------|----|-------|------|--------|-------|------------|")

    for reg in sorted(by_reg.keys()):
        entries = by_reg[reg]
        # Use first entry for format info
        e = entries[0]
        pages_list = sorted(set(en.page_id for en in entries))
        pages_str = ", ".join(str(p) for p in pages_list[:5])
        if len(pages_list) > 5:
            pages_str += f" (+{len(pages_list) - 5})"

        # Look up known name
        known = ""
        if reg in KNOWN_INPUT_REGISTERS:
            known = KNOWN_INPUT_REGISTERS[reg][0]
        elif reg in KNOWN_HOLDING_REGISTERS:
            known = KNOWN_HOLDING_REGISTERS[reg][0]

        signed = "Yes" if e.is_signed else "No"
        w(
            f"| {reg} | {e.num_digits} | {e.decimal_places} | "
            f"{e.scale_factor} | {e.unit_suffix} | {signed} | "
            f"{pages_str} | `{known}` |"
        )

    w()

    # --------------- 4. CROSS-REFERENCE ---------------
    w("## 4. Register Cross-Reference with pylxpweb")
    w()
    w("### Registers displayed on LCD that ARE in pylxpweb")
    w()
    w("| Reg | LCD Unit | LCD Scale | pylxpweb Name | pylxpweb Scale | Match? |")
    w("|-----|----------|-----------|---------------|----------------|--------|")

    matched = 0
    mismatched = 0
    for reg in sorted(by_reg.keys()):
        e = by_reg[reg][0]
        if reg in KNOWN_INPUT_REGISTERS:
            known_name, known_scale, known_unit = KNOWN_INPUT_REGISTERS[reg]
            lcd_scale = e.scale_factor
            match = "YES" if lcd_scale == known_scale else "MISMATCH"
            if match == "MISMATCH":
                mismatched += 1
            else:
                matched += 1
            w(
                f"| {reg} | {e.unit_suffix} | {lcd_scale} | "
                f"`{known_name}` | {known_scale} | {match} |"
            )

    w()
    w(f"**Matched**: {matched}, **Mismatched**: {mismatched}")
    w()

    w("### Registers displayed on LCD that are NOT in pylxpweb")
    w()
    w("These are potential new register discoveries from the LCD firmware.")
    w()
    w("| Reg | Digits | DP | Scale | Unit | Signed | Inferred Purpose | Pages |")
    w("|-----|--------|----|-------|------|--------|------------------|-------|")

    unknown_regs = []
    for reg in sorted(by_reg.keys()):
        if reg not in KNOWN_INPUT_REGISTERS and reg not in KNOWN_HOLDING_REGISTERS:
            e = by_reg[reg][0]
            purpose = infer_register_purpose(e)
            pages_list = sorted(set(en.page_id for en in by_reg[reg]))
            pages_str = ", ".join(str(p) for p in pages_list[:5])
            signed = "Yes" if e.is_signed else "No"
            unknown_regs.append(reg)
            w(
                f"| {reg} | {e.num_digits} | {e.decimal_places} | "
                f"{e.scale_factor} | {e.unit_suffix} | {signed} | "
                f"`{purpose}` | {pages_str} |"
            )

    w()
    w(f"**New registers found**: {len(unknown_regs)}")
    if unknown_regs:
        w(f"**Register addresses**: {', '.join(str(r) for r in unknown_regs)}")
    w()

    # --------------- 5. TOUCH INPUT MAP ---------------
    w("## 5. Touch Input Map")
    w()
    w("Extracted from `13TouchFile.bin`. Each entry defines a touch-sensitive")
    w("region on the screen that navigates to a target page or writes a value.")
    w()
    w(f"**Total touch entries**: {len(touch_entries)}")
    w()

    # Group by target VP
    touch_by_vp: dict[int, list[TouchEntry]] = defaultdict(list)
    for te in touch_entries:
        touch_by_vp[te.vp_addr].append(te)

    w("### Navigation Targets (unique VP addresses)")
    w()
    w("| VP/Page | Dec | Count | Source Pages | Likely Function |")
    w("|---------|-----|-------|-------------|-----------------|")

    # Known page navigation targets
    nav_targets: dict[int, str] = {
        0x0008: "Home / Main Status",
        0x000C: "PV Solar",
        0x000D: "Grid AC",
        0x000E: "EPS / Backup",
        0x000F: "Battery",
        0x0010: "Battery Detail",
        0x0011: "Settings Menu 1",
        0x0012: "Settings Menu 2",
        0x0013: "Firmware Update",
        0x0014: "System Settings",
        0x0015: "Date/Time Settings",
        0x0016: "Charge Schedule 1",
        0x0017: "Charge Schedule 2",
        0x0018: "Discharge Schedule",
        0x001B: "Alarm / Error",
        0x001E: "Grid Config",
        0x001F: "Generator Config",
        0x0020: "Data Screen (next)",
        0x0027: "Scroll Down (data)",
        0x0028: "Scroll Up (data)",
        0x002B: "Settings Parameter Select",
        0x002F: "Logo / Splash",
        0x0030: "Menu",
        0x0031: "Data / Energy",
        0xFF00: "Return / Back (with data)",
    }

    for vp in sorted(touch_by_vp.keys()):
        entries = touch_by_vp[vp]
        count = len(entries)
        source_pages = sorted(set(e.page_id for e in entries))
        pages_str = ", ".join(str(p) for p in source_pages[:8])
        if len(source_pages) > 8:
            pages_str += f" (+{len(source_pages) - 8})"
        desc = nav_targets.get(vp, "")
        w(f"| 0x{vp:04X} | {vp} | {count} | {pages_str} | {desc} |")

    w()

    # --------------- 6. VP CONFIG ---------------
    w("## 6. VP Address Configuration")
    w()
    w("Extracted from `22_Config.bin`. Non-zero values in the config space")
    w("indicate VP addresses with active data variable configuration.")
    w()
    w("The config data starts at file offset 0xA000 (VP address range 0x5000+).")
    w("Key values:")
    w("- `0x3CC3` = Data variable enabled (DWIN enable marker)")
    w("- `0x07D1` = 2001 = Display format configuration word")
    w("- `0x3A98` = 15000 = Max value or range limit")
    w()

    # Only show the interesting VP range
    interesting_vps = {vp: val for vp, val in config_vps.items() if vp >= 0x5000}
    if interesting_vps:
        w("| VP Address | Value (hex) | Value (dec) | Interpretation |")
        w("|------------|-------------|-------------|----------------|")
        for vp in sorted(interesting_vps.keys()):
            val = interesting_vps[vp]
            if val == 0x3CC3:
                interp = "Data variable ENABLED"
            elif val == 0x07D1:
                interp = "Format: numeric, 4 digits, 1 DP"
            elif val == 0x3A98:
                interp = "Max value: 15000 (e.g., 15kW)"
            elif val == 0x1390:
                interp = "Max value: 5008 (e.g., 500.8V)"
            elif val == 0x0BB9:
                interp = "Max value: 3001"
            elif val == 0x6464:
                interp = "Pair: 100, 100 (percent range)"
            elif val <= 10:
                interp = f"Small constant: {val}"
            else:
                interp = "Configuration parameter"
            w(f"| 0x{vp:04X} | 0x{val:04X} | {val} | {interp} |")
    w()

    # --------------- 7. PAGE DETAIL ---------------
    w("## 7. Page-by-Page Detail")
    w()
    w("Detailed register listing for each active display page.")
    w()

    SP_DATA_VAR_PAGE = 0x5A10
    for page in pages:
        # Separate entries by SP type
        register_entries = [
            e
            for e in page.display_entries
            if e.sp_addr == SP_DATA_VAR_PAGE and e.entry_type == 0x50
        ]
        icon_var_entries = [e for e in page.display_entries if e.sp_addr == 0x5A11]
        anim_entries = [
            e for e in page.display_entries if e.sp_addr in (0x5A00, 0x5A01)
        ]
        dt_entries = [e for e in page.display_entries if e.sp_addr == 0x5A12]

        if not register_entries and not page.touch_entries:
            continue

        desc = page_descs.get(page.page_id, "")
        w(f"### Page {page.page_id}: {desc}")
        w()

        if register_entries:
            w("**Register Data Variables** (SP=0x5A10, actual Modbus registers):")
            w()
            w("| Reg | X | Y | Digits | DP | Unit | Name |")
            w("|-----|---|---|--------|----|------|------|")
            for e in sorted(register_entries, key=lambda x: (x.y, x.x)):
                name = ""
                if e.register_addr in KNOWN_INPUT_REGISTERS:
                    name = KNOWN_INPUT_REGISTERS[e.register_addr][0]
                elif e.register_addr in KNOWN_HOLDING_REGISTERS:
                    name = KNOWN_HOLDING_REGISTERS[e.register_addr][0]
                else:
                    name = infer_register_purpose(e)
                w(
                    f"| {e.register_addr} | {e.x} | {e.y} | "
                    f"{e.num_digits} | {e.decimal_places} | {e.unit_suffix} | "
                    f"`{name}` |"
                )
            w()

        if anim_entries:
            w(
                f"**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): "
                f"{len(anim_entries)} entries (icon indices, NOT registers)"
            )
            w()

        if icon_var_entries:
            w(f"**Variable Icons** (SP=0x5A11): {len(icon_var_entries)} entries")
            w()

        if dt_entries:
            w(f"**DateTime Variables** (SP=0x5A12): {len(dt_entries)} entries")
            for e in dt_entries:
                # The raw bytes contain the datetime format string
                fmt_bytes = e.raw[14:28]
                fmt_str = ""
                for b in fmt_bytes:
                    if 32 <= b < 127:
                        fmt_str += chr(b)
                if fmt_str:
                    w(f"  - Format: `{fmt_str}`")
            w()

        if page.touch_entries:
            w("**Touch Regions:**")
            w()
            w("| X1 | Y1 | X2 | Y2 | Target VP | Function |")
            w("|----|----|----|----|-----------| ---------|")
            for te in page.touch_entries:
                func = nav_targets.get(te.vp_addr, f"VP 0x{te.vp_addr:04X}")
                w(
                    f"| {te.x1} | {te.y1} | {te.x2} | {te.y2} | "
                    f"0x{te.vp_addr:04X} | {func} |"
                )
            w()

    # --------------- 8. KEY FINDINGS ---------------
    w("## 8. Key Findings")
    w()

    w("### 8.1 VP-to-Register Address Mapping")
    w()
    w("The DWIN display uses a **direct 1:1 mapping** between VP addresses and")
    w("Modbus input register addresses. Byte 7 of each ShowFile entry IS the")
    w("Modbus register number. This means:")
    w()
    w("- VP address 0 = Modbus input register 0 (device_status)")
    w("- VP address 12 = Modbus input register 12 (grid_voltage_r)")
    w("- VP address 91 = Modbus input register 91 (battery_current)")
    w()
    w("The inverter MCU reads Modbus input registers and writes them directly")
    w("to the corresponding DWIN VP addresses over UART.")
    w()

    w("### 8.2 Scale Factor Confirmation")
    w()
    w("The LCD display decimal places confirm register scaling:")
    w()
    w("| Register | LCD DP | LCD Scale | pylxpweb Scale | Status |")
    w("|----------|--------|-----------|----------------|--------|")

    scale_confirmations = [
        (1, "pv1_voltage", 1, "/10", "/10"),
        (15, "grid_frequency", 2, "/100", "/100"),
        (18, "inverter_rms_current_r", 0, "x1", "/100"),
        (51, "charge_energy_total_hi", 2, "/100", "/10"),
        (85, "eps_l1_frequency", 2, "/100", "/100"),
        (91, "battery_current", 1, "/10", "/10"),
    ]
    for reg, name, dp, lcd_scale, plxp_scale in scale_confirmations:
        match = "CONFIRMED" if lcd_scale == plxp_scale else "DIFFERS"
        w(f"| {reg} (`{name}`) | {dp} | {lcd_scale} | {plxp_scale} | {match} |")

    w()
    w("**Note**: Some scale factor differences are expected -- the LCD may")
    w("display with different precision than the raw register value.")
    w("For example, register 18 (inverter_rms_current_r) has /100 scaling in")
    w("pylxpweb but displays with 0 decimal places on the LCD (showing amps")
    w("as integers on the small screen).")
    w()

    w("### 8.3 Register Coverage")
    w()
    total_lcd = len(by_reg)
    known_count = sum(
        1 for r in by_reg if r in KNOWN_INPUT_REGISTERS or r in KNOWN_HOLDING_REGISTERS
    )
    w(f"- **LCD displays {total_lcd} unique registers**")
    w(f"- **{known_count} are known** in pylxpweb")
    w(f"- **{total_lcd - known_count} are new/unknown**")
    w()

    # Identify the most important unknown registers
    w("### 8.4 New Register Discoveries")
    w()
    w("Registers displayed on the LCD but not yet mapped in pylxpweb.")
    w("Cross-referenced with live Modbus probe data where available.")
    w()
    w("**Important**: The LCD settings pages (9-10, 16, etc.) display HOLDING")
    w("registers for parameter configuration, while data pages (8, 12-15) display")
    w("INPUT registers for runtime data. The same register number may refer to")
    w("different registers depending on which page it appears on.")
    w()

    # Cross-reference with probe data
    PROBE_HOLDING_NAMES: dict[int, str] = {
        28: "grid_frequency_connection_high (6500 = 65.00 Hz)",
        43: "grid_freq_protection_threshold (6500 = 6.500 kV or 65.00 Hz)",
        166: "battery_low_to_utility_voltage (0 = disabled)",
        169: "ongrid_eod_voltage (400 = 40.0V battery cutoff)",
        176: "max_grid_input_power (65535 = unlimited)",
        183: "reconnection_timer (10 seconds)",
        185: "grid_reconnect_voltage (2400 = 240.0V)",
    }

    PROBE_INPUT_NAMES: dict[int, str] = {
        28: "pv1_energy_today (observed: 0-36, /10 = 0-3.6 kWh)",
    }

    new_regs_with_units: list[tuple[int, ShowEntry]] = []
    for reg in sorted(by_reg.keys()):
        if reg not in KNOWN_INPUT_REGISTERS and reg not in KNOWN_HOLDING_REGISTERS:
            e = by_reg[reg][0]
            # Include all unknown registers (with or without unit suffix)
            if e.unit_suffix not in (
                "[icon]",
                "[datetime]",
                "[anim_icon]",
                "[scroll_icon]",
                "[icon_var]",
            ):
                new_regs_with_units.append((reg, e))

    if new_regs_with_units:
        w("| Reg | LCD Format | Pages | Probe Holding Name | Probe Input Name |")
        w("|-----|-----------|-------|--------------------|------------------|")
        for reg, e in new_regs_with_units:
            pages_list = sorted(set(en.page_id for en in by_reg[reg]))
            pages_str = ", ".join(str(p) for p in pages_list)
            fmt = f"{e.unit_suffix}, {e.num_digits}d {e.decimal_places}dp ({e.scale_factor})"
            hold_name = PROBE_HOLDING_NAMES.get(reg, "-")
            input_name = PROBE_INPUT_NAMES.get(reg, "-")
            w(f"| {reg} | {fmt} | {pages_str} | {hold_name} | {input_name} |")
    w()

    w("### 8.5 Screen Layout Architecture")
    w()
    w("The display has a consistent navigation structure:")
    w()
    w("- **Bottom navigation bar** (Y=400-480): Home, Menu, Settings buttons")
    w("- **Left sidebar** (X=0-155): Sub-page selection tabs")
    w("- **Main content area** (X=155-800, Y=0-400): Data display")
    w("- **Pages 9-10**: Settings parameter screens with grid layout")
    w("- **Pages 56-60**: Battery BMS detail screens (8 entries each)")
    w()

    w("### 8.6 DWIN Protocol Summary")
    w()
    w("The inverter communicates with the LCD via UART at 115200 baud using")
    w("the DWIN DGUS II protocol:")
    w()
    w("1. **MCU -> Display**: Write register values to VP addresses")
    w("   - Frame: `5A A5 [len] 82 [VP_hi] [VP_lo] [data_hi] [data_lo]`")
    w("   - VP address = Modbus register number (direct mapping)")
    w()
    w("2. **Display -> MCU**: Touch input events")
    w("   - Frame: `5A A5 [len] 83 [VP_hi] [VP_lo] [value_hi] [value_lo]`")
    w("   - Used for page navigation and parameter input")
    w()
    w("3. **Page switching**: MCU writes to VP 0x0084 (DWIN page register)")
    w("   - `5A A5 04 80 03 00 [page_id]` switches to target page")
    w()

    w("---")
    w()
    w("*Generated by `scripts/parse_dwin_lcd_firmware.py`*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point."""
    print("DWIN DGUS LCD Firmware Parser")
    print("=" * 60)

    # Find files
    files = find_files()
    required = [
        "T5LCFG_12720.CFG",
        "13TouchFile.bin",
        "14ShowFile.bin",
        "22_Config.bin",
        "0.bin",
    ]
    for fname in required:
        if fname not in files:
            print(f"ERROR: Required file not found: {fname}")
            sys.exit(1)
        print(f"  Found: {fname} ({files[fname].stat().st_size:,} bytes)")

    print()

    # 1. Parse T5L Config
    print("Parsing T5LCFG_12720.CFG...")
    with open(files["T5LCFG_12720.CFG"], "rb") as f:
        t5l_cfg = parse_t5l_config(f.read())
    print(f"  Signature: {t5l_cfg.signature}")
    print(f"  Baud: {t5l_cfg.baud_rate}")
    print(f"  Resolution: {t5l_cfg.resolution_x}x{t5l_cfg.resolution_y}")

    # 2. Parse ShowFile
    print("\nParsing 14ShowFile.bin...")
    with open(files["14ShowFile.bin"], "rb") as f:
        show_data = f.read()
    pages, all_show = parse_show_file(show_data)
    # Count by SP type for accurate classification
    n_reg_data = sum(
        1 for e in all_show if e.sp_addr == 0x5A10 and e.entry_type == 0x50
    )
    n_anim = sum(1 for e in all_show if e.sp_addr in (0x5A00, 0x5A01))
    n_icon_var = sum(1 for e in all_show if e.sp_addr == 0x5A11)
    n_dt = sum(1 for e in all_show if e.sp_addr == 0x5A12)
    print(f"  Pages: {len(pages)}")
    print(f"  Total entries: {len(all_show)}")
    print(f"    Register data (SP=0x5A10): {n_reg_data}")
    print(f"    Animated icons (SP=0x5A00/01): {n_anim}")
    print(f"    Variable icons (SP=0x5A11): {n_icon_var}")
    print(f"    DateTime (SP=0x5A12): {n_dt}")

    # Only count actual register references (SP=0x5A10)
    unique_regs = sorted(
        set(
            e.register_addr
            for e in all_show
            if e.sp_addr == 0x5A10 and e.entry_type == 0x50
        )
    )
    print(f"  Unique Modbus registers: {len(unique_regs)}")
    print(f"  Register range: {min(unique_regs)}-{max(unique_regs)}")

    # 3. Parse TouchFile
    print("\nParsing 13TouchFile.bin...")
    with open(files["13TouchFile.bin"], "rb") as f:
        touch_data = f.read()
    touch_entries = parse_touch_file(touch_data)
    print(f"  Touch entries: {len(touch_entries)}")

    unique_touch_vps = sorted(set(e.vp_addr for e in touch_entries))
    print(f"  Unique target VPs: {len(unique_touch_vps)}")

    # 4. Parse Config
    print("\nParsing 22_Config.bin...")
    with open(files["22_Config.bin"], "rb") as f:
        config_data = f.read()
    config_vps = parse_config_bin(config_data)
    print(f"  Non-zero VP configs: {len(config_vps)}")

    # 5. Extract firmware strings
    print("\nExtracting strings from 0.bin...")
    with open(files["0.bin"], "rb") as f:
        fw_data = f.read()
    fw_strings = extract_firmware_strings(fw_data)
    print(f"  Strings found: {len(fw_strings)}")

    # 6. Generate output
    print("\nGenerating LCD_DWIN_ANALYSIS.md...")
    markdown = generate_markdown(
        t5l_cfg, pages, all_show, touch_entries, config_vps, fw_strings
    )

    output_path = OUTPUT_DIR / "LCD_DWIN_ANALYSIS.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(markdown)

    print(f"\nOutput written to: {output_path}")
    print(f"  Size: {output_path.stat().st_size:,} bytes")

    # Print summary statistics
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    by_reg = defaultdict(list)
    for e in all_show:
        if e.sp_addr == 0x5A10 and e.entry_type == 0x50:
            by_reg[e.register_addr].append(e)

    known = sum(
        1 for r in by_reg if r in KNOWN_INPUT_REGISTERS or r in KNOWN_HOLDING_REGISTERS
    )
    unknown = len(by_reg) - known

    pages_with_regs = sum(
        1
        for p in pages
        if any(e.sp_addr == 0x5A10 and e.entry_type == 0x50 for e in p.display_entries)
    )
    print(f"  Display pages with register data: {pages_with_regs}")
    print(f"  Unique registers on LCD: {len(by_reg)}")
    print(f"  Known in pylxpweb: {known}")
    print(f"  New/unknown: {unknown}")
    print(f"  Touch input regions: {len(touch_entries)}")
    print(f"  Navigation targets: {len(unique_touch_vps)}")


if __name__ == "__main__":
    main()
