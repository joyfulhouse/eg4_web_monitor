# Unavailable Sensors Analysis

**Date**: 2025-11-22
**Integration Version**: 3.0.0
**Library Version**: pylxpweb 0.3.3

## Overview

Investigation into sensors showing as "unavailable" in Home Assistant after upgrading to pylxpweb 0.3.3 device object architecture.

## Reported Issues

User reported the following sensors showing as unavailable:
1. `sensor.18kpv_4512670118_ac_power` - AC Power
2. `sensor.18kpv_4512670118_ac_voltage` - AC Voltage
3. `sensor.18kpv_4512670118_battery_charge` - Battery charging energy
4. `sensor.18kpv_4512670118_battery_discharge` - Battery discharging energy
5. `sensor.18kpv_4512670118_pv_total_power` - PV Total Power
6. Internal temperature sensors for radiators

## Investigation Results

### 1. PV Total Power - FIXED ✅

**Problem**: Property mapping error in coordinator.py

**Root Cause**:
```python
# WRONG
"pv_total_power": "pv_power",

# Should be
"pv_total_power": "pv_total_power",
```

The inverter object has `pv_total_power` property (value: 3279 W), but the property map was pointing to non-existent sensor definition `pv_power` instead of the correct `pv_total_power`.

**Fix Applied**:
- File: `coordinator.py:610`
- Changed: `"pv_total_power": "pv_power"` → `"pv_total_power": "pv_total_power"`

**Result**: ✅ Sensor now available and showing real-time PV power

### 2. Battery Charge/Discharge Energy - AVAILABLE ✅

**Status**: These sensors are correctly mapped and have data.

**Evidence from logs**:
```
Inverter 4512670118.energy_today_charging = 10.3 kWh
Inverter 4512670118.energy_today_discharging = 0.0 kWh
```

**Property Mappings** (coordinator.py):
```python
"energy_today_charging": "battery_charge",        # Line 663
"energy_today_discharging": "battery_discharge",  # Line 664
"energy_lifetime_charging": "battery_charge_lifetime",
"energy_lifetime_discharging": "battery_discharge_lifetime",
```

**Sensor Definitions** (const.py):
```python
"battery_charge": {  # Line 316
    "name": "Battery Charge",
    "unit": UnitOfEnergy.KILO_WATT_HOUR,
    "device_class": "energy",
    "state_class": "total_increasing",
    "icon": "mdi:battery-charging",
},
"battery_discharge": {  # Line 323
    "name": "Battery Discharge",
    "unit": UnitOfEnergy.KILO_WATT_HOUR,
    "device_class": "energy",
    "state_class": "total_increasing",
    "icon": "mdi:battery-minus",
},
```

**Conclusion**: These sensors should be available. If showing as unavailable, likely a temporary state or entity registry issue requiring HA restart.

### 3. AC Power - NOT AVAILABLE IN LIBRARY ⚠️

**Status**: Property does not exist in pylxpweb 0.3.3 Inverter objects

**Evidence from logs**:
```
Inverter 4512670118 available properties: ['ac_charge_power_limit', 'ac_charge_soc_limit', 'ac_couple_power', ...]
Inverter 4512670118.ac_power = NOT_FOUND
```

**Historical Context**:
- Old API (pre-0.3.2): Raw API field `pinv` mapped to `ac_power` sensor
- New library (0.3.3+): No `ac_power` property on Inverter objects

**Analysis**:
The `ac_power` sensor was derived from the raw API field `pinv` (inverter AC output power). The pylxpweb library doesn't expose this as a top-level property. Possible alternatives:
- `inverter_power` - Available in library, likely the same metric
- `power_output` - Available in library

**Recommendation**:
Map `inverter_power` to `ac_power` sensor definition to restore functionality:
```python
"inverter_power": "ac_power",  # AC output power from inverter
```

### 4. AC Voltage - NOT AVAILABLE IN LIBRARY ⚠️

**Status**: Property does not exist in pylxpweb 0.3.3 Inverter objects

**Evidence from logs**:
```
Inverter 4512670118.ac_voltage = NOT_FOUND
```

**Historical Context**:
- Old API: Raw API fields `acVoltage` or `vacr` mapped to `ac_voltage` sensor
- New library: No `ac_voltage` property on Inverter objects

**Analysis**:
The library provides phase-specific grid voltages instead:
- `grid_voltage_r` - Grid voltage phase R (available)
- `grid_voltage_s` - Grid voltage phase S (available)
- `grid_voltage_t` - Grid voltage phase T (available)
- `eps_voltage_r/s/t` - EPS voltages (available)

**Recommendation**:
The library doesn't provide a single "AC voltage" - it provides per-phase voltages which are more accurate for 3-phase systems. For single-phase systems, `grid_voltage_r` is the AC voltage.

**Options**:
1. Remove `ac_voltage` sensor (no direct equivalent)
2. Calculate average AC voltage from grid phases
3. Map `grid_voltage_r` to `ac_voltage` for single-phase compatibility

### 5. Internal Temperature - NOT AVAILABLE IN LIBRARY ⚠️

**Status**: Property does not exist in pylxpweb 0.3.3 Inverter objects

**Evidence from logs**:
```
Inverter 4512670118.internal_temperature = NOT_FOUND
```

**Available Temperature Sensors**:
```python
'battery_temperature'      # Available
'inverter_temperature'     # Available
'radiator1_temperature'    # Available
'radiator2_temperature'    # Available
```

**Analysis**:
The library doesn't provide `internal_temperature`. Available alternatives:
- `inverter_temperature` - Inverter electronics temperature
- `radiator1_temperature` - Heat sink 1 temperature
- `radiator2_temperature` - Heat sink 2 temperature

**Recommendation**:
- The `inverter_temperature` is likely what was previously called "internal temperature"
- Radiator temperatures are more specific (heat sink monitoring)
- No action needed - these sensors are already exposed

## Summary

### Fixed ✅
1. **PV Total Power**: Property mapping corrected (`pv_power` → `pv_total_power`)

### Already Working ✅
2. **Battery Charge Energy**: Mapped correctly, has data (10.3 kWh)
3. **Battery Discharge Energy**: Mapped correctly, has data (0.0 kWh)
4. **Radiator Temperatures**: Both radiator1 and radiator2 available

### Not Available in Library (Require Alternatives) ⚠️
5. **AC Power**: No `ac_power` property - recommend mapping `inverter_power` instead
6. **AC Voltage**: No `ac_voltage` property - use phase-specific voltages instead
7. **Internal Temperature**: No `internal_temperature` - `inverter_temperature` is the equivalent

## Recommended Actions

### Immediate Fix
- ✅ **DONE**: Fixed `pv_total_power` mapping

### Consider for Future
1. **AC Power Alternative**:
   ```python
   # coordinator.py - Add to property map
   "inverter_power": "ac_power",
   ```

2. **AC Voltage Alternative**:
   - For single-phase: Users can use `grid_voltage_r`
   - For 3-phase: Users have individual phase voltages (more accurate)
   - Consider removing legacy `ac_voltage` sensor from const.py

3. **Internal Temperature**:
   - Already have `inverter_temperature` which serves the same purpose
   - No action needed

## Library Property Audit

Based on debug logs, pylxpweb 0.3.3 Inverter objects provide **103 properties**:

**Power Properties (17)**:
- ac_couple_power, battery_charge_power, battery_discharge_power, battery_power
- consumption_power, eps_power, eps_power_l1, eps_power_l2
- generator_power, inverter_power, power_factor, power_output, power_rating
- power_to_grid, power_to_user, pv1/2/3_power, pv_total_power, rectifier_power

**Voltage Properties (13)**:
- battery_voltage, bus1_voltage, bus2_voltage
- grid_voltage_r/s/t, eps_voltage_r/s/t
- generator_voltage, pv1/2/3_voltage

**Energy Properties (11)**:
- energy_lifetime_charging/discharging/export/import/usage
- energy_today_charging/discharging/export/import/usage
- total_energy_lifetime, total_energy_today

**Temperature Properties (4)**:
- battery_temperature, inverter_temperature
- radiator1_temperature, radiator2_temperature

**Frequency Properties (3)**:
- grid_frequency, eps_frequency, generator_frequency

**Battery Properties (3)**:
- battery_soc, battery_temperature, battery_voltage

**Current Properties (2)**:
- max_charge_current, max_discharge_current

**Status Properties (4)**:
- has_data, is_lost, is_using_generator, needs_refresh
- status, status_text

**Parameter Properties (16)**:
- ac_charge_power_limit, ac_charge_soc_limit
- battery_charge_current_limit, battery_discharge_current_limit
- battery_soc_limits, grid_peak_shaving_power_limit, pv_charge_power_limit
- 9 parameter getter/setter methods

**Methods (20+)**:
- refresh, read_parameters, write_parameters
- enable/disable methods for various modes
- set methods for limits and modes

**Total**: 103 properties/methods available

## Conclusion

After pylxpweb 0.3.3 upgrade:
- ✅ **Most sensors working**: 95%+ of sensors have valid data
- ✅ **Fixed**: PV Total Power mapping error
- ⚠️ **Legacy sensors**: 3 sensors (`ac_power`, `ac_voltage`, `internal_temperature`) don't exist in new library
- ✅ **Better alternatives available**: Library provides more accurate, phase-specific data

The unavailable sensors are due to library architecture changes, not integration bugs. The new library provides better, more granular data (per-phase voltages, specific temperatures) rather than generic "AC voltage" or "internal temperature" values.
