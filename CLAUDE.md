# EG4 Web Monitor Home Assistant Integration

## Project Overview
Home Assistant custom component that integrates EG4 devices (inverters, GridBOSS, batteries) with Home Assistant through the unofficial EG4 web monitoring API. Supports multi-station architecture with comprehensive device hierarchy and individual battery management.

## Quality Scale Compliance

### Platinum Tier Status - November 2025 🏆
**PLATINUM TIER COMPLIANT** - Meeting all 36 requirements (3 Platinum + 5 Gold + 10 Silver + 18 Bronze)

**Platinum Tier Requirements (3/3)**:
1. **Async Dependency**: Full async implementation using aiohttp for all HTTP operations
2. **Websession Injection**: API client supports injected aiohttp.ClientSession from Home Assistant
3. **Strict Typing**: Comprehensive mypy strict typing configuration with type hints throughout codebase

### Gold Tier Status - November 2025 ✅
**GOLD TIER COMPLIANT** - Meeting all 33 requirements (5 Gold + 10 Silver + 18 Bronze)

**Gold Tier Requirements (5/5)**:
1. **Translation Support**: Complete i18n infrastructure with `strings.json` and `translations/` directory
2. **UI Reconfiguration**: `async_step_reconfigure()` and `async_step_reconfigure_plant()` flows for credential/station updates
3. **User Documentation**: Comprehensive README with troubleshooting, FAQ, and automation examples
4. **Automated Tests**: Full test coverage with `test_config_flow.py`, `test_reconfigure_flow.py`, and tier validation scripts
5. **Code Quality**: Enterprise-grade implementation with proper error handling, logging, and type hints

**Silver Tier Requirements (10/10)** - Inherited:
1. Service exception handling with `ServiceValidationError`
2. Config entry unload support
3. Complete configuration documentation
4. Entity availability management
5. Integration owner specification (@joyfulhouse)
6. Unavailability logging
7. `MAX_PARALLEL_UPDATES` in all platforms
8. UI-based reauthentication flow
9. Test coverage >95% target
10. Installation documentation

**Validation**:
```bash
python tests/validate_platinum_tier.py # All 3 Platinum requirements
python tests/validate_gold_tier.py     # All 5 Gold requirements
python tests/validate_silver_tier.py   # All 10 Silver requirements
python tests/validate_bronze_tier.py   # All 18 Bronze requirements
pytest tests/ --cov=. --cov-report=term-missing
mypy --config-file mypy.ini .          # Strict type checking
```

**Quality Scale Reference**: https://www.home-assistant.io/docs/quality_scale/
**Platinum Tier Reference**: https://developers.home-assistant.io/docs/core/integration-quality-scale/#-platinum

## API Architecture

### Base Configuration
- **Base URL**: `https://monitor.eg4electronics.com`
- **Authentication**: `/WManage/api/login` (POST) - 2-hour session with auto-reauthentication
- **Serial Format**: 10-digit numeric strings (e.g., "1234567890")

### Device Hierarchy
```
Station/Plant (plantId)
└── Parallel Group (min:0, max:n)
    ├── MID Device (GridBOSS) (min:0, max:1)
    └── Inverters (min:1, max:n)
        └── Batteries (min:0, max:n)
```

### API Endpoints

**Station Discovery**:
- `/WManage/web/config/plant/list/viewer` (POST) - List available stations/plants

**Device Discovery**:
- `/WManage/api/inverterOverview/getParallelGroupDetails` (POST) - Parallel group hierarchy
- `/WManage/api/inverterOverview/list` (POST) - All devices in station

**Runtime Data**:
- `/WManage/api/inverter/getInverterEnergyInfoParallel` (POST) - Parallel group energy
- `/WManage/api/inverter/getInverterRuntime` (POST) - Inverter runtime metrics
- `/WManage/api/inverter/getInverterEnergyInfo` (POST) - Inverter energy data
- `/WManage/api/battery/getBatteryInfo` (POST) - Battery details and individual battery array
- `/WManage/api/midbox/getMidboxRuntime` (POST) - GridBOSS/MID device data

## Configuration Flow (Unified Menu-Based Architecture)

### Architecture
The config flow uses a single `EG4ConfigFlow` class with menu-based navigation.
Connection type (http/local/hybrid) is **auto-derived** from configured data, not chosen upfront.

**Directory Structure** (`config_flow/`):
- `__init__.py` — Unified EG4ConfigFlow class (~920 lines)
- `discovery.py` — Device auto-discovery via Modbus/Dongle
- `schemas.py` — Voluptuous schema builders
- `helpers.py` — Utility functions (unique IDs, migration, etc.)
- `options.py` — EG4OptionsFlow for interval configuration

### Onboarding Flow
1. **Entry Menu**: User picks "Cloud (HTTP)" or "Local Device"
2. **Cloud Path**: Credentials → Station Selection → (optional) Add Local Device → Finish
3. **Local Path**: Pick Modbus or Dongle → Enter connection details → Auto-discover device → Add more or finish
4. **Connection Type**: Auto-derived — cloud-only=`http`, local-only=`local`, both=`hybrid`

### Reconfigure Flow
- **Entry Point**: `reconfigure_menu` (MENU type)
- **Options**: Update cloud credentials, add/remove local devices, detach cloud
- Preserves existing entity IDs and automations

### Key Functions
- `_derive_connection_type(has_cloud, has_local)` → http/local/hybrid
- `_validate_cloud_credentials()` → shared error handling for auth
- `_store_cloud_input(user_input)` → saves cloud form data to flow state
- `build_unique_id(mode, ...)` → unique ID generation per mode
- `format_entry_title(mode, name)` → `"{BRAND_NAME} - {name}"` (mode parameter unused)

## Entity Management

### ID Formats
- **Unique ID**: `{serial}_{data_type}_{sensor_key}_{batteryKey?}`
- **Entity ID (Inverter)**: `eg4_{model}_{serial}_{sensor_name}`
- **Entity ID (Battery)**: `eg4_{model}_{serial}_battery_{batteryKey}_{sensor_name}`
- **Entity ID (GridBOSS)**: `eg4_gridboss_{serial}_{sensor_name}`

### Device Types

**Standard Inverters** (FlexBOSS21, FlexBOSS18, 18kPV, 12kPV, XP):
- Full sensor set: power, voltage, current, energy, temperature
- Individual battery device creation
- Runtime, energy, and battery data endpoints

**GridBOSS MID Devices**:
- Grid management sensors only (no batteries)
- Grid interconnection, UPS, load management
- Smart load ports, AC coupling, generator integration

**Individual Batteries**:
- Voltage, current, power, SoC, SoH
- Temperature, cycle count, cell voltages
- Cell voltage delta (imbalance monitoring)

## Performance & Architecture

### Optimizations
- **Concurrent API Calls**: `asyncio.gather()` for parallel device data fetching
- **Session Caching**: 2-hour session reuse with auto-reauthentication
- **Smart Caching**: Differentiated TTL by data volatility:
  - Device Discovery: 15 minutes
  - Battery Info: 5 minutes
  - Parameters: 2 minutes
  - Quick Charge: 1 minute
  - Runtime/Energy: 20 seconds
- **Cache Invalidation**: Pre-hour boundary clearing for date rollover protection
- **Circuit Breaker**: Exponential backoff for API failures

### Data Processing
- API calls can return data for multiple devices - fetch once, update all relevant sensors
- Parallel updates with `MAX_PARALLEL_UPDATES` limits
- Different update intervals for different data types

## Release Process

Release notes should follow the CHANGELOG.md format. See `CHANGELOG.md` for detailed release history.

### Current Version
- **v3.2.0-beta.5** — Unified config flow, pylxpweb>=0.6.5
- See `CHANGELOG.md` for full history

## Testing & Validation

### Local Testing

This project uses `uv` for dependency management. Tests run from the repository root:

```bash
# Run all tests (228 tests)
uv run pytest tests/ -x --tb=short

# Run with coverage
uv run pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_config_flow.py -v
```

### Pre-Commit Validation

```bash
# 1. Lint and format
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/

# 2. Type checking
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/

# 3. All tests
uv run pytest tests/ -x

# 4. Tier validation scripts
uv run python tests/validate_silver_tier.py
uv run python tests/validate_gold_tier.py
uv run python tests/validate_platinum_tier.py
```

### Test Files
- `test_config_flow.py` — Cloud onboarding, menu navigation, error handling
- `test_reconfigure_flow.py` — Reconfigure menu, credential updates
- `test_config_flow_helpers.py` — Utility functions (unique IDs, timezone, migration)
- `test_coordinator.py` — Data update coordinator
- `test_sensor.py` — Sensor entity creation and updates
- `conftest.py` — Shared fixtures (mock stations, mock API client)

### Testing Framework
- **pytest-homeassistant-custom-component** for HA-specific fixtures
- `enable_custom_integrations` fixture auto-enabled in conftest.py
- Coverage target: >95% for production code

## Critical Technical Requirements

### API Integration
1. Use `/WManage/api/inverterOverview/list` with `plantId` filtering
2. Extract `batteryKey` from `getBatteryInfo` for individual battery sensors
3. Detect GridBOSS devices and apply MID-specific sensor sets
4. Implement 2-hour session caching with auto-reauthentication
5. Use concurrent API calls for performance

### Device Architecture
1. Multi-station support: one integration instance per station
2. Device hierarchy: inverters with individual battery sensors
3. GridBOSS special handling: grid management sensors only
4. Battery entity IDs: use `batteryKey` for uniqueness
5. Data separation: inverter status vs individual battery data

### Code Quality Standards
1. All imports present and properly managed
2. Comprehensive exception handling with logging
3. Type hints throughout codebase
4. Smart caching to minimize API calls
5. Test coverage for all features in CI pipeline
6. Use `time.monotonic()` instead of deprecated `asyncio.get_event_loop().time()`
7. TypedDict for configuration dictionaries (e.g., `SensorConfig` in `const.py`)
8. Proper `DeviceInfo | None` return types for device info methods

### String Formatting Conventions
**This integration follows Python string formatting best practices:**

1. **F-Strings (Preferred)**: Use for all non-logging string formatting
   ```python
   # Good - Modern and readable
   message = f"Device {serial} has {count} sensors"
   entity_id = f"sensor.{model}_{serial}_{sensor_type}"
   ```

2. **Percent Formatting (Logging Only)**: Use for logging to enable lazy evaluation
   ```python
   # Good - Lazy evaluation improves performance
   _LOGGER.debug("Processing device %s with type %s", serial, device_type)
   _LOGGER.error("Failed to fetch data for %s: %s", serial, error)
   ```

3. **Avoid `.format()`**: Do not use `.format()` method
   ```python
   # Bad - Outdated style
   message = "Device {} has {} sensors".format(serial, count)
   ```

**Rationale**:
- F-strings provide better readability and performance for immediate string construction
- Percent formatting in logging provides lazy evaluation (string only built if log level active)
- This dual approach optimizes both code clarity and runtime performance

**Base Entity Classes**:
The integration provides base entity classes in `base_entity.py` to eliminate code duplication:
- `EG4DeviceEntity`: Base for all device entities (inverters, GridBOSS, parallel groups)
- `EG4BatteryEntity`: Base for individual battery entities
- `EG4StationEntity`: Base for station/plant level entities
- `EG4BaseSensor`: Base for device sensors with monotonic value support (inherits from EG4DeviceEntity)
- `EG4BaseBatterySensor`: Base for individual battery sensors (inherits from EG4BatteryEntity)
- `EG4BatteryBankEntity`: Base for battery bank aggregate sensors (inherits from EG4DeviceEntity)
- `EG4BaseSwitch`: Base for all switch entities with optimistic state management

All new entity classes should inherit from these base classes to maintain consistency.

**Coordinator Mixins** (`coordinator_mixins.py`):
The coordinator uses a mixin-based architecture for better separation of concerns:
```python
class EG4DataUpdateCoordinator(
    DeviceProcessingMixin,
    DeviceInfoMixin,
    ParameterManagementMixin,
    DSTSyncMixin,
    BackgroundTaskMixin,
    FirmwareUpdateMixin,
    DataUpdateCoordinator,
):
```

Each mixin handles a specific responsibility:
- `DeviceProcessingMixin`: Processes device objects and maps properties to sensors
- `DeviceInfoMixin`: Provides `get_device_info()`, `get_battery_device_info()`, etc.
- `ParameterManagementMixin`: Handles parameter refresh operations
- `DSTSyncMixin`: Manages daylight saving time synchronization
- `BackgroundTaskMixin`: Manages background task lifecycle
- `FirmwareUpdateMixin`: Extracts firmware update information

**Switch Base Class Pattern**:
The `EG4BaseSwitch` class provides:
- Common entity attributes setup (name, icon, unique_id, entity_id)
- Device data and parameter data helper properties (`_device_data`, `_parameter_data`)
- Optimistic state management for immediate UI feedback
- `_execute_switch_action()` helper for standardized switch operations
- `_get_inverter_or_raise()` helper for inverter object retrieval

```python
class EG4QuickChargeSwitch(EG4BaseSwitch):
    async def async_turn_on(self, **kwargs):
        await self._execute_switch_action(
            action_name="quick charge",
            enable_method="enable_quick_charge",
            disable_method="disable_quick_charge",
            turn_on=True,
        )
```

## Troubleshooting

**Integration Not Found**:
- Restart HA: `docker-compose restart homeassistant`
- Check container logs for errors
- Verify file permissions

**Authentication Errors**:
- Verify credentials
- Check network connectivity to `monitor.eg4electronics.com`
- Review SSL verification settings

**Missing Entities**:
- Check device discovery logs
- Verify API responses contain expected data
- Restart integration

**Data Not Updating**:
- Check coordinator update logs
- Verify API session is valid
- Monitor network connectivity

## Modbus Register Mapping (Control Entities)

| Control | Register | Type |
|---------|----------|------|
| EPS/Battery Backup | 21, bit 0 | Bit field |
| AC Charge Enable | 21, bit 7 | Bit field |
| Forced Charge | 21, bit 11 | Bit field |
| Forced Discharge | 21, bit 10 | Bit field |
| Green/Off-Grid Mode | 110, bit 8 | Bit field |
| PV Charge Power | 64 | 0-100% |
| Discharge Power | 65 | 0-100% |
| AC Charge Power | 66 | 0-100% |
| AC Charge SOC Limit | 67 | 0-100% |
| Charge Current | 101 | Amps |
| Discharge Current | 102 | Amps |
| On-Grid SOC Cutoff | 105 | 10-90% |
| Off-Grid SOC Cutoff | 106 | 0-100% |