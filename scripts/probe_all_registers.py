#!/usr/bin/env python3
"""Comprehensive Modbus register probe for EG4 inverters.

Probes ALL holding and input registers (0-999, 5000-5200) on two inverters,
plus extended ranges (1000-2100) on the 18kPV.

Usage:
    .venv/bin/python scripts/probe_all_registers.py
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException

# =============================================================================
# CONFIGURATION
# =============================================================================

DEVICES: dict[str, dict[str, Any]] = {
    "18kPV": {"host": "10.100.14.68", "port": 502},
    "FlexBOSS21": {"host": "10.100.10.184", "port": 502},
}

CHUNK_SIZE = 10
DELAY_BETWEEN_READS = 0.1  # 100ms
TIMEOUT = 3  # seconds per read

# Standard ranges for both inverters
STANDARD_HOLDING_RANGES = [(0, 999)]
STANDARD_INPUT_RANGES = [(0, 999), (5000, 5200)]

# Extended ranges for 18kPV only
EXTENDED_HOLDING_RANGES = [(1000, 2100)]
EXTENDED_INPUT_RANGES = [(1000, 2100)]

OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "reference" / "firmware_re"

# =============================================================================
# KNOWN REGISTER MAP (from pylxpweb)
# =============================================================================

# Holding registers: address -> canonical_name
KNOWN_HOLDING: dict[int, list[str]] = {
    9: ["com_protocol_version"],
    10: ["controller_version"],
    15: ["modbus_address"],
    16: ["language"],
    19: ["device_type_code"],
    20: ["pv_input_mode"],
    21: [
        "eps_enable",
        "overload_derate_enable",
        "drms_enable",
        "lvrt_enable",
        "anti_island_enable",
        "neutral_detect_enable",
        "grid_on_power_soft_start",
        "ac_charge_enable",
        "seamless_switching_enable",
        "power_on",
        "forced_discharge_enable",
        "forced_charge_enable",
        "isolation_detect_enable",
        "gfci_enable",
        "dci_enable",
        "feed_in_grid_enable",
    ],
    22: ["pv_start_voltage"],
    23: ["grid_connection_wait_time"],
    24: ["grid_reconnection_wait_time"],
    25: ["grid_voltage_connection_low"],
    26: [
        "lsp_whole_bypass_1_enable",
        "lsp_whole_bypass_2_enable",
        "lsp_whole_bypass_3_enable",
        "lsp_whole_battery_first_1_enable",
        "lsp_whole_battery_first_2_enable",
        "lsp_whole_battery_first_3_enable",
        "lsp_whole_self_consumption_1_enable",
        "lsp_whole_self_consumption_2_enable",
        "lsp_whole_self_consumption_3_enable",
        "lsp_battery_volt_or_soc",
    ],
    27: ["grid_frequency_connection_low"],
    28: ["grid_frequency_connection_high"],
    59: ["reactive_power_mode"],
    60: ["reactive_power_pv_mode"],
    61: ["reactive_power_setting"],
    62: ["reactive_power_pv_setting"],
    64: ["charge_power_percent"],
    65: ["discharge_power_percent"],
    66: ["ac_charge_power"],
    67: ["ac_charge_soc_limit"],
    68: ["ac_charge_start_hour_1"],
    69: ["ac_charge_start_minute_1"],
    70: ["ac_charge_end_hour_1"],
    71: ["ac_charge_end_minute_1"],
    72: ["ac_charge_enable_period_1"],
    73: ["ac_charge_enable_period_2"],
    74: ["forced_charge_power_command"],
    75: ["forced_charge_soc_limit"],
    76: ["forced_charge_time_0_start"],
    77: ["forced_charge_time_0_end"],
    78: ["forced_charge_time_1_start"],
    79: ["forced_charge_time_1_end"],
    80: ["forced_charge_time_2_start"],
    81: ["forced_charge_time_2_end"],
    82: ["forced_discharge_power_command"],
    83: ["forced_discharge_soc_limit"],
    84: ["forced_discharge_time_0_start"],
    85: ["forced_discharge_time_0_end"],
    86: ["forced_discharge_time_1_start"],
    87: ["forced_discharge_time_1_end"],
    88: ["forced_discharge_time_2_start"],
    89: ["forced_discharge_time_2_end"],
    90: ["output_voltage_select"],
    91: ["output_frequency_select"],
    99: ["charge_voltage_ref"],
    100: ["discharge_cutoff_voltage"],
    101: ["charge_current_limit"],
    102: ["discharge_current_limit"],
    103: ["max_backflow_power_percent"],
    105: ["ongrid_discharge_cutoff_soc"],
    110: [
        "pv_grid_off_enable",
        "run_without_grid",
        "micro_grid_enable",
        "battery_shared",
        "charge_last",
        "take_load_together",
        "buzzer_enable",
        "go_to_offgrid",
        "green_mode_enable",
        "battery_eco_enable",
        "working_mode",
        "pvct_sample_type",
        "pvct_sample_ratio",
        "ct_sample_ratio",
    ],
    112: ["system_type"],
    116: ["ptouser_start_discharge"],
    118: ["voltage_start_derating"],
    119: ["power_offset_wct"],
    120: [
        "half_hour_ac_charge_start_enable",
        "sna_battery_discharge_control",
        "phase_independent_compensate_enable",
        "ac_charge_type",
        "discharge_control_type",
        "ongrid_eod_type",
        "generator_charge_type",
    ],
    125: ["offgrid_discharge_cutoff_soc"],
    144: ["float_charge_voltage"],
    145: ["output_priority"],
    146: ["line_mode"],
    147: ["battery_capacity"],
    148: ["battery_nominal_voltage"],
    149: ["equalization_voltage"],
    150: ["equalization_interval"],
    151: ["equalization_time"],
    158: ["ac_charge_start_voltage"],
    159: ["ac_charge_end_voltage"],
    160: ["ac_charge_start_soc"],
    161: ["ac_charge_end_soc"],
    162: ["battery_low_voltage"],
    163: ["battery_low_back_voltage"],
    164: ["battery_low_soc"],
    165: ["battery_low_back_soc"],
    166: ["battery_low_to_utility_voltage"],
    167: ["battery_low_to_utility_soc"],
    168: ["ac_charge_battery_current"],
    169: ["ongrid_eod_voltage"],
    176: ["max_grid_input_power"],
    177: ["generator_rated_power"],
    179: [
        "ac_ct_direction",
        "pv_ct_direction",
        "afci_alarm_clear",
        "battery_wakeup_enable",
        "volt_watt_enable",
        "trip_time_unit",
        "active_power_cmd_enable",
        "grid_peak_shaving_enable",
        "gen_peak_shaving_enable",
        "battery_charge_control",
        "battery_discharge_control",
        "ac_coupling_enable",
        "pv_arc_enable",
        "smart_load_enable",
        "rsd_disable",
        "ongrid_always_on",
    ],
    190: ["hold_p2"],
    194: ["gen_charge_start_voltage"],
    195: ["gen_charge_end_voltage"],
    196: ["gen_charge_start_soc"],
    197: ["gen_charge_end_soc"],
    198: ["max_gen_charge_battery_current"],
    227: ["system_charge_soc_limit"],
    231: ["grid_peak_shaving_power"],
    233: [
        "quick_charge_start_enable",
        "battery_backup_enable",
        "maintenance_enable",
        "weekly_schedule_enable",
        "over_freq_fast_stop",
        "sporadic_charge_enable",
    ],
}

# Input registers: address -> canonical_name
KNOWN_INPUT: dict[int, list[str]] = {
    0: ["device_status"],
    1: ["pv1_voltage"],
    2: ["pv2_voltage"],
    3: ["pv3_voltage"],
    4: ["battery_voltage"],
    5: ["soc_soh_packed"],
    7: ["pv1_power"],
    8: ["pv2_power"],
    9: ["pv3_power"],
    10: ["charge_power"],
    11: ["discharge_power"],
    12: ["grid_voltage_r"],
    13: ["grid_voltage_s"],
    14: ["grid_voltage_t"],
    15: ["grid_frequency"],
    16: ["inverter_power"],
    17: ["rectifier_power"],
    18: ["inverter_rms_current_r"],
    19: ["power_factor"],
    20: ["eps_voltage_r"],
    21: ["eps_voltage_s"],
    22: ["eps_voltage_t"],
    23: ["eps_frequency"],
    24: ["eps_power"],
    25: ["eps_apparent_power"],
    26: ["power_to_grid"],
    27: ["power_to_user"],
    28: ["pv1_energy_today"],
    29: ["pv2_energy_today"],
    30: ["pv3_energy_today"],
    31: ["inverter_energy_today"],
    32: ["ac_charge_energy_today"],
    33: ["charge_energy_today"],
    34: ["discharge_energy_today"],
    35: ["eps_energy_today"],
    36: ["grid_export_energy_today"],
    37: ["grid_import_energy_today"],
    38: ["bus_voltage_1"],
    39: ["bus_voltage_2"],
    40: ["pv1_energy_total"],
    42: ["pv2_energy_total"],
    44: ["pv3_energy_total"],
    46: ["inverter_energy_total"],
    48: ["ac_charge_energy_total"],
    50: ["charge_energy_total"],
    52: ["discharge_energy_total"],
    54: ["eps_energy_total"],
    56: ["grid_export_energy_total"],
    58: ["grid_import_energy_total"],
    60: ["fault_code"],
    62: ["warning_code"],
    64: ["internal_temperature"],
    65: ["radiator_temperature_1"],
    66: ["radiator_temperature_2"],
    67: ["battery_temperature"],
    68: ["battery_control_temperature"],
    69: ["running_time"],
    72: ["pv1_current"],
    73: ["pv2_current"],
    74: ["pv3_current"],
    75: ["battery_current_inv"],
    77: ["ac_input_type"],
    80: ["bms_battery_type"],
    81: ["bms_charge_current_limit"],
    82: ["bms_discharge_current_limit"],
    83: ["bms_charge_voltage_ref"],
    84: ["bms_discharge_cutoff"],
    85: ["bms_status_0"],
    86: ["bms_status_1"],
    87: ["bms_status_2"],
    88: ["bms_status_3"],
    89: ["bms_status_4"],
    90: ["bms_status_5"],
    91: ["bms_status_6"],
    92: ["bms_status_7"],
    93: ["bms_status_8"],
    94: ["bms_status_9"],
    95: ["battery_status_inv"],
    96: ["battery_parallel_count"],
    97: ["battery_capacity_ah"],
    98: ["battery_current_bms"],
    99: ["bms_fault_code"],
    100: ["bms_warning_code"],
    101: ["bms_max_cell_voltage"],
    102: ["bms_min_cell_voltage"],
    103: ["bms_max_cell_temperature"],
    104: ["bms_min_cell_temperature"],
    105: ["bms_fw_update_state"],
    106: ["bms_cycle_count"],
    107: ["battery_voltage_inv_sample"],
    108: ["temperature_t1"],
    109: ["temperature_t2"],
    110: ["temperature_t3"],
    111: ["temperature_t4"],
    112: ["temperature_t5"],
    113: ["parallel_config"],
    121: ["generator_voltage"],
    122: ["generator_frequency"],
    123: ["generator_power"],
    124: ["generator_energy_today"],
    125: ["generator_energy_total"],
    127: ["eps_l1_voltage"],
    128: ["eps_l2_voltage"],
    129: ["eps_l1_power"],
    130: ["eps_l2_power"],
    131: ["eps_l1_apparent_power"],
    132: ["eps_l2_apparent_power"],
    133: ["eps_l1_energy_today"],
    134: ["eps_l2_energy_today"],
    135: ["eps_l1_energy_total"],
    137: ["eps_l2_energy_total"],
    153: ["ac_couple_power"],
    170: ["output_power"],
    171: ["load_energy_today"],
    172: ["load_energy_total"],
    190: ["inverter_rms_current_s"],
    191: ["inverter_rms_current_t"],
    193: ["grid_l1_voltage"],
    194: ["grid_l2_voltage"],
    195: ["generator_l1_voltage"],
    196: ["generator_l2_voltage"],
    197: ["inverter_power_l1"],
    198: ["inverter_power_l2"],
    199: ["rectifier_power_l1"],
    200: ["rectifier_power_l2"],
    201: ["grid_export_power_l1"],
    202: ["grid_export_power_l2"],
    203: ["grid_import_power_l1"],
    204: ["grid_import_power_l2"],
    210: ["quick_charge_remaining_seconds"],
    217: ["pv4_voltage"],
    218: ["pv5_voltage"],
    219: ["pv6_voltage"],
    220: ["pv4_power"],
    221: ["pv5_power"],
    222: ["pv6_power"],
    223: ["epv4_day"],
    224: ["epv4_all"],
    226: ["epv5_day"],
    227: ["epv5_all"],
    229: ["epv6_day"],
    230: ["epv6_all"],
    232: ["smart_load_power"],
}

# Battery registers (input, 5002-5121)
KNOWN_BATTERY_INPUT: dict[int, str] = {}
for bat_idx in range(4):
    base = 5002 + bat_idx * 30
    KNOWN_BATTERY_INPUT[base + 0] = f"bat{bat_idx}_status_header"
    KNOWN_BATTERY_INPUT[base + 1] = f"bat{bat_idx}_full_capacity_ah"
    KNOWN_BATTERY_INPUT[base + 2] = f"bat{bat_idx}_charge_voltage_ref"
    KNOWN_BATTERY_INPUT[base + 3] = f"bat{bat_idx}_charge_current_limit"
    KNOWN_BATTERY_INPUT[base + 4] = f"bat{bat_idx}_discharge_current_limit"
    KNOWN_BATTERY_INPUT[base + 5] = f"bat{bat_idx}_discharge_voltage_cutoff"
    KNOWN_BATTERY_INPUT[base + 6] = f"bat{bat_idx}_voltage"
    KNOWN_BATTERY_INPUT[base + 7] = f"bat{bat_idx}_current"
    KNOWN_BATTERY_INPUT[base + 8] = f"bat{bat_idx}_soc_soh_packed"
    KNOWN_BATTERY_INPUT[base + 9] = f"bat{bat_idx}_cycle_count"
    KNOWN_BATTERY_INPUT[base + 10] = f"bat{bat_idx}_max_cell_temp"
    KNOWN_BATTERY_INPUT[base + 11] = f"bat{bat_idx}_min_cell_temp"
    KNOWN_BATTERY_INPUT[base + 12] = f"bat{bat_idx}_max_cell_voltage"
    KNOWN_BATTERY_INPUT[base + 13] = f"bat{bat_idx}_min_cell_voltage"
    KNOWN_BATTERY_INPUT[base + 14] = f"bat{bat_idx}_cell_num_voltage_packed"
    KNOWN_BATTERY_INPUT[base + 15] = f"bat{bat_idx}_cell_num_temp_packed"
    KNOWN_BATTERY_INPUT[base + 16] = f"bat{bat_idx}_firmware_version"
    for sn_off in range(8):
        KNOWN_BATTERY_INPUT[base + 17 + sn_off] = f"bat{bat_idx}_serial_{sn_off}"


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class RegisterReading:
    """A single register reading from one or both inverters."""

    address: int
    reg_type: str  # "holding" or "input"
    values: dict[str, int | None]  # device_name -> raw value (None = error)
    known_names: list[str]  # from pylxpweb
    interpretation: str = ""


@dataclass
class ProbeResults:
    """Complete probe results."""

    timestamp: str = ""
    holding: list[RegisterReading] = field(default_factory=list)
    input: list[RegisterReading] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# =============================================================================
# PROBING FUNCTIONS
# =============================================================================


def probe_register_range(
    client: ModbusTcpClient,
    start: int,
    end: int,
    reg_type: str,
    device_name: str,
    skip_individual_retry: bool = False,
) -> dict[int, int | None]:
    """Probe a range of registers, returning address->value map.

    Only stores addresses that actually respond with data.
    When skip_individual_retry=True, failed chunks are skipped entirely
    (much faster for ranges with many non-existent registers).
    """
    results: dict[int, int | None] = {}
    addr = start
    consecutive_errors = 0

    while addr <= end:
        count = min(CHUNK_SIZE, end - addr + 1)
        try:
            if reg_type == "holding":
                response = client.read_holding_registers(address=addr, count=count)
            else:
                response = client.read_input_registers(address=addr, count=count)

            if response.isError():
                consecutive_errors += 1
                if not skip_individual_retry and consecutive_errors <= 2:
                    # Only retry individually near known-good regions
                    for i in range(count):
                        try:
                            if reg_type == "holding":
                                r2 = client.read_holding_registers(
                                    address=addr + i, count=1
                                )
                            else:
                                r2 = client.read_input_registers(
                                    address=addr + i, count=1
                                )

                            if not r2.isError():
                                results[addr + i] = r2.registers[0]
                                consecutive_errors = 0
                            time.sleep(DELAY_BETWEEN_READS / 2)
                        except (ModbusIOException, Exception):
                            pass
                # else: skip chunk entirely (no response = not stored)
            else:
                consecutive_errors = 0
                for i, val in enumerate(response.registers):
                    results[addr + i] = val
        except (ModbusIOException, Exception):
            consecutive_errors += 1

        addr += count
        time.sleep(DELAY_BETWEEN_READS)

    return results


def interpret_value(
    raw: int, address: int, reg_type: str, known_names: list[str]
) -> str:
    """Try to interpret a raw register value."""
    interpretations = []

    # Check for zero
    if raw == 0:
        return "0"

    # Check ASCII (both bytes printable)
    hi = (raw >> 8) & 0xFF
    lo = raw & 0xFF
    if 0x20 <= hi <= 0x7E and 0x20 <= lo <= 0x7E:
        interpretations.append(f"ASCII='{chr(hi)}{chr(lo)}'")

    # Check common voltage ranges (div 10)
    div10 = raw / 10.0
    if 10.0 <= div10 <= 600.0:
        interpretations.append(f"v/10={div10:.1f}")

    # Check percentage (0-100)
    if 0 < raw <= 100:
        interpretations.append(f"pct={raw}%")

    # Check signed interpretation
    if raw >= 0x8000:
        signed_val = raw - 0x10000
        interpretations.append(f"signed={signed_val}")

    # Check div100 (common for voltages, frequencies)
    div100 = raw / 100.0
    if 0.1 <= div100 <= 100.0:
        interpretations.append(f"v/100={div100:.2f}")

    # Check div1000 (common for cell voltages)
    div1000 = raw / 1000.0
    if 0.001 <= div1000 <= 10.0 and raw > 100:
        interpretations.append(f"v/1000={div1000:.3f}")

    # Check temperature with offset (common: value - 1000 for /10 temp)
    if 100 <= raw <= 2000:
        temp_c = (raw - 1000) / 10.0
        if -50.0 <= temp_c <= 100.0:
            interpretations.append(f"temp?={temp_c:.1f}C")

    # Check if it looks like a bitfield
    bit_count = bin(raw).count("1")
    if bit_count <= 4 and raw > 0:
        interpretations.append(f"bits=0b{raw:016b}")

    # Check 32-bit energy pair (low word)
    if reg_type == "input" and raw > 0:
        # Could be low word of 32-bit counter
        interpretations.append(f"hex=0x{raw:04X}")

    if not interpretations:
        interpretations.append(f"raw={raw} (0x{raw:04X})")

    return " | ".join(interpretations[:4])  # Limit to 4 interpretations


def is_known_register(address: int, reg_type: str) -> list[str]:
    """Check if a register address is in the known map."""
    if reg_type == "holding":
        return KNOWN_HOLDING.get(address, [])
    elif reg_type == "input":
        names = KNOWN_INPUT.get(address, [])
        if not names and address in KNOWN_BATTERY_INPUT:
            return [KNOWN_BATTERY_INPUT[address]]
        return names
    return []


# =============================================================================
# MAIN PROBE
# =============================================================================


def run_probe() -> ProbeResults:
    """Run the complete register probe on all devices."""
    results = ProbeResults()
    results.timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    # Connect to both devices
    clients: dict[str, ModbusTcpClient] = {}
    for name, cfg in DEVICES.items():
        print(f"Connecting to {name} at {cfg['host']}:{cfg['port']}...")
        client = ModbusTcpClient(cfg["host"], port=cfg["port"], timeout=TIMEOUT)
        if not client.connect():
            results.errors.append(f"Failed to connect to {name}")
            print(f"  FAILED to connect to {name}!")
            continue
        clients[name] = client
        print(f"  Connected to {name}")

    if not clients:
        print("No devices connected. Aborting.")
        return results

    # =========================================================================
    # PHASE 1: Standard holding registers 0-999 (both devices)
    # =========================================================================
    print("\n=== PHASE 1: Holding Registers 0-999 (both devices) ===")
    holding_data: dict[str, dict[int, int | None]] = {}
    for name, client in clients.items():
        print(f"  Probing {name} holding 0-999...")
        holding_data[name] = probe_register_range(client, 0, 999, "holding", name)
        responding = sum(1 for v in holding_data[name].values() if v is not None)
        print(f"    {responding} registers responded")

    # =========================================================================
    # PHASE 2: Standard input registers 0-999 (both devices)
    # =========================================================================
    print("\n=== PHASE 2: Input Registers 0-999 (both devices) ===")
    input_data: dict[str, dict[int, int | None]] = {}
    for name, client in clients.items():
        print(f"  Probing {name} input 0-999...")
        input_data[name] = probe_register_range(client, 0, 999, "input", name)
        responding = sum(1 for v in input_data[name].values() if v is not None)
        print(f"    {responding} registers responded")

    # =========================================================================
    # PHASE 3: Battery input registers 5000-5200 (both devices)
    # Only 5002-5121 are expected to exist; skip individual retries for speed
    # =========================================================================
    print("\n=== PHASE 3: Battery Input Registers 5000-5200 (both devices) ===")
    for name, client in clients.items():
        print(f"  Probing {name} input 5000-5200...")
        bat_data = probe_register_range(
            client, 5000, 5200, "input", name, skip_individual_retry=True
        )
        responding = sum(1 for v in bat_data.values() if v is not None)
        print(f"    {responding} registers responded")
        # Merge into input_data
        if name not in input_data:
            input_data[name] = {}
        input_data[name].update(bat_data)

    # =========================================================================
    # PHASE 4: Extended ranges on 18kPV only (mostly non-existent, skip retries)
    # =========================================================================
    if "18kPV" in clients:
        print("\n=== PHASE 4: Extended Holding 1000-2100 (18kPV only) ===")
        ext_hold = probe_register_range(
            clients["18kPV"],
            1000,
            2100,
            "holding",
            "18kPV",
            skip_individual_retry=True,
        )
        responding = sum(1 for v in ext_hold.values() if v is not None)
        print(f"    {responding} registers responded")
        holding_data["18kPV"].update(ext_hold)

        print("\n=== PHASE 5: Extended Input 1000-2100 (18kPV only) ===")
        ext_inp = probe_register_range(
            clients["18kPV"],
            1000,
            2100,
            "input",
            "18kPV",
            skip_individual_retry=True,
        )
        responding = sum(1 for v in ext_inp.values() if v is not None)
        print(f"    {responding} registers responded")
        input_data["18kPV"].update(ext_inp)

    # =========================================================================
    # COMPILE RESULTS
    # =========================================================================
    print("\n=== Compiling results ===")

    # Holding registers
    all_holding_addrs = set()
    for dev_data in holding_data.values():
        for addr, val in dev_data.items():
            if val is not None:
                all_holding_addrs.add(addr)

    for addr in sorted(all_holding_addrs):
        values = {}
        for name in DEVICES:
            if name in holding_data and addr in holding_data[name]:
                values[name] = holding_data[name][addr]
            else:
                values[name] = None
        known = is_known_register(addr, "holding")
        reading = RegisterReading(
            address=addr,
            reg_type="holding",
            values=values,
            known_names=known,
        )
        # Interpret using first non-None value
        for v in values.values():
            if v is not None:
                reading.interpretation = interpret_value(v, addr, "holding", known)
                break
        results.holding.append(reading)

    # Input registers
    all_input_addrs = set()
    for dev_data in input_data.values():
        for addr, val in dev_data.items():
            if val is not None:
                all_input_addrs.add(addr)

    for addr in sorted(all_input_addrs):
        values = {}
        for name in DEVICES:
            if name in input_data and addr in input_data[name]:
                values[name] = input_data[name][addr]
            else:
                values[name] = None
        known = is_known_register(addr, "input")
        reading = RegisterReading(
            address=addr,
            reg_type="input",
            values=values,
            known_names=known,
        )
        for v in values.values():
            if v is not None:
                reading.interpretation = interpret_value(v, addr, "input", known)
                break
        results.input.append(reading)

    # Disconnect
    for name, client in clients.items():
        client.close()
        print(f"  Disconnected from {name}")

    return results


# =============================================================================
# OUTPUT GENERATION
# =============================================================================


def save_json(results: ProbeResults) -> Path:
    """Save raw results as JSON for future analysis."""
    data: dict[str, Any] = {
        "timestamp": results.timestamp,
        "devices": {name: cfg for name, cfg in DEVICES.items()},
        "holding_registers": [],
        "input_registers": [],
        "errors": results.errors,
    }

    for r in results.holding:
        data["holding_registers"].append(
            {
                "address": r.address,
                "values": r.values,
                "known_names": r.known_names,
                "interpretation": r.interpretation,
            }
        )

    for r in results.input:
        data["input_registers"].append(
            {
                "address": r.address,
                "values": r.values,
                "known_names": r.known_names,
                "interpretation": r.interpretation,
            }
        )

    json_path = OUTPUT_DIR / "live_register_probe_full.json"
    json_path.write_text(json.dumps(data, indent=2))
    print(f"  JSON saved to {json_path}")
    return json_path


def generate_markdown(results: ProbeResults) -> Path:
    """Generate the comprehensive markdown report."""
    lines: list[str] = []

    # Count stats
    new_holding = [r for r in results.holding if not r.known_names]
    new_input = [r for r in results.input if not r.known_names]
    known_holding = [r for r in results.holding if r.known_names]
    known_input = [r for r in results.input if r.known_names]

    lines.append("# Live Modbus Register Probe - Complete Map")
    lines.append("")
    lines.append(f"**Probe date**: {results.timestamp}")
    lines.append("**Firmware**: fAAB-2727 (both devices)")
    lines.append(
        "**Devices**: 18kPV (10.100.14.68:502), FlexBOSS21 (10.100.10.184:502)"
    )
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Holding | Input | Total |")
    lines.append("|--------|---------|-------|-------|")
    lines.append(
        f"| Responding registers | {len(results.holding)} | {len(results.input)} | {len(results.holding) + len(results.input)} |"
    )
    lines.append(
        f"| KNOWN (in pylxpweb) | {len(known_holding)} | {len(known_input)} | {len(known_holding) + len(known_input)} |"
    )
    lines.append(
        f"| **NEW (undocumented)** | **{len(new_holding)}** | **{len(new_input)}** | **{len(new_holding) + len(new_input)}** |"
    )
    lines.append("")

    # New registers highlight
    if new_holding or new_input:
        lines.append("## Newly Discovered Registers")
        lines.append("")
        lines.append(
            "These registers respond but are NOT in the current pylxpweb register map."
        )
        lines.append("")

        if new_holding:
            lines.append("### New Holding Registers")
            lines.append("")
            lines.append("| Addr | 18kPV | FlexBOSS21 | Interpretation | Notes |")
            lines.append("|------|-------|------------|----------------|-------|")
            for r in new_holding:
                v18 = r.values.get("18kPV")
                vfb = r.values.get("FlexBOSS21")
                v18_str = f"{v18} (0x{v18:04X})" if v18 is not None else "N/A"
                vfb_str = f"{vfb} (0x{vfb:04X})" if vfb is not None else "N/A"
                same = ""
                if v18 is not None and vfb is not None:
                    same = "SAME" if v18 == vfb else "DIFFERENT"
                elif v18 is not None and vfb is None:
                    same = "18kPV-only"
                elif v18 is None and vfb is not None:
                    same = "FlexBOSS21-only"
                lines.append(
                    f"| {r.address} | {v18_str} | {vfb_str} | {r.interpretation} | {same} |"
                )
            lines.append("")

        if new_input:
            lines.append("### New Input Registers")
            lines.append("")
            lines.append("| Addr | 18kPV | FlexBOSS21 | Interpretation | Notes |")
            lines.append("|------|-------|------------|----------------|-------|")
            for r in new_input:
                v18 = r.values.get("18kPV")
                vfb = r.values.get("FlexBOSS21")
                v18_str = f"{v18} (0x{v18:04X})" if v18 is not None else "N/A"
                vfb_str = f"{vfb} (0x{vfb:04X})" if vfb is not None else "N/A"
                same = ""
                if v18 is not None and vfb is not None:
                    same = "SAME" if v18 == vfb else "DIFFERENT"
                elif v18 is not None and vfb is None:
                    same = "18kPV-only"
                elif v18 is None and vfb is not None:
                    same = "FlexBOSS21-only"
                lines.append(
                    f"| {r.address} | {v18_str} | {vfb_str} | {r.interpretation} | {same} |"
                )
            lines.append("")

    # Full holding register map
    lines.append("## Complete Holding Register Map")
    lines.append("")
    lines.append("| Addr | Known Name | 18kPV | FlexBOSS21 | Interpretation | Status |")
    lines.append("|------|-----------|-------|------------|----------------|--------|")
    for r in results.holding:
        v18 = r.values.get("18kPV")
        vfb = r.values.get("FlexBOSS21")
        v18_str = str(v18) if v18 is not None else "ERR"
        vfb_str = str(vfb) if vfb is not None else "ERR"
        name = ", ".join(r.known_names[:2]) if r.known_names else "???"
        if len(r.known_names) > 2:
            name += f" (+{len(r.known_names) - 2})"
        status = "KNOWN" if r.known_names else "**NEW**"
        interp = r.interpretation[:60] if r.interpretation else ""
        lines.append(
            f"| {r.address} | {name} | {v18_str} | {vfb_str} | {interp} | {status} |"
        )
    lines.append("")

    # Full input register map
    lines.append("## Complete Input Register Map")
    lines.append("")
    lines.append("| Addr | Known Name | 18kPV | FlexBOSS21 | Interpretation | Status |")
    lines.append("|------|-----------|-------|------------|----------------|--------|")
    for r in results.input:
        v18 = r.values.get("18kPV")
        vfb = r.values.get("FlexBOSS21")
        v18_str = str(v18) if v18 is not None else "ERR"
        vfb_str = str(vfb) if vfb is not None else "ERR"
        name = ", ".join(r.known_names[:2]) if r.known_names else "???"
        if len(r.known_names) > 2:
            name += f" (+{len(r.known_names) - 2})"
        status = "KNOWN" if r.known_names else "**NEW**"
        interp = r.interpretation[:60] if r.interpretation else ""
        lines.append(
            f"| {r.address} | {name} | {v18_str} | {vfb_str} | {interp} | {status} |"
        )
    lines.append("")

    # Value comparison section
    lines.append("## Value Comparison (Same vs Different)")
    lines.append("")
    lines.append(
        "Registers where both devices respond but with different values suggest"
    )
    lines.append("live/dynamic data or model-specific configuration.")
    lines.append("")

    different_holding = []
    same_holding = []
    for r in results.holding:
        v18 = r.values.get("18kPV")
        vfb = r.values.get("FlexBOSS21")
        if v18 is not None and vfb is not None:
            if v18 != vfb:
                different_holding.append(r)
            else:
                same_holding.append(r)

    different_input = []
    same_input = []
    for r in results.input:
        v18 = r.values.get("18kPV")
        vfb = r.values.get("FlexBOSS21")
        if v18 is not None and vfb is not None:
            if v18 != vfb:
                different_input.append(r)
            else:
                same_input.append(r)

    lines.append(f"### Holding: Different Values ({len(different_holding)} registers)")
    lines.append("")
    if different_holding:
        lines.append("| Addr | Name | 18kPV | FlexBOSS21 | Delta |")
        lines.append("|------|------|-------|------------|-------|")
        for r in different_holding:
            v18 = r.values["18kPV"]
            vfb = r.values["FlexBOSS21"]
            name = ", ".join(r.known_names[:2]) if r.known_names else "???"
            delta = v18 - vfb if v18 is not None and vfb is not None else "?"
            lines.append(
                f"| {r.address} | {name} | {v18} (0x{v18:04X}) | {vfb} (0x{vfb:04X}) | {delta} |"
            )
        lines.append("")

    lines.append(f"### Input: Different Values ({len(different_input)} registers)")
    lines.append("")
    if different_input:
        lines.append("| Addr | Name | 18kPV | FlexBOSS21 | Delta |")
        lines.append("|------|------|-------|------------|-------|")
        for r in different_input:
            v18 = r.values["18kPV"]
            vfb = r.values["FlexBOSS21"]
            name = ", ".join(r.known_names[:2]) if r.known_names else "???"
            delta = v18 - vfb if v18 is not None and vfb is not None else "?"
            lines.append(
                f"| {r.address} | {name} | {v18} (0x{v18:04X}) | {vfb} (0x{vfb:04X}) | {delta} |"
            )
        lines.append("")

    if results.errors:
        lines.append("## Errors")
        lines.append("")
        for err in results.errors:
            lines.append(f"- {err}")
        lines.append("")

    md_path = OUTPUT_DIR / "REGISTER_MAP_LIVE_PROBE.md"
    md_path.write_text("\n".join(lines))
    print(f"  Markdown saved to {md_path}")
    return md_path


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys

    # Force line-buffered stdout for real-time output
    sys.stdout.reconfigure(line_buffering=True)

    print("=" * 70)
    print("EG4 Comprehensive Modbus Register Probe")
    print("=" * 70)
    print()

    start_time = time.monotonic()
    results = run_probe()
    elapsed = time.monotonic() - start_time

    print(f"\nProbe completed in {elapsed:.1f} seconds")
    print(f"  Holding registers responding: {len(results.holding)}")
    print(f"  Input registers responding: {len(results.input)}")

    save_json(results)
    generate_markdown(results)

    # Quick summary of new registers
    new_h = [r for r in results.holding if not r.known_names]
    new_i = [r for r in results.input if not r.known_names]
    print(f"\n  NEW holding registers: {len(new_h)}")
    print(f"  NEW input registers: {len(new_i)}")
    if new_h:
        print(f"  New holding addresses: {[r.address for r in new_h]}")
    if new_i:
        print(f"  New input addresses: {[r.address for r in new_i]}")
