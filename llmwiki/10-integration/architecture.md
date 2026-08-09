---
canonical-for:
  - module inventory of custom_components/eg4_web_monitor
  - EG4DataUpdateCoordinator mixin composition and MRO
  - config-entry setup / unload / removal sequence
  - which file owns which responsibility
sources:
  - custom_components/eg4_web_monitor/coordinator.py
  - custom_components/eg4_web_monitor/coordinator_mixins.py
  - custom_components/eg4_web_monitor/coordinator_local.py
  - custom_components/eg4_web_monitor/coordinator_http.py
  - custom_components/eg4_web_monitor/__init__.py
  - /tmp/llmwiki-research/integration-architecture.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Integration architecture

Line numbers in this chapter are pinned to commit `9f6d6e2`. **Symbol names are the durable
anchor** — if a line number does not match, grep for the symbol rather than assuming the fact
changed. (Historical notes in this repo drifted precisely this way; see
[data-semantics.md](data-semantics.md).)

## 1. Ten-second model

| Fact | Evidence |
|---|---|
| One HA config entry == one cloud *station* (plant) **or** one bag of local devices | `verified-against-code` — `_config_flow/helpers.py:76-108` |
| One `EG4DataUpdateCoordinator` per entry, composed from **9 mixins** + HA's `DataUpdateCoordinator` | `verified-against-code` — `coordinator.py:250-260` |
| Connection mode (`http`/`local`/`hybrid`) is **derived** from what is configured, never chosen by the user | `verified-against-code` — `_config_flow/__init__.py:113-120` |
| The coordinator publishes ONE dict; every entity is a pure reader of it | `verified-against-code` — `base_entity.py` availability + `_get_raw_value` all read `coordinator.data` |
| For most entity classes, availability is literally **key presence** in that dict | `verified-against-code` — see [entities-identity-availability.md](entities-identity-availability.md) |
| Controls write **local-first, cloud-fallback**, publish an optimistic value, then run a bounded post-write refresh | `verified-against-code` — `utils.py:185-270`, `base_entity.py:741-961` |

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

Evidence: `verified-against-code` — built at `coordinator_local.py:1989-1996`,
`coordinator_mixins.py:2570-2580`, `coordinator_http.py:724+`.

> The `"error"` key is **absent** on the healthy path. Its presence, not its value, is what
> measurement entities test. Controls deliberately ignore it.

## 2. Module inventory by layer

All line counts `verified-against-code` (`wc -l` at `9f6d6e2`).

### 2.1 Setup / entry layer

| File | Lines | Responsibility |
|---|---|---|
| `__init__.py` | 1,485 | `async_setup` (service registration), `async_setup_entry`, `async_migrate_entry` (v1→v3), `async_unload_entry`, `async_remove_entry`, every one-time registry migration/purge, platform forwarding order, library-logging ownership, failed-setup rollback |
| `manifest.json` | 15 | domain, `quality_scale: platinum`, `pylxpweb` requirement pin |
| `hacs.json` | 7 | HACS packaging (`zip_release`, min HA 2026.1.0) |
| `services.yaml` | 127 | 4 services: `refresh_data`, `reconcile_history`, `import_historical_data`, `fetch_events` |
| `strings.json` + `translations/*.json` (13 locales) | 1,133 each | config / options / selector / entity / services / **exceptions** / **issues** |
| `py.typed` | 2 | PEP 561 marker (Platinum requirement) |

### 2.2 Coordinator layer

| File | Lines | Responsibility |
|---|---|---|
| `coordinator.py` | 2,024 | The `EG4DataUpdateCoordinator` class itself: construction, transport wiring, intervals, `_async_update_data`, scoped listener fan-out, parameter write seeds, endpoint locks, raw/named register writes, battery-control-regime writes |
| `coordinator_mixins.py` | 4,851 | 6 of the 9 mixins + all device→sensor processing, side-fetch breaker, cloud param stores, device info, parameter management, DST, background tasks, firmware |
| `coordinator_local.py` | 3,263 | `LocalTransportMixin`: LOCAL/Modbus/dongle polling, round-robin battery merge, static first-refresh phase, local parallel groups, transport attach/retry, link-down sync, transport predicates |
| `coordinator_http.py` | 1,365 | `HTTPUpdateMixin`: cloud **and hybrid** update paths, endpoint-serialized station refresh, degraded-device cache busting, battery carry-forward |
| `coordinator_mappings.py` | 2,217 | Pure functions + frozensets: property maps, sensor-key sets, family/grid-type inference, GridBOSS overlay tables, transport config building |
| `cloud_requests.py` | 571 | Account-shared cloud request budget (semaphore), `CloudRequestLimiter`, shared firmware-status single flight |
| `cloud_session.py` | 61 | Cancellation-safe close/detach of the injected `aiohttp` session |
| `transport_serialization.py` | 57 | `physical_endpoint_key()`, task-reentrant `EndpointOperationLock` |

### 2.3 Entity base layer

| File | Lines | Responsibility |
|---|---|---|
| `base_entity.py` | 1,990 | `EG4DeviceEntity`, `EG4BatteryEntity`, `EG4StationEntity`, `EG4BaseSensor`, `EG4BaseBatterySensor`, `EG4BatteryBankEntity`, `EG4OptimisticEntity`, `EG4BaseNumber`, `EG4BaseTime`, `EG4BaseSelect`, `EG4BaseSwitch`, `optimistic_value_context`, `_guard_total_increasing` |
| `control_discovery.py` | 189 | `setup_control_entity_discovery()` — signature-driven late discovery for control platforms + model-prefix unique-ID migration |

### 2.4 Platforms

| File | Lines | Notes |
|---|---|---|
| `sensor.py` | 859 | 3-phase entity registration + 4 late-discovery listeners; `_should_create_sensor()` is the capability gate |
| `number.py` | 2,967 | ~30 control classes, `EG4BaseNumberEntity` read/write helpers, `VoltageNumberSpec` / `SmartLoadNumberSpec` tables |
| `switch.py` | 1,668 | Quick Charge, AC Couple, Smart Load, EPS/Battery Backup, Off-Grid, working modes, station DST switch |
| `select.py` | 688 | Operating Mode, PV Input Mode, GridBOSS Smart Port ×4, Battery Charge/Discharge Control |
| `time.py` | 547 | Schedule windows from the declarative `SCHEDULE_TIME_TYPES` table (7 families) |
| `button.py` | 423 | Device / battery / station Refresh buttons (2-phase registration) |
| `update.py` | 285 | `EG4FirmwareUpdateEntity`, module-level per-serial install locks |
| `binary_sensor.py` | 105 | Single `EG4OffGridBinarySensor` |
| `diagnostics.py` | 264 | Config-entry diagnostics with serial aliasing + redaction |

### 2.5 Config flow package

The package is `_config_flow/` (leading underscore). `config_flow.py` is a **13-line re-export
shim** so hassfest sees a file named `config_flow.py`. Full detail: [config-flow.md](config-flow.md).

| File | Lines | Responsibility |
|---|---|---|
| `_config_flow/__init__.py` | 1,583 | Single `EG4ConfigFlow` (`VERSION = 3`) — onboarding, network scan, reauth, reconfigure, entry build/update |
| `_config_flow/options.py` | 433 | `EG4OptionsFlow` — connection-aware interval form + battery-control-mode pickers |
| `_config_flow/discovery.py` | 498 | Device auto-discovery over Modbus / dongle / serial |
| `_config_flow/schemas.py` | 358 | Voluptuous schema builders |
| `_config_flow/helpers.py` | 221 | `build_unique_id`, `cloud_unique_id_from_data`, conflict finders, `migrate_legacy_entry`, `timezone_observes_dst` |
| `_config_flow/serial_ports.py` | 119 | Serial port enumeration |
| `config_flow.py` | 13 | **Thin re-export shim only** |

### 2.6 Services / helpers

| File | Lines | Responsibility |
|---|---|---|
| `services.py` | 821 | `reconcile_history` (statistics backfill) + `fetch_events` (portal event log) |
| `history_import.py` | 946 | `import_historical_data` — external statistics backfill with tz-migration + recovery snapshot |
| `device_removal.py` | 477 | `async_remove_config_entry_device` + the observation ledger |
| `battery_migration.py` | 244 | Legacy positional → canonical battery-key registry migration (#252) |
| `utils.py` | 738 | ID generators, model/battery-key cleaners, `async_write_with_cloud_fallback`, family gates, Repairs helper, event normalizer |

### 2.7 `const/` package

| File | Lines | Contents |
|---|---|---|
| `const/__init__.py` | 638 | Pure re-export facade with an explicit `__all__` |
| `const/sensors/inverter.py` | 2,592 | `SENSOR_TYPES` — **343 keys** |
| `const/modbus.py` | 422 | `PARAM_*` cloud parameter names, register numbers, `ScheduleTimeSpec` + `SCHEDULE_TIME_TYPES` |
| `const/device_types.py` | 382 | Device types, inverter families, capability sensor sets, regime-gated control sets |
| `const/working_modes.py` | 264 | `WORKING_MODES`, `FUNCTION_PARAM_MAPPING` |
| `const/limits.py` | 221 | Number min/max/step |
| `const/config_keys.py` | 172 | `CONF_*`, connection types, all interval defaults/bounds |
| `const/operating_state.py` | 109 | Operating-state decode (#262) |
| `const/diagnostics.py` | 82 | Diagnostic key sets, `SUPPORTED_INVERTER_MODELS` |
| `const/brand.py` | 54 | `BrandConfig` → `DOMAIN`, `ENTITY_PREFIX="eg4"`, `MANUFACTURER` |
| `const/sensors/mappings.py` | 292 | Field mappings + scaling sets |
| `const/sensors/station.py` | 77 | `STATION_SENSOR_TYPES` (9 keys) |
| `const/sensors/types.py` | 37 | `SensorConfig` TypedDict |

## 3. The coordinator and its nine mixins

### 3.1 Declaration (authoritative)

```python
# coordinator.py:250-260
class EG4DataUpdateCoordinator(
    HTTPUpdateMixin,          # coordinator_http.py:111
    LocalTransportMixin,      # coordinator_local.py:174
    DeviceProcessingMixin,    # coordinator_mixins.py:1073
    DeviceInfoMixin,          # coordinator_mixins.py:3879
    ParameterManagementMixin, # coordinator_mixins.py:4097
    DSTSyncMixin,             # coordinator_mixins.py:4541
    BackgroundTaskMixin,      # coordinator_mixins.py:4621
    FirmwareUpdateMixin,      # coordinator_mixins.py:4816
    DataUpdateCoordinator[dict[str, Any]],
):
```

Evidence: `verified-against-code` — read directly from `coordinator.py` at `9f6d6e2`.

> **Correction to repo `CLAUDE.md`.** `CLAUDE.md` lists **six** mixins and omits
> `HTTPUpdateMixin` and `LocalTransportMixin`. Both are in the MRO, and they come **first**.
> Any reasoning that assumes six mixins, or that the HTTP/local update methods live outside the
> coordinator's own MRO, is wrong. Evidence: `verified-against-code` — `coordinator.py:250-260`.

All mixins inherit `_MixinBase`, which under `TYPE_CHECKING` is a stub class declaring ~60
coordinator attributes for mypy, and **at runtime is `object`, so the MRO is unchanged**
(`verified-against-code` — `coordinator_mixins.py:766-772`). Do not infer runtime behavior from
`_MixinBase`.

### 3.2 Responsibility table

| Mixin | Owns | Key contributed methods |
|---|---|---|
| `HTTPUpdateMixin` | Cloud **and hybrid** update paths | `_async_update_http_data`, `_async_update_hybrid_data`, `_refresh_station_devices`, `_should_poll_hybrid_local`, `_ensure_local_transports`, `_apply_battery_carry_forward`, `_process_station_data`, `_align_client_cache_with_http_interval` |
| `LocalTransportMixin` | Local transports | `_async_update_local_data`, `_async_update_modbus_data`, `_async_update_dongle_data`, `_merge_round_robin_batteries`, `_read_modbus_parameters`, `_build_static_local_data`, `_process_local_parallel_groups`, `_attach_local_transports_to_station`, `_sync_transport_link_state`, `get_local_transport`, `has_local_transport`, `has_configured_local_transport`, `has_local_register_path`, `is_local_only` |
| `DeviceProcessingMixin` | Device object → sensor dicts; all supplemental cloud side-fetches | `_process_inverter_object`, `_process_mid_device_object`, `_process_parallel_group_object`, `_extract_battery_*`, `_filter_unused_smart_port_sensors`, `_calculate_gridboss_aggregates`, `_fetch_quick_charge_status`, `_fetch_last_event`, `_fetch_pv_string_energy`, `_fetch_cloud_param_store`, `_breakered_cloud_call`, `_prefetch_firmware_update_info` |
| `DeviceInfoMixin` | `DeviceInfo` construction + per-cycle caches | `clear_device_info_caches`, `get_device_info`, `get_battery_device_info`, `get_battery_bank_device_info`, `get_station_device_info`, `_get_parallel_group_for_device` |
| `ParameterManagementMixin` | Parameter reads/publishing | `refresh_all_device_parameters`, `async_refresh_device_parameters`, `_refresh_device_parameters`, `_refresh_missing_parameters`, `_schedule_missing_parameter_refresh`, `_hourly_parameter_refresh`, `_should_refresh_parameters`, `_all_parameter_fetches_complete`, `note_parameter_verification_pending` |
| `DSTSyncMixin` | Hourly portal DST reconciliation | `_should_sync_dst`, `_perform_dst_sync` |
| `BackgroundTaskMixin` | Task/transport lifecycle | `async_shutdown`, `_async_handle_shutdown`, `_cancel_background_tasks`, `_disconnect_all_transports`, `_remove_task_from_set`, `_log_task_exception` |
| `FirmwareUpdateMixin` | Firmware info extraction | `_extract_firmware_update_info` |

Evidence for the whole table: `verified-against-code` — method definitions in the cited modules.

### 3.3 MRO ordering constraints — do not reorder

| # | Constraint | Why it breaks if violated | Evidence |
|---|---|---|---|
| 1 | `HTTPUpdateMixin` and `LocalTransportMixin` must precede the processing mixins | HYBRID calls `_async_update_http_data` from `_async_update_hybrid_data` **and** calls `LocalTransportMixin._attach_local_transports_to_station` / `_sync_transport_link_state`; both must resolve on `self` | `verified-against-code` — `coordinator_http.py:342-418` |
| 2 | `BackgroundTaskMixin` must precede `DataUpdateCoordinator` | Its `async_shutdown` / `_async_handle_shutdown` must override HA's, so `coordinator.py:1054-1066` can `super()` into them and then close the cloud session in `finally` | `verified-against-code` — `coordinator.py:1054-1066` |
| 3 | Constructor ordering is **transactional** | `super().__init__(..., config_entry=None, ...)` passes `None` deliberately so a later failure cannot leave a half-built coordinator registered. Account-scoped shared registrations (request budget, limiter, firmware flight) are the **last fallible step**, with rollback in `except BaseException`. `self.config_entry = entry` and `entry.async_on_unload(...)` are the final, infallible operations | `verified-against-code` — `coordinator.py:724-818`, comment at `:804-806` |
| 4 | `clear_device_info_caches()` must run at the start of every cycle | Otherwise entities register against last cycle's `DeviceInfo` | `verified-against-code` — `coordinator.py:841` |
| 5 | `_overlay_parameter_write_seeds(data)` must be the **last no-await step** before publishing | Otherwise a write acknowledged mid-cycle is overwritten by a stale read | `verified-against-code` — `coordinator.py:848` |

> Do not add fallible work after the firmware-owner acquire in the constructor, and never pass
> `config_entry=entry` to `super().__init__`. Evidence: `verified-against-code` —
> `coordinator.py:724-818`.

## 4. Setup sequence (`async_setup_entry`, all modes)

Evidence for the whole sequence: `verified-against-code` — `__init__.py:1146-1390`.

| Step | Action | Cite |
|---|---|---|
| 1 | `async_setup_entry` wraps `_async_setup_entry_logged` in a try/except that runs `_async_cleanup_failed_entry_setup` on ANY exception. Rollback unloads **only platforms actually attempted** (`coordinator._forwarded_platforms`), shuts down the coordinator, closes the client, nulls `runtime_data` | `__init__.py:1146-1165`, `:1105` |
| 2 | `_async_register_library_logging` reconciles the process-global `pylxpweb` logger level from **all** loaded entries' preferences | `__init__.py:180-201` |
| 3 | Force-migration of options: inject `CONF_HTTP_POLLING_INTERVAL`, bump sub-60 s HTTP intervals to 90 s | `__init__.py:1193-1215` |
| 4 | Snapshot existing `parallel_group_*` device identifiers **before** the first refresh | `__init__.py:1220-1226` |
| 5 | Construct the coordinator, load the PV-string lifetime `Store`, then `await coordinator.async_config_entry_first_refresh()` | `__init__.py:1228-1235` |
| 6 | **Registry hygiene passes** — all AFTER the first refresh (table below) | `__init__.py:1240-1364` |
| 7 | **Ordered platform forwarding**: `SENSOR` first (it creates the parent devices that `via_device` needs), then the other 7 concurrently | `__init__.py:83-93`, `:1369-1376` |
| 8 | `_async_update_device_registry` writes `sw_version` from firmware | `__init__.py:570-614` |
| 9 | Options-update listener registered; any options save triggers a **full entry reload** | `__init__.py:1388`, `:1393-1396` |

### 4.1 Registry hygiene passes (step 6)

| Pass | Guard | Cite |
|---|---|---|
| `_async_cleanup_removed_registry_devices` — prune serial/station trees proven absent | **Liveness floor**: zero physical roots ⇒ never prune | `__init__.py:1240`, `:300-310` |
| Stale numeric-index battery entities | — | `__init__.py:1245-1263` |
| `_power_output` → `_output_power` rename | — | `__init__.py:1265-1291` |
| `_migrate_parallel_group_registry_entries` | — | `__init__.py:1300` |
| Deprecated charge/discharge suffixes | Set at `:105-116`; must **not** contain `_battery_discharge_power` | `__init__.py:1304-1312` |
| Duplicate-key purge (#253 / #335) | Set at `:137-143` | `__init__.py:1317` |
| Conditional `_battery_discharge_power` purge | — | `__init__.py:1321` |
| Conditional `EG4_OFFGRID` generator-sensor purge + Repairs issue | — | `__init__.py:1325`, `:879-951` |
| Stale GridBOSS smart-port entity purge | Gated on `SMART_PORT_VALIDATED_KEY`, with a deferred one-shot coordinator listener when data is not yet authoritative | `__init__.py:1337-1364` |

> Two of these are irreversible-if-wrong. `_DEVICE_UID_DATA_TYPE_SEGMENTS` is an **allowlist on
> purpose** — a bare `endswith(f"_{key}")` reaches into the battery and bank namespaces where
> `cycle_count`, `state_of_health` and `battery_type` live, so adding one of those keys silently
> deletes every per-battery entity while passing all tests (`verified-against-code` —
> `__init__.py:817-876`). And the smart-port cleanup must never run without
> `SMART_PORT_VALIDATED_KEY`: the LOCAL static first refresh has no port keys, so cleaning there
> deleted every smart-port registry entry each reboot (#217) (`verified-against-code` —
> `__init__.py:1005-1089`).

## 5. Unload and removal

| Phase | Actions | Cite |
|---|---|---|
| Unload | unload platforms → `coordinator.async_shutdown()` (disconnect transports, cancel background tasks) → close HTTP client → unregister library logging | `verified-against-code` — `__init__.py:1399-1419` |
| Removal | purge recorder statistics for all entities, remove entity/device registry ownership (**shared devices are detached, not deleted**), remove the PV lifetime `Store` | `verified-against-code` — `__init__.py:1422-1485` |

Per-device removal (the user deleting one device from the UI) is a separate, ledger-governed path —
see [diagnostics-repairs.md](diagnostics-repairs.md).

## 6. The update tick

```
_async_update_data()                         # coordinator.py:820-917
  deepcopy(self.data)                        # pre-route snapshot for listener diffing
  clear_device_info_caches()                 # :841
  _route_update_by_connection_type()         # :966-977
  _overlay_parameter_write_seeds(data)       # :848 — final no-await publish boundary
  if self.data is None: null out zero-valued total_increasing keys   # :857-864
  _pending_listener_contexts = _listener_contexts_for_data_change(...)
  assess_discovery_completeness + record_provided_identifiers        # removal ledger
```

Evidence: `verified-against-code` — `coordinator.py:820-917`.

| Mechanism | Behavior | Evidence |
|---|---|---|
| **3-strike stale tolerance** | The first two consecutive `UpdateFailed` cycles return the **same** `self.data` object with `last_update_success` still True; the third raises. `ConfigEntryAuthFailed` is always immediate | `verified-against-code` — `coordinator.py:897-917` |
| **Scoped listener fan-out** | Entities register a private `_ListenerContext` — `device:<serial>`, `station`, or `discovery`. Only listeners whose scope changed are notified. `notify_all` is forced on the first update and on any availability transition | `verified-against-code` — `coordinator.py:155-236`, `:919-948` |
| Discovery callbacks | Use `listener_changed_device_items()`, which degrades to "all devices" for coordinator doubles in tests | `verified-against-code` — `coordinator.py:219-236` |

> **The 3-strike window makes `last_update_success` lie.** Any code that needs to know whether a
> refresh actually produced new data must compare **data-object identity**, not the success flag.
> This is why post-write refresh judges `data is not data_before`
> (`verified-against-code` — `base_entity.py:1423-1438`). See [controls-and-writes.md](controls-and-writes.md).

## 7. Where to look next

| Question | Page |
|---|---|
| How does each mode actually fetch data? | [data-flow-by-mode.md](data-flow-by-mode.md) |
| Why is this entity `unknown` instead of `unavailable`? | [entities-identity-availability.md](entities-identity-availability.md) |
| How does a write get routed and what happens after? | [controls-and-writes.md](controls-and-writes.md) |
| What are the real config-flow step names? | [config-flow.md](config-flow.md) |
| What does diagnostics redact; when is a device deleted? | [diagnostics-repairs.md](diagnostics-repairs.md) |
| Staleness, gating, energy, batteries, throttles — the regression-prone semantics | [data-semantics.md](data-semantics.md) |
