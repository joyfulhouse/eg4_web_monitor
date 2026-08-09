# Documentation

Documentation for EG4 Web Monitor.

| Document | Description |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the integration is structured and why |
| [CONFIGURATION.md](CONFIGURATION.md) | Connection types, setup, options, and the full entity/control reference |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common problems, FAQ, and debug logging |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Development environment and workflow |

## Reference

Project-specific reference material:

| Document | Description |
|---|---|
| [DATA_MAPPING.md](DATA_MAPPING.md) | Register-to-sensor and API-to-sensor mappings |
| [PLANT_API_DOCUMENTATION.md](PLANT_API_DOCUMENTATION.md) | Plant/station configuration API endpoints |
| [BATTERY_CURRENT_CONTROL.md](BATTERY_CURRENT_CONTROL.md) | Battery charge/discharge current control |
| [reference/MODBUS_DOCS.md](reference/MODBUS_DOCS.md) | Modbus register documentation |
| [reference/SCALING_VALIDATION.md](reference/SCALING_VALIDATION.md) | Sensor scaling validation notes |
| [api/](api/) | OpenAPI 3.1 specification for the EG4 portal API |
| [reference/firmware/](reference/firmware/) | Firmware acquisition method and worked register analyses |

> The `reference/firmware/re/` and `reference/firmware_re/` trees are **invalid
> and superseded** — both rest on OTA-framing and word-order errors. See the
> banner on either `00_SUMMARY.md`, and use
> [reference/firmware/FIRMWARE_ACQUISITION.md](reference/firmware/FIRMWARE_ACQUISITION.md)
> instead.

See also the [automation and dashboard examples](../examples/).

---

> Internal design notes, session logs, release notes, plans, and other process
> artifacts live in [`claude/`](claude/) and are not part of the user-facing
> documentation.
