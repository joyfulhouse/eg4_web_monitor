# pylxpweb Missing Abstractions - GitHub Issue Draft

**Date**: 2025-11-19
**Issue for**: https://github.com/joyfulhouse/pylxpweb

---

## Summary

Currently, `pylxpweb` is just an API passthrough library that provides HTTP client functionality and Pydantic models for API responses. For it to be a truly useful client library for Home Assistant integrations and other applications, it needs to provide **higher-level abstractions** for working with devices, managing hierarchies, and extracting entity data.

## Current State: What pylxpweb Provides Today

✅ **HTTP Client Infrastructure**:
- Authentication and session management
- Request/response handling with aiohttp
- Caching with configurable TTL
- Exponential backoff and retry logic
- SSL verification options

✅ **Pydantic Models** for API responses:
- `InverterRuntime`, `EnergyInfo`, `BatteryInfo`
- `MidboxRuntime` (GridBOSS)
- `PlantInfo`, `ParallelGroupDetailsResponse`
- Parameter models, control responses

✅ **Endpoint Organization**:
- `client.devices.*` - Device discovery and data
- `client.plants.*` - Plant/station management
- `client.control.*` - Parameter read/write, functions
- Plus analytics, forecasting, firmware endpoints

## Problem: What's Missing

❌ **No Device Abstractions**:
- Client returns raw dictionaries/Pydantic models
- Consumer must manually:
  - Discover device hierarchy (plants → groups → inverters → batteries)
  - Extract device serial numbers from nested responses
  - Determine device types (inverter vs GridBOSS)
  - Build device relationships
  - Track which devices have batteries

❌ **No Sensor/Data Extraction**:
- Consumer must manually:
  - Map API field names to semantic meanings
  - Apply scaling (÷10 for voltages, ÷100 for frequencies)
  - Filter zero-value sensors
  - Handle special cases (GridBOSS vs inverter sensors)
  - Extract individual battery data from `batteryArray`

❌ **No Entity ID Generation**:
- Consumer must manually:
  - Generate unique IDs for devices and sensors
  - Ensure compatibility across versions
  - Clean model names for entity IDs
  - Handle battery naming (clean `batteryKey`)

❌ **No Device Hierarchy Management**:
- Consumer must manually:
  - Track parent-child relationships
  - Understand parallel group membership
  - Link batteries to parent inverters
  - Manage station → group → device tree

## What a Proper Client Library Should Provide

### 1. Device Abstraction Layer

```python
# HIGH-LEVEL API (what pylxpweb should provide)
from pylxpweb import LuxpowerClient

client = LuxpowerClient(username, password)
await client.login()

# Get station with full device hierarchy
station = await client.get_station(plant_id)

# Access devices through object model
for inverter in station.inverters:
    print(f"Inverter {inverter.serial}: {inverter.model}")
    print(f"  AC Power: {inverter.ac_power}W")  # Already scaled
    print(f"  Battery SOC: {inverter.battery_soc}%")

    # Access individual batteries
    for battery in inverter.batteries:
        print(f"  Battery {battery.key}: {battery.voltage}V, {battery.soc}%")

# Access GridBOSS if present
if station.gridboss:
    gridboss = station.gridboss
    print(f"GridBOSS {gridboss.serial}")
    print(f"  Grid Power: {gridboss.grid_power}W")
```

### 2. Proposed Class Hierarchy

```python
class Station:
    """Represents a complete station/plant with all devices."""
    plant_id: int
    name: str
    timezone: str
    inverters: List[Inverter]
    gridboss: Optional[GridBOSS]
    parallel_groups: List[ParallelGroup]

    async def refresh(self) -> None:
        """Refresh all device data."""

    def get_device(self, serial: str) -> Device | None:
        """Get device by serial number."""

class Device(ABC):
    """Base class for all devices."""
    serial: str
    model: str
    firmware_version: str
    device_type: str

    @abstractmethod
    async def refresh(self) -> None:
        """Refresh device data."""

class Inverter(Device):
    """Standard inverter with sensors and batteries."""
    device_type = "inverter"

    # Runtime sensors (auto-scaled)
    ac_power: float  # Already divided by scaling factor
    pv_power: float
    battery_power: float
    grid_power: float
    battery_soc: int

    # Energy sensors
    today_energy: float  # kWh
    total_energy: float  # kWh

    # Relationships
    batteries: List[Battery]
    parallel_group: Optional[ParallelGroup]

    # Raw data access if needed
    runtime_data: InverterRuntime
    energy_data: EnergyInfo
    battery_data: BatteryInfo

class Battery:
    """Individual battery module."""
    key: str  # Battery key (cleaned)
    serial: str  # Parent inverter serial
    voltage: float  # Already scaled (÷10)
    current: float
    soc: int
    soh: int
    temperature: float
    cycle_count: int

    # Cell data
    cell_voltages: List[float]
    cell_voltage_delta: float  # Imbalance

class GridBOSS(Device):
    """GridBOSS MID device."""
    device_type = "gridboss"

    # Grid sensors (auto-scaled)
    grid_power: float
    load_power: float
    smart_load_power: float
    ups_power: float

    # Smart ports
    smart_ports: List[SmartPort]

    # Raw data
    midbox_data: MidboxRuntime

class SmartPort:
    """GridBOSS smart port configuration."""
    port_number: int
    status: str  # "Unused" | "Smart Load" | "AC Couple"
    power_l1: float
    power_l2: float

class ParallelGroup:
    """Parallel group containing multiple inverters."""
    name: str
    devices: List[Device]
    total_power: float
    total_energy_today: float
```

### 3. Sensor Metadata System

```python
class SensorDefinition:
    """Metadata for a sensor field."""
    api_field: str  # Field name in API response
    name: str  # Semantic name
    scaling: float = 1.0  # Divide by this
    unit: str = ""
    device_class: str = ""  # For Home Assistant
    state_class: str = ""

# Library should provide
INVERTER_SENSORS: Dict[str, SensorDefinition] = {
    "ac_power": SensorDefinition(
        api_field="pac",
        name="AC Power",
        unit="W",
        device_class="power",
        state_class="measurement"
    ),
    "battery_voltage": SensorDefinition(
        api_field="vBat",
        name="Battery Voltage",
        scaling=10.0,  # Divide by 10
        unit="V",
        device_class="voltage"
    ),
    # ... etc
}
```

### 4. Auto-Discovery Helper

```python
class DeviceDiscovery:
    """Handles device discovery and hierarchy building."""

    @staticmethod
    async def discover_station(client: LuxpowerClient, plant_id: int) -> Station:
        """Discover all devices in a station and build hierarchy."""
        # 1. Get device list
        # 2. Fetch data for all devices concurrently
        # 3. Build device objects with relationships
        # 4. Return complete Station object

    @staticmethod
    async def get_device_data(client: LuxpowerClient, serial: str, device_type: str) -> Device:
        """Get comprehensive data for a single device."""
```

## Benefits of These Abstractions

### For Home Assistant Integrations

**Before** (current state):
```python
# Integration must do ALL of this manually
data = await api.get_all_device_data(plant_id)
for serial, device_data in data["devices"].items():
    runtime = device_data.get("runtime", {})

    # Manual scaling
    ac_power = runtime.get("pac", 0)
    battery_voltage = runtime.get("vBat", 0) / 10.0  # Manual division

    # Manual battery extraction
    battery_array = device_data.get("battery", {}).get("batteryArray", [])
    for bat_data in battery_array:
        battery_key = clean_battery_display_name(bat_data["batteryKey"], serial)
        # Extract each sensor manually...
```

**After** (with abstractions):
```python
# Clean, simple API
station = await client.get_station(plant_id)
for inverter in station.inverters:
    # Already scaled, typed, structured
    create_sensor("ac_power", inverter.ac_power)
    create_sensor("battery_voltage", inverter.battery_voltage)

    for battery in inverter.batteries:
        create_sensor(f"battery_{battery.key}_voltage", battery.voltage)
```

### For Other Applications

- **Dashboard apps**: Direct access to typed device data
- **Monitoring tools**: Simple iteration over devices
- **Data exporters**: Structured data ready for databases
- **CLI tools**: Easy device discovery and data access

## Implementation Approach

### Phase 1: Core Device Models
- Add `Device`, `Inverter`, `Battery`, `GridBOSS`, `Station` classes
- Implement basic data loading from API responses
- Add sensor metadata definitions

### Phase 2: Auto-Discovery
- Implement `DeviceDiscovery.discover_station()`
- Build device hierarchy automatically
- Handle parallel groups

### Phase 3: Sensor Extraction
- Implement automatic scaling based on metadata
- Add sensor filtering (essential vs optional)
- Handle special cases (GridBOSS sensors)

### Phase 4: Relationship Management
- Link batteries to inverters
- Track parallel group membership
- Build station device tree

## Breaking Changes Considerations

These additions would be **non-breaking**:
- Add new classes and methods
- Keep existing endpoint methods as-is
- Provide both low-level (current) and high-level (new) APIs

## Example: Before/After Comparison

### Current Usage (Low-Level)
```python
client = LuxpowerClient(username, password)
await client.login()

# Get devices
devices = await client.devices.get_devices(plant_id)
for device in devices.rows:
    serial = device.serialNum

    # Get runtime data
    runtime = await client.devices.get_inverter_runtime(serial)

    # Manual field extraction and scaling
    ac_power = runtime.pac  # No scaling
    voltage = runtime.vBat / 10.0  # Manual scaling

    # Get battery data
    battery = await client.devices.get_battery_info(serial)

    # Manual battery array parsing
    for bat in battery.batteryArray:
        key = bat.batteryKey  # Needs cleaning
        voltage = bat.realVoltage / 10.0  # Manual scaling
```

### Proposed Usage (High-Level)
```python
client = LuxpowerClient(username, password)
station = await client.get_station(plant_id)

for inverter in station.inverters:
    # Auto-scaled, typed properties
    ac_power = inverter.ac_power
    voltage = inverter.battery_voltage

    # Clean battery iteration
    for battery in inverter.batteries:
        print(f"{battery.key}: {battery.voltage}V")
```

## Conclusion

For `pylxpweb` to be a truly valuable client library (not just an API wrapper), it needs to provide:

1. **Device abstractions** - Station, Inverter, Battery, GridBOSS classes
2. **Auto-discovery** - Automatic device hierarchy building
3. **Sensor metadata** - Definitions for scaling, units, device classes
4. **Data extraction** - Automatic scaling and field mapping
5. **Relationship management** - Parent-child device links

This would reduce consumer code by **60-70%** and make the library useful for Home Assistant, dashboards, CLI tools, and any application working with EG4/Luxpower devices.

Without these abstractions, consumers are forced to re-implement all this logic, defeating the purpose of having a shared client library.

---

**Should I open this as a GitHub issue in the pylxpweb repository?**
