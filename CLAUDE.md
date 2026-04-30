# EG4 Web Monitor Home Assistant Integration

## Project Overview

Home Assistant custom component that integrates EG4 devices (inverters, GridBOSS, batteries) with Home Assistant via local Modbus TCP, WiFi dongle, cloud API, or hybrid connectivity. Supports multi-station architecture with comprehensive device hierarchy and individual battery management.

**Two repos, one project:**
- **eg4_web_monitor** (this repo) — HA integration: coordinator, entities, config flow, tests
- **pylxpweb** (`../python/pylxpweb`) — Device/API library: client, transports, device models, registers

Both repos are maintained from this workspace. Changes to pylxpweb require a separate PR + PyPI release before the integration can consume the new version.

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.13+ |
| Package Manager | uv | Latest |
| HA Framework | homeassistant | Latest |
| API Client | pylxpweb | >= 0.9.26 |
| HTTP | aiohttp | >= 3.13 |
| Modbus | pymodbus | >= 3.6 |
| Data Models | Pydantic | >= 2.12 |
| Type Checking | mypy (strict) | Latest |
| Linting | ruff | Latest |
| Testing | pytest + pytest-homeassistant-custom-component | Latest |

## pylxpweb Library Management

### Overview

pylxpweb is our device/API library. It provides:
- `LuxpowerClient` — async HTTP client with auth, caching, retry
- Device hierarchy — Station → ParallelGroup → BaseInverter → BatteryBank → Battery
- Transport layer — HTTP, Modbus TCP, WiFi Dongle, Serial, Hybrid
- Register maps — 5 inverter families, holding + input registers
- Data scaling — automatic unit conversion per register type

**Repo**: `joyfulhouse/pylxpweb` at `/Users/bryanli/Projects/joyfulhouse/python/pylxpweb`
**PyPI**: `pylxpweb`
**Current version**: 0.9.27

### Development Workflow (Docker Volume Mount)

During development, pylxpweb source is live-mounted into the HA Docker container:
```
../python/pylxpweb/src/pylxpweb → /usr/local/lib/python3.13/site-packages/pylxpweb
```
Changes to pylxpweb source files are immediately available. Restart the container for import changes.

### Testing pylxpweb

```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
uv run pytest tests/ -x --tb=short           # 1699+ tests
uv run ruff check src/ --fix && uv run ruff format src/
uv run mypy --strict src/
```

### Release Process (CI/CD — Do NOT Manually Publish)

1. Bump version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Commit and push to main
4. Create GitHub release: `gh release create vX.Y.Z --repo joyfulhouse/pylxpweb`
5. CI pipeline: build → TestPyPI → PyPI (OIDC trusted publishing)
6. Update `eg4_web_monitor/custom_components/eg4_web_monitor/manifest.json` to require new version

### Cross-Repo Fix Workflow

When a bug fix requires changes to BOTH repos:

1. **Fix pylxpweb first** — branch, implement, test, PR, release
2. **Wait for PyPI** — verify new version is available
3. **Update eg4_web_monitor** — bump pylxpweb version in manifest.json, adapt integration code
4. **Test end-to-end** — Docker container with volume mount to verify

The `/fix-issue` and `/sprint` commands handle this automatically — they detect when an issue touches pylxpweb and flag it for the cross-repo workflow.

### Key Integration Points

```python
# Client initialization (coordinator.py)
from pylxpweb import LuxpowerClient
self.client = LuxpowerClient(username, password, session=ha_session)

# Station loading (coordinator_http.py)
from pylxpweb.devices import Station
self.station = await Station.load(self.client, plant_id)

# Transport creation (coordinator_local.py)
from pylxpweb.transports import create_transport
transport = create_transport("modbus", host="192.168.1.100", serial="CE12345678")

# Property access (coordinator_mixins.py)
voltage = inverter.grid_voltage_r  # Auto-scaled via property mixin
soc = inverter.battery_soc

# Parameter write (switch.py, number.py)
await coordinator.write_named_parameter("ac_charge_soc_limit", 90, serial)
```

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
- `options.py` — EG4OptionsFlow for interval configuration and data validation toggle

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
- **v3.2.0** — Major release: unified config flow, data validation, split-phase sensors, BMS diagnostics, 779 tests, pylxpweb>=0.9.26
- See `CHANGELOG.md` for full history

## Docker Development Environment

### Container Setup
- **Container**: `homeassistant-dev`
- **Docker Compose**: `/Users/bryanli/Projects/joyfulhouse/homeassistant-dev/docker-compose.yaml`
- **Image**: `homeassistant/home-assistant:latest` (Python 3.13)
- **Port**: 8123 → http://localhost:8123

### Volume Mappings (Host → Container)
```
eg4_web_monitor integration:
  ./eg4_web_monitor/custom_components/eg4_web_monitor → /config/custom_components/eg4_web_monitor

pylxpweb library (editable install):
  ../python/pylxpweb/src/pylxpweb → /usr/local/lib/python3.13/site-packages/pylxpweb
```

Code changes are live-mounted. Restart container to pick up Python import changes:
```bash
docker restart homeassistant-dev
docker logs -f homeassistant-dev  # Check for errors
```

### Multi-Mode Testing (Cloud vs Local vs Hybrid)

Three separate HA config directories allow testing each connection mode in isolation:

| Mode | Config Directory | Purpose |
|------|------------------|---------|
| `cloud` | `./config` | Baseline/reference - all data validated against this |
| `local` | `./config-local` | Local-only (Modbus TCP or WiFi Dongle) |
| `hybrid` | `./config-hybrid` | Local polling + cloud supplemental data |

**Switch modes** using the helper script:
```bash
cd /Users/bryanli/Projects/joyfulhouse/homeassistant-dev
./scripts/eg4-switch-mode.sh cloud   # Switch to cloud mode
./scripts/eg4-switch-mode.sh local   # Switch to local mode
./scripts/eg4-switch-mode.sh hybrid  # Switch to hybrid mode
```

**Check current mode**:
```bash
grep ":/config" docker-compose.yaml | head -1
# Returns: - ./config:/config OR - ./config-local:/config OR - ./config-hybrid:/config
```

**Setup details**:
- All configs share the same HA user accounts/UI (copied from `./config`)
- Each config has EG4 integration entry removed for fresh configuration
- Integration titles: Cloud/Hybrid use plant name (e.g., "EG4 Electronics - 6245 N WILLARD"), Local uses custom name
- Only ONE mode runs at a time to avoid API rate limits and Modbus collisions

**Validation requirements**:
- Cloud mode is baseline - all data should match production
- Local mode must have ALL entities present in cloud (minimum parity)
- Hybrid mode should poll locally with cloud supplemental data
- Allow small margin of error for live readings due to cloud lag

### Common Issues

**pylxpweb import errors** (e.g., "cannot import name 'LuxpowerClient'"):
```bash
cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
git restore src/pylxpweb/  # Restore accidentally deleted source files
docker restart homeassistant-dev
```

**Integration not loading**: Check `docker logs homeassistant-dev` for import errors

**Changes not reflecting**: Container restart required for Python imports

## Testing & Validation

### Local Testing

This project uses `uv` for dependency management. Tests run from the repository root:

```bash
# Run all tests (692 tests)
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
- `test_config_flow.py` — Cloud onboarding, menu navigation, error handling (56 tests)
- `test_reconfigure_flow.py` — Reconfigure menu, credential updates (24 tests)
- `test_config_flow_helpers.py` — Utility functions (unique IDs, timezone, migration)
- `test_coordinator.py` — Data update coordinator (120+ tests)
- `test_coordinator_http.py` — HTTP flow, error handling, station data (19 tests)
- `test_coordinator_local.py` — Modbus params, local device data, transport (23 tests)
- `test_sensor_entities.py` — Sensor entity creation, feature filtering (42 tests)
- `test_update_entities.py` — Firmware update entity lifecycle (38 tests)
- `test_options_flow.py` — Options flow, data validation toggle
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

## Development Workflow

### Sprint-Based Issue Resolution

This project uses a sprint workflow for systematic issue resolution. Issues are tracked
in beads (synced with GitHub) and executed in parallel worktrees.

**The loop**: `/sprint-plan` → approve → `/sprint` → merge → sync

### Slash Commands

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `/triage [N]` | Score and label issues | New issues need classification |
| `/sprint-plan [name]` | Plan sprint: triage, rank, group, create epic | Starting a batch of work |
| `/sprint [name]` | Execute planned sprint in parallel | After `/sprint-plan` is approved |
| `/sprint-loop [N]` | Chain N sprint cycles | Autonomous issue processing |
| `/fix-issue <N>` | Fix single issue end-to-end | One-off bug fix |
| `/ship-fix` | Simplify → commit → PR → review → comment | Individual bug fix shipping |
| `/ship` | Merge PRs with review gate + update changelog | Merging completed work |
| `/ship-pre <stage>` | Pre-release tag (alpha → beta → rc) | Community testing |
| `/ship-release` | Stable release (consolidate changelog, clean tags) | HACS production deploy |
| `/quality-check` | Full pre-commit validation | Before any commit |

### Release Lifecycle

```
/ship (merge PRs)
  → /ship-pre alpha    (internal testing)
  → /ship-pre beta     (community testing)
  → /ship-pre rc       (release candidate — bug fixes only)
  → /ship-release      (stable — triggers HACS, cleans pre-release tags)
```

All ship commands update `CHANGELOG.md`. Pre-release changelogs are cumulative.
`/ship-release` consolidates all alpha/beta/rc entries into one stable section
and deletes the pre-release tags + GitHub releases.

### Beads Formulas

Two reusable workflow templates:

- **`mol-sprint`** — 6-step sprint: triage → plan → execute → review → merge → retro
- **`mol-fix-issue`** — 5-step fix: investigate → implement → validate → review → ship

```bash
bd formula list                   # List formulas
bd cook mol-sprint --dry-run --var sprint_name=SPRINT-1  # Preview
bd mol pour mol-sprint --var sprint_name=SPRINT-1        # Execute
```

### Quality Gates (Non-Negotiable)

Every change must pass before commit:
```bash
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
uv run pytest tests/ -x --tb=short
```

### Merge Gate

`pr-merge-guard.sh` hook blocks `gh pr merge` until `.merge-ready` exists:
1. Run code-simplifier on changed files
2. Run code-reviewer agent
3. All quality gates pass
4. `touch .merge-ready`

### Issue Triage Labels

| Priority | Meaning | Label |
|----------|---------|-------|
| P0 | Data loss, security, won't load | `priority:p0` |
| P1 | Core function broken | `priority:p1` |
| P2 | Non-critical bugs, features | `priority:p2` (default) |
| P3 | Polish, cosmetic | `priority:p3` |
| P4 | Future ideas | `priority:p4` |

| Effort | Time | Label |
|--------|------|-------|
| xs | <30 min | `effort:xs` |
| s | 30min-2hr | `effort:s` |
| m | 2-4hr | `effort:m` |
| l | 4-8hr | `effort:l` |
| xl | >8hr | `effort:xl` |

## Documentation Requirements

### When to Update Docs

| Change | Update |
|--------|--------|
| Add/rename/remove sensor | `docs/DATA_MAPPING.md` |
| New register mapping | `docs/DATA_MAPPING.md` + `docs/reference/MODBUS_DOCS.md` |
| Architecture decision | New file in `docs/architecture/` |
| New API endpoint | `docs/reference/PLANT_API_DOCUMENTATION.md` |
| L/XL feature plan | `docs/plans/<date>-<topic>-design.md` |
| Sprint results | Beads molecule squash (automatic) |
| Release | `CHANGELOG.md` |

### Documentation Directory

```
docs/
├── DATA_MAPPING.md      — Canonical sensor mapping (ALWAYS consult for sensor work)
├── architecture/        — Design decisions, implementation guides
├── reference/           — API docs, Modbus registers, scaling tables
├── plans/               — Active implementation plans
│   └── archive/         — Completed plans
└── claude/              — Active agent investigation artifacts
    └── archive/         — Historical session notes
```

See `docs/README.md` for the full directory map and maintenance rules.

### Architecture Documentation

- **[STRUCTURE.md](docs/architecture/STRUCTURE.md)** — Full file layout for both repos, data flow diagram, connection modes
- **[COMPONENTS.md](docs/architecture/COMPONENTS.md)** — Coordinator mixins, entity classes, pylxpweb integration points, scaling rules, API call budget
- **[DATA_MAPPING.md](docs/DATA_MAPPING.md)** — Canonical register-to-sensor mapping (Cloud + Local + Hybrid)

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
