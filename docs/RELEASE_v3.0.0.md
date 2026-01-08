# EG4 Web Monitor v3.0.0 Release Notes

**Release Date:** January 8, 2026
**GitHub Release:** https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.0.0

---

## Overview

This is a **major release** with significant architectural changes, new features, and bug fixes. After 17 release candidates and extensive community testing, v3.0.0 brings improved reliability, better device support, and a foundation for future enhancements.

---

## Breaking Changes

### Entity ID Format Changes

Entity naming conventions have been updated for consistency. **Existing automations, scripts, and dashboards may need to be updated.**

| Old Format | New Format |
|------------|------------|
| `sensor.eg4_18kpv_*_power` | `sensor.eg4_18kpv_*_ac_power` |
| `sensor.eg4_*_soc` | `sensor.eg4_*_state_of_charge` |
| `sensor.eg4_*_voltage` | `sensor.eg4_*_ac_voltage` |

**Common Changes:**
- Sensor keys are now more explicit (e.g., `power` → `ac_power`, `soc` → `state_of_charge`)
- Battery sensors consistently use `battery_{battery_key}` format
- GridBOSS sensors use `eg4_gridboss_{serial}` prefix

### Entity Renaming Limitation

When renaming the integration in Home Assistant, some entities (particularly device-level entities) may not automatically update their friendly names. This is a known Home Assistant limitation.

**Workaround:** Delete and re-add the integration after renaming.

### Sensor Availability

Some sensors that were previously always available may now show as "unavailable" if the underlying device doesn't support them. This is intentional—the integration now uses feature detection to only create sensors that the device actually supports.

---

## New Features

### Multi-Brand Support Architecture

The integration now supports a brand configuration system for future expansion:

| Brand | Domain | Default Base URL |
|-------|--------|------------------|
| **EG4 Electronics** (default) | `eg4_web_monitor` | `monitor.eg4electronics.com` |
| **LuxpowerTek** | `lxp_web_monitor` | `eu.luxpowertek.com` |
| **Fortress Power** | `fortress_web_monitor` | `envy.fortresspower.io` |

### New Entities

#### Binary Sensors
- **Dongle Connectivity** (`binary_sensor.eg4_*_dongle_connectivity`)
  - Shows whether the inverter's communication dongle is online
  - Helps identify when inverter data may be stale due to connectivity issues
  - Includes datalog serial number in attributes

#### Switches
- **Off Grid Mode** (`switch.eg4_*_off_grid_mode`)
  - Control Off-Grid/Green Mode on inverters
  - Controls `FUNC_GREEN_EN` parameter (register 110)
  - Distinct from EPS Battery Backup (`FUNC_EPS_EN`)

#### Sensors
- **Battery Status** - Restored sensor that was lost in early refactoring
- **EPS Power L1/L2** - For 12000XP and compatible devices
- **Full 12000XP Support** - All sensors now working for EG4 12000XP inverters

### Inverter Feature Detection

The integration now detects device capabilities and only creates sensors that the device actually supports. This prevents "unavailable" sensors for features your device doesn't have.

### Optimistic Value Context

Number entities now use optimistic updates for immediate UI feedback when changing values, with automatic rollback if the operation fails.

### Library Debug Logging

New configuration option to enable DEBUG logging for the pylxpweb library, showing API requests, responses, and internal library operations for troubleshooting.

---

## Bug Fixes

| Issue | Description |
|-------|-------------|
| #66 | Quick Charge switch now shows correct state (was always showing OFF) |
| #67 | Working mode switches properly refresh parameters after actions |
| #50, #55 | Reauthentication flow fixed - resolved password request loops |
| #70 | Session authorization expiration handling improved |
| #46 | Number entity values no longer "bounce back" after parameter changes |
| #60, #62 | Battery status sensor restored after refactoring loss |
| #63, #64 | Diagnostic logging added for missing sensor troubleshooting |
| #72 | GridBOSS auto-detection improved for unconfigured parallel groups |
| #49 | Full sensor support for 12000XP and single inverter setups |

### Additional Fixes
- Resolved all mypy strict typing errors
- Fixed DongleStatusMixin type errors
- Comprehensive bug fixes and performance optimizations

---

## Dependencies

| Package | Version | Notes |
|---------|---------|-------|
| pylxpweb | >= 0.4.4 | Required for GridBOSS auto-sync and improved re-authentication |

---

## Technical Improvements

### Architecture Refactoring

**Base Entity Classes:**
- `EG4DeviceEntity` - Base for all device entities
- `EG4BatteryEntity` - Base for individual battery entities
- `EG4BaseSensor` - Base for device sensors with monotonic value support
- `EG4BaseBatterySensor` - Base for individual battery sensors
- `EG4BaseSwitch` - Base for all switch entities with optimistic state management

**Coordinator Mixins:**
- `DeviceProcessingMixin` - Device data processing and property mapping
- `DeviceInfoMixin` - Device info retrieval for all device types
- `ParameterManagementMixin` - Parameter refresh operations
- `DSTSyncMixin` - Daylight saving time synchronization
- `BackgroundTaskMixin` - Background task lifecycle management
- `FirmwareUpdateMixin` - Firmware update info extraction

### Code Quality

- **Platinum Quality Scale** - Meeting all 36 Home Assistant quality scale requirements
- **Strict Typing** - Full mypy strict mode compliance throughout codebase
- **Test Coverage** - 124 automated tests with comprehensive coverage
- **SensorConfig TypedDict** - Type-safe sensor configuration

---

## Known Issues

1. **Entity Renaming** - When renaming the integration, some entities may not auto-update their friendly names (Home Assistant limitation)
2. **Historic Data** - Historic data pull from the monitoring portal is not yet supported (#73)

---

## Upgrade Instructions

### From v2.x via HACS

1. **Back up your automations** that reference EG4 entities
2. Go to HACS → Integrations → EG4 Web Monitor
3. Click Update
4. Restart Home Assistant
5. **Check your automations** - entity IDs may have changed
6. Update any broken entity references

### From versions prior to v2.2.1

If you installed a version **before v2.2.1**, you may need to re-add this repository to HACS due to the repository restructuring:

1. In HACS, remove the EG4 Web Monitor integration
2. Click the three dots menu (⋮) in HACS
3. Select "Custom repositories"
4. Add: `https://github.com/joyfulhouse/eg4_web_monitor`
5. Category: Integration
6. Click "Add"
7. Install EG4 Web Monitor from HACS
8. Restart Home Assistant

Your configuration will be preserved during this process.

---

## What's Next

**v3.1.0** is in development with **local Modbus TCP support**:
- Direct communication with your inverter without cloud dependency
- Three connection modes: Cloud API, Local Modbus, Hybrid
- Currently in beta testing (v3.1.0-beta.1)

---

## Full Changelog

### Features
- feat: Add multi-brand support with BrandConfig system
- feat: Add dongle connectivity binary sensor (#65)
- feat: Add Off Grid Mode switch (#57, #59)
- feat: Add inverter feature detection for device-specific sensors (#58)
- feat: Add missing sensors for 12000XP and single inverter support (#49)

### Bug Fixes
- fix: Quick Charge switch always showing OFF (#66)
- fix: Working mode switches now refresh parameters after actions (#67)
- fix: Resolve reauth flow and battery backup switch conflicts (#50, #55)
- fix: Resolve number entity value bouncing after parameter changes (#46)
- fix: Restore battery_status sensor lost in v3.0.0 refactoring (#60, #62)
- fix: Add diagnostic logging for missing sensor issues (#63, #64)
- fix: Require pylxpweb>=0.4.2 for 12000XP compatibility (#63)
- fix: Comprehensive bug fixes and performance optimizations
- fix: Resolve mypy strict typing errors

### Documentation
- docs: Update README for HACS default repository status (#45)
- docs: Update documentation and fix manual installation (#69)

### Refactoring
- refactor: Add optimistic_value_context for number entities (#46)
- refactor: Base entity classes and coordinator mixins
- refactor: Replace hardcoded brand references with constants

---

## Community Forum Post

The following is a draft for the Home Assistant Community Forum announcement:

---

### Forum Post Draft

```markdown
## v3.0.0 Released - Major Architecture Refactor

Hey everyone! After extensive testing through 17 release candidates, **v3.0.0 is now officially released!** This is a major update with significant improvements, new features, and some breaking changes to be aware of.

### Breaking Changes - Please Read First

**Entity IDs have been updated for consistency.** If you have automations, scripts, or dashboards using EG4 entities, you may need to update them after upgrading.

| Old Format | New Format |
|------------|------------|
| `sensor.eg4_18kpv_*_power` | `sensor.eg4_18kpv_*_ac_power` |
| `sensor.eg4_*_soc` | `sensor.eg4_*_state_of_charge` |

Sensor keys are now more explicit (e.g., `power` → `ac_power`, `soc` → `state_of_charge`). **Back up your automations before upgrading!**

---

### What's New

**New Entities:**
- Dongle Connectivity binary sensor - Know when your inverter's communication dongle goes offline
- Off Grid Mode switch - Control Off-Grid/Green Mode directly from Home Assistant
- Battery Status sensor restored (was accidentally removed in early RCs)
- Full 12000XP support - All sensors now working for EG4 12000XP owners

**Inverter Feature Detection:**
The integration now detects what your specific inverter supports and only creates relevant sensors. No more "unavailable" sensors for features your device doesn't have!

**Multi-Brand Architecture:**
Under the hood, we've built support for multiple brands (LuxpowerTek, Fortress Power) using the same codebase. This sets us up for future expansion.

---

### Bug Fixes

- Quick Charge switch now shows correct state (#66)
- Working mode switches properly refresh after changes (#67)
- Reauthentication flow fixed - no more password loops (#50, #70)
- Number entity values no longer "bounce back" after changes (#46)
- GridBOSS auto-detection improved (#72)

---

### Upgrading

**From HACS:**
1. Go to HACS → Integrations → EG4 Web Monitor
2. Click Update
3. Restart Home Assistant
4. Check your automations for any broken entity references

**If you're on a version before v2.2.1**, you may need to re-add the repository to HACS due to the restructuring that happened back then. See the GitHub release notes for details.

---

### What's Next

We're working on **v3.1.0** which will add **local Modbus TCP support** - direct communication with your inverter without going through the cloud! This is currently in beta testing for those with Waveshare RS485-to-Ethernet adapters.

---

### Full Release Notes

For the complete changelog and detailed documentation:
https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.0.0

As always, if you run into issues, please open a GitHub issue with your logs. Thanks to everyone who tested the release candidates and reported bugs!
```

---

## Acknowledgments

Thanks to all community members who tested the release candidates and reported issues:
- Contributors who reported bugs (#49, #50, #55, #57, #60, #63, #65, #66, #67, #70, #72)
- Everyone who provided feedback during the RC testing period
