---
canonical-for:
  - entity base-class inheritance graph
  - per-class availability semantics (unknown vs unavailable)
  - unique_id formats as implemented
  - entity_id derivation, and why _attr_entity_id is inert
sources:
  - custom_components/eg4_web_monitor/base_entity.py
  - custom_components/eg4_web_monitor/sensor.py
  - custom_components/eg4_web_monitor/binary_sensor.py
  - custom_components/eg4_web_monitor/update.py
  - custom_components/eg4_web_monitor/utils.py
  - custom_components/eg4_web_monitor/coordinator_mixins.py
  - homeassistant/helpers/entity.py (installed Home Assistant, repo .venv)
  - memory/issue-261-hybrid-sensor-flicker.md
  - memory/issue-253-duplicate-has-runtime-data.md
  - memory/issue-262-operating-state-and-i18n-names.md
  - memory/queue-cleanup-2026-07-26.md
  - eg4_web_monitor issues #550, #253, #256, #261, #479
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - ../60-history/open-contradictions.md
  - data-semantics.md
---

# Entities: inheritance, identity, availability

Line numbers pinned to `9f6d6e2`; symbol names are the durable anchor.

Two facts on this page are load-bearing and routinely mis-assumed. Read §2 and §4 before
reasoning about any entity-state bug.

## 1. Inheritance graph

```
CoordinatorEntity
├── EG4DeviceEntity                            base_entity.py:66
│   ├── EG4BaseSensor                          base_entity.py:414
│   │   └── EG4InverterSensor                  sensor.py:675
│   │       ├── EG4LastEventSensor             sensor.py:688
│   │       └── EG4QuickChargeRemainingSensor  sensor.py:723
│   ├── EG4BatteryBankEntity                   base_entity.py:627
│   │   └── EG4BatteryBankSensor               sensor.py:747
│   ├── EG4OffGridBinarySensor                 binary_sensor.py:56
│   └── EG4RefreshButton                       button.py:166
├── EG4BatteryEntity                           base_entity.py:117
│   ├── EG4BaseBatterySensor                   base_entity.py:522
│   │   └── EG4BatterySensor                   sensor.py:759
│   └── EG4BatteryRefreshButton                button.py:300
├── EG4StationEntity                           base_entity.py:182
│   ├── EG4StationSensor                       sensor.py:790
│   └── EG4StationRefreshButton                button.py:379
├── EG4OptimisticEntity                        base_entity.py:741
│   ├── EG4BaseNumber                          base_entity.py:1029
│   │   └── EG4BaseNumberEntity(+NumberEntity) number.py:177  → concrete number classes
│   ├── EG4BaseTime                            base_entity.py:1117
│   │   └── EG4ScheduleTimeEntity              time.py:185
│   ├── EG4BaseSelect(+SelectEntity)           base_entity.py:1184  → concrete selects
│   └── EG4BaseSwitch(+SwitchEntity)           base_entity.py:1246  → concrete switches
├── EG4FirmwareUpdateEntity                    update.py:55
└── EG4DSTSwitch                               switch.py:1540   (direct CoordinatorEntity)
```

Evidence: `verified-against-code` — class declarations at the cited lines.

Note the split: **measurement** entities descend from `EG4DeviceEntity` / `EG4BatteryEntity` /
`EG4StationEntity`; **control** entities descend from `EG4OptimisticEntity`. The two branches have
deliberately different availability contracts (§2).

## 2. Availability semantics DIFFER per base class

This is the single most-cited non-obvious mechanic in this codebase. There is **no** shared
availability rule.

> **Scope of this section.** Everything in §2.1–§2.4 describes the **verified current
> implementation** at `9f6d6e2` — what the code does. Whether that behaviour is the *intended*
> contract is an open question, recorded as **C10** in
> [../60-history/open-contradictions.md](../60-history/open-contradictions.md#c10--availability-contract-the-audit-contests-a-base-entity-behaviour-the-bug-notes-rely-on):
> the #261 notes treat "missing key → unknown, stays available" as deliberate, while the
> 2026-08-02 audit lists base-entity convergence treating a `None` cache state as fresh data as
> "deliberate, **contested**". Multiple shipped fixes (#253, #258, #261, #479) are built on the
> first reading. **This page does not pick a side.** Read the rows below as observed behaviour you
> must code against today, not as a contract you may rely on surviving adjudication.

| Class | `available` returns | Checks `last_update_success`? | Checks `"error"` key? | Checks key presence? | Cite |
|---|---|---|---|---|---|
| `EG4DeviceEntity` | serial present in `data["devices"]` | **No** | No | No | `base_entity.py:101-114` |
| `EG4BaseSensor` | `device_present_and_healthy()` | Yes | **Yes** | No | `base_entity.py:516-519`; helper `:282-299` |
| `EG4BaseBatterySensor` | parent healthy **and** `battery_key in parent["batteries"]` | Yes | Yes (on parent) | Yes (battery key) | `base_entity.py:610-624` |
| `EG4BatteryBankEntity` | device present, no `"error"`, **and `sensor_key in device["sensors"]`** | Yes | Yes | **Yes (sensor key)** | `base_entity.py:691-710` |
| `EG4StationEntity` | `last_update_success` and `"station" in data` | Yes | n/a | No | `base_entity.py:212-228` |
| `EG4OptimisticEntity` (all controls) | `_control_device_available()`: success + `_control_discovery_supported` + device exists + `device["type"] == "inverter"` | Yes | **Deliberately No** | No | `base_entity.py:796-812` |
| `EG4OffGridBinarySensor` | mirrors `EG4BaseSensor` on purpose (calls the same helper) | Yes | Yes | No | `binary_sensor.py:94-105` |
| `EG4FirmwareUpdateEntity` | `last_update_success` + serial present | Yes | No | No | `update.py:203-211` |

Every row: `verified-against-code`.

### 2.1 The asymmetry that causes flicker bugs

> **A missing sensor key means `unknown` for `EG4BaseSensor` but `unavailable` for
> `EG4BatteryBankEntity`.**

| Class | Key absent from `device["sensors"]` | Mechanism |
|---|---|---|
| `EG4BaseSensor` | Entity stays **available**, `native_value` is `None` → HA renders **unknown** | `available` never consults key presence; `_get_raw_value()` returns `None` (`base_entity.py:484-497`) |
| `EG4BatteryBankEntity` | Entity becomes **unavailable** | key presence is *part of* `available` (`base_entity.py:710`) |

Evidence: `verified-against-code` — both properties read at `9f6d6e2`.

This asymmetry is the root of the #261 HYBRID flicker. It compounds with a coordinator behaviour:
**the coordinator writes a sensor key only when its value is non-None**, so a transient transport
gap silently *drops* the key rather than nulling it. That is why `fault_code` read *unknown* while
`battery_bank_soc` read *unavailable* in the same poll.

| Claim | Grade |
|---|---|
| The coordinator omits a sensor key whose value is `None` | `verified-against-code` (`coordinator_mappings.py` → `_map_device_properties`, and the transport/energy overlays) |
| That omission produced the divergent #261 states in the field | `asserted-unverified` — `memory/issue-261-hybrid-sensor-flicker.md` |
| The same defect shape recurred on #479 and was caught only after the pre-merge review rounds | `asserted-unverified` — `memory/issue-479-cloud-lost-freeze.md` |

**Engineering rule (applies to the current implementation):** never gate bank/battery data by
*dropping keys*. **Extract-then-null** instead. Dropping keys reproduces the #261 unavailable
flicker under the semantics above. This rule is stable under either resolution of C10 — nulling is
correct whether or not the key-presence behaviour is later changed.

### 2.2 Full state-resolution table (observed behaviour)

| Situation | Resulting state |
|---|---|
| Sensor key missing, `EG4BaseSensor` | **unknown** (entity stays available) |
| Sensor key missing, `EG4BatteryBankEntity` | **unavailable** |
| `"error"` present in `device_data` | **unavailable** for measurement entities; controls stay **available** |
| `has_data == False` on a device | `_process_inverter_object` early-returns a diagnostic-only dict → every runtime key absent → **unknown**, device still "present and healthy" (no `"error"` key set) |
| Value present but `None` | **unknown** |
| Device absent from `data["devices"]` | **unavailable** (all classes) |

Evidence: `verified-against-code` for the availability rows; the `has_data` row is
`verified-against-code` via `device_present_and_healthy` not setting `"error"` on that path.

An offline device therefore reads `Status = offline` with live metrics *unknown*, rather than
blacking out entirely. That this is the **desired** outcome rather than merely the current one is
the #256 fix rationale, and it is `asserted-unverified`
(`memory/issue-256-offline-inverter-blackout.md`); the state resolution itself is
`verified-against-code`.

### 2.3 Controls do not consult the `"error"` key

| Claim | Grade |
|---|---|
| `EG4OptimisticEntity._control_device_available()` does not test for the `"error"` key | `verified-against-code` (`base_entity.py` → `_control_device_available`) |
| Its docstring gives the reason: *"controls are setpoints, not live readings, and stay available through a transport link-down or a transient processing failure"* | `verified-against-code` (the docstring exists and says this) — note that a code comment is evidence of **stated** intent, not of adjudicated intent |
| The same wording appears on `_sync_transport_link_state` and is applied to never-attached `transport_attach_failed` devices | `verified-against-code` (`coordinator_local.py` → `_sync_transport_link_state`) |

Practical consequence: a link-down does **not** currently make controls unavailable. Before
changing that, note that whether the per-class availability split is the intended contract is
**contested under C10** — see the scope note at the top of §2. A change here would alter the
behaviour several shipped fixes depend on, so it needs the C10 adjudication first, not a local
judgement call.

## 3. Value pipeline for sensors

| Stage | Behavior | Evidence |
|---|---|---|
| `native_value` runs `_guard_total_increasing()` | Pins downward dips **smaller than 10 %** for `total_increasing` sensors to the prior high-water mark; larger drops pass through as genuine resets | `verified-against-code` — `base_entity.py:312-345`, threshold `_RESET_DETECTION_THRESHOLD = 0.9` at `:309` |
| Why 10 % | Matches HA recorder's own reset threshold; smaller dips trigger a "state is not strictly increasing" warning and are virtually always cloud rounding noise | `verified-against-code` — comment at `base_entity.py:302-308` |
| Non-numeric / `None` / non-`total_increasing` | Returned untouched, cache not updated | `verified-against-code` — `base_entity.py:314-329` |
| `_apply_sensor_config()` | Applies unit / device_class / state_class / icon / options / `translation_key` / precision / entity_category / `enabled_default` from `SENSOR_TYPES` | `verified-against-code` — `base_entity.py:348-411` |

Two typing gaps worth knowing (`verified-against-code`):

- `SensorConfig` (`const/sensors/types.py:16-37`) **lacks** `options` and `translation_key`, even
  though `_apply_sensor_config` reads both (`base_entity.py:374-384`).
- `SENSOR_TYPES` is **not** annotated as `dict[str, SensorConfig]`; only `STATION_SENSOR_TYPES` is
  (`const/sensors/station.py:13`). `base_entity.py:367-369` casts.
- The `enabled_default` check uses truthiness, not `is False` (`base_entity.py:408`).

This guard is the sanctioned alternative to a coordinator-level energy clamp. See
[data-semantics.md](data-semantics.md) §4 — that section is mandatory reading before touching any
energy sensor.

## 4. `_attr_entity_id` is NOT a Home Assistant attribute — all 17 assignments are inert

### 4.1 The finding

| Claim | Evidence |
|---|---|
| The string `_attr_entity_id` appears **0 times** in the installed `homeassistant/helpers/entity.py` | `verified-against-code` — `grep -c "_attr_entity_id"` against `.venv/.../homeassistant/helpers/entity.py` returned `0` |
| `Entity` declares a plain `entity_id: str = None  # type: ignore[assignment]` | `verified-against-code` — `homeassistant/helpers/entity.py:441` |
| This repo contains **17** `_attr_entity_id` assignments | `verified-against-code` — `grep -rn '_attr_entity_id' --include='*.py'` → 17 |
| They are spread across 5 files | `verified-against-code` — `base_entity.py` (6), `button.py` (4), `select.py` (4), `update.py` (2), `binary_sensor.py` (1) |
| **All 17 are dead attributes.** Setting `_attr_entity_id` does nothing; HA never reads it | `verified-against-code` — the two facts above, combined |
| Tracked as issue **#550** — "Dead code: `_attr_entity_id` assignments are inert (not a Home Assistant Entity attribute)", OPEN | `verified-against-code` — issue read from the `joyfulhouse/eg4_web_monitor` tracker on 2026-08-08 |

`utils.generate_entity_id` (`utils.py:649-674`) likewise only feeds these dead attributes
(`verified-against-code`).

### 4.2 What HA actually does

Every entity in this integration sets `_attr_has_entity_name = True`
(`verified-against-code` — `base_entity.py:462, 570, 665, 1045, 1131, 1300`, and the platform
classes). Under that flag, HA composes the display name as *device name + entity name* and derives
the `entity_id` object_id by **slugifying that name** at first registration.

| Consequence | Detail |
|---|---|
| Entity IDs come from **slugified names**, never from `entity_key` constants | `verified-against-code` — HA `Entity`/`EntityPlatform` naming path + the `_attr_entity_id` finding |
| Live registry examples | `switch.18kpv_<serial>_eps_battery_backup` (despite `entity_key='battery_backup'`); `sensor.battery_bank_<serial>_battery_bank_max_cell_temperature` — `asserted-unverified` — production entity-registry capture recorded in `memory/queue-cleanup-2026-07-26.md`; not re-captured here |
| **HA freezes `entity_id` at first registration** | A device whose model string drifted across pylxpweb versions shows entities with two different model prefixes. That is one device, not two (`asserted-unverified` — `memory/queue-cleanup-2026-07-26.md`) |

> **Review trap.** Reasoning about entity IDs from `entity_key` constants produces false positives.
> Adjudicate any entity-ID claim against a live registry capture, not against source constants.
> Three reviewer findings were rejected on exactly this basis.

### 4.3 The documented format never took effect

| Documented in repo `CLAUDE.md` | Reality |
|---|---|
| `Entity ID (Inverter): eg4_{model}_{serial}_{sensor_name}` | **Never registered by HA.** The code that builds this string writes it to `_attr_entity_id`, which HA ignores (`verified-against-code` — `base_entity.py:470-482` + the §4.1 finding) |
| `Entity ID (Battery): eg4_{model}_{serial}_battery_{batteryKey}_{sensor_name}` | Same — inert (`base_entity.py:578`) |
| `Entity ID (GridBOSS): eg4_gridboss_{serial}_{sensor_name}` | Same — inert (`base_entity.py:473-475`) |

The strings are constructed correctly; they simply go nowhere. Do not use them to predict a live
entity ID, to write a test assertion about registry contents, or to build a dashboard reference.

### 4.4 Two related naming rules

| Rule | Why | Evidence |
|---|---|---|
| **Do not set `_attr_name` when you want a translatable name.** HA's `_name_internal()` returns `_attr_name` if the attribute exists, so it always beats `translation_key` for the NAME | This integration historically set `_attr_name` on every sensor, which made every locale's `entity.*.name` string dead. State/enum translations are a separate path and localize regardless | `asserted-unverified` — `memory/issue-262-operating-state-and-i18n-names.md` |
| **Two `SENSOR_TYPES` keys must never share a display `name`** | Same slug → same `entity_id` candidate, different `unique_id`s → HA keeps **both** as distinct active entities and neither can be deleted. That is the whole of issue #253 | `asserted-unverified` — `memory/issue-253-duplicate-has-runtime-data.md`; the regression guard is a test asserting no two keys in the property map share a `SENSOR_TYPES` name |

## 5. `unique_id` formats — as implemented

**This page is canonical for the unique-ID format table** (adjudication A1). `00-orientation/repo-map.md`
and `60-history/superseded-claims.md` link here rather than restating it.


These are what the code actually emits. `unique_id` **is** honored by HA (unlike `entity_id`), so
these strings are real and stable.

| Entity kind | Format | Cite |
|---|---|---|
| Device sensor | `f"{serial}_{sensor_key}"` | `base_entity.py:457` |
| Individual battery sensor | `f"{serial}_{battery_key}_{sensor_key}"` | `base_entity.py:565` |
| Battery bank sensor | `f"{serial}_battery_bank_{sensor_key}"` | `base_entity.py:660` |
| Station sensor | `f"station_{coordinator.plant_id}_{sensor_key}"` | `sensor.py:829` |
| Off-grid binary sensor | `f"{serial}_off_grid"` | `binary_sensor.py:73` |
| Firmware update | `f"{serial}_firmware_update"` | `update.py:80` |
| Switch | `generate_unique_id(serial, entity_key)` | `base_entity.py:1306` |
| Select | `generate_unique_id(serial, "operating_mode")` (etc.) | `select.py:180` |
| Number / time (via `EG4OptimisticEntity`) | `generate_unique_id(self._retention_serial.lower(), entity_key)` | `base_entity.py:814-816` |

All rows: `verified-against-code`. `utils.generate_unique_id` (`utils.py:677-693`) is literally
`f"{serial}_{entity_type}"` plus an optional `_{suffix}`.

> ⚠️ **Case divergence.** `_stable_control_unique_id` lowercases the serial; switch and select
> unique IDs do not. Lettered serials therefore differ in case **between platforms**. This is why
> `flag_offgrid_control_suppression` matches case-insensitively (`verified-against-code` —
> `utils.py:406`, `:421`). Any code matching unique-ID suffixes must be case-insensitive.

### 5.1 The `{data_type}` format that never existed

| Claim | Verdict |
|---|---|
| An older unique-ID form `{serial}_{data_type}_{sensor_key}_{batteryKey?}` | **Never implemented.** No Python in this repo's history emits a data-type segment; `git log --all -S` finds that shape only in markdown and one test fixture |
| Why the allowlist still exists | `_DEVICE_UID_DATA_TYPE_SEGMENTS` is kept **purely defensively** and is an allowlist on purpose |

Evidence: `verified-against-code` — the allowlist `_DEVICE_UID_DATA_TYPE_SEGMENTS` in
`__init__.py` and the comment above it, which records the `git log --all -S` result. The claim is
also recorded as **S1** in
[../60-history/superseded-claims.md](../60-history/superseded-claims.md) and as **C1** in
[../60-history/open-contradictions.md](../60-history/open-contradictions.md); repo `CLAUDE.md`
carries the correction inline (`asserted-unverified` for that last statement — it is a doc, not
code).

> **Stale-source warning.** `docs/claude/FINAL_VALIDATION_REPORT.md` still states the fictional
> format as fact. **Do not lift entity-ID or unique-ID formats from that file.** The failure chain
> is instructive: documentation-only fiction → a test fixture written to match the docs → real
> registry-cleanup code designed to satisfy the fixture.

## 6. Device identifiers (`DeviceInfo.identifiers`)

| Device | `identifiers` | `via_device` | Cite |
|---|---|---|---|
| inverter / gridboss / parallel_group | `(DOMAIN, serial)` — PG serial is `parallel_group_<name>` | `(DOMAIN, parallel_group_serial)` when a group is found | `coordinator_mixins.py:3924`, `:3937-3940` |
| individual battery | `(DOMAIN, battery_key)` | `(DOMAIN, f"{serial}_battery_bank")` | `coordinator_mixins.py:4000-4005` |
| battery bank | `(DOMAIN, f"{serial}_battery_bank")` | `(DOMAIN, serial)` | `coordinator_mixins.py:4053-4057` |
| station | `(DOMAIN, f"station_{plant_id}")` | — | `coordinator_mixins.py:4082` |

All rows: `verified-against-code`. Cloud PG naming is
`f"parallel_group_{group.name.lower()}"` (`coordinator_mixins.py:3961`).

Because of the `via_device` chain, the `SENSOR` platform must be forwarded **before** every other
platform — it is what creates the parent devices (`verified-against-code` — `__init__.py:80-93`).

**Battery identity is serial-first across all three modes**, with in-place registry migration
(`battery_migration.py`), so switching modes no longer duplicates battery devices (#252). Identity
must stay transport-independent.

## 7. Registry-disabled-by-default conventions

| Category | Rule | Cite |
|---|---|---|
| `SENSOR_TYPES` / `STATION_SENSOR_TYPES` rows with `"enabled_default": False` | Honored by `_apply_sensor_config` (truthiness check) | `base_entity.py:408-409`, `sensor.py:825-826`; example `const/sensors/station.py:44-50` |
| **All** schedule time entities | Disabled by default — explicit product decision | `time.py:225-226` |
| Regime-gated numbers | Default to `is_control_active(control_key, configured_charge, configured_discharge)`; the non-selected SOC/Voltage set starts disabled | `number.py:200-204` |
| Individually pinned | `GridPeakShavingPowerNumber` (`number.py:1203`), `SmartLoadNumber` (`number.py:1901`), `StartChargePowerNumber` (`number.py:2226`), `EG4SmartLoadSwitch` (`switch.py:1020`), some `EG4WorkingModeSwitch` rows (`switch.py:1302`) | as cited |

All rows: `verified-against-code`.

## 8. Renaming and retiring entities

| Rule | Consequence |
|---|---|
| Statistics carry over **only** if `unique_id` is unchanged | `asserted-unverified` — Home Assistant recorder behaviour as relied on in `memory/queue-cleanup-2026-07-26.md`; not re-verified against HA source here |
| A semantic level-shift on an **unchanged** `unique_id` must be documented as breaking | Nothing "breaks" mechanically, but the recorded history changes meaning mid-series |
| Renaming an entity's display name changes the slug for **new** registrations only | HA freezes `entity_id` at first registration |
