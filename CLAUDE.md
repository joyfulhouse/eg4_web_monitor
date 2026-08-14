# EG4 Web Monitor Home Assistant Integration

Home Assistant custom component for EG4 devices (inverters, GridBOSS, batteries)
over local Modbus TCP, WiFi dongle, serial RS485, cloud API, or hybrid. One config
entry per station/plant. Protocol and transport logic live in
[pylxpweb](https://github.com/joyfulhouse/pylxpweb); this repo is the HA wiring.

## Why this file is short

Release notes and the register map used to be duplicated inline here. Both churn
continuously, so both rotted — a 2026-08 audit traced 39 verified documentation
defects to exactly that duplication. **Continuous-churn content lives in exactly
one place and this file points at it.** Do not paste version numbers, release
narratives, or register tables back in.

| Churning content | Single source of truth |
|---|---|
| Version + `pylxpweb` pin | `custom_components/eg4_web_monitor/manifest.json` |
| Release history | `CHANGELOG.md` |
| Register map / control registers | `docs/DATA_MAPPING.md`, `llmwiki/40-hardware/registers.md` |
| Field → sensor mapping, mode differences | `docs/DATA_MAPPING.md` |
| Polling/interval defaults | `const/config_keys.py` |
| Portal API endpoints + schemas | `docs/api/` (OpenAPI 3.1), `docs/PLANT_API_DOCUMENTATION.md` |
| User-facing options catalog | `docs/CONFIGURATION.md` |
| Architecture narrative | `docs/ARCHITECTURE.md`, `llmwiki/10-integration/` |
| Troubleshooting | `docs/TROUBLESHOOTING.md` |

Never state the current version from memory — read `manifest.json`.

## Maintaining `llmwiki/`

`llmwiki/` is the deep knowledge base — numbered chapters that agents write and
keep current. **To find a page, start at `llmwiki/index.md`** — the catalog of
every page with a one-line summary and the facts it owns, so you never scan the
tree. **To grade a claim, go to `llmwiki/README.md`**: it owns the rules the pages
follow — canonical-source policy, evidence-grade legend, freshness discipline,
cold-start reading order — not a list of what exists. `_conventions.md` holds the
page template and front-matter schema; `log.md` is the append-only history.

Three layers. **Raw sources** — this repo's code, `pylxpweb` at its pinned commit,
`docs/`, `memory/*.md`, issues — are immutable here; the wiki reads them.
**The wiki** is agent-owned. **The schema** is this file and `AGENTS.md`: how to
maintain, never what is true.

> **The wiki follows the code. The code is never changed to make a wiki claim
> true.** A documentation task that turns out to need a code change stops and files
> an issue — that rule is why #549, #550 and #558 exist rather than having been
> quietly "fixed" inside a docs PR.

**Ingest.** Read the primary source — not a summary of it. Find the owner via
`index.md` → the page whose `canonical-for:` covers the fact, and update **that
page only**: grade the claim, cite a durable artifact, refresh
`verified-against:` / `last-verified:`. Then update whatever the new knowledge
*falsifies* — a promotion or downgrade is never a local edit, so grep the register,
symbol, or path across `llmwiki/` before finishing. Then **append an entry to
`llmwiki/log.md`**, keeping the heading prefix exact —
`## [YYYY-MM-DD] <op> | <subject>` — because
`grep '^## \[' llmwiki/log.md | tail -5` is how the next agent reads recent
history; that file's header owns the `<op>` vocabulary and the append-only rules.
The commit message is a durable record too; the log carries reasoning across
commits, the commit message explains one diff.

**Query.** `index.md` first, then the owner page. Answer with the page and its
`verified-against:` pin, and state the grade when it changes the answer —
"portal-correlated, not proven" is a different answer from "proven".

**Lint.** Contradictions between pages (unresolved ones belong in
`60-history/open-contradictions.md`, never resolved by assertion); pins that have
moved; `verified-against-code` grades whose cited symbol no longer exists at the
pin; orphan pages and unowned facts; and — the expensive one here — **completeness
claims** (`every`, `only these`, `all controls`): ask what *derives* the set.

**Evidence discipline.** The grade vocabulary is closed and defined **only** in
`llmwiki/README.md`; never coin a grade, weaken one locally, or carve an exception —
that loophole regrew five times during construction, each time with locally
reasonable wording. Never grade `hardware-proven` from source code, a README, or a
`# verified` comment: in this project's register tables `# verified` has meant "the
names matched", which is what caused #476. **A claim whose citation does not support
it is a defect even when the claim is true** — confirm the symbol exists at the pin
before citing it. Prefer a derivation plus its blind spots over an enumeration.

**Rules paid for in defects.**

- **Verify the frame before the contents.** An exhaustive count over an incomplete
  frame reads as rigour and is not — three consecutive review rounds each found a
  write mechanism the previous round's frame excluded.
- **Resolve the runtime class, not the base class.** `HybridInverter._set_schedule`
  (`pylxpweb/devices/inverters/hybrid.py`) and `_set_schedule` on the control
  endpoint (`pylxpweb/endpoints/control.py`) share a name and route differently.
- **A completeness claim is load-bearing** — before writing "every", ask what
  derives the set.
- **A readback proves storage and transport, never semantics.** A wrong-but-writable
  register is firmware-ACKed and reads back what you wrote, so no readback separates
  "the control worked" from "something else silently changed" (#476, #558).
- **Re-verify a finding against the primary source before acting on it.** Tooling
  and reviews here have produced confident results that did not reproduce; a
  "correction" taken from a secondary source would have published a false claim. A
  green check can be wrong.
- **Before stating what another document contains, check whether it is being edited
  in the same change set.** Such a claim is verified against a branch, not against
  what will merge. This build shipped that defect twice — three pages asserted a
  banner state another PR falsified in the same train, and this schema said
  `llmwiki/` had no `index.md` and no `log.md` twenty minutes before a parallel
  branch created both. Prefer describing what a document *owns* over what it lists.

## Source map (where to edit)

Under `custom_components/eg4_web_monitor/`:

- `config_flow.py` — thin re-export shim that exists only because hassfest requires
  a file of that name. It re-exports `EG4ConfigFlow` and `EG4OptionsFlow` from
  `_config_flow/`, and nothing else. **Write code in
  `_config_flow/`.** An empty `config_flow/` directory appearing locally is not
  the package; ignore it.
- `_config_flow/` — `__init__.py` (unified `EG4ConfigFlow`), `discovery.py`,
  `schemas.py`, `helpers.py`, `options.py`, `serial_ports.py`.
- `const/` — a **package, not a `const.py` module**: `brand.py` (`ENTITY_PREFIX`),
  `config_keys.py` (`DEFAULT_*` intervals), `modbus.py`, `sensors/types.py`
  (`SensorConfig` TypedDict), `device_types.py`, `limits.py`, `diagnostics.py`,
  `operating_state.py`, `working_modes.py`.
- `coordinator.py` (composes the mixins), `coordinator_http.py`,
  `coordinator_local.py`, `coordinator_mixins.py`, `coordinator_mappings.py`.
- `base_entity.py` — shared entity base classes.
- Platforms: `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`,
  `select.py`, `button.py`, `time.py`, `update.py`, plus `services.py`.

**Config flow shape.** Connection type is *derived*, never chosen: cloud only →
`http`, local only → `local`, both → `hybrid`. Local device types are Modbus TCP,
WiFi dongle, **and serial RS485**. Reconfigure enters at `async_step_reconfigure`
→ `async_step_reconfigure_menu`, then `reconfigure_cloud_{update,add,station,remove}`
/ `reconfigure_devices` / `reconfigure_add_{modbus,dongle,serial}`. There is no
`async_step_reconfigure_plant`. Grep `async def async_step_` in
`_config_flow/__init__.py` rather than trusting any doc.

**Coordinator mixins.** `EG4DataUpdateCoordinator` composes **eight** mixins, in
MRO order: `HTTPUpdateMixin` (`coordinator_http.py`), `LocalTransportMixin`
(`coordinator_local.py`), then `DeviceProcessingMixin`, `DeviceInfoMixin`,
`ParameterManagementMixin`, `DSTSyncMixin`, `BackgroundTaskMixin`,
`FirmwareUpdateMixin` (all `coordinator_mixins.py`), then
`DataUpdateCoordinator`. The HTTP and local mixins come **first** and win the MRO.

## Entity and unique IDs

**Unique IDs** are set by the integration and are stable: device
`{serial}_{sensor_key}`, battery `{serial}_{battery_key}_{sensor_key}`, bank
`{serial}_battery_bank_{sensor_key}`, station `station_{plant_id}_{sensor_key}`.

**Entity IDs are generated by Home Assistant**, not by this integration — HA
slugifies `{device name}_{entity name}` for entities that set
`_attr_has_entity_name = True`. The `_attr_entity_id` assignments in the codebase
are **inert**: `homeassistant.helpers.entity.Entity.entity_id` is a plain class
attribute, not `_attr_`-backed, so HA ignores them (issue #550;
`llmwiki/10-integration/entities-identity-availability.md` owns the count and its
verification command).

**Scope of that claim.** It describes the ID HA *generates for a newly added
entity*. It does **not** describe what is in any given user's registry. HA freezes
an entity ID once assigned and users can rename entities, so registries predating
a naming change — or carrying manual renames — can hold `eg4_`-prefixed or
otherwise divergent IDs indefinitely. Never assume the generated form is what a
user has; have them read their own registry.

The *shapes* below match a live registry capture of one maintainer system; the
**serials are synthetic** (`1234567890` 18kPV, `SYNTH10005` GridBOSS,
`1234A56789` FlexBOSS21):

```
sensor.18kpv_1234567890_battery_voltage
sensor.battery_bank_1234567890_battery_bank_max_cell_temperature
select.grid_boss_synth10005_smart_port_1_mode
number.flexboss21_1234a56789_battery_charge_current
sensor.parallel_group_a_ac_power
```

Note the FlexBOSS21 line: slugification **lowercases** the serial, so a serial
containing `A` appears as `a` inside the entity ID. Never match entity IDs
case-sensitively against a serial as the portal reports it.

**Adjudicating an entity-ID claim.** Do not reason from `entity_key` constants or
`_attr_entity_id` strings — both have produced wrong "corrections" in this repo.
Use a real registry instead:

- Canonical derivation and its evidence grade:
  `llmwiki/10-integration/entities-identity-availability.md`.
- The prior capture behind the examples above is recorded in
  `memory/queue-cleanup-2026-07-26.md`; it is not re-captured here and is
  `asserted-unverified` for any system but the one it came from.
- To produce a fresh capture, read the target instance's registry directly —
  Developer Tools → States, or `GET /api/states` with a long-lived token — and
  filter for the integration's devices. There is no committed capture in this
  repo to fall back on.

Serials are **10-character alphanumeric**, not numeric-only (`1234567890`,
`1234A56789`). Never assume `\d{10}`.

## Quality gates

Run all of these before committing. `uv` only — never `pip`.

```bash
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
uv run pytest tests/ -x --tb=short
uv run python tests/validate_silver_tier.py
uv run python tests/validate_gold_tier.py
uv run python tests/validate_platinum_tier.py
```

`prek.toml` (not `.pre-commit-config.yaml`) holds the ruff/mypy pre-commit hooks.
Bronze quality-scale requirements are enforced by
`.github/workflows/quality-validation.yml`; there is no Bronze validator script.

Don't cite test counts — they rot. Count them when you need one:
`grep -rhcE '^\s*(async )?def test_' tests/ | paste -sd+ | bc`. The coverage
target and the full gate definitions live in `llmwiki/50-operations/quality-gates.md`,
which is canonical for them. Fixtures come from
`pytest-homeassistant-custom-component`; `enable_custom_integrations` is
auto-enabled in `tests/conftest.py`. Mock mixin methods with instance-level
`patch.object(coordinator, ...)`; config-flow tests patch
`custom_components.eg4_web_monitor._config_flow.LuxpowerClient` — the **package**,
not the shim. `config_flow.py` re-exports only `EG4ConfigFlow` and `EG4OptionsFlow`, so
the name does not exist in that namespace and patching `config_flow.LuxpowerClient`
**raises `AttributeError`** — `mock.patch` resolves the attribute when it starts and
refuses a missing one unless `create=True`. It does not silently no-op.
(`tests/test_config_flow.py:141`, `tests/test_cloud_session_isolation.py:496`.
`MEMORY.md` is stale on this; see `llmwiki/10-integration/config-flow.md`.)
Never disable a linter rule to make a gate pass.

## Coding conventions

- **f-strings** for ordinary formatting; **percent-style `%s` for logging only**
  (lazy evaluation). Never `.format()`.
- New entities inherit from `base_entity.py`: `EG4DeviceEntity`,
  `EG4BatteryEntity`, `EG4StationEntity`, `EG4BaseSensor`,
  `EG4BaseBatterySensor`, `EG4BatteryBankEntity`, `EG4BaseSwitch`. Switches use
  `_execute_switch_action()` / `_get_inverter_or_raise()` and get optimistic
  state for free.
- `TypedDict` for config dicts; `DeviceInfo | None` from device-info methods.
- Use `time.monotonic()`, never `asyncio.get_event_loop().time()`.
  **Throttle gotcha:** `monotonic()` is host uptime on Linux, so `0.0` as the
  "never ran" default in `now - last.get(key, 0.0) < INTERVAL` makes the
  first-ever run look throttled on a freshly booted host (every CI runner) and it
  silently never fires. Use a `None` sentinel. Bit PRs #378 and #380 the same day
  (fix pattern `d66cc92`); regression-test with `monotonic` patched small.
- Prefer capability/family gates over model-name substring matching.
- Fetch once, update all — one API call often carries data for many devices.
- Niche sensors ship `entity_registry_enabled_default=False`.

## Docker development environment

Container `homeassistant-dev`, image `homeassistant/home-assistant:latest`, port
8123. The compose file and mode-switch script live in the **parent** workspace
(`../`), not in this repo. `custom_components/eg4_web_monitor` and
`pylxpweb/src/pylxpweb` are bind-mounted live; restart to pick up import changes:
`docker restart homeassistant-dev && docker logs -f homeassistant-dev`.

`../scripts/eg4-switch-mode.sh <mode>` swaps the mounted HA config directory.
**Four** modes, one at a time (API rate limits, Modbus collisions):

| Mode | Config dir | Purpose |
|---|---|---|
| `cloud` | `./config` | Baseline — all data validated against this |
| `local` | `./config-local` | Local only (Modbus / dongle / serial) |
| `hybrid` | `./config-hybrid` | Local polling + cloud supplemental |
| `local-nomidbox` | `./config-local-nomidbox` | Local without GridBOSS (inverters only) |

Check the current mode with `grep ":/config" docker-compose.yaml | head -1`.
Local must reach at least entity parity with cloud; hybrid is a superset of cloud;
small live-reading deltas are expected from cloud lag.

**Gotchas.** A fresh container layer lacks the `pylxpweb` dist-info, so HA
pip-installs over the bind mount and the integration dies — recreate a minimal
dist-info after every mode switch. `docker restart` has wiped the bind-mounted
`pylxpweb` source; commit first, recover with `git restore src/pylxpweb/`. Prod
runs HYBRID against the same gateway, so leaving the dev container up degrades
prod to cloud fallback — stop it when not developing.

## Troubleshooting

See `docs/TROUBLESHOOTING.md`. Import errors → `docker logs homeassistant-dev`.
Changes not reflecting → the container needs a restart.
