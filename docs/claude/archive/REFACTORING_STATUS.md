# Device Objects Refactoring - Current Status

**Date**: November 20, 2025
**Branch**: `feature/device-objects-refactor`
**Status**: IN PROGRESS - Verification Phase

---

## What We've Accomplished

### ✅ Phase 1: Core Infrastructure (COMPLETE)

1. **manifest.json**: Updated to `pylxpweb==0.2.2`, version `3.0.0`
2. **config_flow.py**: Now uses `Station.load_all()` instead of raw API
3. **coordinator.py**: Uses `Station.load()` and device object hierarchy
4. **__init__.py**: Updated to `client.close()`
5. **utils.py**: Type hints updated for device objects
6. **Deleted**: 1,500+ lines of custom API client code

### ✅ Phase 2: Documentation (COMPLETE)

1. **DEVICE_OBJECTS_DESIGN_PRINCIPLES.md**: Comprehensive usage guide
2. **LIBRARY_MISSING_METHODS.md**: Methods to verify in pylxpweb
3. **Design principle established**: NEVER use `client.api.*`

---

## What Needs to Be Done

### ⏳ Phase 3: Verify Library Methods (CURRENT)

**Action Required**: Check which convenience methods exist in pylxpweb

Run this script to check:
```bash
cd /tmp && source eg4-test/bin/activate && python3 << 'EOF'
from pylxpweb.devices.inverters.base import BaseInverter
import inspect

print("=== Available BaseInverter Methods ===\n")
for name in dir(BaseInverter):
    if not name.startswith('_'):
        attr = getattr(BaseInverter, name)
        if inspect.iscoroutinefunction(attr):
            sig = inspect.signature(attr)
            print(f"async def {name}{sig}")
EOF
```

**Check These Specific Methods**:
- [ ] `enable_battery_backup()`
- [ ] `disable_battery_backup()`
- [ ] `set_ac_charge_power()`
- [ ] `set_pv_charge_power()`
- [ ] `set_grid_peak_shaving_power()`
- [ ] `set_ac_charge_soc_limit()`
- [ ] `set_battery_charge_current()`
- [ ] `set_battery_discharge_current()`
- [ ] `set_operating_mode()`

**We Know These Exist**:
- ✅ `get_battery_soc_limits()` - Confirmed
- ✅ `set_battery_soc_limits()` - Confirmed
- ✅ `set_standby_mode()` - Confirmed
- ✅ `read_parameters()` - Confirmed
- ✅ `write_parameters()` - Confirmed
- ✅ `refresh()` - Confirmed

---

### ⏳ Phase 4: Report Missing Methods (IF NEEDED)

**If methods are missing**:

1. Create issues in pylxpweb repository
2. Provide method signatures and use cases
3. Wait for library update
4. **DO NOT** implement workarounds using `client.api.*`

---

### ⏳ Phase 5: Refactor Platform Files (BLOCKED)

**Blocked Until**: Phase 3 verification complete

**Files to Refactor**:
- `number.py` (9 number entities)
- `switch.py` (battery backup, DST switches)
- `select.py` (operating mode selector)
- `button.py` (refresh buttons)

**Current Issue**: These files have references to `coordinator.api` which no longer exists. They need to be updated to use device object methods.

**Pattern to Use**:
```python
# Get inverter object
inverter = self.coordinator.get_inverter_object(self.serial)

# Use high-level method
success = await inverter.set_battery_soc_limits(on_grid_limit=value)

# Refresh data
await inverter.refresh()
await self.coordinator.async_request_refresh()
```

---

### ⏳ Phase 6: Testing & Validation

Once refactoring is complete:

1. **Type Checking**: `mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/`
2. **Linting**: `ruff check custom_components/eg4_web_monitor/`
3. **Unit Tests**: `pytest tests/ -x`
4. **Entity ID Verification**: Ensure all entity IDs match previous format
5. **Manual Testing**: Test in Docker environment

---

## Known Issues

### Issue 1: `number.py` Still Uses `coordinator.api`

**Problem**: Number entities call `self.coordinator.api` which doesn't exist

**Current Code**:
```python
responses = await read_device_parameters_ranges(
    self.coordinator.api, self.serial
)
```

**Solution**: After Phase 3 verification, update to:
```python
inverter = self.coordinator.get_inverter_object(self.serial)
if hasattr(inverter, 'get_battery_soc_limits'):
    limits = await inverter.get_battery_soc_limits()
else:
    # Report missing method to library
```

---

### Issue 2: Utility Function `read_device_parameters_ranges`

**Problem**: This utility reads parameters manually instead of using device object methods

**Current Approach**: Low-level parameter reading
**Correct Approach**: Use device object convenience methods

**Action**:
1. Check if convenience methods exist in library
2. If yes: Remove utility, use device object methods
3. If no: Report to library, wait for implementation

---

### Issue 3: Platform Files Not Updated

**Problem**: Switch, Select, Button entities may still reference `coordinator.api`

**Action**: Audit all platform files for `coordinator.api` references

**Command**:
```bash
grep -r "coordinator\.api" custom_components/eg4_web_monitor/*.py
```

---

## Commits Made

1. `5fa6469` - refactor: Migrate to pylxpweb device objects (v3.0.0)
2. `7ae6859` - fix: Remove client.api references, use device object methods
3. `3723a67` - docs: Add device object design principles and library verification guide

---

## Next Steps

### Immediate (Today)

1. **Run verification script** to check available methods
2. **Update LIBRARY_MISSING_METHODS.md** with findings
3. **Create GitHub issues** for missing methods (if any)

### Short-term (This Week)

1. **Wait for library updates** (if methods are missing)
2. **Refactor number.py** to use device object methods
3. **Refactor switch.py, select.py, button.py** similarly
4. **Run tests** and validate entity IDs

### Before Merge

1. All platform files using device object methods
2. Zero references to `client.api.*` anywhere
3. All tests passing
4. Entity IDs verified unchanged
5. Manual testing in Docker complete

---

## Success Criteria

- [ ] No `client.api.*` calls anywhere in integration
- [ ] All control operations use device object methods
- [ ] Missing methods reported to library (if any)
- [ ] All tests passing
- [ ] Entity IDs preserved
- [ ] Type checking passes
- [ ] Linting passes

---

## Questions for User

1. Should we wait for library updates before completing refactor?
2. Or should we complete refactor using available methods and circle back later?
3. Are there any specific methods you know exist in the library that I should check?

---

**Document Status**: ACTIVE - Updated after documentation phase
**Last Updated**: November 20, 2025
**Branch Status**: Committed, ready for verification phase
