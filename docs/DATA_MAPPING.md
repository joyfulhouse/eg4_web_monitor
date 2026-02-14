# EG4 Web Monitor - Data Mapping Reference

> **Canonical reference** for how raw data (Modbus registers and Cloud API responses)
> flows through `pylxpweb` and the `eg4_web_monitor` integration to produce Home
> Assistant sensor entities.
>
> **Consult this document** whenever working with register-to-sensor or
> API-to-sensor mappings.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Inverter Input Registers](#2-inverter-input-registers)
3. [Inverter Holding Registers (Parameters)](#3-inverter-holding-registers-parameters)
4. [GridBOSS Input Registers](#4-gridboss-input-registers)
5. [GridBOSS Holding Register 20 (Smart Port Status)](#5-gridboss-holding-register-20-smart-port-status)
6. [Cloud API Field Mappings](#6-cloud-api-field-mappings)
7. [Individual Battery Data](#7-individual-battery-data)
8. [Parallel Group Data](#8-parallel-group-data)
9. [Computed / Derived Sensor Keys](#9-computed--derived-sensor-keys)
10. [Mode Differences](#10-mode-differences)
11. [Smart Port Sensor Filtering](#11-smart-port-sensor-filtering)
12. [GridBOSS CT Overlay](#12-gridboss-ct-overlay)
13. [Entity Counts by Mode](#13-entity-counts-by-mode)
14. [Key Constants Reference](#14-key-constants-reference)
15. [All Calculations Reference](#15-all-calculations-reference)
16. [Data Validation](#1514-data-validation-two-layer-architecture)

---

## 1. Architecture Overview

### Data Flow (LOCAL / Modbus)

```
Modbus Register Read (function codes 0x03/0x04)
    |
    v
pylxpweb: _canonical_reader.py → read_raw() / read_scaled()
    |
    v
pylxpweb: data.py → InverterRuntimeData.from_modbus_registers()
                   → InverterEnergyData.from_modbus_registers()
                   → BatteryBankData / BatteryData
                   → MidboxRuntimeData.from_modbus_registers()
    |
    v
eg4_web_monitor: coordinator_mappings.py
    → _build_runtime_sensor_mapping(runtime_data)
    → _build_energy_sensor_mapping(energy_data)
    → _build_battery_bank_sensor_mapping(battery_data)
    → _build_individual_battery_mapping(battery)
    → _build_gridboss_sensor_mapping(mid_device)
    |
    v
Sensor Dict {sensor_key: value}  →  Home Assistant Entity
```

### Data Flow (CLOUD / HTTP)

```
Cloud API HTTP POST → JSON Response
    |
    v
pylxpweb: LuxpowerClient → JSON dict
    |
    v
eg4_web_monitor: coordinator_http.py
    → _map_device_properties(json_dict, FIELD_MAPPING)
    → const/sensors/mappings.py → INVERTER_RUNTIME_FIELD_MAPPING
                                → GRIDBOSS_FIELD_MAPPING
                                → PARALLEL_GROUP_FIELD_MAPPING
    → Applies scaling (÷10, ÷100) per DIVIDE_BY_10_SENSORS etc.
    |
    v
Sensor Dict {sensor_key: value}  →  Home Assistant Entity
```

### Data Flow (HYBRID)

```
LOCAL (Modbus) data  ─────────────┐
                                  ├──→  Merged Sensor Dict
CLOUD (HTTP) data  ───────────────┘
                                  |
                                  v
    apply_gridboss_overlay() merges GridBOSS CT data onto parallel group
                                  |
                                  v
                            Home Assistant Entity
```

### Layer Responsibilities

| Layer | Component | Responsibility |
|-------|-----------|----------------|
| **Transport** | pylxpweb `_register_data.py` | Read raw Modbus registers, group reads |
| **Canonical** | pylxpweb `_canonical_reader.py` | Apply scale factors, handle 32-bit pairs |
| **Data Model** | pylxpweb `data.py` | Transport-agnostic dataclasses (`InverterRuntimeData`, etc.) |
| **Field Maps** | pylxpweb `_field_mappings.py` | Canonical register name → data model field name |
| **HTTP Maps** | eg4_web_monitor `const/sensors/mappings.py` | Cloud API JSON field → HA sensor key |
| **Coordinator Maps** | eg4_web_monitor `coordinator_mappings.py` | Data model property → HA sensor key |
| **Sensor Platform** | eg4_web_monitor `sensor.py` | Sensor key → HA entity with metadata |

---

## 2. Inverter Input Registers

All input registers use Modbus function code 0x04 (read-only).

Definitions: `pylxpweb/registers/inverter_input.py` (canonical source of truth)

Mapping chain: Register → `_canonical_reader.read_scaled()` → `InverterRuntimeData` field
→ `_build_runtime_sensor_mapping()` → HA sensor key

### Runtime Registers (Read every refresh cycle)

| Reg | Canonical Name | Scale | Unit | pylxpweb Field | HA Sensor Key |
|-----|----------------|-------|------|----------------|---------------|
| 0 | `device_status` | 1 | - | `device_status` | `status_code` |
| 1 | `pv1_voltage` | ÷10 | V | `pv1_voltage` | `pv1_voltage` |
| 2 | `pv2_voltage` | ÷10 | V | `pv2_voltage` | `pv2_voltage` |
| 3 | `pv3_voltage` | ÷10 | V | `pv3_voltage` | `pv3_voltage` |
| 4 | `battery_voltage` | ÷10 | V | `battery_voltage` | `battery_voltage` |
| 5 | `soc_soh_packed` | 1 | % | `battery_soc` / `battery_soh` | `state_of_charge` |
| 7 | `pv1_power` | 1 | W | `pv1_power` | `pv1_power` |
| 8 | `pv2_power` | 1 | W | `pv2_power` | `pv2_power` |
| 9 | `pv3_power` | 1 | W | `pv3_power` | `pv3_power` |
| 10 | `charge_power` | 1 | W | `battery_charge_power` | `battery_charge_power` |
| 11 | `discharge_power` | 1 | W | `battery_discharge_power` | `battery_discharge_power` |
| 12 | `grid_voltage_r` | ÷10 | V | `grid_voltage_r` | `grid_voltage_r` |
| 13 | `grid_voltage_s` | ÷10 | V | `grid_voltage_s` | `grid_voltage_s` |
| 14 | `grid_voltage_t` | ÷10 | V | `grid_voltage_t` | `grid_voltage_t` |
| 15 | `grid_frequency` | ÷100 | Hz | `grid_frequency` | `grid_frequency` |
| 16 | `inverter_power` | 1 | W | `inverter_power` | `ac_power` |
| 17 | `rectifier_power` | 1 | W | `grid_power` | `grid_power` |
| 18 | `inverter_rms_current_r` | ÷100 | A | `inverter_rms_current_r` | `grid_current_l1` |
| 20 | `eps_voltage_r` | ÷10 | V | `eps_voltage_r` | `eps_voltage_r` |
| 21 | `eps_voltage_s` | ÷10 | V | `eps_voltage_s` | `eps_voltage_s` |
| 22 | `eps_voltage_t` | ÷10 | V | `eps_voltage_t` | `eps_voltage_t` |
| 23 | `eps_frequency` | ÷100 | Hz | `eps_frequency` | `eps_frequency` |
| 24 | `eps_power` | 1 | W | `eps_power` | `eps_power` |
| 26 | `power_to_grid` | 1 | W | `power_to_grid` | `grid_export_power` |
| 27 | `power_to_user` | 1 | W | `power_from_grid` | `grid_import_power` |

**Split-Phase Registers (EG4_HYBRID / EG4_OFFGRID only):**

| Reg | Canonical Name | Scale | Unit | pylxpweb Field | HA Sensor Key |
|-----|----------------|-------|------|----------------|---------------|
| 127 | `eps_l1_voltage` | ÷10 | V | `eps_l1_voltage` | `eps_voltage_l1` |
| 128 | `eps_l2_voltage` | ÷10 | V | `eps_l2_voltage` | `eps_voltage_l2` |
| 193 | `grid_l1_voltage` | ÷10 | V | `grid_l1_voltage` | `grid_voltage_l1` |
| 194 | `grid_l2_voltage` | ÷10 | V | `grid_l2_voltage` | `grid_voltage_l2` |

> **Note:** Regs 193-194 return 0 on 18kPV/FlexBOSS firmware. GridBOSS reads
> correct grid L1/L2 voltages from its own register map (regs 4-5).

**Three-Phase Registers (LXP only):**

| Reg | Canonical Name | Scale | Unit | pylxpweb Field | HA Sensor Key |
|-----|----------------|-------|------|----------------|---------------|
| 190 | `inverter_rms_current_s` | ÷100 | A | `inverter_rms_current_s` | `grid_current_l2` |
| 191 | `inverter_rms_current_t` | ÷100 | A | `inverter_rms_current_t` | `grid_current_l3` |

### Bus Voltage Registers

| Reg | Canonical Name | Scale | Unit | HA Sensor Key |
|-----|----------------|-------|------|---------------|
| 38 | `bus_voltage_1` | ÷10 | V | `bus1_voltage` |
| 39 | `bus_voltage_2` | ÷10 | V | `bus2_voltage` |

### Temperature Registers

| Reg | Canonical Name | Scale | Unit | HA Sensor Key |
|-----|----------------|-------|------|---------------|
| 64 | `internal_temperature` | 1 | C | `internal_temperature` |
| 65 | `radiator_temperature_1` | 1 | C | `radiator1_temperature` |
| 66 | `radiator_temperature_2` | 1 | C | `radiator2_temperature` |
| 67 | `battery_temperature` | 1 | C | `battery_temperature` |
| 108 | `temperature_t1` | ÷10 | C | `bt_temperature` |

> **Note:** `bt_temperature` (reg 108) is Modbus-only (not available via Cloud API).
> Available in LOCAL and HYBRID modes (overlaid via `_TRANSPORT_OVERLAY`).

### Energy Registers (Daily)

| Reg | Canonical Name | Scale | Unit | HA Sensor Key |
|-----|----------------|-------|------|---------------|
| 31 | `inverter_energy_today` | ÷10 | kWh | `yield` |
| 33 | `charge_energy_today` | ÷10 | kWh | `charging` |
| 34 | `discharge_energy_today` | ÷10 | kWh | `discharging` |
| 36 | `grid_export_energy_today` | ÷10 | kWh | `grid_export` |
| 37 | `grid_import_energy_today` | ÷10 | kWh | `grid_import` |

### Energy Registers (Lifetime, 32-bit pairs)

32-bit values use `(high_word << 16) | low_word` with little-endian register ordering.

| Reg Pair | Canonical Name | Scale | Unit | HA Sensor Key |
|----------|----------------|-------|------|---------------|
| 46-47 | `inverter_energy_total` | ÷10 | kWh | `yield_lifetime` |
| 50-51 | `charge_energy_total` | ÷10 | kWh | `charging_lifetime` |
| 52-53 | `discharge_energy_total` | ÷10 | kWh | `discharging_lifetime` |
| 56-57 | `grid_export_energy_total` | ÷10 | kWh | `grid_export_lifetime` |
| 58-59 | `grid_import_energy_total` | ÷10 | kWh | `grid_import_lifetime` |

### Consumption Energy

`consumption` and `consumption_lifetime` are **NOT** read from registers.

- Cloud API provides `todayLoad` / `totalLoad` (server-computed)
- LOCAL mode computes via energy balance in `coordinator_mappings._energy_balance()`:

```
consumption = yield + discharge + grid_import - charge - grid_export
```

Register 32 (`Erec_day`, AC charge from grid) is NOT consumption. Registers 48-49
(`Erec_all`) are lifetime AC charge energy, not consumption.

---

## 3. Inverter Holding Registers (Parameters)

Holding registers use Modbus function code 0x03 (read/write). These map to
`switch.` and `number.` entities.

Definitions: `pylxpweb/registers/inverter_holding.py`

### HOLD_MODEL (Registers 0-1) — Model Detection

Registers 0-1 contain a 32-bit bitfield (`HOLD_MODEL`) with hardware
configuration. Used during discovery to refine the model name beyond what
register 19 (device type code) provides.

**Extraction formula** (`InverterModelInfo.from_registers()`):

```python
# Base rating: bits 5-7 of the low byte of reg0
power_rating = ((reg0 & 0xFF) >> 5) & 0x7

# FlexBOSS family offset: bit 8 of reg1 adds 8
if reg1 & 0x100:
    power_rating += 8
```

**Usage in discovery** (`_config_flow/discovery.py`):

1. `_read_device_info_from_transport()` reads device type code from reg 19
2. For non-GridBOSS devices, reads HOLD_MODEL from `transport.read_parameters(0, 2)`
3. `InverterModelInfo.from_registers(reg0, reg1)` extracts `power_rating`
4. `get_model_name(device_type_code, power_rating)` resolves specific model name
5. Guard: if result contains "Unknown", falls back to family default name

**Power rating → model mapping:**

| Device Type | powerRating | Model |
|-------------|-------------|-------|
| 2092 | 2 | 12KPV |
| 2092 | 6 | 18KPV |
| 10284 | 8 | FlexBOSS21 |
| 10284 | 9 | FlexBOSS18 |
| 54 | 6 | 12000XP |
| 54 | 8 | 18000XP |

> **Note**: See `pylxpweb/docs/DEVICE_TYPES.md` for full bit layout documentation,
> validated device table, and example decodings.

### Function Enable Bitfield (Register 21)

| Bit | HA Entity Key | Entity Type | Purpose |
|-----|---------------|-------------|---------|
| 0 | `battery_backup` | switch | EPS/Battery Backup mode |
| 7 | `ac_charge` | switch | AC (Grid) Charging enable |
| 8 | `green_mode` | switch | Green/Off-Grid Mode |
| 10 | `forced_discharge` | switch | Forced Battery Discharge |
| 11 | `pv_charge_priority` | switch | Forced PV Charge Priority |

### Power Control Registers

| Reg | HA Entity Key | Entity Type | Unit | Range |
|-----|---------------|-------------|------|-------|
| 64 | `pv_charge_power` | number | % | 0-100 |
| 65 | `discharge_power_percent` | number | % | 0-100 |
| 66 | `ac_charge_power` | number | W | 0-15000 |
| 67 | `ac_charge_soc_limit` | number | % | 0-100 |

### Battery Control Registers

| Reg | HA Entity Key | Entity Type | Unit | Range |
|-----|---------------|-------------|------|-------|
| 101 | `charge_current` | number | A | 0-140 |
| 102 | `discharge_current` | number | A | 0-140 |
| 105 | `ongrid_discharge_soc` | number | % | 10-90 |
| 125 | `offgrid_discharge_soc` | number | % | 0-100 |

### Extended Function Enable (Register 179)

16-bit bit field for extended functions. Added in pylxpweb 0.9.5.

| Bit | Parameter Key | HA Entity Key | Purpose |
|-----|---------------|---------------|---------|
| 7 | `FUNC_GRID_PEAK_SHAVING` | `grid_peak_shaving` | Grid peak shaving mode (confirmed) |

> **Note:** Register 179 contains 16 API-mapped parameters (`FUNC_ACTIVE_POWER_LIMIT_MODE`,
> `FUNC_AC_COUPLING_FUNCTION`, `FUNC_BAT_CHARGE_CONTROL`, etc.) but only bit 7 has been
> confirmed via live toggle testing. Other bits have placeholder names (`FUNC_179_BIT0` etc.)
> until verified.

Related: Register 231 holds `grid_peak_shaving_power` (32-bit kW value).

### Extended Function Enable 2 (Register 233)

16-bit bit field for additional functions. Added in pylxpweb 0.9.5.

| Bit | Parameter Key | HA Entity Key | Purpose |
|-----|---------------|---------------|---------|
| 1 | `FUNC_BATTERY_BACKUP_CTRL` | `battery_backup_mode` | Battery backup control (confirmed) |

> **Note:** Register 233 contains 9 API-mapped parameters (`BIT_DRY_CONTRACTOR_MULTIPLEX`,
> `BIT_LCD_TYPE`, `FUNC_BATTERY_CALIBRATION_EN`, `FUNC_SPORADIC_CHARGE`, etc.) but only
> bit 1 has been confirmed via live toggle testing. Bit 12 is observed set (possibly
> `FUNC_QUICK_CHARGE_CTRL`). This was the root cause of issue #153 — beta.31 shipped with
> `pylxpweb>=0.9.4` in manifest but these register mappings only exist in 0.9.5.

---

## 4. GridBOSS Input Registers

All GridBOSS registers are INPUT registers (function code 0x04). Device type code: 50.

Definitions: `pylxpweb/registers/gridboss.py`

Mapping chain: Register → `read_scaled()` → `MidboxRuntimeData` field
→ `_build_gridboss_sensor_mapping()` → HA sensor key

### Voltage Registers (÷10 → V)

| Reg | Canonical Name | pylxpweb Field | HA Sensor Key |
|-----|----------------|----------------|---------------|
| 1 | `grid_voltage` | `grid_voltage` | `grid_voltage` |
| 2 | `ups_voltage` | `ups_voltage` | `ups_voltage` |
| 3 | `gen_voltage` | `gen_voltage` | `generator_voltage` |
| 4 | `grid_l1_voltage` | `grid_l1_voltage` | `grid_voltage_l1` |
| 5 | `grid_l2_voltage` | `grid_l2_voltage` | `grid_voltage_l2` |
| 6 | `ups_l1_voltage` | `ups_l1_voltage` | `load_voltage_l1` |
| 7 | `ups_l2_voltage` | `ups_l2_voltage` | `load_voltage_l2` |

### Current Registers (÷10 → A)

| Reg | Canonical Name | pylxpweb Field | HA Sensor Key |
|-----|----------------|----------------|---------------|
| 10 | `grid_l1_current` | `grid_l1_current` | `grid_current_l1` |
| 11 | `grid_l2_current` | `grid_l2_current` | `grid_current_l2` |
| 12 | `load_l1_current` | `load_l1_current` | `load_current_l1` |
| 13 | `load_l2_current` | `load_l2_current` | `load_current_l2` |
| 14 | `gen_l1_current` | `gen_l1_current` | `generator_current_l1` |
| 15 | `gen_l2_current` | `gen_l2_current` | `generator_current_l2` |
| 16 | `ups_l1_current` | `ups_l1_current` | `ups_current_l1` |
| 17 | `ups_l2_current` | `ups_l2_current` | `ups_current_l2` |

### Power Registers (signed, W, no scaling)

| Reg | Canonical Name | pylxpweb Field | HA Sensor Key |
|-----|----------------|----------------|---------------|
| 26 | `grid_l1_power` | `grid_l1_power` | `grid_power_l1` |
| 27 | `grid_l2_power` | `grid_l2_power` | `grid_power_l2` |
| 28 | `load_l1_power` | `load_l1_power` | `load_power_l1` |
| 29 | `load_l2_power` | `load_l2_power` | `load_power_l2` |
| 30 | `gen_l1_power` | `gen_l1_power` | `generator_power_l1` |
| 31 | `gen_l2_power` | `gen_l2_power` | `generator_power_l2` |
| 32 | `ups_l1_power` | `ups_l1_power` | `ups_power_l1` |
| 33 | `ups_l2_power` | `ups_l2_power` | `ups_power_l2` |

### Smart Load/AC Couple Power (signed, W, no scaling)

Smart ports can be configured as Smart Load (status=1) or AC Couple (status=2).
The power registers report actual measurement regardless of port mode — the
same physical registers contain the power reading; HA sensor keys are aliased
based on port status.

| Reg | Canonical Name | pylxpweb Field | HA Sensor Key |
|-----|----------------|----------------|---------------|
| 34 | `smart_load1_l1_power` | `smart_load_1_l1_power` | `smart_load1_power_l1` |
| 35 | `smart_load1_l2_power` | `smart_load_1_l2_power` | `smart_load1_power_l2` |
| 36 | `smart_load2_l1_power` | `smart_load_2_l1_power` | `smart_load2_power_l1` |
| 37 | `smart_load2_l2_power` | `smart_load_2_l2_power` | `smart_load2_power_l2` |
| 38 | `smart_load3_l1_power` | `smart_load_3_l1_power` | `smart_load3_power_l1` |
| 39 | `smart_load3_l2_power` | `smart_load_3_l2_power` | `smart_load3_power_l2` |
| 40 | `smart_load4_l1_power` | `smart_load_4_l1_power` | `smart_load4_power_l1` |
| 41 | `smart_load4_l2_power` | `smart_load_4_l2_power` | `smart_load4_power_l2` |

> **AC Couple power:** When a port is in AC Couple mode (status=2), the `smart_load{N}`
> registers contain the AC couple power. The coordinator creates `ac_couple{N}_power_l1/l2`
> sensor keys aliased from the same register values. See [Section 11](#11-smart-port-sensor-filtering).

### Frequency Registers (÷100 → Hz)

| Reg | Canonical Name | pylxpweb Field | HA Sensor Key |
|-----|----------------|----------------|---------------|
| 128 | `phase_lock_frequency` | `phase_lock_freq` | `phase_lock_frequency` |
| 129 | `grid_frequency` | `grid_frequency` | `frequency` |
| 130 | `gen_frequency` | `gen_frequency` | `generator_frequency` |

### Daily Energy Registers (÷10 → kWh)

| Reg | Canonical Name | HA Sensor Key |
|-----|----------------|---------------|
| 42 | `load_energy_today_l1` | `load_l1` |
| 43 | `load_energy_today_l2` | `load_l2` |
| 44 | `ups_energy_today_l1` | `ups_l1` |
| 45 | `ups_energy_today_l2` | `ups_l2` |
| 46 | `grid_export_today_l1` | `grid_export_l1` |
| 47 | `grid_export_today_l2` | `grid_export_l2` |
| 48 | `grid_import_today_l1` | `grid_import_l1` |
| 49 | `grid_import_today_l2` | `grid_import_l2` |
| 52-59 | `smart_load{1-4}_energy_today_l{1-2}` | `smart_load{N}_l{P}` |
| 60-67 | `ac_couple{1-4}_energy_today_l{1-2}` | `ac_couple{N}_l{P}` |

> **Note:** L2 energy registers always read 0 in practice. Aggregate energy
> sensors (e.g., `ups_today`, `load_today`) are computed by summing L1+L2 in pylxpweb.
>
> **Note:** Regs 50-51 are unused/unknown. Smart load daily energy starts at reg 52,
> not 50. Confirmed by Cloud API ↔ Modbus comparison (issue #146).

### Lifetime Energy Registers (32-bit pairs, ÷10 → kWh)

| Reg Pair | Canonical Name | HA Sensor Key |
|----------|----------------|---------------|
| 68-69 | `load_energy_total_l1` | `load_lifetime_l1` |
| 70-71 | `load_energy_total_l2` | `load_lifetime_l2` |
| 72-73 | `ups_energy_total_l1` | `ups_lifetime_l1` |
| 74-75 | `ups_energy_total_l2` | `ups_lifetime_l2` |
| 76-77 | `grid_export_total_l1` | `grid_export_lifetime_l1` |
| 78-79 | `grid_export_total_l2` | `grid_export_lifetime_l2` |
| 80-81 | `grid_import_total_l1` | `grid_import_lifetime_l1` |
| 82-83 | `grid_import_total_l2` | `grid_import_lifetime_l2` |
| 88-103 | `smart_load{1-4}_energy_total_l{1-2}` | `smart_load{N}_lifetime_l{P}` |
| 104-118 | `ac_couple{1-4}_energy_total_l{1-2}` | `ac_couple{N}_lifetime_l{P}` |

> **Note:** Regs 84-87 are unused/unknown. Smart load lifetime energy starts at reg 88,
> not 84. Confirmed by Cloud API ↔ Modbus comparison (issue #146).
>
> **Warning:** Input registers 105-108 are the HIGH words of 32-bit AC couple
> lifetime energy, NOT smart port status. See [Section 5](#5-gridboss-holding-register-20-smart-port-status).

### Register 134-253 Mirror

Input registers 134-253 are an exact mirror of holding registers 134-253.
This is a firmware quirk, NOT new data. Do not add register definitions in
this range.

---

## 5. GridBOSS Holding Register 20 (Smart Port Status)

Smart port status is stored as a **bit-packed value in HOLDING register 20**,
not in input registers.

### Encoding

2 bits per port, LSB-first:

```
Bits 0-1: Port 1
Bits 2-3: Port 2
Bits 4-5: Port 3
Bits 6-7: Port 4
```

### Values

| Value | Meaning | HA Display |
|-------|---------|------------|
| 0 | Unused/Off | Entity not created |
| 1 | Smart Load | `smart_port{N}_status` = 1 |
| 2 | AC Couple | `smart_port{N}_status` = 2 |

### Example

Register 20 = 18 (0b00010010):
- Port 1: bits 0-1 = `10` = 2 (AC Couple)
- Port 2: bits 2-3 = `00` = 0 (Unused)
- Port 3: bits 4-5 = `01` = 1 (Smart Load)
- Port 4: bits 6-7 = `00` = 0 (Unused)

### Implementation

**pylxpweb** (`_register_data.py`): `read_midbox_runtime()` reads holding register 20
and passes it to `MidboxRuntimeData.from_modbus_registers(smart_port_mode_reg=value)`.

The `from_modbus_registers()` method decodes the bit-packed value:
```python
for port in range(1, 5):
    mode = (smart_port_mode_reg >> ((port - 1) * 2)) & 0x03
    kwargs[f"smart_port_{port}_status"] = mode
```

**Cloud API**: Uses `bitParamControl` with `BIT_MIDBOX_SP_MODE_N` to read/write
this register. The `getMidboxRuntime` endpoint returns `smartPort{N}Status` fields.

---

## 6. Cloud API Field Mappings

Cloud API responses are mapped to HA sensor keys via dictionaries in
`const/sensors/mappings.py`. Scaling is applied by `_map_device_properties()`
in `coordinator_mixins.py`.

### Inverter Runtime (getInverterRuntime)

Mapping dict: `INVERTER_RUNTIME_FIELD_MAPPING`

| API Field | HA Sensor Key | Scale |
|-----------|---------------|-------|
| `status` | `status_code` | 1 |
| `pinv` | `ac_power` | 1 |
| `ppv` | `pv_total_power` | 1 |
| `ppv1` | `pv1_power` | 1 |
| `ppv2` | `pv2_power` | 1 |
| `ppv3` | `pv3_power` | 1 |
| `pCharge` | `battery_charge_power` | 1 |
| `pDisCharge` | `battery_discharge_power` | 1 |
| `consumptionPower` | `consumption_power` | 1 |
| `vBat` | `battery_voltage` | 1 |
| `vpv1` | `pv1_voltage` | 1 |
| `vpv2` | `pv2_voltage` | 1 |
| `vpv3` | `pv3_voltage` | 1 |
| `soc` | `state_of_charge` | 1 |
| `frequency` | `frequency` | 1 |
| `tinner` | `internal_temperature` | 1 |
| `tradiator1` | `radiator1_temperature` | 1 |
| `tradiator2` | `radiator2_temperature` | 1 |
| `todayYielding` | `yield` | ÷10 |
| `todayCharging` | `charging` | ÷10 |
| `todayDischarging` | `discharging` | ÷10 |
| `todayLoad` | `consumption` | ÷10 |
| `todayGridFeed` | `grid_export` | ÷10 |
| `todayGridConsumption` | `grid_import` | ÷10 |
| `totalYielding` | `yield_lifetime` | ÷10 |
| `totalCharging` | `charging_lifetime` | ÷10 |
| `totalDischarging` | `discharging_lifetime` | ÷10 |
| `totalLoad` | `consumption_lifetime` | ÷10 |
| `totalGridFeed` | `grid_export_lifetime` | ÷10 |
| `totalGridConsumption` | `grid_import_lifetime` | ÷10 |

### GridBOSS Runtime (getMidboxRuntime)

Mapping dict: `GRIDBOSS_FIELD_MAPPING`

| API Field | HA Sensor Key | Scale |
|-----------|---------------|-------|
| `gridFreq` | `frequency` | ÷100 |
| `genFreq` | `generator_frequency` | ÷100 |
| `phaseLockFreq` | `phase_lock_frequency` | ÷100 |
| `gridL1RmsVolt` | `grid_voltage_l1` | ÷10 |
| `gridL2RmsVolt` | `grid_voltage_l2` | ÷10 |
| `upsL1RmsVolt` | `load_voltage_l1` | ÷10 |
| `upsL2RmsVolt` | `load_voltage_l2` | ÷10 |
| `upsRmsVolt` | `ups_voltage` | ÷10 |
| `gridRmsVolt` | `grid_voltage` | ÷10 |
| `genRmsVolt` | `generator_voltage` | ÷10 |
| `gridL1RmsCurr` | `grid_current_l1` | ÷10 |
| `gridL2RmsCurr` | `grid_current_l2` | ÷10 |
| `loadL1RmsCurr` | `load_current_l1` | ÷10 |
| `loadL2RmsCurr` | `load_current_l2` | ÷10 |
| `upsL1RmsCurr` | `ups_current_l1` | ÷10 |
| `upsL2RmsCurr` | `ups_current_l2` | ÷10 |
| `genL1RmsCurr` | `generator_current_l1` | ÷10 |
| `genL2RmsCurr` | `generator_current_l2` | ÷10 |
| `gridL1ActivePower` | `grid_power_l1` | 1 |
| `gridL2ActivePower` | `grid_power_l2` | 1 |
| `loadL1ActivePower` | `load_power_l1` | 1 |
| `loadL2ActivePower` | `load_power_l2` | 1 |
| `upsL1ActivePower` | `ups_power_l1` | 1 |
| `upsL2ActivePower` | `ups_power_l2` | 1 |
| `genL1ActivePower` | `generator_power_l1` | 1 |
| `genL2ActivePower` | `generator_power_l2` | 1 |
| `smartLoad{N}L{P}ActivePower` | `smart_load{N}_power_l{P}` | 1 |
| `smartPort{N}Status` | `smart_port{N}_status` | 1 |
| Energy fields | See `DIVIDE_BY_10_SENSORS` | ÷10 |

### Parallel Group Energy (getInverterEnergyInfoParallel)

Mapping dict: `PARALLEL_GROUP_FIELD_MAPPING`

| API Field | HA Sensor Key | Scale |
|-----------|---------------|-------|
| `todayYielding` | `yield` | ÷10 |
| `todayCharging` | `charging` | ÷10 |
| `todayDischarging` | `discharging` | ÷10 |
| `todayExport` | `grid_export` | ÷10 |
| `todayImport` | `grid_import` | ÷10 |
| `todayUsage` | `consumption` | ÷10 |
| `totalYielding` | `yield_lifetime` | ÷10 |
| `totalCharging` | `charging_lifetime` | ÷10 |
| `totalDischarging` | `discharging_lifetime` | ÷10 |
| `totalExport` | `grid_export_lifetime` | ÷10 |
| `totalImport` | `grid_import_lifetime` | ÷10 |
| `totalUsage` | `consumption_lifetime` | ÷10 |

---

## 7. Individual Battery Data

### Battery Data Sources

Battery data comes from two distinct register ranges:

1. **Regular registers (0-255):** Aggregate battery bank data (SOC, voltage,
   current, charge/discharge power, temperature, capacity). Available on ALL
   inverters with batteries connected. Mapped via `BatteryBankData`.

2. **Extended registers (5002+):** Individual battery CAN bus data (per-battery
   cell voltages, temperatures, cycle counts, SOH). Only available when
   batteries actively communicate via CAN bus to the inverter.

**Important:** Some batteries do not communicate on the 5002+ range. This is
NOT specific to any inverter family — it can occur with any inverter/battery
combination. When 5002+ data is unavailable:
- Battery bank aggregate entities ARE created (from regular registers)
- Individual battery entities are NOT created (no per-battery data)
- Cloud API returns `batteryArray=[]`, `totalNumber=0`
- Cross-battery diagnostic sensors (`battery_bank_soc_delta`, etc.) return None

**Individual Battery Filtering (beta.28+):** Even when 5002+ registers are
read, individual batteries with ALL CAN bus data as `None` (voltage=None,
soc=None) are skipped. This prevents creating "Unknown" entities when CAN
communication is not established. The guard checks `batt.voltage is None and
batt.soc is None` in both `coordinator_local.py` and `coordinator_http.py`.

### Battery Register Space (Modbus)

Base address: 5002, 30 registers per battery, max 5 batteries per inverter.

Address formula: `5002 + (battery_index * 30) + offset`

Definitions: `pylxpweb/registers/battery.py`

| Offset | Canonical Name | Scale | Unit | HA Sensor Key |
|--------|----------------|-------|------|---------------|
| 1 | `battery_full_capacity` | 1 | Ah | `battery_full_capacity` |
| 2 | `battery_charge_voltage_ref` | ÷10 | V | `battery_charge_voltage_ref` |
| 3 | `battery_charge_current_limit` | ÷100 | A | `battery_max_charge_current` |
| 6 | `battery_voltage` | ÷100 | V | `battery_real_voltage` |
| 7 | `battery_current` | ÷10 | A | `battery_real_current` |
| 8 (low) | `battery_soc` | 1 | % | `battery_rsoc` |
| 8 (high) | `battery_soh` | 1 | % | `state_of_health` |
| 9 | `battery_cycle_count` | 1 | - | `cycle_count` |
| 12 | `battery_max_cell_voltage` | ÷1000 | V | `battery_max_cell_voltage` |
| 13 | `battery_min_cell_voltage` | ÷1000 | V | `battery_min_cell_voltage` |

### Cloud API (getBatteryInfo)

| API Field | HA Sensor Key |
|-----------|---------------|
| `totalVoltage` | `battery_real_voltage` |
| `current` | `battery_real_current` |
| `soc` | `battery_rsoc` |
| `soh` | `state_of_health` |
| `cycleCnt` | `cycle_count` |
| `batMaxCellVoltage` | `battery_max_cell_voltage` |
| `batMinCellVoltage` | `battery_min_cell_voltage` |
| `currentFullCapacity` | `battery_full_capacity` |
| `batBmsModelText` | `battery_model` |

### Computed Battery Keys

These are derived from register/API data in `coordinator_mappings.py`:

| HA Sensor Key | Computation |
|---------------|-------------|
| `battery_real_power` | `voltage * current` |
| `battery_cell_voltage_delta` | `max_cell_voltage - min_cell_voltage` |
| `battery_remaining_capacity` | `full_capacity * soc / 100` |

### Battery Bank Aggregate Keys

From `_build_battery_bank_sensor_mapping()`, sourced from regular registers:

| HA Sensor Key | Source |
|---------------|--------|
| `battery_bank_soc` | BatteryBankData.soc (register 5 low byte) |
| `battery_bank_voltage` | BatteryBankData.voltage (register 4, ÷10) |
| `battery_bank_current` | BatteryBankData.current (register 98, ÷10, signed) |
| `battery_bank_charge_power` | BatteryBankData.charge_power (register 10) |
| `battery_bank_discharge_power` | BatteryBankData.discharge_power (register 11) |
| `battery_bank_power` | `charge_power - discharge_power` |
| `battery_bank_count` | BatteryBankData.battery_count (register 96) |
| `battery_bank_min_soh` | Min SOH across individual batteries (5002+ only) |
| `battery_bank_max_cell_temp` | Max cell temp across individual batteries (5002+ only) |
| `battery_bank_soc_delta` | Max SOC - Min SOC across individual batteries (5002+ only) |
| `battery_bank_cell_voltage_delta_max` | Max cell voltage delta across individual batteries (5002+ only) |

**Note:** Cross-battery diagnostic sensors (min_soh, max_cell_temp, soc_delta,
etc.) require individual battery data from the 5002+ register range. When
batteries don't communicate on 5002+, these sensors return None.

---

## 8. Parallel Group Data

Parallel groups aggregate data from multiple inverters in the same group.

### Power Sensors (from inverter summing in LOCAL mode)

| HA Sensor Key | Computation |
|---------------|-------------|
| `pv_total_power` | Sum of all inverter `pv_total_power` |
| `grid_power` | Sum of all inverter `grid_power` |
| `grid_import_power` | Sum of all inverter `grid_import_power` |
| `grid_export_power` | Sum of all inverter `grid_export_power` |
| `consumption_power` | Sum of all inverter `consumption_power` |
| `eps_power` | Sum of all inverter `eps_power` |
| `ac_power` | Sum of all inverter `ac_power` |
| `output_power` | Sum of all inverter `output_power` |

### Energy Sensors (from parallel group API in CLOUD mode)

See [Section 6 - Parallel Group Energy](#parallel-group-energy-getinverterenergyinfoparallel).

### Battery Aggregate Sensors

| HA Sensor Key | Source |
|---------------|--------|
| `parallel_battery_charge_power` | Sum of inverter charge powers |
| `parallel_battery_discharge_power` | Sum of inverter discharge powers |
| `parallel_battery_power` | `charge - discharge` |
| `parallel_battery_current` | Sum of inverter `battery_bank_current` |
| `parallel_battery_soc` | Average SOC |
| `parallel_battery_voltage` | Average voltage |
| `parallel_battery_count` | Sum of battery counts |

---

## 9. Computed / Derived Sensor Keys

These keys are NOT directly read from registers or API. They are computed
in the coordinator layer.

### Inverter Computed Keys

From `INVERTER_COMPUTED_KEYS` frozenset in `coordinator_mappings.py`:

| HA Sensor Key | Computation | Where |
|---------------|-------------|-------|
| `consumption_power` | pylxpweb `inverter.consumption_power` (energy balance: PV + discharge + grid_import - charge - grid_export) | coordinator_local.py |
| `total_load_power` | Aliased from consumption_power | coordinator_local.py |
| `battery_power` | `charge_power - discharge_power` | coordinator_local.py |
| `rectifier_power` | From register 17 (`grid_power`) — renamed for clarity | coordinator_local.py |
| `grid_import_power` | From register 27 (`power_to_user`) | coordinator_local.py |
| `eps_power_l1` | `eps_power * (eps_voltage_l1 / (eps_voltage_l1 + eps_voltage_l2))` | coordinator_local.py |
| `eps_power_l2` | `eps_power * (eps_voltage_l2 / (eps_voltage_l1 + eps_voltage_l2))` | coordinator_local.py |

### GridBOSS Computed Keys

| HA Sensor Key | Computation |
|---------------|-------------|
| `grid_power` | `grid_l1_power + grid_l2_power` |
| `ups_power` | `ups_l1_power + ups_l2_power` |
| `load_power` | `load_l1_power + load_l2_power` |
| `generator_power` | `gen_l1_power + gen_l2_power` |
| `consumption_power` | `load_power` (CT measurement = actual consumption) |
| `hybrid_power` | `ups_power - grid_power` |

### Metadata Keys

| HA Sensor Key | Source |
|---------------|--------|
| `firmware_version` | From holding register read or API |
| `connection_transport` | "Cloud", "Modbus", "Dongle" (from config) |
| `transport_host` | IP/hostname of transport |
| `last_polled` | `dt_util.utcnow()` at refresh time |
| `midbox_last_polled` | `dt_util.utcnow()` for GridBOSS refresh |

---

## 10. Mode Differences

### LOCAL Mode

- **Data source**: Modbus TCP or WiFi Dongle (direct register reads)
- **Static entity creation**: First refresh creates all entities with `None` values (zero Modbus reads). Second refresh populates real data.
- **Consumption**: Computed via `_energy_balance()` from register values
- **bt_temperature**: Available (register 108) - Modbus-only, also in HYBRID via transport overlay
- **Battery data**: Read from extended register range (5000+)
- **Smart port status**: Read from holding register 20 (bit-packed)
- **GridBOSS energy**: Read from input registers 42-118 (smart load daily at 52-59, lifetime at 88-103)

### CLOUD Mode

- **Data source**: Cloud API HTTP endpoints
- **Consumption**: `todayLoad` / `totalLoad` from API (server-computed)
- **bt_temperature**: NOT available (no API field)
- **Battery data**: From `getBatteryInfo` API endpoint
- **Smart port status**: From `smartPort{N}Status` API fields
- **GridBOSS energy**: From `getMidboxRuntime` API fields
- **Scaling**: Applied by `_map_device_properties()` via `DIVIDE_BY_10_SENSORS`

### HYBRID Mode

- **Data source**: Both LOCAL (Modbus for runtime) and CLOUD (API for supplemental)
- **Priority**: LOCAL data preferred when available; CLOUD fills gaps
- **Transport-exclusive overlay**: When local transport is attached, Modbus-only sensors are overlaid onto cloud data via `_TRANSPORT_OVERLAY` in `coordinator_mixins.py`: `bt_temperature`, `grid_current_l1/l2/l3`, `battery_current`, `total_load_power`
- **GridBOSS overlay**: `apply_gridboss_overlay()` merges CT data onto parallel group
- **Consumption**: Uses GridBOSS CT `load_power` when GridBOSS present

### LOCAL-NOMIDBOX Mode

- Same as LOCAL but without direct Modbus connection to GridBOSS
- GridBOSS data comes from cloud API if hybrid, or is absent
- Fewer GridBOSS entities than full LOCAL mode

### Sensor Availability by Mode

| Sensor Key | LOCAL | CLOUD | HYBRID | Notes |
|------------|-------|-------|--------|-------|
| `bt_temperature` | Yes | No | Yes (overlay) | Modbus reg 108 only |
| `grid_current_l1/l2/l3` | Yes | No | Yes (overlay) | Modbus regs 18, 190, 191 |
| `battery_current` (inverter) | Yes | No | Yes (overlay) | Modbus reg 4 (via `_transport_runtime`) |
| `total_load_power` | Yes | API | Yes (overlay) | Aliased from consumption_power |
| `consumption_power` (inverter) | Computed | API | API or computed | Energy balance vs API |
| `consumption` (energy) | Computed | API (÷10) | API (÷10) | `_energy_balance()` vs `todayLoad` |
| Smart port power | Modbus regs 34-41 | API fields | Both | Filtered by port status |

---

## 11. Smart Port Sensor Filtering

### How It Works

`_filter_unused_smart_port_sensors()` in `coordinator_mixins.py` filters smart
port entities based on port status from holding register 20 (LOCAL) or API (CLOUD).

### Filtering Rules

For each port (1-4), based on `smart_port{N}_status`:

| Status | Smart Load Power Keys | AC Couple Power Keys | Energy Keys |
|--------|----------------------|---------------------|-------------|
| **0 (Unused)** | Removed | Removed | Removed |
| **1 (Smart Load)** | `setdefault(key, 0.0)` | `sensors[key] = None` | Only smart_load energy |
| **2 (AC Couple)** | `sensors[key] = None` | `setdefault(key, 0.0)` | Only ac_couple energy |

- **Correct-type** sensors: Ensures key exists with real value or 0.0
- **Wrong-type** sensors: Key set to `None` → entity shows as "Unknown" in HA
- **Unused** ports: All keys removed → no entities created

### Power Keys Affected

The 26 keys in `GRIDBOSS_SMART_PORT_POWER_KEYS`:
```
smart_load{1-4}_power_l{1-2}   (L1/L2 per-port)
ac_couple{1-4}_power_l{1-2}    (L1/L2 per-port)
smart_load{1-4}_power           (per-port aggregate, computed by _calculate_gridboss_aggregates)
ac_couple{1-4}_power            (per-port aggregate, computed by _calculate_gridboss_aggregates)
smart_load_power                (total across all smart load ports)
ac_couple_power                 (total across all AC couple ports)
```

**Aggregation behavior**: `_calculate_gridboss_aggregates()` runs AFTER the filter.
When both L1 and L2 are `None` (wrong-type port), the per-port aggregate is also
set to `None` instead of computing `0.0`. Total aggregates only sum correct-type ports.

### Late Registration

Smart port power entities are NOT created during static entity creation. They
are dynamically registered via a coordinator listener in `sensor.py` when
smart port data first becomes available.

---

## 12. GridBOSS CT Overlay

### Purpose

When a GridBOSS device is present, its CT (Current Transformer) measurements
provide accurate grid and load power readings for the parallel group. These
override the less accurate inverter-summed values.

### Function

`apply_gridboss_overlay()` in `coordinator_mixins.py` (module-level function).

Called from BOTH:
- `coordinator_http.py` (HYBRID mode)
- `coordinator_local.py` (LOCAL mode)

### Overlay Mapping

`_GRIDBOSS_PG_OVERLAY` dict maps GridBOSS sensor keys to parallel group keys:

| GridBOSS Key | Parallel Group Key | Category |
|--------------|--------------------|----------|
| `grid_power` | `grid_power` (PG) | Power |
| `grid_power_l1` | `grid_power_l1` (PG) | Power |
| `grid_power_l2` | `grid_power_l2` (PG) | Power |
| `load_power` | `load_power` (PG) | Power |
| `load_power_l1` | `load_power_l1` (PG) | Power |
| `load_power_l2` | `load_power_l2` (PG) | Power |
| `grid_voltage_l1` | `grid_voltage_l1` (PG) | Voltage |
| `grid_voltage_l2` | `grid_voltage_l2` (PG) | Voltage |
| `grid_export_today` | `grid_export` (PG) | Energy (daily) |
| `grid_export_total` | `grid_export_lifetime` (PG) | Energy (lifetime) |
| `grid_import_today` | `grid_import` (PG) | Energy (daily) |
| `grid_import_total` | `grid_import_lifetime` (PG) | Energy (lifetime) |

**Consumption energy (UPS + Load):** Computed separately after the overlay loop
because it requires summing two MID sources (not a simple key→key mapping):

```
consumption       = ups_today + load_today
consumption_lifetime = ups_total + load_total
```

UPS CTs measure inverter output (backup loads); Load CTs measure direct-from-grid
loads that bypass the inverter. Both contribute to total consumption.

### LOCAL-Specific Overlays

After the shared `apply_gridboss_overlay()`, `coordinator_local.py` applies:

**Consumption power (energy balance with MID grid_power):**
```
consumption_power = pv_total_power + battery_net + grid_power
    where battery_net = parallel_battery_discharge_power - parallel_battery_charge_power
    and grid_power is from MID overlay (positive = importing)
    clamped to >= 0
```

**Grid voltage conditional:** Grid voltage is copied from the master inverter
ONLY when no MID device is present. When a MID device exists, the overlay
provides authoritative grid voltage (inverter regs 193-194 return 0 on
18kPV/FlexBOSS firmware).

**AC couple PV inclusion** (optional, controlled by `CONF_INCLUDE_AC_COUPLE_PV`):
```
pv_total_power += Σ ac_couple_port_l1 + ac_couple_port_l2
                  (for all ports with status == 2)
```

---

## 13. Entity Counts by Mode

Captured 2026-02-13 from Docker test environment (v3.2.0-beta.32).

**Test configuration:** 2 inverters (FlexBOSS21 + 18kPV), 1 GridBOSS, batteries.
Smart ports: Port 1 = AC Couple, Port 2 = Unused, Port 3 = Smart Load, Port 4 = Unused.

| Mode | Total | Sensors | Switches | Updates | Numbers | Buttons | Selects | Unavail | Unknown |
|------|-------|---------|----------|---------|---------|---------|---------|---------|---------|
| CLOUD | 475 | 424 | 17 | 3 | 18 | 11 | 2 | 10 | 8 |
| HYBRID | 485 | 434 | 17 | 3 | 18 | 11 | 2 | 17 | 8 |
| LOCAL | 454 | 413 | 14 | 3 | 18 | 4 | 2 | 2 | 2 |
| LOCAL-NOMIDBOX | 391 | 352 | 14 | 2 | 18 | 3 | 2 | 1 | 1 |

**Entity growth since v3.2.0-beta.25:** Entity counts increased from ~365-373 to ~391-485
due to addition of button entities (cloud-only commands), select entities (working mode),
additional switch entities (cloud-only controls), and transport-exclusive sensors.

### Mode Differences

- **HYBRID** has the most entities (485): combines LOCAL sensors + CLOUD-only buttons/switches
- **CLOUD** (475): includes cloud-only command buttons (11) and cloud-only switches (3 extra vs LOCAL)
- **LOCAL** (454): includes transport-exclusive sensors (bt_temperature, grid_current, etc.)
- **LOCAL-NOMIDBOX** (391): no GridBOSS sensors, fewer buttons/updates

### Known Discrepancies

HYBRID has 10 more entities than CLOUD due to transport-exclusive sensors
(`bt_temperature`, `battery_current`, `total_load_power`, `grid_current_l1/l2/l3`,
`transport_ip_address` per inverter). CLOUD has cloud-only command buttons not
available in LOCAL mode.

---

## 14. Key Constants Reference

### Frozensets (coordinator_mappings.py)

| Constant | Count | Description |
|----------|-------|-------------|
| `INVERTER_RUNTIME_KEYS` | 43 | Voltage, current, power, temperature, status, grid_current_l1/l2/l3 |
| `INVERTER_ENERGY_KEYS` | 12 | Daily + lifetime energy (6 each) |
| `BATTERY_BANK_KEYS` | 23 | Battery aggregate sensors (incl. battery_bank_current) |
| `INVERTER_COMPUTED_KEYS` | 7 | Derived sensors (consumption, battery, EPS split) |
| `INVERTER_METADATA_KEYS` | 4 | Firmware, transport, host, last_polled |
| `ALL_INVERTER_SENSOR_KEYS` | 89 | Union of all above |
| `GRIDBOSS_SENSOR_KEYS` | 65 | All GridBOSS sensor keys (incl. smart port, energy, metadata) |
| `GRIDBOSS_SMART_PORT_POWER_KEYS` | 26 | Smart load + AC couple power (L1/L2 + aggregates + totals) |
| `PARALLEL_GROUP_SENSOR_KEYS` | 32 | PG power, energy, battery aggregates (incl. grid import/export, battery current) |
| `PARALLEL_GROUP_GRIDBOSS_KEYS` | 5 | Additional keys from CT overlay |

### Scaling Sets (const/sensors/mappings.py)

| Constant | Description |
|----------|-------------|
| `DIVIDE_BY_10_SENSORS` | All energy sensors requiring ÷10 from Cloud API |
| `DIVIDE_BY_100_SENSORS` | Frequency sensors requiring ÷100 from Cloud API |
| `VOLTAGE_SENSORS` | GridBOSS voltage sensors requiring ÷10 from Cloud API |
| `CURRENT_SENSORS` | GridBOSS current sensors requiring ÷10 from Cloud API |

### Feature Flags (from _features_from_family)

| Family | `split_phase` | `three_phase` | Models |
|--------|---------------|---------------|--------|
| `EG4_OFFGRID` | True | False | 12000XP, 6000XP |
| `EG4_HYBRID` | True | False | FlexBOSS, 18kPV, 12kPV |
| `LXP` (code 12) | False | True | LXP-EU (3-phase) |
| `LXP` (code 44) | True | False | LXP-LB (BR/US) |

---

## 15. All Calculations Reference

This section documents **every** calculation, derivation, scaling, and transformation
in the data pipeline. Organized by pipeline stage.

---

### 15.1 Register Scaling (pylxpweb `_canonical_reader.py`)

The canonical reader applies scale factors from `RegisterDefinition.scale`:

```
ScaleFactor.DIVIDE_10   → raw_value / 10.0     (voltages, energy kWh)
ScaleFactor.DIVIDE_100  → raw_value / 100.0     (frequencies, currents)
ScaleFactor.DIVIDE_1000 → raw_value / 1000.0    (cell voltages)
ScaleFactor.NONE        → raw_value             (power W, status codes)
```

`read_scaled(registers, field)` returns the final float.
`read_raw(registers, field)` returns the unscaled int.

### 15.2 32-bit Register Pairs

For lifetime energy counters spanning two 16-bit registers:

```
value = (high_word << 16) | low_word
```

`RegisterDefinition` with `size=2` auto-sets `little_endian=True` via
`__post_init__`. The "low" register has the lower address, "high" the next.
Final value is then scaled (typically ÷10 for kWh).

**Example:** Regs 46-47 → `(reg47 << 16) | reg46` → `÷10` → `yield_lifetime` kWh.

### 15.3 Battery SoC/SoH Byte Unpacking (Register 5)

Register 5 (`soc_soh_packed`) encodes two values in a single 16-bit register:

```python
soc = raw_value & 0xFF        # Low byte: State of Charge (0-100%)
soh = (raw_value >> 8) & 0xFF # High byte: State of Health (0-100%)
```

Handled by `InverterRuntimeData.from_modbus_registers()` in pylxpweb.

### 15.4 Cloud API Scaling (`_map_device_properties`)

**Function:** `coordinator_mixins._map_device_properties(device, property_map)`

**Behavior:**
1. Iterates `property_map` (API field → sensor key)
2. Calls `getattr(device, property_name, None)` — catches TypeError/ValueError
   from property getters that call `float(None)` on unpopulated data
3. **Skips** `None` values and empty strings — keys not added to sensors dict
4. Non-None values passed through as-is

**Post-mapping scaling** in `coordinator_http.py` and `coordinator_mixins.py`:

After `_map_device_properties()` produces the sensor dict, scaling is applied
based on membership in these sets (defined in `const/sensors/mappings.py`):

| Scaling Set | Factor | Applied To |
|-------------|--------|------------|
| `DIVIDE_BY_10_SENSORS` | `value / 10` | All energy sensors (kWh) |
| `DIVIDE_BY_100_SENSORS` | `value / 100` | Frequency sensors (Hz) |
| `VOLTAGE_SENSORS` | `value / 10` | GridBOSS voltage sensors (V) |
| `CURRENT_SENSORS` | `value / 10` | GridBOSS current sensors (A) |

**Note:** Inverter voltage/power sensors arrive pre-scaled from pylxpweb
properties in CLOUD mode. Only GridBOSS and energy sensors need post-mapping
scaling since they come from raw JSON fields.

### 15.5 `_safe_numeric()` Helper

**File:** `coordinator_mixins.py:260`

```python
def _safe_numeric(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
```

Used throughout aggregation code. **Critical behavior:** `None` → `0.0`.
This means summing a mix of real values and `None` treats missing data as zero.
The smart port aggregation explicitly checks for `None` before calling this
to avoid creating misleading `0.0` aggregates for wrong-type ports.

---

### 15.6 Inverter Computed Sensors

These sensors are NOT read from a single register or API field. They are
computed in the coordinator layer.

#### `consumption_power` (Inverter, LOCAL)

**Source:** `pylxpweb` `inverter.consumption_power` property

```
consumption_power = pv_total_power + grid_import - grid_export
                    (clamped to >= 0)
```

**Where:** `coordinator_local.py` — set via `inverter.consumption_power`
property accessor.

#### `consumption` / `consumption_lifetime` (Inverter Energy, LOCAL)

**Function:** `coordinator_mappings._energy_balance()`

```python
def _energy_balance(pv, discharge, grid_import, charge, grid_export):
    if all(v is None for v in (pv, discharge, grid_import, charge, grid_export)):
        return None
    result = (float(pv or 0)
              + float(discharge or 0)
              + float(grid_import or 0)
              - float(charge or 0)
              - float(grid_export or 0))
    return max(0.0, result)
```

**Formula:**
```
consumption = yield + discharging + grid_import - charging - grid_export
              (clamped >= 0, returns None if all inputs None)
```

**When applied:**
- `_build_energy_sensor_mapping()` always uses energy balance for LOCAL sensors
- `_process_inverter_object()` recalculates when `_transport` is attached
  (overrides pylxpweb's `energy_today_usage` which reads the wrong register)

**CLOUD mode:** Uses `todayLoad` / `totalLoad` from API (server-computed).

#### `battery_power` (Inverter)

```
battery_power = charge_power - discharge_power
```

Positive = net charging, negative = net discharging.

**Source:** `inverter.battery_power` property in pylxpweb (LOCAL),
or `batPower` API field (CLOUD).

#### `grid_power` (Inverter)

```
grid_power = power_to_user - power_to_grid
```

Positive = importing from grid, negative = exporting to grid.

**Where:** `coordinator_mixins.py` `_process_inverter_object()` line ~458.

#### `eps_power_l1` / `eps_power_l2` (Inverter, LOCAL only)

Split-phase EPS power per leg, computed from total EPS power and voltage ratio:

```python
eps_power_l1 = eps_power * (eps_voltage_l1 / (eps_voltage_l1 + eps_voltage_l2))
eps_power_l2 = eps_power * (eps_voltage_l2 / (eps_voltage_l1 + eps_voltage_l2))
```

Returns `None` when both voltages are zero (no EPS output).

**Source:** `inverter.eps_power_l1` / `inverter.eps_power_l2` properties in
pylxpweb. Set in `coordinator_local.py` `_build_local_device_data()`.

#### `total_load_power` (Inverter)

Alias for `consumption_power`. Same value, different sensor key for
backward compatibility.

#### `rectifier_power` (Inverter)

Direct alias for register 17 (`grid_power` in pylxpweb). Named `rectifier_power`
in HA for disambiguation from the computed `grid_power` sensor.

#### `grid_import_power` (Inverter)

Direct alias for register 27 (`power_to_user` in pylxpweb).

---

### 15.7 GridBOSS Computed Sensors

#### L1+L2 Aggregate Power (`_calculate_gridboss_aggregates`)

**File:** `coordinator_mixins.py:1306`

Computes total power from individual L1/L2 values using `sum_l1_l2()`:

```python
def sum_l1_l2(l1_key, l2_key):
    if l1_key in sensors and l2_key in sensors:
        l1_val, l2_val = sensors[l1_key], sensors[l2_key]
        if l1_val is None and l2_val is None:
            return None  # Wrong-type port marker
        return _safe_numeric(l1_val) + _safe_numeric(l2_val)
    return None  # Keys don't exist
```

**Simple L1+L2 pairs:**

| Output Key | Formula |
|------------|---------|
| `grid_power` | `grid_power_l1 + grid_power_l2` |
| `ups_power` | `ups_power_l1 + ups_power_l2` |
| `load_power` | `load_power_l1 + load_power_l2` |
| `generator_power` | `generator_power_l1 + generator_power_l2` |

**Smart port per-port aggregates:**

| Output Key | Formula |
|------------|---------|
| `smart_load{N}_power` | `smart_load{N}_power_l1 + smart_load{N}_power_l2` |
| `ac_couple{N}_power` | `ac_couple{N}_power_l1 + ac_couple{N}_power_l2` |

For wrong-type ports (both L1 and L2 are `None`), the per-port aggregate
is also set to `None` (not 0.0).

**Smart port total aggregates:**

| Output Key | Formula |
|------------|---------|
| `smart_load_power` | Sum of all `smart_load{N}_power` where value is not None |
| `ac_couple_power` | Sum of all `ac_couple{N}_power` where value is not None |

Total keys are only created when at least one port of that type has a real
value. If no ports are active, the total key is not added to the sensors dict.

#### `consumption_power` (GridBOSS)

```
consumption_power = load_power   (direct CT measurement, NOT energy balance)
```

The GridBOSS load CT is the authoritative consumption measurement. Set in
`_build_gridboss_sensor_mapping()` and `_get_mid_device_property_map()`.

#### `hybrid_power` (GridBOSS)

```
hybrid_power = ups_power - grid_power
```

Computed by `MIDRuntimePropertiesMixin.hybrid_power` in pylxpweb.

---

### 15.8 Individual Battery Computed Sensors

#### `battery_real_power`

```
battery_real_power = voltage * current
```

Computed by `pylxpweb` `Battery.power` property. Also available from
`BatteryData.power` in LOCAL mode.

#### `battery_cell_voltage_delta`

```
battery_cell_voltage_delta = max_cell_voltage - min_cell_voltage
```

Computed by pylxpweb `Battery.cell_voltage_delta` / `BatteryData.cell_voltage_delta`.

#### `battery_remaining_capacity`

```
battery_remaining_capacity = max_capacity * soc / 100
```

Computed by pylxpweb `BatteryData.remaining_capacity`.

#### `battery_capacity_percentage` (fallback)

```
battery_capacity_percentage = remaining_capacity / full_capacity * 100
```

Only computed when not already provided by the library. Calculated in
`_calculate_battery_derived_sensors()`.

#### `battery_cell_voltage_diff` (fallback)

```
battery_cell_voltage_diff = max_cell_voltage - min_cell_voltage
```

Rounded to 3 decimal places. Only computed when `battery_cell_voltage_diff`
is not already in the sensors dict. Calculated in
`_calculate_battery_derived_sensors()`.

---

### 15.9 Battery Bank Computed Sensors

**File:** `coordinator_mappings._build_battery_bank_sensor_mapping()`

#### `battery_bank_power`

Primary formula:
```
battery_bank_power = charge_power - discharge_power
```
Positive = net charging, negative = net discharging.

Fallback (when charge/discharge unavailable):
```
battery_bank_power = battery_data.battery_power   (V * I computation)
```

**Note:** In HTTP mode (`_extract_battery_bank_from_object`), the same
charge−discharge formula is used as fallback when `batPower` API field
is not present.

#### Cross-Battery Diagnostic Sensors

These are computed by `BatteryBankData` properties in pylxpweb, comparing
values across all batteries in the bank:

| Sensor Key | Computation |
|------------|-------------|
| `battery_bank_soc_delta` | `max(soc) - min(soc)` across all batteries |
| `battery_bank_min_soh` | `min(soh)` across all batteries |
| `battery_bank_soh_delta` | `max(soh) - min(soh)` across all batteries |
| `battery_bank_voltage_delta` | `max(voltage) - min(voltage)` across all batteries |
| `battery_bank_cell_voltage_delta_max` | `max(cell_voltage_delta)` across all batteries |
| `battery_bank_cycle_count_delta` | `max(cycle_count) - min(cycle_count)` across all batteries |
| `battery_bank_max_cell_temp` | `max(max_cell_temp)` across all batteries |
| `battery_bank_temp_delta` | `max(max_cell_temp) - min(min_cell_temp)` across all batteries |

All return `None` when insufficient data (fewer than 1 battery with the field).

---

### 15.10 Parallel Group Computations (LOCAL mode)

**File:** `coordinator_local.py:_process_local_parallel_groups()`

#### Power Sensor Summing

These sensors are summed across all member inverters:

```
pv_total_power    = Σ inverter.pv_total_power
grid_power        = Σ inverter.grid_power
grid_import_power = Σ inverter.grid_import_power
grid_export_power = Σ inverter.grid_export_power
consumption_power = Σ inverter.consumption_power
eps_power         = Σ inverter.eps_power
ac_power          = Σ inverter.ac_power
output_power      = Σ inverter.output_power
```

Only non-None values are included in each sum.

#### Energy Sensor Summing

```
yield              = Σ inverter.yield
charging           = Σ inverter.charging
discharging        = Σ inverter.discharging
grid_import        = Σ inverter.grid_import
grid_export        = Σ inverter.grid_export
consumption        = Σ inverter.consumption
(same for _lifetime variants)
```

#### Battery Aggregates at Parallel Group Level

```
parallel_battery_charge_power    = Σ inverter.battery_charge_power
parallel_battery_discharge_power = Σ inverter.battery_discharge_power
parallel_battery_power           = discharge_sum - charge_sum
                                   (positive = discharging)
parallel_battery_soc             = average(inverter.state_of_charge)
parallel_battery_voltage         = average(inverter.battery_voltage)
parallel_battery_current         = Σ inverter.battery_bank_current
parallel_battery_count           = Σ inverter.battery_bank_count
parallel_battery_max_capacity    = Σ inverter.battery_bank_max_capacity
parallel_battery_current_capacity = Σ inverter.battery_bank_current_capacity
```

**Sign convention note:** `parallel_battery_power` uses `discharge - charge`
(positive = discharging), which is the **opposite** sign convention from
`battery_bank_power` (which uses `charge - discharge`, positive = charging).

#### Grid Voltage Copy

Grid voltage L1/L2 comes from the MID device (GridBOSS) when present (via
`apply_gridboss_overlay()`). When no MID device exists, it falls back to the
master inverter:
```
grid_voltage_l1 = gridboss.grid_voltage_l1  (if MID present)
grid_voltage_l2 = gridboss.grid_voltage_l2  (if MID present)
# OR
grid_voltage_l1 = master_inverter.grid_voltage_l1  (fallback, no MID)
grid_voltage_l2 = master_inverter.grid_voltage_l2  (fallback, no MID)
```

Rationale: Inverter regs 193-194 return 0 on 18kPV/FlexBOSS firmware. The MID
device has authoritative grid voltage from its own sensors.

---

### 15.11 GridBOSS CT Overlay (Full Mapping)

**Function:** `apply_gridboss_overlay()` in `coordinator_mixins.py`

The `_GRIDBOSS_PG_OVERLAY` dict maps GridBOSS sensor keys to parallel group
sensor keys. Only non-None GridBOSS values are applied (cast to `float`).

| GridBOSS Key | → Parallel Group Key | Category |
|--------------|---------------------|----------|
| `grid_power` | `grid_power` | Power |
| `grid_power_l1` | `grid_power_l1` | Power |
| `grid_power_l2` | `grid_power_l2` | Power |
| `load_power` | `load_power` | Power |
| `load_power_l1` | `load_power_l1` | Power |
| `load_power_l2` | `load_power_l2` | Power |
| `grid_voltage_l1` | `grid_voltage_l1` | Voltage |
| `grid_voltage_l2` | `grid_voltage_l2` | Voltage |
| `grid_export_today` | `grid_export` | Energy (daily) |
| `grid_export_total` | `grid_export_lifetime` | Energy (lifetime) |
| `grid_import_today` | `grid_import` | Energy (daily) |
| `grid_import_total` | `grid_import_lifetime` | Energy (lifetime) |

**Consumption energy (computed after overlay loop):**
```
consumption          = ups_today + load_today
consumption_lifetime = ups_total + load_total
```
UPS CTs measure backup loads (inverter output); Load CTs measure non-backup
loads (direct from grid). Both contribute to total consumption.

#### LOCAL-Only Additional Overlays

After the shared overlay, `_process_local_parallel_groups()` applies:

**Consumption power (energy balance with MID grid_power):**
```
consumption_power = pv_total_power + battery_net + grid_power
    where battery_net = parallel_battery_discharge_power - parallel_battery_charge_power
    and grid_power comes from MID overlay (positive = importing)
    clamped to >= 0
```

Rationale: Inverters lack grid CTs in MID systems — their grid register
values are unreliable. The MID overlay provides authoritative `grid_power`,
which combined with known PV and battery flow yields accurate consumption.

**AC couple PV inclusion** (optional, controlled by `CONF_INCLUDE_AC_COUPLE_PV`):
```
pv_total_power += Σ ac_couple_port_l1 + ac_couple_port_l2
                  (for all ports with status == 2)
```

When enabled, AC-coupled solar inverters on smart ports are included in
the total PV power. Default: disabled.

---

### 15.12 Smart Port Status Decode (Holding Register 20)

```python
for port in range(1, 5):
    status = (register_20_value >> ((port - 1) * 2)) & 0x03
```

See [Section 5](#5-gridboss-holding-register-20-smart-port-status) for
encoding details. The decoded status drives all smart port sensor filtering
in [Section 11](#11-smart-port-sensor-filtering).

---

### 15.13 Cloud API vs LOCAL Calculation Differences

| Sensor Key | CLOUD Source | LOCAL Computation |
|------------|-------------|-------------------|
| `consumption` | `todayLoad ÷ 10` (server-computed) | `_energy_balance(yield, discharge, grid_import, charge, grid_export)` |
| `consumption_lifetime` | `totalLoad ÷ 10` (server-computed) | `_energy_balance(...)` on lifetime values |
| `consumption_power` | `consumptionPower` API field | `inverter.consumption_power` property (energy balance on instantaneous power) |
| `grid_power` (inverter) | Computed: `pToUser - pToGrid` | Computed: `power_to_user - power_to_grid` (same formula, different source) |
| `battery_power` (inverter) | `batPower` API field | `inverter.battery_power` property (`charge - discharge`) |
| `battery_bank_power` | `batPower` API or `charge - discharge` | `charge_power - discharge_power` (with V*I fallback) |
| GridBOSS L1+L2 aggregates | Computed by `_calculate_gridboss_aggregates()` | Same function, same computation |
| Smart port status | `smartPort{N}Status` API fields | Holding register 20 bit-decode |
| GridBOSS energy | `getMidboxRuntime` API (÷10 scaling) | Input registers 42-67 (daily), 68-103 (lifetime), 104-118 (AC couple) (÷10 by canonical reader) |

---

### 15.14 Data Validation (Two-Layer Architecture)

Data validation operates at two independent layers:

#### Layer 1: Transport-Level (pylxpweb)

Controlled by `inverter.validate_data` property (set from `CONF_DATA_VALIDATION`
option in the Options flow). When enabled, `is_corrupt()` canary checks run
after each Modbus read. If corrupt, the read is rejected and the previous
cached value is preserved.

**Canary fields by data class:**

| Data Class | Check | Threshold | Rationale |
|------------|-------|-----------|-----------|
| `InverterRuntimeData` | `_raw_soc > 100` | SoC physically 0-100% | Register desync |
| `InverterRuntimeData` | `_raw_soh > 100` | SoH physically 0-100% | Register desync |
| `InverterRuntimeData` | `frequency < 30 or > 90` | World grids 50/60 Hz | Extreme corruption only |
| `InverterRuntimeData` | `frequency == 0` | **Allowed** (off-grid/EPS) | Not corruption |
| `BatteryData` | `_raw_soc > 100` | SoC 0-100% | CAN bus error |
| `BatteryData` | `_raw_soh > 100` | SoH 0-100% | CAN bus error |
| `BatteryData` | `voltage > 100V` | No LFP exceeds 60V | Register desync |
| `BatteryBankData` | Cascade to batteries | Skips ghost batteries (V=0, SoC=0) | No CAN data |
| `MidboxRuntimeData` | `frequency < 30 or > 90` | Same as inverter | Extreme corruption |
| `MidboxRuntimeData` | `smart_port_status > 2` | Valid: 0, 1, 2 | Bit decode error |

**Implementation:** `coordinator_local.py` sets `inverter.validate_data = self._data_validation_enabled`
before each `inverter.refresh()` call. The `_data_validation_enabled` property
reads from `CONF_DATA_VALIDATION` in the config entry options (default: `True`).

#### Layer 2: Coordinator-Level (eg4_web_monitor)

**Energy monotonicity:** `_validate_energy_monotonicity()` in `coordinator_local.py`
checks that lifetime energy counters never decrease between poll cycles.

```
_LIFETIME_ENERGY_KEYS = frozenset({
    "yield_lifetime", "charging_lifetime", "discharging_lifetime",
    "grid_import_lifetime", "grid_export_lifetime", "consumption_lifetime",
})
```

When a decrease is detected, the new (lower) value is rejected and the
previous value is preserved. This catches register rollover and corruption
that passes Layer 1 canary checks.

#### Options Flow

The data validation toggle appears in Options flow (`_config_flow/options.py`)
only when local transports are configured (Modbus TCP, WiFi dongle, serial).
Cloud-only mode does not show this option since the cloud API has its own
server-side validation.
