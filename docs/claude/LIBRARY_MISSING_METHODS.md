# pylxpweb Library - Missing Device Object Methods

**Date**: November 20, 2025
**Library**: pylxpweb==0.2.2
**Status**: NEEDS INVESTIGATION & REPORTING

---

## Purpose

This document tracks functionality that may be missing from the pylxpweb device objects. Before implementing workarounds using `client.api.*`, we should verify these methods exist or request them to be added to the library.

---

## Methods to Verify

### 1. Battery Backup Control

**Current Usage**: Number/switch entities need to enable/disable battery backup

**Expected Device Object Methods**:
```python
inverter = station.all_inverters[0]

# Enable battery backup (EPS mode)
success = await inverter.enable_battery_backup()

# Disable battery backup
success = await inverter.disable_battery_backup()

# Get current battery backup status
status = inverter.battery_backup_enabled  # Property or method?
```

**Check**:
- [ ] Does `BaseInverter` have `enable_battery_backup()` method?
- [ ] Does `BaseInverter` have `disable_battery_backup()` method?
- [ ] Does `BaseInverter` have `battery_backup_enabled` property?

**If Missing**: This should be added to `pylxpweb/devices/inverters/base.py`

---

### 2. Daylight Saving Time Control

**Current Usage**: Switch entity for DST control

**Expected Device Object Method**:
```python
station = await Station.load(client, plant_id)

# Enable DST
success = await station.set_daylight_saving_time(enabled=True)

# Or on plant-level object?
# success = await plant.set_daylight_saving_time(enabled=True)
```

**Check**:
- [ ] Does `Station` have `set_daylight_saving_time()` method?
- [ ] Is there a separate `Plant` class that has this method?
- [ ] Does `Station` have `daylight_saving_time_enabled` property?

**If Missing**: This should be added to `pylxpweb/devices/station.py`

---

### 3. AC Charge Power Control

**Current Usage**: Number entity for AC charge power limit

**Expected Device Object Method**:
```python
inverter = station.all_inverters[0]

# Set AC charge power limit (kW)
success = await inverter.set_ac_charge_power(power_kw=5.0)

# Get current AC charge power limit
current_power = await inverter.get_ac_charge_power()
# Or as property: current_power = inverter.ac_charge_power_limit
```

**Check**:
- [ ] Does `BaseInverter` have `set_ac_charge_power()` method?
- [ ] Does `BaseInverter` have `get_ac_charge_power()` method?
- [ ] Does `BaseInverter` have `ac_charge_power_limit` property?

**If Missing**: This should be added to `pylxpweb/devices/inverters/base.py`

---

### 4. PV Charge Power Control

**Current Usage**: Number entity for PV charge power limit

**Expected Device Object Method**:
```python
inverter = station.all_inverters[0]

# Set PV charge power limit (kW)
success = await inverter.set_pv_charge_power(power_kw=10.0)

# Get current PV charge power limit
current_power = await inverter.get_pv_charge_power()
# Or as property: current_power = inverter.pv_charge_power_limit
```

**Check**:
- [ ] Does `BaseInverter` have `set_pv_charge_power()` method?
- [ ] Does `BaseInverter` have `get_pv_charge_power()` method?
- [ ] Does `BaseInverter` have `pv_charge_power_limit` property?

**If Missing**: This should be added to `pylxpweb/devices/inverters/base.py`

---

### 5. Grid Peak Shaving Power Control

**Current Usage**: Number entity for grid peak shaving power limit

**Expected Device Object Method**:
```python
inverter = station.all_inverters[0]

# Set grid peak shaving power limit (kW)
success = await inverter.set_grid_peak_shaving_power(power_kw=7.0)

# Get current grid peak shaving power limit
current_power = await inverter.get_grid_peak_shaving_power()
# Or as property: current_power = inverter.grid_peak_shaving_power_limit
```

**Check**:
- [ ] Does `BaseInverter` have `set_grid_peak_shaving_power()` method?
- [ ] Does `BaseInverter` have `get_grid_peak_shaving_power()` method?
- [ ] Does `BaseInverter` have `grid_peak_shaving_power_limit` property?

**If Missing**: This should be added to `pylxpweb/devices/inverters/base.py`

---

### 6. AC Charge SOC Limit Control

**Current Usage**: Number entity for AC charge stop SOC

**Expected Device Object Method**:
```python
inverter = station.all_inverters[0]

# Set AC charge SOC limit (when to stop AC charging)
success = await inverter.set_ac_charge_soc_limit(soc_percent=90)

# Get current AC charge SOC limit
current_limit = await inverter.get_ac_charge_soc_limit()
# Or as property: current_limit = inverter.ac_charge_soc_limit
```

**Check**:
- [ ] Does `BaseInverter` have `set_ac_charge_soc_limit()` method?
- [ ] Does `BaseInverter` have `get_ac_charge_soc_limit()` method?
- [ ] Does `BaseInverter` have `ac_charge_soc_limit` property?

**If Missing**: This should be added to `pylxpweb/devices/inverters/base.py`

**Note**: This is different from `set_battery_soc_limits()` which sets discharge cutoffs

---

### 7. Battery Charge/Discharge Current Control

**Current Usage**: Number entities for battery charge/discharge current limits

**Expected Device Object Methods**:
```python
inverter = station.all_inverters[0]

# Set battery charge current limit (Amps)
success = await inverter.set_battery_charge_current(current_amps=100)

# Set battery discharge current limit (Amps)
success = await inverter.set_battery_discharge_current(current_amps=120)

# Get current limits
charge_limit = await inverter.get_battery_charge_current()
discharge_limit = await inverter.get_battery_discharge_current()
```

**Check**:
- [ ] Does `BaseInverter` have `set_battery_charge_current()` method?
- [ ] Does `BaseInverter` have `set_battery_discharge_current()` method?
- [ ] Does `BaseInverter` have `get_battery_charge_current()` method?
- [ ] Does `BaseInverter` have `get_battery_discharge_current()` method?

**If Missing**: These should be added to `pylxpweb/devices/inverters/base.py`

---

### 8. Operating Mode Control (Quick Charge/Discharge)

**Current Usage**: Select entity for operating mode selection

**Expected Device Object Methods**:
```python
inverter = station.all_inverters[0]

# Set operating mode
success = await inverter.set_operating_mode("normal")  # or "quick_charge", "quick_discharge"

# Get current operating mode
mode = inverter.operating_mode  # Property: "normal", "standby", "quick_charge", etc.
```

**Check**:
- [ ] Does `BaseInverter` have `set_operating_mode()` method?
- [ ] Does `BaseInverter` have `operating_mode` property?
- [ ] What are the valid mode strings?

**Note**: We know `set_standby_mode(True/False)` exists, but is there a more general method?

**If Missing**: Enhanced operating mode control should be added to `pylxpweb/devices/inverters/base.py`

---

## Investigation Script

Use this script to check what methods actually exist:

```python
from pylxpweb.devices.inverters.base import BaseInverter
from pylxpweb.devices import Station
import inspect

print("=== BaseInverter Methods ===")
for name in dir(BaseInverter):
    if not name.startswith('_'):
        attr = getattr(BaseInverter, name)
        if callable(attr):
            if inspect.iscoroutinefunction(attr):
                sig = inspect.signature(attr)
                print(f"async def {name}{sig}")
            elif isinstance(attr, property):
                print(f"@property {name}")
            else:
                print(f"def {name}(...)")

print("\n=== Station Methods ===")
for name in dir(Station):
    if not name.startswith('_'):
        attr = getattr(Station, name)
        if callable(attr):
            if inspect.iscoroutinefunction(attr):
                sig = inspect.signature(attr)
                print(f"async def {name}{sig}")
            elif isinstance(attr, property):
                print(f"@property {name}")
```

---

## Alternative: Check pylxpweb Source Code

**Repository**: https://github.com/joyfulhouse/pylxpweb

**Files to Check**:
1. `pylxpweb/devices/inverters/base.py` - BaseInverter class
2. `pylxpweb/devices/station.py` - Station class
3. `pylxpweb/devices/battery.py` - Battery class

---

## Action Items

1. **Verify Existing Methods**: Run investigation script to check what exists
2. **Document Findings**: Update checkboxes above with results
3. **Group by Status**:
   - ✅ **Exists**: Use the device object method
   - ⚠️ **Exists but Different**: Adapt our code to match library pattern
   - ❌ **Missing**: Report to library maintainers

4. **For Missing Methods**: Create issues in pylxpweb repo with:
   - Use case description
   - Proposed method signature
   - Example usage
   - Benefits of adding to library

---

## Next Steps

Once we've verified what exists in the library:

1. **For existing methods**: Update Home Assistant integration to use them
2. **For missing methods**:
   - Create GitHub issues in pylxpweb repository
   - Propose method signatures and implementations
   - Wait for library update OR contribute PR to library
   - NEVER implement workarounds using `client.api.*` in Home Assistant

---

**Document Status**: NEEDS VERIFICATION
**Priority**: HIGH - Blocks completion of device object refactoring
**Assigned**: Review pylxpweb library source code
