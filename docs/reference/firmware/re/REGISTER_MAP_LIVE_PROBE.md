# Live Modbus Register Probe - Complete Map

**Probe date**: 2026-04-13 19:26:54 UTC
**Firmware**: fAAB-2727 (both devices)
**Devices**: 18kPV (10.100.14.68:502), FlexBOSS21 (10.100.10.184:502)
**Probe method**: pymodbus 3.x, chunks of 10, 100ms delay, 3s timeout
**Ranges probed**: Holding 0-999, Input 0-999 + 5000-5200, Extended 1000-2100 (18kPV only)

## Summary

| Metric | Holding | Input | Total |
|--------|---------|-------|-------|
| Responding registers | 850 | 620 | 1470 |
| Known (in pylxpweb) | 91 | 243 | 334 |
| New (undocumented) | 759 | 377 | 1136 |
| New with non-zero values | 277 | 37 | 314 |
| New with different values between devices | 87 | 23 | 110 |

**Key finding**: Both inverters respond to holding registers 0-849 (850 contiguous)
and input registers 0-499 (500 contiguous). Extended ranges 1000-2100 return no data.
Battery input registers 5002-5121 respond as expected (4 slots x 30 registers).

**Register space layout**:
- Holding 0-8: Device identity (serial number, model code)
- Holding 9-233: Active configuration parameters (91 known)
- Holding 234-599: Scheduling tables, grid protection, mostly zero
- Holding 600-849: Secondary parameter page (partial mirror of 100-349)
- Input 0-232: Runtime data, energy counters, BMS data (243 known)
- Input 233-499: Extended runtime, mostly zero (mirrors some holding values)
- Input 5002-5121: Individual battery data (4 slots x 30 registers)

## Key Discoveries

### 1. Device Identity Block (Holding 0-8)

Registers 0-8 contain the device serial number and type code in ASCII format.

| Addr | 18kPV Raw | 18kPV ASCII | FlexBOSS21 Raw | FlexBOSS21 ASCII | Purpose |
|------|-----------|-------------|----------------|------------------|---------|
| 0 | 0x86C0 | .. | 0x8600 | .. | Device type/model code |
| 1 | 0x0009 | .. | 0x0109 | .. | Firmware/protocol version |
| 2 | 0x3534 | 54 | 0x3235 | 25 | Serial[0:2] |
| 3 | 0x3231 | 21 | 0x3438 | 48 | Serial[2:4] |
| 4 | 0x3736 | 76 | 0x5032 | P2 | Serial[4:6] |
| 5 | 0x3130 | 10 | 0x3530 | 50 | Serial[6:8] |
| 6 | 0x3831 | 81 | 0x3138 | 18 | Serial[8:10] |
| 7 | 0x4166 | Af | 0x4146 | AF | Firmware code[0:2] (Af/AF = fAAB) |
| 8 | 0x4241 | BA | 0x4241 | BA | Firmware code[2:4] (BA = common suffix) |

**Decoded serials**: 18kPV = `5421761081`, FlexBOSS21 = `2548P25018`
**Firmware marker**: H7-H8 = `AfBA` / `AFBA` (case variation for model sub-type)

### 2. Serial Number in Input Registers (Input 115-119)

Input registers 115-119 contain the same serial number as holding 2-6.
Input 120 contains what appears to be a firmware or dongle version.

| Addr | 18kPV | FlexBOSS21 | Purpose |
|------|-------|------------|---------|
| 115 | 13620 (0x3534) | 12853 (0x3235) | Serial[0:2] |
| 116 | 12849 (0x3231) | 13368 (0x3438) | Serial[2:4] |
| 117 | 14134 (0x3736) | 20530 (0x5032) | Serial[4:6] |
| 118 | 12592 (0x3130) | 13616 (0x3530) | Serial[6:8] |
| 119 | 14385 (0x3831) | 12600 (0x3138) | Serial[8:10] |
| 120 | 1878 (0x0756) | 2191 (0x088F) | Version (hi.lo) |

### 3. Grid Protection Limits (Holding 29-58)

Registers 29-58 contain grid protection voltage/frequency thresholds.
All values are identical between devices (factory defaults).
Most values are div/10 scaled (voltage in 0.1V, frequency in 0.1Hz).

| Addr | Value | /10 | Likely Purpose |
|------|-------|-----|----------------|
| 29 | 2112 | 211.2 | Grid under-voltage trip point 1 |
| 30 | 2640 | 264.0 | Grid over-voltage trip point 1 |
| 31 | 2100 | 210.0 | Grid under-voltage trip point 2 |
| 32 | 1300 | 130.0 | Grid under-voltage trip point 3 (slow) |
| 33 | 1200 | 120.0 | Grid under-voltage trip point 4 (slow) |
| 34 | 2880 | 288.0 | Grid over-voltage trip point 2 |
| 35 | 200 | 20.0 | Trip time (ms) for point 1 |
| 36 | 16 | 1.6 | Trip time (ms) for point 2 |
| 37 | 1200 | 120.0 | Frequency under-trip point 1 |
| 38 | 2880 | 288.0 | Frequency over-trip point 1 |
| 39 | 200 | 20.0 | Freq trip time 1 (ms) |
| 40 | 16 | 1.6 | Freq trip time 2 (ms) |
| 41 | 2640 | 264.0 | Grid overvoltage slow limit |
| 42 | 4500 | 450.0 | Voltage trip level 5 (450V = PV max?) |
| 43 | 6500 | 650.0 | Voltage trip level 6 (650V = bus max?) |
| 44 | 30000 | 3000.0 | Time constant (3000 = 30s or 300s) |
| 45 | 30000 | 3000.0 | Time constant (3000 = 30s or 300s) |
| 46 | 4500 | 450.0 | Voltage trip level 7 |
| 47 | 6500 | 650.0 | Voltage trip level 8 |
| 48 | 16 | 1.6 | Time constant |
| 49 | 16 | 1.6 | Time constant |
| 50 | 4500 | 450.0 | Voltage trip level 9 |
| 51 | 6500 | 650.0 | Voltage trip level 10 |
| 52 | 16 | 1.6 | Time constant |
| 53 | 16 | 1.6 | Time constant |
| 54 | 44 | 4.4 | Unknown (4.4 or 44) |
| 55 | 2352 | 235.2 | Voltage/frequency threshold (235.2V?) |
| 56 | 2208 | 220.8 | Voltage/frequency threshold (220.8V?) |
| 57 | 2448 | 244.8 | Voltage/frequency threshold (244.8V?) |
| 58 | 2592 | 259.2 | Voltage/frequency threshold (259.2V?) |

### 4. Scheduling Table (Holding 720-789)

Holding registers 720-789 contain a perfect 10-register repeating pattern.
This is a 7-slot scheduling/timer table with identical default values.

| Offset | Value | Likely Meaning |
|--------|-------|----------------|
| +0 | 100 | Power rate (100%) |
| +1 | 255 | SOC limit (255 = disabled) |
| +2 | 595 | Start time (5:95 → 05:57 or packed HHMM) |
| +3 | 800 | End time (8:00 or packed HHMM) |
| +4 | 786 | Config/flags (0x0312) |
| +5 | 0 | Reserved/unused |
| +6 | 1024 | Power limit (1024W or 0x0400 flags) |
| +7 | 90 | SOC threshold (90%) |
| +8 | 595 | Secondary start time |
| +9 | 360 | Duration (360 min = 6h) or secondary end |

Slot addresses: 720, 730, 740, 750, 760, 770, 780 (all identical = defaults)

### 5. Secondary Parameter Page (Holding 600-849)

Holding registers 600-849 appear to be a secondary parameter page.
51 non-zero values match their counterpart at (addr - 500), suggesting
this may be a slave/parallel inverter configuration mirror or backup page.

Notable differences from primary page (100-349):
- H600-H618: All zero where primary has non-zero config values
- H634-H637: Match H134-H137 (RTC/calendar related?)
- H720-H789: Scheduling table (not present in primary 220-289)
- H790+: Device-specific live data (different between 18kPV and FlexBOSS21)

### 6. Unknown Live Data Registers

These input registers have non-zero values that differ between devices,
suggesting they contain live operational data:

| Addr | 18kPV | FlexBOSS21 | Hypothesis |
|------|-------|------------|------------|
| 6 | 13568 | 9984 | Total PV power (combined strings, 18kPV: 1356.8W via /10) |
| 70 | 450 | 122 | Battery AH remaining or total charge AH (18kPV: 45.0 via /10) |
| 71 | 0 | 0 | Battery AH high word (32-bit counter) |
| 78 | 4681 | 4818 | BMS config/feature bitfield (different bit patterns) |
| 79 | 769 | 769 | BMS protocol/type bitfield (0x0301 = same on both) |
| 114 | 1475 | 0 | Dongle firmware version or comm status |
| 120 | 1878 | 2191 | Dongle/WiFi module firmware version (packed hi.lo) |
| 139 | 598 | 538 | Battery bus voltage (59.8V / 53.8V via /10) |
| 140 | 1211 | 1214 | AC L1 voltage (121.1V / 121.4V via /10) |
| 141 | 1218 | 1220 | AC L2 voltage (121.8V / 122.0V via /10) |
| 142 | 2560 | 100 | Unknown power/config (different scale per model?) |
| 143 | 9238 | 557 | CT power reading? (large difference between devices) |
| 144 | 1543 | 376 | CT or load power (different values) |
| 145 | 12544 | 12072 | Bus voltage or total energy (high values) |
| 148 | 1 | 257 | Parallel config/capability flags |
| 151 | 2 | 2 | Connection type or phase config |
| 174 | 2 | 1 | Inverter count in parallel group |

### 7. Battery Register Confirmation

Battery input registers 5002-5121 (4 slots x 30 regs) respond exactly as
documented. Slot 3 (5092-5121) is all zeros on both devices (only 3 batteries
connected). Registers 5000-5001 respond with zero (may be a battery bank header).
Registers 5027-5031, 5057-5061, 5087-5091, 5117-5119 are the reserved tail of
each 30-register block, all reading zero.

## Actionable New Registers for pylxpweb

These newly discovered registers have meaningful values and should be
considered for addition to the pylxpweb register map:

### High Priority (identity/live data)

| Addr | Type | Value Pattern | Recommended Name | Notes |
|------|------|--------------|------------------|-------|
| H0 | Holding | 0x86C0/0x8600 | `device_model_code` | High byte differs by model |
| H1 | Holding | 9/265 | `firmware_version_raw` | Packed firmware version |
| H2-6 | Holding | ASCII | `serial_number` (5 regs) | Already known from dongle protocol |
| H7-8 | Holding | ASCII | `firmware_code` (2 regs) | 'AfBA'/'AFBA' = fAAB firmware family |
| I6 | Input | 13568/9984 | `total_pv_power` | Sum of all PV string powers? |
| I70 | Input | 450/122 | `battery_charge_ah_today` | Amp-hours charged today? |
| I115-119 | Input | ASCII | `serial_number_input` | Mirror of H2-6 |
| I120 | Input | 1878/2191 | `dongle_firmware_version` | Packed version (7.86 / 8.143) |
| I139 | Input | 598/538 | `battery_bus_voltage` | Div/10 = 59.8V / 53.8V |
| I140-141 | Input | 1211/1218 | `ac_l1_voltage_ext`, `ac_l2_voltage_ext` | Div/10 = 121.1V, 121.8V |

### Medium Priority (config/protection)

| Addr | Type | Value | Recommended Name | Notes |
|------|------|-------|------------------|-------|
| H11 | Holding | 1 | `parallel_enabled` | Boolean flag |
| H12 | Holding | 1050 | `firmware_build_number` | Version sub-field |
| H13 | Holding | 3085 | `hardware_version` | Packed (12.13) |
| H29-34 | Holding | Various | `grid_uv_trip_1` through `grid_ov_trip_2` | Grid voltage protection |
| H42-53 | Holding | Various | Voltage/frequency trip table | UL1741/IEEE1547 limits |
| H63 | Holding | 1000 | `power_factor_setting` | 1000 = 1.000 (unity) |
| H96 | Holding | 5 | `parallel_device_count` | Number in parallel group |
| H106 | Holding | 65336 (-200) | `ct_offset_calibration` | Signed, calibration offset |
| H113 | Holding | 257 (0x0101) | `inverter_address_config` | Packed parallel addressing |

### Low Priority (scheduling/secondary page)

| Addr | Type | Notes |
|------|------|-------|
| H234-260 | Holding | Extended scheduling parameters |
| H600-849 | Holding | Secondary parameter page (parallel/backup) |
| H720-789 | Holding | 7-slot scheduling table (10 regs each) |
| I233-499 | Input | Extended runtime block, mostly zeros |

## Complete Holding Register Map (0-849)

Legend: **KNOWN** = in pylxpweb, **NEW** = undocumented, values shown for 18kPV

### Holding 0-28: Identity and Basic Config

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 0 | NEW | 34496 | 34304 |  |
| 1 | NEW | 9 | 265 |  |
| 2 | NEW | 13620 | 12853 |  |
| 3 | NEW | 12849 | 13368 |  |
| 4 | NEW | 14134 | 20530 |  |
| 5 | NEW | 12592 | 13616 |  |
| 6 | NEW | 14385 | 12600 |  |
| 7 | NEW | 16742 | 16710 |  |
| 8 | NEW | 16961 | 16961 |  |
| 9 | KNOWN | 9987 | 9987 | com_protocol_version |
| 10 | KNOWN | 295 | 295 | controller_version |
| 11 | NEW | 1 | 1 |  |
| 12 | NEW | 1050 | 1050 |  |
| 13 | NEW | 3085 | 3085 |  |
| 14 | NEW | 8986 | 4123 |  |
| 15 | KNOWN | 1 | 1 | modbus_address |
| 16 | KNOWN | 1 | 1 | language |
| 19 | KNOWN | 2092 | 10284 | device_type_code |
| 20 | KNOWN | 0 | 4 | pv_input_mode |
| 21 | KNOWN | 65493 | 65493 | eps_enable, overload_derate_enable, drms_enable |
| 22 | KNOWN | 2000 | 1400 | pv_start_voltage |
| 23 | KNOWN | 300 | 300 | grid_connection_wait_time |
| 24 | KNOWN | 300 | 300 | grid_reconnection_wait_time |
| 25 | KNOWN | 2200 | 2200 | grid_voltage_connection_low |
| 26 | KNOWN | 2520 | 2520 | lsp_whole_bypass_1_enable, lsp_whole_bypass_2_enable, lsp_whole_bypass_3_enable |
| 27 | KNOWN | 4500 | 4500 | grid_frequency_connection_low |
| 28 | KNOWN | 6500 | 6500 | grid_frequency_connection_high |

### Holding 29-58: Grid Protection Limits

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 29 | NEW | 2112 | 2112 |  |
| 30 | NEW | 2640 | 2640 |  |
| 31 | NEW | 2100 | 2100 |  |
| 32 | NEW | 1300 | 1300 |  |
| 33 | NEW | 1200 | 1200 |  |
| 34 | NEW | 2880 | 2880 |  |
| 35 | NEW | 200 | 200 |  |
| 36 | NEW | 16 | 16 |  |
| 37 | NEW | 1200 | 1200 |  |
| 38 | NEW | 2880 | 2880 |  |
| 39 | NEW | 200 | 200 |  |
| 40 | NEW | 16 | 16 |  |
| 41 | NEW | 2640 | 2640 |  |
| 42 | NEW | 4500 | 4500 |  |
| 43 | NEW | 6500 | 6500 |  |
| 44 | NEW | 30000 | 30000 |  |
| 45 | NEW | 30000 | 30000 |  |
| 46 | NEW | 4500 | 4500 |  |
| 47 | NEW | 6500 | 6500 |  |
| 48 | NEW | 16 | 16 |  |
| 49 | NEW | 16 | 16 |  |
| 50 | NEW | 4500 | 4500 |  |
| 51 | NEW | 6500 | 6500 |  |
| 52 | NEW | 16 | 16 |  |
| 53 | NEW | 16 | 16 |  |
| 54 | NEW | 44 | 44 |  |
| 55 | NEW | 2352 | 2352 |  |
| 56 | NEW | 2208 | 2208 |  |
| 57 | NEW | 2448 | 2448 |  |
| 58 | NEW | 2592 | 2592 |  |

### Holding 59-120: Power Settings and Control

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 59 | KNOWN | 0 | 0 | reactive_power_mode |
| 60 | KNOWN | 100 | 100 | reactive_power_pv_mode |
| 61 | KNOWN | 100 | 100 | reactive_power_setting |
| 62 | KNOWN | 1000 | 1000 | reactive_power_pv_setting |
| 63 | NEW | 1000 | 1000 |  |
| 64 | KNOWN | 6 | 80 | charge_power_percent |
| 65 | KNOWN | 100 | 100 | discharge_power_percent |
| 66 | KNOWN | 120 | 120 | ac_charge_power |
| 67 | KNOWN | 60 | 60 | ac_charge_soc_limit |
| 68 | KNOWN | 21 | 21 | ac_charge_start_hour_1 |
| 69 | KNOWN | 8 | 8 | ac_charge_start_minute_1 |
| 70 | KNOWN | 0 | 0 | ac_charge_end_hour_1 |
| 71 | KNOWN | 0 | 0 | ac_charge_end_minute_1 |
| 72 | KNOWN | 0 | 21 | ac_charge_enable_period_1 |
| 73 | KNOWN | 0 | 0 | ac_charge_enable_period_2 |
| 74 | KNOWN | 120 | 10 | forced_charge_power_command |
| 75 | KNOWN | 100 | 100 | forced_charge_soc_limit |
| 76 | KNOWN | 8 | 8 | forced_charge_time_0_start |
| 77 | KNOWN | 16 | 16 | forced_charge_time_0_end |
| 78 | KNOWN | 0 | 0 | forced_charge_time_1_start |
| 79 | KNOWN | 0 | 0 | forced_charge_time_1_end |
| 80 | KNOWN | 0 | 0 | forced_charge_time_2_start |
| 81 | KNOWN | 0 | 0 | forced_charge_time_2_end |
| 82 | KNOWN | 120 | 120 | forced_discharge_power_command |
| 83 | KNOWN | 20 | 20 | forced_discharge_soc_limit |
| 84 | KNOWN | 16 | 16 | forced_discharge_time_0_start |
| 85 | KNOWN | 21 | 21 | forced_discharge_time_0_end |
| 86 | KNOWN | 0 | 0 | forced_discharge_time_1_start |
| 87 | KNOWN | 0 | 0 | forced_discharge_time_1_end |
| 88 | KNOWN | 0 | 0 | forced_discharge_time_2_start |
| 89 | KNOWN | 0 | 0 | forced_discharge_time_2_end |
| 90 | KNOWN | 240 | 240 | output_voltage_select |
| 91 | KNOWN | 60 | 60 | output_frequency_select |
| 96 | NEW | 5 | 5 |  |
| 99 | KNOWN | 550 | 550 | charge_voltage_ref |
| 100 | KNOWN | 400 | 400 | discharge_cutoff_voltage |
| 101 | KNOWN | 250 | 250 | charge_current_limit |
| 102 | KNOWN | 250 | 250 | discharge_current_limit |
| 103 | KNOWN | 160 | 160 | max_backflow_power_percent |
| 105 | KNOWN | 20 | 20 | ongrid_discharge_cutoff_soc |
| 106 | NEW | 65336 | 65336 |  |
| 107 | NEW | 550 | 550 |  |
| 109 | NEW | 400 | 400 |  |
| 110 | KNOWN | 1056 | 1056 | pv_grid_off_enable, run_without_grid, micro_grid_enable |
| 112 | KNOWN | 2 | 1 | system_type |
| 113 | NEW | 257 | 257 |  |
| 114 | NEW | 1 | 1 |  |
| 115 | NEW | 60040 | 60040 |  |
| 116 | KNOWN | 100 | 100 | ptouser_start_discharge |
| 117 | NEW | 65486 | 65486 |  |
| 118 | KNOWN | 400 | 400 | voltage_start_derating |
| 119 | KNOWN | 0 | 0 | power_offset_wct |
| 120 | KNOWN | 0 | 0 | half_hour_ac_charge_start_enable, sna_battery_discharge_control, phase_independent_compensate_enable |

### Holding 121-199: Extended Config

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 124 | NEW | 6304 | 6304 |  |
| 125 | KNOWN | 20 | 20 | offgrid_discharge_cutoff_soc |
| 134 | NEW | 59960 | 59960 |  |
| 135 | NEW | 5696 | 5696 |  |
| 136 | NEW | 20 | 20 |  |
| 137 | NEW | 1421 | 1405 |  |
| 144 | KNOWN | 540 | 540 | float_charge_voltage |
| 145 | KNOWN | 0 | 0 | output_priority |
| 146 | KNOWN | 0 | 0 | line_mode |
| 147 | KNOWN | 0 | 0 | battery_capacity |
| 148 | KNOWN | 0 | 0 | battery_nominal_voltage |
| 149 | KNOWN | 0 | 0 | equalization_voltage |
| 150 | KNOWN | 0 | 0 | equalization_interval |
| 151 | KNOWN | 0 | 0 | equalization_time |
| 158 | KNOWN | 400 | 400 | ac_charge_start_voltage |
| 159 | KNOWN | 590 | 560 | ac_charge_end_voltage |
| 160 | KNOWN | 5 | 5 | ac_charge_start_soc |
| 161 | KNOWN | 0 | 0 | ac_charge_end_soc |
| 162 | KNOWN | 0 | 0 | battery_low_voltage |
| 163 | KNOWN | 0 | 0 | battery_low_back_voltage |
| 164 | KNOWN | 0 | 0 | battery_low_soc |
| 165 | KNOWN | 0 | 0 | battery_low_back_soc |
| 166 | KNOWN | 0 | 0 | battery_low_to_utility_voltage |
| 167 | KNOWN | 0 | 0 | battery_low_to_utility_soc |
| 168 | KNOWN | 0 | 0 | ac_charge_battery_current |
| 169 | KNOWN | 400 | 400 | ongrid_eod_voltage |
| 176 | KNOWN | 65535 | 65535 | max_grid_input_power |
| 177 | KNOWN | 120 | 120 | generator_rated_power |
| 179 | KNOWN | 76 | 76 | ac_ct_direction, pv_ct_direction, afci_alarm_clear |
| 180 | NEW | 100 | 100 |  |
| 181 | NEW | 2544 | 2544 |  |
| 182 | NEW | 2640 | 2640 |  |
| 183 | NEW | 10 | 10 |  |
| 184 | NEW | 20 | 20 |  |
| 185 | NEW | 2400 | 2400 |  |
| 186 | NEW | 300 | 300 |  |
| 188 | NEW | 44 | 44 |  |
| 190 | KNOWN | 50 | 50 | hold_p2 |
| 191 | NEW | 100 | 100 |  |
| 192 | NEW | 100 | 100 |  |
| 193 | NEW | 20 | 20 |  |
| 194 | KNOWN | 400 | 400 | gen_charge_start_voltage |
| 195 | KNOWN | 560 | 560 | gen_charge_end_voltage |
| 196 | KNOWN | 10 | 10 | gen_charge_start_soc |
| 197 | KNOWN | 100 | 100 | gen_charge_end_soc |
| 198 | KNOWN | 60 | 60 | max_gen_charge_battery_current |

### Holding 200-260: Advanced Settings

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 201 | NEW | 560 | 560 |  |
| 202 | NEW | 400 | 400 |  |
| 204 | NEW | 250 | 250 |  |
| 207 | NEW | 80 | 80 |  |
| 208 | NEW | 520 | 520 |  |
| 209 | NEW | 16 | 16 |  |
| 210 | NEW | 15124 | 15124 |  |
| 213 | NEW | 540 | 540 |  |
| 214 | NEW | 480 | 480 |  |
| 215 | NEW | 90 | 90 |  |
| 216 | NEW | 60 | 60 |  |
| 217 | NEW | 5 | 5 |  |
| 218 | NEW | 50 | 50 |  |
| 219 | NEW | 520 | 520 |  |
| 220 | NEW | 100 | 100 |  |
| 221 | NEW | 255 | 255 |  |
| 222 | NEW | 595 | 595 |  |
| 223 | NEW | 800 | 800 |  |
| 224 | NEW | 786 | 0 |  |
| 226 | NEW | 1024 | 1024 |  |
| 227 | KNOWN | 90 | 90 | system_charge_soc_limit |
| 228 | NEW | 595 | 595 |  |
| 229 | NEW | 360 | 360 |  |
| 231 | KNOWN | 0 | 0 | grid_peak_shaving_power |
| 233 | KNOWN | 4096 | 4096 | quick_charge_start_enable, battery_backup_enable, maintenance_enable |
| 236 | NEW | 1 | 1 |  |
| 237 | NEW | 4 | 4 |  |
| 241 | NEW | 1 | 1 |  |
| 242 | NEW | 300 | 300 |  |
| 244 | NEW | 1 | 1 |  |
| 245 | NEW | 512 | 512 |  |
| 252 | NEW | 240 | 240 |  |
| 253 | NEW | 5 | 5 |  |
| 254 | NEW | 20 | 20 |  |
| 257 | NEW | 15127 | 15127 |  |
| 260 | NEW | 550 | 550 |  |

### Holding 261-599: Scheduling / Reserved

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 268 | NEW | 255 | 255 |  |
| 270 | NEW | 15127 | 15127 |  |
| 336 | NEW | 1000 | 1000 |  |

### Holding 600-699: Secondary Page (mirrors 100-199)

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 612 | NEW | 0 | 1 |  |
| 613 | NEW | 0 | 257 |  |
| 614 | NEW | 0 | 1 |  |
| 615 | NEW | 0 | 60040 |  |
| 616 | NEW | 0 | 100 |  |
| 617 | NEW | 0 | 65486 |  |
| 618 | NEW | 0 | 400 |  |
| 624 | NEW | 0 | 6304 |  |
| 625 | NEW | 0 | 20 |  |
| 634 | NEW | 59960 | 59960 |  |
| 635 | NEW | 5696 | 5696 |  |
| 636 | NEW | 20 | 20 |  |
| 637 | NEW | 1422 | 1406 |  |
| 644 | NEW | 540 | 540 |  |
| 658 | NEW | 400 | 400 |  |
| 659 | NEW | 590 | 560 |  |
| 660 | NEW | 5 | 5 |  |
| 669 | NEW | 400 | 400 |  |
| 676 | NEW | 65535 | 65535 |  |
| 677 | NEW | 120 | 120 |  |
| 679 | NEW | 76 | 76 |  |
| 680 | NEW | 100 | 100 |  |
| 681 | NEW | 2544 | 2544 |  |
| 682 | NEW | 2640 | 2640 |  |
| 683 | NEW | 10 | 10 |  |
| 684 | NEW | 20 | 20 |  |
| 685 | NEW | 2400 | 2400 |  |
| 686 | NEW | 300 | 300 |  |
| 688 | NEW | 44 | 44 |  |
| 690 | NEW | 50 | 50 |  |
| 691 | NEW | 100 | 100 |  |
| 692 | NEW | 100 | 100 |  |
| 693 | NEW | 20 | 20 |  |
| 694 | NEW | 400 | 400 |  |
| 695 | NEW | 560 | 560 |  |
| 696 | NEW | 10 | 10 |  |
| 697 | NEW | 100 | 100 |  |
| 698 | NEW | 60 | 60 |  |

### Holding 700-849: Secondary Scheduling / Live Data

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 701 | NEW | 560 | 560 |  |
| 702 | NEW | 400 | 400 |  |
| 704 | NEW | 250 | 250 |  |
| 707 | NEW | 80 | 80 |  |
| 708 | NEW | 520 | 520 |  |
| 709 | NEW | 16 | 16 |  |
| 710 | NEW | 15124 | 15124 |  |
| 713 | NEW | 540 | 540 |  |
| 714 | NEW | 480 | 480 |  |
| 715 | NEW | 90 | 90 |  |
| 716 | NEW | 60 | 60 |  |
| 717 | NEW | 5 | 5 |  |
| 718 | NEW | 50 | 50 |  |
| 719 | NEW | 520 | 520 |  |
| 720 | NEW | 100 | 100 |  |
| 721 | NEW | 255 | 255 |  |
| 722 | NEW | 595 | 595 |  |
| 723 | NEW | 800 | 800 |  |
| 724 | NEW | 786 | 0 |  |
| 726 | NEW | 1024 | 1024 |  |
| 727 | NEW | 90 | 90 |  |
| 728 | NEW | 595 | 595 |  |
| 729 | NEW | 360 | 360 |  |
| 730 | NEW | 100 | 100 |  |
| 731 | NEW | 255 | 255 |  |
| 732 | NEW | 595 | 595 |  |
| 733 | NEW | 800 | 800 |  |
| 734 | NEW | 786 | 0 |  |
| 736 | NEW | 1024 | 1024 |  |
| 737 | NEW | 90 | 90 |  |
| 738 | NEW | 595 | 595 |  |
| 739 | NEW | 360 | 360 |  |
| 740 | NEW | 100 | 100 |  |
| 741 | NEW | 255 | 255 |  |
| 742 | NEW | 595 | 595 |  |
| 743 | NEW | 800 | 800 |  |
| 744 | NEW | 786 | 0 |  |
| 746 | NEW | 1024 | 1024 |  |
| 747 | NEW | 90 | 90 |  |
| 748 | NEW | 595 | 595 |  |
| 749 | NEW | 360 | 360 |  |
| 750 | NEW | 100 | 100 |  |
| 751 | NEW | 255 | 255 |  |
| 752 | NEW | 595 | 595 |  |
| 753 | NEW | 800 | 800 |  |
| 754 | NEW | 786 | 0 |  |
| 756 | NEW | 1024 | 1024 |  |
| 757 | NEW | 90 | 90 |  |
| 758 | NEW | 595 | 595 |  |
| 759 | NEW | 360 | 360 |  |
| 760 | NEW | 100 | 100 |  |
| 761 | NEW | 255 | 255 |  |
| 762 | NEW | 595 | 595 |  |
| 763 | NEW | 800 | 800 |  |
| 764 | NEW | 786 | 0 |  |
| 766 | NEW | 1024 | 1024 |  |
| 767 | NEW | 90 | 90 |  |
| 768 | NEW | 595 | 595 |  |
| 769 | NEW | 360 | 360 |  |
| 770 | NEW | 100 | 100 |  |
| 771 | NEW | 255 | 255 |  |
| 772 | NEW | 595 | 595 |  |
| 773 | NEW | 800 | 800 |  |
| 774 | NEW | 786 | 0 |  |
| 776 | NEW | 1024 | 1024 |  |
| 777 | NEW | 90 | 90 |  |
| 778 | NEW | 595 | 595 |  |
| 779 | NEW | 360 | 360 |  |
| 780 | NEW | 100 | 100 |  |
| 781 | NEW | 255 | 255 |  |
| 782 | NEW | 595 | 595 |  |
| 783 | NEW | 800 | 800 |  |
| 784 | NEW | 786 | 0 |  |
| 786 | NEW | 1024 | 1024 |  |
| 787 | NEW | 90 | 90 |  |
| 788 | NEW | 595 | 595 |  |
| 789 | NEW | 360 | 360 |  |
| 790 | NEW | 32 | 100 |  |
| 791 | NEW | 1 | 255 |  |
| 792 | NEW | 1 | 595 |  |
| 793 | NEW | 3 | 800 |  |
| 794 | NEW | 537 | 0 |  |
| 795 | NEW | 25687 | 0 |  |
| 796 | NEW | 13568 | 1024 |  |
| 797 | NEW | 0 | 90 |  |
| 798 | NEW | 0 | 595 |  |
| 799 | NEW | 0 | 360 |  |
| 800 | NEW | 99 | 100 |  |
| 801 | NEW | 98 | 255 |  |
| 802 | NEW | 0 | 595 |  |
| 803 | NEW | 0 | 800 |  |
| 804 | NEW | 68 | 0 |  |
| 805 | NEW | 343 | 0 |  |
| 806 | NEW | 3750 | 1024 |  |
| 807 | NEW | 3277 | 90 |  |
| 808 | NEW | 14718 | 595 |  |
| 809 | NEW | 0 | 360 |  |
| 810 | NEW | 33 | 100 |  |
| 811 | NEW | 52 | 255 |  |
| 812 | NEW | 38 | 595 |  |
| 813 | NEW | 5 | 800 |  |
| 815 | NEW | 13121 | 0 |  |
| 816 | NEW | 450 | 1024 |  |
| 817 | NEW | 0 | 90 |  |
| 818 | NEW | 0 | 595 |  |
| 819 | NEW | 0 | 360 |  |
| 820 | NEW | 6 | 100 |  |
| 821 | NEW | 6000 | 255 |  |
| 822 | NEW | 6000 | 595 |  |
| 823 | NEW | 560 | 800 |  |
| 824 | NEW | 450 | 0 |  |
| 826 | NEW | 0 | 1024 |  |
| 827 | NEW | 0 | 90 |  |
| 828 | NEW | 0 | 595 |  |
| 829 | NEW | 0 | 360 |  |
| 830 | NEW | 518 | 100 |  |
| 831 | NEW | 1405 | 255 |  |
| 832 | NEW | 13620 | 595 |  |
| 833 | NEW | 12849 | 800 |  |
| 834 | NEW | 14134 | 0 |  |
| 835 | NEW | 12592 | 0 |  |
| 836 | NEW | 14385 | 1024 |  |
| 837 | NEW | 1876 | 90 |  |
| 838 | NEW | 0 | 595 |  |
| 839 | NEW | 0 | 360 |  |
| 840 | NEW | 1215 | 100 |  |
| 841 | NEW | 1222 | 255 |  |
| 842 | NEW | 2560 | 595 |  |
| 843 | NEW | 37729 | 800 |  |
| 844 | NEW | 14134 | 0 |  |
| 845 | NEW | 12592 | 0 |  |
| 846 | NEW | 14385 | 1024 |  |
| 847 | NEW | 1876 | 90 |  |
| 848 | NEW | 0 | 595 |  |
| 849 | NEW | 0 | 360 |  |

## Complete Input Register Map (0-499)

### Input 0-39: Core Runtime Data

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 0 | KNOWN | 32 | 12 | device_status |
| 1 | KNOWN | 1 | 2654 | pv1_voltage |
| 2 | KNOWN | 1 | 4346 | pv2_voltage |
| 3 | KNOWN | 2 | 14 | pv3_voltage |
| 4 | KNOWN | 536 | 529 | battery_voltage |
| 5 | KNOWN | 25688 | 25682 | soc_soh_packed |
| 6 | NEW | 13568 | 9984 |  |
| 7 | KNOWN | 0 | 935 | pv1_power |
| 8 | KNOWN | 0 | 1485 | pv2_power |
| 9 | KNOWN | 0 | 0 | pv3_power |
| 10 | KNOWN | 1667 | 956 | charge_power |
| 11 | KNOWN | 0 | 0 | discharge_power |
| 12 | KNOWN | 2440 | 2448 | grid_voltage_r |
| 13 | KNOWN | 1 | 0 | grid_voltage_s |
| 14 | KNOWN | 0 | 0 | grid_voltage_t |
| 15 | KNOWN | 5998 | 5998 | grid_frequency |
| 16 | KNOWN | 0 | 1401 | inverter_power |
| 17 | KNOWN | 1701 | 0 | rectifier_power |
| 18 | KNOWN | 741 | 608 | inverter_rms_current_r |
| 19 | KNOWN | 1000 | 1000 | power_factor |
| 20 | KNOWN | 2439 | 2445 | eps_voltage_r |
| 21 | KNOWN | 0 | 0 | eps_voltage_s |
| 22 | KNOWN | 160 | 0 | eps_voltage_t |
| 23 | KNOWN | 5997 | 5998 | eps_frequency |
| 24 | KNOWN | 0 | 0 | eps_power |
| 25 | KNOWN | 0 | 0 | eps_apparent_power |
| 26 | KNOWN | 0 | 100 | power_to_grid |
| 27 | KNOWN | 0 | 0 | power_to_user |
| 28 | KNOWN | 0 | 36 | pv1_energy_today |
| 29 | KNOWN | 0 | 81 | pv2_energy_today |
| 30 | KNOWN | 0 | 0 | pv3_energy_today |
| 31 | KNOWN | 0 | 69 | inverter_energy_today |
| 32 | KNOWN | 99 | 44 | ac_charge_energy_today |
| 33 | KNOWN | 98 | 88 | charge_energy_today |
| 34 | KNOWN | 0 | 0 | discharge_energy_today |
| 35 | KNOWN | 0 | 0 | eps_energy_today |
| 36 | KNOWN | 68 | 53 | grid_export_energy_today |
| 37 | KNOWN | 343 | 371 | grid_import_energy_today |
| 38 | KNOWN | 3753 | 4421 | bus_voltage_1 |
| 39 | KNOWN | 3277 | 3227 | bus_voltage_2 |

### Input 40-79: Energy Totals and Status

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 40 | KNOWN | 14718 | 8127 | pv1_energy_total |
| 42 | KNOWN | 5275 | 16859 | pv2_energy_total |
| 44 | KNOWN | 984 | 3 | pv3_energy_total |
| 46 | KNOWN | 54479 | 26166 | inverter_energy_total |
| 48 | KNOWN | 42808 | 3399 | ac_charge_energy_total |
| 50 | KNOWN | 50836 | 9336 | charge_energy_total |
| 52 | KNOWN | 44183 | 8192 | discharge_energy_total |
| 54 | KNOWN | 7 | 0 | eps_energy_total |
| 56 | KNOWN | 32140 | 23411 | grid_export_energy_total |
| 57 | NEW | 1 | 0 |  |
| 58 | KNOWN | 16314 | 26175 | grid_import_energy_total |
| 59 | NEW | 2 | 0 |  |
| 60 | KNOWN | 0 | 0 | fault_code |
| 62 | KNOWN | 0 | 0 | warning_code |
| 64 | KNOWN | 33 | 30 | internal_temperature |
| 65 | KNOWN | 52 | 33 | radiator_temperature_1 |
| 66 | KNOWN | 39 | 34 | radiator_temperature_2 |
| 67 | KNOWN | 5 | 5 | battery_temperature |
| 68 | KNOWN | 0 | 0 | battery_control_temperature |
| 69 | KNOWN | 13177 | 25736 | running_time |
| 70 | NEW | 450 | 122 |  |
| 72 | KNOWN | 0 | 0 | pv1_current |
| 73 | KNOWN | 0 | 0 | pv2_current |
| 74 | KNOWN | 0 | 0 | pv3_current |
| 75 | KNOWN | 0 | 0 | battery_current_inv |
| 77 | KNOWN | 226 | 226 | ac_input_type |
| 78 | NEW | 4681 | 4818 |  |
| 79 | NEW | 769 | 769 |  |

### Input 80-120: BMS and Extended Status

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 80 | KNOWN | 6 | 6 | bms_battery_type |
| 81 | KNOWN | 6000 | 6000 | bms_charge_current_limit |
| 82 | KNOWN | 6000 | 6000 | bms_discharge_current_limit |
| 83 | KNOWN | 560 | 560 | bms_charge_voltage_ref |
| 84 | KNOWN | 450 | 450 | bms_discharge_cutoff |
| 85 | KNOWN | 0 | 0 | bms_status_0 |
| 86 | KNOWN | 0 | 0 | bms_status_1 |
| 87 | KNOWN | 0 | 0 | bms_status_2 |
| 88 | KNOWN | 0 | 0 | bms_status_3 |
| 89 | KNOWN | 0 | 0 | bms_status_4 |
| 90 | KNOWN | 192 | 192 | bms_status_5 |
| 91 | KNOWN | 0 | 0 | bms_status_6 |
| 92 | KNOWN | 0 | 0 | bms_status_7 |
| 93 | KNOWN | 0 | 0 | bms_status_8 |
| 94 | KNOWN | 0 | 0 | bms_status_9 |
| 95 | KNOWN | 3 | 3 | battery_status_inv |
| 96 | KNOWN | 3 | 3 | battery_parallel_count |
| 97 | KNOWN | 840 | 840 | battery_capacity_ah |
| 98 | KNOWN | 300 | 165 | battery_current_bms |
| 99 | KNOWN | 0 | 0 | bms_fault_code |
| 100 | KNOWN | 0 | 0 | bms_warning_code |
| 101 | KNOWN | 3359 | 3316 | bms_max_cell_voltage |
| 102 | KNOWN | 3354 | 3311 | bms_min_cell_voltage |
| 103 | KNOWN | 220 | 210 | bms_max_cell_temperature |
| 104 | KNOWN | 200 | 200 | bms_min_cell_temperature |
| 105 | KNOWN | 0 | 0 | bms_fw_update_state |
| 106 | KNOWN | 152 | 67 | bms_cycle_count |
| 107 | KNOWN | 538 | 531 | battery_voltage_inv_sample |
| 108 | KNOWN | 310 | 295 | temperature_t1 |
| 109 | KNOWN | 0 | 0 | temperature_t2 |
| 110 | KNOWN | 0 | 0 | temperature_t3 |
| 111 | KNOWN | 0 | 0 | temperature_t4 |
| 112 | KNOWN | 0 | 0 | temperature_t5 |
| 113 | KNOWN | 518 | 517 | parallel_config |
| 114 | NEW | 1475 | 0 |  |
| 115 | NEW | 13620 | 12853 |  |
| 116 | NEW | 12849 | 13368 |  |
| 117 | NEW | 14134 | 20530 |  |
| 118 | NEW | 12592 | 13616 |  |
| 119 | NEW | 14385 | 12600 |  |
| 120 | NEW | 1878 | 2191 |  |

### Input 121-175: Generator, EPS, Load Data

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 121 | KNOWN | 0 | 0 | generator_voltage |
| 122 | KNOWN | 0 | 0 | generator_frequency |
| 123 | KNOWN | 1702 | 1774 | generator_power |
| 124 | KNOWN | 117 | 116 | generator_energy_today |
| 125 | KNOWN | 56126 | 23102 | generator_energy_total |
| 126 | NEW | 1 | 0 |  |
| 127 | KNOWN | 1213 | 1222 | eps_l1_voltage |
| 128 | KNOWN | 1220 | 1221 | eps_l2_voltage |
| 129 | KNOWN | 0 | 0 | eps_l1_power |
| 130 | KNOWN | 0 | 0 | eps_l2_power |
| 131 | KNOWN | 0 | 0 | eps_l1_apparent_power |
| 132 | KNOWN | 0 | 0 | eps_l2_apparent_power |
| 133 | KNOWN | 0 | 0 | eps_l1_energy_today |
| 134 | KNOWN | 0 | 0 | eps_l2_energy_today |
| 135 | KNOWN | 7 | 0 | eps_l1_energy_total |
| 137 | KNOWN | 7 | 0 | eps_l2_energy_total |
| 139 | NEW | 598 | 538 |  |
| 140 | NEW | 1211 | 1214 |  |
| 141 | NEW | 1218 | 1220 |  |
| 142 | NEW | 2560 | 100 |  |
| 143 | NEW | 9238 | 557 |  |
| 144 | NEW | 1543 | 376 |  |
| 145 | NEW | 12544 | 12072 |  |
| 148 | NEW | 1 | 257 |  |
| 151 | NEW | 2 | 2 |  |
| 153 | KNOWN | 1708 | 0 | ac_couple_power |
| 170 | KNOWN | 1440 | 1490 | output_power |
| 171 | KNOWN | 368 | 0 | load_energy_today |
| 172 | KNOWN | 5827 | 1429 | load_energy_total |
| 173 | NEW | 3 | 0 |  |
| 174 | NEW | 2 | 1 |  |

### Input 176-260: Extended Runtime

| Addr | Status | 18kPV | FB21 | Known Names |
|------|--------|-------|------|-------------|
| 190 | KNOWN | 0 | 0 | inverter_rms_current_s |
| 191 | KNOWN | 0 | 0 | inverter_rms_current_t |
| 193 | KNOWN | 0 | 0 | grid_l1_voltage |
| 194 | KNOWN | 0 | 0 | grid_l2_voltage |
| 195 | KNOWN | 0 | 0 | generator_l1_voltage |
| 196 | KNOWN | 0 | 0 | generator_l2_voltage |
| 197 | KNOWN | 0 | 0 | inverter_power_l1 |
| 198 | KNOWN | 0 | 0 | inverter_power_l2 |
| 199 | KNOWN | 0 | 0 | rectifier_power_l1 |
| 200 | KNOWN | 0 | 0 | rectifier_power_l2 |
| 201 | KNOWN | 0 | 0 | grid_export_power_l1 |
| 202 | KNOWN | 0 | 0 | grid_export_power_l2 |
| 203 | KNOWN | 0 | 0 | grid_import_power_l1 |
| 204 | KNOWN | 0 | 0 | grid_import_power_l2 |
| 210 | KNOWN | 0 | 0 | quick_charge_remaining_seconds |
| 217 | KNOWN | 0 | 0 | pv4_voltage |
| 218 | KNOWN | 0 | 0 | pv5_voltage |
| 219 | KNOWN | 0 | 0 | pv6_voltage |
| 220 | KNOWN | 0 | 0 | pv4_power |
| 221 | KNOWN | 0 | 0 | pv5_power |
| 222 | KNOWN | 0 | 0 | pv6_power |
| 223 | KNOWN | 0 | 0 | epv4_day |
| 224 | KNOWN | 0 | 0 | epv4_all |
| 226 | KNOWN | 0 | 0 | epv5_day |
| 227 | KNOWN | 0 | 0 | epv5_all |
| 229 | KNOWN | 0 | 0 | epv6_day |
| 230 | KNOWN | 0 | 0 | epv6_all |
| 232 | KNOWN | 0 | 0 | smart_load_power |
| 241 | NEW | 1 | 1 |  |
| 242 | NEW | 300 | 300 |  |
| 244 | NEW | 1 | 1 |  |
| 245 | NEW | 512 | 512 |  |
| 252 | NEW | 240 | 240 |  |
| 253 | NEW | 5 | 5 |  |
| 254 | NEW | 20 | 20 |  |
| 257 | NEW | 15127 | 15127 |  |
| 260 | NEW | 550 | 550 |  |

## Battery Input Registers (5000-5121)

| Addr | Status | 18kPV | FB21 | Name |
|------|--------|-------|------|------|
| 5002 | KNOWN | 49155 | 49155 | bat0_status_header |
| 5003 | KNOWN | 280 | 280 | bat0_full_capacity_ah |
| 5004 | KNOWN | 560 | 560 | bat0_charge_voltage_ref |
| 5005 | KNOWN | 2000 | 2000 | bat0_charge_current_limit |
| 5006 | KNOWN | 2000 | 2000 | bat0_discharge_current_limit |
| 5007 | KNOWN | 450 | 450 | bat0_discharge_voltage_cutoff |
| 5008 | KNOWN | 5371 | 5303 | bat0_voltage |
| 5009 | KNOWN | 123 | 57 | bat0_current |
| 5010 | KNOWN | 25687 | 25681 | bat0_soc_soh_packed |
| 5011 | KNOWN | 152 | 67 | bat0_cycle_count |
| 5012 | KNOWN | 220 | 210 | bat0_max_cell_temp |
| 5013 | KNOWN | 210 | 200 | bat0_min_cell_temp |
| 5014 | KNOWN | 3358 | 3316 | bat0_max_cell_voltage |
| 5015 | KNOWN | 3355 | 3313 | bat0_min_cell_voltage |
| 5016 | KNOWN | 514 | 259 | bat0_cell_num_voltage_packed |
| 5017 | KNOWN | 264 | 258 | bat0_cell_num_temp_packed |
| 5018 | KNOWN | 529 | 529 | bat0_firmware_version |
| 5019 | KNOWN | 24898 | 24898 | bat0_serial_0 |
| 5020 | KNOWN | 29812 | 29812 | bat0_serial_1 |
| 5021 | KNOWN | 29285 | 29285 | bat0_serial_2 |
| 5022 | KNOWN | 24441 | 24441 | bat0_serial_3 |
| 5023 | KNOWN | 17481 | 17481 | bat0_serial_4 |
| 5024 | KNOWN | 12383 | 12383 | bat0_serial_5 |
| 5025 | KNOWN | 49 | 49 | bat0_serial_6 |
| 5026 | KNOWN | 0 | 0 | bat0_serial_7 |
| 5032 | KNOWN | 49155 | 49155 | bat1_status_header |
| 5033 | KNOWN | 280 | 280 | bat1_full_capacity_ah |
| 5034 | KNOWN | 560 | 560 | bat1_charge_voltage_ref |
| 5035 | KNOWN | 2000 | 2000 | bat1_charge_current_limit |
| 5036 | KNOWN | 2000 | 2000 | bat1_discharge_current_limit |
| 5037 | KNOWN | 450 | 450 | bat1_discharge_voltage_cutoff |
| 5038 | KNOWN | 5369 | 5299 | bat1_voltage |
| 5039 | KNOWN | 99 | 55 | bat1_current |
| 5040 | KNOWN | 25684 | 25682 | bat1_soc_soh_packed |
| 5041 | KNOWN | 139 | 61 | bat1_cycle_count |
| 5042 | KNOWN | 210 | 200 | bat1_max_cell_temp |
| 5043 | KNOWN | 210 | 200 | bat1_min_cell_temp |
| 5044 | KNOWN | 3358 | 3313 | bat1_max_cell_voltage |
| 5045 | KNOWN | 3354 | 3311 | bat1_min_cell_voltage |
| 5046 | KNOWN | 771 | 1028 | bat1_cell_num_voltage_packed |
| 5047 | KNOWN | 257 | 771 | bat1_cell_num_temp_packed |
| 5048 | KNOWN | 529 | 529 | bat1_firmware_version |
| 5049 | KNOWN | 24898 | 24898 | bat1_serial_0 |
| 5050 | KNOWN | 29812 | 29812 | bat1_serial_1 |
| 5051 | KNOWN | 29285 | 29285 | bat1_serial_2 |
| 5052 | KNOWN | 24441 | 24441 | bat1_serial_3 |
| 5053 | KNOWN | 17481 | 17481 | bat1_serial_4 |
| 5054 | KNOWN | 12383 | 12383 | bat1_serial_5 |
| 5055 | KNOWN | 50 | 50 | bat1_serial_6 |
| 5056 | KNOWN | 256 | 256 | bat1_serial_7 |
| 5062 | KNOWN | 49155 | 49155 | bat2_status_header |
| 5063 | KNOWN | 280 | 280 | bat2_full_capacity_ah |
| 5064 | KNOWN | 560 | 560 | bat2_charge_voltage_ref |
| 5065 | KNOWN | 2000 | 2000 | bat2_charge_current_limit |
| 5066 | KNOWN | 2000 | 2000 | bat2_discharge_current_limit |
| 5067 | KNOWN | 450 | 450 | bat2_discharge_voltage_cutoff |
| 5068 | KNOWN | 5369 | 5300 | bat2_voltage |
| 5069 | KNOWN | 90 | 51 | bat2_current |
| 5070 | KNOWN | 25692 | 25683 | bat2_soc_soh_packed |
| 5071 | KNOWN | 109 | 55 | bat2_cycle_count |
| 5072 | KNOWN | 210 | 200 | bat2_max_cell_temp |
| 5073 | KNOWN | 200 | 200 | bat2_min_cell_temp |
| 5074 | KNOWN | 3357 | 3313 | bat2_max_cell_voltage |
| 5075 | KNOWN | 3355 | 3311 | bat2_min_cell_voltage |
| 5076 | KNOWN | 0 | 0 | bat2_cell_num_voltage_packed |
| 5077 | KNOWN | 1027 | 522 | bat2_cell_num_temp_packed |
| 5078 | KNOWN | 529 | 529 | bat2_firmware_version |
| 5079 | KNOWN | 24898 | 24898 | bat2_serial_0 |
| 5080 | KNOWN | 29812 | 29812 | bat2_serial_1 |
| 5081 | KNOWN | 29285 | 29285 | bat2_serial_2 |
| 5082 | KNOWN | 24441 | 24441 | bat2_serial_3 |
| 5083 | KNOWN | 17481 | 17481 | bat2_serial_4 |
| 5084 | KNOWN | 12383 | 12383 | bat2_serial_5 |
| 5085 | KNOWN | 51 | 51 | bat2_serial_6 |
| 5086 | KNOWN | 512 | 512 | bat2_serial_7 |
| 5092 | KNOWN | 0 | 0 | bat3_status_header |
| 5093 | KNOWN | 0 | 0 | bat3_full_capacity_ah |
| 5094 | KNOWN | 0 | 0 | bat3_charge_voltage_ref |
| 5095 | KNOWN | 0 | 0 | bat3_charge_current_limit |
| 5096 | KNOWN | 0 | 0 | bat3_discharge_current_limit |
| 5097 | KNOWN | 0 | 0 | bat3_discharge_voltage_cutoff |
| 5098 | KNOWN | 0 | 0 | bat3_voltage |
| 5099 | KNOWN | 0 | 0 | bat3_current |
| 5100 | KNOWN | 0 | 0 | bat3_soc_soh_packed |
| 5101 | KNOWN | 0 | 0 | bat3_cycle_count |
| 5102 | KNOWN | 0 | 0 | bat3_max_cell_temp |
| 5103 | KNOWN | 0 | 0 | bat3_min_cell_temp |
| 5104 | KNOWN | 0 | 0 | bat3_max_cell_voltage |
| 5105 | KNOWN | 0 | 0 | bat3_min_cell_voltage |
| 5106 | KNOWN | 0 | 0 | bat3_cell_num_voltage_packed |
| 5107 | KNOWN | 0 | 0 | bat3_cell_num_temp_packed |
| 5108 | KNOWN | 0 | 0 | bat3_firmware_version |
| 5109 | KNOWN | 0 | 0 | bat3_serial_0 |
| 5110 | KNOWN | 0 | 0 | bat3_serial_1 |
| 5111 | KNOWN | 0 | 0 | bat3_serial_2 |
| 5112 | KNOWN | 0 | 0 | bat3_serial_3 |
| 5113 | KNOWN | 0 | 0 | bat3_serial_4 |
| 5114 | KNOWN | 0 | 0 | bat3_serial_5 |
| 5115 | KNOWN | 0 | 0 | bat3_serial_6 |
| 5116 | KNOWN | 0 | 0 | bat3_serial_7 |

## Value Comparison: Registers Different Between Devices

Registers where both devices respond with different non-zero values.
These are either live data, model-specific config, or serial-number fields.

### Holding Registers (Different Values)

| Addr | 18kPV | FlexBOSS21 | Known Name |
|------|-------|------------|------------|
| 0 | 34496 (0x86C0) | 34304 (0x8600) |  |
| 1 | 9 (0x0009) | 265 (0x0109) |  |
| 2 | 13620 (0x3534) | 12853 (0x3235) |  |
| 3 | 12849 (0x3231) | 13368 (0x3438) |  |
| 4 | 14134 (0x3736) | 20530 (0x5032) |  |
| 5 | 12592 (0x3130) | 13616 (0x3530) |  |
| 6 | 14385 (0x3831) | 12600 (0x3138) |  |
| 7 | 16742 (0x4166) | 16710 (0x4146) |  |
| 14 | 8986 (0x231A) | 4123 (0x101B) |  |
| 19 | 2092 (0x082C) | 10284 (0x282C) | device_type_code |
| 20 | 0 (0x0000) | 4 (0x0004) | pv_input_mode |
| 22 | 2000 (0x07D0) | 1400 (0x0578) | pv_start_voltage |
| 64 | 6 (0x0006) | 80 (0x0050) | charge_power_percent |
| 72 | 0 (0x0000) | 21 (0x0015) | ac_charge_enable_period_1 |
| 74 | 120 (0x0078) | 10 (0x000A) | forced_charge_power_command |
| 112 | 2 (0x0002) | 1 (0x0001) | system_type |
| 137 | 1421 (0x058D) | 1405 (0x057D) |  |
| 159 | 590 (0x024E) | 560 (0x0230) | ac_charge_end_voltage |
| 224 | 786 (0x0312) | 0 (0x0000) |  |
| 612 | 0 (0x0000) | 1 (0x0001) |  |
| 613 | 0 (0x0000) | 257 (0x0101) |  |
| 614 | 0 (0x0000) | 1 (0x0001) |  |
| 615 | 0 (0x0000) | 60040 (0xEA88) |  |
| 616 | 0 (0x0000) | 100 (0x0064) |  |
| 617 | 0 (0x0000) | 65486 (0xFFCE) |  |
| 618 | 0 (0x0000) | 400 (0x0190) |  |
| 624 | 0 (0x0000) | 6304 (0x18A0) |  |
| 625 | 0 (0x0000) | 20 (0x0014) |  |
| 637 | 1422 (0x058E) | 1406 (0x057E) |  |
| 659 | 590 (0x024E) | 560 (0x0230) |  |
| 724 | 786 (0x0312) | 0 (0x0000) |  |
| 734 | 786 (0x0312) | 0 (0x0000) |  |
| 744 | 786 (0x0312) | 0 (0x0000) |  |
| 754 | 786 (0x0312) | 0 (0x0000) |  |
| 764 | 786 (0x0312) | 0 (0x0000) |  |
| 774 | 786 (0x0312) | 0 (0x0000) |  |
| 784 | 786 (0x0312) | 0 (0x0000) |  |
| 790 | 32 (0x0020) | 100 (0x0064) |  |
| 791 | 1 (0x0001) | 255 (0x00FF) |  |
| 792 | 1 (0x0001) | 595 (0x0253) |  |
| 793 | 3 (0x0003) | 800 (0x0320) |  |
| 794 | 537 (0x0219) | 0 (0x0000) |  |
| 795 | 25687 (0x6457) | 0 (0x0000) |  |
| 796 | 13568 (0x3500) | 1024 (0x0400) |  |
| 797 | 0 (0x0000) | 90 (0x005A) |  |
| 798 | 0 (0x0000) | 595 (0x0253) |  |
| 799 | 0 (0x0000) | 360 (0x0168) |  |
| 800 | 99 (0x0063) | 100 (0x0064) |  |
| 801 | 98 (0x0062) | 255 (0x00FF) |  |
| 802 | 0 (0x0000) | 595 (0x0253) |  |
| 803 | 0 (0x0000) | 800 (0x0320) |  |
| 804 | 68 (0x0044) | 0 (0x0000) |  |
| 805 | 343 (0x0157) | 0 (0x0000) |  |
| 806 | 3750 (0x0EA6) | 1024 (0x0400) |  |
| 807 | 3277 (0x0CCD) | 90 (0x005A) |  |
| 808 | 14718 (0x397E) | 595 (0x0253) |  |
| 809 | 0 (0x0000) | 360 (0x0168) |  |
| 810 | 33 (0x0021) | 100 (0x0064) |  |
| 811 | 52 (0x0034) | 255 (0x00FF) |  |
| 812 | 38 (0x0026) | 595 (0x0253) |  |
| 813 | 5 (0x0005) | 800 (0x0320) |  |
| 815 | 13121 (0x3341) | 0 (0x0000) |  |
| 816 | 450 (0x01C2) | 1024 (0x0400) |  |
| 817 | 0 (0x0000) | 90 (0x005A) |  |
| 818 | 0 (0x0000) | 595 (0x0253) |  |
| 819 | 0 (0x0000) | 360 (0x0168) |  |
| 820 | 6 (0x0006) | 100 (0x0064) |  |
| 821 | 6000 (0x1770) | 255 (0x00FF) |  |
| 822 | 6000 (0x1770) | 595 (0x0253) |  |
| 823 | 560 (0x0230) | 800 (0x0320) |  |
| 824 | 450 (0x01C2) | 0 (0x0000) |  |
| 826 | 0 (0x0000) | 1024 (0x0400) |  |
| 827 | 0 (0x0000) | 90 (0x005A) |  |
| 828 | 0 (0x0000) | 595 (0x0253) |  |
| 829 | 0 (0x0000) | 360 (0x0168) |  |
| 830 | 518 (0x0206) | 100 (0x0064) |  |
| 831 | 1405 (0x057D) | 255 (0x00FF) |  |
| 832 | 13620 (0x3534) | 595 (0x0253) |  |
| 833 | 12849 (0x3231) | 800 (0x0320) |  |
| 834 | 14134 (0x3736) | 0 (0x0000) |  |
| 835 | 12592 (0x3130) | 0 (0x0000) |  |
| 836 | 14385 (0x3831) | 1024 (0x0400) |  |
| 837 | 1876 (0x0754) | 90 (0x005A) |  |
| 838 | 0 (0x0000) | 595 (0x0253) |  |
| 839 | 0 (0x0000) | 360 (0x0168) |  |
| 840 | 1215 (0x04BF) | 100 (0x0064) |  |
| 841 | 1222 (0x04C6) | 255 (0x00FF) |  |
| 842 | 2560 (0x0A00) | 595 (0x0253) |  |
| 843 | 37729 (0x9361) | 800 (0x0320) |  |
| 844 | 14134 (0x3736) | 0 (0x0000) |  |
| 845 | 12592 (0x3130) | 0 (0x0000) |  |
| 846 | 14385 (0x3831) | 1024 (0x0400) |  |
| 847 | 1876 (0x0754) | 90 (0x005A) |  |
| 848 | 0 (0x0000) | 595 (0x0253) |  |
| 849 | 0 (0x0000) | 360 (0x0168) |  |

### Input Registers (Different Values)

| Addr | 18kPV | FlexBOSS21 | Known Name |
|------|-------|------------|------------|
| 0 | 32 (0x0020) | 12 (0x000C) | device_status |
| 1 | 1 (0x0001) | 2654 (0x0A5E) | pv1_voltage |
| 2 | 1 (0x0001) | 4346 (0x10FA) | pv2_voltage |
| 3 | 2 (0x0002) | 14 (0x000E) | pv3_voltage |
| 4 | 536 (0x0218) | 529 (0x0211) | battery_voltage |
| 5 | 25688 (0x6458) | 25682 (0x6452) | soc_soh_packed |
| 6 | 13568 (0x3500) | 9984 (0x2700) |  |
| 7 | 0 (0x0000) | 935 (0x03A7) | pv1_power |
| 8 | 0 (0x0000) | 1485 (0x05CD) | pv2_power |
| 10 | 1667 (0x0683) | 956 (0x03BC) | charge_power |
| 12 | 2440 (0x0988) | 2448 (0x0990) | grid_voltage_r |
| 13 | 1 (0x0001) | 0 (0x0000) | grid_voltage_s |
| 16 | 0 (0x0000) | 1401 (0x0579) | inverter_power |
| 17 | 1701 (0x06A5) | 0 (0x0000) | rectifier_power |
| 18 | 741 (0x02E5) | 608 (0x0260) | inverter_rms_current_r |
| 20 | 2439 (0x0987) | 2445 (0x098D) | eps_voltage_r |
| 22 | 160 (0x00A0) | 0 (0x0000) | eps_voltage_t |
| 23 | 5997 (0x176D) | 5998 (0x176E) | eps_frequency |
| 26 | 0 (0x0000) | 100 (0x0064) | power_to_grid |
| 28 | 0 (0x0000) | 36 (0x0024) | pv1_energy_today |
| 29 | 0 (0x0000) | 81 (0x0051) | pv2_energy_today |
| 31 | 0 (0x0000) | 69 (0x0045) | inverter_energy_today |
| 32 | 99 (0x0063) | 44 (0x002C) | ac_charge_energy_today |
| 33 | 98 (0x0062) | 88 (0x0058) | charge_energy_today |
| 36 | 68 (0x0044) | 53 (0x0035) | grid_export_energy_today |
| 37 | 343 (0x0157) | 371 (0x0173) | grid_import_energy_today |
| 38 | 3753 (0x0EA9) | 4421 (0x1145) | bus_voltage_1 |
| 39 | 3277 (0x0CCD) | 3227 (0x0C9B) | bus_voltage_2 |
| 40 | 14718 (0x397E) | 8127 (0x1FBF) | pv1_energy_total |
| 42 | 5275 (0x149B) | 16859 (0x41DB) | pv2_energy_total |
| 44 | 984 (0x03D8) | 3 (0x0003) | pv3_energy_total |
| 46 | 54479 (0xD4CF) | 26166 (0x6636) | inverter_energy_total |
| 48 | 42808 (0xA738) | 3399 (0x0D47) | ac_charge_energy_total |
| 50 | 50836 (0xC694) | 9336 (0x2478) | charge_energy_total |
| 52 | 44183 (0xAC97) | 8192 (0x2000) | discharge_energy_total |
| 54 | 7 (0x0007) | 0 (0x0000) | eps_energy_total |
| 56 | 32140 (0x7D8C) | 23411 (0x5B73) | grid_export_energy_total |
| 57 | 1 (0x0001) | 0 (0x0000) |  |
| 58 | 16314 (0x3FBA) | 26175 (0x663F) | grid_import_energy_total |
| 59 | 2 (0x0002) | 0 (0x0000) |  |
| 64 | 33 (0x0021) | 30 (0x001E) | internal_temperature |
| 65 | 52 (0x0034) | 33 (0x0021) | radiator_temperature_1 |
| 66 | 39 (0x0027) | 34 (0x0022) | radiator_temperature_2 |
| 69 | 13177 (0x3379) | 25736 (0x6488) | running_time |
| 70 | 450 (0x01C2) | 122 (0x007A) |  |
| 78 | 4681 (0x1249) | 4818 (0x12D2) |  |
| 98 | 300 (0x012C) | 165 (0x00A5) | battery_current_bms |
| 101 | 3359 (0x0D1F) | 3316 (0x0CF4) | bms_max_cell_voltage |
| 102 | 3354 (0x0D1A) | 3311 (0x0CEF) | bms_min_cell_voltage |
| 103 | 220 (0x00DC) | 210 (0x00D2) | bms_max_cell_temperature |
| 106 | 152 (0x0098) | 67 (0x0043) | bms_cycle_count |
| 107 | 538 (0x021A) | 531 (0x0213) | battery_voltage_inv_sample |
| 108 | 310 (0x0136) | 295 (0x0127) | temperature_t1 |
| 113 | 518 (0x0206) | 517 (0x0205) | parallel_config |
| 114 | 1475 (0x05C3) | 0 (0x0000) |  |
| 115 | 13620 (0x3534) | 12853 (0x3235) |  |
| 116 | 12849 (0x3231) | 13368 (0x3438) |  |
| 117 | 14134 (0x3736) | 20530 (0x5032) |  |
| 118 | 12592 (0x3130) | 13616 (0x3530) |  |
| 119 | 14385 (0x3831) | 12600 (0x3138) |  |
| 120 | 1878 (0x0756) | 2191 (0x088F) |  |
| 123 | 1702 (0x06A6) | 1774 (0x06EE) | generator_power |
| 124 | 117 (0x0075) | 116 (0x0074) | generator_energy_today |
| 125 | 56126 (0xDB3E) | 23102 (0x5A3E) | generator_energy_total |
| 126 | 1 (0x0001) | 0 (0x0000) |  |
| 127 | 1213 (0x04BD) | 1222 (0x04C6) | eps_l1_voltage |
| 128 | 1220 (0x04C4) | 1221 (0x04C5) | eps_l2_voltage |
| 135 | 7 (0x0007) | 0 (0x0000) | eps_l1_energy_total |
| 137 | 7 (0x0007) | 0 (0x0000) | eps_l2_energy_total |
| 139 | 598 (0x0256) | 538 (0x021A) |  |
| 140 | 1211 (0x04BB) | 1214 (0x04BE) |  |
| 141 | 1218 (0x04C2) | 1220 (0x04C4) |  |
| 142 | 2560 (0x0A00) | 100 (0x0064) |  |
| 143 | 9238 (0x2416) | 557 (0x022D) |  |
| 144 | 1543 (0x0607) | 376 (0x0178) |  |
| 145 | 12544 (0x3100) | 12072 (0x2F28) |  |
| 148 | 1 (0x0001) | 257 (0x0101) |  |
| 153 | 1708 (0x06AC) | 0 (0x0000) | ac_couple_power |
| 170 | 1440 (0x05A0) | 1490 (0x05D2) | output_power |
| 171 | 368 (0x0170) | 0 (0x0000) | load_energy_today |
| 172 | 5827 (0x16C3) | 1429 (0x0595) | load_energy_total |
| 173 | 3 (0x0003) | 0 (0x0000) |  |
| 174 | 2 (0x0002) | 1 (0x0001) |  |
| 5008 | 5371 (0x14FB) | 5303 (0x14B7) | bat0_voltage |
| 5009 | 123 (0x007B) | 57 (0x0039) | bat0_current |
| 5010 | 25687 (0x6457) | 25681 (0x6451) | bat0_soc_soh_packed |
| 5011 | 152 (0x0098) | 67 (0x0043) | bat0_cycle_count |
| 5012 | 220 (0x00DC) | 210 (0x00D2) | bat0_max_cell_temp |
| 5013 | 210 (0x00D2) | 200 (0x00C8) | bat0_min_cell_temp |
| 5014 | 3358 (0x0D1E) | 3316 (0x0CF4) | bat0_max_cell_voltage |
| 5015 | 3355 (0x0D1B) | 3313 (0x0CF1) | bat0_min_cell_voltage |
| 5016 | 514 (0x0202) | 259 (0x0103) | bat0_cell_num_voltage_packed |
| 5017 | 264 (0x0108) | 258 (0x0102) | bat0_cell_num_temp_packed |
| 5038 | 5369 (0x14F9) | 5299 (0x14B3) | bat1_voltage |
| 5039 | 99 (0x0063) | 55 (0x0037) | bat1_current |
| 5040 | 25684 (0x6454) | 25682 (0x6452) | bat1_soc_soh_packed |
| 5041 | 139 (0x008B) | 61 (0x003D) | bat1_cycle_count |
| 5042 | 210 (0x00D2) | 200 (0x00C8) | bat1_max_cell_temp |
| 5043 | 210 (0x00D2) | 200 (0x00C8) | bat1_min_cell_temp |
| 5044 | 3358 (0x0D1E) | 3313 (0x0CF1) | bat1_max_cell_voltage |
| 5045 | 3354 (0x0D1A) | 3311 (0x0CEF) | bat1_min_cell_voltage |
| 5046 | 771 (0x0303) | 1028 (0x0404) | bat1_cell_num_voltage_packed |
| 5047 | 257 (0x0101) | 771 (0x0303) | bat1_cell_num_temp_packed |
| 5068 | 5369 (0x14F9) | 5300 (0x14B4) | bat2_voltage |
| 5069 | 90 (0x005A) | 51 (0x0033) | bat2_current |
| 5070 | 25692 (0x645C) | 25683 (0x6453) | bat2_soc_soh_packed |
| 5071 | 109 (0x006D) | 55 (0x0037) | bat2_cycle_count |
| 5072 | 210 (0x00D2) | 200 (0x00C8) | bat2_max_cell_temp |
| 5074 | 3357 (0x0D1D) | 3313 (0x0CF1) | bat2_max_cell_voltage |
| 5075 | 3355 (0x0D1B) | 3311 (0x0CEF) | bat2_min_cell_voltage |
| 5077 | 1027 (0x0403) | 522 (0x020A) | bat2_cell_num_temp_packed |

## Extended Range Results

### Holding 1000-2100 (18kPV only)
**Result**: No registers responded. The 18kPV firmware does not use extended holding register addresses.

### Input 1000-2100 (18kPV only)
**Result**: No registers responded. The 18kPV firmware does not use extended input register addresses.
