# Device Objects Refactoring - BLOCKED

**Date**: November 20, 2025
**Status**: BLOCKED - Waiting for library updates
**Branch**: `feature/device-objects-refactor`

---

## Executive Summary

The device objects refactoring is **BLOCKED** because pylxpweb library is missing critical convenience methods. We **WILL NOT** implement workarounds using `write_parameters()` or `client.api.*` calls.

**Next Action**: Create GitHub issues in pylxpweb repository requesting the missing convenience methods.

---

## What We've Completed ✅

### 1. Core Infrastructure (DONE)
- ✅ `manifest.json`: Updated to `pylxpweb==0.2.2`
- ✅ `config_flow.py`: Uses `Station.load_all()`
- ✅ `coordinator.py`: Uses `Station.load()` and device hierarchy
- ✅ `__init__.py`: Uses `client.close()`
- ✅ `utils.py`: Type hints updated
- ✅ Deleted 1,500+ lines of custom API code

### 2. Documentation (DONE)
- ✅ **DEVICE_OBJECTS_DESIGN_PRINCIPLES.md**: Core principles established
- ✅ **LIBRARY_MISSING_METHODS.md**: Verification checklist
- ✅ **GITHUB_ISSUES_TO_CREATE.md**: 8 detailed issues ready to file
- ✅ **REFACTORING_STATUS.md**: Progress tracking

### 3. Design Principle Established (CRITICAL)
- ✅ NEVER use `client.api.*`
- ✅ NEVER use `write_parameters()` as workaround
- ✅ NO EXCEPTIONS to device object abstraction
- ✅ Create GitHub issues for missing methods
- ✅ Wait for library, don't work around

---

## What's Blocked ❌

### Platform Files Requiring Missing Methods

#### `number.py` - 9 Number Entities
**Status**: BLOCKED

| Entity | Required Method | GitHub Issue |
|--------|----------------|--------------|
| SystemChargeSOCLimitNumber | ✅ `set_battery_soc_limits()` | Exists! |
| OnGridSOCCutoffNumber | ✅ `set_battery_soc_limits()` | Exists! |
| OffGridSOCCutoffNumber | ✅ `set_battery_soc_limits()` | Exists! |
| ACChargePowerNumber | ❌ `set_ac_charge_power()` | Issue #2 |
| PVChargePowerNumber | ❌ `set_pv_charge_power()` | Issue #3 |
| GridPeakShavingPowerNumber | ❌ `set_grid_peak_shaving_power()` | Issue #4 |
| ACChargeSOCLimitNumber | ❌ `set_ac_charge_soc_limit()` | Issue #5 |
| BatteryChargeCurrentNumber | ❌ `set_battery_charge_current()` | Issue #6 |
| BatteryDischargeCurrentNumber | ❌ `set_battery_discharge_current()` | Issue #6 |

**Result**: 3 entities can be refactored now, 6 are blocked

#### `switch.py` - Switch Entities
**Status**: PARTIALLY BLOCKED

| Entity | Required Method | GitHub Issue |
|--------|----------------|--------------|
| Battery Backup Switch | ❌ `enable_battery_backup()` | Issue #1 |
| DST Switch | ❌ `station.set_daylight_saving_time()` | Issue #8 |

**Result**: All switches blocked

#### `select.py` - Operating Mode Select
**Status**: BLOCKED

| Entity | Required Method | GitHub Issue |
|--------|----------------|--------------|
| Operating Mode Select | ⚠️ `set_operating_mode()` | Issue #7 |

**Note**: Has `set_standby_mode()` but not general mode control

#### `button.py` - Refresh Buttons
**Status**: CAN BE REFACTORED ✅

| Entity | Required Method | Status |
|--------|----------------|--------|
| Device Refresh | ✅ `inverter.refresh()` | Exists! |
| Battery Refresh | ✅ `battery.refresh()` | Exists! |
| Station Refresh | ✅ `station.refresh()` | Exists! |

**Result**: All buttons can use device object methods!

---

## Missing Convenience Methods

### Verified Available ✅
- `Station.load_all(client)` - Load all stations
- `Station.load(client, plant_id)` - Load specific station
- `station.refresh_all_data()` - Refresh all devices
- `inverter.get_battery_soc_limits()` - Get SOC limits
- `inverter.set_battery_soc_limits()` - Set SOC limits
- `inverter.set_standby_mode()` - Set standby mode
- `inverter.refresh()` - Refresh inverter data
- `inverter.read_parameters()` - Read parameters
- `inverter.write_parameters()` - Write parameters (LOW-LEVEL, avoid!)
- `battery.refresh()` - Refresh battery data

### Missing (Need GitHub Issues) ❌
1. **Battery Backup Control**:
   - `inverter.enable_battery_backup()`
   - `inverter.disable_battery_backup()`
   - `inverter.get_battery_backup_status()`

2. **AC Charge Power Control**:
   - `inverter.set_ac_charge_power(power_kw)`
   - `inverter.get_ac_charge_power()`

3. **PV Charge Power Control**:
   - `inverter.set_pv_charge_power(power_kw)`
   - `inverter.get_pv_charge_power()`

4. **Grid Peak Shaving Control**:
   - `inverter.set_grid_peak_shaving_power(power_kw)`
   - `inverter.get_grid_peak_shaving_power()`

5. **AC Charge SOC Limit**:
   - `inverter.set_ac_charge_soc_limit(soc_percent)`
   - `inverter.get_ac_charge_soc_limit()`

6. **Battery Current Control**:
   - `inverter.set_battery_charge_current(current_amps)`
   - `inverter.set_battery_discharge_current(current_amps)`
   - `inverter.get_battery_charge_current()`
   - `inverter.get_battery_discharge_current()`

7. **Operating Mode Enhancement**:
   - `inverter.set_operating_mode(mode)`
   - `inverter.operating_mode` property

8. **DST Control**:
   - `station.set_daylight_saving_time(enabled)`
   - `station.daylight_saving_time_enabled` property

---

## Immediate Next Steps

### Step 1: Create GitHub Issues (TODAY)

Go to: https://github.com/joyfulhouse/pylxpweb/issues

Create 8 issues using templates from `GITHUB_ISSUES_TO_CREATE.md`:
1. Battery Backup Control (HIGH PRIORITY)
2. AC Charge Power Control (HIGH PRIORITY)
3. PV Charge Power Control (MEDIUM PRIORITY)
4. Grid Peak Shaving Control (MEDIUM PRIORITY)
5. AC Charge SOC Limit Control (HIGH PRIORITY)
6. Battery Current Control (MEDIUM PRIORITY)
7. Operating Mode Enhancement (LOW PRIORITY)
8. DST Control (LOW PRIORITY)

### Step 2: Partial Refactoring (CAN START NOW)

We CAN refactor these entities that only need existing methods:
- **3 SOC limit number entities** (use existing `set_battery_soc_limits()`)
- **All button entities** (use existing `.refresh()` methods)

### Step 3: Wait for Library Updates

**DO NOT**:
- ❌ Use `write_parameters()` as workaround
- ❌ Use `client.api.*` as workaround
- ❌ Implement low-level parameter mapping

**DO**:
- ✅ Wait for library to add convenience methods
- ✅ Monitor GitHub issues for updates
- ✅ Test new methods when added
- ✅ Update Home Assistant once methods exist

---

## Why We're Waiting

### The Right Way (Device Objects)
```python
# Clean, type-safe, maintainable
inverter = coordinator.get_inverter_object(serial)
success = await inverter.set_ac_charge_power(5.0)
```

### The Wrong Way (Workarounds)
```python
# Error-prone, breaks abstraction, creates tech debt
inverter = coordinator.get_inverter_object(serial)
success = await inverter.write_parameters({register_num: value})
# Which register? What unit? How to validate?
```

**We choose to wait for the right way.**

---

## Partial Refactoring Plan

Since we CAN refactor some entities now, here's the plan:

### Phase A: Refactor What We Can (NOW)

1. **SOC Limit Numbers** (3 entities):
   - `SystemChargeSOCLimitNumber` - Use `set_battery_soc_limits(on_grid_limit=value)`
   - `OnGridSOCCutoffNumber` - Use `set_battery_soc_limits(on_grid_limit=value)`
   - `OffGridSOCCutoffNumber` - Use `set_battery_soc_limits(off_grid_limit=value)`

2. **All Buttons** (refresh buttons):
   - Use `inverter.refresh()`, `battery.refresh()`, `station.refresh()`

3. **Test & Validate**:
   - Ensure entity IDs preserved
   - Test control operations
   - Verify data refresh works

### Phase B: Wait for Library (LATER)

1. **Monitor pylxpweb for updates**
2. **When methods are added**:
   - Update remaining number entities
   - Update switch entities
   - Update select entity
3. **Complete refactoring**
4. **Full testing**
5. **Merge to main**

---

## Success Criteria

### For Partial Refactoring (Phase A)
- [ ] 3 SOC number entities use `set_battery_soc_limits()`
- [ ] All buttons use `.refresh()` methods
- [ ] Zero `client.api.*` calls in refactored files
- [ ] Entity IDs preserved
- [ ] Tests passing for refactored entities

### For Complete Refactoring (Phase B)
- [ ] All GitHub issues created
- [ ] Library adds convenience methods
- [ ] All platform files use device object methods
- [ ] Zero `client.api.*` or low-level `write_parameters()` calls
- [ ] All tests passing
- [ ] Entity IDs preserved
- [ ] Ready to merge

---

## Current Branch Status

**Branch**: `feature/device-objects-refactor`

**Commits**:
1. Core infrastructure refactored
2. Client.api references removed
3. Documentation created
4. Design principles updated (NO workarounds)
5. GitHub issues documented

**Next Commit**: Partial refactoring of entities that can use existing methods

---

## Communication Plan

### To Library Maintainers
- Create detailed GitHub issues
- Provide clear use cases and benefits
- Offer to help test new methods
- Be patient and respectful

### To Home Assistant Users
- Explain why refactoring is taking time
- Emphasize benefits of proper abstraction
- Share timeline once library updates available

---

**Document Status**: ACTIVE - Tracking refactoring blocker
**Last Updated**: November 20, 2025
**Next Review**: After GitHub issues created
