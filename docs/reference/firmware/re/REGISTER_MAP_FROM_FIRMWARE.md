# Firmware Register Map Extraction

**Generated from**: EG4 18kPV ARM Cortex-M4 firmware decompilation
**Firmware file**: `18kpv_FAAB-27xx_20260330_App.bin`
**Live dump devices**: 18kPV (10.100.14.68), FlexBOSS21 (10.100.10.184)

---

## 1. DSP Firmware Register Read Map

Extracted from the DSP firmware's literal pool at offset 0x1A306-0x1A368.
These define the Modbus register blocks the firmware reads from the ARM controller.

### Holding Register Read Blocks

| Block | Start Reg | Count | End Reg | Coverage |
|-------|-----------|-------|---------|----------|
| 1 | 0 | 12 | 11 | regs 0-11 |
| 2 | 6 | 12 | 17 | regs 6-17 |
| 3 | 18 | 12 | 29 | regs 18-29 |
| 4 | 24 | 12 | 35 | regs 24-35 |
| 5 | 30 | 12 | 41 | regs 30-41 |
| 6 | 70 | 12 | 81 | regs 70-81 |
| 7 | 72 | 12 | 83 | regs 72-83 |
| 8 | 74 | 12 | 85 | regs 74-85 |
| 9 | 76 | 12 | 87 | regs 76-87 |
| 10 | 78 | 12 | 89 | regs 78-89 |
| 11 | 86 | 12 | 97 | regs 86-97 |
| 12 | 88 | 12 | 99 | regs 88-99 |

**Total holding registers covered by firmware reads**: 72
**Range**: 0-99

### Input Register Read Blocks

| Block | Start Reg | Count | Coverage |
|-------|-----------|-------|----------|

### Holding Register Address Lists (from DSP literal pool)

Individual holding registers referenced in the DSP firmware:

- **reg 27**: `grid_frequency_connection_low`
- **reg 28**: `grid_frequency_connection_high`
- **reg 29**: `?`
- **reg 30**: `?`
- **reg 31**: `?`
- **reg 32**: `?`
- **reg 33**: `?`
- **reg 35**: `?`
- **reg 36**: `?`
- **reg 44**: `?`
- **reg 72**: `ac_charge_enable_period_1`

---

## 2. Input Registers (FC 0x04) - Complete Map

Cross-reference: pylxpweb definitions + live register dump values.

### Known Registers (in pylxpweb)

| Reg | Canonical Name | Scale | Unit | HA Sensor Key | 18kPV Value | FB21 Value |
|-----|----------------|-------|------|---------------|-------------|------------|
| 0 | `device_status` | NONE |  | `status_code` | 32 | 12 |
| 1 | `pv1_voltage` | DIV_10 | V | `pv1_voltage` | 1 | 2230 |
| 2 | `pv2_voltage` | DIV_10 | V | `pv2_voltage` | 1 | 3657 |
| 3 | `pv3_voltage` | DIV_10 | V | `pv3_voltage` | 4 | 33 |
| 4 | `battery_voltage` | DIV_10 | V | `battery_voltage` | 536 | 529 |
| 5 | `soc_soh_packed` | NONE |  | `` | 25682 | 25681 |
| 7 | `pv1_power` | NONE | W | `pv1_power` | 0 | 1995 |
| 8 | `pv2_power` | NONE | W | `pv2_power` | 0 | 4947 |
| 9 | `pv3_power` | NONE | W | `pv3_power` | 0 | 0 |
| 10 | `charge_power` | NONE | W | `battery_charge_power` | 5648 | 957 |
| 11 | `discharge_power` | NONE | W | `battery_discharge_power` | 0 | 0 |
| 12 | `grid_voltage_r` | DIV_10 | V | `grid_voltage_r` | 2473 | 2478 |
| 13 | `grid_voltage_s` | DIV_10 | V | `grid_voltage_s` | 1 | 0 |
| 14 | `grid_voltage_t` | DIV_10 | V | `grid_voltage_t` | 0 | 0 |
| 15 | `grid_frequency` | DIV_100 | Hz | `grid_frequency` | 6001 | 6002 |
| 16 | `inverter_power` | NONE | W | `ac_power` | 0 | 5705 |
| 17 | `rectifier_power` | NONE | W | `rectifier_power` | 5763 | 0 |
| 18 | `inverter_rms_current_r` | DIV_100 | A | `grid_current_l1` | 2390 | 2344 |
| 20 | `eps_voltage_r` | DIV_10 | V | `eps_voltage_r` | 2464 | 2474 |
| 21 | `eps_voltage_s` | DIV_10 | V | `eps_voltage_s` | 0 | 0 |
| 22 | `eps_voltage_t` | DIV_10 | V | `eps_voltage_t` | 160 | 0 |
| 23 | `eps_frequency` | DIV_100 | Hz | `eps_frequency` | 6001 | 6002 |
| 24 | `eps_power` | NONE | W | `eps_power` | 0 | 0 |
| 25 | `eps_apparent_power` | NONE | VA | `` | 0 | 0 |
| 26 | `power_to_grid` | NONE | W | `grid_export_power` | 3782 | 3710 |
| 27 | `power_to_user` | NONE | W | `grid_import_power` | 0 | 0 |
| 28 | `pv1_energy_today` | DIV_10 | kWh | `` | 0 | 25 |
| 29 | `pv2_energy_today` | DIV_10 | kWh | `` | 0 | 57 |
| 30 | `pv3_energy_today` | DIV_10 | kWh | `` | 0 | 0 |
| 31 | `inverter_energy_today` | DIV_10 | kWh | `yield` | 0 | 41 |
| 32 | `ac_charge_energy_today` | DIV_10 | kWh | `` | 72 | 44 |
| 33 | `charge_energy_today` | DIV_10 | kWh | `charging` | 72 | 83 |
| 34 | `discharge_energy_today` | DIV_10 | kWh | `discharging` | 0 | 0 |
| 35 | `eps_energy_today` | DIV_10 | kWh | `` | 0 | 0 |
| 36 | `grid_export_energy_today` | DIV_10 | kWh | `grid_export` | 52 | 36 |
| 37 | `grid_import_energy_today` | DIV_10 | kWh | `grid_import` | 342 | 371 |
| 38 | `bus_voltage_1` | DIV_10 | V | `bus1_voltage` | 3787 | 3806 |
| 39 | `bus_voltage_2` | DIV_10 | V | `bus2_voltage` | 3330 | 3225 |
| 40 | `pv1_energy_total` | DIV_10 | kWh | `` | 14718 | 8116 |
| 42 | `pv2_energy_total` | DIV_10 | kWh | `` | 5275 | 16835 |
| 44 | `pv3_energy_total` | DIV_10 | kWh | `` | 984 | 3 |
| 46 | `inverter_energy_total` | DIV_10 | kWh | `yield_lifetime` | 54479 | 26138 |
| 48 | `ac_charge_energy_total` | DIV_10 | kWh | `` | 42781 | 3399 |
| 50 | `charge_energy_total` | DIV_10 | kWh | `charging_lifetime` | 50810 | 9331 |
| 52 | `discharge_energy_total` | DIV_10 | kWh | `discharging_lifetime` | 44183 | 8192 |
| 54 | `eps_energy_total` | DIV_10 | kWh | `` | 7 | 0 |
| 56 | `grid_export_energy_total` | DIV_10 | kWh | `grid_export_lifetime` | 32124 | 23394 |
| 58 | `grid_import_energy_total` | DIV_10 | kWh | `grid_import_lifetime` | 16313 | 26175 |
| 60 | `fault_code` | NONE |  | `fault_code` | 0 | 0 |
| 62 | `warning_code` | NONE |  | `warning_code` | 0 | 0 |
| 64 | `internal_temperature` | NONE | °C | `internal_temperature` | 43 | 31 |
| 65 | `radiator_temperature_1` | NONE | °C | `radiator1_temperature` | 53 | 31 |
| 66 | `radiator_temperature_2` | NONE | °C | `radiator2_temperature` | 51 | 33 |
| 67 | `battery_temperature` | NONE | °C | `battery_temperature` | 5 | 5 |
| 68 | `battery_control_temperature` | NONE | °C | `` | 0 | 0 |
| 69 | `running_time` | NONE | s | `` | 11047 | 23568 |
| 72 | `pv1_current` | DIV_100 | A | `` | 0 | 0 |
| 73 | `pv2_current` | DIV_100 | A | `` | 0 | 0 |
| 74 | `pv3_current` | DIV_100 | A | `` | 0 | 0 |
| 75 | `battery_current_inv` | DIV_100 | A | `` | 0 | 0 |
| 77 | `ac_input_type` | NONE |  | `` | 226 | 226 |
| 80 | `bms_battery_type` | NONE |  | `` | 6 | 6 |
| 81 | `bms_charge_current_limit` | DIV_10 | A | `` | 6000 | 6000 |
| 82 | `bms_discharge_current_limit` | DIV_10 | A | `` | 6000 | 6000 |
| 83 | `bms_charge_voltage_ref` | DIV_10 | V | `` | 560 | 560 |
| 84 | `bms_discharge_cutoff` | DIV_10 | V | `` | 450 | 450 |
| 85 | `bms_status_0` | NONE |  | `` | 0 | 0 |
| 86 | `bms_status_1` | NONE |  | `` | 0 | 0 |
| 87 | `bms_status_2` | NONE |  | `` | 0 | 0 |
| 88 | `bms_status_3` | NONE |  | `` | 0 | 0 |
| 89 | `bms_status_4` | NONE |  | `` | 0 | 0 |
| 90 | `bms_status_5` | NONE |  | `` | 192 | 192 |
| 91 | `bms_status_6` | NONE |  | `` | 0 | 0 |
| 92 | `bms_status_7` | NONE |  | `` | 0 | 0 |
| 93 | `bms_status_8` | NONE |  | `` | 0 | 0 |
| 94 | `bms_status_9` | NONE |  | `` | 0 | 0 |
| 95 | `battery_status_inv` | NONE |  | `battery_status` | 3 | 3 |
| 96 | `battery_parallel_count` | NONE |  | `battery_bank_count` | 3 | 3 |
| 97 | `battery_capacity_ah` | NONE | Ah | `` | 840 | 840 |
| 98 | `battery_current_bms` | DIV_10 | A | `battery_current` | 1025 | 167 |
| 99 | `bms_fault_code` | NONE |  | `bms_fault_code` | 0 | 0 |
| 100 | `bms_warning_code` | NONE |  | `bms_warning_code` | 0 | 0 |
| 101 | `bms_max_cell_voltage` | DIV_1000 | V | `` | 3360 | 3314 |
| 102 | `bms_min_cell_voltage` | DIV_1000 | V | `` | 3350 | 3309 |
| 103 | `bms_max_cell_temperature` | DIV_10 | °C | `` | 210 | 200 |
| 104 | `bms_min_cell_temperature` | DIV_10 | °C | `` | 200 | 190 |
| 105 | `bms_fw_update_state` | NONE |  | `` | 0 | 0 |
| 106 | `bms_cycle_count` | NONE |  | `` | 152 | 67 |
| 107 | `battery_voltage_inv_sample` | DIV_10 | V | `` | 540 | 531 |
| 108 | `temperature_t1` | DIV_10 | °C | `bt_temperature` | 414 | 300 |
| 109 | `temperature_t2` | DIV_10 | °C | `` | 0 | 0 |
| 110 | `temperature_t3` | DIV_10 | °C | `` | 0 | 0 |
| 111 | `temperature_t4` | DIV_10 | °C | `` | 0 | 0 |
| 112 | `temperature_t5` | DIV_10 | °C | `` | 0 | 0 |
| 113 | `parallel_config` | NONE |  | `` | 518 | 517 |
| 121 | `generator_voltage` | DIV_10 | V | `generator_voltage` | 0 | 0 |
| 122 | `generator_frequency` | DIV_100 | Hz | `generator_frequency` | 0 | 0 |
| 123 | `generator_power` | NONE | W | `generator_power` | 5742 | 5713 |
| 124 | `generator_energy_today` | DIV_10 | kWh | `` | 90 | 89 |
| 125 | `generator_energy_total` | DIV_10 | kWh | `` | 56099 | 23075 |
| 127 | `eps_l1_voltage` | DIV_10 | V | `eps_voltage_l1` | 1231 | 1233 |
| 128 | `eps_l2_voltage` | DIV_10 | V | `eps_voltage_l2` | 1235 | 1234 |
| 129 | `eps_l1_power` | NONE | W | `` | 0 | 0 |
| 130 | `eps_l2_power` | NONE | W | `` | 0 | 0 |
| 131 | `eps_l1_apparent_power` | NONE | VA | `` | 0 | 0 |
| 132 | `eps_l2_apparent_power` | NONE | VA | `` | 0 | 0 |
| 133 | `eps_l1_energy_today` | DIV_10 | kWh | `` | 0 | 0 |
| 134 | `eps_l2_energy_today` | DIV_10 | kWh | `` | 0 | 0 |
| 135 | `eps_l1_energy_total` | DIV_10 | kWh | `` | 7 | 0 |
| 137 | `eps_l2_energy_total` | DIV_10 | kWh | `` | 7 | 0 |
| 153 | `ac_couple_power` | NONE | W | `` | 5794 | 0 |
| 170 | `output_power` | NONE | W | `output_power` | 1950 | 2005 |
| 171 | `load_energy_today` | DIV_10 | kWh | `` | 357 | 0 |
| 172 | `load_energy_total` | DIV_10 | kWh | `` | 5816 | 1429 |
| 190 | `inverter_rms_current_s` | DIV_100 | A | `grid_current_l2` | 0 | 0 |
| 191 | `inverter_rms_current_t` | DIV_100 | A | `grid_current_l3` | 0 | 0 |
| 193 | `grid_l1_voltage` | DIV_10 | V | `grid_voltage_l1` | 0 | 0 |
| 194 | `grid_l2_voltage` | DIV_10 | V | `grid_voltage_l2` | 0 | 0 |
| 195 | `generator_l1_voltage` | DIV_10 | V | `` | 0 | 0 |
| 196 | `generator_l2_voltage` | DIV_10 | V | `` | 0 | 0 |
| 197 | `inverter_power_l1` | NONE | W | `` | 0 | 0 |
| 198 | `inverter_power_l2` | NONE | W | `` | 0 | 0 |
| 199 | `rectifier_power_l1` | NONE | W | `` | 0 | 0 |
| 200 | `rectifier_power_l2` | NONE | W | `` | 0 | 0 |
| 201 | `grid_export_power_l1` | NONE | W | `` | 0 | 0 |
| 202 | `grid_export_power_l2` | NONE | W | `` | 0 | 0 |
| 203 | `grid_import_power_l1` | NONE | W | `` | 0 | 0 |
| 204 | `grid_import_power_l2` | NONE | W | `` | 0 | 0 |
| 210 | `quick_charge_remaining_seconds` | NONE | s | `` | 0 | 0 |
| 217 | `pv4_voltage` | DIV_10 | V | `pv4_voltage` | 0 | 0 |
| 218 | `pv5_voltage` | DIV_10 | V | `pv5_voltage` | 0 | 0 |
| 219 | `pv6_voltage` | DIV_10 | V | `pv6_voltage` | 0 | 0 |
| 220 | `pv4_power` | NONE | W | `pv4_power` | 0 | 0 |
| 221 | `pv5_power` | NONE | W | `pv5_power` | 0 | 0 |
| 222 | `pv6_power` | NONE | W | `pv6_power` | 0 | 0 |
| 223 | `epv4_day` | DIV_10 | kWh | `epv4_day` | 0 | 0 |
| 224 | `epv4_all` | DIV_10 | kWh | `epv4_all` | 0 | 0 |
| 226 | `epv5_day` | DIV_10 | kWh | `epv5_day` | 0 | 0 |
| 227 | `epv5_all` | DIV_10 | kWh | `epv5_all` | 0 | 0 |
| 229 | `epv6_day` | DIV_10 | kWh | `epv6_day` | 0 | 0 |
| 230 | `epv6_all` | DIV_10 | kWh | `epv6_all` | 0 | 0 |
| 232 | `smart_load_power` | NONE | W | `` | 0 | 0 |

### Undocumented Input Registers (non-zero in live dump)

These registers have data but no pylxpweb definition.

| Reg | 18kPV Value | FB21 Value | Possible Interpretation |
|-----|-------------|------------|------------------------|
| 6 | 13568 | 9984 | Unknown (between SOC/SOH packed and PV1 power) |
| 19 | 1000 | 1000 | Power factor (DIV_1000, defined but no HA sensor) |
| 57 | 1 |  | Unknown purpose (avg=1) |
| 59 | 2 |  | Unknown purpose (avg=2) |
| 70 | 450 | 122 | Running time (32-bit, defined) |
| 78 | 4681 | 4818 | BMS/parallel/generator registers (partially defined) |
| 79 | 769 | 769 | BMS/parallel/generator registers (partially defined) |
| 114 | 1965 |  | Firmware version / serial number fields |
| 115 | 13620 | 12853 | Firmware version / serial number fields |
| 116 | 12849 | 13368 | Firmware version / serial number fields |
| 117 | 14134 | 20530 | Firmware version / serial number fields |
| 118 | 12592 | 13616 | Firmware version / serial number fields |
| 119 | 14385 | 12600 | Firmware version / serial number fields |
| 120 | 1894 | 1876 | Firmware version / serial number fields |
| 126 | 1 |  | Extended runtime / energy counters |
| 139 | 1010 | 1203 | Holding register mirror (firmware quirk) or extended runtime |
| 140 | 1228 | 1228 | Holding register mirror (firmware quirk) or extended runtime |
| 141 | 1227 | 1242 | Holding register mirror (firmware quirk) or extended runtime |
| 142 | 8448 | 99 | Holding register mirror (firmware quirk) or extended runtime |
| 143 | 9238 | 557 | Holding register mirror (firmware quirk) or extended runtime |
| 144 | 1543 | 376 | Holding register mirror (firmware quirk) or extended runtime |
| 145 | 12544 | 12072 | Holding register mirror (firmware quirk) or extended runtime |
| 148 | 1 | 257 | Holding register mirror (firmware quirk) or extended runtime |
| 151 | 2 | 2 | Holding register mirror (firmware quirk) or extended runtime |
| 173 | 3 |  | Holding register mirror (firmware quirk) or extended runtime |
| 174 | 2 | 1 | Holding register mirror (firmware quirk) or extended runtime |
| 241 | 1 | 1 | Three-phase / extended registers (LXP only?) |
| 242 | 300 | 300 | Three-phase / extended registers (LXP only?) |
| 244 | 1 | 1 | Three-phase / extended registers (LXP only?) |
| 245 | 512 | 512 | Three-phase / extended registers (LXP only?) |
| 252 | 240 | 240 | Three-phase / extended registers (LXP only?) |
| 253 | 5 | 5 | Three-phase / extended registers (LXP only?) |
| 254 | 20 | 20 | Three-phase / extended registers (LXP only?) |
| 257 | 15127 | 15127 | Three-phase / extended registers (LXP only?) |
| 260 | 550 | 550 | Three-phase / extended registers (LXP only?) |
| 268 | 255 | 255 | Three-phase / extended registers (LXP only?) |
| 270 | 15127 | 15127 | Three-phase / extended registers (LXP only?) |
| 336 | 1000 | 1000 | Three-phase / extended registers (LXP only?) |

---

## 3. Holding Registers (FC 0x03) - Complete Map

### Known Registers (in pylxpweb)

| Reg | Canonical Name | API Param Key | HA Entity Key | 18kPV | FB21 |
|-----|----------------|---------------|---------------|-------|------|
| 9 | `com_protocol_version` | `HOLD_COM_VERSION` | `` | 9987 | 9987 |
| 10 | `controller_version` | `HOLD_CONTROLLER_VERSION` | `` | 295 | 295 |
| 15 | `modbus_address` | `HOLD_COM_ADDR` | `` | 1 | 1 |
| 16 | `language` | `HOLD_LANGUAGE` | `` | 1 | 1 |
| 19 | `device_type_code` | `HOLD_DEVICE_TYPE_CODE` | `` | 2092 | 10284 |
| 20 | `pv_input_mode` | `HOLD_PV_INPUT_MODE` | `` | 0 | 4 |
| 21 | `eps_enable` | `FUNC_EPS_EN` | `battery_backup` | 65493 | 65493 |
| 22 | `pv_start_voltage` | `HOLD_START_PV_VOLT` | `` | 2000 | 1400 |
| 23 | `grid_connection_wait_time` | `HOLD_CONNECT_TIME` | `` | 300 | 300 |
| 24 | `grid_reconnection_wait_time` | `HOLD_RECONNECT_TIME` | `` | 300 | 300 |
| 25 | `grid_voltage_connection_low` | `HOLD_GRID_VOLT_CONN_LOW` | `` | 2200 | 2200 |
| 26 | `lsp_whole_bypass_1_enable` | `FUNC_LSP_WHOLE_BYPASS_1_EN` | `` | 2520 | 2520 |
| 27 | `grid_frequency_connection_low` | `HOLD_GRID_FREQ_CONN_LOW` | `` | 4500 | 4500 |
| 28 | `grid_frequency_connection_high` | `HOLD_GRID_FREQ_CONN_HIGH` | `` | 6500 | 6500 |
| 59 | `reactive_power_mode` | `HOLD_Q_MODE` | `` | 0 | 0 |
| 60 | `reactive_power_pv_mode` | `HOLD_Q_PV_MODE` | `` | 100 | 100 |
| 61 | `reactive_power_setting` | `HOLD_Q_POWER` | `` | 100 | 100 |
| 62 | `reactive_power_pv_setting` | `HOLD_Q_PV_POWER` | `` | 1000 | 1000 |
| 64 | `charge_power_percent` | `HOLD_CHG_POWER_PERCENT_CMD` | `pv_charge_power` | 6 | 80 |
| 65 | `discharge_power_percent` | `HOLD_DISCHG_POWER_PERCENT_CMD` | `` | 100 | 100 |
| 66 | `ac_charge_power` | `HOLD_AC_CHARGE_POWER_CMD` | `ac_charge_power` | 120 | 120 |
| 67 | `ac_charge_soc_limit` | `HOLD_AC_CHARGE_SOC_LIMIT` | `ac_charge_soc_limit` | 60 | 60 |
| 68 | `ac_charge_start_hour_1` | `HOLD_AC_CHARGE_START_HOUR_1` | `` | 21 | 21 |
| 69 | `ac_charge_start_minute_1` | `HOLD_AC_CHARGE_START_MINUTE_1` | `` | 8 | 8 |
| 70 | `ac_charge_end_hour_1` | `HOLD_AC_CHARGE_END_HOUR_1` | `` | 0 | 0 |
| 71 | `ac_charge_end_minute_1` | `HOLD_AC_CHARGE_END_MINUTE_1` | `` | 0 | 0 |
| 72 | `ac_charge_enable_period_1` | `HOLD_AC_CHARGE_ENABLE_1` | `` | 0 | 21 |
| 73 | `ac_charge_enable_period_2` | `HOLD_AC_CHARGE_ENABLE_2` | `` | 0 | 0 |
| 74 | `forced_charge_power_command` | `HOLD_FORCED_CHG_POWER_CMD` | `` | 120 | 10 |
| 75 | `forced_charge_soc_limit` | `HOLD_FORCED_CHG_SOC_LIMIT` | `` | 100 | 100 |
| 76 | `forced_charge_time_0_start` | `HOLD_FORCED_CHARGE_TIME_0_START` | `` | 8 | 8 |
| 77 | `forced_charge_time_0_end` | `HOLD_FORCED_CHARGE_TIME_0_END` | `` | 16 | 16 |
| 78 | `forced_charge_time_1_start` | `HOLD_FORCED_CHARGE_TIME_1_START` | `` | 0 | 0 |
| 79 | `forced_charge_time_1_end` | `HOLD_FORCED_CHARGE_TIME_1_END` | `` | 0 | 0 |
| 80 | `forced_charge_time_2_start` | `HOLD_FORCED_CHARGE_TIME_2_START` | `` | 0 | 0 |
| 81 | `forced_charge_time_2_end` | `HOLD_FORCED_CHARGE_TIME_2_END` | `` | 0 | 0 |
| 82 | `forced_discharge_power_command` | `HOLD_FORCED_DISCHG_POWER_CMD` | `` | 120 | 120 |
| 83 | `forced_discharge_soc_limit` | `HOLD_FORCED_DISCHG_SOC_LIMIT` | `` | 20 | 20 |
| 84 | `forced_discharge_time_0_start` | `HOLD_FORCED_DISCHARGE_TIME_0_START` | `` | 16 | 16 |
| 85 | `forced_discharge_time_0_end` | `HOLD_FORCED_DISCHARGE_TIME_0_END` | `` | 21 | 21 |
| 86 | `forced_discharge_time_1_start` | `HOLD_FORCED_DISCHARGE_TIME_1_START` | `` | 0 | 0 |
| 87 | `forced_discharge_time_1_end` | `HOLD_FORCED_DISCHARGE_TIME_1_END` | `` | 0 | 0 |
| 88 | `forced_discharge_time_2_start` | `HOLD_FORCED_DISCHARGE_TIME_2_START` | `` | 0 | 0 |
| 89 | `forced_discharge_time_2_end` | `HOLD_FORCED_DISCHARGE_TIME_2_END` | `` | 0 | 0 |
| 90 | `output_voltage_select` | `HOLD_INVERTER_OUTPUT_VOLTAGE` | `` | 240 | 240 |
| 91 | `output_frequency_select` | `HOLD_INVERTER_OUTPUT_FREQUENCY` | `` | 60 | 60 |
| 99 | `charge_voltage_ref` | `HOLD_LEAD_ACID_CHARGE_VOLTAGE_REF` | `` | 550 | 550 |
| 100 | `discharge_cutoff_voltage` | `HOLD_LEAD_ACID_DISCHARGE_CUT_OFF_VOLT` | `` | 400 | 400 |
| 101 | `charge_current_limit` | `HOLD_LEAD_ACID_CHARGE_RATE` | `charge_current` | 250 | 250 |
| 102 | `discharge_current_limit` | `HOLD_LEAD_ACID_DISCHARGE_RATE` | `discharge_current` | 250 | 250 |
| 103 | `max_backflow_power_percent` | `HOLD_MAX_BACKFLOW_POWER_PERCENT` | `` | 160 | 160 |
| 105 | `ongrid_discharge_cutoff_soc` | `HOLD_DISCHG_CUT_OFF_SOC_EOD` | `ongrid_discharge_soc` | 20 | 20 |
| 110 | `pv_grid_off_enable` | `FUNC_PV_GRID_OFF_EN` | `` | 1056 | 1056 |
| 112 | `system_type` | `HOLD_SYSTEM_TYPE` | `` | 2 | 1 |
| 116 | `ptouser_start_discharge` | `HOLD_PTOUSER_START_DISCHARGE` | `` | 100 | 100 |
| 118 | `voltage_start_derating` | `HOLD_VOLTAGE_START_DERATING` | `` | 400 | 400 |
| 119 | `power_offset_wct` | `HOLD_POWER_OFFSET_WCT` | `` | 0 | 0 |
| 120 | `half_hour_ac_charge_start_enable` | `FUNC_HALF_HOUR_AC_CHG_START_EN` | `` | 0 | 0 |
| 125 | `offgrid_discharge_cutoff_soc` | `HOLD_SOC_LOW_LIMIT_EPS_DISCHG` | `offgrid_discharge_soc` | 20 | 20 |
| 144 | `float_charge_voltage` | `HOLD_FLOAT_CHARGE_VOLTAGE` | `` | 540 | 540 |
| 145 | `output_priority` | `HOLD_OUTPUT_PRIORITY` | `` | 0 | 0 |
| 146 | `line_mode` | `HOLD_LINE_MODE` | `` | 0 | 0 |
| 147 | `battery_capacity` | `HOLD_BATTERY_CAPACITY` | `` | 0 | 0 |
| 148 | `battery_nominal_voltage` | `HOLD_BATTERY_NOMINAL_VOLTAGE` | `` | 0 | 0 |
| 149 | `equalization_voltage` | `HOLD_EQUALIZATION_VOLTAGE` | `` | 0 | 0 |
| 150 | `equalization_interval` | `HOLD_EQUALIZATION_PERIOD` | `` | 0 | 0 |
| 151 | `equalization_time` | `HOLD_EQUALIZATION_TIME` | `` | 0 | 0 |
| 158 | `ac_charge_start_voltage` | `HOLD_AC_CHARGE_START_VOLTAGE` | `` | 400 | 400 |
| 159 | `ac_charge_end_voltage` | `HOLD_AC_CHARGE_END_VOLTAGE` | `` | 590 | 560 |
| 160 | `ac_charge_start_soc` | `HOLD_AC_CHARGE_START_BATTERY_SOC` | `` | 5 | 5 |
| 161 | `ac_charge_end_soc` | `HOLD_AC_CHARGE_END_BATTERY_SOC` | `` | 0 | 0 |
| 162 | `battery_low_voltage` | `HOLD_BATTERY_LOW_VOLTAGE` | `` | 0 | 0 |
| 163 | `battery_low_back_voltage` | `HOLD_BATTERY_LOW_BACK_VOLTAGE` | `` | 0 | 0 |
| 164 | `battery_low_soc` | `HOLD_BATTERY_LOW_SOC` | `` | 0 | 0 |
| 165 | `battery_low_back_soc` | `HOLD_BATTERY_LOW_BACK_SOC` | `` | 0 | 0 |
| 166 | `battery_low_to_utility_voltage` | `HOLD_BATTERY_LOW_TO_UTILITY_VOLTAGE` | `` | 0 | 0 |
| 167 | `battery_low_to_utility_soc` | `HOLD_BATTERY_LOW_TO_UTILITY_SOC` | `` | 0 | 0 |
| 168 | `ac_charge_battery_current` | `HOLD_AC_CHARGE_BATTERY_CURRENT` | `` | 0 | 0 |
| 169 | `ongrid_eod_voltage` | `HOLD_ONGRID_EOD_VOLTAGE` | `` | 400 | 400 |
| 176 | `max_grid_input_power` | `HOLD_MAX_GRID_INPUT_POWER` | `` | 65535 | 65535 |
| 177 | `generator_rated_power` | `HOLD_GEN_RATED_POWER` | `` | 120 | 120 |
| 179 | `ac_ct_direction` | `FUNC_AC_CT_DIRECTION` | `` | 76 | 76 |
| 190 | `hold_p2` | `HOLD_P2` | `` | 50 | 50 |
| 194 | `gen_charge_start_voltage` | `HOLD_GEN_CHARGE_START_VOLTAGE` | `` | 400 | 400 |
| 195 | `gen_charge_end_voltage` | `HOLD_GEN_CHARGE_END_VOLTAGE` | `` | 560 | 560 |
| 196 | `gen_charge_start_soc` | `HOLD_GEN_CHARGE_START_SOC` | `` | 10 | 10 |
| 197 | `gen_charge_end_soc` | `HOLD_GEN_CHARGE_END_SOC` | `` | 100 | 100 |
| 198 | `max_gen_charge_battery_current` | `HOLD_MAX_GEN_CHARGE_BATTERY_CURRENT` | `` | 60 | 60 |
| 227 | `system_charge_soc_limit` | `HOLD_SYSTEM_CHARGE_SOC_LIMIT` | `system_charge_soc_limit` | 90 | 90 |
| 231 | `grid_peak_shaving_power` | `_12K_HOLD_GRID_PEAK_SHAVING_POWER` | `grid_peak_shaving_power` | 0 | 0 |
| 233 | `quick_charge_start_enable` | `FUNC_QUICK_CHG_START_EN` | `` | 4096 | 4096 |

### Undocumented Holding Registers (non-zero in live dump)

| Reg | 18kPV Value | FB21 Value | Possible Interpretation |
|-----|-------------|------------|------------------------|
| 0 | 34496 | 34304 | HOLD_MODEL / serial number fields |
| 1 | 9 | 265 | HOLD_MODEL / serial number fields |
| 2 | 13620 | 12853 | HOLD_MODEL / serial number fields |
| 3 | 12849 | 13368 | HOLD_MODEL / serial number fields |
| 4 | 14134 | 20530 | HOLD_MODEL / serial number fields |
| 5 | 12592 | 13616 | HOLD_MODEL / serial number fields |
| 6 | 14385 | 12600 | HOLD_MODEL / serial number fields |
| 7 | 16742 | 16710 | HOLD_MODEL / serial number fields |
| 8 | 16961 | 16961 | HOLD_MODEL / serial number fields |
| 11 | 1 | 1 | System/comm configuration |
| 12 | 1050 | 1050 | System/comm configuration |
| 13 | 2829 | 2829 | System/comm configuration |
| 14 | 8500 | 7476 | System/comm configuration |
| 29 | 2112 | 2112 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 30 | 2640 | 2640 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 31 | 2100 | 2100 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 32 | 1300 | 1300 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 33 | 1200 | 1200 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 34 | 2880 | 2880 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 35 | 200 | 200 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 36 | 16 | 16 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 37 | 1200 | 1200 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 38 | 2880 | 2880 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 39 | 200 | 200 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 40 | 16 | 16 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 41 | 2640 | 2640 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 42 | 4500 | 4500 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 43 | 6500 | 6500 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 44 | 30000 | 30000 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 45 | 30000 | 30000 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 46 | 4500 | 4500 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 47 | 6500 | 6500 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 48 | 16 | 16 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 49 | 16 | 16 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 50 | 4500 | 4500 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 51 | 6500 | 6500 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 52 | 16 | 16 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 53 | 16 | 16 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 54 | 44 | 44 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 55 | 2352 | 2352 | Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output) |
| 56 | 2208 | 2208 | Scheduling / generator / power parameter |
| 57 | 2448 | 2448 | Scheduling / generator / power parameter |
| 58 | 2592 | 2592 | Scheduling / generator / power parameter |
| 63 | 1000 | 1000 | Scheduling / generator / power parameter |
| 96 | 5 | 5 | Scheduling / generator / power parameter |
| 106 | 65336 | 65336 | Battery BMS configuration / current limits |
| 107 | 550 | 550 | Battery BMS configuration / current limits |
| 109 | 400 | 400 | Battery BMS configuration / current limits |
| 113 | 257 | 257 | Battery BMS configuration / current limits |
| 114 | 1 | 1 | Battery BMS configuration / current limits |
| 115 | 60040 | 60040 | Battery BMS configuration / current limits |
| 117 | 65486 | 65486 | Battery BMS configuration / current limits |
| 124 | 6304 | 6304 | Battery BMS configuration / current limits |
| 134 | 59960 | 59960 | Extended configuration / firmware-specific |
| 135 | 5696 | 5696 | Extended configuration / firmware-specific |
| 136 | 20 | 20 | Extended configuration / firmware-specific |
| 137 | 1420 | 1405 | Extended configuration / firmware-specific |
| 180 | 100 | 100 | Extended function enable / peak shaving / advanced params |
| 181 | 2544 | 2544 | Extended function enable / peak shaving / advanced params |
| 182 | 2640 | 2640 | Extended function enable / peak shaving / advanced params |
| 183 | 10 | 10 | Extended function enable / peak shaving / advanced params |
| 184 | 20 | 20 | Extended function enable / peak shaving / advanced params |
| 185 | 2400 | 2400 | Extended function enable / peak shaving / advanced params |
| 186 | 300 | 300 | Extended function enable / peak shaving / advanced params |
| 188 | 44 | 44 | Extended function enable / peak shaving / advanced params |
| 191 | 100 | 100 | Extended function enable / peak shaving / advanced params |
| 192 | 100 | 100 | Extended function enable / peak shaving / advanced params |
| 193 | 20 | 20 | Extended function enable / peak shaving / advanced params |
| 201 | 560 | 560 | Extended function enable / peak shaving / advanced params |
| 202 | 400 | 400 | Extended function enable / peak shaving / advanced params |
| 204 | 250 | 250 | Extended function enable / peak shaving / advanced params |
| 207 | 80 | 80 | Extended function enable / peak shaving / advanced params |
| 208 | 520 | 520 | Extended function enable / peak shaving / advanced params |
| 209 | 16 | 16 | Extended function enable / peak shaving / advanced params |
| 210 | 15124 | 15124 | Extended function enable / peak shaving / advanced params |
| 213 | 540 | 540 | Extended function enable / peak shaving / advanced params |
| 214 | 480 | 480 | Extended function enable / peak shaving / advanced params |
| 215 | 90 | 90 | Extended function enable / peak shaving / advanced params |
| 216 | 60 | 60 | Extended function enable / peak shaving / advanced params |
| 217 | 5 | 5 | Extended function enable / peak shaving / advanced params |
| 218 | 50 | 50 | Extended function enable / peak shaving / advanced params |
| 219 | 520 | 520 | Extended function enable / peak shaving / advanced params |
| 220 | 100 | 100 | Extended function enable / peak shaving / advanced params |
| 221 | 255 | 255 | Extended function enable / peak shaving / advanced params |
| 222 | 595 | 595 | Extended function enable / peak shaving / advanced params |
| 223 | 800 | 800 | Extended function enable / peak shaving / advanced params |
| 224 | 786 |  | Extended function enable / peak shaving / advanced params |
| 226 | 1024 | 1024 | Extended function enable / peak shaving / advanced params |
| 228 | 595 | 595 | Extended function enable / peak shaving / advanced params |
| 229 | 360 | 360 | Extended function enable / peak shaving / advanced params |
| 236 | 1 | 1 | Advanced configuration / model-specific |
| 237 | 4 | 4 | Advanced configuration / model-specific |
| 241 | 1 | 1 | Advanced configuration / model-specific |
| 242 | 300 | 300 | Advanced configuration / model-specific |
| 244 | 1 | 1 | Advanced configuration / model-specific |
| 245 | 512 | 512 | Advanced configuration / model-specific |
| 252 | 240 | 240 | Advanced configuration / model-specific |
| 253 | 5 | 5 | Advanced configuration / model-specific |
| 254 | 20 | 20 | Advanced configuration / model-specific |
| 257 | 15127 | 15127 | Extended parameters (scheduling blocks, rare) |
| 260 | 550 | 550 | Extended parameters (scheduling blocks, rare) |
| 268 | 255 | 255 | Extended parameters (scheduling blocks, rare) |
| 270 | 15127 | 15127 | Extended parameters (scheduling blocks, rare) |
| 336 | 1000 | 1000 | Extended parameters (scheduling blocks, rare) |

---

## 4. Battery Register Space (Input Regs 5000-5124)

Base address: 5002, 30 registers per battery, max 5 batteries per inverter.

### 18kPV Battery Data (3 batteries)

| Offset | Reg | Name | Battery 1 | Battery 2 | Battery 3 |
|--------|-----|------|-----------|-----------|-----------|
| 0 | 5002/5032/5062 | `protocol_id` | 49155 | 49155 | 49155 |
| 1 | 5003/5033/5063 | `full_capacity` | 280 | 280 | 280 |
| 2 | 5004/5034/5064 | `charge_voltage_ref` | 560 | 560 | 560 |
| 3 | 5005/5035/5065 | `charge_current_limit` | 2000 | 2000 | 2000 |
| 4 | 5006/5036/5066 | `discharge_current_limit` | 2000 | 2000 | 2000 |
| 5 | 5007/5037/5067 | `reserved_5` | 450 | 450 | 450 |
| 6 | 5008/5038/5068 | `voltage` | 5369 | 5362 | 5361 |
| 7 | 5009/5039/5069 | `current` | 372 | 342 | 318 |
| 8 | 5010/5040/5070 | `soc_soh_packed` | 25681 | 25678 | 25686 |
| 9 | 5011/5041/5071 | `cycle_count` | 152 | 139 | 109 |
| 10 | 5012/5042/5072 | `reserved_10` | 210 | 200 | 200 |
| 11 | 5013/5043/5073 | `reserved_11` | 200 | 200 | 200 |
| 12 | 5014/5044/5074 | `max_cell_voltage` | 3359 | 3356 | 3353 |
| 13 | 5015/5045/5075 | `min_cell_voltage` | 3353 | 3349 | 3349 |
| 14 | 5016/5046/5076 | `max_cell_temp` | 259 | 1028 | 0 |
| 15 | 5017/5047/5077 | `min_cell_temp` | 513 | 257 | 513 |
| 16 | 5018/5048/5078 | `bms_flags` | 529 | 529 | 529 |
| 17 | 5019/5049/5079 | `bms_version` | 24898 | 24898 | 24898 |
| 18 | 5020/5050/5080 | `bms_serial_1` | 29812 | 29812 | 29812 |
| 19 | 5021/5051/5081 | `bms_serial_2` | 29285 | 29285 | 29285 |
| 20 | 5022/5052/5082 | `bms_serial_3` | 24441 | 24441 | 24441 |
| 21 | 5023/5053/5083 | `bms_serial_4` | 17481 | 17481 | 17481 |
| 22 | 5024/5054/5084 | `bms_serial_5` | 12383 | 12383 | 12383 |
| 23 | 5025/5055/5085 | `bms_serial_6` | 49 | 50 | 51 |
| 24 | 5026/5056/5086 | `bms_serial_7` | 0 | 256 | 512 |
| 25 | 5027/5057/5087 | `bms_serial_8` | 0 | 0 | 0 |
| 26 | 5028/5058/5088 | `reserved_26` | 0 | 0 | 0 |
| 27 | 5029/5059/5089 | `reserved_27` | 0 | 0 | 0 |
| 28 | 5030/5060/5090 | `reserved_28` | 0 | 0 | 0 |
| 29 | 5031/5061/5091 | `reserved_29` | 0 | 0 | 0 |

---

## 5. ARM Firmware Decompilation Analysis

### FUN_08041612 (5,818 bytes) - Main Modbus Handler

The largest function in the firmware. Ghidra's decompilation is heavily
corrupted due to ARM Thumb-2 mixed instruction/data issues.

**What is recoverable from the decompiled output:**

1. **Slave address check**: `(char)local_28 == '\x01'` -- checks Modbus slave ID = 1
2. **FC 0x06 handler**: `*(char *)(param_1 + 1) == '\x06'` -- Write Single Register
   - Extracts register address from bytes 2-3: `CONCAT11(*(param_1 + 2), *(param_1 + 3))`
   - Sets count=1, response length=4 (standard FC 06 response)
3. **FC 0x16 handler**: `*(char *)(param_1 + 1) == '\x16'` -- Mask Write Register (FC 22)
   - Extracts register count from offset 0x0E
   - Response length = 0x11 (17 bytes)
4. **Calls FUN_080659f2**: Memory clear/init (memset-like)
5. **Calls FUN_08023ace**: Likely CRC calculation or UART transmit
6. **Calls FUN_080587e4**: Likely register access/validation

**Why full register extraction failed:**
- 90+ 'Removing unreachable block' warnings indicate Ghidra couldn't follow branch tables
- 'Bad instruction data' and 'Truncating control flow' at the core register dispatch code
- ARM Thumb-2 inline literal pools misidentified as instructions
- The register dispatch likely uses a computed jump table (switch statement) that
  Ghidra couldn't reconstruct from the binary

### Other Modbus-Related Functions

| Function | Size | FC Codes | Role |
|----------|------|----------|------|
| FUN_08041612 | 5,818B | FC6, FC22 | Main Modbus PDU handler |
| FUN_08040ce8 | 668B | - | Register value processor (param validation?) |
| FUN_0803d340 | ~500B | FC16, FC22 | Write-multiple response handler |
| FUN_08045f34 | 810B | FC3/FC4 | Read response builder |
| FUN_080376cc | 1,080B | FC3 | UART/Modbus state machine |

### Modbus Function Code Summary

| FC | Hex | Name | Found In |
|----|-----|------|----------|
| 3 | 0x03 | Read Holding Registers | FUN_080376cc, FUN_08045f34 |
| 4 | 0x04 | Read Input Registers | (implied by FC3 handler) |
| 6 | 0x06 | Write Single Register | FUN_08041612 |
| 16 | 0x10 | Write Multiple Registers | FUN_0803d340 |
| 22 | 0x16 | Mask Write Register | FUN_08041612, FUN_0803d340 |

---

## 6. DSP Firmware Analysis (TI C28x)

The Para firmware (.bin files) contain TI C28x DSP code that implements
the actual register handling, validation, and scaling. Key findings:

### Modbus Register Read Map (from DSP literal pool)

The DSP firmware at offset 0x1A306 contains a structured table of
register block read definitions used for DSP-to-ARM register transfer:

```
Section A - Single holding register blocks (12 regs each):
  [0-11] [6-17] [18-29] [24-35] [30-41]    -- config/function regs
  [70-81] [72-83] [74-85] [76-87] [78-89]   -- PV/battery/schedule regs
  [86-97] [88-99]                            -- battery/generator regs

Section B - Dual-block reads (input 14-29 + holding blocks):
  [input 14-29] + [holding 0-11]
  [input 14-29] + [holding 6-17]
  [input 14-29] + [holding 18-29]
  [input 14-29] + [holding 24-35]
  [input 14-29] + [holding 30-41]
```

### Calibration Tables

| Table | Offset | Entries | Description |
|-------|--------|---------|-------------|
| PV voltage curves | 0x1A000 | 10 x 8 | MPPT voltage range limits (0.1V units) |
| Power rating table | 0x1A0A0 | 8 x 8 | Model variant power limits |
| Scaling table | 0x1A4E0 | 8 | Prescaler values [1,5,20,60,100,200,244,256] |
| CRC-16/Modbus LOW | 0x24D8 | 256 | Standard Modbus CRC lookup (low byte) |
| CRC-16/Modbus HIGH | 0x26D8 | 256 | Standard Modbus CRC lookup (high byte) |

### Power Rating Table (Model Variants)

| Row | Rated W | Min W | PV Cap | Batt Cap | Grid Cap | Possible Model |
|-----|---------|-------|--------|----------|----------|---------------|
| 0 | 2,223 | 110 | 1,200 | 2,880 | 5,650 | Test/debug variant |
| 1 | 6,200 | 200 | 240 | 2,880 | 5,000 | 12KPV base |
| 2 | 6,500 | 200 | 1,080 | 2,980 | 5,600 | 12KPV with MPPT3 |
| 3 | 6,400 | 15 | 1,200 | 2,880 | 5,650 | Variant with strict limits |
| 4 | 6,200 | 100 | 240 | 2,880 | 5,000 | 12KPV variant (100W min) |
| 5 | 6,500 | 200 | 440 | 2,596 | 5,690 | Variant with lower batt cap |
| 6 | 6,310 | 2 | 1,200 | 2,880 | 5,650 | Variant (2W minimum, strict) |
| 7 | 6,200 | 110 | 0 | 0 | 0 | Base variant, no caps defined |

---

## 7. Register Space Summary

### Input Registers
- **Total non-zero in live dump**: 184 registers
- **Defined in pylxpweb**: 142 registers
- **Undocumented non-zero**: 111 registers
- **Coverage**: 73/184 non-zero registers documented (39%)

### Holding Registers
- **Total non-zero in live dump**: 165 registers
- **Defined in pylxpweb**: 91 registers
- **Undocumented non-zero**: 104 registers
- **Coverage**: 61/165 non-zero registers documented (36%)

### Battery Registers (5000-5124)
- **Non-zero registers**: 73
- **Active batteries (18kPV)**: 3 (regs 5002-5091)
- **Battery slots**: 5 max (5002-5151)

---

## 8. Recommendations for pylxpweb

### High-Priority Undocumented Registers to Investigate

**Input Registers:**
- **Reg 6**: 18kPV=13568, FlexBOSS21=9984 -- Unknown (between SOC/SOH packed and PV1 power)
- **Reg 19**: 18kPV=1000, FlexBOSS21=1000 -- Power factor (DIV_1000, defined but no HA sensor)
- **Reg 57**: 18kPV=1 -- Unknown purpose (avg=1)
- **Reg 59**: 18kPV=2 -- Unknown purpose (avg=2)
- **Reg 70**: 18kPV=450, FlexBOSS21=122 -- Running time (32-bit, defined)
- **Reg 78**: 18kPV=4681, FlexBOSS21=4818 -- BMS/parallel/generator registers (partially defined)
- **Reg 79**: 18kPV=769, FlexBOSS21=769 -- BMS/parallel/generator registers (partially defined)
- **Reg 114**: 18kPV=1965 -- Firmware version / serial number fields
- **Reg 115**: 18kPV=13620, FlexBOSS21=12853 -- Firmware version / serial number fields
- **Reg 116**: 18kPV=12849, FlexBOSS21=13368 -- Firmware version / serial number fields
- **Reg 117**: 18kPV=14134, FlexBOSS21=20530 -- Firmware version / serial number fields
- **Reg 118**: 18kPV=12592, FlexBOSS21=13616 -- Firmware version / serial number fields
- **Reg 119**: 18kPV=14385, FlexBOSS21=12600 -- Firmware version / serial number fields
- **Reg 120**: 18kPV=1894, FlexBOSS21=1876 -- Firmware version / serial number fields
- **Reg 126**: 18kPV=1 -- Extended runtime / energy counters
- **Reg 139**: 18kPV=1010, FlexBOSS21=1203 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 140**: 18kPV=1228, FlexBOSS21=1228 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 141**: 18kPV=1227, FlexBOSS21=1242 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 142**: 18kPV=8448, FlexBOSS21=99 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 143**: 18kPV=9238, FlexBOSS21=557 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 144**: 18kPV=1543, FlexBOSS21=376 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 145**: 18kPV=12544, FlexBOSS21=12072 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 148**: 18kPV=1, FlexBOSS21=257 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 151**: 18kPV=2, FlexBOSS21=2 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 173**: 18kPV=3 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 174**: 18kPV=2, FlexBOSS21=1 -- Holding register mirror (firmware quirk) or extended runtime
- **Reg 241**: 18kPV=1, FlexBOSS21=1 -- Three-phase / extended registers (LXP only?)
- **Reg 242**: 18kPV=300, FlexBOSS21=300 -- Three-phase / extended registers (LXP only?)
- **Reg 244**: 18kPV=1, FlexBOSS21=1 -- Three-phase / extended registers (LXP only?)
- **Reg 245**: 18kPV=512, FlexBOSS21=512 -- Three-phase / extended registers (LXP only?)
- **Reg 252**: 18kPV=240, FlexBOSS21=240 -- Three-phase / extended registers (LXP only?)
- **Reg 253**: 18kPV=5, FlexBOSS21=5 -- Three-phase / extended registers (LXP only?)
- **Reg 254**: 18kPV=20, FlexBOSS21=20 -- Three-phase / extended registers (LXP only?)
- **Reg 257**: 18kPV=15127, FlexBOSS21=15127 -- Three-phase / extended registers (LXP only?)
- **Reg 260**: 18kPV=550, FlexBOSS21=550 -- Three-phase / extended registers (LXP only?)
- **Reg 268**: 18kPV=255, FlexBOSS21=255 -- Three-phase / extended registers (LXP only?)
- **Reg 270**: 18kPV=15127, FlexBOSS21=15127 -- Three-phase / extended registers (LXP only?)
- **Reg 336**: 18kPV=1000, FlexBOSS21=1000 -- Three-phase / extended registers (LXP only?)

**Holding Registers:**
- **Reg 0**: 18kPV=34496, FlexBOSS21=34304 -- HOLD_MODEL / serial number fields
- **Reg 1**: 18kPV=9, FlexBOSS21=265 -- HOLD_MODEL / serial number fields
- **Reg 2**: 18kPV=13620, FlexBOSS21=12853 -- HOLD_MODEL / serial number fields
- **Reg 3**: 18kPV=12849, FlexBOSS21=13368 -- HOLD_MODEL / serial number fields
- **Reg 4**: 18kPV=14134, FlexBOSS21=20530 -- HOLD_MODEL / serial number fields
- **Reg 5**: 18kPV=12592, FlexBOSS21=13616 -- HOLD_MODEL / serial number fields
- **Reg 6**: 18kPV=14385, FlexBOSS21=12600 -- HOLD_MODEL / serial number fields
- **Reg 7**: 18kPV=16742, FlexBOSS21=16710 -- HOLD_MODEL / serial number fields
- **Reg 8**: 18kPV=16961, FlexBOSS21=16961 -- HOLD_MODEL / serial number fields
- **Reg 11**: 18kPV=1, FlexBOSS21=1 -- System/comm configuration
- **Reg 12**: 18kPV=1050, FlexBOSS21=1050 -- System/comm configuration
- **Reg 13**: 18kPV=2829, FlexBOSS21=2829 -- System/comm configuration
- **Reg 14**: 18kPV=8500, FlexBOSS21=7476 -- System/comm configuration
- **Reg 29**: 18kPV=2112, FlexBOSS21=2112 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 30**: 18kPV=2640, FlexBOSS21=2640 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 31**: 18kPV=2100, FlexBOSS21=2100 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 32**: 18kPV=1300, FlexBOSS21=1300 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 33**: 18kPV=1200, FlexBOSS21=1200 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 34**: 18kPV=2880, FlexBOSS21=2880 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 35**: 18kPV=200, FlexBOSS21=200 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 36**: 18kPV=16, FlexBOSS21=16 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 37**: 18kPV=1200, FlexBOSS21=1200 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 38**: 18kPV=2880, FlexBOSS21=2880 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 39**: 18kPV=200, FlexBOSS21=200 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 40**: 18kPV=16, FlexBOSS21=16 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 41**: 18kPV=2640, FlexBOSS21=2640 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 42**: 18kPV=4500, FlexBOSS21=4500 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 43**: 18kPV=6500, FlexBOSS21=6500 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 44**: 18kPV=30000, FlexBOSS21=30000 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 45**: 18kPV=30000, FlexBOSS21=30000 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 46**: 18kPV=4500, FlexBOSS21=4500 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 47**: 18kPV=6500, FlexBOSS21=6500 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 48**: 18kPV=16, FlexBOSS21=16 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 49**: 18kPV=16, FlexBOSS21=16 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 50**: 18kPV=4500, FlexBOSS21=4500 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 51**: 18kPV=6500, FlexBOSS21=6500 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 52**: 18kPV=16, FlexBOSS21=16 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 53**: 18kPV=16, FlexBOSS21=16 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 54**: 18kPV=44, FlexBOSS21=44 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 55**: 18kPV=2352, FlexBOSS21=2352 -- Grid/PV/battery parameter (likely in pylxpweb but missing from parsed output)
- **Reg 56**: 18kPV=2208, FlexBOSS21=2208 -- Scheduling / generator / power parameter
- **Reg 57**: 18kPV=2448, FlexBOSS21=2448 -- Scheduling / generator / power parameter
- **Reg 58**: 18kPV=2592, FlexBOSS21=2592 -- Scheduling / generator / power parameter
- **Reg 63**: 18kPV=1000, FlexBOSS21=1000 -- Scheduling / generator / power parameter
- **Reg 96**: 18kPV=5, FlexBOSS21=5 -- Scheduling / generator / power parameter
- **Reg 106**: 18kPV=65336, FlexBOSS21=65336 -- Battery BMS configuration / current limits
- **Reg 107**: 18kPV=550, FlexBOSS21=550 -- Battery BMS configuration / current limits
- **Reg 109**: 18kPV=400, FlexBOSS21=400 -- Battery BMS configuration / current limits
- **Reg 113**: 18kPV=257, FlexBOSS21=257 -- Battery BMS configuration / current limits
- **Reg 114**: 18kPV=1, FlexBOSS21=1 -- Battery BMS configuration / current limits
- **Reg 115**: 18kPV=60040, FlexBOSS21=60040 -- Battery BMS configuration / current limits
- **Reg 117**: 18kPV=65486, FlexBOSS21=65486 -- Battery BMS configuration / current limits
- **Reg 124**: 18kPV=6304, FlexBOSS21=6304 -- Battery BMS configuration / current limits
- **Reg 134**: 18kPV=59960, FlexBOSS21=59960 -- Extended configuration / firmware-specific
- **Reg 135**: 18kPV=5696, FlexBOSS21=5696 -- Extended configuration / firmware-specific
- **Reg 136**: 18kPV=20, FlexBOSS21=20 -- Extended configuration / firmware-specific
- **Reg 137**: 18kPV=1420, FlexBOSS21=1405 -- Extended configuration / firmware-specific
- **Reg 180**: 18kPV=100, FlexBOSS21=100 -- Extended function enable / peak shaving / advanced params
- **Reg 181**: 18kPV=2544, FlexBOSS21=2544 -- Extended function enable / peak shaving / advanced params
- **Reg 182**: 18kPV=2640, FlexBOSS21=2640 -- Extended function enable / peak shaving / advanced params
- **Reg 183**: 18kPV=10, FlexBOSS21=10 -- Extended function enable / peak shaving / advanced params
- **Reg 184**: 18kPV=20, FlexBOSS21=20 -- Extended function enable / peak shaving / advanced params
- **Reg 185**: 18kPV=2400, FlexBOSS21=2400 -- Extended function enable / peak shaving / advanced params
- **Reg 186**: 18kPV=300, FlexBOSS21=300 -- Extended function enable / peak shaving / advanced params
- **Reg 188**: 18kPV=44, FlexBOSS21=44 -- Extended function enable / peak shaving / advanced params
- **Reg 191**: 18kPV=100, FlexBOSS21=100 -- Extended function enable / peak shaving / advanced params
- **Reg 192**: 18kPV=100, FlexBOSS21=100 -- Extended function enable / peak shaving / advanced params
- **Reg 193**: 18kPV=20, FlexBOSS21=20 -- Extended function enable / peak shaving / advanced params
- **Reg 201**: 18kPV=560, FlexBOSS21=560 -- Extended function enable / peak shaving / advanced params
- **Reg 202**: 18kPV=400, FlexBOSS21=400 -- Extended function enable / peak shaving / advanced params
- **Reg 204**: 18kPV=250, FlexBOSS21=250 -- Extended function enable / peak shaving / advanced params
- **Reg 207**: 18kPV=80, FlexBOSS21=80 -- Extended function enable / peak shaving / advanced params
- **Reg 208**: 18kPV=520, FlexBOSS21=520 -- Extended function enable / peak shaving / advanced params
- **Reg 209**: 18kPV=16, FlexBOSS21=16 -- Extended function enable / peak shaving / advanced params
- **Reg 210**: 18kPV=15124, FlexBOSS21=15124 -- Extended function enable / peak shaving / advanced params
- **Reg 213**: 18kPV=540, FlexBOSS21=540 -- Extended function enable / peak shaving / advanced params
- **Reg 214**: 18kPV=480, FlexBOSS21=480 -- Extended function enable / peak shaving / advanced params
- **Reg 215**: 18kPV=90, FlexBOSS21=90 -- Extended function enable / peak shaving / advanced params
- **Reg 216**: 18kPV=60, FlexBOSS21=60 -- Extended function enable / peak shaving / advanced params
- **Reg 217**: 18kPV=5, FlexBOSS21=5 -- Extended function enable / peak shaving / advanced params
- **Reg 218**: 18kPV=50, FlexBOSS21=50 -- Extended function enable / peak shaving / advanced params
- **Reg 219**: 18kPV=520, FlexBOSS21=520 -- Extended function enable / peak shaving / advanced params
- **Reg 220**: 18kPV=100, FlexBOSS21=100 -- Extended function enable / peak shaving / advanced params
- **Reg 221**: 18kPV=255, FlexBOSS21=255 -- Extended function enable / peak shaving / advanced params
- **Reg 222**: 18kPV=595, FlexBOSS21=595 -- Extended function enable / peak shaving / advanced params
- **Reg 223**: 18kPV=800, FlexBOSS21=800 -- Extended function enable / peak shaving / advanced params
- **Reg 224**: 18kPV=786 -- Extended function enable / peak shaving / advanced params
- **Reg 226**: 18kPV=1024, FlexBOSS21=1024 -- Extended function enable / peak shaving / advanced params
- **Reg 228**: 18kPV=595, FlexBOSS21=595 -- Extended function enable / peak shaving / advanced params
- **Reg 229**: 18kPV=360, FlexBOSS21=360 -- Extended function enable / peak shaving / advanced params
- **Reg 236**: 18kPV=1, FlexBOSS21=1 -- Advanced configuration / model-specific
- **Reg 237**: 18kPV=4, FlexBOSS21=4 -- Advanced configuration / model-specific
- **Reg 241**: 18kPV=1, FlexBOSS21=1 -- Advanced configuration / model-specific
- **Reg 242**: 18kPV=300, FlexBOSS21=300 -- Advanced configuration / model-specific
- **Reg 244**: 18kPV=1, FlexBOSS21=1 -- Advanced configuration / model-specific
- **Reg 245**: 18kPV=512, FlexBOSS21=512 -- Advanced configuration / model-specific
- **Reg 252**: 18kPV=240, FlexBOSS21=240 -- Advanced configuration / model-specific
- **Reg 253**: 18kPV=5, FlexBOSS21=5 -- Advanced configuration / model-specific
- **Reg 254**: 18kPV=20, FlexBOSS21=20 -- Advanced configuration / model-specific
- **Reg 257**: 18kPV=15127, FlexBOSS21=15127 -- Extended parameters (scheduling blocks, rare)
- **Reg 260**: 18kPV=550, FlexBOSS21=550 -- Extended parameters (scheduling blocks, rare)
- **Reg 268**: 18kPV=255, FlexBOSS21=255 -- Extended parameters (scheduling blocks, rare)
- **Reg 270**: 18kPV=15127, FlexBOSS21=15127 -- Extended parameters (scheduling blocks, rare)
- **Reg 336**: 18kPV=1000, FlexBOSS21=1000 -- Extended parameters (scheduling blocks, rare)

### Register Gaps in Current Map

Input register addresses NOT defined in pylxpweb but within the active range (0-200):

Missing: [6, 19, 41, 43, 45, 47, 49, 51, 53, 55, 57, 59, 61, 63, 70, 71, 76, 78, 79, 114, 115, 116, 117, 118, 119, 120, 126, 136, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 154, 155, 156, 157, 158, 159, 160]...

### Firmware Architecture Insights

1. **Dual-CPU architecture**: ARM Cortex-M4 (communication/UI) + TI C28x DSP (power control)
2. **Register transfer**: DSP reads holding regs in 12-register blocks, transfers to ARM
3. **CRC-16/Modbus**: Standard polynomial confirmed (0xA001, init 0xFFFF)
4. **Multi-model support**: Both 18kW and 21kW constants in single firmware image
5. **Register map is code**: Implemented as C28x instructions, not data tables
6. **Block checksums**: 771-byte blocks with model-specific XOR key (0xE7A7)
