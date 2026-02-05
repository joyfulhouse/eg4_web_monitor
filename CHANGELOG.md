# Changelog

All notable changes to the EG4 Web Monitor integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0-beta.22] - 2026-02-05

### Fixed

- **Local Parallel Group AC Power**: Added `ac_power` and `output_power` sensors to local mode parallel groups for parity with HTTP/hybrid modes
- **Shutdown Listener Warnings**: Prevent "Unable to remove unknown job listener" warnings by properly tracking one-time listener state
- **Smart Port Status Warning Spam**: Only log Smart Port status warning once per device instead of every update cycle
- **Legacy Inverter Family Names**: Map legacy family names (e.g., `LXP_EU`, `PV_SERIES`) to new names to prevent "Unknown inverter family" warnings
- **services.yaml YAML Syntax**: Fixed YAML parser error by quoting description containing colon

### Dependencies

- Requires `pylxpweb>=0.8.3`

## [3.2.0-beta.21] - 2026-02-05

### Fixed

- **Automatic Config Entry Migration**: Added `async_migrate_entry()` hook so Home Assistant automatically migrates legacy modbus/dongle config entries to the unified local format on startup. Previously, migration only ran when users manually clicked the reconfigure gear icon, causing broken integrations that required deletion and recreation. ([#83](https://github.com/joyfulhouse/eg4_web_monitor/issues/83))

### Changed

- **Config Flow Version**: Bumped from v1 to v2 to trigger automatic migration for existing entries
- **AC-Coupled PV Option**: Temporarily disabled in options UI until feature is fully implemented (constants and translations preserved)

## [3.2.0-beta.18] - 2026-02-04

### Changed

- **BREAKING: Inverter family constants renamed** for clarity (aligns with pylxpweb 0.8.0):
  - `INVERTER_FAMILY_SNA` → `INVERTER_FAMILY_EG4_OFFGRID`
  - `INVERTER_FAMILY_PV_SERIES` → `INVERTER_FAMILY_EG4_HYBRID`
  - `INVERTER_FAMILY_LXP_EU` → `INVERTER_FAMILY_LXP`
  - `INVERTER_FAMILY_LXP_LV` → `INVERTER_FAMILY_LXP`
  - Old constants emit `DeprecationWarning` but continue to work

### Added

- **Deprecation warnings** for legacy family constants via module-level `__getattr__`
- **LXP-LB-BR 10kW support** - Brazil model device type for local discovery

### Fixed

- Updated all code comments to use new family names

### Dependencies

- Requires `pylxpweb>=0.8.0`

## [3.2.0-beta.10] - 2026-02-01

### Changed

- **Hybrid Mode Simplification**: Replaced ~430-line manual local-read/merge pipeline with library transport routing. `_async_update_hybrid_data()` now delegates to `_async_update_http_data()` — pylxpweb's `inverter.refresh()` automatically routes runtime/energy through attached local transports with internal TTL caching.
- **Removed Cloud Refresh Throttling**: The `cloud_refresh_interval` option and associated state (`_last_cloud_refresh`, `_cloud_refresh_interval`, `skip_cloud_refresh`) are removed; library-level cache TTLs handle throttling.
- **Transport Labels via Introspection**: Hybrid transport labels (`Hybrid (Modbus)`, `Hybrid (Dongle)`) now detected from `inverter._transport` instead of manual tracking.

### Removed

- `_async_update_hybrid_data()` manual pipeline, `_hybrid_legacy_read()`, `_merge_local_data_with_http()`, `_merge_local_into_parallel_groups()`
- `_hybrid_transport_cache` state and cleanup in `async_unload_entry()`
- `CONF_CLOUD_REFRESH_INTERVAL`, `DEFAULT_CLOUD_REFRESH_INTERVAL`, `MIN_CLOUD_REFRESH_INTERVAL`, `MAX_CLOUD_REFRESH_INTERVAL` constants
- Cloud refresh interval from options UI and all 14 translation files

## [3.2.0-beta.7] - 2026-02-01

### Changed

- **Local Transport Concurrency**: Refactored `_async_update_local_data` to group transports by endpoint, enabling concurrent processing of independent connections while keeping sequential access for shared physical links.
- **Parallel Group Refresh Optimization**: Replaced sequential `group.refresh()` calls with concurrent PG energy-only fetches, eliminating redundant inverter/MID re-refreshes that `refresh_all_data()` already covers.

### Fixed

- **Firmware Version Cache Regression**: Restored `_firmware_cache` lookup in `_process_single_local_device` — firmware was being read from Modbus on every 5-second update cycle instead of cached after first read.
- **Per-Register Error Handling**: A single failing Modbus register range no longer aborts the entire parameter fetch; each range is read independently with individual error logging.

### Documentation

- Updated README to document Serial Modbus (USB/RS485) transport option.
- Clarified hybrid mode description (DST auto-sync and quick charge control).

## [3.2.0] - 2026-01-30

### Breaking Changes

- **Config Flow Architecture**: Replaced the 23-file, 12-mixin config flow with a single unified `EG4ConfigFlow` class. The user-facing behavior is similar but uses menu-based navigation instead of separate onboarding paths per connection type.

### Added

- **Menu-Based Config Flow**: New setup starts with a menu offering "Cloud (HTTP)" or "Local Device" entry points. Users can add the other side at any time via reconfigure, and the connection type (http/local/hybrid) is auto-derived.
- **Unified Reconfigure Flow**: Single reconfigure menu with options to update cloud credentials, add/remove local devices, or detach cloud — replacing 4 separate reconfigure mixins.
- **Auto-Detection for Local Devices**: Modbus and Dongle setup now auto-detects serial number, device model, inverter family, firmware version, and parallel group configuration.
- **Translation Validation**: New `validate_translations.py` script and CI job to verify all translation files have complete key coverage.

### Changed

- **Config Flow Structure**: `config_flow/` directory simplified from 23 files to 5 files:
  - `__init__.py` — Unified EG4ConfigFlow class (~920 lines)
  - `discovery.py` — Device auto-discovery via Modbus/Dongle
  - `schemas.py` — Voluptuous schema builders
  - `helpers.py` — Utility functions (unique IDs, migration, etc.)
  - `options.py` — EG4OptionsFlow for interval configuration
- **Connection Type Derivation**: Connection type is no longer chosen upfront by the user. It's automatically derived: cloud-only → `http`, local-only → `local`, both → `hybrid`.

### Fixed

- **BaseInverter Factory Dispatch**: Fixed calls to non-existent `BaseInverter.from_transport()` — now correctly dispatches to `from_modbus_transport()` or `from_dongle_transport()` based on transport type.
- **Mypy Type Errors**: Fixed nullable type handling in `discovery.py` (runtime data) and `coordinator.py` (config_entry, plant_id).
- **LuxpowerConnectionError Handling**: Connection errors during config flow now correctly show "cannot_connect" instead of "unknown".

### Removed

- Deleted 18 config flow files: `base.py`, `onboarding/` (5 files), `reconfigure/` (6 files), `transitions/` (5 files)
- Deleted 5 obsolete test files: `test_main_configflow.py`, `test_onboarding_mixins.py`, `test_reconfigure_mixins.py`, `test_transition_mixin.py`, `test_transitions.py`
- Removed dead `get_reconfigure_entry()` helper function

### Dependencies

- Requires `pylxpweb>=0.6.5`

## [3.1.1] - 2025-01-11

### Added

- **Parallel Group Aggregate Battery Sensors**: New sensors for parallel groups that aggregate battery data across all inverters:
  - Battery Charge Power (W)
  - Battery Discharge Power (W)
  - Battery Power (net W)
  - Battery State of Charge (weighted average %)
  - Battery Max Capacity (Ah)
  - Battery Current Capacity (Ah)
  - Battery Voltage (average V)
  - Battery Count (total modules)

  > **Note**: SOC is calculated as a capacity-weighted average: `(total_current_capacity / total_max_capacity) * 100`. This is more accurate than a simple average when batteries have different capacities.

### Dependencies

- Requires `pylxpweb>=0.5.7` (adds aggregate battery properties to ParallelGroup)

## [3.1.0] - 2025-01-11

### Added

- **Local Modbus/RS485 Connection (Experimental)**: Three connection modes leveraging pylxpweb 0.5.0 transport abstraction:
  - **HTTP (Cloud-only)**: Original behavior using EG4 cloud API (30s polling)
  - **Modbus (Local-only)**: Direct Modbus TCP connection to dongle (5s polling)
  - **Hybrid (Local + Cloud)**: Modbus for fast runtime data + HTTP for cloud-only features

  > **Note**: Local RS485/Modbus connection is experimental and has open issues reported by users. Use with caution and report any issues on GitHub.

- **GridBOSS Smart Load and AC Couple Power Sensors** (#78): New power sensors for GridBOSS devices with Smart Port functionality
- **Reconfigure Flow for Modbus/Hybrid**: Support for changing connection type after initial setup

### Fixed

- **Quick Charge Switch Bounce**: Fixed issue where Quick Charge switch would briefly show OFF after turning ON, then bounce back to ON after coordinator refresh. The optimistic state is now properly maintained until the coordinator refresh completes.
- **Battery Bank Entity Registration** (#81): Fixed device registry error by registering battery bank devices before individual batteries
- **Battery Bank Aggregate Stats** (#76): Battery Bank entity now created with aggregate stats even when `totalNumber=0` in API response
- **Battery Discovery for Short-Format Keys** (#76): Fixed battery discovery when API returns short-format `batteryKey` values
- **Missing batteryArray Handling** (#76): Gracefully handle API responses missing the `batteryArray` field
- **Reconfigure Flow Abort Message**: Added missing `brand_name` placeholder to `reconfigure_successful` abort message

### Changed

- **Modbus Transport Serialization**: Serialize transport reads and add diagnostic logging for debugging connection issues
- **GridBOSS Energy Sensors**: Refactored to use aggregate L1+L2 combined sensors instead of separate per-phase sensors
- **Smart Port Sensor Filtering**: Sensors now filtered based on Smart Port mode (AC Couple vs Smart Load)

### Dependencies

- Requires `pylxpweb>=0.5.6`
- Requires `pymodbus>=3.6.0` (for local Modbus connection)

## [3.0.0] - 2024-12-15

### Breaking Changes

- **Entity ID Changes**: Entity naming convention updated for consistency. Existing automations, scripts, and dashboards may need to be updated.
  - Sensor keys are now more explicit (e.g., `power` → `ac_power`, `soc` → `state_of_charge`)
  - Battery sensors use `battery_{battery_key}` format consistently
  - GridBOSS sensors use `eg4_gridboss_{serial}` prefix
- **Sensor Availability**: Some sensors that were previously always available may now show as "unavailable" if the device doesn't support them (feature detection)

### Added

- **Multi-Brand Support Architecture**: Support for EG4 Electronics, LuxpowerTek, and Fortress Power
- **Binary Sensor: Dongle Connectivity**: Shows whether the inverter's communication dongle is online
- **Switch: Off Grid Mode**: Control Off-Grid/Green Mode on inverters
- **Battery Status Sensor**: Restored battery status sensor lost in refactoring
- **EPS Power Sensors**: EPS Power L1, L2 for 12000XP and compatible devices
- **Inverter Feature Detection**: Only creates sensors that the device actually supports
- **Optimistic Value Context**: Immediate UI feedback for number entity changes

### Fixed

- Quick Charge Switch always showing OFF (#66)
- Working Mode Switches not refreshing parameters after actions (#67)
- Battery Backup Switch conflicts with reauth flow (#50, #55)
- Number Entity value bouncing after parameter changes (#46)
- Reauthentication Flow session expiration handling (#70)
- GridBOSS Auto-Detection when parallel group data not pre-configured (#72)
- 12000XP full sensor support (#49, #63)
- mypy strict typing compliance

### Architecture

- **Base Entity Classes**: `EG4DeviceEntity`, `EG4BatteryEntity`, `EG4BaseSensor`, `EG4BaseSwitch`
- **Coordinator Mixins**: Modular coordinator with focused mixins
- **Platinum Quality Scale**: Meeting all 36 Home Assistant quality scale requirements

### Dependencies

- Requires `pylxpweb>=0.4.4`

[3.2.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.2.0
[3.1.1]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.1
[3.1.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.0
[3.0.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.0.0
