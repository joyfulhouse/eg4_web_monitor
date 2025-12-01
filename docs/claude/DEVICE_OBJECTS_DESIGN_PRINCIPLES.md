# Device Objects Design Principles

**Date**: November 20, 2025
**Status**: CRITICAL ARCHITECTURE GUIDELINES
**Priority**: MUST FOLLOW

---

## Core Principle: NEVER Use `client.api.*`

**Rule**: The integration must NEVER directly call `client.api.*` methods. Always use the high-level device object abstraction provided by pylxpweb.

### Why?

1. **Abstraction Layer**: Device objects encapsulate the complexity of API calls
2. **Type Safety**: Device objects provide Pydantic models with validation
3. **Convenience Methods**: Device objects have high-level methods for common operations
4. **Data Management**: Device objects manage their own state and refresh cycles
5. **Future-Proof**: Changes to the underlying API are handled by the library

### Exception: THERE ARE NO EXCEPTIONS

If a feature requires `client.api.*` calls OR low-level `write_parameters()` calls because the device objects don't provide the necessary convenience methods:

1. **STOP IMPLEMENTATION IMMEDIATELY**
2. **Document the missing convenience method**
3. **Open an issue at https://github.com/joyfulhouse/pylxpweb/issues**
4. **Wait for the library to add the convenience method**
5. **NEVER work around it by using `write_parameters()` or `client.api.*`**

**Why No Workarounds?**
- Using `write_parameters()` defeats the purpose of device object abstraction
- Low-level parameter writes are error-prone and hard to maintain
- The library should provide high-level, type-safe convenience methods
- Working around missing methods creates technical debt
- The library maintainers need to know what methods are needed

---

## Device Object Hierarchy

```
LuxpowerClient (context manager)
└── Station.load_all(client) → list[Station]
    └── Station.load(client, plant_id) → Station
        ├── station.all_inverters → list[BaseInverter]
        │   ├── inverter.runtime → InverterRuntime (Pydantic model)
        │   ├── inverter.energy → EnergyInfo (Pydantic model)
        │   └── inverter.battery_bank → BatteryBank
        │       └── battery_bank.batteries → list[Battery]
        └── station.parallel_groups → list[ParallelGroup]
            ├── parallel_group.mid_device → MIDDevice (GridBOSS)
            └── parallel_group.inverters → list[BaseInverter]
```

---

## Correct Usage Patterns

### 1. Loading Station Data

**❌ WRONG - Using Raw API:**
```python
# DON'T DO THIS!
async with LuxpowerClient(...) as client:
    plants = await client.api.plants.get_plants()
    for plant in plants.rows:
        devices = await client.api.devices.get_devices(plant.plantId)
```

**✅ CORRECT - Using Device Objects:**
```python
# Do this instead!
async with LuxpowerClient(...) as client:
    stations = await Station.load_all(client)
    for station in stations:
        for inverter in station.all_inverters:
            # Access data via object properties
            pv_power = inverter.runtime.ppv
```

---

### 2. Reading Inverter Data

**❌ WRONG - Manual API Calls:**
```python
# DON'T DO THIS!
runtime = await client.api.devices.get_inverter_runtime(serial)
battery = await client.api.devices.get_battery_info(serial)
```

**✅ CORRECT - Using Inverter Objects:**
```python
# Do this instead!
inverter = coordinator.get_inverter_object(serial)
await inverter.refresh()  # Refreshes runtime, energy, and battery data

# Access via properties
pv_power = inverter.runtime.ppv
soc = inverter.runtime.soc
battery_voltage = inverter.battery_bank.batteries[0].voltage
```

---

### 3. Reading Device Parameters

**❌ WRONG - Low-Level Parameter Reads:**
```python
# DON'T DO THIS!
params = await client.api.control.read_parameters(serial, 0, 127)
soc_limit = params.parameters.get("HOLD_SYSTEM_CHARGE_SOC_LIMIT")
```

**✅ CORRECT - Using Convenience Methods:**
```python
# Do this instead!
inverter = coordinator.get_inverter_object(serial)
limits = await inverter.get_battery_soc_limits()

on_grid_limit = limits["on_grid_soc_limit"]
off_grid_limit = limits["off_grid_soc_limit"]
```

---

### 4. Writing Device Parameters

**❌ WRONG - Low-Level Parameter Writes:**
```python
# DON'T DO THIS!
await client.api.control.write_parameter(
    serial=serial,
    hold_param="HOLD_SYSTEM_CHARGE_SOC_LIMIT",
    value_text="10"
)
```

**✅ CORRECT - Using Convenience Methods:**
```python
# Do this instead!
inverter = coordinator.get_inverter_object(serial)
success = await inverter.set_battery_soc_limits(
    on_grid_limit=10,
    off_grid_limit=5
)

if success:
    await inverter.refresh()
```

---

### 5. Controlling Operating Mode

**❌ WRONG - Raw Parameter Control:**
```python
# DON'T DO THIS!
await client.api.control.write_parameters(serial, {21: 0})  # Standby mode
```

**✅ CORRECT - Using Control Methods:**
```python
# Do this instead!
inverter = coordinator.get_inverter_object(serial)
success = await inverter.set_standby_mode(standby=True)

if success:
    await inverter.refresh()
```

---

### 6. Battery Backup Control

**❌ WRONG - Raw API Calls:**
```python
# DON'T DO THIS!
await client.api.control.enable_battery_backup(serial)
```

**✅ CORRECT - Using Device Object Methods:**
```python
# Do this instead - IF the method exists on inverter object
inverter = coordinator.get_inverter_object(serial)
# Check if method exists first:
if hasattr(inverter, 'enable_battery_backup'):
    await inverter.enable_battery_backup()
else:
    # REPORT TO LIBRARY: Missing convenience method
    # DO NOT fall back to client.api - fix the library!
    _LOGGER.error("Battery backup control not available on device objects")
```

---

## Available Device Object Methods

### Station Methods

```python
# Loading
stations = await Station.load_all(client)  # Load all stations
station = await Station.load(client, plant_id)  # Load specific station

# Properties
station.id                  # int - Plant ID
station.name                # str - Station name
station.location            # Location - Geographic info
station.all_inverters       # list[BaseInverter] - All inverters
station.all_batteries       # list[Battery] - All batteries
station.parallel_groups     # list[ParallelGroup] - Parallel groups
station.standalone_inverters  # list[BaseInverter] - Standalone inverters

# Methods
await station.refresh()              # Refresh station metadata
await station.refresh_all_data()     # Refresh all devices recursively
await station.get_total_production() # Get aggregated energy stats
```

---

### BaseInverter Methods

```python
# Properties
inverter.serial              # str - Serial number
inverter.model               # str - Model name
inverter.runtime             # InverterRuntime - Real-time data
inverter.energy              # EnergyInfo - Energy statistics
inverter.battery_bank        # BatteryBank - Battery bank object
inverter.battery_soc         # int - Current SOC %
inverter.power_output        # int - Current power output
inverter.total_energy_today  # float - Today's energy
inverter.total_energy_lifetime  # float - Lifetime energy
inverter.has_data            # bool - True if data loaded
inverter.needs_refresh       # bool - True if data stale

# Data Management
await inverter.refresh()     # Refresh runtime, energy, battery data

# Parameter Management
params = await inverter.read_parameters(start=0, count=127)
success = await inverter.write_parameters({21: 0, 22: 100})

# Battery SOC Control (HIGH-LEVEL!)
limits = await inverter.get_battery_soc_limits()
# Returns: {"on_grid_soc_limit": int, "off_grid_soc_limit": int}

success = await inverter.set_battery_soc_limits(
    on_grid_limit=10,      # Optional: On-grid discharge cutoff %
    off_grid_limit=5       # Optional: Off-grid discharge cutoff %
)

# Operating Mode Control (HIGH-LEVEL!)
success = await inverter.set_standby_mode(standby=True)  # True=Standby, False=Normal
```

---

### Battery Methods

```python
# Properties
battery.index               # int - Battery index
battery.voltage             # float - Voltage (V)
battery.current             # float - Current (A)
battery.power               # float - Power (W)
battery.soc                 # int - State of charge %
battery.soh                 # int - State of health %
battery.cycle_count         # int - Charge cycles
battery.firmware_version    # str - Firmware version
battery.max_cell_voltage    # float - Max cell voltage (V)
battery.min_cell_voltage    # float - Min cell voltage (V)
battery.cell_voltage_delta  # float - Cell imbalance (V)
battery.max_cell_temp       # float - Max cell temp (°C)
battery.min_cell_temp       # float - Min cell temp (°C)
battery.is_lost             # bool - Communication lost
battery.needs_refresh       # bool - Data stale

# Methods
await battery.refresh()     # Refresh battery data
```

---

## Home Assistant Integration Patterns

### Coordinator Pattern

```python
class EG4DataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, client, plant_id):
        super().__init__(...)
        self.client = client
        self.plant_id = plant_id
        self.station: Optional[Station] = None

    async def _async_update_data(self):
        """Fetch data using device objects."""
        # Load or refresh station
        if self.station is None:
            self.station = await Station.load(self.client, self.plant_id)
        else:
            await self.station.refresh_all_data()

        # Extract data from device objects
        data = {"devices": {}}
        for inverter in self.station.all_inverters:
            data["devices"][inverter.serial] = {
                "runtime": inverter.runtime,  # Pydantic model
                "energy": inverter.energy,    # Pydantic model
            }
        return data

    def get_inverter_object(self, serial: str) -> Optional[BaseInverter]:
        """Get inverter object by serial."""
        if not self.station:
            return None
        for inverter in self.station.all_inverters:
            if inverter.serial == serial:
                return inverter
        return None
```

---

### Number Entity Pattern

```python
class SOCLimitNumber(CoordinatorEntity, NumberEntity):
    """Number entity for SOC limit control using device objects."""

    async def async_set_native_value(self, value: float) -> None:
        """Set SOC limit using device object convenience method."""
        # Get inverter object from coordinator
        inverter = self.coordinator.get_inverter_object(self.serial)
        if not inverter:
            raise HomeAssistantError(f"Inverter {self.serial} not found")

        # Use high-level convenience method!
        success = await inverter.set_battery_soc_limits(
            on_grid_limit=int(value)
        )

        if not success:
            raise HomeAssistantError(f"Failed to set SOC limit to {value}%")

        # Refresh inverter data
        await inverter.refresh()

        # Update coordinator
        await self.coordinator.async_request_refresh()

    @property
    def native_value(self) -> Optional[float]:
        """Get current SOC limit from device object."""
        # Access coordinator data (already extracted from device objects)
        device_data = self.coordinator.data["devices"].get(self.serial)
        if not device_data:
            return None

        # If we need live data, get it from inverter object
        inverter = self.coordinator.get_inverter_object(self.serial)
        if inverter and inverter.runtime:
            # SOC limit might be in runtime data or we query it
            # Use the convenience method if needed:
            # limits = await inverter.get_battery_soc_limits()
            # return limits["on_grid_soc_limit"]

            # Or access from coordinator data if already cached
            return device_data.get("parameters", {}).get("soc_limit")
```

---

### Switch Entity Pattern

```python
class BatteryBackupSwitch(CoordinatorEntity, SwitchEntity):
    """Switch for battery backup using device object methods."""

    async def async_turn_on(self) -> None:
        """Enable battery backup."""
        inverter = self.coordinator.get_inverter_object(self.serial)
        if not inverter:
            raise HomeAssistantError(f"Inverter {self.serial} not found")

        # Check if method exists on inverter object
        if hasattr(inverter, 'enable_battery_backup'):
            success = await inverter.enable_battery_backup()
        else:
            # MISSING FUNCTIONALITY - REPORT TO LIBRARY
            _LOGGER.error(
                "enable_battery_backup() not available on inverter object. "
                "This should be added to pylxpweb library."
            )
            raise HomeAssistantError(
                "Battery backup control not supported by device object"
            )

        if not success:
            raise HomeAssistantError("Failed to enable battery backup")

        await inverter.refresh()
        await self.coordinator.async_request_refresh()
```

---

### Button Entity Pattern

```python
class RefreshButton(CoordinatorEntity, ButtonEntity):
    """Button to refresh device data."""

    async def async_press(self) -> None:
        """Refresh device data using device object."""
        inverter = self.coordinator.get_inverter_object(self.serial)
        if not inverter:
            raise HomeAssistantError(f"Inverter {self.serial} not found")

        # Use device object refresh method
        await inverter.refresh()

        # Trigger coordinator update
        await self.coordinator.async_request_refresh()
```

---

## When to Report Missing Functionality

If you encounter a situation where you need to use `client.api.*`, it means the device objects are missing functionality. **Report it immediately:**

### Reporting Template

```markdown
## Missing Device Object Method

**Current Workaround**: Using `client.api.control.enable_battery_backup(serial)`

**Expected Device Object Method**:
```python
inverter = station.all_inverters[0]
success = await inverter.enable_battery_backup()
```

**Why This Should Be Added**:
- Battery backup control is a common operation
- Should be abstracted as high-level convenience method
- Matches pattern of other control methods like `set_standby_mode()`

**Proposed Implementation Location**:
- File: `pylxpweb/devices/inverters/base.py`
- Class: `BaseInverter`
- Method: `async def enable_battery_backup(self) -> bool`
```

---

## Testing Device Object Integration

### Unit Test Pattern

```python
async def test_soc_limit_using_device_objects(mock_inverter):
    """Test SOC limit control using device object methods."""
    # Mock inverter object
    mock_inverter.get_battery_soc_limits = AsyncMock(
        return_value={"on_grid_soc_limit": 10, "off_grid_soc_limit": 5}
    )
    mock_inverter.set_battery_soc_limits = AsyncMock(return_value=True)

    # Create number entity
    entity = SOCLimitNumber(coordinator, "1234567890")

    # Set value using device object method
    await entity.async_set_native_value(15.0)

    # Verify device object method was called
    mock_inverter.set_battery_soc_limits.assert_called_once_with(on_grid_limit=15)
    mock_inverter.refresh.assert_called_once()
```

---

## Migration Checklist

When refactoring code to use device objects:

- [ ] Remove all `client.api.*` calls
- [ ] Replace with device object methods
- [ ] Use high-level convenience methods when available
- [ ] For missing functionality: STOP and report to library
- [ ] Update tests to mock device objects instead of API client
- [ ] Document any missing device object methods
- [ ] Verify entity IDs remain unchanged
- [ ] Test all control operations work correctly

---

## Quick Reference: Method Mapping

| Old API Call | New Device Object Method |
|-------------|--------------------------|
| `client.api.plants.get_plants()` | `Station.load_all(client)` |
| `client.api.devices.get_inverter_runtime(serial)` | `inverter.refresh()` then access `inverter.runtime` |
| `client.api.devices.get_battery_info(serial)` | `inverter.refresh()` then access `inverter.battery_bank` |
| `client.api.control.read_parameters(serial, 0, 127)` | `inverter.read_parameters(0, 127)` |
| `client.api.control.write_parameter(serial, param, value)` | `inverter.write_parameters({param: value})` |
| Battery SOC limits (read) | `inverter.get_battery_soc_limits()` |
| Battery SOC limits (write) | `inverter.set_battery_soc_limits(on_grid=10, off_grid=5)` |
| Operating mode control | `inverter.set_standby_mode(True/False)` |
| Battery backup enable | **MISSING** - Report to library |
| Battery backup disable | **MISSING** - Report to library |
| DST control | **CHECK** - May need station-level method |

---

## Summary

**Golden Rule**: If you find yourself typing `client.api.`, STOP and ask:
1. Does the device object have a method for this?
2. If not, should it?
3. Report missing functionality to library maintainers
4. Fix the library, then use device object methods

**Never bypass the device object abstraction layer!**

---

**Document Status**: ACTIVE - MUST FOLLOW
**Last Updated**: November 20, 2025
**Review Required**: Before any API interaction implementation
