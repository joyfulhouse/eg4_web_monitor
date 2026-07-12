# EG4 Web Monitor Home Assistant Integration

## Project Overview
Home Assistant custom component that integrates EG4 devices (inverters, GridBOSS, batteries) with Home Assistant via local Modbus TCP, WiFi dongle, cloud API, or hybrid connectivity. Supports multi-station architecture with comprehensive device hierarchy and individual battery management.

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
- **v3.5.0-beta.3** — BETA (2026-07-12): Quick Charge local control; requires **pylxpweb>=0.9.38b4**. LOCAL/HYBRID start = paired reg 233+234 contiguous frame (live-validated FlexBOSS21 2026-07-12; per-inverter, unlike group-wide portal starts; lone idle 234 write firmware-rejected #251; XP stays cloud-routed #296/#308). Duration number: idle-set stores start preference (`start_preference` attr = restart-safe persistence channel), active-set adjusts live countdown + seeds throttled status cache. #367 bank-current canary scaled (150A/battery, 500A floor, 2000A ceiling, present-battery corroboration — 9-battery bank staled at solar noon; pending Caymanwent confirm). Gate: codex BLOCKED(2P1+2P2)→fixed→CLEAR + DRY + simplifier.
- **v3.5.0-beta.2** — BETA (2026-07-11): dual-scan fast-follow; requires **pylxpweb>=0.9.38b2** (orchestrator force-poll — beta.1's headline #353 fix was broken by a 5-min idle-cache replay; ac-charge cloud enable read). eg4: per-serial install lock (reload-safe), tz-retry stale-row purge + DST-at-midnight alignment. Scan residue: #362 (write-refresh semantics), #363 (DRY batch).
- **v3.5.0-beta.1** — BETA (2026-07-11): requires **pylxpweb>=0.9.38b1**. Fixes: #353 firmware multi-step chain orchestration (6000XP partial-update; FAILED abort, start-visibility grace, settle window, result surfacing — hardware validation pending on eode's retained 6000XP), #348 battery-temp 0x7F sentinel (no-BMS secondary all-unknown), #346 daily-energy float-boundary tick rejection, #359 PV Start Voltage cloud read (folded into VoltageNumberSpec), #345 INFO log demotion. Internal: #342 DRY consolidation (PRs #354/#357/#358), CI strict-typing pin extraction from requirements-test.txt.
- **v3.4.0** — STABLE (2026-07-07): consolidates the beta.1–beta.27 + rc.1 cycle; requires **pylxpweb>=0.9.37**. The final tri-vendor review (Codex GPT-5.5 + Gemini 3.1 Pro + Claude, 3 rounds, both repos against v3.3.0/v0.9.35 baselines) found and fixed pre-ship: pylxpweb's cloud raw-register write NEVER worked (nested-dict form-encoding dropped the values on the wire — root cause of the historical param-specific cloud write failures; the five 3.4.0 voltage-limit numbers were dead in pure-CLOUD until 0.9.37's live-validated named-write rewrite), a `_read_modbus_parameters` completeness-flag race across concurrently-polled endpoint groups (#282 regression class), options-flow battery-control-mode writes firing on any options save, partial reg-179 write convergence, and pylxpweb `set_ac_charge_voltage_limits` ×10/÷10 inversion. DRY items 1–4 applied (−79 lines); deferred simplifier items → #342, pylxpweb follow-ups → pylxpweb#223. Merged to main (PR #341), tagged latest, prod rolled via HACS (605 entities / 0 unavailable).
- **v3.4.0-rc.1** — RELEASE CANDIDATE: identical source to beta.27, version promotion only (semver orders beta.27 < rc.1 < final). pylxpweb 0.9.36 stable pin unchanged. Cut after the three-mode sweep passed + #334/#335/#336 landed.
- **v3.4.0-beta.27** — EPS Load un-aliased (#335, brendonlobo123: EPS/EPS Load identical on XP): #197's off-grid enablement aliased combined pEpsL1N/L2N onto eps_load_* — validated while smart load idle (the one matching state); #222 consumption identity = the proof (peps/pEpsL1N/L2N combined, epsLoadPower subset, smartLoadPower GEN port). eps_load_power → real epsLoadPower via NEW pylxpweb 0.9.36-STABLE property (#219, cut as first non-beta of the line: also #217 log dedup + #218 transports README); per-leg eps_load L1/L2 RETIRED (no per-leg cloud field; #253 suffix purge, changelog breaking-note per agy P2); statistics carry over on unchanged total unique_id, semantic level-shift documented; pure-LOCAL total = unknown (no local subset register — probe = follow-up). LOCAL PS-power sweep fix #334 rides too. Review: Opus CLEAN + agy P1 = the seam-gap/pin lockstep (property merged mid-review — KNOWN_SEAM_GAPS tripwire worked exactly as designed), agy P2s → changelog notes + real-resolution-path tests (upgraded #222 e2e now pins combined-3330 vs subset-365 divergence). 1949 tests, requires pylxpweb>=0.9.36 (stable).
- **v3.4.0-beta.26** — off-grid AC Charge SOC fix (#331, brendonlobo123's nightly REMOTE_SET_ERROR): reg 67 SOC Limit is grid-tied-only (offgrid firmware-rejects, portal-absent, reads 0 on XP-v2 dump) -> gated off EG4_OFFGRID w/ one-shot Repairs; NEW AC Charge Start/End Battery SOC numbers (regs 160/161, portal-verified, enabled-default, offgrid-only); reg 161 = pinned SOC-101 top-balance candidate; pylxpweb b28 maps 161 (only unmapped family member, historical accident) + family-scopes the old "161 read-only" FlexBOSS note (grid-tied observation preserved; offgrid local write UNVERIFIED, readback-verify covers) + #215 [serial]+frame-context dongle logs (#213); Repairs suffix serial-boundary hardened all callers. Review: Opus refuted agy's cache-incoherence P1 (wholesale param replace), Opus found the read-only-note contradiction; raw-161 dual-key workaround DELETED for named path per both reviewers. 1957 tests, requires pylxpweb>=0.9.36b28.
- **v3.4.0-beta.25** — Grid Peak Shaving complete (#328, DoubleDoc's pylxpweb#158 hardware test + live cloud correlation): reg 206 = 0.1 kW CONFIRMED, PS family (206/232 power deci-kW, 207/218 SOC, 208/219 volt decivolts) mapped for local reads w/ cloud-identical strings + direct local writes (pylxpweb b27 #214, dual-CLEAN review); number entity pre-checks FUNC_GRID_PEAK_SHAVING with verify-then-block (live reg-179 read on stale-falsy cache — portal-side enable honored immediately) (#329); firmware NAKs PS writes + zeroes setpoint while mode off (live-verified). Pin bump also delivers b26 proven-capable Fast-mode (ivanfmartinez: >40-reg success ever → cooldown never permanent latch). 1932 tests, requires pylxpweb>=0.9.36b27.
- **v3.4.0-beta.24** — post-RC bug batch from the 2026-07-04 report wave: DST switch un-pinned (coordinator never populated daylightSavingTime + hourly sync misread detect_dst_status semantics + sync compared against a never-re-read cached flag — portal toggles now converge <=1h) (#324/#323); Refresh Data button forces runtime+energy+battery+parameters with obsolete coordinator link-down gate removed (pylxpweb b24's _fetch_parameters guard routes params via cloud in HYBRID) and raises on parameters_complete=False (#325/#322); pylxpweb b25 — misrouted/unsolicited dongle frames (incl. heartbeats 0xC1 + param frames 0xC3/0xC4 via new request-aware TCP-func validation) raise TransportResponseMismatchError and no longer latch Fast coalescing off, ~5-min cooldown re-probe; short reads deliberately still latch (firmware-cap signature) (#320/pylxpweb#211). Codex quota dead until Jul 7 — Antigravity ran the adversarial gate and found 3 confirmed P1s after Opus passed both eg4 PRs clean. #321 closed (HA-core reload-on-enable), #319 milestoned 3.5.0 (entity-name sort grouping), #317 evidence upgraded (XP-v2 dump: regs 84-89 read cleanly; write evidence still missing; asked mjstrand for extended-range dump 0-380). 1922+ tests, requires pylxpweb>=0.9.36b25.
- **v3.4.0-beta.23** — 3.4.0 RELEASE CANDIDATE: Forced Charge schedule times gated off EG4_OFFGRID (#316, mjstrand's live REMOTE_SET_ERROR on 12000XP v2 + zero HOLD_FORCED_CHARGE on the offgrid portal page — beta.20 over-generalized from the hybrid page; one-word gate change control→control_grid_tied + one-shot Repairs via generalized #307 machinery). INVERSE finding: offgrid portal DOES carry a full 3-window Forced Discharge widget (12 holdParam + 6 timeParam inputs) that we suppress → #317, blocked on hardware write evidence; FUNC_FORCED_CHG_EN switch (reg 21 bit 11) deliberately left on offgrid (different register, no rejection evidence — noted on #317). mjstrand redirected from XLS testing plan → utils/map_registers.py register dump (read-only, safe on his son's off-grid hybrid). 1911 tests, requires pylxpweb>=0.9.36b24 (unchanged).
- **v3.4.0-beta.22** — 3.4.0 issue-zeroing release (every open issue resolved; only #176 RS485 remains, milestoned 3.5.0): NEW schedule families Peak Shaving (209-212, LSP_HOLD_DIS_CHG_POWER_TIME_37-44 cloud reads)/Generator (256-259, HYBRID+OFFGRID per SNA probe)/Off-Grid (269-274, HYBRID) via portal-verified registers + atomic writeTime endpoint (pylxpweb #209); SMART_LOAD excluded (DATAFRAME_TIMEOUT both units, regs unpinned); **ALL schedule time entities disabled-by-default incl. existing four families' window 1** (registry keeps already-enabled); Share Battery switch HOLD 110 bit 3 FUNC_BAT_SHARED (#306/#288); Quick Charge XP fix — reg 233 family-rejected → cloud-routed status+control, fresh-data-terminated retention, Duration reads reg 234 live, 3 review rounds (#308/#296); XP-v2 Battery Backup Mode gated (rejected write + portal absence), EPS KEPT (SNA dump shows live-enabled — Opus caught over-gating; NO device_type_code isolates XP v2, family=54 covers SNA+XP+6000XP) (#307/#289); positional retirement across slot shifts (#309/#302); switch cloud-fallback cache seeding, zero stale publishes (state-sequence test found 2nd window) (#311/#310); targeted param reads link-down-gated (#313); pylxpweb b24 (#207 reg96 shared-battery context, #208 _fetch_parameters link-down guard + cloud _set_schedule raw-register write was BROKEN→named params, #209 schedules, #210 UNVERIFIED offgrid bit-8 FUNC_GREEN_EN removed — absent=unknown not False). Codex found post-Opus blockers on #308(×2 rounds)+#311+#312; Opus found SNA over-gating on #307. 1851+ tests, requires pylxpweb>=0.9.36b24.
- **v3.4.0-beta.21** — four-scanner bug sweep (Claude ×2, Codex, Antigravity) + dead-code cleanup, both repos: LOCAL 6h battery eviction was unreachable on non-empty polls (removed pack frozen until restart) → unconditional per-merge, HYBRID local-only branch now bounded too (#300); HYBRID number/select/time controls get switch-parity cloud fallback (attempt-then-fallback + immediate cloud on transport_link_down + link-down-aware post-write refreshes + note_parameters_written cache seeding — Codex P1 caught the refresh hang + sticky-param revert after Opus passed) (#301); switch/select availability gates on coordinator health (3-strike breaker, day-to-day inert) (#303); dead code −106/−26 lines (#299/pylxpweb#202). pylxpweb b23: holding short-read guard both transports (#203), pos:{N} fallback-key eviction (#204), cloud schedule getters + link-down probe 6x cheaper (#205). Antigravity scan: 2 real/1 refuted; Gemini CLI permanently dead (free-tier deprecated) — use `agy --print "<prompt>"` (prompt is --print's VALUE). Mode-switch gotcha: fresh container layer lacks pylxpweb dist-info → HA pip-installs over bind mount (cross-device error, integration dead) → recreate minimal dist-info after EVERY switch. 3-mode docker validation: cloud 555/local 588/hybrid 622 entities, 0 unexpected unavailable, hybrid⊇cloud exactly, local gaps = documented cloud-only set. 1785 tests, requires pylxpweb>=0.9.36b23. Follow-ups filed: #302 (positional retirement keying), #304 (availability vs cloud-fallback design), pylxpweb#206 (_fetch_parameters link-down guard).
- **v3.4.0-beta.20** — all schedule types as time entities (#295): AC First (regs 152-157, EG4_OFFGRID-only fails-closed, portal-verified cloud params HOLD_AC_FIRST_*), Forced Charge (76-81, control-capable) and Forced Discharge (84-89, control-capable minus offgrid) join AC Charge via a 4-row declarative ScheduleTimeSpec table — time.py +18 lines total for 4x schedules; window 1 enabled, 2/3 registry-disabled per schedule; (152,6) LOCAL read family-gated per-cycle like the entities; #283 behaviors shared and matrix-tested. pylxpweb b22 (ScheduleType.AC_FIRST + canonical names for 84-89/152-157). Dual Opus+Codex gate, code-simplifier verdict already-minimal. 1751 tests, requires pylxpweb>=0.9.36b22.
- **v3.4.0-beta.19** — #258 hybrid battery-gap fix: HYBRID/CLOUD merge carried the CLOUD payload as battery-dict baseline (availability=key-presence) so transient cloud omissions/re-keys dropped entity subsets on rotating >4 banks; now once-published batteries carry forward (original battery_last_seen kept, staleness=data not availability) with a 6h eviction bound (physical removal converges, no restart), migration/supersede exclusions, LOCAL rr-cache same bound + authoritative retirement; pylxpweb b21: transient duplicate-serial reads disambiguate as {serial}@posN + re-verify on next clean read of the position (no lasting phantom), battery Pos-dump prints full 15-char serial (old 14-char dump = phantom-duplicate red herring). Dual Opus+Codex gate (2 CONFIRMED Codex P1s fixed in round). 1659 tests, requires pylxpweb>=0.9.36b21.
- **v3.4.0-beta.18** — sprint 3.4.0-final-prep: 9 issues (#275, #252, #258, #274, #282, #272, #277, #254, #287). Fixed: multi-station cloud onboarding (int station ids vs frontend string submission, #275); one serial-first battery identity across Cloud/Local/Hybrid with in-place registry migration — mode changes no longer duplicate battery devices (#252); HYBRID battery outage-cycle merge guard (#258); Grid Sell Back Power re-scaled percent→kW (raw 100 W units) + new Fast Zero Export switch, LXP included (#274); parameter-backed controls no longer blank for an hour after one failed range read — sticky carry-forward + 2-min retry floor + per-device retry set, both integration and pylxpweb layers (#282); battery firmware version zero-padded to match cloud, no more HYBRID flap (#287). Added: Start Discharge/Charge power threshold numbers, HOLD 116 (1 W raw) + signed HOLD 117 local-only disabled-default (#272); AC Charge schedule time entities, 3 windows, regs 68-73 packed hour-low/minute-high byte (#277); Modbus Read Block Size option Conservative/Fast with probe-once fallback latch (#254). Every PR passed a dual Opus+Codex adversarial review gate (Codex found confirmed P1s on 3 of 4 PRs after Opus passed them). 1650 tests, requires pylxpweb>=0.9.36b20 (HYBRID #282 gating + Fast mode are inert on older versions).
- **v3.4.0-beta.14** — Operating State sensor + >4-battery and HYBRID-flicker fixes (#262, #258/#170, #261, #256, #251): new friendly **Operating State** enum sensor + **Off-Grid** binary sensor decoded from `status_code` (Table 9, all modes, #262); >4 batteries now accumulate by serial ignoring unreliable reg 96, with a hybrid cloud-fallback for non-rotating firmware (#258/#170); HYBRID battery-bank + fault/warning sensors stop flickering unknown/unavailable on transient local hiccups (#261); offline inverter shows `Status=offline` instead of blacking out all entities (#256); Quick Charge restored-Duration no longer leaks into the cloud start (#251). The refuted "dedicated 5th slot" read was reverted — there is no readable 5th slot (#170). Requires pylxpweb>=0.9.36b15 (serial-keyed accumulation + bms_data-drop cache preservation).
- **v3.4.0-beta.13** — Quick Charge Duration faithfully mirrors HOLD 234 (#251, LXP-LB/@ivanfmartinez): LOCAL/HYBRID `Quick Charge Duration` number shows the live HOLD 234 register (idle+active) not a retained preference (firmware governs the value); set while charging→writes reg 234, set while idle→ServiceValidationError (firmware rejects idle writes); preference is now CLOUD-only (start minute). `Quick Charge Remaining` sensor now reports SECONDS (INPUT 210 resolution, HOLD 234 fallback; CLOUD=API). HOLD 234 number (writable min) + INPUT 210 sensor (read-only sec) INTENTIONALLY two separate entities (one per register). pylxpweb 0.9.36b12 (QuickChargeStatus.quickChargeMinute = raw HOLD 234). Block-size/poll-speed = separate enhancement #254. 1364 tests, pylxpweb>=0.9.36b12
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
| Charge Last | 110, bit 4 | Bit field |
| PV Charge Power | 74 | 100 W units (reg 64 is the legacy percent command; the entity reads/writes 74) |
| Discharge Power | 65 | 0-100% |
| AC Charge Power | 66 | 0-100% |
| AC Charge SOC Limit | 67 | 0-100% (grid-tied families only; removed on EG4_OFFGRID, #331/#332) |
| AC Charge Start / End Battery SOC | 160 / 161 | 0-100% (EG4_OFFGRID family only, #332) |
| Charge Current | 101 | Amps |
| Discharge Current | 102 | Amps |
| On-Grid SOC Cutoff | 105 | 10-90% |
| Off-Grid SOC Cutoff | 125 | 0-100% |
| Battery Charge / Discharge Control | 179, bit 9 / bit 10 | Bit field (0=SOC, 1=Voltage; #48) |
| System Charge Voltage Limit | 228 | Decivolts |
| On-Grid / Off-Grid Cut-Off Voltage | 169 / 100 | Decivolts |
| AC Charge Start / End Voltage | 158 / 159 | Decivolts |
| Stop Discharge Voltage | 202 | Decivolts |
| Grid Sell Back | 21, bit 15 | Bit field (#135) |
| Export PV Only | 179, bit 3 | Bit field (#135) |
| Grid Sell Back Power | 103 | 100 W units, kW cap (#135) |
| Fast Zero Export | 110, bit 1 | Bit field (#274) |
| Share Battery | 110, bit 3 | Bit field (#306) |
| Start Discharge Power Threshold | 116 | Whole watts (#272) |
| Start Charge Power Threshold | 117 | Signed watts, LOCAL/HYBRID only (#272) |
| Grid Peak Shaving Power | 206 | 0.1 kW units (#328) |
| Forced Discharge Power / SOC Limit | 82 / 83 | kW / % (grid-tied only, #207) |
| Schedule time windows | 68-73 (AC Charge), 76-81 (Forced Charge), 84-89 (Forced Discharge), 152-157 (AC First), 209-212 (Peak Shaving), 256-259 (Generator), 269-274 (Off-Grid) | Packed hour (low byte) + minute (high byte); #277/#295/#312 |
