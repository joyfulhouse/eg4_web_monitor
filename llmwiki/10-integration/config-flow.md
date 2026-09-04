---
canonical-for:
  - the _config_flow package layout and the config_flow.py shim
  - real config-flow step names (onboarding, reauth, reconfigure, options)
  - connection-type derivation
  - Modbus discovery error classification
  - unique-id construction, conflict detection, entry migration
sources:
  - custom_components/eg4_web_monitor/_config_flow/__init__.py
  - custom_components/eg4_web_monitor/_config_flow/helpers.py
  - custom_components/eg4_web_monitor/_config_flow/options.py
  - custom_components/eg4_web_monitor/config_flow.py
  - custom_components/eg4_web_monitor/__init__.py
  - tests/conftest.py
  - tests/test_config_flow.py
  - tests/test_config_flow_scan.py
  - eg4_web_monitor issue #275
  - eg4_web_monitor issue #574
verified-against: c411499
last-verified: 2026-09-04
see-also:
  - architecture.md
  - ../00-orientation/repo-map.md
---

# Config flow

Line numbers pinned to `9f6d6e2`; symbol names are the durable anchor.

## 1. Package layout — it is `_config_flow/`, not `config_flow/`

| Fact | Evidence |
|---|---|
| The implementation package is **`_config_flow/`** (leading underscore) | `verified-against-code` — directory listing |
| **`config_flow.py` is a thin re-export shim** (reproduced in full below). Its only job is to satisfy hassfest's requirement that a file named `config_flow.py` exists. It re-exports `EG4ConfigFlow` and `EG4OptionsFlow` and declares `__all__` | `verified-against-code` — `config_flow.py` |

> **Two paths differing by one underscore, and the wrong one has the conventional name.** This is
> the durable trap; it produces three distinct mistakes, all of which have been made.
>
> | Failure mode | What it looks like | Why the shape causes it |
> |---|---|---|
> | Reading the shim as the implementation | "the config flow is trivial / a dozen lines" | `config_flow.py` is the name Home Assistant convention trains you to open, and hassfest requires it to exist — so the file you reach for first is the one with nothing in it |
> | Writing the package as `config_flow/` | docs, paths and imports that resolve to nothing | The underscore reads as an editorial detail rather than part of the name |
> | Aiming a patch target or a grep at `config_flow.<symbol>` | `AttributeError`, or a CI check that silently matches nothing | Only `EG4ConfigFlow` and `EG4OptionsFlow` transit the shim; every other symbol lives in the package namespace |
>
> `verified-against-code` — both paths exist at `9f6d6e2` (`config_flow.py` file, `_config_flow/`
> package); the shim's complete contents are reproduced below. The third row is worked through
> under **Test patch target**, and the CI note in §5 is the same trap in a workflow.

```python
# config_flow.py — the entire file
from custom_components.eg4_web_monitor._config_flow import (  # noqa: F401
    EG4ConfigFlow,
    EG4OptionsFlow,
)
__all__ = ["EG4ConfigFlow", "EG4OptionsFlow"]
```

> **Test patch target.** The cloud client is patched at
> **`custom_components.eg4_web_monitor._config_flow.LuxpowerClient`** — the `_config_flow`
> **package** namespace, not the shim.
>
> | Claim | Grade |
> |---|---|
> | That is the exact string the tests use | `verified-against-code` — `tests/test_config_flow.py:141`; `tests/test_cloud_session_isolation.py:496`, `:533`, `:563`, `:592` |
> | It works because `_config_flow/__init__.py` does `from pylxpweb import LuxpowerClient`, binding the name in that module | `verified-against-code` — `_config_flow/__init__.py:29`, construction site at `:1409-1411` |
> | Patching `config_flow.LuxpowerClient` is **impossible** — the shim imports only `EG4ConfigFlow` and `EG4OptionsFlow`, so the name does not exist in that namespace | `verified-against-code` — the shim is reproduced in full above |
>
> The repo's own notes have carried the shim-namespace version of this; it is wrong, and patching
> through the shim would raise `AttributeError` rather than silently miss.

| File | Responsibility |
|---|---|
| `_config_flow/__init__.py` | Single `EG4ConfigFlow` (`VERSION = 3`) — onboarding, network scan, reauth, reconfigure, entry build/update |
| `_config_flow/options.py` | `EG4OptionsFlow` — connection-aware interval form and battery-control-mode pickers |
| `_config_flow/discovery.py` | Device auto-discovery over Modbus / dongle / serial |
| `_config_flow/schemas.py` | Voluptuous schema builders |
| `_config_flow/helpers.py` | `build_unique_id`, `cloud_unique_id_from_data`, conflict finders, `migrate_legacy_entry`, `timezone_observes_dst` |
| `_config_flow/serial_ports.py` | Serial port enumeration |

All rows: `verified-against-code`. This table is the **canonical** `_config_flow/` package layout
(adjudication A7); `architecture.md` and `00-orientation/repo-map.md` link here instead of
restating it.

## 2. The flow class

| Fact | Evidence |
|---|---|
| `class EG4ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN)` | `verified-against-code` — `_config_flow/__init__.py:128-131` |
| `VERSION = 3` | `verified-against-code` — `:138` |
| Docstring: *"Replaces the previous 12-mixin architecture with a single class. Connection type is derived from configured data, not chosen upfront."* | `verified-against-code` — `:132-136` |
| Flow state is plain instance attributes set in `__init__` (cloud state, local-device state, serial state, network-scan state, a `_reconfigure_after_device` context flag) | `verified-against-code` — `:140-176` |
| Options flow accessor: `async_get_options_flow` returns `EG4OptionsFlow()` | `verified-against-code` — `:178-183` |

## 3. Connection-type derivation

```python
# _config_flow/__init__.py:113-120
def _derive_connection_type(has_cloud: bool, has_local: bool) -> str:
    if has_cloud and has_local:  return CONNECTION_TYPE_HYBRID
    if has_cloud:                return CONNECTION_TYPE_HTTP
    return CONNECTION_TYPE_LOCAL
```

| Input | Definition | Cite |
|---|---|---|
| `_has_cloud` | `bool(self._username and self._plant_id)` | `:189-192` |
| `_has_local` | `bool(self._local_transports)` | `:194-197` |

Used in `_build_entry_data` (`:1440`) and `_build_title` (`:1471`). All
`verified-against-code`.

**The user never picks a connection type.** The entry menu offers "Cloud (HTTP)" or "Local
Device" as *starting points*; the stored `connection_type` is recomputed from what ends up
configured.

## 4. Onboarding step graph — real step names

```
user (MENU)                                                    :219
├── cloud_credentials ──(1 plant)──────────────► cloud_add_local (MENU)   :233, :275
│        └──(N plants)──► cloud_station ───────► cloud_add_local          :259
│                                                ├── local_device_type
│                                                └── cloud_finish → _create_entry   :285
└── local_device_type (MENU)                                              :295
     ├── network_scan_config → network_scan_progress → network_scan_results   :336, :379, :422
     │                                              └→ network_scan_empty (MENU)  :473
     ├── local_modbus ─┐                                                  :490
     ├── local_serial ─┤→ local_serial_manual                             :609, :652
     └── local_dongle ─┴──► local_device_confirmed → local_device_added (MENU)  :543, :674, :759
                                                     ├── local_device_type   (add another)
                                                     ├── local_add_cloud     (→ cloud_credentials)  :769
                                                     └── local_finish → _create_entry               :775
```

Evidence: `verified-against-code` — every `async_step_*` method enumerated from
`_config_flow/__init__.py` at `c411499`.

### 4.1 Modbus TCP discovery classifies a standalone battery explicitly

The normal inverter path starts with `EndpointBusCapability.read_serial_number()`, whose
first wire request is for input registers 115–119. If that call raises a timeout, OS error,
or pylxpweb `TransportError`, `discover_modbus_device` makes one bounded holding-register
read of H0–H41 before preserving the original failure. It accepts a battery classification
only when the full block exists, pylxpweb's `detect_protocol` selects `eg4_master` or
`eg4_slave`, and the corresponding voltage, SOC, 16-cell count and (for a slave) sixteen
cell-voltage fields pass the map-specific plausibility checks. An all-zero, incomplete, or
otherwise non-battery response re-raises the original discovery error unchanged.

On a match, discovery raises `StandaloneBatteryDetectedError`; both
`async_step_local_modbus` and `async_step_reconfigure_add_modbus` map it to
`standalone_battery_not_supported`. Every shipped locale explains that the target is a
battery and points to issue #176 instead of presenting the generic Modbus timeout.

`verified-against-code` — `_config_flow/discovery.py` →
`_detect_standalone_battery_protocol`, `discover_modbus_device`;
`_config_flow/__init__.py` → both exception mappings; `tests/test_config_flow_scan.py` →
master/slave and non-battery regression cases; `tests/test_config_flow.py` → both form
mappings, all at `c411499`.

Issue #574 preserves the motivating master/slave holding-register dumps and the failed
input-register request. Those device observations are `asserted-unverified`; the code and
tests prove only how the integration classifies matching responses, not a general hardware
claim about every EG4 battery.

## 5. Reauth

| Step | Cite |
|---|---|
| `async_step_reauth` | `:807` |
| `async_step_reauth_confirm` | `:811` |

`verified-against-code`. Both names are also **CI-enforced**: the Silver
"Reauthentication Flow" job greps `_config_flow/__init__.py` for `async_step_reauth` and
`async_step_reauth_confirm` and fails the build if either is absent
(`verified-against-code` — `.github/workflows/quality-validation.yml`, job
`Silver - Reauthentication Flow`). Note the job greps the **package** file directly, not the shim.

## 6. Reconfigure

`async_step_reconfigure` (`:856`) hands off to `async_step_reconfigure_menu` (`:890`), whose menu
options are **built conditionally**:

| Condition | Menu options offered | Cite |
|---|---|---|
| `_has_cloud` | `reconfigure_cloud_update`; plus `reconfigure_cloud_remove` only when `_has_local` too | `:894-899` |
| not `_has_cloud` | `reconfigure_cloud_add` | `:900-901` |
| always | `reconfigure_devices` | `:903` |

`verified-against-code`. Note the guard: cloud can only be *detached* when local transports exist —
otherwise the entry would have no data source at all.

### 6.1 Complete reconfigure step list

| Step | Cite |
|---|---|
| `async_step_reconfigure` | `:856` |
| `async_step_reconfigure_menu` | `:890` |
| `async_step_reconfigure_cloud_update` | `:918` |
| `async_step_reconfigure_cloud_add` | `:943` |
| `async_step_reconfigure_cloud_station` | `:969` |
| `async_step_reconfigure_cloud_remove` (detach cloud) | `:996` |
| `async_step_reconfigure_devices` | `:1020` |
| `async_step_reconfigure_device_remove` | `:1055` |
| `async_step_reconfigure_devices_save` | `:1080` |
| `async_step_reconfigure_device_add` | `:1086` |
| `async_step_reconfigure_add_modbus` | `:1101` |
| `async_step_reconfigure_add_dongle` | `:1158` |
| `async_step_reconfigure_add_serial` | `:1228` |
| `async_step_reconfigure_add_serial_manual` | `:1276` |

All `verified-against-code` — enumerated by grepping `async def async_step_` in
**`_config_flow/__init__.py`** at `9f6d6e2`. That file is the frame: it holds every config-flow
step. The only `async_step_*` defined anywhere else in the component is the options flow's
`async_step_init` (`_config_flow/options.py:119`, §9), which belongs to a different flow class
and is deliberately not in this list (`verified-against-code` — a component-wide grep returns
exactly that one additional definition).

> **There is no `async_step_reconfigure_plant`** — the enumeration above contains no
> `reconfigure_plant`, and the station-selection step during reconfigure is
> **`async_step_reconfigure_cloud_station`** (`verified-against-code`).
>
> The durable trap is that **this codebase names the same concept two ways, and the step names use
> the rarer one.** Step names say *station*; the data keys, helpers and locals inside those very
> steps say *plant*:
>
> | Layer | Vocabulary | Evidence |
> |---|---|---|
> | Step names | `station` — `async_step_cloud_station`, `async_step_reconfigure_cloud_station` | `verified-against-code` — `_config_flow/__init__.py:259`, `:969` |
> | Everything inside them | `plant` — `self._plant_id = user_input[CONF_PLANT_ID]`, `find_plant_by_id(...)` | `verified-against-code` — `_config_flow/__init__.py:264-265`, `:976` |
> | Config-entry data and unique IDs | `plant` — `CONF_PLANT_ID`, `build_unique_id(..., plant_id=...)` | `verified-against-code` — `_config_flow/helpers.py` → `build_unique_id` |
> | The portal itself | `plant` — the station-list endpoint path contains `plant/list/viewer` | Grade **owned by [../30-portal-api/endpoints.md](../30-portal-api/endpoints.md)**, which pins pylxpweb and holds this fact. This page cites it for the vocabulary point only and asserts no grade of its own over another chapter's repo |
>
> So anyone reasoning from the data model — which is *plant* almost everywhere — reaches for a
> `..._plant` step name, and guesses a method that does not exist. **Derive step names from the
> enumeration above, never from the vocabulary of the data they operate on.**

### 6.2 `_update_entry` guards

| Guard | Behavior | Cite |
|---|---|---|
| Preserve an established **local-only** unique_id | Recomputing it would collapse unrelated installs onto `local_local` | `:1513-1577` |
| Refuse when another canonical owner holds the identity | Prevents two entries claiming the same cloud plant | `:1513-1577` |

`verified-against-code`.

## 7. Identity and migration helpers (`_config_flow/helpers.py`)

| Helper | Behavior | Cite |
|---|---|---|
| `build_unique_id(mode, ...)` | `http` / `hybrid` → `f"{username}_{plant_id}"` — **mode-independent by design**, so HTTP and HYBRID entries cannot both own the same remote plant. `modbus` / `dongle` → `f"{mode}_{serial}"`. `local` → `f"local_{station_name.lower().replace(' ', '_')}"`. Raises `ValueError` on missing required params or an unknown mode | `:76-108` |
| `cloud_unique_id_from_data(data)` | Canonical cloud identity recomputed from stored entry data; returns `None` unless both `username` and a non-empty `plant_id` are present | `:111-121` |
| `find_config_entry_identity_conflicts` | Matches on exact `unique_id` **or** derived cloud identity, catching legacy `hybrid_`-prefixed IDs | `:124-146` |
| `find_serial_conflict` | Scans both flat legacy entries and `local_transports` arrays | `:149-171` |
| `find_plant_by_id` | Plant lookup within a fetched plant list | `:174-180` |
| `migrate_legacy_entry` | Flat `modbus`/`dongle` keys → one `local_transports` element; sets `connection_type = local` | `:183-221` |
| `format_entry_title(_mode, name)` | `f"{BRAND_NAME} - {name}"` — the mode parameter is **literally named `_mode` and unused** | `:71-73` |
| `timezone_observes_dst` | Jan-15 vs Jul-15 UTC-offset comparison | `:35-61` |
| `get_ha_timezone` | HA config timezone accessor | `:64-68` |

All rows: `verified-against-code`.

> The cloud unique_id being **mode-independent** is deliberate: connection mode is mutable, so
> keying identity on it would let a single plant be owned by two entries after a mode switch. The
> code comment states this explicitly (`_config_flow/helpers.py:93-95`).

## 8. Entry migration (`async_migrate_entry`)

| Fact | Evidence |
|---|---|
| Handles v1→v2 (transport array) and v2→v3 (canonical cloud identity), **staged and committed together** | `verified-against-code` — `__init__.py:479-567` |
| Owner election via `_select_cloud_migration_owner`: the canonical owner wins; otherwise the oldest entry by `(created_at, entry_id)` | `verified-against-code` — `__init__.py:460-476` |
| When it must refuse, it raises a `duplicate_cloud_entry` Repairs issue | `verified-against-code` — `__init__.py:541-554` |

## 9. Options flow (`_config_flow/options.py`)

Single `init` step (`async_step_init`, `:119`). Fields shown depend on connection type and
configured transport types.

| Field group | Shown when | Cite |
|---|---|---|
| Modbus interval / Dongle interval / HTTP interval / legacy generic sensor interval | per connection type + `_has_transport_type()` | `:184-275`, helper `:95-100` |
| Parameter refresh interval, library debug | always | `:278-295` |
| Data-validation toggle, Modbus block size | local-only | `:298-324` |
| Charge/discharge control-mode pickers | always; pre-filled from the **live** reg-179 regime when polled, else the stored option | `:326-338`, `:380-403` |

All rows: `verified-against-code`.

### 9.1 The critical options-flow guard

| Mechanism | Why it exists | Cite |
|---|---|---|
| `_control_mode_prefill` records the pre-filled `(charge, discharge)` tuple at form-build time | On submit, the regime write fires **only if the submitted tuple differs**. Without this, *any* unrelated options save (e.g. changing a poll interval) would rewrite another inverter's battery-control regime | `:93`, `:144-154`, `:332` |
| `_apply_battery_control_mode` skips inverters whose live regime is unknown | Never guess a regime from a failed read | `:405-433` |

`verified-against-code`.

### 9.2 Side effects

| Effect | Cite |
|---|---|
| Saving options triggers a **full config-entry reload** | `verified-against-code` — `__init__.py:1393-1396` |
| Configuring a WiFi dongle auto-sets `CONF_DATA_VALIDATION = True` (onboarding and reconfigure) | `verified-against-code` — `_config_flow/__init__.py:1500-1505`, `:1561-1565` |
| On setup, options are force-migrated: `CONF_HTTP_POLLING_INTERVAL` is injected and sub-60 s HTTP intervals are bumped to 90 s | `verified-against-code` — `__init__.py:1193-1215` |

## 10. Known gotchas

| Gotcha | Detail | Evidence |
|---|---|---|
| **Station IDs are ints in production** | The frontend submits station selections as **strings**. Comparing without normalizing broke multi-station cloud onboarding (#275). `create_mock_station`'s docstring records this | `verified-against-code` — `tests/conftest.py:347-380` |
| Legacy `hybrid_`-prefixed unique IDs exist in the wild | `find_config_entry_identity_conflicts` matches derived cloud identity precisely to catch them | `verified-against-code` — `_config_flow/helpers.py:124-146` |
| `local` mode unique IDs are derived from the **station name** | Two local installs with the same station name collide. This is why `_update_entry` preserves an established local unique_id rather than recomputing it | `verified-against-code` — `helpers.py:104-108`, `__init__.py:1513-1577` |
