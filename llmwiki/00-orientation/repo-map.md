---
canonical-for:
  - "Where code and documentation actually live in this repo"
  - "Path traps: _config_flow/, const/ package, the two firmware RE trees"
sources:
  - git ls-files at 9f6d6e2
  - PR #557 (documentation-defect corrections)
  - issue #549
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - what-this-project-is.md
  - ../60-history/superseded-claims.md
---

# Repo map

Everything below is `verified-against-code` at `9f6d6e2` unless a row says otherwise:
paths came from `git ls-files`, symbols from the files themselves.

**Several widely-copied paths in the older docs are wrong.** Read the traps section
before trusting any path you find in `CLAUDE.md`, `docs/ARCHITECTURE.md`, or a sprint
command file.

## Path traps

| Wrong (still in older docs) | Correct | Consequence |
|---|---|---|
| `config_flow/` (package) | `_config_flow/` (package) + `config_flow.py` (thin re-export) | An agent creates or edits the wrong directory. Classed *breaks-agent* in the docs audit. |
| `const.py` | `const/` (package) | The file does not exist. `SensorConfig` is in `const/sensors/types.py`. A CI step in `.github/workflows/quality-validation.yml` still compiles the nonexistent path (tracked as issue #549). |
| `async_step_reconfigure_plant()` | No such step. `async_step_reconfigure` exists; the station step is `async_step_reconfigure_cloud_station` | Named in `CLAUDE.md`; not present in `_config_flow/`. `asserted-unverified` (PR #557, which corrects it against `_config_flow/__init__.py`) |
| Coordinator mixin list without HTTP/Local | `HTTPUpdateMixin` and `LocalTransportMixin` are the **first two** bases | See the coordinator table below |

An **empty untracked `config_flow/` directory** may exist in a working copy and is a
known hazard — it looks like the package and is not. `asserted-unverified`
(PR #557; not present in this worktree at 9f6d6e2).

## Top level

| Path | Contents |
|---|---|
| `custom_components/eg4_web_monitor/` | The integration. See below. |
| `tests/` | Test suite (67 tracked `.py` files, plus `conftest.py`, `mypy.ini`, `requirements-test.txt`, `.coveragerc`, and three `manual_*.py.skip` scripts) |
| `docs/` | Contributor and user documentation. See below. |
| `scripts/` | 31 tracked files: firmware download/extraction, Ghidra drivers, register probes, capture and validation utilities |
| `examples/` | `automations/`, `dashboards/` |
| `.github/` | Workflows, issue templates, `CODEOWNERS` (`@btli`), `WORKFLOWS.md` |
| `.claude/` | Agent commands (`commands/`) and local skill copies |
| `.beads/` | Beads work-tracking database and config |
| Root files | `CLAUDE.md`, `AGENTS.md`, `README.md`, `INSTALL.md`, `CHANGELOG.md`, `LICENSE`, `hacs.json`, `pytest.ini`, `prek.toml` (pre-commit config — note the filename), `.gitattributes`, `.gitignore` |

There is **no `pyproject.toml`** and no top-level `utils/` package in this repo.

## `custom_components/eg4_web_monitor/`

### Entry, coordinator, transport

| File | Role |
|---|---|
| `__init__.py` | Setup/unload, platform forwarding, registry cleanup helpers (e.g. `_async_cleanup_duplicate_runtime_data_entities`) |
| `coordinator.py` | `EG4DataUpdateCoordinator` — composes the mixins (bases in order below) |
| `coordinator_http.py` | Cloud fetch/processing; battery carry-forward (`_apply_battery_carry_forward`) |
| `coordinator_local.py` | Local transport fetch/processing |
| `coordinator_mixins.py` | The behavioural mixins; `_TRANSPORT_OVERLAY`; `_breakered_cloud_call` |
| `coordinator_mappings.py` | Property→sensor mapping tables; static local data construction |
| `transport_serialization.py` | Transport payload (de)serialisation |
| `cloud_session.py`, `cloud_requests.py` | Portal session and request plumbing |

Coordinator bases, in MRO order (`coordinator.py` → `class EG4DataUpdateCoordinator`):
`HTTPUpdateMixin`, `LocalTransportMixin`, `DeviceProcessingMixin`, `DeviceInfoMixin`,
`ParameterManagementMixin`, `DSTSyncMixin`, `BackgroundTaskMixin`,
`FirmwareUpdateMixin`, `DataUpdateCoordinator[dict[str, Any]]`.

### Entities and platforms

| File | Role |
|---|---|
| `base_entity.py` | Base classes and the unique-ID emission sites; `_guard_total_increasing` |
| `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`, `select.py`, `time.py`, `button.py`, `update.py` | HA platforms |
| `control_discovery.py` | Which controls exist for a device |
| `utils.py` | Shared helpers; `CONTROL_CAPABLE_FAMILIES`, `is_supported_control_model` |
| `battery_migration.py`, `device_removal.py` | Registry migration and device removal |
| `diagnostics.py` | HA diagnostics platform (with redaction) |
| `history_import.py` | Historical statistics import |
| `services.py` + `services.yaml` | Services |
| `strings.json` + `translations/` | i18n |
| `manifest.json` | **Source of truth** for version and dependency pins |
| `py.typed` | Typing marker |

Unique-ID and entity-ID forms are owned by
[`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md).
They are deliberately **not** reproduced here: duplicating that exact table across
documents is what produced the fictional format recorded in
[superseded-claims](../60-history/superseded-claims.md), and it would be indefensible to
triplicate it in the cure.

### `_config_flow/`

`config_flow.py` is a thin re-export that exists only to satisfy hassfest's requirement
that `config_flow.py` be a file; its own docstring says so. The implementation lives in
the `_config_flow/` package, whose module-by-module breakdown is owned by
[`10-integration/config-flow.md`](../10-integration/config-flow.md).

### `const/`

| File | Contents |
|---|---|
| `const/__init__.py` | Re-exports |
| `const/brand.py` | Brand config incl. `default_base_url` |
| `const/config_keys.py` | Config/option keys and defaults, incl. `CONNECTION_TYPE_*` and the polling-interval defaults (**the source of truth for intervals — do not restate them elsewhere**) |
| `const/device_types.py` | Device type codes |
| `const/modbus.py` | Modbus register/bit constants |
| `const/limits.py` | Value limits |
| `const/operating_state.py`, `const/working_modes.py` | Enum tables |
| `const/diagnostics.py` | Diagnostics constants |
| `const/sensors/` | `types.py` (`SensorConfig` TypedDict), `inverter.py`, `station.py`, `mappings.py`, `__init__.py` |

## `docs/`

| Path | What it is |
|---|---|
| `docs/DATA_MAPPING.md` | The large mapping reference (registers, cloud fields, computed keys, mode differences, entity counts). Only §2–§5 are register content; §6 and §9–§15 are integration-side and currently have no wiki owner. |
| `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/DEVELOPMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/README.md` | Contributor/user docs |
| `docs/BATTERY_CURRENT_CONTROL.md` | Feature guide (its entity-ID examples are known-wrong; see the audit) |
| `docs/PLANT_API_DOCUMENTATION.md` | Plant/DST API notes, predates `docs/api/` |
| `docs/api/` | OpenAPI spec for the portal |
| `docs/audits/` | Analytical audits, incl. the 2026-08-02 register/race/performance audit |
| `docs/plans/`, `docs/claude/` | Design plans and agent-session artefacts (largely historical; several entries are explicitly superseded) |
| `docs/reference/` | `MODBUS_DOCS.md`, `SCALING_VALIDATION.md`, `FIRMWARE_*.md`, and the two firmware RE trees below |

### The two firmware RE trees

| Path | Tracked files at 9f6d6e2 | State |
|---|---|---|
| `docs/reference/firmware/re/` | 10 | Carries an "⛔ These artifacts are INVALID — do not cite them (2026-08-08)" banner in `00_SUMMARY.md` |
| `docs/reference/firmware_re/` | 10, identical filenames | `00_SUMMARY.md` has **no** banner — a stale duplicate |

`verified-against-code`: filename sets are identical and the only content difference
found is the banner block in `00_SUMMARY.md`. Neither tree's generated artefacts are
authoritative firmware evidence — see
[superseded-claims](../60-history/superseded-claims.md). The current worked firmware
analyses are `docs/reference/firmware/FIRMWARE_ACQUISITION.md`,
`OFFGRID_GENERATOR_REGISTERS.md`, `OFFGRID_EPS_REGISTERS.md`, `HYBRID_EPS_REGISTERS.md`.

## Outside this repo

| Thing | Location | Note |
|---|---|---|
| `pylxpweb` source | `/Users/bryanli/Projects/joyfulhouse/python/pylxpweb` | Sibling repo; register decode and transports live here |
| Dev container + mode configs | `/Users/bryanli/Projects/joyfulhouse/homeassistant-dev/` (`docker-compose.yaml`, `config*/`, `scripts/eg4-switch-mode.sh`) | Four modes: `cloud`, `local`, `hybrid`, `local-nomidbox` — `verified-against-code` (`eg4-switch-mode.sh`). Owned by `50-operations/dev-environment.md`. |
| Maintainer memory corpus | `~/.claude/projects/…-eg4-web-monitor/memory/` | Not in the repo, not guaranteed to exist. Much of `60-history/` was distilled from it. |
