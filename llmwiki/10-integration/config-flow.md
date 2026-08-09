---
canonical-for:
  - the _config_flow package layout and the config_flow.py shim
  - real config-flow step names (onboarding, reauth, reconfigure, options)
  - connection-type derivation
  - unique-id construction, conflict detection, entry migration
sources:
  - custom_components/eg4_web_monitor/_config_flow/__init__.py
  - custom_components/eg4_web_monitor/_config_flow/helpers.py
  - custom_components/eg4_web_monitor/_config_flow/options.py
  - custom_components/eg4_web_monitor/config_flow.py
  - custom_components/eg4_web_monitor/__init__.py
  - tests/conftest.py
  - tests/test_config_flow.py
  - eg4_web_monitor issue #275
verified-against: 9f6d6e2
last-verified: 2026-08-08
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
| Repo `CLAUDE.md` documents the directory as `config_flow/` and gives a line count for the main module | The directory name is wrong — the package is `_config_flow/` (`verified-against-code`). The line count is also stale, but counts do not belong in prose either way; read the file |

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
`_config_flow/__init__.py` at `9f6d6e2`.

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

All `verified-against-code` — enumerated by grepping `async def async_step_` at `9f6d6e2`.

> **`async_step_reconfigure_plant` does not exist.** Repo `CLAUDE.md` names it as one of the two
> reconfigure flows. There is no such method. The station-selection step during reconfigure is
> **`async_step_reconfigure_cloud_station`**. Evidence: `verified-against-code` — the exhaustive
> step enumeration above contains no `reconfigure_plant`.

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
