# DWIN DGUS LCD Display Firmware Analysis

**Firmware**: EG4 18KPV/12KPV LCD V18 (LCDV18_20241114)
**Display**: DWIN T5L DGUS II, 7-inch 1024x600
**Analysis date**: 2026-04-13
**Source files**: `scratchpad/firmware/lcd_v18/`

---

## Table of Contents

1. [T5L Configuration](#1-t5l-configuration)
2. [Page Structure Overview](#2-page-structure-overview)
3. [Display Variable Register Map](#3-display-variable-register-map)
4. [Register Cross-Reference with pylxpweb](#4-register-cross-reference)
5. [Touch Input Map](#5-touch-input-map)
6. [VP Address Configuration](#6-vp-address-configuration)
7. [Page-by-Page Detail](#7-page-by-page-detail)
8. [Key Findings](#8-key-findings)

---

## 1. T5L Configuration

| Parameter | Value |
|-----------|-------|
| Signature | `T5LC1` |
| Baud Rate | 115200 bps |
| Resolution | 1024x600 |
| Config Size | 46 bytes |
| Raw (hex) | `54354c4331bf00102028001c6400753000000000000000000000000000000000000014000000fe006e0bb800f00a` |

The T5L 12720 is a DWIN 7-inch LCD with capacitive touch panel.
Communication with the inverter MCU is via UART at 115200 bps.
The MCU writes Modbus register values to DWIN VP (Variable Pointer)
addresses, and the display renders them according to ShowFile definitions.

## 2. Page Structure Overview

**Total pages defined**: 61
**Active pages (with content)**: 50

| Page | Display Vars | Touch Regions | Description |
|------|-------------|---------------|-------------|
| 6 | 0 (+1 icons) | 1 | Navigation / Status |
| 8 | 29 (+34 icons) | 3 | PV + Battery + Grid + EPS/Backup + Energy + Temperature |
| 9 | 0 (+32 icons) | 14 | Navigation / Status |
| 10 | 0 (+32 icons) | 10 | Navigation / Status |
| 12 | 12 (+2 icons) | 7 | PV + Battery + Grid + Energy |
| 13 | 24 (+2 icons) | 7 | Battery + Grid + EPS/Backup + Energy |
| 14 | 22 | 7 | EPS/Backup + Energy + Temperature |
| 15 | 16 | 7 | Battery + Load/Consumption + Energy |
| 16 | 30 (+13 icons) | 7 | Battery Detail |
| 17 | 0 (+21 icons) | 7 | Navigation / Status |
| 18 | 0 (+21 icons) | 7 | Navigation / Status |
| 19 | 0 (+4 icons) | 31 | Navigation / Status |
| 20 | 0 (+1 icons) | 10 | Navigation / Status |
| 21 | 0 (+1 icons) | 33 | Navigation / Status |
| 22 | 0 (+1 icons) | 35 | Navigation / Status |
| 23 | 0 | 12 | Navigation / Status |
| 24 | 0 (+8 icons) | 17 | Navigation / Status |
| 25 | 0 | 8 |  |
| 26 | 0 (+1 icons) | 30 | Navigation / Status |
| 27 | 0 (+2 icons) | 1 | Navigation / Status |
| 28 | 0 (+2 icons) | 1 | Navigation / Status |
| 29 | 0 (+2 icons) | 1 | Navigation / Status |
| 30 | 0 (+2 icons) | 1 | Navigation / Status |
| 31 | 0 (+2 icons) | 2 | Navigation / Status |
| 32 | 0 (+9 icons) | 1 | Navigation / Status |
| 33 | 0 (+2 icons) | 1 | Navigation / Status |
| 34 | 0 (+4 icons) | 0 | Navigation / Status |
| 35 | 0 (+38 icons) | 1 | Navigation / Status |
| 36 | 0 (+31 icons) | 1 | Navigation / Status |
| 37 | 0 (+23 icons) | 1 | Navigation / Status |
| 38 | 0 (+12 icons) | 1 | Navigation / Status |
| 39 | 0 (+21 icons) | 7 | Navigation / Status |
| 40 | 0 (+21 icons) | 7 | Navigation / Status |
| 41 | 0 | 9 |  |
| 43 | 0 (+5 icons) | 43 | Navigation / Status |
| 44 | 0 (+6 icons) | 1 | Navigation / Status |
| 45 | 0 (+5 icons) | 43 | Navigation / Status |
| 46 | 0 (+4 icons) | 31 | Navigation / Status |
| 47 | 0 (+1 icons) | 3 | Navigation / Status |
| 48 | 0 (+1 icons) | 6 | Navigation / Status |
| 49 | 1 (+2 icons) | 6 | Data (regs 185-185) |
| 50 | 0 | 21 | Navigation / Status |
| 51 | 0 (+1 icons) | 1 | Navigation / Status |
| 52 | 0 | 32 | Navigation / Status |
| 53 | 0 (+1 icons) | 1 | Navigation / Status |
| 54 | 0 (+4 icons) | 31 | Navigation / Status |
| 55 | 0 (+2 icons) | 1 | Navigation / Status |
| 56 | 0 (+2 icons) | 21 | Navigation / Status |
| 57 | 0 (+2 icons) | 19 | Navigation / Status |
| 58 | 0 (+3 icons) | 1 | Navigation / Status |
| 59 | 0 (+3 icons) | 2 | Navigation / Status |
| 60 | 0 (+2 icons) | 21 | Navigation / Status |

## 3. Display Variable Register Map

Extracted from `14ShowFile.bin`. Each entry maps a Modbus input register
to a display position on the LCD screen with specific formatting.

**Entry format** (32 bytes per variable):
- Bytes 0-1: SP (Description Pointer) address -- **0x5A10 = register data**
- Byte 6: Display type (0x50=numeric data, 0x70=icon, 0x00=datetime)
- Byte 7: **Modbus register address** (only valid when SP=0x5A10)
- Bytes 8-9: X position on screen
- Bytes 10-11: Y position on screen
- Byte 17: Number of display digits
- Byte 18: Decimal places (determines scale factor)
- Byte 19: Format flags (bit 1 = signed)
- Bytes 20-25: Unit suffix string (ASCII)

**SP Address Types:**
- `0x5A10` = DATA_VAR (numeric register display) -- byte[7] = Modbus register
- `0x5A00` = ICON_ANIM (animated icons, power flow arrows)
- `0x5A01` = ICON_SCROLL (scrolling/rotating icons)
- `0x5A11` = ICON_VAR (state-dependent variable icon)
- `0x5A12` = DATETIME (date/time display)
- `0x5A04` = PAGE_SWITCH (page navigation trigger)
- `0x5A06` = BTN_RETURN (return/back button)

**Unique registers displayed**: 106

| Reg | Digits | DP | Scale | Unit | Signed | Pages | Known Name |
|-----|--------|----|-------|------|--------|-------|------------|
| 0 | 3 | 1 | /10 | V | No | 8, 12 | `device_status` |
| 1 | 3 | 1 | /10 | V | No | 8, 12 | `pv1_voltage` |
| 2 | 4 | 1 | /10 | kW | No | 8, 12 | `pv2_voltage` |
| 3 | 4 | 1 | /10 | kW | No | 8, 12 | `pv3_voltage` |
| 6 | 5 | 1 | /10 | kWh | No | 12 | `total_pv_power` |
| 7 | 9 | 1 | /10 | kWh | Yes | 12 | `pv1_power` |
| 9 | 5 | 1 | /10 | kWh | No | 12 | `pv3_power` |
| 10 | 9 | 1 | /10 | kWh | Yes | 12 | `charge_power` |
| 12 | 5 | 1 | /10 | kWh | No | 8 | `grid_voltage_r` |
| 13 | 9 | 1 | /10 | kWh | Yes | 8 | `grid_voltage_s` |
| 15 | 3 | 1 | /10 | V | No | 8, 12 | `grid_frequency` |
| 17 | 3 | 1 | /10 | V | No | 13 | `rectifier_power` |
| 18 | 3 | 0 | x1 | % | Yes | 8, 13 | `inverter_rms_current_r` |
| 19 | 4 | 1 | /10 | V | No | 8, 13 | `device_type_code` |
| 20 | 5 | 0 | x1 |  | Yes | 13 | `eps_voltage_r` |
| 22 | 5 | 0 | x1 | W | No | 13 | `eps_voltage_t` |
| 23 | 5 | 0 | x1 | W | No | 13 | `eps_frequency` |
| 24 | 4 | 1 | /10 | kW | No | 8 | `eps_power` |
| 27 | 5 | 1 | /10 | kWh | No | 13 | `power_to_user` |
| 28 | 9 | 1 | /10 | kWh | Yes | 13 | `` |
| 30 | 5 | 1 | /10 | kWh | No | 8, 13 | `inverter_energy_today` |
| 31 | 9 | 1 | /10 | kWh | Yes | 8, 13 | `inverter_energy_today_alt` |
| 33 | 4 | 1 | /10 | kW | No | 8, 12 | `charge_energy_today` |
| 34 | 4 | 1 | /10 | A | No | 13 | `discharge_energy_today` |
| 36 | 4 | 1 | /10 | A | No | 13 | `grid_export_energy_today` |
| 37 | 4 | 1 | /10 | A | No | 13 | `grid_import_energy_today` |
| 38 | 3 | 1 | /10 | V | No | 13 | `bus_voltage_1` |
| 39 | 3 | 1 | /10 | V | No | 13 | `bus_voltage_2` |
| 40 | 5 | 0 | x1 |  | No | 13 | `pv1_energy_today` |
| 41 | 5 | 0 | x1 |  | No | 13 | `pv2_energy_today` |
| 42 | 1 | 3 | /1000 | V | No | 13 | `pv3_energy_today` |
| 43 | 1 | 3 | /1000 | V | No | 13 | `` |
| 44 | 3 | 1 | /10 |  | No | 13 | `pv1_current` |
| 45 | 3 | 1 | /10 |  | No | 13 | `pv2_current` |
| 46 | 5 | 0 | x1 |  | No | 13 | `inverter_energy_total_lo` |
| 47 | 9 | 1 | /10 | kWh | Yes | 12 | `inverter_energy_total_hi` |
| 50 | 4 | 1 | /10 | V | No | 14 | `charge_energy_total_lo` |
| 51 | 4 | 2 | /100 | Hz | No | 14 | `charge_energy_total_hi` |
| 52 | 3 | 1 | /10 | V | No | 8 | `discharge_energy_total_lo` |
| 53 | 2 | 2 | /100 | Hz | No | 8 | `discharge_energy_total_hi` |
| 54 | 4 | 1 | /10 | V | No | 14 | `grid_l1_voltage_ext` |
| 55 | 4 | 1 | /10 | V | No | 14 | `grid_l2_voltage_ext` |
| 56 | 5 | 0 | x1 | W | No | 14 | `grid_export_energy_total_lo` |
| 57 | 5 | 0 | x1 | W | No | 14 | `grid_export_energy_total_hi` |
| 58 | 4 | 1 | /10 | kW | No | 8 | `grid_import_energy_total_lo` |
| 61 | 5 | 1 | /10 | kWh | No | 14 | `pv1_energy_total_lo` |
| 62 | 9 | 1 | /10 | kWh | Yes | 14 | `pv1_energy_total_hi` |
| 64 | 5 | 1 | /10 | kWh | No | 8, 14 | `internal_temperature` |
| 65 | 9 | 1 | /10 | kWh | Yes | 8, 14 | `radiator_temperature_1` |
| 67 | 5 | 0 | x1 | W | No | 14 | `battery_temperature` |
| 68 | 5 | 0 | x1 | W | No | 14 | `eps_power_l2` |
| 71 | 5 | 1 | /10 | kWh | No | 14 | `pv2_energy_total_lo` |
| 72 | 9 | 1 | /10 | kWh | Yes | 14 | `pv2_energy_total_hi` |
| 74 | 5 | 1 | /10 | kWh | No | 14 | `pv3_energy_total_lo` |
| 75 | 9 | 1 | /10 | kWh | Yes | 14 | `pv3_energy_total_hi` |
| 77 | 4 | 1 | /10 | kW | No | 8 | `total_load_power` |
| 78 | 5 | 1 | /10 | kWh | No | 12 | `bms_feature_flags` |
| 81 | 5 | 1 | /10 | kWh | No | 8, 14 | `bms_charge_current_limit` |
| 82 | 9 | 1 | /10 | kWh | Yes | 8, 14 | `bms_discharge_current_limit` |
| 84 | 4 | 1 | /10 | V | No | 14 | `eps_l1_voltage` |
| 85 | 4 | 2 | /100 | Hz | No | 14 | `eps_l1_frequency` |
| 86 | 4 | 1 | /10 | kW | No | 8, 14 | `eps_power_combined` |
| 91 | 3 | 1 | /10 | V | No | 8, 15 | `battery_current` |
| 92 | 4 | 1 | /10 | V | No | 15 | `grid_voltage_l1` |
| 93 | 4 | 1 | /10 | V | No | 15 | `grid_voltage_l2` |
| 94 | 2 | 2 | /100 | Hz | No | 8, 15 | `grid_frequency_alt` |
| 95 | 4 | 1 | /10 | kW | No | 8 | `load_power_alt` |
| 98 | 5 | 0 | x1 | W | No | 15 | `consumption_power` |
| 99 | 5 | 0 | x1 | W | No | 15 | `consumption_power_l2` |
| 100 | 5 | 0 | x1 | VA | No | 15 | `apparent_power` |
| 101 | 5 | 0 | x1 | VA | No | 15 | `apparent_power_l2` |
| 102 | 5 | 0 | x1 | VA | No | 15 | `apparent_power_total` |
| 103 | 5 | 1 | /10 | kWh | No | 15 | `consumption_energy_today` |
| 104 | 9 | 1 | /10 | kWh | Yes | 15 | `consumption_energy_total_lo` |
| 106 | 5 | 1 | /10 | kWh | No | 15 | `ac_charge_energy_today` |
| 107 | 9 | 1 | /10 | kWh | Yes | 15 | `ac_charge_energy_total_lo` |
| 109 | 5 | 1 | /10 | kWh | No | 15 | `eps_energy_today` |
| 110 | 9 | 1 | /10 | kWh | Yes | 15 | `eps_energy_total_lo` |
| 112 | 3 | 0 | x1 |  | Yes | 16 | `pv1_energy_today_2` |
| 113 | 3 | 0 | x1 |  | Yes | 16 | `pv2_energy_today_2` |
| 114 | 5 | 0 | x1 | W | No | 14 | `dongle_comm_status` |
| 115 | 5 | 0 | x1 | W | No | 15 | `serial_reg0` |
| 120 | 3 | 1 | /10 | V | No | 16 | `dongle_firmware_version` |
| 121 | 3 | 1 | /10 | V | No | 16 | `grid_voltage_r_ext2` |
| 122 | 3 | 1 | /10 | V | No | 16 | `grid_voltage_s_ext2` |
| 123 | 3 | 1 | /10 | V | No | 16 | `grid_voltage_t_ext2` |
| 124 | 3 | 1 | /10 |  | No | 16 | `grid_current_l1` |
| 125 | 3 | 1 | /10 |  | No | 16 | `grid_current_l2` |
| 126 | 3 | 1 | /10 |  | No | 16 | `grid_current_l3` |
| 127 | 3 | 1 | /10 |  | No | 16 | `eps_l1_voltage_split` |
| 128 | 5 | 0 | x1 |  | No | 16 | `eps_l2_voltage_split` |
| 129 | 5 | 0 | x1 |  | No | 16 | `eps_power_l1` |
| 130 | 5 | 0 | x1 |  | Yes | 16 | `grid_power_import` |
| 131 | 5 | 0 | x1 |  | Yes | 16 | `grid_power_export` |
| 132 | 5 | 0 | x1 |  | No | 16 | `inverter_power_l1` |
| 133 | 5 | 0 | x1 |  | No | 16 | `inverter_power_l2` |
| 134 | 3 | 0 | x1 | A | Yes | 16 | `battery_discharge_a` |
| 135 | 3 | 0 | x1 | A | Yes | 16 | `battery_charge_a` |
| 136 | 5 | 0 | x1 |  | Yes | 16 | `total_consumption_w` |
| 137 | 5 | 0 | x1 |  | Yes | 16 | `grid_power_total` |
| 146 | 5 | 0 | x1 | Ah | No | 13 | `battery_remaining_ah` |
| 166 | 2 | 0 | x1 |  | Yes | 8 | `` |
| 169 | 1 | 0 | x1 |  | Yes | 16 | `` |
| 176 | 4 | 1 | /10 | kW | No | 8 | `` |
| 183 | 5 | 0 | x1 | S | No | 8 | `` |
| 185 | 5 | 0 | x1 | S | No | 49 | `` |

## 4. Register Cross-Reference with pylxpweb

### Registers displayed on LCD that ARE in pylxpweb

| Reg | LCD Unit | LCD Scale | pylxpweb Name | pylxpweb Scale | Match? |
|-----|----------|-----------|---------------|----------------|--------|
| 0 | V | /10 | `device_status` | x1 | MISMATCH |
| 1 | V | /10 | `pv1_voltage` | /10 | YES |
| 2 | kW | /10 | `pv2_voltage` | /10 | YES |
| 3 | kW | /10 | `pv3_voltage` | /10 | YES |
| 6 | kWh | /10 | `total_pv_power` | x1 | MISMATCH |
| 7 | kWh | /10 | `pv1_power` | x1 | MISMATCH |
| 9 | kWh | /10 | `pv3_power` | x1 | MISMATCH |
| 10 | kWh | /10 | `charge_power` | x1 | MISMATCH |
| 12 | kWh | /10 | `grid_voltage_r` | /10 | YES |
| 13 | kWh | /10 | `grid_voltage_s` | /10 | YES |
| 15 | V | /10 | `grid_frequency` | /100 | MISMATCH |
| 17 | V | /10 | `rectifier_power` | x1 | MISMATCH |
| 18 | % | x1 | `inverter_rms_current_r` | /100 | MISMATCH |
| 19 | V | /10 | `device_type_code` | x1 | MISMATCH |
| 20 |  | x1 | `eps_voltage_r` | /10 | MISMATCH |
| 22 | W | x1 | `eps_voltage_t` | /10 | MISMATCH |
| 23 | W | x1 | `eps_frequency` | /100 | MISMATCH |
| 24 | kW | /10 | `eps_power` | x1 | MISMATCH |
| 27 | kWh | /10 | `power_to_user` | x1 | MISMATCH |
| 30 | kWh | /10 | `inverter_energy_today` | /10 | YES |
| 31 | kWh | /10 | `inverter_energy_today_alt` | /10 | YES |
| 33 | kW | /10 | `charge_energy_today` | /10 | YES |
| 34 | A | /10 | `discharge_energy_today` | /10 | YES |
| 36 | A | /10 | `grid_export_energy_today` | /10 | YES |
| 37 | A | /10 | `grid_import_energy_today` | /10 | YES |
| 38 | V | /10 | `bus_voltage_1` | /10 | YES |
| 39 | V | /10 | `bus_voltage_2` | /10 | YES |
| 40 |  | x1 | `pv1_energy_today` | /10 | MISMATCH |
| 41 |  | x1 | `pv2_energy_today` | /10 | MISMATCH |
| 42 | V | /1000 | `pv3_energy_today` | /10 | MISMATCH |
| 44 |  | /10 | `pv1_current` | /10 | YES |
| 45 |  | /10 | `pv2_current` | /10 | YES |
| 46 |  | x1 | `inverter_energy_total_lo` | /10 | MISMATCH |
| 47 | kWh | /10 | `inverter_energy_total_hi` | /10 | YES |
| 50 | V | /10 | `charge_energy_total_lo` | /10 | YES |
| 51 | Hz | /100 | `charge_energy_total_hi` | /10 | MISMATCH |
| 52 | V | /10 | `discharge_energy_total_lo` | /10 | YES |
| 53 | Hz | /100 | `discharge_energy_total_hi` | /10 | MISMATCH |
| 54 | V | /10 | `grid_l1_voltage_ext` | /10 | YES |
| 55 | V | /10 | `grid_l2_voltage_ext` | /10 | YES |
| 56 | W | x1 | `grid_export_energy_total_lo` | /10 | MISMATCH |
| 57 | W | x1 | `grid_export_energy_total_hi` | /10 | MISMATCH |
| 58 | kW | /10 | `grid_import_energy_total_lo` | /10 | YES |
| 61 | kWh | /10 | `pv1_energy_total_lo` | /10 | YES |
| 62 | kWh | /10 | `pv1_energy_total_hi` | /10 | YES |
| 64 | kWh | /10 | `internal_temperature` | x1 | MISMATCH |
| 65 | kWh | /10 | `radiator_temperature_1` | x1 | MISMATCH |
| 67 | W | x1 | `battery_temperature` | x1 | YES |
| 68 | W | x1 | `eps_power_l2` | x1 | YES |
| 71 | kWh | /10 | `pv2_energy_total_lo` | /10 | YES |
| 72 | kWh | /10 | `pv2_energy_total_hi` | /10 | YES |
| 74 | kWh | /10 | `pv3_energy_total_lo` | /10 | YES |
| 75 | kWh | /10 | `pv3_energy_total_hi` | /10 | YES |
| 77 | kW | /10 | `total_load_power` | x1 | MISMATCH |
| 78 | kWh | /10 | `bms_feature_flags` | x1 | MISMATCH |
| 81 | kWh | /10 | `bms_charge_current_limit` | /10 | YES |
| 82 | kWh | /10 | `bms_discharge_current_limit` | /10 | YES |
| 84 | V | /10 | `eps_l1_voltage` | /10 | YES |
| 85 | Hz | /100 | `eps_l1_frequency` | /100 | YES |
| 86 | kW | /10 | `eps_power_combined` | x1 | MISMATCH |
| 91 | V | /10 | `battery_current` | /10 | YES |
| 92 | V | /10 | `grid_voltage_l1` | /10 | YES |
| 93 | V | /10 | `grid_voltage_l2` | /10 | YES |
| 94 | Hz | /100 | `grid_frequency_alt` | /100 | YES |
| 95 | kW | /10 | `load_power_alt` | x1 | MISMATCH |
| 98 | W | x1 | `consumption_power` | x1 | YES |
| 99 | W | x1 | `consumption_power_l2` | x1 | YES |
| 100 | VA | x1 | `apparent_power` | x1 | YES |
| 101 | VA | x1 | `apparent_power_l2` | x1 | YES |
| 102 | VA | x1 | `apparent_power_total` | x1 | YES |
| 103 | kWh | /10 | `consumption_energy_today` | /10 | YES |
| 104 | kWh | /10 | `consumption_energy_total_lo` | /10 | YES |
| 106 | kWh | /10 | `ac_charge_energy_today` | /10 | YES |
| 107 | kWh | /10 | `ac_charge_energy_total_lo` | /10 | YES |
| 109 | kWh | /10 | `eps_energy_today` | /10 | YES |
| 110 | kWh | /10 | `eps_energy_total_lo` | /10 | YES |
| 112 |  | x1 | `pv1_energy_today_2` | /10 | MISMATCH |
| 113 |  | x1 | `pv2_energy_today_2` | /10 | MISMATCH |
| 114 | W | x1 | `dongle_comm_status` | x1 | YES |
| 115 | W | x1 | `serial_reg0` | x1 | YES |
| 120 | V | /10 | `dongle_firmware_version` | x1 | MISMATCH |
| 121 | V | /10 | `grid_voltage_r_ext2` | /10 | YES |
| 122 | V | /10 | `grid_voltage_s_ext2` | /10 | YES |
| 123 | V | /10 | `grid_voltage_t_ext2` | /10 | YES |
| 124 |  | /10 | `grid_current_l1` | /10 | YES |
| 125 |  | /10 | `grid_current_l2` | /10 | YES |
| 126 |  | /10 | `grid_current_l3` | /10 | YES |
| 127 |  | /10 | `eps_l1_voltage_split` | /10 | YES |
| 128 |  | x1 | `eps_l2_voltage_split` | /10 | MISMATCH |
| 129 |  | x1 | `eps_power_l1` | x1 | YES |
| 130 |  | x1 | `grid_power_import` | x1 | YES |
| 131 |  | x1 | `grid_power_export` | x1 | YES |
| 132 |  | x1 | `inverter_power_l1` | x1 | YES |
| 133 |  | x1 | `inverter_power_l2` | x1 | YES |
| 134 | A | x1 | `battery_discharge_a` | /10 | MISMATCH |
| 135 | A | x1 | `battery_charge_a` | /10 | MISMATCH |
| 136 |  | x1 | `total_consumption_w` | x1 | YES |
| 137 |  | x1 | `grid_power_total` | x1 | YES |
| 146 | Ah | x1 | `battery_remaining_ah` | x1 | YES |

**Matched**: 65, **Mismatched**: 34

### Registers displayed on LCD that are NOT in pylxpweb

These are potential new register discoveries from the LCD firmware.

| Reg | Digits | DP | Scale | Unit | Signed | Inferred Purpose | Pages |
|-----|--------|----|-------|------|--------|------------------|-------|
| 28 | 9 | 1 | /10 | kWh | Yes | `energy_lifetime_reg_28` | 13 |
| 43 | 1 | 3 | /1000 | V | No | `voltage_reg_43` | 13 |
| 166 | 2 | 0 | x1 |  | Yes | `unknown_reg_166` | 8 |
| 169 | 1 | 0 | x1 |  | Yes | `unknown_reg_169` | 16 |
| 176 | 4 | 1 | /10 | kW | No | `power_reg_176` | 8 |
| 183 | 5 | 0 | x1 | S | No | `seconds_reg_183` | 8 |
| 185 | 5 | 0 | x1 | S | No | `seconds_reg_185` | 49 |

**New registers found**: 7
**Register addresses**: 28, 43, 166, 169, 176, 183, 185

## 5. Touch Input Map

Extracted from `13TouchFile.bin`. Each entry defines a touch-sensitive
region on the screen that navigates to a target page or writes a value.

**Total touch entries**: 573

### Navigation Targets (unique VP addresses)

| VP/Page | Dec | Count | Source Pages | Likely Function |
|---------|-----|-------|-------------|-----------------|
| 0x0008 | 8 | 27 | 12, 13, 14, 15, 16, 17, 18, 19 (+19) | Home / Main Status |
| 0x0009 | 9 | 1 | 43 |  |
| 0x000A | 10 | 1 | 43 |  |
| 0x000C | 12 | 27 | 8, 13, 14, 15, 16, 17, 18, 19 (+19) | PV Solar |
| 0x000D | 13 | 4 | 12, 14, 15, 16 | Grid AC |
| 0x000E | 14 | 4 | 12, 13, 15, 16 | EPS / Backup |
| 0x000F | 15 | 4 | 12, 13, 14, 16 | Battery |
| 0x0010 | 16 | 4 | 12, 13, 14, 15 | Battery Detail |
| 0x0011 | 17 | 5 | 18, 39, 40, 48, 49 | Settings Menu 1 |
| 0x0012 | 18 | 5 | 17, 39, 40, 48, 49 | Settings Menu 2 |
| 0x0013 | 19 | 2 | 27, 43 | Firmware Update |
| 0x0014 | 20 | 29 | 8, 12, 13, 14, 15, 16, 17, 18 (+21) | System Settings |
| 0x0015 | 21 | 15 | 19, 20, 22, 23, 24, 26, 29, 43 (+7) | Date/Time Settings |
| 0x0016 | 22 | 16 | 19, 20, 21, 23, 24, 26, 30, 43 (+8) | Charge Schedule 1 |
| 0x0017 | 23 | 19 | 19, 20, 21, 22, 24, 26, 35, 36 (+11) | Charge Schedule 2 |
| 0x0018 | 24 | 16 | 19, 20, 21, 22, 23, 26, 32, 43 (+8) | Discharge Schedule |
| 0x001A | 26 | 3 | 21, 33, 50 |  |
| 0x001B | 27 | 7 | 19, 54 | Alarm / Error |
| 0x001D | 29 | 2 | 21 |  |
| 0x001E | 30 | 2 | 22 | Grid Config |
| 0x001F | 31 | 1 | 20 | Generator Config |
| 0x0020 | 32 | 2 | 24 | Data Screen (next) |
| 0x0021 | 33 | 1 | 26 |  |
| 0x0023 | 35 | 1 | 23 |  |
| 0x0024 | 36 | 1 | 23 |  |
| 0x0025 | 37 | 1 | 23 |  |
| 0x0026 | 38 | 1 | 23 |  |
| 0x0027 | 39 | 1 | 17 | Scroll Down (data) |
| 0x0028 | 40 | 1 | 18 | Scroll Up (data) |
| 0x002B | 43 | 29 | 9, 10, 19, 44, 54, 56, 60 | Settings Parameter Select |
| 0x002C | 44 | 2 | 43 |  |
| 0x002D | 45 | 2 | 46, 57 |  |
| 0x002E | 46 | 10 | 20, 21, 22, 23, 24, 26, 45, 47 (+2) |  |
| 0x002F | 47 | 66 | 6, 45, 46, 57 | Logo / Splash |
| 0x0030 | 48 | 27 | 8, 12, 13, 14, 15, 16, 17, 18 (+19) | Menu |
| 0x0031 | 49 | 5 | 17, 18, 39, 40, 48 | Data / Energy |
| 0x0032 | 50 | 2 | 26, 51 |  |
| 0x0033 | 51 | 2 | 50 |  |
| 0x0034 | 52 | 2 | 22, 53 |  |
| 0x0035 | 53 | 2 | 52 |  |
| 0x0036 | 54 | 1 | 55 |  |
| 0x0037 | 55 | 4 | 19 |  |
| 0x0038 | 56 | 4 | 43, 58, 59 |  |
| 0x0039 | 57 | 1 | 45 |  |
| 0x003A | 58 | 7 | 56, 60 |  |
| 0x003B | 59 | 2 | 56, 60 |  |
| 0x003C | 60 | 1 | 61 |  |
| 0x003D | 61 | 2 | 56 |  |
| 0xFF00 | 65280 | 199 | 19, 20, 21, 22, 24, 25, 26, 31 (+8) | Return / Back (with data) |

## 6. VP Address Configuration

Extracted from `22_Config.bin`. Non-zero values in the config space
indicate VP addresses with active data variable configuration.

The config data starts at file offset 0xA000 (VP address range 0x5000+).
Key values:
- `0x3CC3` = Data variable enabled (DWIN enable marker)
- `0x07D1` = 2001 = Display format configuration word
- `0x3A98` = 15000 = Max value or range limit

| VP Address | Value (hex) | Value (dec) | Interpretation |
|------------|-------------|-------------|----------------|
| 0x5006 | 0x3CC3 | 15555 | Data variable ENABLED |
| 0x5008 | 0x3CC3 | 15555 | Data variable ENABLED |
| 0x5009 | 0x3CC3 | 15555 | Data variable ENABLED |
| 0x500B | 0x3CC3 | 15555 | Data variable ENABLED |
| 0x5011 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5012 | 0x6464 | 25700 | Pair: 100, 100 (percent range) |
| 0x5014 | 0x0300 | 768 | Configuration parameter |
| 0x5015 | 0x0032 | 50 | Configuration parameter |
| 0x5016 | 0x3A98 | 15000 | Max value: 15000 (e.g., 15kW) |
| 0x5017 | 0x3CC3 | 15555 | Data variable ENABLED |
| 0x501E | 0x0003 | 3 | Small constant: 3 |
| 0x5020 | 0x0003 | 3 | Small constant: 3 |
| 0x5022 | 0x0BB9 | 3001 | Max value: 3001 |
| 0x5024 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5025 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5026 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5027 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5028 | 0x0003 | 3 | Small constant: 3 |
| 0x5029 | 0x0003 | 3 | Small constant: 3 |
| 0x502A | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x502B | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x502C | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x502D | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x502E | 0x3A98 | 15000 | Max value: 15000 (e.g., 15kW) |
| 0x5030 | 0x3CC3 | 15555 | Data variable ENABLED |
| 0x5032 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5033 | 0x1390 | 5008 | Max value: 5008 (e.g., 500.8V) |
| 0x5036 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5037 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5038 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5039 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5040 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5042 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5043 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5044 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5047 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5049 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x504A | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x504C | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x504E | 0x3CC3 | 15555 | Data variable ENABLED |
| 0x5054 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5055 | 0x1388 | 5000 | Configuration parameter |
| 0x505C | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x505D | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5062 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5063 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5064 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5065 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5066 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5067 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5069 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x506A | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x506C | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x506D | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x506F | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5070 | 0x1010 | 4112 | Configuration parameter |
| 0x5071 | 0x1010 | 4112 | Configuration parameter |
| 0x5078 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x5079 | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x507A | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x507B | 0x07D1 | 2001 | Format: numeric, 4 digits, 1 DP |
| 0x507C | 0x012D | 301 | Configuration parameter |
| 0x507D | 0x012D | 301 | Configuration parameter |
| 0x507E | 0x012D | 301 | Configuration parameter |
| 0x507F | 0x012D | 301 | Configuration parameter |
| 0x508E | 0x0001 | 1 | Small constant: 1 |
| 0x508F | 0x0001 | 1 | Small constant: 1 |
| 0x5090 | 0x0001 | 1 | Small constant: 1 |
| 0x5091 | 0x0001 | 1 | Small constant: 1 |
| 0x50A6 | 0x0101 | 257 | Configuration parameter |
| 0x50A7 | 0x5200 | 20992 | Configuration parameter |
| 0x50A8 | 0x4D00 | 19712 | Configuration parameter |
| 0x50B8 | 0x0001 | 1 | Small constant: 1 |
| 0x50BA | 0x0001 | 1 | Small constant: 1 |
| 0x5100 | 0x07E5 | 2021 | Configuration parameter |
| 0x5104 | 0x0004 | 4 | Small constant: 4 |
| 0x510C | 0x07E5 | 2021 | Configuration parameter |
| 0x510D | 0x0001 | 1 | Small constant: 1 |
| 0x5110 | 0x0001 | 1 | Small constant: 1 |
| 0x5111 | 0x0001 | 1 | Small constant: 1 |
| 0x5114 | 0x2800 | 10240 | Configuration parameter |
| 0x512D | 0x0235 | 565 | Configuration parameter |
| 0x512E | 0x0235 | 565 | Configuration parameter |
| 0x512F | 0x0064 | 100 | Configuration parameter |
| 0x5132 | 0x6464 | 25700 | Pair: 100, 100 (percent range) |
| 0x5133 | 0x5858 | 22616 | Configuration parameter |
| 0x513C | 0x0190 | 400 | Configuration parameter |
| 0x513D | 0x0064 | 100 | Configuration parameter |
| 0x513E | 0x0190 | 400 | Configuration parameter |
| 0x5146 | 0x5858 | 22616 | Configuration parameter |
| 0x5147 | 0x5858 | 22616 | Configuration parameter |
| 0x5148 | 0x5858 | 22616 | Configuration parameter |
| 0x5149 | 0x5858 | 22616 | Configuration parameter |
| 0x514A | 0x5858 | 22616 | Configuration parameter |
| 0x514B | 0x4541 | 17729 | Configuration parameter |
| 0x514C | 0x4141 | 16705 | Configuration parameter |
| 0x514D | 0x3030 | 12336 | Configuration parameter |
| 0x514E | 0x3030 | 12336 | Configuration parameter |
| 0x5153 | 0x0001 | 1 | Small constant: 1 |
| 0x7000 | 0x312E | 12590 | Configuration parameter |
| 0x7001 | 0x3000 | 12288 | Configuration parameter |
| 0x7003 | 0x2D00 | 11520 | Configuration parameter |
| 0x7004 | 0x506E | 20590 | Configuration parameter |
| 0x7005 | 0x756D | 30061 | Configuration parameter |
| 0x7006 | 0x203A | 8250 | Configuration parameter |
| 0x7007 | 0x526F | 21103 | Configuration parameter |
| 0x7008 | 0x6C65 | 27749 | Configuration parameter |
| 0x7009 | 0x203A | 8250 | Configuration parameter |
| 0x700A | 0x5068 | 20584 | Configuration parameter |
| 0x700B | 0x6173 | 24947 | Configuration parameter |
| 0x700C | 0x6520 | 25888 | Configuration parameter |
| 0x700D | 0x3A00 | 14848 | Configuration parameter |
| 0x705B | 0x2F00 | 12032 | Configuration parameter |
| 0x8002 | 0x0312 | 786 | Configuration parameter |

## 7. Page-by-Page Detail

Detailed register listing for each active display page.

### Page 6: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 464 | 84 | 579 | 192 | 0x002F | Logo / Splash |

### Page 8: PV + Battery + Grid + EPS/Backup + Energy + Temperature

**Register Data Variables** (SP=0x5A10, actual Modbus registers):

| Reg | X | Y | Digits | DP | Unit | Name |
|-----|---|---|--------|----|------|------|
| 183 | 123 | 9 | 5 | 0 | S | `seconds_reg_183` |
| 0 | 59 | 61 | 3 | 1 | V | `device_status` |
| 2 | 127 | 61 | 4 | 1 | kW | `pv2_voltage` |
| 176 | 281 | 61 | 4 | 1 | kW | `power_reg_176` |
| 12 | 647 | 70 | 5 | 1 | kWh | `grid_voltage_r` |
| 1 | 59 | 90 | 3 | 1 | V | `pv1_voltage` |
| 3 | 127 | 90 | 4 | 1 | kW | `pv3_voltage` |
| 13 | 647 | 106 | 9 | 1 | kWh | `grid_voltage_s` |
| 86 | 392 | 117 | 4 | 1 | kW | `eps_power_combined` |
| 15 | 59 | 120 | 3 | 1 | V | `grid_frequency` |
| 33 | 127 | 120 | 4 | 1 | kW | `charge_energy_today` |
| 30 | 646 | 168 | 5 | 1 | kWh | `inverter_energy_today` |
| 31 | 647 | 204 | 9 | 1 | kWh | `inverter_energy_today_alt` |
| 53 | 479 | 213 | 2 | 2 | Hz | `discharge_energy_total_hi` |
| 18 | 36 | 218 | 3 | 0 | % | `inverter_rms_current_r` |
| 19 | 11 | 251 | 4 | 1 | V | `device_type_code` |
| 52 | 479 | 256 | 3 | 1 | V | `discharge_energy_total_lo` |
| 64 | 647 | 264 | 5 | 1 | kWh | `internal_temperature` |
| 24 | 74 | 287 | 4 | 1 | kW | `eps_power` |
| 58 | 413 | 287 | 4 | 1 | kW | `grid_import_energy_total_lo` |
| 65 | 647 | 301 | 9 | 1 | kWh | `radiator_temperature_1` |
| 95 | 143 | 330 | 4 | 1 | kW | `load_power_alt` |
| 166 | 520 | 341 | 2 | 0 |  | `unknown_reg_166` |
| 91 | 143 | 358 | 3 | 1 | V | `battery_current` |
| 81 | 647 | 359 | 5 | 1 | kWh | `bms_charge_current_limit` |
| 94 | 143 | 385 | 2 | 2 | Hz | `grid_frequency_alt` |
| 77 | 304 | 395 | 4 | 1 | kW | `total_load_power` |
| 82 | 647 | 396 | 9 | 1 | kWh | `bms_discharge_current_limit` |
| 166 | 520 | 398 | 1 | 0 |  | `unknown_reg_166` |

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 30 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 4 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 141 | 400 | 221 | 480 | 0x000C | PV Solar |
| 268 | 400 | 348 | 480 | 0x0030 | Menu |
| 391 | 400 | 471 | 480 | 0x0014 | System Settings |

### Page 9: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 32 entries (icon indices, NOT registers)

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 742 | 9 | 786 | 48 | 0x002B | Settings Parameter Select |
| 40 | 57 | 214 | 92 | 0x002B | Settings Parameter Select |
| 225 | 57 | 399 | 92 | 0x002B | Settings Parameter Select |
| 407 | 57 | 581 | 92 | 0x002B | Settings Parameter Select |
| 225 | 102 | 399 | 137 | 0x002B | Settings Parameter Select |
| 407 | 102 | 581 | 137 | 0x002B | Settings Parameter Select |
| 36 | 151 | 210 | 186 | 0x002B | Settings Parameter Select |
| 406 | 244 | 580 | 279 | 0x002B | Settings Parameter Select |
| 406 | 195 | 580 | 230 | 0x002B | Settings Parameter Select |
| 39 | 297 | 213 | 332 | 0x002B | Settings Parameter Select |
| 227 | 297 | 385 | 332 | 0x002B | Settings Parameter Select |
| 404 | 396 | 562 | 431 | 0x002B | Settings Parameter Select |
| 588 | 393 | 746 | 428 | 0x002B | Settings Parameter Select |
| 594 | 244 | 752 | 279 | 0x002B | Settings Parameter Select |

### Page 10: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 32 entries (icon indices, NOT registers)

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 744 | 9 | 788 | 48 | 0x002B | Settings Parameter Select |
| 41 | 57 | 199 | 92 | 0x002B | Settings Parameter Select |
| 226 | 57 | 384 | 92 | 0x002B | Settings Parameter Select |
| 408 | 57 | 566 | 92 | 0x002B | Settings Parameter Select |
| 595 | 57 | 753 | 92 | 0x002B | Settings Parameter Select |
| 41 | 101 | 199 | 136 | 0x002B | Settings Parameter Select |
| 226 | 103 | 384 | 138 | 0x002B | Settings Parameter Select |
| 408 | 103 | 566 | 138 | 0x002B | Settings Parameter Select |
| 39 | 193 | 197 | 228 | 0x002B | Settings Parameter Select |
| 595 | 150 | 753 | 185 | 0x002B | Settings Parameter Select |

### Page 12: PV + Battery + Grid + Energy

**Register Data Variables** (SP=0x5A10, actual Modbus registers):

| Reg | X | Y | Digits | DP | Unit | Name |
|-----|---|---|--------|----|------|------|
| 0 | 334 | 54 | 3 | 1 | V | `device_status` |
| 2 | 634 | 54 | 4 | 1 | kW | `pv2_voltage` |
| 1 | 334 | 121 | 3 | 1 | V | `pv1_voltage` |
| 3 | 634 | 121 | 4 | 1 | kW | `pv3_voltage` |
| 15 | 337 | 190 | 3 | 1 | V | `grid_frequency` |
| 33 | 632 | 190 | 4 | 1 | kW | `charge_energy_today` |
| 6 | 334 | 255 | 5 | 1 | kWh | `total_pv_power` |
| 7 | 634 | 255 | 9 | 1 | kWh | `pv1_power` |
| 9 | 334 | 321 | 5 | 1 | kWh | `pv3_power` |
| 10 | 634 | 321 | 9 | 1 | kWh | `charge_power` |
| 78 | 333 | 392 | 5 | 1 | kWh | `bms_feature_flags` |
| 47 | 634 | 392 | 9 | 1 | kWh | `inverter_energy_total_hi` |

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 13 | 119 | 150 | 174 | 0x000D | Grid AC |
| 13 | 180 | 149 | 235 | 0x000E | EPS / Backup |
| 13 | 242 | 152 | 297 | 0x000F | Battery |
| 11 | 305 | 152 | 360 | 0x0010 | Battery Detail |
| 16 | 400 | 96 | 480 | 0x0008 | Home / Main Status |
| 267 | 400 | 347 | 480 | 0x0030 | Menu |
| 392 | 400 | 472 | 480 | 0x0014 | System Settings |

### Page 13: Battery + Grid + EPS/Backup + Energy

**Register Data Variables** (SP=0x5A10, actual Modbus registers):

| Reg | X | Y | Digits | DP | Unit | Name |
|-----|---|---|--------|----|------|------|
| 19 | 334 | 54 | 3 | 1 | V | `device_type_code` |
| 34 | 634 | 54 | 4 | 1 | A | `discharge_energy_today` |
| 23 | 334 | 87 | 5 | 0 | W | `eps_frequency` |
| 22 | 634 | 87 | 5 | 0 | W | `eps_voltage_t` |
| 17 | 334 | 121 | 3 | 1 | V | `rectifier_power` |
| 20 | 634 | 121 | 5 | 0 |  | `eps_voltage_r` |
| 18 | 334 | 155 | 3 | 0 | % | `inverter_rms_current_r` |
| 18 | 406 | 155 | 3 | 0 | % | `inverter_rms_current_r` |
| 46 | 634 | 155 | 5 | 0 |  | `inverter_energy_total_lo` |
| 38 | 334 | 188 | 3 | 1 | V | `bus_voltage_1` |
| 39 | 410 | 188 | 3 | 1 | V | `bus_voltage_2` |
| 146 | 634 | 188 | 5 | 0 | Ah | `battery_remaining_ah` |
| 36 | 334 | 222 | 4 | 1 | A | `grid_export_energy_today` |
| 37 | 634 | 222 | 4 | 1 | A | `grid_import_energy_today` |
| 42 | 334 | 256 | 1 | 3 | V | `pv3_energy_today` |
| 43 | 634 | 256 | 1 | 3 | V | `voltage_reg_43` |
| 44 | 335 | 292 | 3 | 1 |  | `pv1_current` |
| 45 | 635 | 292 | 3 | 1 |  | `pv2_current` |
| 40 | 334 | 320 | 5 | 0 |  | `pv1_energy_today` |
| 41 | 634 | 320 | 5 | 0 |  | `pv2_energy_today` |
| 30 | 334 | 355 | 5 | 1 | kWh | `inverter_energy_today` |
| 27 | 634 | 355 | 5 | 1 | kWh | `power_to_user` |
| 31 | 334 | 389 | 9 | 1 | kWh | `inverter_energy_today_alt` |
| 28 | 634 | 389 | 9 | 1 | kWh | `energy_lifetime_reg_28` |

**Variable Icons** (SP=0x5A11): 2 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 12 | 59 | 149 | 114 | 0x000C | PV Solar |
| 16 | 400 | 96 | 480 | 0x0008 | Home / Main Status |
| 267 | 400 | 347 | 480 | 0x0030 | Menu |
| 392 | 400 | 472 | 480 | 0x0014 | System Settings |
| 13 | 180 | 149 | 235 | 0x000E | EPS / Backup |
| 13 | 242 | 152 | 297 | 0x000F | Battery |
| 11 | 305 | 152 | 360 | 0x0010 | Battery Detail |

### Page 14: EPS/Backup + Energy + Temperature

**Register Data Variables** (SP=0x5A10, actual Modbus registers):

| Reg | X | Y | Digits | DP | Unit | Name |
|-----|---|---|--------|----|------|------|
| 50 | 334 | 57 | 4 | 1 | V | `charge_energy_total_lo` |
| 51 | 634 | 57 | 4 | 2 | Hz | `charge_energy_total_hi` |
| 54 | 334 | 90 | 4 | 1 | V | `grid_l1_voltage_ext` |
| 55 | 634 | 90 | 4 | 1 | V | `grid_l2_voltage_ext` |
| 84 | 334 | 123 | 4 | 1 | V | `eps_l1_voltage` |
| 85 | 634 | 123 | 4 | 2 | Hz | `eps_l1_frequency` |
| 56 | 334 | 157 | 5 | 0 | W | `grid_export_energy_total_lo` |
| 57 | 634 | 157 | 5 | 0 | W | `grid_export_energy_total_hi` |
| 67 | 334 | 189 | 5 | 0 | W | `battery_temperature` |
| 68 | 634 | 190 | 5 | 0 | W | `eps_power_l2` |
| 114 | 334 | 223 | 5 | 0 | W | `dongle_comm_status` |
| 86 | 634 | 223 | 4 | 1 | kW | `eps_power_combined` |
| 61 | 334 | 257 | 5 | 1 | kWh | `pv1_energy_total_lo` |
| 64 | 634 | 257 | 5 | 1 | kWh | `internal_temperature` |
| 62 | 334 | 291 | 9 | 1 | kWh | `pv1_energy_total_hi` |
| 65 | 634 | 291 | 9 | 1 | kWh | `radiator_temperature_1` |
| 71 | 334 | 323 | 5 | 1 | kWh | `pv2_energy_total_lo` |
| 74 | 634 | 323 | 5 | 1 | kWh | `pv3_energy_total_lo` |
| 72 | 334 | 357 | 9 | 1 | kWh | `pv2_energy_total_hi` |
| 75 | 634 | 357 | 9 | 1 | kWh | `pv3_energy_total_hi` |
| 81 | 334 | 391 | 5 | 1 | kWh | `bms_charge_current_limit` |
| 82 | 634 | 391 | 9 | 1 | kWh | `bms_discharge_current_limit` |

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 16 | 400 | 96 | 480 | 0x0008 | Home / Main Status |
| 267 | 400 | 347 | 480 | 0x0030 | Menu |
| 392 | 400 | 472 | 480 | 0x0014 | System Settings |
| 12 | 59 | 149 | 114 | 0x000C | PV Solar |
| 13 | 242 | 152 | 297 | 0x000F | Battery |
| 11 | 305 | 152 | 360 | 0x0010 | Battery Detail |
| 13 | 119 | 150 | 174 | 0x000D | Grid AC |

### Page 15: Battery + Load/Consumption + Energy

**Register Data Variables** (SP=0x5A10, actual Modbus registers):

| Reg | X | Y | Digits | DP | Unit | Name |
|-----|---|---|--------|----|------|------|
| 91 | 334 | 57 | 4 | 1 | V | `battery_current` |
| 94 | 634 | 57 | 4 | 2 | Hz | `grid_frequency_alt` |
| 92 | 334 | 89 | 4 | 1 | V | `grid_voltage_l1` |
| 93 | 634 | 89 | 4 | 1 | V | `grid_voltage_l2` |
| 115 | 334 | 121 | 5 | 0 | W | `serial_reg0` |
| 100 | 634 | 121 | 5 | 0 | VA | `apparent_power` |
| 98 | 334 | 154 | 5 | 0 | W | `consumption_power` |
| 101 | 634 | 154 | 5 | 0 | VA | `apparent_power_l2` |
| 99 | 334 | 188 | 5 | 0 | W | `consumption_power_l2` |
| 102 | 634 | 188 | 5 | 0 | VA | `apparent_power_total` |
| 103 | 334 | 221 | 5 | 1 | kWh | `consumption_energy_today` |
| 104 | 634 | 221 | 9 | 1 | kWh | `consumption_energy_total_lo` |
| 106 | 334 | 255 | 5 | 1 | kWh | `ac_charge_energy_today` |
| 107 | 634 | 255 | 9 | 1 | kWh | `ac_charge_energy_total_lo` |
| 109 | 334 | 288 | 5 | 1 | kWh | `eps_energy_today` |
| 110 | 634 | 288 | 9 | 1 | kWh | `eps_energy_total_lo` |

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 13 | 180 | 153 | 235 | 0x000E | EPS / Backup |
| 16 | 400 | 96 | 480 | 0x0008 | Home / Main Status |
| 267 | 400 | 347 | 480 | 0x0030 | Menu |
| 392 | 400 | 472 | 480 | 0x0014 | System Settings |
| 12 | 59 | 149 | 114 | 0x000C | PV Solar |
| 11 | 305 | 152 | 360 | 0x0010 | Battery Detail |
| 13 | 119 | 150 | 174 | 0x000D | Grid AC |

### Page 16: Battery Detail

**Register Data Variables** (SP=0x5A10, actual Modbus registers):

| Reg | X | Y | Digits | DP | Unit | Name |
|-----|---|---|--------|----|------|------|
| 112 | 364 | 57 | 3 | 0 |  | `pv1_energy_today_2` |
| 112 | 660 | 57 | 3 | 0 |  | `pv1_energy_today_2` |
| 113 | 660 | 89 | 3 | 0 |  | `pv2_energy_today_2` |
| 113 | 364 | 90 | 3 | 0 |  | `pv2_energy_today_2` |
| 120 | 364 | 156 | 3 | 1 | V | `dongle_firmware_version` |
| 121 | 436 | 156 | 3 | 1 | V | `grid_voltage_r_ext2` |
| 122 | 660 | 156 | 3 | 1 | V | `grid_voltage_s_ext2` |
| 123 | 730 | 156 | 3 | 1 | V | `grid_voltage_t_ext2` |
| 124 | 364 | 191 | 3 | 1 |  | `grid_current_l1` |
| 125 | 436 | 191 | 3 | 1 |  | `grid_current_l2` |
| 126 | 660 | 191 | 3 | 1 |  | `grid_current_l3` |
| 127 | 730 | 191 | 3 | 1 |  | `eps_l1_voltage_split` |
| 128 | 364 | 225 | 5 | 0 |  | `eps_l2_voltage_split` |
| 129 | 436 | 225 | 5 | 0 |  | `eps_power_l1` |
| 132 | 660 | 225 | 5 | 0 |  | `inverter_power_l1` |
| 133 | 730 | 225 | 5 | 0 |  | `inverter_power_l2` |
| 130 | 364 | 257 | 5 | 0 |  | `grid_power_import` |
| 130 | 436 | 257 | 5 | 0 |  | `grid_power_import` |
| 131 | 660 | 257 | 5 | 0 |  | `grid_power_export` |
| 131 | 730 | 257 | 5 | 0 |  | `grid_power_export` |
| 137 | 364 | 293 | 5 | 0 |  | `grid_power_total` |
| 137 | 435 | 293 | 5 | 0 |  | `grid_power_total` |
| 135 | 660 | 293 | 3 | 0 | A | `battery_charge_a` |
| 135 | 730 | 293 | 3 | 0 | A | `battery_charge_a` |
| 134 | 660 | 324 | 3 | 0 | A | `battery_discharge_a` |
| 136 | 364 | 325 | 5 | 0 |  | `total_consumption_w` |
| 136 | 435 | 325 | 5 | 0 |  | `total_consumption_w` |
| 134 | 730 | 325 | 3 | 0 | A | `battery_discharge_a` |
| 169 | 381 | 357 | 1 | 0 |  | `unknown_reg_169` |
| 169 | 398 | 357 | 1 | 0 |  | `unknown_reg_169` |

**Variable Icons** (SP=0x5A11): 13 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 13 | 244 | 149 | 299 | 0x000F | Battery |
| 16 | 400 | 96 | 480 | 0x0008 | Home / Main Status |
| 267 | 400 | 347 | 480 | 0x0030 | Menu |
| 392 | 400 | 472 | 480 | 0x0014 | System Settings |
| 13 | 180 | 153 | 235 | 0x000E | EPS / Backup |
| 12 | 59 | 149 | 114 | 0x000C | PV Solar |
| 13 | 119 | 150 | 174 | 0x000D | Grid AC |

### Page 17: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 20 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 1 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 13 | 238 | 154 | 293 | 0x0012 | Settings Menu 2 |
| 722 | 312 | 800 | 464 | 0x0027 | Scroll Down (data) |
| 12 | 114 | 151 | 169 | 0x0031 | Data / Energy |
| 12 | 53 | 151 | 108 | 0x0030 | Menu |
| 147 | 415 | 212 | 480 | 0x000C | PV Solar |
| 22 | 415 | 87 | 480 | 0x0008 | Home / Main Status |
| 401 | 414 | 466 | 479 | 0x0014 | System Settings |

### Page 18: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 20 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 1 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 10 | 179 | 154 | 234 | 0x0011 | Settings Menu 1 |
| 720 | 324 | 800 | 456 | 0x0028 | Scroll Up (data) |
| 13 | 117 | 151 | 172 | 0x0031 | Data / Energy |
| 12 | 54 | 151 | 109 | 0x0030 | Menu |
| 147 | 415 | 212 | 480 | 0x000C | PV Solar |
| 22 | 415 | 87 | 480 | 0x0008 | Home / Main Status |
| 400 | 415 | 465 | 480 | 0x0014 | System Settings |

### Page 19: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 4 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 545 | 96 | 718 | 133 | 0xFF00 | Return / Back (with data) |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 733 | 334 | 799 | 448 | 0x002B | Settings Parameter Select |
| 254 | 40 | 483 | 86 | 0xFF00 | Return / Back (with data) |
| 310 | 140 | 428 | 180 | 0xFF00 | Return / Back (with data) |
| 543 | 36 | 720 | 91 | 0xFF00 | Return / Back (with data) |
| 539 | 138 | 718 | 181 | 0xFF00 | Return / Back (with data) |
| 335 | 189 | 375 | 229 | 0xFF00 | Return / Back (with data) |
| 549 | 282 | 589 | 322 | 0xFF00 | Return / Back (with data) |
| 724 | 281 | 769 | 323 | 0xFF00 | Return / Back (with data) |
| 549 | 237 | 589 | 277 | 0xFF00 | Return / Back (with data) |
| 731 | 39 | 800 | 106 | 0x001B | Alarm / Error |
| 334 | 237 | 374 | 277 | 0xFF00 | Return / Back (with data) |
| 333 | 383 | 373 | 423 | 0xFF00 | Return / Back (with data) |
| 549 | 384 | 589 | 424 | 0xFF00 | Return / Back (with data) |
| 631 | 190 | 671 | 230 | 0xFF00 | Return / Back (with data) |
| 316 | 93 | 426 | 134 | 0xFF00 | Return / Back (with data) |
| 644 | 377 | 710 | 427 | 0x001B | Alarm / Error |
| 727 | 236 | 767 | 276 | 0xFF00 | Return / Back (with data) |
| 335 | 332 | 375 | 372 | 0x0037 | VP 0x0037 |
| 641 | 319 | 710 | 371 | 0x0037 | VP 0x0037 |
| 335 | 285 | 375 | 325 | 0x0037 | VP 0x0037 |
| 549 | 329 | 589 | 369 | 0x0037 | VP 0x0037 |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 737 | 174 | 800 | 226 | 0x001B | Alarm / Error |

### Page 20: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 10 | 239 | 153 | 294 | 0x002E | VP 0x002E |
| 9 | 116 | 152 | 171 | 0x0015 | Date/Time Settings |
| 9 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 8 | 360 | 152 | 415 | 0x0018 | Discharge Schedule |
| 643 | 51 | 741 | 107 | 0x001F | Generator Config |
| 266 | 53 | 321 | 108 | 0xFF00 | Return / Back (with data) |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 412 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |

### Page 21: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 10 | 54 | 154 | 109 | 0x0014 | System Settings |
| 729 | 160 | 800 | 215 | 0x001D | VP 0x001D |
| 252 | 267 | 297 | 301 | 0xFF00 | Return / Back (with data) |
| 302 | 266 | 347 | 300 | 0xFF00 | Return / Back (with data) |
| 354 | 267 | 399 | 301 | 0xFF00 | Return / Back (with data) |
| 404 | 266 | 449 | 300 | 0xFF00 | Return / Back (with data) |
| 253 | 310 | 298 | 344 | 0xFF00 | Return / Back (with data) |
| 300 | 311 | 345 | 345 | 0xFF00 | Return / Back (with data) |
| 354 | 311 | 399 | 345 | 0xFF00 | Return / Back (with data) |
| 404 | 310 | 449 | 344 | 0xFF00 | Return / Back (with data) |
| 251 | 359 | 296 | 393 | 0xFF00 | Return / Back (with data) |
| 301 | 359 | 346 | 393 | 0xFF00 | Return / Back (with data) |
| 354 | 359 | 399 | 393 | 0xFF00 | Return / Back (with data) |
| 403 | 359 | 448 | 393 | 0xFF00 | Return / Back (with data) |
| 674 | 308 | 758 | 343 | 0xFF00 | Return / Back (with data) |
| 762 | 340 | 798 | 451 | 0x001A | VP 0x001A |
| 708 | 40 | 800 | 110 | 0x001D | VP 0x001D |
| 311 | 181 | 338 | 210 | 0xFF00 | Return / Back (with data) |
| 677 | 353 | 756 | 387 | 0xFF00 | Return / Back (with data) |
| 476 | 51 | 531 | 106 | 0xFF00 | Return / Back (with data) |
| 639 | 51 | 694 | 106 | 0xFF00 | Return / Back (with data) |
| 420 | 112 | 511 | 151 | 0xFF00 | Return / Back (with data) |
| 378 | 207 | 462 | 252 | 0xFF00 | Return / Back (with data) |
| 10 | 239 | 153 | 294 | 0x002E | VP 0x002E |
| 9 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 8 | 360 | 152 | 415 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 412 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 674 | 220 | 758 | 255 | 0xFF00 | Return / Back (with data) |
| 677 | 263 | 756 | 297 | 0xFF00 | Return / Back (with data) |
| 685 | 175 | 720 | 208 | 0xFF00 | Return / Back (with data) |

### Page 22: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 10 | 116 | 153 | 171 | 0x0015 | Date/Time Settings |
| 442 | 233 | 509 | 284 | 0x001E | Grid Config |
| 240 | 288 | 280 | 319 | 0xFF00 | Return / Back (with data) |
| 291 | 291 | 335 | 320 | 0xFF00 | Return / Back (with data) |
| 347 | 291 | 388 | 319 | 0xFF00 | Return / Back (with data) |
| 395 | 291 | 438 | 321 | 0xFF00 | Return / Back (with data) |
| 241 | 326 | 282 | 356 | 0xFF00 | Return / Back (with data) |
| 291 | 329 | 337 | 360 | 0xFF00 | Return / Back (with data) |
| 347 | 329 | 385 | 360 | 0xFF00 | Return / Back (with data) |
| 394 | 330 | 439 | 361 | 0xFF00 | Return / Back (with data) |
| 237 | 370 | 283 | 401 | 0xFF00 | Return / Back (with data) |
| 347 | 371 | 386 | 401 | 0xFF00 | Return / Back (with data) |
| 395 | 371 | 438 | 401 | 0xFF00 | Return / Back (with data) |
| 674 | 327 | 754 | 359 | 0xFF00 | Return / Back (with data) |
| 358 | 142 | 430 | 177 | 0xFF00 | Return / Back (with data) |
| 711 | 147 | 800 | 181 | 0xFF00 | Return / Back (with data) |
| 353 | 239 | 398 | 279 | 0xFF00 | Return / Back (with data) |
| 711 | 43 | 776 | 93 | 0x001E | Grid Config |
| 675 | 285 | 755 | 321 | 0xFF00 | Return / Back (with data) |
| 674 | 366 | 753 | 403 | 0xFF00 | Return / Back (with data) |
| 492 | 52 | 537 | 97 | 0xFF00 | Return / Back (with data) |
| 653 | 52 | 698 | 97 | 0xFF00 | Return / Back (with data) |
| 294 | 371 | 335 | 402 | 0xFF00 | Return / Back (with data) |
| 411 | 98 | 482 | 136 | 0xFF00 | Return / Back (with data) |
| 359 | 184 | 435 | 219 | 0xFF00 | Return / Back (with data) |
| 713 | 101 | 800 | 137 | 0xFF00 | Return / Back (with data) |
| 712 | 189 | 800 | 228 | 0xFF00 | Return / Back (with data) |
| 760 | 341 | 799 | 437 | 0x0034 | VP 0x0034 |
| 10 | 54 | 154 | 109 | 0x0014 | System Settings |
| 10 | 239 | 153 | 294 | 0x002E | VP 0x002E |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 8 | 360 | 152 | 415 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 412 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |

### Page 23: Navigation / Status

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 168 | 68 | 643 | 143 | 0x0023 | VP 0x0023 |
| 168 | 159 | 643 | 234 | 0x0024 | VP 0x0024 |
| 168 | 258 | 643 | 333 | 0x0025 | VP 0x0025 |
| 168 | 340 | 643 | 415 | 0x0026 | VP 0x0026 |
| 10 | 116 | 153 | 171 | 0x0015 | Date/Time Settings |
| 10 | 54 | 154 | 109 | 0x0014 | System Settings |
| 10 | 239 | 153 | 294 | 0x002E | VP 0x002E |
| 8 | 360 | 152 | 415 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 428 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 9 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |

### Page 24: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 7 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 10 | 244 | 152 | 285 | 0x002E | VP 0x002E |
| 10 | 61 | 152 | 100 | 0x0014 | System Settings |
| 9 | 122 | 152 | 162 | 0x0015 | Date/Time Settings |
| 9 | 186 | 155 | 227 | 0x0016 | Charge Schedule 1 |
| 11 | 309 | 153 | 349 | 0x0017 | Charge Schedule 2 |
| 340 | 114 | 524 | 141 | 0xFF00 | Return / Back (with data) |
| 536 | 111 | 587 | 142 | 0x0020 | Data Screen (next) |
| 262 | 68 | 325 | 100 | 0xFF00 | Return / Back (with data) |
| 331 | 69 | 372 | 99 | 0xFF00 | Return / Back (with data) |
| 379 | 69 | 418 | 98 | 0xFF00 | Return / Back (with data) |
| 425 | 69 | 466 | 98 | 0xFF00 | Return / Back (with data) |
| 472 | 67 | 513 | 99 | 0xFF00 | Return / Back (with data) |
| 519 | 68 | 559 | 99 | 0xFF00 | Return / Back (with data) |
| 570 | 69 | 615 | 100 | 0x0020 | Data Screen (next) |
| 153 | 425 | 208 | 480 | 0x000C | PV Solar |
| 278 | 425 | 333 | 480 | 0x0030 | Menu |
| 27 | 425 | 82 | 480 | 0x0008 | Home / Main Status |

### Page 25:

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 233 | 121 | 297 | 186 | 0xFF00 | Return / Back (with data) |
| 374 | 120 | 437 | 187 | 0xFF00 | Return / Back (with data) |
| 235 | 195 | 298 | 261 | 0xFF00 | Return / Back (with data) |
| 374 | 195 | 436 | 261 | 0xFF00 | Return / Back (with data) |
| 236 | 268 | 299 | 335 | 0xFF00 | Return / Back (with data) |
| 374 | 269 | 436 | 335 | 0xFF00 | Return / Back (with data) |
| 235 | 341 | 298 | 409 | 0xFF00 | Return / Back (with data) |
| 373 | 342 | 436 | 409 | 0xFF00 | Return / Back (with data) |

### Page 26: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 246 | 92 | 289 | 125 | 0xFF00 | Return / Back (with data) |
| 299 | 93 | 342 | 126 | 0xFF00 | Return / Back (with data) |
| 345 | 93 | 388 | 126 | 0xFF00 | Return / Back (with data) |
| 396 | 93 | 439 | 126 | 0xFF00 | Return / Back (with data) |
| 245 | 138 | 288 | 171 | 0xFF00 | Return / Back (with data) |
| 298 | 136 | 341 | 169 | 0xFF00 | Return / Back (with data) |
| 345 | 136 | 388 | 169 | 0xFF00 | Return / Back (with data) |
| 394 | 136 | 437 | 169 | 0xFF00 | Return / Back (with data) |
| 248 | 180 | 291 | 213 | 0xFF00 | Return / Back (with data) |
| 299 | 180 | 342 | 213 | 0xFF00 | Return / Back (with data) |
| 349 | 180 | 392 | 213 | 0xFF00 | Return / Back (with data) |
| 397 | 180 | 440 | 213 | 0xFF00 | Return / Back (with data) |
| 685 | 139 | 760 | 173 | 0xFF00 | Return / Back (with data) |
| 765 | 273 | 799 | 343 | 0x0015 | Date/Time Settings |
| 331 | 47 | 371 | 87 | 0xFF00 | Return / Back (with data) |
| 704 | 241 | 760 | 297 | 0x0021 | VP 0x0021 |
| 753 | 350 | 799 | 428 | 0x0032 | VP 0x0032 |
| 686 | 96 | 761 | 129 | 0xFF00 | Return / Back (with data) |
| 687 | 180 | 758 | 216 | 0xFF00 | Return / Back (with data) |
| 364 | 256 | 440 | 297 | 0xFF00 | Return / Back (with data) |
| 364 | 303 | 441 | 340 | 0xFF00 | Return / Back (with data) |
| 610 | 251 | 691 | 303 | 0xFF00 | Return / Back (with data) |
| 153 | 425 | 208 | 480 | 0x000C | PV Solar |
| 278 | 425 | 333 | 480 | 0x0030 | Menu |
| 27 | 425 | 82 | 480 | 0x0008 | Home / Main Status |
| 10 | 54 | 154 | 109 | 0x0014 | System Settings |
| 10 | 239 | 153 | 294 | 0x002E | VP 0x002E |
| 9 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 8 | 360 | 152 | 415 | 0x0018 | Discharge Schedule |

### Page 27: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 675 | 0 | 800 | 125 | 0x0013 | Firmware Update |

### Page 28: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 681 | 1 | 806 | 126 | 0x0014 | System Settings |

### Page 29: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 675 | 0 | 800 | 125 | 0x0015 | Date/Time Settings |

### Page 30: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 675 | 0 | 800 | 125 | 0x0016 | Charge Schedule 1 |

### Page 31: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 666 | 119 | 800 | 191 | 0xFF00 | Return / Back (with data) |
| 667 | 0 | 800 | 98 | 0x0014 | System Settings |

### Page 32: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 7 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 675 | 0 | 800 | 125 | 0x0018 | Discharge Schedule |

### Page 33: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 675 | 0 | 800 | 125 | 0x001A | VP 0x001A |

### Page 35: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 38 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 168 | 82 | 800 | 172 | 0x0017 | Charge Schedule 2 |

### Page 36: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 31 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 163 | 169 | 800 | 267 | 0x0017 | Charge Schedule 2 |

### Page 37: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 23 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 163 | 264 | 800 | 349 | 0x0017 | Charge Schedule 2 |

### Page 38: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 12 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 161 | 344 | 800 | 428 | 0x0017 | Charge Schedule 2 |

### Page 39: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 20 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 1 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 711 | 310 | 800 | 459 | 0x0011 | Settings Menu 1 |
| 13 | 238 | 154 | 293 | 0x0012 | Settings Menu 2 |
| 12 | 114 | 151 | 169 | 0x0031 | Data / Energy |
| 12 | 53 | 151 | 108 | 0x0030 | Menu |
| 147 | 415 | 212 | 480 | 0x000C | PV Solar |
| 22 | 415 | 87 | 480 | 0x0008 | Home / Main Status |
| 401 | 414 | 466 | 479 | 0x0014 | System Settings |

### Page 40: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 20 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 1 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 713 | 306 | 800 | 460 | 0x0012 | Settings Menu 2 |
| 10 | 179 | 154 | 234 | 0x0011 | Settings Menu 1 |
| 13 | 117 | 151 | 172 | 0x0031 | Data / Energy |
| 12 | 54 | 151 | 109 | 0x0030 | Menu |
| 147 | 415 | 212 | 480 | 0x000C | PV Solar |
| 22 | 415 | 87 | 480 | 0x0008 | Home / Main Status |
| 399 | 414 | 464 | 479 | 0x0014 | System Settings |

### Page 41:

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 0 | 0 | 135 | 135 | 0xFF00 | Return / Back (with data) |
| 0 | 175 | 135 | 310 | 0xFF00 | Return / Back (with data) |
| 0 | 345 | 135 | 480 | 0xFF00 | Return / Back (with data) |
| 336 | 0 | 471 | 135 | 0xFF00 | Return / Back (with data) |
| 665 | 0 | 800 | 135 | 0xFF00 | Return / Back (with data) |
| 335 | 177 | 470 | 312 | 0xFF00 | Return / Back (with data) |
| 330 | 345 | 465 | 480 | 0xFF00 | Return / Back (with data) |
| 665 | 179 | 800 | 314 | 0xFF00 | Return / Back (with data) |
| 665 | 345 | 800 | 480 | 0xFF00 | Return / Back (with data) |

### Page 43: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 5 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 764 | 312 | 800 | 362 | 0x0013 | Firmware Update |
| 763 | 376 | 799 | 426 | 0x0038 | VP 0x0038 |
| 292 | 370 | 483 | 414 | 0x0009 | VP 0x0009 |
| 319 | 100 | 499 | 139 | 0x000A | VP 0x000A |
| 196 | 149 | 278 | 179 | 0xFF00 | Return / Back (with data) |
| 289 | 149 | 371 | 179 | 0xFF00 | Return / Back (with data) |
| 409 | 149 | 491 | 179 | 0xFF00 | Return / Back (with data) |
| 503 | 149 | 585 | 179 | 0xFF00 | Return / Back (with data) |
| 623 | 149 | 705 | 179 | 0xFF00 | Return / Back (with data) |
| 716 | 149 | 798 | 179 | 0xFF00 | Return / Back (with data) |
| 196 | 189 | 278 | 219 | 0xFF00 | Return / Back (with data) |
| 289 | 189 | 371 | 219 | 0xFF00 | Return / Back (with data) |
| 407 | 189 | 489 | 219 | 0xFF00 | Return / Back (with data) |
| 503 | 189 | 585 | 219 | 0xFF00 | Return / Back (with data) |
| 625 | 189 | 707 | 219 | 0xFF00 | Return / Back (with data) |
| 716 | 189 | 798 | 219 | 0xFF00 | Return / Back (with data) |
| 196 | 227 | 278 | 257 | 0xFF00 | Return / Back (with data) |
| 289 | 227 | 371 | 257 | 0xFF00 | Return / Back (with data) |
| 407 | 227 | 489 | 257 | 0xFF00 | Return / Back (with data) |
| 503 | 227 | 585 | 257 | 0xFF00 | Return / Back (with data) |
| 625 | 227 | 707 | 257 | 0xFF00 | Return / Back (with data) |
| 716 | 227 | 798 | 257 | 0xFF00 | Return / Back (with data) |
| 193 | 269 | 275 | 299 | 0xFF00 | Return / Back (with data) |
| 289 | 269 | 371 | 299 | 0xFF00 | Return / Back (with data) |
| 407 | 269 | 489 | 299 | 0xFF00 | Return / Back (with data) |
| 503 | 269 | 585 | 299 | 0xFF00 | Return / Back (with data) |
| 625 | 269 | 707 | 299 | 0xFF00 | Return / Back (with data) |
| 716 | 269 | 798 | 299 | 0xFF00 | Return / Back (with data) |
| 664 | 377 | 748 | 419 | 0xFF00 | Return / Back (with data) |
| 679 | 97 | 772 | 139 | 0xFF00 | Return / Back (with data) |
| 737 | 42 | 797 | 91 | 0x002C | VP 0x002C |
| 660 | 315 | 723 | 371 | 0x002C | VP 0x002C |
| 645 | 47 | 731 | 91 | 0xFF00 | Return / Back (with data) |
| 314 | 47 | 499 | 95 | 0xFF00 | Return / Back (with data) |
| 295 | 323 | 484 | 366 | 0xFF00 | Return / Back (with data) |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |

### Page 44: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 6 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 665 | 0 | 800 | 135 | 0x002B | Settings Parameter Select |

### Page 45: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 5 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 328 | 57 | 496 | 90 | 0x002F | Logo / Splash |
| 330 | 101 | 498 | 134 | 0x002F | Logo / Splash |
| 206 | 148 | 263 | 181 | 0x002F | Logo / Splash |
| 741 | 52 | 787 | 88 | 0x002F | Logo / Splash |
| 307 | 329 | 480 | 362 | 0x002F | Logo / Splash |
| 301 | 379 | 481 | 412 | 0x002F | Logo / Splash |
| 671 | 380 | 746 | 413 | 0x002F | Logo / Splash |
| 666 | 327 | 713 | 360 | 0x002F | Logo / Splash |
| 295 | 147 | 352 | 180 | 0x002F | Logo / Splash |
| 206 | 189 | 263 | 222 | 0x002F | Logo / Splash |
| 295 | 188 | 352 | 221 | 0x002F | Logo / Splash |
| 207 | 230 | 264 | 263 | 0x002F | Logo / Splash |
| 296 | 229 | 353 | 262 | 0x002F | Logo / Splash |
| 207 | 271 | 264 | 304 | 0x002F | Logo / Splash |
| 296 | 270 | 353 | 303 | 0x002F | Logo / Splash |
| 421 | 145 | 478 | 178 | 0x002F | Logo / Splash |
| 510 | 144 | 567 | 177 | 0x002F | Logo / Splash |
| 421 | 186 | 478 | 219 | 0x002F | Logo / Splash |
| 510 | 185 | 567 | 218 | 0x002F | Logo / Splash |
| 422 | 227 | 479 | 260 | 0x002F | Logo / Splash |
| 511 | 226 | 568 | 259 | 0x002F | Logo / Splash |
| 422 | 268 | 479 | 301 | 0x002F | Logo / Splash |
| 511 | 267 | 568 | 300 | 0x002F | Logo / Splash |
| 637 | 149 | 694 | 182 | 0x002F | Logo / Splash |
| 726 | 148 | 783 | 181 | 0x002F | Logo / Splash |
| 637 | 190 | 694 | 223 | 0x002F | Logo / Splash |
| 726 | 189 | 783 | 222 | 0x002F | Logo / Splash |
| 638 | 231 | 695 | 264 | 0x002F | Logo / Splash |
| 727 | 230 | 784 | 263 | 0x002F | Logo / Splash |
| 638 | 272 | 695 | 305 | 0x002F | Logo / Splash |
| 727 | 271 | 784 | 304 | 0x002F | Logo / Splash |
| 683 | 103 | 760 | 136 | 0x002F | Logo / Splash |
| 649 | 54 | 727 | 87 | 0x002F | Logo / Splash |
| 763 | 312 | 799 | 362 | 0x002E | VP 0x002E |
| 763 | 376 | 799 | 426 | 0x0039 | VP 0x0039 |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |

### Page 46: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 4 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 552 | 100 | 713 | 131 | 0x002F | Logo / Splash |
| 749 | 56 | 793 | 95 | 0x002F | Logo / Splash |
| 599 | 54 | 712 | 85 | 0x002F | Logo / Splash |
| 556 | 143 | 712 | 174 | 0x002F | Logo / Splash |
| 765 | 356 | 800 | 417 | 0x002D | VP 0x002D |
| 751 | 190 | 795 | 229 | 0x002F | Logo / Splash |
| 269 | 56 | 466 | 87 | 0x002F | Logo / Splash |
| 341 | 195 | 368 | 224 | 0x002F | Logo / Splash |
| 555 | 286 | 582 | 315 | 0x002F | Logo / Splash |
| 341 | 241 | 368 | 270 | 0x002F | Logo / Splash |
| 341 | 285 | 368 | 314 | 0x002F | Logo / Splash |
| 341 | 388 | 368 | 417 | 0x002F | Logo / Splash |
| 555 | 243 | 582 | 272 | 0x002F | Logo / Splash |
| 555 | 388 | 582 | 417 | 0x002F | Logo / Splash |
| 653 | 381 | 697 | 420 | 0x002F | Logo / Splash |
| 733 | 287 | 760 | 316 | 0x002F | Logo / Splash |
| 732 | 242 | 759 | 271 | 0x002F | Logo / Splash |
| 638 | 195 | 665 | 224 | 0x002F | Logo / Splash |
| 341 | 335 | 368 | 364 | 0x002F | Logo / Splash |
| 654 | 327 | 698 | 366 | 0x002F | Logo / Splash |
| 324 | 101 | 423 | 132 | 0x002F | Logo / Splash |
| 319 | 145 | 419 | 173 | 0x002F | Logo / Splash |
| 555 | 337 | 582 | 366 | 0x002F | Logo / Splash |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |

### Page 47: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 473 | 78 | 576 | 175 | 0x002E | VP 0x002E |
| 486 | 216 | 585 | 309 | 0xFF00 | Return / Back (with data) |
| 224 | 181 | 478 | 245 | 0xFF00 | Return / Back (with data) |

### Page 48: Navigation / Status

**Variable Icons** (SP=0x5A11): 1 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 11 | 176 | 152 | 231 | 0x0011 | Settings Menu 1 |
| 13 | 238 | 154 | 293 | 0x0012 | Settings Menu 2 |
| 12 | 114 | 151 | 169 | 0x0031 | Data / Energy |
| 147 | 415 | 212 | 480 | 0x000C | PV Solar |
| 22 | 415 | 87 | 480 | 0x0008 | Home / Main Status |
| 401 | 415 | 466 | 480 | 0x0014 | System Settings |

### Page 49: Data (regs 185-185)

**Register Data Variables** (SP=0x5A10, actual Modbus registers):

| Reg | X | Y | Digits | DP | Unit | Name |
|-----|---|---|--------|----|------|------|
| 185 | 215 | 10 | 5 | 0 | S | `seconds_reg_185` |

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**Variable Icons** (SP=0x5A11): 1 entries

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 11 | 176 | 152 | 231 | 0x0011 | Settings Menu 1 |
| 13 | 238 | 154 | 293 | 0x0012 | Settings Menu 2 |
| 147 | 415 | 212 | 480 | 0x000C | PV Solar |
| 22 | 415 | 87 | 480 | 0x0008 | Home / Main Status |
| 401 | 415 | 466 | 480 | 0x0014 | System Settings |
| 12 | 54 | 151 | 109 | 0x0030 | Menu |

### Page 50: Navigation / Status

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 718 | 331 | 800 | 457 | 0x001A | VP 0x001A |
| 744 | 67 | 800 | 134 | 0x0033 | VP 0x0033 |
| 373 | 88 | 461 | 131 | 0xFF00 | Return / Back (with data) |
| 374 | 135 | 460 | 172 | 0xFF00 | Return / Back (with data) |
| 374 | 178 | 459 | 217 | 0xFF00 | Return / Back (with data) |
| 670 | 139 | 744 | 170 | 0xFF00 | Return / Back (with data) |
| 672 | 179 | 746 | 215 | 0xFF00 | Return / Back (with data) |
| 672 | 91 | 738 | 127 | 0xFF00 | Return / Back (with data) |
| 726 | 250 | 799 | 314 | 0x0033 | VP 0x0033 |
| 305 | 259 | 386 | 304 | 0xFF00 | Return / Back (with data) |
| 307 | 310 | 385 | 349 | 0xFF00 | Return / Back (with data) |
| 604 | 266 | 688 | 301 | 0xFF00 | Return / Back (with data) |
| 606 | 307 | 690 | 345 | 0xFF00 | Return / Back (with data) |
| 10 | 54 | 154 | 109 | 0x0014 | System Settings |
| 10 | 239 | 153 | 294 | 0x002E | VP 0x002E |
| 9 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 8 | 360 | 152 | 415 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 412 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |

### Page 51: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 665 | 0 | 800 | 135 | 0x0032 | VP 0x0032 |

### Page 52: Navigation / Status

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 10 | 116 | 153 | 171 | 0x0015 | Date/Time Settings |
| 10 | 54 | 154 | 109 | 0x0014 | System Settings |
| 10 | 239 | 153 | 294 | 0x002E | VP 0x002E |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 8 | 360 | 152 | 415 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 412 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 385 | 57 | 426 | 95 | 0xFF00 | Return / Back (with data) |
| 760 | 348 | 798 | 426 | 0x0016 | Charge Schedule 1 |
| 744 | 30 | 800 | 92 | 0x0035 | VP 0x0035 |
| 736 | 252 | 800 | 322 | 0x0035 | VP 0x0035 |
| 275 | 151 | 356 | 188 | 0xFF00 | Return / Back (with data) |
| 250 | 105 | 299 | 139 | 0xFF00 | Return / Back (with data) |
| 307 | 105 | 356 | 139 | 0xFF00 | Return / Back (with data) |
| 362 | 105 | 411 | 139 | 0xFF00 | Return / Back (with data) |
| 418 | 104 | 467 | 138 | 0xFF00 | Return / Back (with data) |
| 568 | 105 | 617 | 139 | 0xFF00 | Return / Back (with data) |
| 628 | 105 | 677 | 139 | 0xFF00 | Return / Back (with data) |
| 683 | 105 | 732 | 139 | 0xFF00 | Return / Back (with data) |
| 741 | 105 | 790 | 139 | 0xFF00 | Return / Back (with data) |
| 504 | 152 | 585 | 189 | 0xFF00 | Return / Back (with data) |
| 714 | 151 | 800 | 188 | 0xFF00 | Return / Back (with data) |
| 687 | 335 | 751 | 363 | 0xFF00 | Return / Back (with data) |
| 690 | 386 | 749 | 418 | 0xFF00 | Return / Back (with data) |
| 381 | 328 | 461 | 371 | 0xFF00 | Return / Back (with data) |
| 381 | 379 | 461 | 422 | 0xFF00 | Return / Back (with data) |
| 655 | 280 | 700 | 325 | 0xFF00 | Return / Back (with data) |
| 382 | 275 | 462 | 318 | 0xFF00 | Return / Back (with data) |
| 504 | 199 | 586 | 240 | 0xFF00 | Return / Back (with data) |
| 714 | 199 | 800 | 237 | 0xFF00 | Return / Back (with data) |
| 274 | 199 | 354 | 237 | 0xFF00 | Return / Back (with data) |

### Page 53: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 1 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 665 | 1 | 800 | 136 | 0x0034 | VP 0x0034 |

### Page 54: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 4 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 544 | 95 | 717 | 132 | 0xFF00 | Return / Back (with data) |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 733 | 334 | 799 | 448 | 0x002B | Settings Parameter Select |
| 254 | 40 | 483 | 86 | 0xFF00 | Return / Back (with data) |
| 310 | 140 | 428 | 180 | 0xFF00 | Return / Back (with data) |
| 543 | 36 | 720 | 91 | 0xFF00 | Return / Back (with data) |
| 539 | 138 | 718 | 181 | 0xFF00 | Return / Back (with data) |
| 335 | 189 | 375 | 229 | 0xFF00 | Return / Back (with data) |
| 549 | 282 | 589 | 322 | 0xFF00 | Return / Back (with data) |
| 724 | 281 | 769 | 323 | 0xFF00 | Return / Back (with data) |
| 549 | 237 | 589 | 277 | 0xFF00 | Return / Back (with data) |
| 731 | 38 | 800 | 105 | 0x001B | Alarm / Error |
| 737 | 174 | 800 | 226 | 0x001B | Alarm / Error |
| 334 | 237 | 374 | 277 | 0xFF00 | Return / Back (with data) |
| 333 | 383 | 373 | 423 | 0xFF00 | Return / Back (with data) |
| 549 | 384 | 589 | 424 | 0xFF00 | Return / Back (with data) |
| 631 | 190 | 671 | 230 | 0xFF00 | Return / Back (with data) |
| 316 | 93 | 426 | 134 | 0xFF00 | Return / Back (with data) |
| 644 | 377 | 710 | 427 | 0x001B | Alarm / Error |
| 727 | 236 | 767 | 276 | 0xFF00 | Return / Back (with data) |
| 335 | 330 | 375 | 370 | 0xFF00 | Return / Back (with data) |
| 643 | 317 | 709 | 367 | 0x001B | Alarm / Error |
| 549 | 331 | 589 | 371 | 0xFF00 | Return / Back (with data) |
| 335 | 282 | 375 | 322 | 0xFF00 | Return / Back (with data) |

### Page 55: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 665 | 0 | 800 | 135 | 0x0036 | VP 0x0036 |

### Page 56: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 720 | 355 | 800 | 480 | 0x002B | Settings Parameter Select |
| 400 | 286 | 469 | 339 | 0x003A | VP 0x003A |
| 746 | 185 | 799 | 246 | 0x003A | VP 0x003A |
| 333 | 288 | 383 | 338 | 0xFF00 | Return / Back (with data) |
| 235 | 181 | 422 | 248 | 0xFF00 | Return / Back (with data) |
| 536 | 183 | 730 | 244 | 0xFF00 | Return / Back (with data) |
| 708 | 280 | 800 | 337 | 0x003B | VP 0x003B |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 338 | 48 | 383 | 93 | 0xFF00 | Return / Back (with data) |
| 338 | 98 | 383 | 143 | 0xFF00 | Return / Back (with data) |
| 740 | 42 | 800 | 102 | 0x003A | VP 0x003A |
| 646 | 44 | 735 | 93 | 0xFF00 | Return / Back (with data) |
| 338 | 362 | 383 | 409 | 0x003D | VP 0x003D |
| 398 | 362 | 466 | 411 | 0x003D | VP 0x003D |

### Page 57: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 754 | 194 | 800 | 236 | 0x002F | Logo / Splash |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 715 | 291 | 800 | 452 | 0x002D | VP 0x002D |
| 408 | 292 | 451 | 331 | 0x002F | Logo / Splash |
| 236 | 198 | 404 | 228 | 0x002F | Logo / Splash |
| 565 | 200 | 733 | 230 | 0x002F | Logo / Splash |
| 346 | 298 | 373 | 327 | 0x002F | Logo / Splash |
| 343 | 354 | 461 | 407 | 0x002F | Logo / Splash |
| 346 | 107 | 373 | 136 | 0x002F | Logo / Splash |
| 346 | 55 | 373 | 84 | 0x002F | Logo / Splash |
| 662 | 56 | 732 | 85 | 0x002F | Logo / Splash |
| 754 | 47 | 800 | 89 | 0x002F | Logo / Splash |

### Page 58: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 3 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 665 | 0 | 800 | 135 | 0x0038 | VP 0x0038 |

### Page 59: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 3 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 697 | 0 | 800 | 98 | 0x0038 | VP 0x0038 |
| 692 | 113 | 800 | 198 | 0x0038 | VP 0x0038 |

### Page 60: Navigation / Status

**Animated/Scrolling Icons** (SP=0x5A00/0x5A01): 2 entries (icon indices, NOT registers)

**DateTime Variables** (SP=0x5A12): 1 entries
  - Format: `Y-M-D H:Q:S `

**Touch Regions:**

| X1 | Y1 | X2 | Y2 | Target VP | Function |
|----|----|----|----|-----------| ---------|
| 720 | 355 | 800 | 480 | 0x002B | Settings Parameter Select |
| 400 | 286 | 469 | 339 | 0x003A | VP 0x003A |
| 746 | 185 | 799 | 246 | 0x003A | VP 0x003A |
| 333 | 288 | 383 | 338 | 0xFF00 | Return / Back (with data) |
| 235 | 181 | 422 | 248 | 0xFF00 | Return / Back (with data) |
| 536 | 183 | 730 | 244 | 0xFF00 | Return / Back (with data) |
| 708 | 280 | 800 | 337 | 0x003B | VP 0x003B |
| 9 | 55 | 155 | 110 | 0x0014 | System Settings |
| 8 | 117 | 154 | 172 | 0x0015 | Date/Time Settings |
| 8 | 177 | 152 | 232 | 0x0016 | Charge Schedule 1 |
| 9 | 300 | 153 | 355 | 0x0017 | Charge Schedule 2 |
| 10 | 362 | 154 | 417 | 0x0018 | Discharge Schedule |
| 16 | 426 | 96 | 480 | 0x0008 | Home / Main Status |
| 272 | 427 | 341 | 480 | 0x0030 | Menu |
| 141 | 428 | 221 | 480 | 0x000C | PV Solar |
| 338 | 48 | 383 | 93 | 0xFF00 | Return / Back (with data) |
| 338 | 98 | 383 | 143 | 0xFF00 | Return / Back (with data) |
| 740 | 42 | 800 | 102 | 0x003A | VP 0x003A |
| 646 | 44 | 735 | 93 | 0xFF00 | Return / Back (with data) |
| 327 | 361 | 383 | 411 | 0xFF00 | Return / Back (with data) |
| 399 | 359 | 468 | 412 | 0x003A | VP 0x003A |

## 8. Key Findings

### 8.1 VP-to-Register Address Mapping

The DWIN display uses a **direct 1:1 mapping** between VP addresses and
Modbus input register addresses. Byte 7 of each ShowFile entry IS the
Modbus register number. This means:

- VP address 0 = Modbus input register 0 (device_status)
- VP address 12 = Modbus input register 12 (grid_voltage_r)
- VP address 91 = Modbus input register 91 (battery_current)

The inverter MCU reads Modbus input registers and writes them directly
to the corresponding DWIN VP addresses over UART.

### 8.2 Scale Factor Confirmation

The LCD display decimal places confirm register scaling:

| Register | LCD DP | LCD Scale | pylxpweb Scale | Status |
|----------|--------|-----------|----------------|--------|
| 1 (`pv1_voltage`) | 1 | /10 | /10 | CONFIRMED |
| 15 (`grid_frequency`) | 2 | /100 | /100 | CONFIRMED |
| 18 (`inverter_rms_current_r`) | 0 | x1 | /100 | DIFFERS |
| 51 (`charge_energy_total_hi`) | 2 | /100 | /10 | DIFFERS |
| 85 (`eps_l1_frequency`) | 2 | /100 | /100 | CONFIRMED |
| 91 (`battery_current`) | 1 | /10 | /10 | CONFIRMED |

**Note**: Some scale factor differences are expected -- the LCD may
display with different precision than the raw register value.
For example, register 18 (inverter_rms_current_r) has /100 scaling in
pylxpweb but displays with 0 decimal places on the LCD (showing amps
as integers on the small screen).

### 8.3 Register Coverage

- **LCD displays 106 unique registers**
- **99 are known** in pylxpweb
- **7 are new/unknown**

### 8.4 New Register Discoveries

Registers displayed on the LCD but not yet mapped in pylxpweb.
Cross-referenced with live Modbus probe data where available.

**Important**: The LCD settings pages (9-10, 16, etc.) display HOLDING
registers for parameter configuration, while data pages (8, 12-15) display
INPUT registers for runtime data. The same register number may refer to
different registers depending on which page it appears on.

| Reg | LCD Format | Pages | Probe Holding Name | Probe Input Name |
|-----|-----------|-------|--------------------|------------------|
| 28 | kWh, 9d 1dp (/10) | 13 | grid_frequency_connection_high (6500 = 65.00 Hz) | pv1_energy_today (observed: 0-36, /10 = 0-3.6 kWh) |
| 43 | V, 1d 3dp (/1000) | 13 | grid_freq_protection_threshold (6500 = 6.500 kV or 65.00 Hz) | - |
| 166 | , 2d 0dp (x1) | 8 | battery_low_to_utility_voltage (0 = disabled) | - |
| 169 | , 1d 0dp (x1) | 16 | ongrid_eod_voltage (400 = 40.0V battery cutoff) | - |
| 176 | kW, 4d 1dp (/10) | 8 | max_grid_input_power (65535 = unlimited) | - |
| 183 | S, 5d 0dp (x1) | 8 | reconnection_timer (10 seconds) | - |
| 185 | S, 5d 0dp (x1) | 49 | grid_reconnect_voltage (2400 = 240.0V) | - |

### 8.5 Screen Layout Architecture

The display has a consistent navigation structure:

- **Bottom navigation bar** (Y=400-480): Home, Menu, Settings buttons
- **Left sidebar** (X=0-155): Sub-page selection tabs
- **Main content area** (X=155-800, Y=0-400): Data display
- **Pages 9-10**: Settings parameter screens with grid layout
- **Pages 56-60**: Battery BMS detail screens (8 entries each)

### 8.6 DWIN Protocol Summary

The inverter communicates with the LCD via UART at 115200 baud using
the DWIN DGUS II protocol:

1. **MCU -> Display**: Write register values to VP addresses
   - Frame: `5A A5 [len] 82 [VP_hi] [VP_lo] [data_hi] [data_lo]`
   - VP address = Modbus register number (direct mapping)

2. **Display -> MCU**: Touch input events
   - Frame: `5A A5 [len] 83 [VP_hi] [VP_lo] [value_hi] [value_lo]`
   - Used for page navigation and parameter input

3. **Page switching**: MCU writes to VP 0x0084 (DWIN page register)
   - `5A A5 04 80 03 00 [page_id]` switches to target page

---

*Generated by `scripts/parse_dwin_lcd_firmware.py`*
