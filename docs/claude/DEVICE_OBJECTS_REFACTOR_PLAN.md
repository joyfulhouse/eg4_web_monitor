# Device Objects Refactoring Plan

**Date**: November 20, 2025
**Branch**: `feature/device-objects-refactor`
**Approach**: Use pylxpweb high-level device objects (`Station`, `BaseInverter`, `Battery`)

---

## Executive Summary

This refactoring will migrate the integration from using `pylxpweb` raw API endpoints to using the library's high-level device object hierarchy. This approach provides:

1. **Object-Oriented Data Access**: Direct property access instead of dict parsing
2. **Automatic Refresh Management**: Objects handle their own data refresh cycles
3. **Type Safety**: Full Pydantic model integration with IDE autocomplete
4. **Simplified Code**: Estimated 60-70% reduction in coordinator complexity

---

## Device Object Architecture

### Core Pattern

```python
from pylxpweb import LuxpowerClient
from pylxpweb.devices import Station

# Initialize client
async with LuxpowerClient(username, password) as client:
    # Load station with full device hierarchy
    station = await Station.load(client, plant_id=12345)

    # Access device hierarchy
    for inverter in station.all_inverters:
        print(f"Serial: {inverter.serial}")
        print(f"PV Power: {inverter.runtime.ppv}W")
        print(f"SOC: {inverter.runtime.soc}%")

        # Access battery bank
        if inverter.battery_bank:
            for battery in inverter.battery_bank.batteries:
                print(f"  Battery {battery.index}: {battery.soc}%")
```

### Object Hierarchy

```
Station (plant_id, name, location, timezone)
├── parallel_groups: list[ParallelGroup]
│   ├── mid_device: MIDDevice (GridBOSS) | None
│   └── inverters: list[BaseInverter]
└── standalone_inverters: list[BaseInverter]
    └── battery_bank: BatteryBank | None
        └── batteries: list[Battery]
```

### Station Object

**Class**: `pylxpweb.devices.Station`

**Attributes**:
- `id: int` - Plant ID
- `name: str` - Station name
- `location: Location` - Geographic info
- `timezone: str` - Timezone string
- `created_date: datetime` - Creation timestamp
- `parallel_groups: list[ParallelGroup]` - Parallel group devices
- `standalone_inverters: list[BaseInverter]` - Standalone inverters
- `weather: WeatherData | None` - Weather information

**Methods**:
- `await Station.load(client, plant_id)` - Load station with full hierarchy
- `await Station.load_all(client)` - Load all stations for user
- `await station.refresh()` - Refresh station metadata
- `await station.refresh_all_data()` - Refresh all devices recursively
- `await station.get_total_production()` - Get aggregated energy stats

**Properties**:
- `station.all_inverters` - Flattened list of all inverters
- `station.all_batteries` - Flattened list of all batteries
- `station.needs_refresh` - True if data is stale

### BaseInverter Object

**Class**: `pylxpweb.devices.inverters.base.BaseInverter`

**Attributes**:
- `serial: str` - Serial number (inherited from BaseDevice)
- `model: str` - Model name (e.g., "FlexBOSS21")
- `runtime: InverterRuntime | None` - Real-time runtime data
- `energy: EnergyInfo | None` - Energy statistics
- `battery_bank: BatteryBank | None` - Battery bank object

**Methods**:
- `await inverter.refresh()` - Refresh runtime and energy data
- `await inverter.read_parameters(start=0, count=127)` - Read device parameters
- `await inverter.write_parameters({param: value})` - Write parameters
- `await inverter.set_battery_soc_limits(on_grid=10, off_grid=5)` - Set SOC limits
- `await inverter.set_standby_mode(standby=True)` - Set operating mode
- `await inverter.get_battery_soc_limits()` - Get current SOC limits

**Properties**:
- `inverter.battery_soc` - Current SOC % (from runtime.soc)
- `inverter.power_output` - Current power output (from runtime.pinv)
- `inverter.total_energy_today` - Today's energy (from energy)
- `inverter.total_energy_lifetime` - Lifetime energy (from energy)
- `inverter.has_data` - True if runtime data is present
- `inverter.needs_refresh` - True if data is stale

### Battery Object

**Class**: `pylxpweb.devices.battery.Battery`

**Attributes**:
- `index: int` - Battery index (1-based)
- `data: BatteryData` - Raw battery data from API

**Methods**:
- `await battery.refresh()` - Refresh battery data

**Properties**:
- `battery.voltage` - Battery voltage (V)
- `battery.current` - Battery current (A)
- `battery.power` - Battery power (W)
- `battery.soc` - State of charge (%)
- `battery.soh` - State of health (%)
- `battery.cycle_count` - Charge cycles
- `battery.firmware_version` - Firmware version
- `battery.max_cell_voltage` - Max cell voltage (mV)
- `battery.min_cell_voltage` - Min cell voltage (mV)
- `battery.cell_voltage_delta` - Cell imbalance (mV)
- `battery.max_cell_temp` - Max cell temperature (°C)
- `battery.min_cell_temp` - Min cell temperature (°C)
- `battery.is_lost` - True if communication lost
- `battery.needs_refresh` - True if data is stale

---

## Data Access Patterns

### Current Implementation (Raw API)

```python
# coordinator.py - Current implementation
async def _async_update_data(self):
    # Manual API calls
    devices = await self.client.api.devices.get_devices(self.plant_id)

    # Manual parallel processing
    for device in devices.rows:
        serial = device.serialNum
        runtime = await self.client.api.devices.get_inverter_runtime(serial)
        battery = await self.client.api.devices.get_battery_info(serial)

    # Manual dict parsing and sensor extraction
    sensors = {}
    for api_field, sensor_type in FIELD_MAPPING.items():
        if api_field in runtime.model_dump():
            sensors[sensor_type] = runtime.model_dump()[api_field]
```

### New Implementation (Device Objects)

```python
# coordinator.py - Device objects implementation
async def _async_update_data(self):
    # Load station with full device hierarchy
    station = await Station.load(self.client, self.plant_id)

    # Refresh all data in one call
    await station.refresh_all_data()

    # Access data via object properties
    data = {"station": station, "devices": {}}

    for inverter in station.all_inverters:
        # Direct property access - no dict parsing!
        data["devices"][inverter.serial] = {
            "runtime": inverter.runtime,  # InverterRuntime Pydantic model
            "energy": inverter.energy,    # EnergyInfo Pydantic model
            "batteries": []
        }

        # Battery access
        if inverter.battery_bank:
            for battery in inverter.battery_bank.batteries:
                data["devices"][inverter.serial]["batteries"].append({
                    "index": battery.index,
                    "soc": battery.soc,
                    "voltage": battery.voltage,
                    # All properties available directly!
                })

    return data
```

---

## Implementation Phases

### Phase 1: Update Manifest and Dependencies ✅

**File**: `manifest.json`

```json
{
  "requirements": ["pylxpweb==0.2.2"],
  "version": "3.0.0"
}
```

**Why**: Declare pylxpweb dependency for HACS installation.

---

### Phase 2: Refactor Config Flow

**File**: `config_flow.py`

**Changes**:
1. Keep existing `LuxpowerClient` usage (no change needed)
2. Use `Station.load()` for plant verification
3. Store station name and metadata

```python
# Step: Verify plant access and get station info
async with LuxpowerClient(
    username=self._username,
    password=self._password,
    base_url=self._base_url,
    verify_ssl=self._verify_ssl,
    session=session,
) as client:
    # Load station to verify access
    station = await Station.load(client, self._plant_id)

    # Store station info for config entry
    return self.async_create_entry(
        title=f"EG4 Web Monitor {station.name}",
        data={
            "username": self._username,
            "password": self._password,
            "plant_id": self._plant_id,
            "station_name": station.name,
            # ... other config
        },
    )
```

---

### Phase 3: Refactor Coordinator (CRITICAL)

**File**: `coordinator.py`

**Current Size**: 1,659 lines
**Estimated New Size**: 500-600 lines (60-70% reduction)

**Key Changes**:

#### 3.1: Store Station Object

```python
class EG4DataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, client, plant_id):
        super().__init__(...)
        self.client = client
        self.plant_id = plant_id
        self.station: Station | None = None  # Store station object
```

#### 3.2: Simplified Update Method

```python
async def _async_update_data(self):
    """Fetch data using device objects."""
    try:
        # Load or refresh station
        if self.station is None:
            self.station = await Station.load(self.client, self.plant_id)
        else:
            await self.station.refresh_all_data()

        # Build data structure
        data = {
            "station": {
                "id": self.station.id,
                "name": self.station.name,
                "location": self.station.location,
                "timezone": self.station.timezone,
            },
            "devices": {},
        }

        # Process all inverters
        for inverter in self.station.all_inverters:
            device_data = await self._process_inverter(inverter)
            data["devices"][inverter.serial] = device_data

        return data

    except LuxpowerAuthError:
        raise ConfigEntryAuthFailed("Authentication expired")
    except LuxpowerAPIError as err:
        raise UpdateFailed(f"API error: {err}")
```

#### 3.3: Process Inverter Method

```python
async def _process_inverter(self, inverter: BaseInverter) -> dict:
    """Process single inverter data."""
    device_data = {
        "type": "inverter",
        "serial": inverter.serial,
        "model": inverter.model,
        "runtime": {},
        "energy": {},
        "batteries": {},
    }

    # Extract runtime data
    if inverter.runtime:
        runtime = inverter.runtime
        device_data["runtime"] = {
            "ppv": runtime.ppv,
            "soc": runtime.soc,
            "pToGrid": runtime.pToGrid,
            "pToUser": runtime.pToUser,
            "vBat": runtime.vBat,
            "batPower": runtime.batPower,
            # ... all runtime fields
        }

    # Extract energy data
    if inverter.energy:
        energy = inverter.energy
        device_data["energy"] = {
            "today": energy.eToday,
            "month": energy.eMonth,
            "year": energy.eYear,
            "total": energy.eTotal,
        }

    # Process batteries
    if inverter.battery_bank:
        for battery in inverter.battery_bank.batteries:
            device_data["batteries"][battery.index] = {
                "soc": battery.soc,
                "voltage": battery.voltage,
                "current": battery.current,
                "power": battery.power,
                "soh": battery.soh,
                "cycle_count": battery.cycle_count,
                "cell_voltage_delta": battery.cell_voltage_delta,
                "max_cell_temp": battery.max_cell_temp,
                "min_cell_temp": battery.min_cell_temp,
            }

    return device_data
```

#### 3.4: Entity ID Preservation

**CRITICAL**: Must preserve existing entity ID generation patterns!

```python
# Current entity ID pattern (MUST PRESERVE)
def generate_unique_id(serial: str, sensor_key: str, battery_key: str = None):
    if battery_key:
        return f"{serial}_runtime_{sensor_key}_{battery_key}"
    else:
        return f"{serial}_runtime_{sensor_key}"

def generate_entity_id(platform: str, model: str, serial: str, sensor_name: str, battery_key: str = None):
    if battery_key:
        return f"{platform}.eg4_{model}_{serial}_battery_{battery_key}_{sensor_name}"
    else:
        return f"{platform}.eg4_{model}_{serial}_{sensor_name}"
```

**The device objects provide data, but we still use our existing entity ID generation logic!**

---

### Phase 4: Update Platform Files

**Files**: `sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`

**Changes**: Minimal - mostly access pattern updates

#### 4.1: Sensor Platform

```python
# sensor.py - Access runtime data from objects
class EG4Sensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, serial, sensor_key):
        super().__init__(coordinator)
        self._serial = serial
        self._sensor_key = sensor_key

    @property
    def native_value(self):
        """Get sensor value from device object data."""
        device_data = self.coordinator.data.get("devices", {}).get(self._serial)
        if not device_data:
            return None

        # Access runtime data (no dict.get() - it's already extracted!)
        runtime = device_data.get("runtime", {})
        return runtime.get(self._sensor_key)
```

#### 4.2: Number Platform

```python
# number.py - Use inverter object methods for control
async def async_set_native_value(self, value: float):
    """Set SOC limit using inverter object."""
    # Get inverter object from station
    inverter = self._get_inverter_object()

    if inverter:
        # Use high-level control method!
        await inverter.set_battery_soc_limits(on_grid=int(value))

        # Refresh data
        await inverter.refresh()
        await self.coordinator.async_request_refresh()
```

#### 4.3: Switch Platform

```python
# switch.py - Use inverter control methods
async def async_turn_on(self):
    """Enable battery backup using inverter object."""
    inverter = self._get_inverter_object()

    if inverter:
        # Library provides high-level method for this!
        # But we need to check if it exists first...
        # For now, use raw API call
        await self.coordinator.client.api.control.enable_battery_backup(self._serial)
```

#### 4.4: Button Platform

```python
# button.py - Use object refresh methods
async def async_press(self):
    """Refresh device data using object methods."""
    inverter = self._get_inverter_object()

    if inverter:
        # Use object's refresh method
        await inverter.refresh()
        await self.coordinator.async_request_refresh()
```

---

### Phase 5: Helper Methods

**Add to Coordinator**:

```python
def get_inverter_object(self, serial: str) -> BaseInverter | None:
    """Get inverter object by serial number."""
    if not self.station:
        return None

    for inverter in self.station.all_inverters:
        if inverter.serial == serial:
            return inverter

    return None

def get_battery_object(self, serial: str, battery_index: int) -> Battery | None:
    """Get battery object by parent serial and index."""
    inverter = self.get_inverter_object(serial)

    if inverter and inverter.battery_bank:
        for battery in inverter.battery_bank.batteries:
            if battery.index == battery_index:
                return battery

    return None
```

---

## Entity ID Compatibility Strategy

### Critical Requirement

**MUST** generate identical entity IDs to current implementation to preserve user automations!

### Current Entity ID Patterns

```python
# Inverter sensor
f"sensor.eg4_{model}_{serial}_{sensor_name}"
# Example: sensor.eg4_flexboss21_1234567890_pv_power

# Battery sensor
f"sensor.eg4_{model}_{serial}_battery_{batteryKey}_{sensor_name}"
# Example: sensor.eg4_flexboss21_1234567890_battery_1_voltage

# GridBOSS sensor
f"sensor.eg4_gridboss_{serial}_{sensor_name}"
# Example: sensor.eg4_gridboss_9876543210_grid_power
```

### Preservation Strategy

1. **Keep Existing Field Mappings**: Don't change sensor key generation
2. **Keep Existing Entity ID Functions**: Use current `generate_entity_id()` utilities
3. **Extract Data to Same Format**: Convert object data to same dict structure
4. **Test Entity IDs**: Validate generated IDs match exactly

---

## Testing Strategy

### Unit Tests

```python
# tests/test_device_objects.py
async def test_station_loading(hass, mock_client):
    """Test Station.load() loads device hierarchy."""
    station = await Station.load(mock_client, plant_id=12345)

    assert station.id == 12345
    assert len(station.all_inverters) > 0
    assert station.all_inverters[0].runtime is not None

async def test_entity_id_preservation(hass, coordinator):
    """Test entity IDs match current implementation."""
    await coordinator.async_refresh()

    # Get device data
    device_data = coordinator.data["devices"]["1234567890"]

    # Generate entity ID using current logic
    entity_id = generate_entity_id("sensor", "FlexBOSS21", "1234567890", "pv_power")

    # Verify format
    assert entity_id == "sensor.eg4_flexboss21_1234567890_pv_power"
```

### Integration Tests

1. Load station and verify device hierarchy
2. Refresh data and verify all objects updated
3. Compare entity IDs with current implementation
4. Verify sensor values match API responses
5. Test control operations (SOC limits, standby mode)

---

## Code Reduction Estimates

| File | Current Lines | Estimated New Lines | Reduction |
|------|--------------|-------------------|-----------|
| `coordinator.py` | 1,659 | 600 | 64% |
| `sensor.py` | 450 | 400 | 11% |
| `number.py` | 300 | 250 | 17% |
| `switch.py` | 400 | 350 | 13% |
| `button.py` | 450 | 400 | 11% |
| **Total** | **3,259** | **2,000** | **39%** |

**Note**: Reduction is lower than initially estimated (93%) because:
- Entity ID generation logic must be preserved
- Platform files still need full entity setup
- Field mappings still required for sensor extraction

**But**: Code is much cleaner with type-safe object access instead of dict parsing!

---

## Risks and Mitigations

### Risk 1: Entity ID Changes

**Risk**: Device objects might use different field names, breaking entity IDs

**Mitigation**:
- Preserve all existing entity ID generation functions
- Convert object data to same dict structure as current implementation
- Add comprehensive entity ID validation tests

### Risk 2: Missing Device Types

**Risk**: Library might not support all device types (GridBOSS, parallel groups)

**Mitigation**:
- Check library source for `MIDDevice` class (GridBOSS)
- Check library source for `ParallelGroup` class
- Fall back to raw API for unsupported device types

### Risk 3: Control Method Coverage

**Risk**: High-level control methods might not cover all parameters

**Mitigation**:
- Use `inverter.write_parameters()` for low-level parameter writes
- Keep raw API calls as fallback for unsupported operations

---

## Success Criteria

1. ✅ All existing entity IDs preserved (100% match)
2. ✅ All sensor values match current implementation
3. ✅ All control operations work (SOC limits, standby, backup)
4. ✅ Code reduction of 30-40% achieved
5. ✅ Type safety improved with object properties
6. ✅ All tests pass with no regressions
7. ✅ Performance maintained or improved

---

## Next Steps

1. ✅ Update `manifest.json` with pylxpweb dependency
2. ⏳ Refactor `config_flow.py` to use Station.load()
3. ⏳ Refactor `coordinator.py` to use device objects
4. ⏳ Update platform files for object access patterns
5. ⏳ Add helper methods for object retrieval
6. ⏳ Run comprehensive tests and entity ID validation
7. ⏳ Performance testing and optimization

---

**Document Status**: Ready for Implementation
**Approval**: Awaiting user confirmation to proceed
