---
canonical-for:
  - "Module inventory by layer for custom_components/eg4_web_monitor"
  - "EG4DataUpdateCoordinator mixin composition and MRO ordering constraints"
  - "Config-entry setup, unload and removal sequence"
sources:
  - custom_components/eg4_web_monitor/coordinator.py
  - custom_components/eg4_web_monitor/coordinator_mixins.py
  - custom_components/eg4_web_monitor/coordinator_local.py
  - custom_components/eg4_web_monitor/coordinator_http.py
  - custom_components/eg4_web_monitor/__init__.py
  - memory/architecture-patterns.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - data-flow-by-mode.md
  - controls-and-writes.md
  - ../60-history/open-contradictions.md
---

# Integration architecture

Line numbers on this page are pinned by `verified-against: 9f6d6e2`. **Symbol names are the
durable anchor** — if a line number does not match, grep for the symbol rather than assuming the
fact changed.

Evidence grades used here are defined in [../README.md](../README.md#evidence-grade-legend).

## 1. Ten-second model

| Claim | Grade |
|---|---|
| One HA config entry == one cloud *station* (plant) **or** one bag of local devices | `verified-against-code` (`_config_flow/helpers.py` → `build_unique_id`) |
| One `EG4DataUpdateCoordinator` per entry, composed from **eight mixins plus HA's `DataUpdateCoordinator`** | `verified-against-code` (`coordinator.py` → `EG4DataUpdateCoordinator` class bases) |
| Connection mode (`http`/`local`/`hybrid`) is **derived** from what is configured, never chosen by the user | `verified-against-code` (`_config_flow/__init__.py` → `_derive_connection_type`) |
| The coordinator publishes ONE dict; every entity is a pure reader of it | `verified-against-code` (`base_entity.py` — every `available` property and `_get_raw_value` read `coordinator.data`) |
| For most entity classes, availability is key presence in that dict | `verified-against-code` (see [entities-identity-availability.md](entities-identity-availability.md)) |
| Controls write local-first, cloud-fallback, publish an optimistic value, then run a bounded post-write refresh | `verified-against-code` (`utils.py` → `async_write_with_cloud_fallback`; `base_entity.py` → `EG4OptimisticEntity`) |

### Canonical published data shape

```python
{
  "plant_id": str | None,
  "connection_type": "http" | "local" | "hybrid",
  "last_update": datetime,
  "station": {...},                      # cloud/hybrid only
  "device_info": {...},
  "parameters": {serial: {PARAM_NAME: value}},
  "devices": {
     serial: {
       "serial", "type": "inverter" | "gridboss" | "parallel_group",
       "model", "firmware_version", "firmware_update_info",
       "features": {...},                # capability gating source
       "sensors": {sensor_key: value},   # entity availability = key presence
       "binary_sensors": {...},
       "batteries": {battery_key: {sensor_key: value}},
       "quick_charge_status": {...}, "ac_couple_soc": {...}, "smart_load": {...},
       "last_event_detail": {...},
       "error": "Local transport link down" | ...,   # present ONLY when set
       "member_serials": [...],          # parallel_group only
     }
  }
}
```

`verified-against-code` — assembled by `coordinator_local.py` → `_async_update_local_data`,
`coordinator_mixins.py` → `_process_inverter_object`, and `coordinator_http.py` →
`_process_station_data`.

> The `"error"` key is **absent** on the healthy path. Its presence, not its value, is what
> measurement entities test. Controls deliberately ignore it.

## 2. Module inventory by layer

Responsibilities only. Per-file line counts and key counts are deliberately omitted:
[`_conventions.md`](../_conventions.md) bans copying a code value into prose as a standalone fact,
and such counts rot on the next commit. Read the file.

### 2.1 Setup / entry layer

| File | Responsibility |
|---|---|
| `__init__.py` | `async_setup` (service registration), `async_setup_entry`, `async_migrate_entry` (v1→v3), `async_unload_entry`, `async_remove_entry`, every one-time registry migration/purge, platform forwarding order, library-logging ownership, failed-setup rollback |
| `manifest.json` | domain, `quality_scale`, the `pylxpweb` requirement pin |
| `hacs.json` | HACS packaging |
| `services.yaml` | Service schemas for `refresh_data`, `reconcile_history`, `import_historical_data`, `fetch_events` |
| `strings.json` + `translations/` | config / options / selector / entity / services / **exceptions** / **issues** |
| `py.typed` | PEP 561 marker |

### 2.2 Coordinator layer

| File | Responsibility |
|---|---|
| `coordinator.py` | The `EG4DataUpdateCoordinator` class itself: construction, transport wiring, intervals, `_async_update_data`, scoped listener fan-out, parameter write seeds, endpoint locks, raw/named register writes, battery-control-regime writes |
| `coordinator_mixins.py` | Six of the eight mixins (§3), plus device→sensor processing, the side-fetch breaker, cloud param stores, device info, parameter management, DST, background tasks, firmware |
| `coordinator_local.py` | `LocalTransportMixin`: LOCAL/Modbus/dongle polling, round-robin battery merge, static first-refresh phase, local parallel groups, transport attach/retry, link-down sync, transport predicates |
| `coordinator_http.py` | `HTTPUpdateMixin`: cloud **and hybrid** update paths, endpoint-serialized station refresh, degraded-device cache busting, battery carry-forward |
| `coordinator_mappings.py` | Pure functions and frozensets: property maps, sensor-key sets, family/grid-type inference, GridBOSS overlay tables, transport config building |
| `cloud_requests.py` | Account-shared cloud request budget (semaphore), `CloudRequestLimiter`, shared firmware-status single flight |
| `cloud_session.py` | Cancellation-safe close/detach of the injected `aiohttp` session |
| `transport_serialization.py` | `physical_endpoint_key()`, task-reentrant `EndpointOperationLock` |

### 2.3 Entity base layer

| File | Responsibility |
|---|---|
| `base_entity.py` | `EG4DeviceEntity`, `EG4BatteryEntity`, `EG4StationEntity`, `EG4BaseSensor`, `EG4BaseBatterySensor`, `EG4BatteryBankEntity`, `EG4OptimisticEntity`, `EG4BaseNumber`, `EG4BaseTime`, `EG4BaseSelect`, `EG4BaseSwitch`, `optimistic_value_context`, `_guard_total_increasing` |
| `control_discovery.py` | `setup_control_entity_discovery()` — signature-driven late discovery for control platforms, plus model-prefix unique-ID migration |

### 2.4 Platforms

| File | Responsibility |
|---|---|
| `sensor.py` | 3-phase entity registration plus late-discovery listeners; `_should_create_sensor()` is the capability gate |
| `number.py` | The control-number classes, `EG4BaseNumberEntity` read/write helpers, `VoltageNumberSpec` / `SmartLoadNumberSpec` tables |
| `switch.py` | Quick Charge, AC Couple, Smart Load, EPS/Battery Backup, Off-Grid, working modes, station DST switch |
| `select.py` | Operating Mode, PV Input Mode, GridBOSS Smart Port, Battery Charge/Discharge Control |
| `time.py` | Schedule windows from the declarative `SCHEDULE_TIME_TYPES` table |
| `button.py` | Device / battery / station Refresh buttons (2-phase registration) |
| `update.py` | `EG4FirmwareUpdateEntity`, module-level per-serial install locks |
| `binary_sensor.py` | `EG4OffGridBinarySensor` |
| `diagnostics.py` | Config-entry diagnostics with serial aliasing and redaction |

### 2.5 Config flow package

The implementation package is **`_config_flow/`** (leading underscore); `config_flow.py` is a thin
re-export shim that exists only to satisfy hassfest. The per-file table is owned by
[config-flow.md](config-flow.md#1-package-layout--it-is-_config_flow-not-config_flow).

### 2.6 Services / helpers

| File | Responsibility |
|---|---|
| `services.py` | `reconcile_history` (statistics backfill) and `fetch_events` (portal event log) |
| `history_import.py` | `import_historical_data` — external statistics backfill with tz-migration and recovery snapshot |
| `device_removal.py` | `async_remove_config_entry_device` and the observation ledger |
| `battery_migration.py` | Legacy positional → canonical battery-key registry migration (issue #252) |
| `utils.py` | ID generators, model/battery-key cleaners, `async_write_with_cloud_fallback`, family gates, Repairs helper, event normalizer |

### 2.7 `const/` package

| File | Contents |
|---|---|
| `const/__init__.py` | Pure re-export facade with an explicit `__all__` |
| `const/sensors/inverter.py` | `SENSOR_TYPES` |
| `const/modbus.py` | `PARAM_*` cloud parameter names, register numbers, `ScheduleTimeSpec`, `SCHEDULE_TIME_TYPES` |
| `const/device_types.py` | Device types, inverter families, capability sensor sets, regime-gated control sets |
| `const/working_modes.py` | `WORKING_MODES`, `FUNCTION_PARAM_MAPPING` |
| `const/limits.py` | Number min/max/step |
| `const/config_keys.py` | `CONF_*`, connection types, all interval defaults and bounds |
| `const/operating_state.py` | Operating-state decode |
| `const/diagnostics.py` | Diagnostic key sets, `SUPPORTED_INVERTER_MODELS` |
| `const/brand.py` | `BrandConfig` → `DOMAIN`, `ENTITY_PREFIX`, `MANUFACTURER` |
| `const/sensors/mappings.py` | Field mappings and scaling sets |
| `const/sensors/station.py` | `STATION_SENSOR_TYPES` |
| `const/sensors/types.py` | `SensorConfig` TypedDict |

Whole section: `verified-against-code` — module contents read at `9f6d6e2`.

## 3. The coordinator: eight mixins plus HA's `DataUpdateCoordinator`

### 3.1 Declaration (authoritative)

```python
# coordinator.py:250-260 — EG4DataUpdateCoordinator class bases
class EG4DataUpdateCoordinator(
    HTTPUpdateMixin,          # coordinator_http.py  → HTTPUpdateMixin
    LocalTransportMixin,      # coordinator_local.py → LocalTransportMixin
    DeviceProcessingMixin,    # coordinator_mixins.py
    DeviceInfoMixin,          # coordinator_mixins.py
    ParameterManagementMixin, # coordinator_mixins.py
    DSTSyncMixin,             # coordinator_mixins.py
    BackgroundTaskMixin,      # coordinator_mixins.py
    FirmwareUpdateMixin,      # coordinator_mixins.py
    DataUpdateCoordinator[dict[str, Any]],   # Home Assistant, not a mixin
):
```

`verified-against-code` — class bases read directly at `9f6d6e2`; mixin definition sites confirmed
by `grep -n '^class .*Mixin'` across the three coordinator modules.

| Count | Value |
|---|---|
| Mixins contributed by this integration | **8** |
| Of those, defined in `coordinator_mixins.py` | 6 |
| Of those, defined elsewhere | 2 — `HTTPUpdateMixin` in `coordinator_http.py`, `LocalTransportMixin` in `coordinator_local.py` |
| Total class bases | 9 — the eight mixins plus HA's `DataUpdateCoordinator[dict[str, Any]]` |

Whole table: `verified-against-code` — counted from the class bases and from `grep -n '^class .*Mixin'` across `coordinator_mixins.py`, `coordinator_http.py` and `coordinator_local.py` at `9f6d6e2`.

> **Two counting errors are easy to make here, and both are in circulation.**
>
> - **Undercounting to six.** `HTTPUpdateMixin` and `LocalTransportMixin` are named "mixin" but
>   defined in the transport modules, so any survey scoped to `coordinator_mixins.py` — a grep, a
>   file read, a docs pass — finds only six and misses the two that come **first** in the MRO.
>   Six-mixin lists are in circulation for exactly this reason.
> - **Overcounting to nine.** Nine is the number of **base classes**, one of which
>   (`DataUpdateCoordinator`) is Home Assistant's and is not a mixin. Count the mixins, or count
>   the bases, but do not report one as the other.

All eight mixins inherit `_MixinBase`, which under `TYPE_CHECKING` is a stub class declaring the
coordinator attributes for mypy and **at runtime is `object`, so the MRO is unchanged**
(`verified-against-code` — `coordinator_mixins.py` → `_MixinBase`, whose own docstring states it).
Do not infer runtime behaviour from `_MixinBase`.

### 3.2 Responsibility table

| Mixin | Defined in | Owns | Key contributed methods |
|---|---|---|---|
| `HTTPUpdateMixin` | `coordinator_http.py` | Cloud **and hybrid** update paths | `_async_update_http_data`, `_async_update_hybrid_data`, `_refresh_station_devices`, `_should_poll_hybrid_local`, `_ensure_local_transports`, `_apply_battery_carry_forward`, `_process_station_data`, `_align_client_cache_with_http_interval` |
| `LocalTransportMixin` | `coordinator_local.py` | Local transports | `_async_update_local_data`, `_async_update_modbus_data`, `_async_update_dongle_data`, `_merge_round_robin_batteries`, `_read_modbus_parameters`, `_build_static_local_data`, `_process_local_parallel_groups`, `_attach_local_transports_to_station`, `_sync_transport_link_state`, `get_local_transport`, `has_local_transport`, `has_configured_local_transport`, `has_local_register_path`, `is_local_only` |
| `DeviceProcessingMixin` | `coordinator_mixins.py` | Device object → sensor dicts; all supplemental cloud side-fetches | `_process_inverter_object`, `_process_mid_device_object`, `_process_parallel_group_object`, `_extract_battery_*`, `_filter_unused_smart_port_sensors`, `_calculate_gridboss_aggregates`, `_fetch_quick_charge_status`, `_fetch_last_event`, `_fetch_pv_string_energy`, `_fetch_cloud_param_store`, `_breakered_cloud_call`, `_prefetch_firmware_update_info` |
| `DeviceInfoMixin` | `coordinator_mixins.py` | `DeviceInfo` construction and per-cycle caches | `clear_device_info_caches`, `get_device_info`, `get_battery_device_info`, `get_battery_bank_device_info`, `get_station_device_info`, `_get_parallel_group_for_device` |
| `ParameterManagementMixin` | `coordinator_mixins.py` | Parameter reads and publishing | `refresh_all_device_parameters`, `async_refresh_device_parameters`, `_refresh_device_parameters`, `_refresh_missing_parameters`, `_schedule_missing_parameter_refresh`, `_hourly_parameter_refresh`, `_should_refresh_parameters`, `_all_parameter_fetches_complete`, `note_parameter_verification_pending` |
| `DSTSyncMixin` | `coordinator_mixins.py` | Hourly portal DST reconciliation | `_should_sync_dst`, `_perform_dst_sync` |
| `BackgroundTaskMixin` | `coordinator_mixins.py` | Task and transport lifecycle | `async_shutdown`, `_async_handle_shutdown`, `_cancel_background_tasks`, `_disconnect_all_transports`, `_remove_task_from_set`, `_log_task_exception` |
| `FirmwareUpdateMixin` | `coordinator_mixins.py` | Firmware info extraction | `_extract_firmware_update_info` |

Whole table: `verified-against-code` — method definitions read in the cited modules.

### 3.3 MRO ordering constraints — do not reorder

| # | Constraint | Why it breaks if violated | Grade |
|---|---|---|---|
| 1 | `HTTPUpdateMixin` and `LocalTransportMixin` must precede the processing mixins | HYBRID calls `_async_update_http_data` from `_async_update_hybrid_data` **and** calls `LocalTransportMixin._attach_local_transports_to_station` / `_sync_transport_link_state`; all must resolve on `self` | `verified-against-code` (`coordinator_http.py` → `_async_update_hybrid_data`) |
| 2 | `BackgroundTaskMixin` must precede `DataUpdateCoordinator` | Its `async_shutdown` / `_async_handle_shutdown` must override HA's, so the coordinator can `super()` into them and then close the cloud session in `finally` | `verified-against-code` (`coordinator.py` → `async_shutdown`, `_async_handle_shutdown`) |
| 3 | Constructor ordering is **transactional** | `super().__init__(..., config_entry=None, ...)` passes `None` deliberately so a later failure cannot leave a half-built coordinator registered. The account-scoped shared registrations (request budget, limiter, firmware flight) are the **last fallible step**, with rollback in `except BaseException`. `self.config_entry = entry` and `entry.async_on_unload(...)` are the final, infallible operations | `verified-against-code` (`coordinator.py` → `EG4DataUpdateCoordinator.__init__`, and its inline comment) |
| 4 | `clear_device_info_caches()` must run at the start of every cycle | Otherwise entities register against last cycle's `DeviceInfo` | `verified-against-code` (`coordinator.py` → `_async_update_data`) |
| 5 | `_overlay_parameter_write_seeds(data)` must be the **last no-await step** before publishing | Otherwise a write acknowledged mid-cycle is overwritten by a stale read | `verified-against-code` (`coordinator.py` → `_async_update_data`) |

> Do not add fallible work after the firmware-owner acquire in the constructor, and never pass
> `config_entry=entry` to `super().__init__`.

## 4. Setup sequence (`async_setup_entry`, all modes)

| Step | Action | Symbol |
|---|---|---|
| 1 | `async_setup_entry` wraps `_async_setup_entry_logged` in a try/except that runs `_async_cleanup_failed_entry_setup` on ANY exception. Rollback unloads **only platforms actually attempted** (`coordinator._forwarded_platforms`), shuts down the coordinator, closes the client, nulls `runtime_data` | `__init__.py` → `async_setup_entry`, `_async_cleanup_failed_entry_setup` |
| 2 | Reconcile the process-global `pylxpweb` logger level from **all** loaded entries' preferences | `__init__.py` → `_async_register_library_logging` |
| 3 | Force-migrate options: inject the HTTP polling interval key and raise sub-minimum HTTP intervals (values owned by `const/config_keys.py`) | `__init__.py` → `_async_setup_entry_logged` |
| 4 | Snapshot existing `parallel_group_*` device identifiers **before** the first refresh | `__init__.py` → `_async_setup_entry_logged` |
| 5 | Construct the coordinator, load the PV-string lifetime `Store`, then `await coordinator.async_config_entry_first_refresh()` | `__init__.py` → `_async_setup_entry_logged` |
| 6 | **Registry hygiene passes** — all AFTER the first refresh (§4.1) | see below |
| 7 | **Ordered platform forwarding**: `SENSOR` first (it creates the parent devices that `via_device` needs), then the remaining platforms concurrently | `__init__.py` → `PLATFORMS_FIRST` / `PLATFORMS_REST` |
| 8 | Write `sw_version` from firmware into the device registry | `__init__.py` → `_async_update_device_registry` |
| 9 | Register the options-update listener; any options save triggers a **full entry reload** | `__init__.py` → `_async_options_updated` |

Whole table: `verified-against-code` — read at `9f6d6e2`.

### 4.1 Registry hygiene passes (step 6)

| Pass | Guard |
|---|---|
| Prune serial/station registry trees proven absent | **Liveness floor**: zero physical roots ⇒ never prune (`__init__.py` → `_async_cleanup_removed_registry_devices`) |
| Remove stale numeric-index battery entities | — |
| Rename `_power_output` → `_output_power` | — |
| Migrate parallel-group registry entries | `__init__.py` → `_migrate_parallel_group_registry_entries` |
| Purge deprecated charge/discharge suffixes | Set `_DEPRECATED_CHARGE_DISCHARGE_SUFFIXES`; must **not** contain `_battery_discharge_power` |
| Duplicate-key purge (issues #253 / #335) | — |
| Conditional `_battery_discharge_power` purge | — |
| Conditional `EG4_OFFGRID` generator-sensor purge plus a Repairs issue | — |
| Purge stale GridBOSS smart-port entities | Gated on `SMART_PORT_VALIDATED_KEY`, with a deferred one-shot coordinator listener when data is not yet authoritative |

Whole table: `verified-against-code` — `__init__.py` at `9f6d6e2`.

> Two of these are irreversible if wrong.
>
> `_DEVICE_UID_DATA_TYPE_SEGMENTS` is an **allowlist on purpose** — a bare `endswith(f"_{key}")`
> reaches into the battery and bank namespaces where `cycle_count`, `state_of_health` and
> `battery_type` live, so adding one of those keys silently deletes every per-battery entity while
> passing all tests (`verified-against-code` — `__init__.py`, and the allowlist's own comment).
>
> The smart-port cleanup must never run without `SMART_PORT_VALIDATED_KEY`: the LOCAL static first
> refresh carries no port keys, so cleaning there deleted every smart-port registry entry on each
> reboot (issue #217) (`verified-against-code` — `__init__.py` → the smart-port purge guard;
> `asserted-unverified` for the #217 field history, per `memory/architecture-patterns.md`).

## 5. Unload and removal

| Phase | Actions | Grade |
|---|---|---|
| Unload | Unload platforms → `coordinator.async_shutdown()` (disconnect transports, cancel background tasks) → close the HTTP client → unregister library logging | `verified-against-code` (`__init__.py` → `async_unload_entry`) |
| Removal | Purge recorder statistics for all entities, remove entity/device registry ownership (**shared devices are detached, not deleted**), remove the PV lifetime `Store` | `verified-against-code` (`__init__.py` → `async_remove_entry`) |

Per-device removal — the user deleting one device from the UI — is a separate, ledger-governed
path; see [diagnostics-repairs.md](diagnostics-repairs.md#6-device-removal-observation-ledger).

## 6. The update tick

```
_async_update_data()                         # coordinator.py → _async_update_data
  deepcopy(self.data)                        # pre-route snapshot for listener diffing
  clear_device_info_caches()
  _route_update_by_connection_type()
  _overlay_parameter_write_seeds(data)       # final no-await publish boundary
  if self.data is None: null out zero-valued total_increasing keys
  _pending_listener_contexts = _listener_contexts_for_data_change(...)
  assess_discovery_completeness + record_provided_identifiers   # removal ledger
```

`verified-against-code` — `coordinator.py` → `_async_update_data`.

| Mechanism | Behaviour | Grade |
|---|---|---|
| **3-strike stale tolerance** | The first two consecutive `UpdateFailed` cycles return the **same** `self.data` object with `last_update_success` still True; the third raises. `ConfigEntryAuthFailed` is always immediate | `verified-against-code` (`coordinator.py` → `_async_update_data`) |
| **Scoped listener fan-out** | Entities register a private `_ListenerContext` — `device:<serial>`, `station`, or `discovery`. Only listeners whose scope changed are notified. `notify_all` is forced on the first update and on any availability transition | `verified-against-code` (`coordinator.py` → `_ListenerContext`, `_listener_contexts_for_data_change`) |
| Discovery callbacks | Use `listener_changed_device_items()`, which degrades to "all devices" for coordinator doubles in tests | `verified-against-code` (`coordinator.py` → `listener_changed_device_items`) |

> **The 3-strike window makes `last_update_success` lie.** Code that needs to know whether a
> refresh actually produced new data must compare **data-object identity**, not the success flag.
> This is why post-write refresh judges `data is not data_before`
> (`verified-against-code` — `base_entity.py` → `_refresh_coordinator_data`). See
> [controls-and-writes.md](controls-and-writes.md).

## 7. Where to look next

| Question | Page |
|---|---|
| How does each mode actually fetch data? | [data-flow-by-mode.md](data-flow-by-mode.md) |
| Why is this entity `unknown` instead of `unavailable`? | [entities-identity-availability.md](entities-identity-availability.md) |
| How does a write get routed, and what happens after? | [controls-and-writes.md](controls-and-writes.md) |
| What are the real config-flow step names? | [config-flow.md](config-flow.md) |
| What does diagnostics redact; when is a device deleted? | [diagnostics-repairs.md](diagnostics-repairs.md) |
| Staleness, gating, energy, batteries, throttles | [data-semantics.md](data-semantics.md) |
| Register ground truth | [../40-hardware/registers.md](../40-hardware/registers.md) |
| Unresolved conflicts touching this chapter | [../60-history/open-contradictions.md](../60-history/open-contradictions.md) |
