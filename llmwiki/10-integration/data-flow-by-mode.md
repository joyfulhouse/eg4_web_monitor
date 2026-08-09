---
canonical-for:
  - HTTP / LOCAL / HYBRID data flow end to end
  - the fact that HYBRID is not a third code path
  - poll intervals, throttles, cache TTLs
  - LOCAL static first-refresh phase
sources:
  - custom_components/eg4_web_monitor/coordinator_http.py
  - custom_components/eg4_web_monitor/coordinator_local.py
  - custom_components/eg4_web_monitor/coordinator.py
  - custom_components/eg4_web_monitor/const/config_keys.py
  - /tmp/llmwiki-research/integration-architecture.md
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Data flow by connection mode

Line numbers pinned to `9f6d6e2`; symbol names are the durable anchor.

## 0. Read this first: HYBRID is not a third code path

| Claim | Evidence |
|---|---|
| `_async_update_hybrid_data` **calls `_async_update_http_data`** and then overrides `data["connection_type"] = CONNECTION_TYPE_HYBRID` | `verified-against-code` — `coordinator_http.py:342-418` (the delegation is at `:366-369`) |
| Local transports are attached to the pylxpweb `Station`; **pylxpweb** then routes runtime/energy locally and battery data via the cloud | `verified-against-code` — `_attach_local_transports_to_station`, `coordinator_local.py:2545` |
| HYBRID therefore inherits every HTTP-path behavior — station refresh, endpoint serialization, battery carry-forward, error taxonomy — unless it explicitly overrides it | `verified-against-code` — `coordinator_http.py:342-418` |
| HYBRID lives in `coordinator_http.py`, **not** in `coordinator_local.py` | `verified-against-code` — file location |

**Consequences an agent must internalize:**

1. A bug reported "only in HYBRID" is usually an HTTP-path bug plus a local-overlay interaction —
   read `_async_update_http_data` first.
2. A fix applied to the LOCAL path does **not** reach HYBRID. This is the shape of the HYBRID
   GridBOSS energy-divergence bug: the CT overlay was fixed in LOCAL and missed in HTTP
   (`asserted-unverified` — recorded in the notes corpus as a structural hazard; the general rule
   below is what matters).
3. **When fixing anything mode-specific, grep for the sibling path.** Parallel-group construction
   exists in three places (`coordinator_http`, `coordinator_local` static, `coordinator_local`
   runtime), and `apply_gridboss_overlay()` is shared but called from three unrelated lifecycle
   points (`inferred` from the module inventory; treat as a search obligation, not a fact).

## 1. Mode derivation

| has_cloud | has_local | `connection_type` |
|---|---|---|
| yes | yes | `hybrid` |
| yes | no | `http` |
| no | yes/no | `local` |

Evidence: `verified-against-code` — `_config_flow/__init__.py:113-120`. `_has_cloud = bool(username
and plant_id)`; `_has_local = bool(local_transports)` (`:189-197`).

The mode is **never** selected by the user. It is recomputed whenever the entry is built or updated.

## 2. HTTP / cloud mode

Entry point: `_async_update_http_data` (`coordinator_http.py:420-596`). Evidence throughout:
`verified-against-code`.

| Phase | Behavior | Cite |
|---|---|---|
| First cycle | `Station.load(client, int(plant_id))` → `station.refresh_all_data()` → `_rebuild_inverter_cache()` → `_align_client_cache_with_http_interval()` | `:459-472` |
| Later cycles | `_refresh_station_devices()` | `:197-340` |
| Client cache alignment | TTLs for `battery_info`, `midbox_runtime`, `quick_charge_status`, `inverter_runtime`, `inverter_energy`, `parameter_read` are set to the HTTP polling interval | `:114-133` |
| DST | Portal DST sync near the top of the hour, when enabled | `:526-527`, `coordinator_mixins.py:4544-4562` |
| Publish | `_process_station_data()` builds the published dict | `:724` |
| Errors | → `ConfigEntryAuthFailed` / `UpdateFailed`, each flipping `_last_available_state` once with a WARNING (Silver-tier logging requirement) | `:554-596` |
| Labels | `connection_type = "http"`; per-device `connection_transport = "Cloud"` | `:531-539` |

`Station.id` is an **int** in production — string/int confusion here caused the multi-station
onboarding bug #275 (`verified-against-code` — noted in `tests/conftest.py:347-380` docstring).

## 3. LOCAL mode

Entry point: `_async_update_local_data` (`coordinator_local.py:1946-2221`). Evidence throughout:
`verified-against-code`.

### 3.1 The static first refresh — zero Modbus reads, by design

| Fact | Evidence |
|---|---|
| On the first refresh only, `_build_static_local_data()` returns **every sensor key with value `None`**, derived purely from config-entry metadata — **zero Modbus reads** | `verified-against-code` — `coordinator_local.py:1969-1985`; builder at `:1774-1871` |
| Purpose: entities get created inside HA's setup timeout | `verified-against-code` — comment at `:1969-1971` |
| The phase is one-shot, gated by `_local_static_phase_done` | `verified-against-code` — `coordinator_local.py:1971` |
| It schedules an immediate follow-up `async_request_refresh()` as a tracked background task; Phase 2 populates real data | `verified-against-code` — `coordinator_local.py:1978-1985` |
| Features on this path come from `_features_from_family()` — without it, BOTH split-phase and three-phase sensors get created | `verified-against-code` — `coordinator_mappings.py:1935` |

**Why the phase exists.** Multiple devices on one Modbus gateway meant 60+ sequential reads on
first setup, which exceeded HA's ~90 s setup timeout; the resulting `CancelledError` left the
connection dirty (issue #83). The steady-state read budget is ~23 Modbus transactions per inverter
per refresh — roughly 7 input reads (including one atomic 120-register battery read), ~8 holding
params, ~8 coordinator reads (`asserted-unverified` — budget figure is from the notes corpus, not
re-counted at `9f6d6e2`; the timeout hazard itself is `verified-against-code` via the static-phase
comment).

> Do **not** "optimize" the static phase away by making the first refresh read registers. That is
> the exact regression #83 documents.

### 3.2 Phase 2+ steady state

| Step | Behavior | Cite |
|---|---|---|
| Pre-populate | `processed` is seeded from `self.data` so interval-skipped transports retain values | `:1998-2002` |
| Poll decisions | Per-gate poll decisions computed **once per tick** | `:2013-2024` |
| Parameters | Inclusion/retry decided for the whole cycle | `:2029-2051` |
| Grouping | Configs grouped by physical endpoint; groups polled concurrently, members **sequentially** | `:2075-2115` |
| Link state | `_sync_transport_link_state(processed)` marks link-down devices with `error` and syncs Repairs **before** the all-failed check | `:2120` |
| All failed | Error-mark carried-forward parallel groups, then raise `UpdateFailed` | `:2139-2140` |
| Parameter bookkeeping | A due cycle stamps the hourly throttle **regardless of per-device outcome**, and queues any inverter that did not complete into `_param_retry_pending` | `:2174-2202` |
| Deferred load | After the first successful refresh, a background `_deferred_local_parameter_load()` loads parameters + feature detection, so controls appear on a later cycle | `:2208-2219` |

> **Serial-bus devices must refresh sequentially.** Concurrent frames on one RS485 adapter
> interleave and corrupt (#233). The endpoint grouping is what enforces this, and it avoids the
> bogus `":0"` endpoint collapse (`verified-against-code` — `coordinator_http.py:249-256`,
> `transport_serialization.py:physical_endpoint_key`).

## 4. HYBRID mode

Entry point: `_async_update_hybrid_data` (`coordinator_http.py:342-418`). Evidence throughout:
`verified-against-code`.

| Concern | Behavior | Cite |
|---|---|---|
| Core | Delegates to `_async_update_http_data(include_mid_refresh=include_mid)`, then relabels | `:366-369` |
| MID/GridBOSS gating | `_should_poll_hybrid_local()` gates MID refresh on the **dongle** interval, evaluating every gate **eagerly** so all monotonic stamps advance | `:135-168`, `:151-157` |
| Degraded-MID escalation | A failed attach **or** `transport_link_down` escalates `include_mid`, so the MID's cloud fallback is not throttled to the dongle window | `:353-366` |
| Per-device label | `Hybrid (<label>)`, or `Hybrid (<label> — link down)`, or `"Cloud"` when no transport | `:398-413` |
| Link state | `_sync_transport_link_state(None)` — Repairs issues only, **no `error` key**, because cloud fallback is still serving data | `:416`; contract at `coordinator_local.py:2885-2911` |
| Attach retry | `_ensure_local_transports()` retries whole-attach and per-serial failures, bounded by `ATTACH_RETRY_INTERVAL_SECONDS = 60.0` | `:170-195`, `coordinator_local.py:153` |
| Degraded cache busting | `_maybe_bust_degraded_cloud_cache()` busts per-device cloud caches for degraded devices, throttled per serial to the HTTP interval | `:74-108` |

> **The HYBRID first refresh must not force a Modbus read.** Python 3.11's `asyncio.wait_for()`
> does not interrupt an in-flight pymodbus read; a stale RS485 bus can block 3–5 minutes and take
> the whole setup with it. The first regular poll (~5 s later) populates `_transport_runtime` once
> the bus clears. Evidence: `asserted-unverified` — recorded in the notes corpus as a design
> constraint; the HYBRID path's reliance on the HTTP first cycle is `verified-against-code`
> (`coordinator_http.py:366-369`).

### 4.1 Why HYBRID omits the `error` key but LOCAL sets it

| Mode | `_sync_transport_link_state` argument | `error` key set? | Rationale |
|---|---|---|---|
| LOCAL | `processed` | **Yes** | No other source of truth — a link-down device's measurements are genuinely gone |
| HYBRID | `None` | **No** | Cloud fallback is still serving data; marking `error` would flip healthy measurement entities unavailable |

Evidence: `verified-against-code` — `coordinator_local.py:2120` (LOCAL) vs
`coordinator_http.py:416` (HYBRID); contract documented at `coordinator_local.py:2885-2911`.

## 5. Transport-exclusive and cloud-only data

Both statements below are `asserted-unverified` at the field level (lifted from the notes corpus,
not re-derived from the overlay tables at `9f6d6e2`) but the **mechanism** is
`verified-against-code`: the overlay tables `_TRANSPORT_OVERLAY` and `_ENERGY_OVERLAY` exist at
`coordinator_mixins.py:446` / `:483` and are asserted by `tests/test_register_contract_harness.py`.

| Class | Fields |
|---|---|
| Modbus-only, overlaid onto cloud data when a local transport is attached | `bt_temperature` (reg 108), `grid_current_l1/l2/l3`, `battery_current`, `total_load_power`, `grid_voltage_l1/l2`, `eps_voltage_l1/l2`, `load_power` (reg 170), `fault_code`/`warning_code` (regs 60-63 — the cloud has **no** fault field at all). GridBOSS smart-port currents (I18-25) are Modbus-only too |
| Cloud-only, no local equivalent | Station/plant-level entities; `smart_load_power` / `grid_load_power` / `eps_load_power` (the backup-output split, `EG4_OFFGRID`-only); `bms_model`; PV1-3 yield via chart side-fetch; and decisively **whole-home lifetime consumption**, because per-inverter `energy_balance` wraps |

**Founding principle:** *the cloud is not a separate data source.* The EG4 cloud relays the same
Modbus register values the dongle reads, or computes a derivation from them. When a cloud field
looks "missing", trace it to its register before calling it cloud-only. `cloud_api_field=None` on a
register means the cloud does not carry that field — not that the data is unavailable.
(`asserted-unverified` — corpus principle; it has held across every investigation recorded there.)

## 6. Intervals, throttles and caches

All rows `verified-against-code`.

| Thing | Value | Cite |
|---|---|---|
| HTTP polling default / min / max | 120 / 60 / 600 s | `const/config_keys.py:152-154` |
| Legacy HTTP sensor interval default | 90 s | `const/config_keys.py:126-127` |
| Modbus default / min / max | 5 / 3 / 300 s | `const/config_keys.py:142,146-147` |
| Dongle default / min / max | 30 / 5 / 300 s | `const/config_keys.py:143,148-149` |
| Parameter refresh default / min / max | 60 / 5 / 1440 min | `const/config_keys.py:130,138-139` |
| Coordinator tick | HTTP: the HTTP interval. LOCAL/HYBRID: the **fastest** configured transport interval. MODBUS/DONGLE-only: its own interval | `coordinator.py:707-722` |
| Per-transport poll gate | monotonic stamps, **`None` sentinel** for "never ran" | `coordinator.py:678-686`, `:1414-1439` |
| Modbus TCP and serial share ONE gate key | `_poll_gate_key()` normalizes both to `"modbus"` | `coordinator.py:1401-1412` |
| Parameter retry floor | 2 min | `coordinator_mixins.py:371` |
| Battery carry-forward eviction | 6 h | `coordinator_mixins.py:382` |
| HYBRID transport battery freshness | 5 min | `coordinator_http.py:71` |
| Quick-charge cloud status timeout | 10 s | `coordinator_mixins.py:91` |
| Firmware / battery-backup cloud timeouts | 10 s each; backup fetch every 30 s | `coordinator_mixins.py:96-98` |
| Event-log fetch / timeout | 300 s / 10 s | `coordinator_mixins.py:105,111` |
| PV-string daily / lifetime fetch | 300 s / 3600 s | `coordinator_mixins.py:117-118` |
| Cloud param store fetch / timeout / retry floor | 300 / 30 / 120 s | `coordinator_mixins.py:130,134,143` |
| Side-fetch breaker | 3 consecutive connectivity failures → 300 s skip | `coordinator_mixins.py:173-174` |
| Parameter write seed TTL / confirmed grace | 1800 s / 120 s | `coordinator.py:141,146` |
| Optimistic retention TTL | 300 s (**numerically equal** to `QUICK_CHARGE_OPTIMISTIC_TTL`) | `base_entity.py:63`, `switch.py:447` |
| Cloud request budget | semaphore of 3, shared per `(username, base_url, verify_ssl)` | `coordinator.py:766-769` |
| Per-device mapping/side-fetch semaphore | 3 | `coordinator.py:641` |
| Modbus block-size presets | conservative 40 / fast 120 registers | `const/config_keys.py:58-65` |
| Local transport attach retry | 60 s | `coordinator_local.py:153` |

### 6.1 Two poll-gate rules that have each caused a shipped bug

| Rule | Failure mode if broken | Evidence |
|---|---|---|
| Evaluate **every** gate eagerly, even after an earlier gate already returned True | Stable-order starvation: later transports never advance their stamp and never poll | `verified-against-code` — `coordinator_http.py:151-157`; LOCAL equivalent `poll_gates_seen` at `coordinator_local.py:2013-2024` |
| Ask the gate **once** for the normalized key, then apply that decision to both concrete Modbus types in the same tick | Mixed TCP + serial: the later type starves every cycle | `verified-against-code` — `coordinator.py:1401-1412` |

Related and equally load-bearing: a shared throttle stamp consumed inside a per-device loop starves
every device after the first. With 2+ same-type local devices, only the first was ever polled
(`asserted-unverified` — postmortem "per-transport interval" in the corpus; the current
pre-compute-once shape is `verified-against-code` at `coordinator_local.py:2013-2024`).

See also the `time.monotonic()` fresh-boot trap in [data-semantics.md](data-semantics.md) — the
`None` sentinel in the table above is not stylistic.

## 7. Where staleness / carry-forward logic lives

| Concern | Location | Evidence |
|---|---|---|
| Battery carry-forward (HYBRID/CLOUD baseline rebuild) | `coordinator_http.py:598-696`; state in `coordinator.py:613` | `verified-against-code` |
| LOCAL round-robin battery accumulation + aged eviction | `coordinator_local.py:177-527` | `verified-against-code` |
| Parameter sticky carry-forward + per-device retry queue | `coordinator_local.py:2029-2051`, `:2167-2202`; `coordinator_mixins.py:4473-4538` | `verified-against-code` |
| Acknowledged-write seeds (parameter cache) | `coordinator.py:1110-1249` | `verified-against-code` |
| Cloud-param-store seeds surviving a `self.data` swap | `coordinator.py:1273-1347`, `coordinator_mixins.py:2051-2110` | `verified-against-code` |
| Quick-charge / event / PV-string / store carry-forward | `coordinator_mixins.py:1410-1552`, `:2063-2118` | `verified-against-code` |
| "Cloud lost" blanking sets | `coordinator_mappings.py:273-382` | `verified-against-code` |
| Optimistic retention (entity level) | `base_entity.py:741-961` | `verified-against-code` |

The **rules** governing all of the above are in [data-semantics.md](data-semantics.md). This table
is only the map.

## 8. Mode-parity expectations for validation sweeps

| Expectation | Status |
|---|---|
| `hybrid ⊇ cloud` exactly | `asserted-unverified` — validation-sweep convention from the corpus |
| `local − cloud` = the documented cloud-only set (§5) | `asserted-unverified` — same |
| Compare **registries by unique_id, not states** | `asserted-unverified` — a states-only comparison produces 35–40 false "missing" entries from slug drift (`grid_boss` vs `gridboss`, `output_power` vs `power_output`) and from enablement differences |

Entity **counts** per mode are deliberately omitted here: six documents in the corpus give six
different numbers, each a snapshot of a different version, and several state them as standing
facts. Do not quote a mode entity count without a version stamp.
