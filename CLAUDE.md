# EG4 Web Monitor Home Assistant Integration

## Project Overview
Home Assistant custom component that integrates EG4 devices (inverters, GridBOSS, batteries) with Home Assistant through the unofficial EG4 web monitoring API. Supports multi-station architecture with comprehensive device hierarchy and individual battery management.

## Quality Scale Compliance

### Platinum Tier Status - January 2025 🏆
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

## Recent Release History

### v1.4.5 - January 2025: Operating Mode Control
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
cd /Users/bryanli/Projects/joyfulhouse/custom_components/eg4_web_monitor

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
cd /Users/bryanli/Projects/joyfulhouse/custom_components/eg4_web_monitor

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

# 5. Verify all 301 tests pass with no teardown errors
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