# Changelog

All notable changes to the EG4 Web Monitor integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Off-grid mode state change fails on fresh LOCAL-only install** ([#194](https://github.com/joyfulhouse/eg4_web_monitor/issues/194)): Smart port status sensors received raw integer `0` instead of enum string `"unused"` when all ports were unused and no cache existed, causing HA to reject entity state writes and block switch toggles.
- **Firmware cache sentinel inconsistency**: `_resolve_local_firmware()` now caches a sentinel when `read_firmware_version()` returns empty string (avoids unnecessary Modbus reads every poll cycle) and treats `"Unknown"` entries from the LOCAL path as sentinels in HYBRID mode.

## [3.2.0] - 2026-03-09

The biggest release in the integration's history: 279 commits, 43 beta/RC releases, and contributions from the community. Local polling is no longer experimental — it's production-ready across all four connection modes with full entity parity validated in Docker.

### Changed

- **WiFi dongle minimum polling interval** ([#185](https://github.com/joyfulhouse/eg4_web_monitor/issues/185)): Lowered from 15s to 5s, allowing users who need faster reaction times to opt in via the options flow. Default remains 30s.

### Breaking Changes

- **Config Flow Architecture**: Replaced the 23-file, 12-mixin config flow with a single unified `EG4ConfigFlow` class using menu-based navigation. Existing config entries migrate automatically.
- **Inverter Family Constants Renamed**: `INVERTER_FAMILY_SNA` → `EG4_OFFGRID`, `PV_SERIES` → `EG4_HYBRID`, `LXP_EU`/`LXP_LV` → `LXP`. Old names emit `DeprecationWarning` but continue to work.
- **Config Entry Version**: Bumped from v1 to v2. Legacy modbus/dongle entries auto-migrate on startup via `async_migrate_entry()`.

### Added

#### New Sensors
- **Split-phase per-leg power sensors** ([#178](https://github.com/joyfulhouse/eg4_web_monitor/issues/178)): Separate L1/L2 sensors for EPS and grid power on split-phase inverters
- **BMS bank-level diagnostic sensors**: Min cell voltage/temperature, BMS charge/discharge current limits, charge voltage reference, discharge cutoff, battery type, voltage inverter sample — always available from BMS registers, no CAN bus needed
- **Battery bank cycle count**: From BMS register 106 (always available)
- **Battery bank current**: Mapped from `battery_data.current` in both LOCAL and HTTP paths
- **Battery last seen** ([#170](https://github.com/joyfulhouse/eg4_web_monitor/issues/170)): Per-battery diagnostic timestamp showing last physical read — useful for >4 battery round-robin systems
- **Common voltage aliases** ([#159](https://github.com/joyfulhouse/eg4_web_monitor/issues/159)): `grid_voltage` and `eps_voltage` for single/split-phase inverters
- **Signed net sensors**: Consolidated charge/discharge pairs into single signed sensors
- **Charge rate sensors**: New sensors for monitoring charge rates
- **Parallel battery current**: Aggregates battery current across parallel group members
- **Hybrid transport-exclusive sensors** ([#149](https://github.com/joyfulhouse/eg4_web_monitor/issues/149)): `bt_temperature`, `grid_current_l1/l2/l3`, `battery_current`, `total_load_power` overlaid from local transport in hybrid mode
- **PV Start Voltage number** and **PV Input Mode select** entities
- **Connection transport** and **transport IP** diagnostic sensors
- **API monitoring sensors**: Peak rate, hourly, and daily cloud API request counters

#### New Controls
- **GridBOSS smart port mode select entities**: Configure each smart port (1–4) between Off, Smart Load, and AC Couple modes via holding register 20 bit fields
- **Battery Backup and Grid Peak Shaving switches** in LOCAL mode ([#153](https://github.com/joyfulhouse/eg4_web_monitor/issues/153))

#### Config Flow
- **Menu-based setup**: Cloud (HTTP) or Local Device entry points with auto-derived connection type
- **Unified reconfigure flow**: Update credentials, add/remove local devices, or detach cloud
- **Auto-detection for local devices**: Serial number, model, family, firmware, and parallel group configuration detected automatically
- **Network scan**: Auto-discover Modbus/dongle devices on local network
- **Serial transport**: Modbus RTU via USB-to-RS485 adapter support
- **Automatic config migration**: `async_migrate_entry()` migrates v1 entries on startup ([#83](https://github.com/joyfulhouse/eg4_web_monitor/issues/83))
- **LXP-LB-BR 10kW support**: Brazil model device type for local discovery

#### Data Integrity
- **WiFi dongle cross-request validation** ([#158](https://github.com/joyfulhouse/eg4_web_monitor/issues/158)): Response serial, function code, and register validated against request — catches misrouted cloud responses causing garbage readings
- **Data validation toggle**: Options flow setting to enable/disable canary checks on Modbus reads
- **Energy monotonicity validation**: Lifetime energy counters validated to never decrease
- **Battery canary checks**: Reject readings with `battery_count > 20` or `abs(current) > 500A`

#### Architecture
- **Shared battery bank mirroring** ([#169](https://github.com/joyfulhouse/eg4_web_monitor/issues/169)): In parallel systems with shared batteries, LOCAL path mirrors primary's battery_bank_* values to secondary inverters
- **Static entity creation**: First LOCAL refresh produces zero Modbus reads — entities created from config metadata, real data fills in on second refresh
- **Round-robin battery cache** ([#165](https://github.com/joyfulhouse/eg4_web_monitor/issues/165)): Serial-based battery tracking across round-robin rotation for >4 battery systems
- **Per-transport refresh intervals**: Independent poll intervals for Modbus TCP, WiFi dongle, and serial, configurable via options flow
- **Complete i18n**: 12 language translations (Chinese Simplified, Chinese Traditional, Dutch, French, German, Italian, Japanese, Korean, Polish, Portuguese, Russian, Spanish)

#### Testing & Quality
- **779 tests** (up from ~350 in v3.1.8): Comprehensive suites for all entity types, coordinator paths, config flow, reconfigure flow, and tier validation
- **DATA_MAPPING.md**: Canonical reference for all register-to-sensor and API-to-sensor mappings
- **CI**: Automated issue triage with Claude, translation validation, quality tier scripts

### Fixed

- **HYBRID mode setup hang on HA restart** ([#180](https://github.com/joyfulhouse/eg4_web_monitor/issues/180)): Removed forced Modbus read from transport attachment — Waveshare RS485 gateway stale buffers caused 3–5 minute blocks on `async_config_entry_first_refresh()`
- **HYBRID late sensor registration**: Transport-only sensor keys missing from first update are now discovered and registered via coordinator listener
- **Individual battery entities permanently unavailable** ([#180](https://github.com/joyfulhouse/eg4_web_monitor/issues/180)): pylxpweb no longer permanently disables battery reads after transient WiFi dongle failures; coordinator falls back to round-robin cache
- **Smart port status register** ([#142](https://github.com/joyfulhouse/eg4_web_monitor/issues/142), [#139](https://github.com/joyfulhouse/eg4_web_monitor/issues/139)): Now reads from correct holding register 20 (bit-packed) instead of input registers 105-108
- **Smart port wrong-type sensors**: Removed instead of set to `None`, preventing "Unknown" entities
- **Smart port status display**: Uses `device_class: enum` with translated labels
- **Smart load energy register addresses** ([#146](https://github.com/joyfulhouse/eg4_web_monitor/issues/146)): Corrected off-by-one in daily and lifetime energy registers
- **Parallel group consumption** ([#149](https://github.com/joyfulhouse/eg4_web_monitor/issues/149)): Energy-balance formula using MID device grid power overlay; fixes 0W consumption and energy divergence between LOCAL/CLOUD
- **Parallel group grid voltage**: Overlaid from MID device CT reading; fixes 0V on inverters where firmware doesn't populate regs 193-194
- **Per-transport interval gate bug**: `_should_poll_transport()` now stamps per-type instead of per-device, fixing multi-device LOCAL setups where only first device was polled
- **Double MID device refresh** ([#148](https://github.com/joyfulhouse/eg4_web_monitor/issues/148)): Eliminated redundant refresh that doubled dongle reads per cycle (14→7)
- **Three-phase entity registration order** ([#154](https://github.com/joyfulhouse/eg4_web_monitor/issues/154)): Parallel group devices registered before referencing entities, preventing `via_device` warnings on HA 2025.12.0+
- **GridBOSS firmware shows "unknown"** ([#156](https://github.com/joyfulhouse/eg4_web_monitor/issues/156)): Read from transport + firmware cache instead of always-None property
- **Battery bank diagnostic sensors permanently Unavailable**: Split into CORE (BMS, always available) and CAN (intermittent) key sets
- **Battery bank min_soh**: Falls back to bank-level SOH from input register 5 high byte
- **Secondary inverter battery bank suppression** ([#169](https://github.com/joyfulhouse/eg4_web_monitor/issues/169)): Deferred to runtime to avoid false positives on LXP-EU dual-battery systems
- **Cloud API fallback for HYBRID switch writes**: Falls back to HTTP when local transport write fails
- **LOCAL mode cache TTL adherence**: Removed `force=True` that bypassed pylxpweb cache TTLs
- **Transport disconnect on shutdown**: Prevents unload timeout from dangling connections
- **Truncated battery serial handling** ([#165](https://github.com/joyfulhouse/eg4_web_monitor/issues/165)): Skip in round-robin cache instead of crashing
- **FlexBOSS model detection** ([#152](https://github.com/joyfulhouse/eg4_web_monitor/issues/152)): Corrected during local discovery
- **Network scan dongle prefill crash** ([#172](https://github.com/joyfulhouse/eg4_web_monitor/issues/172)): Handle partial user_input during discovery

### Changed

- **Major coordinator restructuring**: Split monolithic `coordinator.py` (~3000 lines) into focused modules: `coordinator_http.py`, `coordinator_local.py`, `coordinator_mappings.py`, `coordinator_mixins.py`
- **Number entity deduplication**: Consolidated 9 classes into shared `_read_param`/`_write_param` helpers (-500 lines)
- **Hybrid mode simplification**: Replaced ~430-line manual merge pipeline with pylxpweb library transport routing
- **Config flow**: Simplified from 23 files to 5 files
- **last_polled sensors disabled by default**: Reduces database noise
- **GridBOSS CT overlay**: Shared between HTTP and LOCAL paths for consistent energy data
- **HYBRID coordinator interval**: Uses fastest configured transport interval

### Removed

- Legacy config flow (23 files, ~1969 lines)
- `CircuitBreaker` class, `utils.py` helpers, dead constant modules
- Cloud refresh interval option (replaced by library-level cache TTLs)
- Grid type mismatch detection (config is authoritative)
- 5 obsolete test files

### Dependencies

- Requires `pylxpweb>=0.9.26`
- Requires `pymodbus>=3.6.0`
- Requires `pyserial>=3.5`

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
