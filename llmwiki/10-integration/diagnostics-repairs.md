---
canonical-for:
  - diagnostics output shape and redaction rules
  - serial/plant aliasing with digit-boundary guards
  - repairs issue keys and who raises them
  - device-removal observation ledger
sources:
  - custom_components/eg4_web_monitor/diagnostics.py
  - custom_components/eg4_web_monitor/device_removal.py
  - custom_components/eg4_web_monitor/utils.py
  - custom_components/eg4_web_monitor/coordinator_local.py
  - custom_components/eg4_web_monitor/__init__.py
  - custom_components/eg4_web_monitor/strings.json
  - memory/issue-reporting-hardening.md
  - eg4_web_monitor issues #174, #322, #515
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - ../50-operations/issue-pipeline.md
---

# Diagnostics, Repairs, and device removal

Line numbers pinned to `9f6d6e2`; symbol names are the durable anchor.

## 1. Diagnostics output shape

```python
{
  "entry": {"data": {...}, "options": {...}},
  "versions": {"pylxpweb": "<version>" | "unknown"},
  "coordinator": {
     "connection_type", "last_update_success", "update_interval",
     "device_count", "serial_aliases", "data"
  } | None
}
```

Evidence: `verified-against-code` — `diagnostics.py:200-263`.

| Behavior | Detail | Cite |
|---|---|---|
| **Works on a failed-setup or unloaded entry.** `runtime_data` is only assigned after the first successful refresh, so the dump degrades to a config-only snapshot (`"coordinator": None`) instead of raising | The reporter whose setup fails is exactly the reporter who most needs to attach evidence | `diagnostics.py:201-216`, `:254-256` |
| Per-value pipeline | `_jsonable()` → `async_redact_data(TO_REDACT)` → `_alias_serials()` | `diagnostics.py:227-230` |
| `pylxpweb` version resolution | `importlib.metadata.version("pylxpweb")`, falling back to `"unknown"` on `PackageNotFoundError` | `diagnostics.py:232-236` |

All rows: `verified-against-code`.

> The diagnostics platform **did not exist until 2026-08-02** (issue #515). Triage comments
> predating that asked reporters to download diagnostics that were not implemented.
> (`asserted-unverified` — `memory/issue-reporting-hardening.md`.)

## 2. Redaction rules

| Rule | Detail | Cite |
|---|---|---|
| **Entry title is never emitted** | It embeds the plant name | `verified-against-code` — the result dict contains only `entry.data` and `entry.options` (`:243-248`) |
| Redacted keys (`TO_REDACT`) | `username`, `password`, `plant_name`, `modbus_host`, `dongle_host`, plus location fields `name`, `address`, `phone`, `latitude`, `longitude`, `lat`, `lng`, `country`, `city`. Nested occurrences are covered because `async_redact_data` walks the whole tree | `diagnostics.py:35-53` |
| Base URL allowlist | Kept only if it is one of 3 public portal URLs (`monitor.eg4electronics.com`, `us.luxpowertek.com`, `eu.luxpowertek.com`), else `**REDACTED**`. Anything else is the reporter's private topology (a proxy, an internal hostname) | `diagnostics.py:57-61`, `:238-241` |
| **No `repr()`, ever** | Unknown objects become a bounded `<TypeName>` placeholder. A `repr` can embed credentials, hosts or tokens — an aiohttp exception repr carries the connection target — and nothing downstream could redact free-form repr text reliably | `diagnostics.py:184-198` |

All rows: `verified-against-code`.

## 3. Serial and plant-id aliasing

| Rule | Detail | Cite |
|---|---|---|
| Each **collected** serial → `SN_1 … SN_n`; plant id → `PLANT_1` | Built as an uppercase-keyed alias map. "Collected" is doing real work here — see §3.1 | `diagnostics.py:218-226` |
| Applied to **keys, values, and embedded substrings**, recursively | `_alias_serials` walks dicts (both key and value), lists/tuples, and strings | `diagnostics.py:153-181` |
| **Case-insensitive matching** | Letter-bearing dongle/battery serials appear **lowercased** inside derived strings such as entity IDs; the pattern compiles with `re.IGNORECASE` and looks the match up via `.upper()` | `diagnostics.py:150`, `:175` |
| **Longest-first ordering** | So a serial that embeds another is replaced before its fragment can be | `diagnostics.py:128-131` |
| **Digit-boundary guards** | A purely numeric serial or plant id is wrapped in `(?<!\d)…(?!\d)`, so it only matches where it is not part of a longer number. Without this, an energy reading containing the plant id as a substring would be corrupted | `diagnostics.py:134-151` |
| **Minimum serial length = 4** | Shorter (or empty) values are **dropped from the alias map** rather than aliased — a short string is more likely to be a coincidental substring than a serial. This is a deliberate trade-off with a residual gap; see §3.1 | `diagnostics.py:68-69`, `:127` |
| **int-typed occurrences handled explicitly** | The cloud returns `plantId` as a number; an int-typed serial or plant id would otherwise sail past the string replacement | `diagnostics.py:178-180` |
| Serial collection sources | Device dict keys + a recursive walk (`batteries` keys, any key containing `serial` or `battery_sn`) + entry data (`inverter_serial`, `dongle_serial`) + transports | `diagnostics.py:64-132` |

All rows: `verified-against-code`.

### 3.1 Residual limitation — aliasing is not a redaction guarantee

An earlier revision of this page said "every serial" is aliased. That is **false**, and the gap is
worth stating precisely because a reporter attaches this output to a public issue.

| Claim | Grade |
|---|---|
| The alias map is built only from serials the collector **found**, then filtered to those at least four characters long | `verified-against-code` — `diagnostics.py` → `_collect_serials`, `_MIN_SERIAL_LEN` |
| A real serial shorter than four characters is therefore **dropped from the alias map and survives verbatim** in the dump | `verified-against-code` — the length filter drops it before `_build_alias_pattern` runs; nothing else removes it |
| A serial-bearing value the collector does not reach is likewise not aliased. The collector walks device keys, `batteries` keys, keys containing `serial` or `battery_sn`, entry data, and transports — anything outside that walk is uncovered | `verified-against-code` — `diagnostics.py` → `_collect_serials` |
| Whether any real EG4/dongle/battery serial is under four characters | **Unknown here.** Observed serials are 10+ characters (`memory/issue-reporting-hardening.md`), which is the assumption the filter encodes — but the code enforces a length rule, not a schema, so a short value in a serial-designated field is not protected | `asserted-unverified` |

The trade-off the length filter buys is real: a two-character "serial" would match constantly as a
coincidental substring and corrupt the dump. The current code chooses dump integrity over
guaranteed coverage.

**Until the code changes, state the guarantee accurately:** diagnostics aliases *collected serials
of at least four characters*, plus the plant id. It is not a proof that no identifier appears in the
output. A fix would redact serial-**designated** fields by key regardless of value length (or drop
them), independently of the substring aliasing — that is a code change, out of scope for this page.

> **These rules must be preserved as a set.** Each one closes a specific leak: the title omission
> hides the plant name; case-insensitivity catches serials lowercased into entity IDs; the
> digit-boundary guard prevents corrupting numeric telemetry; the int handling catches the cloud's
> numeric `plantId`; the `repr` ban prevents connection targets leaking through exception text; and
> the failed-setup path exists because that reporter needs it most.

## 4. Repairs issues

Eleven issue keys are declared under `issues` in `strings.json` (`verified-against-code` —
enumerated from the file):

| Issue key | Raised by |
|---|---|
| `offgrid_grid_controls_removed` | `flag_offgrid_control_suppression` |
| `offgrid_battery_backup_removed` | `flag_offgrid_control_suppression` |
| `offgrid_ac_charge_soc_limit_removed` | `flag_offgrid_control_suppression` |
| `offgrid_forced_charge_times_removed` | `flag_offgrid_control_suppression` |
| `offgrid_generator_sensors_removed` | Setup-time generator-sensor purge, `__init__.py:939-951` |
| `dongle_validation_disabled` | Options/validation state |
| `unknown_family_fallback` | Family resolution fallback |
| `serial_attach_failed` | Local transport attach (per-serial) |
| `transport_attach_failed` | Local transport attach (whole transport) |
| `transport_link_down` | `_sync_transport_link_state` |
| `duplicate_cloud_entry` | Refused v2→v3 migration, `__init__.py:541-553` |

### 4.1 `flag_offgrid_control_suppression`

| Rule | Detail | Cite |
|---|---|---|
| Raises **one issue per `(issue_key, serial)`** | Not per entity | `verified-against-code` — `utils.py:362-439` |
| Raises **only if a matching entity was previously registered** | A fresh install that never had the control gets no noise | `verified-against-code` — `utils.py:362-439` |
| Matches unique-ID **suffixes with a serial-boundary guard**, case-insensitively | Number/time control unique IDs lowercase the serial while switch/select ones do not — see [entities-identity-availability.md](entities-identity-availability.md) §5 | `verified-against-code` — `utils.py:406`, `:421` |
| Callers | `switch.py:291-313`, `number.py:633-656`, `time.py:140-152` | `verified-against-code` |

### 4.2 Link-down issue lifecycle

| Behavior | Evidence |
|---|---|
| Created **once** per down transition; deleted on recovery | `verified-against-code` — `coordinator_local.py:2934-2961` |
| The healthy path performs an idempotent registry no-op, which clears a stale issue left by a restart that happened mid-outage | `verified-against-code` — same |
| LOCAL passes `processed` (sets the device `error` key **and** the issue); HYBRID passes `None` (issue only) | `verified-against-code` — `coordinator_local.py:2120` vs `coordinator_http.py:416` |

## 5. Services (context for diagnostics consumers)

Registered in `async_setup`, so they exist even with no loaded entry
(`verified-against-code` — `__init__.py:149-167`, `:360-416`).

| Service | Response | Handler |
|---|---|---|
| `refresh_data` | none | `__init__.py:360-416` |
| `reconcile_history` | none | `services.py:async_reconcile_history` |
| `import_historical_data` | `SupportsResponse.OPTIONAL` | `history_import.py` |
| `fetch_events` | `SupportsResponse.ONLY` | `services.py:async_fetch_events` |

`CONFIG_SCHEMA` is `cv.config_entry_only_config_schema(DOMAIN)` — there is no YAML configuration
(`verified-against-code` — `__init__.py:167`). Fifteen translated exception keys exist under
`exceptions` in `strings.json` (`verified-against-code`).

> `refresh_data` forces runtime + energy + battery + parameters and **raises** on
> `parameters_complete=False`. A bare `refresh()` is a cache-respecting no-op that never reads
> params — that was issue #322. Note also that "log and raise" is fiction inside a
> `gather(return_exceptions=True)`. (`verified-against-code` — `__init__.py` → the `refresh_data`
> handler; `asserted-unverified` for the #322 field history.)

## 6. Device-removal observation ledger

`async_remove_config_entry_device` is re-exported from `__init__.py:61-63` and implemented in
`device_removal.py`. Deletion is judged over an **observation ledger**, never over a single cycle.

### 6.1 Windows and classes

| Constant | Value | Meaning | Cite |
|---|---|---|---|
| `DEVICE_ABSENCE_WINDOW` | `15 * 60.0` s (15 min) | Inverters, GridBOSS, parallel groups, station — re-enumerated every healthy cycle, so a short window suffices | `device_removal.py:117` |
| `BATTERY_ABSENCE_WINDOW` | `BATTERY_CARRY_FORWARD_MAX_AGE` = **6 h** | Battery absence is only meaningful past the #258 carry-forward eviction window | `device_removal.py:118` |
| `_LEDGER_PRUNE_AGE` | `4 × BATTERY_ABSENCE_WINDOW` (24 h) | Bounds ledger growth; chosen well beyond both windows so a pruned entry can only ever become a conservative "never seen" one | `device_removal.py:130`, `:393` |

All rows: `verified-against-code`.

### 6.2 What the clock actually measures

> Coverage counts only **complete observed** time — an unbroken run of cycles that observed that
> identifier class **completely**. Neither blind outage time nor a silently-incomplete discovery
> can age an identifier toward deletion.

A clock is reset to `None` whenever the run is broken:

| Reset trigger | Cite |
|---|---|
| The previous cycle failed | `coordinator.py:879-892` |
| The **3-strike cached fallback** served old data (`last_update_success` stays True across a ≤2-strike blip) | `coordinator.py:900-906` |
| This cycle's completeness verdict for that class was not met | `assess_discovery_completeness()`, `coordinator.py:879-892` |

`verified-against-code` — mechanism documented at `device_removal.py:40-60`.

### 6.3 Refusal conditions

| Condition | Behavior | Cite |
|---|---|---|
| No coordinator, or `last_update_success` is False | **Refuse** — no healthy data to judge staleness against; an outage must not make every device look removable | `device_removal.py:424-427` |
| `_consecutive_update_failures != 0` | **Refuse** — a fetch failed this cycle and cached data is being served while `last_update_success` is still True. The table's absences are an outage, not a fresh observation | `device_removal.py:428-433` |
| Identifier never seen this session | Held to the **conservative battery-class window** (6 h) — its class is unknowable | `device_removal.py:58-60` |
| Per-parent battery clocks | One degraded inverter cannot block sibling battery cleanup | `device_removal.py:300-328` |

All rows: `verified-against-code`.

**Cold-start consequence:** battery-class deletions are refused for the first 6 observed *complete*
hours, and device-class for the first 15 observed *complete* minutes. An identifier never seen in a
whole complete observed window is deletable — that is exactly the stale-device case the feature
exists for (the #174 ghost inverter parked disabled after a hardware swap).

### 6.4 Related: setup-time registry pruning is a different mechanism

`_async_cleanup_removed_registry_devices` runs at setup and prunes serial/station trees proven
absent, guarded by a **liveness floor**: zero physical device roots is *not* proof of removal, so
it never prunes in that case (`verified-against-code` — `__init__.py:300-310`, `:1240`).

Do not conflate the two. The ledger governs *user-initiated* per-device deletion; the setup pass
governs orphan cleanup.
