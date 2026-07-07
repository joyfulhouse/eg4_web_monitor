# Architecture

How EG4 Web Monitor is structured and why.

## Overview

The integration is a Home Assistant custom component that exposes EG4 inverters,
GridBOSS (MID) devices, and batteries as devices and entities. It is built on the
[pylxpweb](https://github.com/joyfulhouse/pylxpweb) Python library, which
provides the cloud API client and the local transport abstraction (Modbus TCP,
WiFi dongle, and serial RS485). A single config entry maps to one station/plant.

## Components

- **Config flow** (`config_flow/`) — a unified `EG4ConfigFlow` with menu-based
  navigation. The connection type (`http` / `local` / `hybrid`) is *derived* from
  the configured data rather than chosen upfront. Submodules cover device
  discovery, voluptuous schema builders, helpers, and the options flow.
- **Coordinator** — a `DataUpdateCoordinator` composed from focused mixins
  (device processing, device info, parameter management, DST sync, background
  tasks, firmware updates). HTTP and local data paths live in dedicated modules,
  with a shared mappings module translating raw data into sensor values.
- **Base entities** (`base_entity.py`) — shared base classes for device,
  battery, station, sensor, switch, and battery-bank entities to eliminate
  duplication.
- **Entity platforms** — `sensor.py`, `binary_sensor.py`, `switch.py`,
  `number.py`, `select.py`, `button.py`, `time.py` (schedule windows), and
  `update.py`, plus service actions in `services.py`.
- **Constants** (`const/`) — typed configuration (e.g. `SensorConfig`),
  `SENSOR_TYPES`, and config keys.

## Device Hierarchy

```
Station / Plant (plantId)
└── Parallel Group (0..n)
    ├── MID Device (GridBOSS) (0..1)
    └── Inverters (1..n)
        └── Batteries (0..n)
```

Standard inverters (FlexBOSS21/18, 18kPV, 12kPV, XP) expose the full sensor set
and create individual battery devices. GridBOSS MID devices expose grid-
management sensors only. Individual batteries expose voltage, current, power,
SoC/SoH, temperature, cycle count, and per-cell metrics.

## Data Flow

- **HTTP (cloud):** the coordinator authenticates against EG4's cloud API
  (2-hour session with auto-reauthentication), fetches station, device, runtime,
  energy, battery, and MID data with concurrent calls, and maps the responses to
  entities. Default polling is 30 seconds.
- **Local:** the coordinator reads holding/input registers over the selected
  transport. Default polling is 5 seconds. The first refresh creates entities
  from config metadata (zero Modbus reads); real values fill in on the next
  refresh.
- **Hybrid:** local transports drive fast sensor updates while the cloud API
  supplies cloud-only features (DST sync) and any transport-exclusive overlays.
  Controls fall back to the cloud when the local link is down. pylxpweb handles
  transport routing.

## Key Design Decisions

- **Auto-derived connection type** keeps onboarding simple: users pick *what* to
  connect, not *which mode* to run.
- **Mixin-based coordinator** separates concerns and keeps each data path
  testable in isolation.
- **Feature detection** means entities are created only for capabilities the
  hardware actually reports, so unused features do not produce "unknown"
  entities.
- **Data-integrity guards** (cross-request validation, canary checks, energy
  monotonicity) protect against corrupt local readings, especially over WiFi
  dongles.
- **Library boundary:** all protocol and transport logic lives in `pylxpweb`;
  the integration focuses on Home Assistant wiring.
