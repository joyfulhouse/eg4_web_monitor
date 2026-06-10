# Changelog

All notable changes to the EG4 Web Monitor integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.4.0-beta.3] - 2026-06-10

### Fixed

- **HYBRID: a failed local-transport attach at startup is now retried** (live-found on production validating beta.2): right after a Home Assistant restart, the WiFi dongle's single TCP slot can still be held by the previous session, so the attach times out — previously that one transient failure parked the device on cloud data **forever** (until a manual reload). Failed attaches are now retried about once a minute and recover automatically; a **Repairs issue** explains the degraded state and clears itself on reconnection.
- **HYBRID: devices running degraded (failed attach) no longer freeze**: while a locally-configured device falls back to cloud data, its cloud API caches — tuned for the slow supplemental role — could pin its sensors at stale values for the whole cache window. Degraded devices now bypass those caches and keep updating at the normal coordinator cadence, a degraded GridBOSS is no longer throttled by the dongle polling interval (it isn't using the dongle), and cloud-fallback failures are logged instead of being silently swallowed.

## [3.4.0-beta.2] - 2026-06-10

### Added

- **Charge Last switch** ([#177](https://github.com/joyfulhouse/eg4_web_monitor/issues/177)): toggle the battery *Charge Last* function (`FUNC_CHARGE_LAST`, register 110 bit 4) from Home Assistant. Off (default, "charge first"): PV charges the battery before exporting surplus. On: PV serves house loads and grid export first and charges the battery last — automate it to reserve battery headroom during peak production (e.g. charge to ~90% in the morning, enable Charge Last through midday, disable in the afternoon to top off). Works in cloud, local, and hybrid modes; hybrid prefers the local Modbus write and falls back to the cloud function-control API.
- **Confirmed EG4_OFFGRID registers** ([#197](https://github.com/joyfulhouse/eg4_web_monitor/issues/197)): surfaced three register groups live-validated on 12000XP hardware (Modbus sweep + cloud cross-reference). All new entities are created for the EG4_OFFGRID family only (12000XP/6000XP).
  - **Per-phase EPS load power** — new `EPS Load Power L1` / `EPS Load Power L2` sensors (input regs 129/130, W) plus a combined `EPS Load Power` (L1+L2 sum, matches the cloud `epsLoadPower` field within polling skew). Useful for diagnosing breaker-panel load imbalance.
  - **Load Power** (input reg 170, `Pload`) — enabled for EG4_OFFGRID. The cloud zeroes its reg-170 mirror for these models, so the value is taken from the local register in LOCAL and HYBRID modes (never the cloud zero); valid both grid-tied and in EPS mode.
  - **Battery Discharge Power** (input reg 11 / cloud `pDisCharge`) — reintroduced as a per-inverter sensor in all connection modes for EG4_OFFGRID. The signed net `Battery Power` sensor is unchanged; the one-time registry cleanup from the charge/discharge consolidation no longer removes this key.

### Fixed

- **Smart Port Status ValueError when all four ports are Unused** ([#248](https://github.com/joyfulhouse/eg4_web_monitor/issues/248), regression of [#195](https://github.com/joyfulhouse/eg4_web_monitor/issues/195)): re-lands the PR [#198](https://github.com/joyfulhouse/eg4_web_monitor/pull/198) fix that was lost in a history rewrite — on GridBOSS units with **all four smart ports Unused**, the all-zeros status read was treated as corrupt, leaking raw integer `0` to HA's enum validation (`ValueError: state value '0' not in options`) on every refresh and leaving the four Smart Port Status sensors permanently unavailable. All-zeros is again recognized as a valid state, and on corrupt no-cache reads status values are normalized to valid labels (out-of-range → `unused`) so raw integers can never reach HA. The lost regression tests are re-landed alongside.
- **Family-UNKNOWN devices regain their real sensor profile** ([#219](https://github.com/joyfulhouse/eg4_web_monitor/issues/219)): when firmware reports an unmapped device type code (e.g. 6000XP on `ccaa-140A0A`), the integration now derives the family profile from the model name, restoring split-phase sensors (`eps_power_l1/l2`) in all connection modes. The user-selected **Grid Type** override now also survives every LOCAL poll (previously only the first static refresh). The diagnostic `inverter_family` sensor reports the effective family, with `family_source`/`detected_inverter_family` breadcrumbs preserved in coordinator data.
- **Behavior change for legacy UNKNOWN-family LOCAL entries**: the static path no longer creates the full create-all sensor set for them — phase sensors the hardware never had (dead three-phase R/S/T entities on split-phase models) are no longer provided. A **Repairs issue** is raised on each affected device explaining the pruning; if your device truly is three-phase, set **Grid Type** in the integration options.
- **Modbus serial (USB/RS485) devices in HYBRID mode** ([#233](https://github.com/joyfulhouse/eg4_web_monitor/issues/233)): devices sharing one RS485 serial bus are now refreshed **sequentially** — concurrent reads on a shared bus corrupted responses. Serial-attached devices reachable only via the station (e.g. a GridBOSS the inverter cache never holds) are now disconnected on unload/reload, closing a leaked-open-serial-port bug. Malformed local-device configs (serial/port type drift) no longer crash setup, and a **Repairs issue** is raised when a serial port cannot be opened (the device temporarily falls back to cloud data).
- **Battery bank Full/Remaining Capacity double-counted in cloud mode** (via pylxpweb 0.9.36b2): on banks whose master battery mirrors pack-level totals into its own module fields, the cloud's module-array sums over-reported the bank (e.g. 1400 Ah "full" on an 840 Ah bank). The bank sensors now use the BMS-reported bank pair, matching the local register path exactly; open-loop (lead-acid / no BMS comms) systems keep the legacy fields.

### Changed

- Minimum `pylxpweb` raised to **0.9.36b2**: WiFi dongle parameter writes now survive mid-sequence TCP connection drops without write wars ([#201](https://github.com/joyfulhouse/eg4_web_monitor/issues/201)) — the full read-modify-write sequence retries with a fresh register read, never resending stale values; write ACKs are echo-validated against misrouted dongle responses; all multi-request reads are serialized on the dongle's single TCP link; and the cloud battery-bank capacity fix above.

### Documentation

- **Example dashboards re-audited against current entity IDs** ([#209](https://github.com/joyfulhouse/eg4_web_monitor/issues/209)): refreshed `examples/dashboards/` (`battery_details.yaml`, `energy_overview.yaml`, `eg4_solar_monitor.yaml`) toward the entity IDs the integration generates today. This re-applies the v3.2.0 renames from #212 (which were lost when `main` was superseded by the 3.3.0 release branch) and catches 3.3.0/3.4.0 drift: dropped the phantom `eg4_` entity-ID prefix (sensors are `sensor.<model>_<serial>_*`), `battery_soc` → `state_of_charge`, `pv_power` → `pv_total_power`, `daily_*` → `yield`/`consumption`/`grid_import`, inverter `load_power` → `consumption_power`, per-battery `state_of_charge` → `relative_soc` and `cell_voltage_max/min` → `max/min_cell_voltage`, per-battery sensors on the `<model>_battery_<serial>_<nn>` device (`real_power`, `state_of_health`, `cell_temperature_delta`, `max/min_voltage_cell_number`), `eg4_gridboss_*` → `grid_boss_*`, switches `battery_backup` → `eps_battery_backup` and `peak_shaving_mode` → `grid_peak_shaving_mode`, and `battery_high/low_soc_limit` → `system_charge_soc_limit`/`on_grid_soc_cut_off`. Rows for controls that never shipped were replaced honestly: `grid_charge` → **AC Charge** (`ac_charge_mode`); `feed_in_grid` ("Grid Export") has no real counterpart — the row is now plain **Forced Discharge** (a true export toggle would need `FUNC_FEED_IN_GRID_EN`, reg 21 bit 15, not yet exposed); `battery_equalization` likewise — use **System Charge SOC Limit** (accepts 101 for top-balancing), with the v3.4.0 **Battery Charge/Discharge Control** selects shown as regime pickers only. Note: Home Assistant preserves existing registry entries, so long-standing installs may retain older object IDs — verify exact IDs under Settings → Devices & Services → Entities.
- **Battery control mode — EG4 UI label cross-reference**: documented the mapping from EG4 web-monitor parameter labels to Home Assistant entities for the SOC/Voltage battery limits — e.g. EG4's *"Back Up Volt(V)"* is the **AC Charge End Voltage** entity (reg 159, the voltage twin of the AC-charge SOC limit, active in battery-backup/voltage mode) and *"System Charge Volt Limit(V)"* is reg 228. Added a label table to [CONFIGURATION.md](docs/CONFIGURATION.md#battery-control-mode-soc-vs-voltage), the canonical register/param table plus confirmed register-179 bits 9/10 to [DATA_MAPPING.md](docs/DATA_MAPPING.md), and a discovery pointer in the README.

## [3.4.0-beta.1] - 2026-06-08

### Added

- **Battery control mode — SOC vs Voltage** ([#48](https://github.com/joyfulhouse/eg4_web_monitor/issues/48)): choose whether the inverter governs battery charge/discharge limits by **State-of-Charge (closed-loop / BMS lithium)** or **Voltage (open-loop / lead-acid / no BMS comms)**, mirroring the inverter's own register-179 regime bits (bit 9 charge, bit 10 discharge). Works in cloud, local, and hybrid modes.
  - Two new **select** entities per inverter — **Battery Charge Control** and **Battery Discharge Control** (`SOC` / `Voltage`) — read and write the live regime and are fully automatable.
  - Five new **voltage-limit number** entities (the open-loop counterparts of the existing SOC limits): **System Charge Voltage Limit** (reg 228), **On-Grid Cut-Off Voltage** (reg 169), **Off-Grid Cut-Off Voltage** (reg 100), **AC Charge Start Voltage** (reg 158), **AC Charge End Voltage** (reg 159).
  - **Configure → Battery Charge/Discharge Control Mode** options: pre-filled from the inverter's live regime; changing them reconfigures the inverter and gates which limit entities are enabled by default to reduce clutter.
- **Entity decluttering by regime**: limit controls for the non-selected regime are created but **disabled by default** (SOC is the default, preserving existing behavior). The active controls expose an `is_effective` attribute and log a non-blocking warning if you set a limit that the current regime ignores.

### Fixed

- **Voltage limits read 10× low in cloud/hybrid mode**: the cloud API returns battery voltages already scaled (e.g. `59.5 V`) while local Modbus returns raw decivolts (`595`); a blind ÷10 produced `5.95 V`. Reads are now magnitude-normalized so both transports agree. (Pre-existing latent issue surfaced while adding the voltage entities.)
- **On-Grid Cut-Off Voltage showed "unknown" in cloud**: the cloud exposes register 169 as `HOLD_ON_GRID_EOD_VOLTAGE`; the mapping used a non-canonical spelling. Confirmed against a live cloud register read.

### Changed

- Minimum `pylxpweb` raised to **0.9.36b1** (dual cloud/transport battery-control methods, `BatteryControlMode`, register 228 definition, and the register-169 cloud name fix).

### Notes

- In a **parallel group**, the inverter firmware syncs the battery control regime across all inverters; setting it on one propagates to the group. The integration writes all inverters and refreshes them together so the per-inverter entities stay consistent.

## [3.3.0] - 2026-06-05

Stable release consolidating the `3.3.0-beta.1`–`3.3.0-beta.8` cycle. Detailed beta notes are retained below.

### Added

- **Per-inverter Load Energy sensors** (`Eload` regs 171/172) — the inverter-served load, a separate meter from whole-home Consumption (see beta.6).
- **BMS permission/request sensors** ([#232](https://github.com/joyfulhouse/eg4_web_monitor/issues/232)) — BMS charge/discharge/force-charge state in all modes (see beta.1).
- **Power factor, GridBOSS smart-load current, granular energy** ([#243](https://github.com/joyfulhouse/eg4_web_monitor/issues/243)).

### Fixed

- **PV Charge Power did not stick on Modbus/hybrid inverters** ("set 1 kW → reads 0" bounce): the local path wrote register 64 (a 0-100% limit) with a lossy `kW↔%` conversion. It now targets register **74** (`HOLD_FORCED_CHG_POWER_CMD`, 100W units) in kW like AC charge power; the cloud path was already correct. Hardware-verified: FlexBOSS reg74=20→2.0 kW, 18kPV reg74=120→12.0 kW.
- **Daily consumption never reset in LOCAL mode** ([#227](https://github.com/joyfulhouse/eg4_web_monitor/issues/227)) and **`total_increasing` dip warnings** ([#218](https://github.com/joyfulhouse/eg4_web_monitor/issues/218)) (see beta.5).
- **EPS/grid aggregate voltage, PV input current, hybrid L1/L2** ([#243](https://github.com/joyfulhouse/eg4_web_monitor/issues/243)).

### Changed

- Minimum `pylxpweb` raised to **0.9.35** (adds register 74 to the local register map).

## [3.3.0-beta.6] - 2026-06-02

### Added

- **Per-inverter Load Energy sensors** (`Load Energy` / `Load Energy (Lifetime)`): the inverter-served load read straight from the `Eload` registers (171/172), matching the EG4 cloud's per-inverter `todayUsage`/`totalUsage` exactly in every mode (validated to the decimal on live hardware). This is a **separate meter** from whole-home **Consumption**: in a parallel group a master inverter can read `0` Load Energy while the home still draws power — grid-direct loads bypass the inverter — and the per-inverter Eload sum sits far below whole-home consumption (the cloud reports them as two distinct numbers, on two different screens). Non-breaking: existing `consumption`/`consumption_lifetime` entities are unchanged and `consumption` remains the whole-home figure (energy balance / GridBOSS CT overlay / cloud group). No new dependency. See [DATA_MAPPING.md → "Consumption vs Load Energy"](docs/DATA_MAPPING.md).

## [3.3.0-beta.5] - 2026-06-02

### Fixed

- **Daily consumption never reset to zero in LOCAL mode** ([#227](https://github.com/joyfulhouse/eg4_web_monitor/issues/227)): In local/dongle/Modbus modes the computed `consumption`/`consumption_lifetime` sensors were pinned at their daily peak by an unbounded monotonic clamp in the coordinator — they only rose when surpassing the previous peak and never reset at midnight. Cloud and hybrid were unaffected. Removed the clamp and rely on Home Assistant's `total_increasing` state class, which detects meter resets natively.
- **`total_increasing` sensors triggering recorder warning on small dips** ([#218](https://github.com/joyfulhouse/eg4_web_monitor/issues/218)): Energy-balance rounding noise caused `consumption` and `consumption_lifetime` to step down by 0.1 kWh between polls (e.g. 2917.1 → 2917.0), tripping HA's "state is not strictly increasing" warning. Added a sensor-level guard that pins downward dips ≤10% to the previous high-water mark — matching HA recorder's reset-detection threshold so daily resets, lifetime counter wraps, and inverter replacements (drops >10%) still pass through unchanged. Paired with the #227 fix, midnight resets pass through while rounding jitter is suppressed.

## [3.3.0-beta.1] - 2026-05-31

### Added

- **BMS permission/request sensors** ([#232](https://github.com/joyfulhouse/eg4_web_monitor/issues/232)): three battery-bank diagnostic sensors surfacing the BMS's charge/discharge/force-charge state, available in cloud, local, and hybrid modes:
  - **BMS Charge Allowed** and **BMS Discharge Allowed** (Allowed / Blocked) — cleared when the bank is full / empty respectively
  - **BMS Force Charge Request** (Requested / Idle) — the BMS requesting a full calibration charge; read-only, distinct from the writable Forced Charge control

  Decoded from input register 95 (bitmap `0x01`/`0x02`/`0x20`) in local/hybrid and from the cloud `bmsCharge`/`bmsDischarge`/`bmsForceCharge` fields — the local decode was validated against the cloud values on live hardware. Requires `pylxpweb>=0.9.32`.

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

## [3.1.1] - 2026-01-11

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

## [3.1.0] - 2026-01-11

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

## [3.0.0] - 2026-01-07

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

[Unreleased]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0...HEAD
[3.3.0]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.2.0...v3.3.0
[3.3.0-beta.6]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0-beta.5...v3.3.0-beta.6
[3.3.0-beta.5]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.3.0-beta.1...v3.3.0-beta.5
[3.3.0-beta.1]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.2.0...v3.3.0-beta.1
[3.2.0]: https://github.com/joyfulhouse/eg4_web_monitor/compare/v3.1.8...v3.2.0
[3.1.1]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.1
[3.1.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.0
[3.0.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.0.0
