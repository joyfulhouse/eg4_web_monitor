# Sensor Definitions for Full Property Exposure - COMPLETED ✅

## Summary

**Status**: All sensor definitions have been added to const.py as of 2025-11-22.

The integration now exposes all available properties from battery and inverter objects:
- **Batteries**: All 39 properties exposed (100%) - 14 new sensor definitions added
- **Inverters**: All 70 properties exposed (100%) - 2 new sensor definitions added (status_code already existed)

## Required Changes

### 1. Battery Sensor Definitions (const.py)

Add these 14 new battery sensor definitions after line 537 in const.py:

```python
"battery_max_cell_temp": {
    "name": "Max Cell Temperature",
    "unit": UnitOfTemperature.CELSIUS,
    "device_class": "temperature",
    "state_class": "measurement",
    "icon": "mdi:thermometer-high",
    "entity_category": "diagnostic",
},
"battery_min_cell_temp": {
    "name": "Min Cell Temperature",
    "unit": UnitOfTemperature.CELSIUS,
    "device_class": "temperature",
    "state_class": "measurement",
    "icon": "mdi:thermometer-low",
    "entity_category": "diagnostic",
},
"battery_max_cell_voltage": {
    "name": "Max Cell Voltage",
    "unit": UnitOfElectricPotential.VOLT,
    "device_class": "voltage",
    "state_class": "measurement",
    "icon": "mdi:battery-plus",
    "entity_category": "diagnostic",
},
"battery_min_cell_voltage": {
    "name": "Min Cell Voltage",
    "unit": UnitOfElectricPotential.VOLT,
    "device_class": "voltage",
    "state_class": "measurement",
    "icon": "mdi:battery-minus",
    "entity_category": "diagnostic",
},
"battery_cell_voltage_delta": {
    "name": "Cell Voltage Delta",
    "unit": UnitOfElectricPotential.VOLT,
    "device_class": "voltage",
    "state_class": "measurement",
    "icon": "mdi:delta",
    "entity_category": "diagnostic",
},
"battery_cell_temp_delta": {
    "name": "Cell Temperature Delta",
    "unit": UnitOfTemperature.CELSIUS,
    "device_class": "temperature",
    "state_class": "measurement",
    "icon": "mdi:delta",
    "entity_category": "diagnostic",
},
"battery_discharge_capacity": {
    "name": "Discharge Capacity",
    "unit": "Ah",
    "icon": "mdi:battery-arrow-down",
    "entity_category": "diagnostic",
},
"battery_charge_voltage_ref": {
    "name": "Charge Voltage Reference",
    "unit": UnitOfElectricPotential.VOLT,
    "device_class": "voltage",
    "state_class": "measurement",
    "icon": "mdi:battery-charging",
    "entity_category": "diagnostic",
},
"battery_serial_number": {
    "name": "Serial Number",
    "icon": "mdi:identifier",
    "entity_category": "diagnostic",
},
"battery_type": {
    "name": "Battery Type Code",
    "icon": "mdi:battery",
    "entity_category": "diagnostic",
},
"battery_type_text": {
    "name": "Battery Type",
    "icon": "mdi:battery-sync",
    "entity_category": "diagnostic",
},
"battery_bms_model": {
    "name": "BMS Model",
    "icon": "mdi:chip",
    "entity_category": "diagnostic",
},
"battery_model": {
    "name": "Model",
    "icon": "mdi:information",
    "entity_category": "diagnostic",
},
"battery_index": {
    "name": "Index",
    "icon": "mdi:numeric",
    "entity_category": "diagnostic",
},
```

### 2. Inverter Sensor Definitions (const.py)

Add these 3 new inverter sensor definitions:

```python
"grid_import_power": {
    "name": "Grid Import Power",
    "unit": UnitOfPower.WATT,
    "device_class": "power",
    "state_class": "measurement",
    "icon": "mdi:transmission-tower-import",
},
"grid_export_power": {
    "name": "Grid Export Power",
    "unit": UnitOfPower.WATT,
    "device_class": "power",
    "state_class": "measurement",
    "icon": "mdi:transmission-tower-export",
},
"status_code": {
    "name": "Status Code",
    "icon": "mdi:information",
    "entity_category": "diagnostic",
},
```

## Property Mapping Updates Already Complete

The coordinator.py file has been updated to include:

✅ **Battery properties**: Expanded from 17 to 33 mappings (all 39 properties covered including calculated ones)
✅ **Inverter properties**: Expanded from 54 to 58 mappings

## Expected Results After Adding Sensor Definitions

### Battery Devices
Each battery will have **~35 sensors** instead of 7:
- Core metrics: voltage, current, power, SoC, SoH
- Temperatures: MOS, ambient, max/min cell temps with cell numbers
- Cell voltages: max/min with cell numbers, delta
- Capacity: remaining, full, design, discharge
- Metadata: serial number, type, BMS model, index
- Lifecycle: cycle count, firmware version

### Inverter Devices
Each inverter will have **~105 sensors** instead of 101:
- Added: grid_import_power, grid_export_power, status_code
- All energy accumulation sensors (from 0.3.3 upgrade)
- All power, voltage, frequency, temperature sensors

## Implementation Steps - COMPLETED ✅

1. ✅ Added 14 battery sensor definitions to const.py after line 537
2. ✅ Added 2 new inverter sensor definitions (grid_import_power, grid_export_power) - status_code already existed
3. ✅ Validated with mypy (zero errors) and ruff (all checks passed)
4. **Next**: Restart Home Assistant
5. **Next**: Verify battery devices now show full sensor list (~35 sensors per battery)
6. **Next**: Check entity registry for new sensors

## Notes

- All new battery sensors are marked with `entity_category: "diagnostic"` to keep the main device view clean
- The property mappings in coordinator.py are already complete
- This change is purely additive - no existing sensors are affected
- Battery devices should become fully visible in Home Assistant after this change
