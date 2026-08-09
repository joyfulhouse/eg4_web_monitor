# Architecture

How EG4 Web Monitor is structured and why.

## Overview

The integration is a Home Assistant custom component that exposes EG4 inverters,
GridBOSS (MID) devices, and batteries as devices and entities. It is built on the
[pylxpweb](https://github.com/joyfulhouse/pylxpweb) Python library, which
provides the cloud API client and the local transport abstraction (Modbus TCP,
WiFi dongle, and serial RS485). A single config entry maps to one station/plant.

## Components

- **Config flow** (`_config_flow/`) — a unified `EG4ConfigFlow` with menu-based
  navigation. The connection type (`http` / `local` / `hybrid`) is *derived* from
  the configured data rather than chosen upfront. Submodules cover device
  discovery, voluptuous schema builders, helpers, serial-port enumeration, and
  the options flow. The top-level `config_flow.py` is a thin re-export that
  exists only to satisfy hassfest's requirement that a file of that name exist;
  the implementation lives in the underscore package.
- **Coordinator** — a `DataUpdateCoordinator` composed from eight focused mixins.
  In MRO order: `HTTPUpdateMixin` (`coordinator_http.py`) and
  `LocalTransportMixin` (`coordinator_local.py`) come first and own the two data
  paths, followed by `DeviceProcessingMixin`, `DeviceInfoMixin`,
  `ParameterManagementMixin`, `DSTSyncMixin`, `BackgroundTaskMixin` and
  `FirmwareUpdateMixin` (all in `coordinator_mixins.py`). A shared
  `coordinator_mappings.py` translates raw data into sensor values.
- **Base entities** (`base_entity.py`) — shared base classes for device,
  battery, station, sensor, switch, and battery-bank entities to eliminate
  duplication.
- **Entity platforms** — `sensor.py`, `binary_sensor.py`, `switch.py`,
  `number.py`, `select.py`, `button.py`, `time.py` (schedule windows), and
  `update.py`, plus service actions in `services.py`.
- **Constants** (`const/`) — a package, not a single `const.py` module. Holds
  typed configuration (`SensorConfig` lives in `const/sensors/types.py`),
  `SENSOR_TYPES`, config keys and polling defaults (`const/config_keys.py`),
  register constants (`const/modbus.py`), and branding (`const/brand.py`).

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

- **HTTP (cloud):** the coordinator authenticates against EG4's cloud API, fetches
  station, device, runtime, energy, battery, and MID data with concurrent calls,
  and maps the responses to entities. Default polling is 120 seconds
  (`DEFAULT_HTTP_POLLING_INTERVAL`, `const/config_keys.py`).

  **Session lifetime is not a portal contract.** The login response carries no
  expiry; pylxpweb stamps `now + 2 hours` locally after every successful login and
  uses that only to decide when to refresh *proactively*. The portal may invalidate
  a session sooner or later. Actual expiry is detected **reactively**, from the API
  returning an HTML login page instead of JSON (surfacing as a
  `ContentTypeError`) or a `401`, either of which triggers one re-authentication
  and a retry. Treat the two hours as a client-side heuristic, never as a
  guaranteed window. Owner: `llmwiki/20-pylxpweb/` (auth/session).
- **Local:** the coordinator reads holding/input registers over the selected
  transport. Polling defaults differ per transport: 5 seconds for Modbus TCP and
  serial (`DEFAULT_MODBUS_UPDATE_INTERVAL`), 30 seconds for the WiFi dongle
  (`DEFAULT_DONGLE_UPDATE_INTERVAL`, whose reads take ~8-10 s). The first refresh
  creates entities from config metadata (zero Modbus reads); real values fill in
  on the next refresh.
- **Hybrid:** local transports drive fast sensor updates while the cloud API adds
  what only it can supply. The two sources are distinct and must not be conflated:

  - **From the local transport:** the fast sensor updates *and* the
    **transport-exclusive overlays** — fields that exist only in register space
    and have no cloud equivalent. These are local-only; the cloud cannot
    supply them, and they go stale or unavailable when the local link drops.
  - **From the cloud API:** cloud-only data with no register backing (DST sync,
    quick-charge status on families that reject the local path, plant-level
    history), plus **fallback** for control writes and parameter reads when the
    local link is down.

  pylxpweb handles transport routing. See
  `llmwiki/10-integration/data-flow-by-mode.md` for the per-field overlay
  behavior and the merge/carry-forward rules.

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
