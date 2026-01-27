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

## Configuration Flow (4 Steps)

### Step 1: Authentication
- Form: Username, Password, Base URL, SSL Verification
- Establishes session with JSESSIONID cookie

### Step 2: Station Selection
- Auto-select if single station, dropdown if multiple
- Entry name: "EG4 Web Monitor {station_name}"
- Unique ID: `{username}_{plant_id}`

### Step 3: Device Discovery
- Calls `getParallelGroupDetails` and `inverterOverview/list` with `plantId` filter
- Creates devices: Parallel Groups, Inverters, GridBOSS MID devices
- Applies device-specific sensor sets

### Step 4: Battery Association
- For each inverter: calls `getBatteryInfo` with `serialNum`
- Creates inverter status sensors from non-batteryArray data
- Creates individual battery sensors from batteryArray using `batteryKey`

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

### Important Notes for All Releases Until v3.0
**CRITICAL**: All release notes from v2.2.1 through v2.x.x must include the following HACS upgrade notice for users coming from versions prior to v2.2.1:

```markdown
## Upgrade Notes

**⚠️ Important for users upgrading from versions prior to v2.2.1:**

If you installed a version **before v2.2.1**, you may need to **re-add this repository to HACS** due to the repository restructuring that occurred in v2.2.1:

1. In HACS, remove the EG4 Web Monitor integration
2. Click the three dots menu (⋮) in HACS
3. Select "Custom repositories"
4. Add: `https://github.com/joyfulhouse/eg4_web_monitor`
5. Category: Integration
6. Click "Add"
7. Install EG4 Web Monitor from HACS
8. Restart Home Assistant

Your configuration will be preserved during this process.
```

This notice can be removed starting with v3.0.0, as sufficient time will have passed for users to upgrade.

## Recent Release History

### v3.1.8-beta.10 - January 2026: WiFi Dongle Connection Reset Fix
**Bug Fixes:**
- Fixed WiFi dongle "Connection reset" errors during register reads (#83)
  - Root cause: Dongle overwhelmed by rapid sequential register group reads
  - Added 200ms delay between register group reads in pylxpweb
  - The dongle only supports ONE concurrent TCP connection and has limited processing power

**Dependency Updates:**
- Require pylxpweb>=0.5.19 for dongle connection stability fix

### v3.1.8-beta.9 - January 2026: Dual-Mode Control & Configurable Intervals
**New Features:**
- **Dual-Mode Control**: Switches and number entities now support both HTTP API and local Modbus register writes
  - HTTP/Hybrid modes: Use cloud API methods (richer feature set, validation)
  - Modbus/Dongle modes: Direct register writes for local-only control
  - Quick Charge remains HTTP-only (cloud task feature)
- **Configurable Refresh Intervals**: New Options Flow for customizing polling intervals
  - Sensor Update Interval: 5-300 seconds (default: 5s local, 30s HTTP)
  - Parameter Refresh Interval: 5-1440 minutes (default: 60 minutes)
  - Access via Settings → Integrations → EG4 → Configure

**Technical Details:**
- New coordinator methods: `has_http_api()`, `is_local_only()`, `write_named_parameter()`
- New Modbus register constants in const.py for control operations
- `EG4OptionsFlow` class for UI-based interval configuration
- Options update triggers integration reload for immediate effect

**Modbus Register Mapping:**
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

### v3.1.8-beta.8 - January 2026: Modbus/Dongle Configuration Entities Fix
**Bug Fixes:**
- Fixed configuration entities (switches, numbers) not showing for Modbus/Dongle modes (#89)
  - Root cause: Empty `inverter_model` in config entry caused `SUPPORTED_INVERTER_MODELS` check to fail
  - Added `INVERTER_FAMILY_DEFAULT_MODELS` mapping to derive model from inverter family
  - PV_SERIES → "18kPV", SNA → "12000XP", LXP_EU → "LXP-EU"
  - Added "lxp" to `SUPPORTED_INVERTER_MODELS` for LuxPower EU support
  - Switches (Quick Charge, Battery Backup, etc.) and Number entities now properly created

### v3.1.8-beta.7 - January 2026: Firmware Version Reading & Dongle Retry Logic
**Bug Fixes:**
- Fixed firmware version reading for Modbus/Dongle transports
  - Registers 7-8 contain firmware prefix as byte-swapped ASCII (e.g., "FAAB")
  - v1 extracted from high byte of register 9, v2 from low byte of register 10
  - Now returns full firmware code matching web API format (e.g., "FAAB-2525")
- Improved WiFi dongle reliability with retry logic (#83)
  - Added 2 retries with 0.5s delay for empty responses
  - Enhanced error messages explaining potential firmware blocking
  - Better diagnostic information for troubleshooting

**New Features:**
- Added `read_firmware_version()` and `read_serial_number()` methods to DongleTransport
- New diagnostic script: `utils/read_firmware_registers.py` for debugging firmware register data

**Dependency Updates:**
- Require pylxpweb>=0.5.17 for firmware reading and dongle retry fixes

### v3.1.8-beta.3 - January 2026: Modbus Sensor Key Fix & WiFi Dongle Support
**Bug Fixes:**
- Fixed "only 8 sensors showing" in Modbus mode - sensor keys now match SENSOR_TYPES definitions (#83)
- Key mapping alignment: `ppv`→`pv_total_power`, `soc`→`state_of_charge`, `pCharge`→`battery_charge_power`, etc.
- All Modbus/Dongle/Hybrid modes now create ~40 sensors instead of 8

**New Features:**
- **WiFi Dongle Support**: Direct local access via inverter's WiFi dongle on port 8000 (no additional hardware)
- New connection type: "WiFi Dongle" in config flow
- Requires dongle serial + inverter serial for authentication
- Pure asyncio TCP implementation (no pymodbus dependency for dongle mode)

**Technical Details:**
- WiFi dongle protocol is NOT standard Modbus TCP - uses custom LuxPower/EG4 packet format
- Packet structure: `0xA1 0x1A` prefix + version + length + function code + serials + data + CRC-16
- TCP function codes: 0xC1 (heartbeat), 0xC2 (Modbus wrap), 0xC3 (read), 0xC4 (write)
- Note: Recent dongle firmware may block port 8000 access for security reasons

**Dependency Updates:**
- Require pylxpweb>=0.5.15 for WiFi dongle transport support

### v3.1.7 - January 2026: Inverter Family Selection for Modbus
**New Features:**
- Add inverter family selection dropdown in Modbus configuration (standalone, hybrid, and reconfigure flows)
- Support for model-specific Modbus register maps from pylxpweb 0.5.12
- Available families: PV_SERIES (18kPV/FlexBOSS), SNA (12000XP/6000XP), LXP_EU (European)

**Technical Details:**
- Different inverter families have different register layouts (32-bit vs 16-bit power values, register offsets)
- LXP-EU 12K uses 16-bit power registers with 4-register offset vs PV Series 32-bit registers
- Backward compatible - defaults to PV_SERIES for existing configurations

**Dependency Updates:**
- Require pylxpweb>=0.5.12 for model-specific register map support

### v3.0.0-rc.17 - December 2025: GridBOSS Auto-Sync Fix
**Bug Fixes:**
- GridBOSS now automatically detected even when parallel group data is not pre-configured (#72)
- Require pylxpweb>=0.4.4 which auto-calls `/api/inverter/autoParallel` to initialize parallel groups when GridBOSS is detected but parallel data is missing

### v3.0.0-rc.16 - December 2025: Dependency Update & Documentation Fixes
**Dependency Updates:**
- Require pylxpweb>=0.4.3 for improved re-authentication handling that prevents silent failures on transient network issues (#70)

**Documentation:**
- Fixed manual installation instructions to correctly copy inner `custom_components/eg4_web_monitor` directory (#69)
- Fixed entity ID format in examples (removed incorrect `eg4_` prefix)
- Fixed automation example using wrong entity ID (`battery_backup_eps` → `battery_backup`)
- Added FAQ about parameter refresh timing when changing settings via EG4 web portal

### v3.0.0-rc.15 - December 2025: Working Mode Switch Fix & Type Safety
**Bug Fixes:**
- Fixed working mode switches (battery_backup_mode, ac_charge, etc.) not refreshing parameters after actions (#67)
- Changed `refresh_params=False` to `refresh_params=True` in `EG4WorkingModeSwitch`
- Added explicit type hints to `ParameterManagementMixin` and `DSTSyncMixin`
- Fixed `OperatingMode` import path to use main pylxpweb module
- Removed explicit Protocol self type from mixin method

### v3.0.0-rc.14 - December 2025: Bug Fixes & Optimizations
**Bug Fixes:**
- Comprehensive bug fixes and performance optimizations
- Resolved mypy type errors in DongleStatusMixin

### v3.0.0-rc.13 - December 2025: Quick Charge Switch Fix
- Fixed Quick Charge switch always showing OFF (#66)
- Quick charge status now properly fetched during coordinator updates

### v3.0.0-beta.7 - November 2025: Architecture Refactor & Code Quality
Major refactoring release introducing base classes and mixins for better code organization:

**Architecture Improvements:**
- New `EG4BaseSwitch` base class eliminates ~40% code duplication in switch platform
- Coordinator logic split into focused mixins in `coordinator_mixins.py`:
  - `DeviceProcessingMixin`: Device data processing and property mapping
  - `DeviceInfoMixin`: Device info retrieval for all device types
  - `ParameterManagementMixin`: Parameter refresh operations
  - `DSTSyncMixin`: Daylight saving time synchronization
  - `BackgroundTaskMixin`: Background task management
  - `FirmwareUpdateMixin`: Firmware update info extraction
- Added `SensorConfig` TypedDict for type-safe sensor configuration
- Added `optimistic_state_context()` for clean switch state management

**Dependency Updates:**
- pylxpweb 0.3.18: Removed monotonic enforcement for energy sensors (now handled by HA's TOTAL_INCREASING)

**Bug Fixes:**
- Fixed deprecated `asyncio.get_event_loop()` usage (now uses `time.monotonic()`)
- Fixed `DeviceInfo` return type inconsistencies
- Removed unused parameters from utility functions

### v2.2.4 - November 2025: AC Charge Power Decimal Support
- AC Charge Power number entity supports decimal values (0.1 kW increments)
- Updated precision to 1 decimal place
- Removed integer-only validation
- Fixes issue #37

### v2.2.3 - November 2025: Background Task Cleanup
- Proper background task cleanup and test teardown fixes
- Enhanced session management

### v2.2.2 - November 2025: Session Management
- Comprehensive session management and re-authentication fixes

### v2.2.1 - November 2025: Repository Restructuring
- Repository restructured for HACS compliance
- Integration moved to `custom_components/` subdirectory
- **Note**: Users upgrading from pre-v2.2.1 may need to re-add repository to HACS

### v1.4.5 - September 2025: Operating Mode Control
- Operating Mode select entity (Normal/Standby) with real-time parameter sync
- XP device filtering for EPS Battery Backup (XP devices don't support EPS)
- Enhanced device compatibility detection
- Select platform registration

### v1.4.2 - September 2025: Cache Management
- Smart cache invalidation before hour boundaries
- Pre-emptive cache clearing within 5 minutes of hour boundary
- Rate-limited invalidation (10-minute minimum interval)
- UTC-based timing for consistency

### v1.4.0 - September 2025: Production Optimization
- Code quality validation with ruff (zero linting errors)
- Circuit breaker pattern with exponential backoff
- 9 consolidated utility functions (70% code reduction)
- Enhanced parameter reading error handling

### v1.3.2 - September 2025: Diagnostic Refresh
- Device refresh buttons for all device types
- Battery refresh buttons with proper device assignment
- Advanced API caching with differentiated TTL
- Battery cell voltage precision fix (÷1000 for millivolts)
- Battery backup status accuracy fix
- Parallel group naming improvements

### v1.2.4 - September 2025: Code Quality
- Code quality improvements with automated linting
- Consolidated field mappings in const.py
- Missing sensor resolution (PV power, SOC, radiator temps)
- Entity count: 231 sensors

### v1.2.3 - September 2025: Parameter Refresh
- Multi-inverter parameter synchronization
- Hourly automatic parameter refresh
- Cross-device SOC limit updates
- Background task processing

### Earlier Features
- GridBOSS MidBox Runtime integration (174 optimized sensors)
- Frequency scaling correction (÷100 for Hz)
- Essential sensor preservation (grid power at 0W)
- Invalid binary sensors removed
- Diagnostic status sensors added
- Cell voltage delta sensors

## Testing & Validation

### Local Testing Strategy

**IMPORTANT**: Always test locally in an isolated environment before pushing to GitHub to avoid consuming compute credits.

**Isolated Test Environment Setup**:
```bash
# Create isolated virtual environment (one-time setup)
cd /tmp && python3 -m venv eg4-test
source /tmp/eg4-test/bin/activate
pip install pytest pytest-asyncio pytest-homeassistant-custom-component pytest-cov mypy aiohttp ruff homeassistant
```

**Running Tests** (run from repository root):
```bash
# Activate the test environment
source /tmp/eg4-test/bin/activate

# Navigate to repository root
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor

# Run all tests
pytest tests/ -x --tb=short

# Run with code coverage
pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing

# Run single test file
pytest tests/test_config_flow.py -v
```

**Pre-Commit Validation Checklist** (all commands run from repository root):
```bash
# Navigate to repository root
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor

# Activate test environment
source /tmp/eg4-test/bin/activate

# 1. Run all unit tests
pytest tests/ -x

# 2. Run tier validation scripts (validates repository structure)
python3 tests/validate_silver_tier.py
python3 tests/validate_gold_tier.py
python3 tests/validate_platinum_tier.py

# 3. Run mypy type checking on integration files
mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/

# 4. Run ruff linting on integration files
ruff check custom_components/ --fix && ruff format custom_components/

# 5. Verify all 127 tests pass with no teardown errors
# 6. Only push to GitHub after all local validations pass
```

**Why This Approach?**:
- Repository structure follows HACS best practices with integration in `custom_components/` subdirectory
- No PYTHONPATH hacks needed - pytest-homeassistant-custom-component handles directory structure
- Tests automatically discover the integration via the `custom_components/` directory
- Isolated virtual environment prevents system package interference
- Saves GitHub Actions compute credits by testing locally first

### Testing Framework
This integration uses **pytest-homeassistant-custom-component** for Home Assistant-specific testing:
- **Repository**: https://github.com/MatthewFlamm/pytest-homeassistant-custom-component
- **Purpose**: Provides pytest fixtures and utilities for testing Home Assistant custom components
- **Key Features**:
  - `enable_custom_integrations` fixture for loading custom components
  - `hass` fixture providing a configured Home Assistant instance
  - Async test support with proper event loop management
  - Config entry and entity testing utilities

**Test Configuration**:
```python
# tests/conftest.py
pytest_plugins = "pytest_homeassistant_custom_component"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield
```

**Coverage Configuration** (.coveragerc):
- Excludes `secrets.py` (credentials file, not in git)
- Excludes `test_plant_api.py` (test utility, not production code)
- Excludes all test directories and files
- Coverage target: >95% for production code only

**Requirements** (requirements-test.txt):
```
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
pytest-homeassistant-custom-component>=0.13.0
homeassistant>=2024.1.0
```

**Running Tests**:
```bash
# Install test dependencies (from repository root)
pip install -r tests/requirements-test.txt

# Run all tests with coverage
pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing

# Run specific test file
pytest tests/test_config_flow.py -v

# Run with async debugging
pytest tests/ -v --log-cli-level=DEBUG
```

### Phase 1: API Testing
```bash
cd eg4_inverter_api
cp ../tests/secrets.py.example ../secrets.py
# Edit secrets.py with credentials
python tests/test_client.py
```

### Phase 2: Docker Environment
```bash
cd homeassistant-dev
docker-compose up -d
# Access: http://localhost:8123
```

### Phase 3: Integration Setup
1. Settings → Devices & Services → Add Integration
2. Search "EG4 Web Monitor"
3. Enter credentials and select station
4. Verify device discovery

### Phase 4: Entity Validation
- Standard Inverters: Power, voltage, current, energy, temperature sensors
- GridBOSS: Grid management, UPS, load, smart port sensors
- Batteries: Voltage, current, SoC, SoH, temperature, cycle count

### Phase 5: Testing Checklist
- Configuration flow (auth, station selection, discovery)
- Device discovery (inverters, GridBOSS, batteries)
- Entity creation (proper IDs, units, device classes)
- Data validation (real-time updates, accuracy)
- Error handling (network loss, session expiry, invalid responses)

### Phase 6: Log Analysis
```bash
# Enable debug logging in configuration.yaml
logger:
  logs:
    eg4_web_monitor: debug

# Monitor logs
docker-compose logs -f homeassistant | grep eg4_web_monitor
```

### Phase 7: Performance Validation
- Update intervals: 30 seconds default
- Concurrent API calls for parallel devices
- Session management: 2-hour reauthentication
- Resource usage monitoring

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

## Success Criteria

1. API tests pass for all endpoints
2. Docker environment running healthy
3. Configuration flow completes without errors
4. All expected devices appear in HA
5. Sensors show real-time data with proper units
6. Values match EG4 monitor website
7. Data refreshes automatically every 30 seconds
8. Graceful handling of network/API issues
9. Efficient API usage with parallel requests
10. Comprehensive debug logging available
- use https://docs.aiohttp.org/en/stable/testing.html for aiohttp testing