# Changelog

All notable changes to the EG4 Web Monitor integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[3.1.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.1.0
[3.0.0]: https://github.com/joyfulhouse/eg4_web_monitor/releases/tag/v3.0.0
