# GitHub Issues for pylxpweb Library

**Repository**: https://github.com/joyfulhouse/pylxpweb/issues
**Date**: November 20, 2025
**Status**: ISSUES TO BE CREATED

---

## Issue Template

Use this template for each missing convenience method:

```markdown
## Missing Convenience Method: [Method Name]

### Current Situation
To perform [operation description], Home Assistant integration must use low-level `write_parameters()` or `client.api.*` calls, which defeats the purpose of the device object abstraction.

### Proposed Convenience Method

**Class**: `BaseInverter` (or `Station`, `Battery` as appropriate)
**Method Name**: `[method_name]`
**Method Signature**:
```python
async def [method_name](self, [parameters]) -> bool:
    """[Description]

    Args:
        [parameter descriptions]

    Returns:
        True if successful, False otherwise
    """
```

### Example Usage

```python
# Current workaround (WRONG)
await inverter.write_parameters({register: value})

# Proposed convenience method (CORRECT)
success = await inverter.[method_name]([parameters])
```

### Benefits
- Type-safe, high-level interface
- Clear intent and error handling
- Consistent with existing methods like `set_battery_soc_limits()`
- Reduces Home Assistant integration complexity
- Makes the library easier to use for all consumers

### Implementation Notes
[Any notes about parameter mapping, validation, etc.]
```

---

## Issues to Create

### Issue 1: Battery Backup Control

**Title**: Add `enable_battery_backup()` and `disable_battery_backup()` convenience methods

**Description**:
```markdown
## Missing Convenience Method: Battery Backup Control

### Current Situation
To enable/disable battery backup (EPS mode), Home Assistant integration must use low-level parameter writes, which defeats the purpose of the device object abstraction.

### Proposed Convenience Methods

**Class**: `BaseInverter`

```python
async def enable_battery_backup(self) -> bool:
    """Enable battery backup (EPS) mode.

    Returns:
        True if successful, False otherwise
    """

async def disable_battery_backup(self) -> bool:
    """Disable battery backup (EPS) mode.

    Returns:
        True if successful, False otherwise
    """

async def get_battery_backup_status(self) -> bool:
    """Get current battery backup status.

    Returns:
        True if enabled, False if disabled
    """
```

### Example Usage

```python
# Enable battery backup
inverter = station.all_inverters[0]
success = await inverter.enable_battery_backup()

# Disable battery backup
success = await inverter.disable_battery_backup()

# Check status
is_enabled = await inverter.get_battery_backup_status()
```

### Benefits
- Clear, type-safe interface for common operation
- Consistent with existing `set_standby_mode()` pattern
- Eliminates need for parameter name knowledge (FUNC_EPS_EN)
- Better error handling and validation

### Implementation Notes
- Maps to `FUNC_EPS_EN` parameter
- Should validate device supports EPS mode
- Consider adding `battery_backup_enabled` property for cached status
```

---

### Issue 2: AC Charge Power Control

**Title**: Add `set_ac_charge_power()` and `get_ac_charge_power()` convenience methods

**Description**:
```markdown
## Missing Convenience Method: AC Charge Power Control

### Current Situation
To control AC charge power limit, Home Assistant integration must use low-level `write_parameters()`, which defeats the purpose of the device object abstraction.

### Proposed Convenience Methods

**Class**: `BaseInverter`

```python
async def set_ac_charge_power(self, power_kw: float) -> bool:
    """Set AC charge power limit.

    Args:
        power_kw: Power limit in kilowatts (0.0 to 15.0)

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If power_kw is out of valid range
    """

async def get_ac_charge_power(self) -> float:
    """Get current AC charge power limit.

    Returns:
        Current power limit in kilowatts
    """
```

### Example Usage

```python
# Set AC charge power to 5 kW
inverter = station.all_inverters[0]
success = await inverter.set_ac_charge_power(5.0)

# Get current setting
current_power = await inverter.get_ac_charge_power()
```

### Benefits
- Type-safe with range validation
- Clear intent - no need to know parameter names
- Consistent with other control methods
- Handles unit conversion internally

### Implementation Notes
- Maps to `HOLD_AC_CHARGE_POWER_CMD` parameter
- Should validate range (0.0 to 15.0 kW typically)
- Consider device-specific maximum values
```

---

### Issue 3: PV Charge Power Control

**Title**: Add `set_pv_charge_power()` and `get_pv_charge_power()` convenience methods

**Description**:
```markdown
## Missing Convenience Method: PV Charge Power Control

### Current Situation
To control PV charge power limit, Home Assistant integration must use low-level `write_parameters()`.

### Proposed Convenience Methods

**Class**: `BaseInverter`

```python
async def set_pv_charge_power(self, power_kw: float) -> bool:
    """Set PV charge power limit.

    Args:
        power_kw: Power limit in kilowatts (0.0 to device maximum)

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If power_kw is out of valid range
    """

async def get_pv_charge_power(self) -> float:
    """Get current PV charge power limit.

    Returns:
        Current power limit in kilowatts
    """
```

### Example Usage

```python
# Set PV charge power to 10 kW
inverter = station.all_inverters[0]
success = await inverter.set_pv_charge_power(10.0)

# Get current setting
current_power = await inverter.get_pv_charge_power()
```

### Benefits
- Clear, type-safe interface
- Handles validation and unit conversion
- Consistent with AC charge power control

### Implementation Notes
- Maps to appropriate PV charge power parameter
- Maximum value may be device-specific
- Should validate against device capabilities
```

---

### Issue 4: Grid Peak Shaving Control

**Title**: Add `set_grid_peak_shaving_power()` and `get_grid_peak_shaving_power()` convenience methods

**Description**:
```markdown
## Missing Convenience Method: Grid Peak Shaving Control

### Current Situation
To control grid peak shaving power limit, Home Assistant integration must use low-level `write_parameters()`.

### Proposed Convenience Methods

**Class**: `BaseInverter`

```python
async def set_grid_peak_shaving_power(self, power_kw: float) -> bool:
    """Set grid peak shaving power limit.

    Args:
        power_kw: Power limit in kilowatts (0.0 to device maximum)

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If power_kw is out of valid range
    """

async def get_grid_peak_shaving_power(self) -> float:
    """Get current grid peak shaving power limit.

    Returns:
        Current power limit in kilowatts
    """
```

### Example Usage

```python
# Set grid peak shaving to 7 kW
inverter = station.all_inverters[0]
success = await inverter.set_grid_peak_shaving_power(7.0)

# Get current setting
current_power = await inverter.get_grid_peak_shaving_power()
```

### Benefits
- Clear interface for peak shaving configuration
- Type-safe with validation
- Easier for users to understand than raw parameters

### Implementation Notes
- Maps to grid peak shaving parameter
- May need device capability checks
```

---

### Issue 5: AC Charge SOC Limit Control

**Title**: Add `set_ac_charge_soc_limit()` and `get_ac_charge_soc_limit()` convenience methods

**Description**:
```markdown
## Missing Convenience Method: AC Charge SOC Limit Control

### Current Situation
To control AC charge stop SOC percentage, Home Assistant integration must use low-level `write_parameters()`. This is different from the discharge SOC limits provided by `set_battery_soc_limits()`.

### Proposed Convenience Methods

**Class**: `BaseInverter`

```python
async def set_ac_charge_soc_limit(self, soc_percent: int) -> bool:
    """Set AC charge stop SOC limit (when to stop AC charging).

    Args:
        soc_percent: SOC percentage (0 to 100)

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If soc_percent is out of valid range (0-100)
    """

async def get_ac_charge_soc_limit(self) -> int:
    """Get current AC charge stop SOC limit.

    Returns:
        Current SOC limit percentage
    """
```

### Example Usage

```python
# Set AC charging to stop at 90% SOC
inverter = station.all_inverters[0]
success = await inverter.set_ac_charge_soc_limit(90)

# Get current setting
current_limit = await inverter.get_ac_charge_soc_limit()
```

### Benefits
- Clear distinction from discharge SOC limits
- Type-safe with range validation (0-100)
- Consistent with existing SOC control methods

### Implementation Notes
- This is a charging stop limit (different from discharge cutoff)
- Maps to AC charge SOC limit parameter
- Should validate 0-100 range
```

---

### Issue 6: Battery Current Control

**Title**: Add `set_battery_charge_current()`, `set_battery_discharge_current()`, and getter methods

**Description**:
```markdown
## Missing Convenience Methods: Battery Current Control

### Current Situation
To control battery charge/discharge current limits, Home Assistant integration must use low-level `write_parameters()`.

### Proposed Convenience Methods

**Class**: `BaseInverter`

```python
async def set_battery_charge_current(self, current_amps: int) -> bool:
    """Set battery charge current limit.

    Args:
        current_amps: Current limit in amperes (0 to device maximum)

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If current_amps is out of valid range
    """

async def set_battery_discharge_current(self, current_amps: int) -> bool:
    """Set battery discharge current limit.

    Args:
        current_amps: Current limit in amperes (0 to device maximum)

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If current_amps is out of valid range
    """

async def get_battery_charge_current(self) -> int:
    """Get current battery charge current limit.

    Returns:
        Current limit in amperes
    """

async def get_battery_discharge_current(self) -> int:
    """Get current battery discharge current limit.

    Returns:
        Current limit in amperes
    """
```

### Example Usage

```python
# Set battery charge current to 100A
inverter = station.all_inverters[0]
success = await inverter.set_battery_charge_current(100)

# Set battery discharge current to 120A
success = await inverter.set_battery_discharge_current(120)

# Get current settings
charge_limit = await inverter.get_battery_charge_current()
discharge_limit = await inverter.get_battery_discharge_current()
```

### Benefits
- Type-safe current control
- Device-specific validation of maximum values
- Clear, separated charge vs discharge control
- Consistent with other power/current control methods

### Implementation Notes
- Maps to battery charge/discharge current parameters
- Maximum values are device-specific
- Should validate against battery capabilities
```

---

### Issue 7: Operating Mode Control Enhancement

**Title**: Enhance `set_standby_mode()` or add general `set_operating_mode()` method

**Description**:
```markdown
## Enhancement: General Operating Mode Control

### Current Situation
The library has `set_standby_mode(standby: bool)` but doesn't provide control for other operating modes like Quick Charge, Quick Discharge, etc.

### Proposed Enhancement

**Option A**: Add general operating mode method

**Class**: `BaseInverter`

```python
from enum import Enum

class OperatingMode(Enum):
    """Inverter operating modes."""
    NORMAL = "normal"
    STANDBY = "standby"
    QUICK_CHARGE = "quick_charge"
    QUICK_DISCHARGE = "quick_discharge"

async def set_operating_mode(self, mode: OperatingMode) -> bool:
    """Set inverter operating mode.

    Args:
        mode: Operating mode to set

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If mode is not supported by this device
    """

@property
def operating_mode(self) -> OperatingMode:
    """Get current operating mode.

    Returns:
        Current operating mode
    """
```

**Option B**: Add specific methods for each mode

```python
async def enable_quick_charge(self) -> bool:
    """Enable quick charge mode."""

async def enable_quick_discharge(self) -> bool:
    """Enable quick discharge mode."""

async def set_normal_mode(self) -> bool:
    """Set normal operating mode."""
```

### Example Usage

```python
# Option A: Enum-based
inverter = station.all_inverters[0]
success = await inverter.set_operating_mode(OperatingMode.QUICK_CHARGE)
current_mode = inverter.operating_mode

# Option B: Method-based
success = await inverter.enable_quick_charge()
```

### Benefits
- Type-safe operating mode control
- Clear, semantic interface
- Prevents invalid mode combinations
- Better than `set_standby_mode(True/False)` for multiple modes

### Implementation Notes
- Should replace or extend current `set_standby_mode()`
- Some modes may not be available on all devices
- Should validate mode availability
```

---

### Issue 8: Daylight Saving Time Control

**Title**: Add `set_daylight_saving_time()` method to Station class

**Description**:
```markdown
## Missing Convenience Method: Daylight Saving Time Control

### Current Situation
To control DST settings, Home Assistant integration must use low-level API calls. This is a station-level (plant-level) setting, not inverter-level.

### Proposed Convenience Method

**Class**: `Station`

```python
async def set_daylight_saving_time(self, enabled: bool) -> bool:
    """Set daylight saving time adjustment.

    Args:
        enabled: True to enable DST, False to disable

    Returns:
        True if successful, False otherwise
    """

@property
def daylight_saving_time_enabled(self) -> bool:
    """Get current DST setting.

    Returns:
        True if DST is enabled, False otherwise
    """
```

### Example Usage

```python
# Enable DST for the station
station = await Station.load(client, plant_id)
success = await station.set_daylight_saving_time(True)

# Check current setting
is_dst_enabled = station.daylight_saving_time_enabled
```

### Benefits
- Station-level setting properly placed on Station class
- Type-safe boolean interface
- Consistent with other control methods

### Implementation Notes
- This is a station/plant-level setting, not device-specific
- Maps to DST control API endpoint
- Should be cached in station metadata
```

---

## Priority Order

Based on Home Assistant integration needs:

1. **HIGH PRIORITY** (Blocks basic functionality):
   - Issue 1: Battery Backup Control
   - Issue 2: AC Charge Power Control
   - Issue 5: AC Charge SOC Limit Control

2. **MEDIUM PRIORITY** (Important but workarounds exist):
   - Issue 3: PV Charge Power Control
   - Issue 4: Grid Peak Shaving Control
   - Issue 6: Battery Current Control

3. **LOW PRIORITY** (Enhancement):
   - Issue 7: Operating Mode Control Enhancement
   - Issue 8: Daylight Saving Time Control

---

## Action Plan

1. ✅ **Create all issues in pylxpweb repository** - DONE
2. ✅ **Do NOT implement workarounds in Home Assistant** - Policy enforced
3. ⏳ **Wait for library to add convenience methods** - In progress
4. ⏳ **Once methods are added, update Home Assistant to use them** - Pending
5. ✅ **NEVER use `write_parameters()` or `client.api.*` as workarounds** - Policy enforced

---

## Created Issues

All issues have been created in the pylxpweb repository:

1. ✅ [Issue #8](https://github.com/joyfulhouse/pylxpweb/issues/8) - Battery Backup Control (HIGH PRIORITY)
2. ✅ [Issue #9](https://github.com/joyfulhouse/pylxpweb/issues/9) - AC Charge Power Control (HIGH PRIORITY)
3. ✅ [Issue #10](https://github.com/joyfulhouse/pylxpweb/issues/10) - PV Charge Power Control (MEDIUM PRIORITY)
4. ✅ [Issue #11](https://github.com/joyfulhouse/pylxpweb/issues/11) - Grid Peak Shaving Control (MEDIUM PRIORITY)
5. ✅ [Issue #12](https://github.com/joyfulhouse/pylxpweb/issues/12) - AC Charge SOC Limit Control (HIGH PRIORITY)
6. ✅ [Issue #13](https://github.com/joyfulhouse/pylxpweb/issues/13) - Battery Current Control (MEDIUM PRIORITY)
7. ✅ [Issue #14](https://github.com/joyfulhouse/pylxpweb/issues/14) - Operating Mode Enhancement (LOW PRIORITY)
8. ✅ [Issue #15](https://github.com/joyfulhouse/pylxpweb/issues/15) - DST Control (LOW PRIORITY)

---

**Document Status**: ISSUES CREATED - Waiting for library updates
**Repository**: https://github.com/joyfulhouse/pylxpweb/issues
**Date Created**: November 20, 2025
**Next Step**: Monitor issues and proceed with partial refactoring of entities using existing methods
