# Project Structure

Two repositories work together: the **HA integration** (this repo) and the **pylxpweb library** (the device/API layer).

## Repository Layout

```
eg4_web_monitor/                          ← This repo (HA integration)
├── custom_components/eg4_web_monitor/    ← Integration source
│   ├── __init__.py                       — Entry point: setup, migration, cleanup
│   ├── coordinator.py                    — Main coordinator class (7 mixins)
│   ├── coordinator_http.py               — Cloud API update logic
│   ├── coordinator_local.py              — Modbus/Dongle update logic
│   ├── coordinator_mixins.py             — Device processing, DST, params, firmware
│   ├── coordinator_mappings.py           — Pure data transform functions
│   ├── base_entity.py                    — 7 base entity classes
│   ├── sensor.py                         — Sensor platform (1000+ entities)
│   ├── switch.py                         — Switch platform (EPS, charge, modes)
│   ├── number.py                         — Number platform (SOC, power limits)
│   ├── select.py                         — Select platform (working modes)
│   ├── button.py                         — Button platform (force refresh)
│   ├── update.py                         — Firmware update platform
│   ├── services.py                       — HA services (refresh, reconcile)
│   ├── config_flow.py                    — Delegates to _config_flow/
│   ├── _config_flow/                     — Config flow package
│   │   ├── __init__.py                   — Unified EG4ConfigFlow (1499 lines)
│   │   ├── discovery.py                  — Auto-discovery (Modbus/Dongle/Serial)
│   │   ├── schemas.py                    — Voluptuous form schemas
│   │   ├── helpers.py                    — Migration, unique IDs, timezone
│   │   └── options.py                    — Runtime options flow
│   ├── const/                            — Constants package
│   │   ├── __init__.py                   — DOMAIN, MANUFACTURER, ENTITY_PREFIX
│   │   ├── config_keys.py               — 30+ configuration keys
│   │   ├── device_types.py              — Inverter family detection
│   │   ├── limits.py                     — Min/max/step for number entities
│   │   ├── working_modes.py             — Register 110 mode mappings
│   │   ├── diagnostics.py               — Diagnostic entity keys
│   │   └── sensors/                      — Sensor definitions
│   │       ├── inverter.py               — SENSOR_TYPES (2000+ definitions)
│   │       ├── station.py                — Station-level sensors
│   │       ├── mappings.py               — Device→sensor field mappings
│   │       └── types.py                  — SensorConfig TypedDict
│   ├── strings.json                      — Translations (English)
│   └── translations/                     — i18n files
├── tests/                                ← 757+ tests
│   ├── conftest.py                       — Shared fixtures
│   ├── test_config_flow.py               — Cloud onboarding (56 tests)
│   ├── test_reconfigure_flow.py          — Reconfigure menu (24 tests)
│   ├── test_coordinator.py               — Coordinator logic (120+ tests)
│   ├── test_coordinator_http.py          — HTTP path (19 tests)
│   ├── test_coordinator_local.py         — Local path (23 tests)
│   ├── test_sensor_entities.py           — Sensor creation (42 tests)
│   ├── test_update_entities.py           — Firmware update (38 tests)
│   ├── test_options_flow.py              — Options flow
│   └── validate_*.py                     — Quality tier validation scripts
├── docs/                                 ← Documentation (see docs/README.md)
├── .claude/                              ← Claude Code config
│   ├── commands/                          — Sprint/triage/fix commands
│   ├── hooks/                             — Safety hooks
│   └── settings.json                      — Hook registration
├── .beads/                               ← Issue tracking (Dolt DB)
│   ├── formulas/                          — mol-sprint, mol-fix-issue
│   └── embeddeddolt/eg4/                  — Issue database
├── CLAUDE.md                             — Project conventions and rules
├── AGENTS.md                             — Agent workflow and beads integration
└── CHANGELOG.md                          — Release history
```

## pylxpweb Library

```
pylxpweb/                                 ← Sibling repo (device/API layer)
├── src/pylxpweb/
│   ├── client.py                         — LuxpowerClient (HTTP + auth + caching)
│   ├── models.py                         — Pydantic data models (API responses)
│   ├── exceptions.py                     — 5 exception types
│   ├── devices/                          — Device hierarchy
│   │   ├── station.py                    — Station (top-level container)
│   │   ├── parallel_group.py             — ParallelGroup (inverter cluster)
│   │   ├── battery_bank.py              — BatteryBank (aggregate)
│   │   ├── battery.py                    — Battery (individual module)
│   │   ├── mid_device.py                — MIDDevice (GridBOSS)
│   │   └── inverters/                    — Inverter hierarchy
│   │       ├── base.py                   — BaseInverter (abstract)
│   │       ├── generic.py                — GenericInverter
│   │       ├── hybrid.py                 — HybridInverter
│   │       ├── _runtime_properties.py   — 80+ runtime properties mixin
│   │       └── _energy_properties.py    — Energy properties mixin
│   ├── transports/                       — Transport implementations
│   │   ├── protocol.py                   — InverterTransport Protocol
│   │   ├── http.py                       — HTTP transport (cloud API)
│   │   ├── modbus.py                     — Modbus TCP transport
│   │   ├── dongle.py                     — WiFi Dongle transport
│   │   ├── hybrid.py                     — Hybrid (local + cloud fallback)
│   │   ├── serial.py                     — Modbus RS485 serial
│   │   └── data.py                       — Data classes (RuntimeData, EnergyData, etc.)
│   ├── endpoints/                        — API endpoint groups
│   │   ├── plants.py                     — Plant/station CRUD
│   │   ├── devices.py                    — Device discovery + runtime data
│   │   ├── control.py                    — Quick charge, parameter writes
│   │   ├── analytics.py                  — Historical data, statistics
│   │   ├── forecasting.py               — Weather-based PV forecasting
│   │   ├── export.py                     — Data export endpoints
│   │   └── firmware.py                   — Firmware version checking
│   ├── constants/                        — Configuration constants
│   │   ├── api.py                        — URL paths, timeouts
│   │   ├── devices.py                    — Device type codes, families
│   │   ├── registers.py                  — Register addresses
│   │   ├── scaling.py                    — ScaleFactor enum + helpers
│   │   └── locations.py                  — Regional API endpoints
│   ├── registers/                        — Modbus register maps (5 families)
│   │   ├── inverter_holding.py           — Holding registers (config)
│   │   ├── inverter_input.py             — Input registers (measurements)
│   │   └── battery.py                    — Battery BMS registers
│   ├── battery_protocols/               — EG4 BMS master/slave protocol
│   ├── scanner/                          — Network device discovery
│   └── cli/                              — CLI tools (collect, modbus-diag)
├── tests/                                ← 1699+ tests
│   ├── unit/ (83 files, 550+ tests)     — Mock API, full coverage
│   ├── integration/ (58 tests)          — Live API tests (require .env)
│   └── unit/*/samples/                  — Real API response fixtures
├── pyproject.toml                        — v0.9.27, Python 3.12+, uv_build
└── CLAUDE.md                             — Library conventions
```

## Data Flow

```
[EG4 Cloud API]                    [Local Network]
      │                                  │
      ▼                                  ▼
LuxpowerClient ←───── pylxpweb ─────→ ModbusTransport / DongleTransport
      │                   │                       │
      ▼                   ▼                       ▼
  Station ──→ ParallelGroup ──→ BaseInverter ──→ BatteryBank ──→ Battery
      │              │               │                │
      └──────────────┴───────────────┴────────────────┘
                           │
                           ▼
              EG4DataUpdateCoordinator (7 mixins)
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
      Sensor (1000+)  Switch/Number   Update
      entities        entities        entities
```

## Connection Modes

| Mode | Data Source | Polling | Use Case |
|------|-----------|---------|----------|
| HTTP (cloud) | EG4 cloud API | 60-600s | Remote monitoring |
| LOCAL (modbus) | Modbus TCP direct | 5-60s | Low-latency local |
| LOCAL (dongle) | WiFi Dongle | 5-60s | Dongle-equipped systems |
| HYBRID | Local primary + cloud supplemental | Mixed | Best of both worlds |

## Cross-Repo Dependency

The integration depends on pylxpweb via `pyproject.toml`:
```
pylxpweb >= 0.9.26
```

During development, pylxpweb is volume-mounted into the Docker container:
```
../python/pylxpweb/src/pylxpweb → /usr/local/lib/python3.13/site-packages/pylxpweb
```

Changes to pylxpweb require a **separate PR + PyPI release** before the integration can pin the new version.
