# Changelog

All notable changes to the EG4 Web Monitor integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0-beta.28] - 2026-02-13

### Added

- **Hybrid transport-exclusive sensors**: When local transport is attached in hybrid mode, Modbus-only sensors are now overlaid onto the cloud-derived data: `bt_temperature`, `grid_current_l1/l2/l3`, `battery_current`, `total_load_power` ([#149](https://github.com/joyfulhouse/eg4_web_monitor/issues/149))
- **Parallel battery current**: New `parallel_battery_current` sensor aggregates battery current across member inverters in parallel groups (both LOCAL and HTTP paths)
- **Data validation toggle**: New option in Options flow (local/hybrid modes only) to enable/disable pylxpweb transport-level canary checks that reject corrupt Modbus reads ([#139](https://github.com/joyfulhouse/eg4_web_monitor/issues/139))
- **Energy monotonicity validation**: Coordinator-level checks ensure lifetime energy counters never decrease (detects register corruption or rollover)
- **692 tests** (up from 666): Added 12 tests for hybrid transport overlay, parallel battery current aggregation, individual battery filtering, data validation options flow

### Fixed

- **Parallel battery count override**: When cloud API returns 0 batteries but local transport has BMS data (register 96), the correct count from member inverters is now used
- **Individual battery filtering**: Batteries with no CAN bus data (5002+ register read failure) are now skipped instead of creating "Unknown" entities in HA. Common on LXP-EU inverters.
- **Debug log accuracy**: Fixed 3 locations reporting pre-filter battery count instead of post-filter count after individual battery filtering
- **Parallel battery power sign**: Corrected sign convention in LOCAL mode parallel group aggregation ([#149](https://github.com/joyfulhouse/eg4_web_monitor/issues/149))

### Changed

- **pylxpweb data validation**: Canary checks tuned in pylxpweb v0.9.2 — grid frequency range widened to 30-90 Hz (0 Hz allowed for off-grid/EPS), `ac_input_type` check removed (unreliable), ghost battery cascade skip in `BatteryBankData`
- **Data validation translations**: All 13 language files updated with data validation toggle strings

### Dependencies

- Requires `pylxpweb>=0.9.2` (transport-level data validation with tuned canary checks)

## [3.2.0-beta.27] - 2026-02-10

### Fixed

- **Double MID device refresh** ([#148](https://github.com/joyfulhouse/eg4_web_monitor/issues/148)): Removed redundant `mid_device.refresh()` from `_process_mid_device_object()` — MID device was already refreshed by `station.refresh_all_data()`, causing 14 dongle reads/cycle instead of 7
- **HYBRID per-transport interval gating** ([#148](https://github.com/joyfulhouse/eg4_web_monitor/issues/148)): HYBRID mode now uses per-transport interval gating (same as LOCAL mode), preventing dongle saturation from polling every coordinator tick. MID device refreshes only when the dongle interval elapses.
- **LOCAL mode cache TTL adherence**: Removed `force=True` from LOCAL mode `inverter.refresh()` calls that bypassed pylxpweb cache TTLs. Added `_align_inverter_cache_ttls()` to override pylxpweb's hardcoded defaults with user-configured intervals from the options flow.
- **Smart port wrong-type sensors**: Wrong-type power/energy sensors (e.g., `smart_load1_power` on an AC Couple port) are now completely removed instead of set to `None`, preventing "Unknown" entities in the HA UI
- **Smart port status display**: Status sensors now use `device_class: enum` with translated state values ("Unused", "Smart Load", "AC Couple") instead of raw integers (0, 1, 2)
- **Status label on all-zeros early return**: Status sensors are now converted to string labels even when the all-zeros safety guard skips power sensor filtering
- **Translation completeness**: Synced all 13 translation files with `strings.json` — added missing keys for BT temperature sensor, reconcile_history service, HTTP polling interval option, and invalid date format exception
- **Proper localization**: All 12 non-English translation files now have properly translated strings instead of English placeholders
- **Silver tier validation**: Fixed `check_unavailability_logging` to scan split coordinator modules (`coordinator_http.py`, `coordinator_local.py`) instead of only `coordinator.py`

### Changed

- **HYBRID coordinator interval**: HYBRID mode now uses `_get_active_transport_intervals()` (same as LOCAL) to set the coordinator tick rate to the fastest configured transport interval
- **Smart port aggregate cleanup**: Removed dead `None`-aggregate branches in `_calculate_gridboss_aggregates()` — wrong-type L1/L2 keys no longer exist in the dict, making these branches unreachable
- **651 tests** (up from 638): Added 7 HYBRID transport gating tests, 4 cache TTL adherence tests, status label mapping and all-zeros early return tests

## [3.2.0-beta.26] - 2026-02-10

### Changed

- **Major coordinator restructuring**: Split monolithic `coordinator.py` (~3000 lines) into focused modules: `coordinator_http.py` (HTTP/cloud), `coordinator_local.py` (Modbus/dongle), `coordinator_mappings.py` (sensor mappings), `coordinator_mixins.py` (shared logic). Coordinator base class is now a thin orchestrator.
- **Number entity deduplication**: Consolidated 9 repetitive number entity classes into shared `_read_param`/`_write_param` helpers, reducing `number.py` by ~500 lines while preserving all functionality.
- **Per-transport refresh intervals**: LOCAL mode now supports independent poll intervals for each transport type (Modbus TCP, WiFi dongle, serial), configurable via options flow with sensible defaults.
- **Static entity creation**: First refresh in LOCAL mode produces zero Modbus reads by returning pre-populated sensor keys from config metadata, ensuring fast HA setup. Real data fills in on second refresh.
- **Smart port sensor filtering**: Active smart ports (status 1=smart_load, 2=ac_couple) now create both sensor types in all modes. Correct-type sensors show values; wrong-type sensors show as unavailable.

### Fixed

- **Smart port status register**: Smart port status now read from correct register (holding register 20, bit-packed) instead of input registers 105-108. Fixes smart ports incorrectly showing status=0 and missing smart load/AC couple sensors. ([#142](https://github.com/joyfulhouse/eg4_web_monitor/issues/142), [#139](https://github.com/joyfulhouse/eg4_web_monitor/issues/139))
- **Per-transport interval gate bug**: Fixed `_should_poll_transport()` stamping shared timestamp per-device instead of per-type, causing only the first device to be polled when multiple devices share the same transport type. Fixes missing parallel group data and unavailable battery entities in multi-device LOCAL setups. ([#142](https://github.com/joyfulhouse/eg4_web_monitor/issues/142), [cc8d4e2](https://github.com/joyfulhouse/eg4_web_monitor/commit/cc8d4e2))
- **Smart port aggregate power**: `_calculate_gridboss_aggregates()` now returns `None` for wrong-type port aggregates instead of including zeroed values that skew totals
- **Private pylxpweb imports**: Replaced internal module imports (`pylxpweb.transports.data`) with public API equivalents

### Removed

- **Legacy config flow**: Deleted `_config_flow_legacy.py` (~1969 lines) — unified config flow fully replaces the 12-mixin architecture
- **Dead code**: `CircuitBreaker` class, `utils.py` helpers, `const/brand.py`, `const/modbus.py`, `const/working_modes.py`, `const/diagnostics.py`, `test_config_flow_schemas.py`, `test_utils.py`
- **Duplicated constants**: Consolidated scattered constant definitions into canonical locations

### Added

- **623 tests** (up from ~350): Comprehensive test suites for sensor entities, coordinator HTTP/local paths, config flow, reconfigure flow, update entities, number/switch/select entities
- **DATA_MAPPING.md**: Canonical reference documenting all register-to-sensor and Cloud API-to-sensor mappings, smart port decode logic, GridBOSS CT overlay, entity counts, and all calculations
- **Network scan**: Auto-discover Modbus/dongle devices on local network during config flow
- **Serial transport**: Modbus RTU via USB-to-RS485 adapter support in config flow

### Dependencies

- Requires `pylxpweb>=0.9.0` (canonical register migration, dual-source MIDDevice, smart port status fix)

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
