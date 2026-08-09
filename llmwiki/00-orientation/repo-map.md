---
canonical-for:
  - "Where code and documentation actually live in this repo"
  - "Path traps: _config_flow/, const/ package, the two firmware RE trees"
sources:
  - git ls-files at 9f6d6e2
  - pylxpweb git ls-tree at 204b95d
  - PR #557 (documentation-defect corrections)
  - issue #549
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-08
see-also:
  - what-this-project-is.md
  - ../60-history/superseded-claims.md
---

# Repo map

Unless a row says otherwise, everything below is `verified-against-code`: repo paths came
from `git ls-files` at `eg4_web_monitor@9f6d6e2` and symbols from the files themselves,
and the pylxpweb layout under "Outside this repo" was checked at `pylxpweb@204b95d`.
Rows that name a weaker grade mean it — see "Outside this repo", where two of the three
sources cannot be pinned at all.

**Several widely-copied paths in the older docs are wrong.** Read the traps section
before trusting any path you find in `CLAUDE.md`, `docs/ARCHITECTURE.md`, or a sprint
command file.

## Path traps

| Wrong (still in older docs) | Correct | Consequence |
|---|---|---|
| `config_flow/` (package) | `_config_flow/` (package) + `config_flow.py` (thin re-export) | An agent creates or edits the wrong directory. Classed *breaks-agent* in the docs audit. |
| `const.py` | `const/` (package) | The file does not exist. `SensorConfig` is in `const/sensors/types.py`. A CI step in `.github/workflows/quality-validation.yml` still compiles the nonexistent path (tracked as issue #549). |
| `async_step_reconfigure_plant()` | No such step has ever existed. `async_step_reconfigure` is the entry point; the station step is `async_step_reconfigure_cloud_station` | An agent implements against, or tests for, a method that is not there. `verified-against-code`: `_config_flow/__init__.py` defines fourteen `async_step_reconfigure*` methods and this is not one of them. **`tests/validate_gold_tier.py` → `validate_reconfiguration()` still greps for it and, not finding it, prints "may be optional" and passes** — which is why the name survived every green CI run that was supposed to catch it |
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
| `docs/reference/firmware/re/` | 10 | Duplicate of the tree below; both tombstoned |
| `docs/reference/firmware_re/` | 10, identical filenames | Duplicate of the tree above; both tombstoned |

Two directories, one set of artefacts: the filename sets are identical and nine of the
ten files are byte-identical — `verified-against-code` at 9f6d6e2. **Both summaries carry
the invalidity banner as of PR #557**; that fact and the banner's wording are owned by
[superseded-claims S4](../60-history/superseded-claims.md), which also records why the
artefacts are invalid. Neither tree is authoritative firmware evidence. The current worked
firmware analyses are `docs/reference/firmware/FIRMWARE_ACQUISITION.md`,
`OFFGRID_GENERATOR_REGISTERS.md`, `OFFGRID_EPS_REGISTERS.md`, `HYBRID_EPS_REGISTERS.md`.

## Outside this repo

| Thing | Where | Note |
|---|---|---|
| `pylxpweb` source | `github.com/joyfulhouse/pylxpweb`, normally cloned as a sibling checkout | Register decode and transports live here: `src/pylxpweb/` carries `transports/`, `devices/`, `registers/`, `constants/`, `client.py`. `verified-against-code` at `pylxpweb@204b95d`. Owned by `20-pylxpweb/`. |
| Dev container + mode configs | An **unversioned** working directory on the maintainer's machine, beside the integration checkout: a `docker-compose.yaml`, per-mode `config*/` directories, and `scripts/eg4-switch-mode.sh` | Four modes: `cloud`, `local`, `hybrid`, `local-nomidbox`. **`asserted-unverified`** — sourced from an unversioned local working directory; it is not a git repository, so no durable revision exists to pin and the claim cannot be code-verified by anyone else. The knowledge is still correct and useful; only its provenance is unauditable. Owned by `50-operations/dev-environment.md`. |
| Maintainer memory corpus | A per-project `memory/` directory outside the repo, under the maintainer's local agent state | Not in the repo, not guaranteed to exist, and not pinnable. Much of `60-history/` was distilled from it; those rows are graded `asserted-unverified` and cite the `memory/*.md` filename. |

**Why two of these three rows are not code-verified.** The wiki grades a claim
`verified-against-code` only against a revision a future reader can check out. A sibling
git repo has one, so pylxpweb is pinned above. A local working directory and a local agent
state directory do not, so nothing sourced from them can hold that grade no matter how
reliably true it is. Downgrading them is not a judgement about accuracy — it records that
a substantial part of what we know about the dev environment rests on a source only one
machine can produce.
