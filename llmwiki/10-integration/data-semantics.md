---
canonical-for:
  - staleness, carry-forward and eviction rules
  - capability gating by inverter_family (never by model-name substring)
  - INVERTER_FAMILY_UNKNOWN as a truthy string
  - energy monotonicity, consumption vs load, the total_increasing clamp ban
  - float tolerance on quantized deltas
  - battery accumulation keyed by serial; reg 96 unreliability
  - parameter cache seeding after writes
  - the time.monotonic() fresh-boot throttle trap
sources:
  - custom_components/eg4_web_monitor/utils.py
  - custom_components/eg4_web_monitor/sensor.py
  - custom_components/eg4_web_monitor/const/device_types.py
  - custom_components/eg4_web_monitor/coordinator.py
  - custom_components/eg4_web_monitor/coordinator_local.py
  - custom_components/eg4_web_monitor/coordinator_http.py
  - custom_components/eg4_web_monitor/coordinator_mixins.py
  - custom_components/eg4_web_monitor/base_entity.py
  - pylxpweb src/pylxpweb/transports/data.py
  - memory/issue-227-consumption-no-reset-local-clamp.md
  - memory/issue-258-battery-rr-reg96-unreliable.md
  - memory/issue-258-beta18-carry-forward.md
  - memory/issue-259-control-gate-family-aware.md
  - memory/issue-346-daily-energy-float-boundary.md
  - memory/issue-348-one-inverter-all-unknown.md
  - memory/issue-479-cloud-lost-freeze.md
  - memory/issue-514-capacity-percent-fake-zero.md
  - memory/issue-544-generator-power-offgrid.md
  - memory/voltage-param-scaling-cloud-vs-local.md
  - memory/consumption-energy-sources.md
  - memory/queue-cleanup-2026-07-26.md
  - eg4_web_monitor issues #170, #256, #258, #261, #300, #367, #378, #380, #490, #511, #516
  - https://github.com/joyfulhouse/eg4_web_monitor/pull/569
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/570
verified-against:
  # Page verified at 9f6d6e2; the off-grid write-routing sections (H161,
  # Quick Charge/H233) were falsified by PR #569 and re-verified at e9853eb
  # for the #570 sweep ingest — those sections carry their pin inline.
  # Claims describing the PR #600 change set itself (the sweep-extended
  # protected set, the quick-charge fail-closed predicates, the schedule
  # and QuickChargeDuration family gates) are reproducible from PR #600
  # (the durable artifact — its change-set diff survives branch deletion;
  # embedded SHAs staled twice, the r5/r6 LOWs). REQUIRED POST-MERGE
  # ACTION (recorded in log.md): re-pin to the mainline merge SHA at the
  # release cut (#559 precedent).
  eg4_web_monitor: "9f6d6e2 + PR #600 (change-set claims; re-pin to the merge SHA at the release cut)"
  pylxpweb: 204b95d
last-verified: 2026-08-29
see-also:
  - ../40-hardware/registers.md
  - ../60-history/open-contradictions.md
  - ../60-history/superseded-claims.md
---

# Data semantics — the rules behind this project's repeated regressions

Line numbers are pinned per repo by the `verified-against:` mapping above — `9f6d6e2` for
`eg4_web_monitor`, `204b95d` for `pylxpweb`. Each citation names its repo where it is not this one.
Symbol names are the durable anchor.

**Read this page before changing anything that touches sensor values, entity lifetimes, or
capability gates.** Every section below corresponds to a defect class that has shipped more than
once. Several of them are *irreversible for the user* when they go wrong — a wrong purge deletes
entities and the customizations attached to them.

## 1. Staleness, carry-forward and eviction

### 1.1 The rules

| # | Rule | Rationale | Evidence |
|---|---|---|---|
| 1 | **Once published, never silently dropped.** `_apply_battery_carry_forward()` keeps a battery in the dict once it has been published | A cloud payload that momentarily omits or re-keys a battery must not vanish its entities | `verified-against-code` — `coordinator_http.py:598-696` |
| 2 | **Staleness is expressed as data, not as availability.** Carried entries keep their **old** `battery_last_seen` | The consumer can see the entry is stale; the entity does not flap | `verified-against-code` — same |
| 3 | **Bound every never-evict rule.** LOCAL keeps a 6 h eviction bound so a physically removed pack converges without a restart | `BATTERY_CARRY_FORWARD_MAX_AGE = timedelta(hours=6)` | `verified-against-code` — `coordinator_mixins.py:382`; enforced at `coordinator_local.py:492-524` |
| 4 | **Eviction must run unconditionally per merge**, not only on empty polls | The original eviction was gated on an empty poll and was therefore **unreachable** on non-empty polls — a removed pack stayed frozen until restart (#300) | `verified-against-code` — `coordinator_local.py:479-488` ("Age-based eviction must run on every merge, not only on empty…") |
| 5 | **Freshness must be relative, not absolute.** The supplemental-battery gate counts a transport battery as "surfaced" only if its `last_seen` is within a short window **of the freshest sibling** | Relative ⇒ poll-interval agnostic, needs no clock read, and is shorter than the transport-freshness overlay window so cloud data is ready before the overlay switches | `verified-against-code` — `coordinator_http.py` → the supplemental-battery gate and the transport-freshness constant |
| 6 | **Status codes may be carried forward; measurements may not.** `fault_code` / `warning_code` carry forward across link-down polls (no other source of truth); measurements stay honestly absent | | `verified-against-code` — the fault/warning carry-forward in `coordinator_mixins.py`; `asserted-unverified` (`memory/issue-261-hybrid-sensor-flicker.md`) for the rule's origin |
| 7 | **Cloud freshness must be gated on the portal's own `lost` verdict.** A `lost:true` payload still returns `success:true` with the last register mirror — indistinguishable from live data unless you read the flag | This is #479 | `portal-correlated` — verified against live portal payloads during #479 |
| 8 | Parameter/param-cache carry-forward: a single failed range read must **not** blank parameter-backed controls for an hour. Sticky carry-forward + a **2-minute retry floor** + a per-device retry set, at both the integration and library layers | This is #282 | `verified-against-code` — retry floor `coordinator_mixins.py:371`; retry set `coordinator_local.py:2174-2202` |

### 1.2 The meta-rule: independent staleness heuristics fight each other

> **Contradictory assumptions compound.** The never-evict accumulator assumes "seen once ⇒
> reappears" — true for rotating firmware, **false** for non-rotating firmware. Combined with the
> supplemental gate and the freshness overlay, a battery's *single* local appearance poisoned it:
> the cached entry made the gate believe all batteries were surfaced, so the cloud refresh that had
> been keeping it alive switched off.
>
> **When adding a staleness rule, enumerate what the other rules already assume.**
>
> Evidence: `asserted-unverified` — `memory/issue-258-battery-rr-reg96-unreliable.md`.

### 1.3 Never blank by dropping keys

Because availability semantics differ per base class (see
[entities-identity-availability.md](entities-identity-availability.md) §2), *how* you express
"no value" changes the entity state:

| Technique | Result on `EG4BaseSensor` | Result on `EG4BatteryBankEntity` |
|---|---|---|
| Drop the key | unknown | **unavailable** ← flicker |
| **Extract-then-null** (key present, value `None`) | unknown | unknown |

**Always extract-then-null.** #479's blanking used a keep-set and nulled at 4 levels for exactly
this reason. Evidence: `verified-against-code` — `coordinator_mappings.py:273-382`
(`LOST_KEEP_SENSOR_KEYS`, `LOST_KEEP_BATTERY_KEYS`, `CLOUD_SUPPLEMENTAL_LOST_KEYS`).

### 1.4 Carry-forward guard list

| Guard | Why | Evidence |
|---|---|---|
| Exclude legacy **migration aliases** from carry-forward | Otherwise a migration is blocked by "legacy key still active" | `verified-against-code` — `coordinator_http.py:598-696` |
| **Supersede** a cached key whose serial is republished under a new key | Prevents a duplicate identity surviving a re-key | `verified-against-code` — same |
| LOCAL rr-cache uses the **same 6 h bound**, with authoritative retirement | Symmetry with the cloud path | `verified-against-code` — `coordinator_local.py:492-524`, `:1494-1497` |

## 2. Capability gating: family, never model-name substring

### 2.1 The rule

> **Gate capability on the detected `inverter_family`. Never on a model-name substring alone.**

Gating on `model.lower()` substrings produced **zero** control entities for an `"SNA-US 15K"`
(a 15 kW EG4_OFFGRID unit, device type code 54) — while an `"SNA-US 12K"` matched by accident on
`"12k"` and a `"12000XP"` matched on `"xp"`. That is issue #259.

Evidence: `verified-against-code` — `is_supported_control_model` docstring and body,
`utils.py:273-296`. The fix is a family **backstop**: substring match **OR**
`features["inverter_family"] in CONTROL_CAPABLE_FAMILIES`.

### 2.2 The gate inventory

| Gate | Semantics | Fails… | Cite |
|---|---|---|---|
| `is_supported_control_model()` | model substring in `SUPPORTED_INVERTER_MODELS` **OR** family in `CONTROL_CAPABLE_FAMILIES` | open | `utils.py:273-296` |
| `is_offgrid_family()` | `family == EG4_OFFGRID` | **open** (False when unknown) — so family-based suppression never removes entities from unidentified hardware | `utils.py:340-348` |
| `is_hybrid_family()` | `family == EG4_HYBRID` | **closed** (False when unknown) — Generator/Off-Grid/Peak-Shaving schedules were verified on EG4_HYBRID hardware and are only created there | `utils.py:351-359` |
| `is_family_control_supported()` | per-family `FUNC_` blocklist (`FAMILY_UNSUPPORTED_CONTROL_PARAMS`) | open | `utils.py:165-182`, map at `:156-162` |
| `supports_grid_sellback()` | family → `MODEL_NAME_FAMILY_FALLBACK` → `\d+XP\b` regex; defaults True | open | `utils.py:306-337`, regex `:303` |
| `_supports_eps_battery_backup()` | features → `supports_off_grid`; else model-string `"xp" not in model` | — | `switch.py:92-124` |
| `_schedule_supported()` | `ScheduleTimeSpec.gate` ∈ `control` / `control_grid_tied` / `offgrid` / `hybrid` / `hybrid_or_offgrid` | per gate | `time.py:82-113` |
| `is_control_active()` | regime-gated (SOC vs Voltage) number entities | — | `const/device_types.py:369-382` |

All rows: `verified-against-code`.

> Note the deliberate asymmetry between `is_offgrid_family` (**open**) and `is_hybrid_family`
> (**closed**). Each direction was chosen so that the *unknown* case does the least-damaging thing
> for that specific consumer — for suppression gates, not deleting a working entity. Do not
> "unify" them.

> **Fail-open has a safety cost, and it compounds with §2.3.** The control gates fail open by
> design: `is_family_control_supported`'s own docstring says "a device whose family is missing or
> unknown keeps every control". Combine that with `INVERTER_FAMILY_UNKNOWN` being a truthy string
> (§2.3) and the consequence is that **the control surface is widest exactly where family
> identification is weakest** — an unidentified device gets every control, including ones whose
> register mapping was only ever proven on a different family.
>
> That is the right trade for *entity deletion*, which is irreversible for the user. It is not a
> safety property for *writes*. **Never reason "the family gate would have caught it"** — for an
> unresolved family the gate catches nothing. Whether a given write is reachable is answered by
> the entity and its routing, not by a family gate; see
> [controls-and-writes.md §0](controls-and-writes.md#0-the-write-surface-is-not-reliably-enumerable-from-documentation).
>
> `verified-against-code` — `utils.py` → `is_family_control_supported`, `is_offgrid_family`, and
> their docstrings; `const/device_types.py` → `INVERTER_FAMILY_UNKNOWN`.

### 2.3 `INVERTER_FAMILY_UNKNOWN` is a TRUTHY STRING

```python
# const/device_types.py:48-55
INVERTER_FAMILY_UNKNOWN = "UNKNOWN"
```

| Fact | Evidence |
|---|---|
| The value is the **literal string `"UNKNOWN"`**, not `None` and not an absent key | `verified-against-code` — `const/device_types.py:55` |
| pylxpweb's `InverterFeatures.model_family` defaults to `InverterFamily.UNKNOWN`, and `detect_features()` returns that default **without raising** when the parameter fetch leaves `parameters` unavailable | `verified-against-code` at pylxpweb `204b95d` — the dataclass default `model_family: InverterFamily = InverterFamily.UNKNOWN` (`devices/inverters/_features.py:537`) and the detection path's own `UNKNOWN` seed (`devices/inverters/base.py:460`). The eg4 comment at `const/device_types.py:48-54` records the same, but is prose |
| So this truthy string is what the pipeline actually emits for a device whose family could not be determined | `verified-against-code` — same |
| `if features.get("inverter_family"):` is therefore **True** for an unresolved device | `verified-against-code` — Python truthiness of a non-empty string |

#### Why mishandling it irreversibly deletes entities

A gate written as `family != EG4_OFFGRID` treats `"UNKNOWN"` as "definitely not off-grid" and
creates (or, worse, a purge treats it as "definitely is X" and **deletes**) entities on the very
hardware the gate exists to protect. Deletion takes the user's customizations — name, area, icon,
dashboard references, automations — with it, and there is no undo.

**One transient parameter-read failure is enough to produce `"UNKNOWN"`.**

The correct posture, as implemented for the #544 inverse gate:

```python
# sensor.py:122-133 — OFFGRID_EXCLUDED_SENSORS
family = (features or {}).get("inverter_family")
if not family or family == INVERTER_FAMILY_UNKNOWN:
    _LOGGER.debug("Deferring %s: inverter family unresolved (%s); ...", ...)
    return False              # fail CLOSED — create nothing
return bool(family != INVERTER_FAMILY_EG4_OFFGRID)
```

Evidence: `verified-against-code` — `sensor.py:106-133`.

**Failing closed costs nothing permanent**, and this is the part that makes it safe: a key filtered
here stays eligible for late registration, and `_async_discover_device_sensors` re-evaluates
`_should_create_sensor` with fresh features on **every changed cycle**, so a genuine
`EG4_HYBRID` sensor appears as soon as its family resolves (`verified-against-code` — comment at
`sensor.py:117-121`).

> **The late-registration path had its own bug.** Seeding `known_device_sensor_keys` from *all*
> present keys marked filtered keys as "known" forever, stranding them until a manual reload
> (#243). **Seed only with keys that actually passed `_should_create_sensor` and created an
> entity.** Evidence: `verified-against-code` — `sensor.py:413-427`.

### 2.4 But family is not always the right grain either

> **#490 is the cautionary tale.** The internal-temperature-zero defect **splits within device type
> code 54**: a 6000XP owner reports live values while 12000XPs report 0 — and 6000XP is classified
> `EG4_OFFGRID`. A family gate would have permanently deleted a working sensor along with the
> user's customizations.
>
> Final shape: **no gate, no purge.** An *exact* 0 in `internal_temperature` /
> `battery_temperature` / `bt_temperature` is blanked to `None` on every path (CLOUD, HYBRID,
> LOCAL), and only when at least one radiator reading is strictly `> 0` °C — cold-consistent
> (`<= 0`) or absent radiators publish the 0. #560 falsified the original cloud-only shape
> (transport-backed values served the same constant 0) and warmth-narrowed the predicate.
>
> Evidence: `verified-against-code` — `blank_constant_zero_temperatures` in
> `coordinator_mappings.py`, verified at `500f5ed` (the #560 fix branch; supersedes the
> cloud-only handling this page originally cited at this page's pin). The two-owner
> observation split is `asserted-unverified` (reporter data).

**Two observations do not make a family rule.** Prefer a value-scoped fix over a gate whenever the
evidence is thin, because a wrong purge is irreversible for the user and a wrong gate is not
self-correcting.

### 2.5 Family-scoped register behaviour

**Register ground truth is owned by
[../40-hardware/registers.md](../40-hardware/registers.md), including its evidence grades.** This
page does not restate register semantics and must never state a register claim more broadly, or at
a higher grade, than the canonical ledger does.

Each row below pairs an *integration consequence* — what this code must do — with the register
claim it rests on. **The Grade column is echoed from the owning ledger row, not assigned here.**
If an echoed grade disagrees with the ledger, the ledger is right and this table is stale.

| Integration consequence | Register claim, and its scope as the owner states it | Grade (echoed from owner) |
|---|---|---|
| AC Charge SOC Limit is gated off `EG4_OFFGRID` with a one-shot Repairs issue | H67 is the AC-charge stop SOC on **grid-tied only**; off-grid rejects the control | `portal-correlated` — [H67 row](../40-hardware/registers.md) |
| AC Charge Start Battery SOC exists as the off-grid equivalent | H160, AC-charge start SOC, off-grid plus hybrid read scope | `portal-correlated` — [H160 row](../40-hardware/registers.md) |
| AC Charge End Battery SOC is created on `EG4_OFFGRID`; since PR #569 its write is **routed cloud-only** there and on unresolved families (pure-LOCAL raises) — see the routing note below | H161 mapping is `firmware-proven` on the decoded CEAA/CCAA images (#570); **LOCAL writability is still unresolved** — no live off-grid write exists, and both tested grid-tied hybrids are inert. The owner says explicitly: do not treat H161 as a safe local write | Owner rows: [H161](../40-hardware/registers.md); conflict preserved as [C6/C7](../60-history/open-contradictions.md) |
| Quick Charge status **and** control are cloud-routed on off-grid families; since PR #569 the switch **fails closed** — pure-LOCAL off-grid/unresolved entries get an unavailable switch instead of the doomed local H233 write; see the note below | H233 is rejected on the decoded CEAA image (`firmware-proven`, jump H229→H234 → ILLEGAL DATA ADDRESS); CCAA implements the address but has **no traced bit-0 consumer**; the live #296/#308 rejection reports remain `asserted-unverified` (no preserved capture) | Owner rows: [H233 off-grid access boundary](../40-hardware/registers.md#h233-off-grid-access-boundary) |
| Generator Power and its two siblings are suppressed on `EG4_OFFGRID` (purged, with a Repairs issue) and kept on `EG4_HYBRID` | The owner splits I123 **by decoded image, not by family**: on the decoded 12000XP off-grid image it is an ARM-initialization counter, not generator power; on the decoded 18kPV/FlexBOSS hybrid image it is genuine GEN-port power; on **6000XP the meaning is unresolved** with no validated image | `firmware-proven` (12000XP off-grid), `firmware-proven` (hybrid), `asserted-unverified` (6000XP) — [I123 rows](../40-hardware/registers.md) |
| The Off-Grid/green switch writes bit 14 of H110 | H110 b14 is Green/Off-Grid Mode on the **tested 18kPV hybrid unit**; for 12000XP/6000XP it is a layout inference awaiting a family-specific capture. H110 b8 is **UNKNOWN** and was the wrong bit (#476) | `hardware-toggle-proven` (tested 18kPV), `lineage-inferred` (12000XP/6000XP) — [H110 rows](../40-hardware/registers.md); refutation recorded as **S2** in [../60-history/superseded-claims.md](../60-history/superseded-claims.md) |

Grades for the **left** column — that these gates, purges and routings exist in this code — are
`verified-against-code`: `sensor.py` → `_should_create_sensor`, `utils.py` →
`flag_offgrid_control_suppression`, plus the control platforms `switch.py`, `number.py`, `time.py`.

> ### ⚠ H161 routing: cloud-only since PR #569 — but the gate is a list, not a mechanism
>
> **A register the ledger marks "writability unresolved" is not thereby un-writable in this code.**
> Those are independent facts: the ledger records what has been *proven about the hardware*, the
> router decides what the integration *attempts*. Nothing links them — there is STILL no mechanism
> by which a ledger grade suppresses a write. What changed is that a **hand-maintained gate** now
> exists for the number platform's scalar registers.
>
> **What actually ships** (since PR #569, merged 2026-08-13; extended by the #570 evidence sweep;
> `verified-against-code` at `e9853eb` for the #569 half, this change set for the extension):
>
> | Step | Site |
> |---|---|
> | `ACChargeEndBatterySOCNumber` passes `local_write_blocked_reason` from `_offgrid_cloud_only_reason` | `number.py` → `ACChargeEndBatterySOCNumber.async_set_native_value` |
> | The gate FAILS CLOSED: EG4_OFFGRID, a missing family, and UNKNOWN all block the local path; only a positively resolved non-off-grid family keeps local-first | `number.py` → `_offgrid_cloud_only_reason`, `utils.py` → `is_positively_non_offgrid_family` |
> | With the reason set, the router never attempts the local write; it goes cloud, or raises a clear error on a pure-LOCAL install | `utils.py` → `async_write_with_cloud_fallback` |
> | The #570 sweep extended the same gate to **every** scalar register the number platform can write on a possibly-off-grid unit: the off-grid-created set (74, 101, 102, 105, 125, 202, 227, 228, 169, 100, 22 — alongside the original 66, 158–161) plus, after review round 5, the fail-open-created grid-tied scalars reachable before family resolution (67, 82, 83, 103, 116; the RAW 117 write is refused outright — no cloud path exists) and the schedule time entities' packed `write_register` path in `time.py` | `number.py` — derivation recorded in `_offgrid_cloud_only_reason`'s docstring |
>
> **Limits of the gate — do not read more into it than it is.** (1) It is a curated per-entity
> list; a new entity gets no protection automatically, and no lint compares the list against the
> ledger. (2) Bit-level switch/select writes (H110/H179 bits, H179 b9/b10 regime selects, H20)
> and direct `inverter.<method>()` calls remain outside it — their per-bit risk stays recorded
> in the keeper and [C7](../60-history/open-contradictions.md) — with one exception: the grid
> peak-shaving direct call (H206) is family-gated at its entity since round 6, because
> pylxpweb's method is transport-first (an earlier "cloud-only by construction" claim the
> pinned wheel falsified). Since round 5 the schedule time
> entities' packed `write_register` path carries an equivalent inline fail-closed gate in
> `time.py`, and the Quick Charge Duration live reg-234 adjust carries its own at the entity
> (#570 adversarial round 1: on off-grid the live-active check is cloud-routed per #296, so no
> local H233 rejection ever gated that write). (3) On resolved non-off-grid
> families the local-first write still runs on mappings whose proof is scoped to one or two
> tested units. **The readback still does not cover any of this** — storage and transport only,
> the #476 mechanism.
>
> **Status:** the off-grid local-write exposure that #558 filed is discharged by routing; the
> underlying writability question stays OPEN as **C6/C7**. History (pre-#569 local-first
> exposure) is preserved in C7's entry, not here.
>
> **H161 is not the only register in this shape, and this page does not enumerate the others.**
> That set is not a list anyone maintains — it is a consequence of tables in the code. README owns
> both halves and this page restates neither:
>
> | What you want | Where it lives |
> |---|---|
> | How to **derive** the current local-write surface | [README → the rule is not enforced anywhere in the code](../README.md#the-rule-is-not-enforced-anywhere-in-the-code) |
> | The narrower set where **the keeper itself** marks writability or family scope unresolved | [README → registers the keeper marks unresolved](../README.md#registers-the-keeper-marks-unresolved) |
>
> Run the derivation rather than reading the tables as complete. **A register's absence from
> README's table is not a clearance** — it means only that the keeper has not flagged it, and
> README says so in terms.

> **Do not infer a gate from a weak grade.** H161 is one instance of a general fact: a
> `lineage-inferred`, `asserted-unverified` or scope-unresolved grade in the ledger does not close
> a write path, and nothing in the code consults the grade. Whether a register is reachable is
> answered by the entity and its write routing — see
> [controls-and-writes.md §0](controls-and-writes.md#0-the-write-surface-is-not-reliably-enumerable-from-documentation) for the procedure
> that derives the routing, and the README table above for the register-side criterion.

> **The off-grid Quick Charge scope gap is closed (PR #569, merged 2026-08-13).**
>
> | Fact | Grade |
> |---|---|
> | With a cloud client, off-grid AND unresolved families go cloud-direct: `_prefers_cloud_control` is `not is_positively_non_offgrid_family(...) and has_http_api()` (#570 audit review round 4, this change set — the earlier positive-off-grid-only gate left unresolved families on pylxpweb's local-first path, unsafe on CCAA where the H233 write is silently accepted) | part of the PR #600 change set — `switch.py` → `EG4QuickChargeSwitch._prefers_cloud_control` |
> | Without a cloud client the switch **fails closed**: only a positively resolved non-off-grid family keeps the local H233 route; off-grid/unresolved entries get an unavailable switch, and a forced service call raises before pylxpweb is reached | `verified-against-code` at `e9853eb` — `switch.py` → `_offgrid_without_cloud` availability gate and `is_positively_non_offgrid_family` |
> | The firmware basis is lineage-scoped: CEAA rejects the H233 address outright; CCAA implements it but no bit-0 quick-charge consumer was traced — neither lineage has a proven local route | grades owned by the [H233 off-grid access boundary](../40-hardware/registers.md#h233-off-grid-access-boundary) |
>
> The pre-#569 exposure — pure-LOCAL off-grid attempting the firmware-rejected write — is
> history; it is preserved in the keeper's boundary section and
> [controls-and-writes.md §2.4](controls-and-writes.md#24-the-h233-exposure-this-makes-visible).

> **The H233 rejection is a tested-scope observation, not a family property.**
> "Returns ILLEGAL DATA ADDRESS on the off-grid units we tested" and "no off-grid inverter has this
> register" are different claims, and only the first has ever been observed here. The distinction is
> binding under README's negative-claims rule. The integration's response — routing Quick Charge via
> the cloud on off-grid families — is deliberately *broader* than the evidence, because the cost of
> over-routing is a slower control path while the cost of under-routing is a control that silently
> fails on unsurveyed hardware. Widening the **claim** to match the gate would be the error.
> Both the [H233 off-grid access boundary row](../40-hardware/registers.md#h233-off-grid-access-boundary)
> and [bug-postmortems #296/#308](../60-history/bug-postmortems.md) carry the observation and its
> missing capture; the register row now carries the address **and** the rejection together, so cite
> it first.

> **Portal page presence per family is evidence** for register applicability — weaker than a
> hardware toggle, stronger than lineage inference. The ordering is defined in
> [../README.md](../README.md#evidence-grade-legend); this page does not restate it.

## 3. Value scaling: cloud vs local divergence

| Fact | Evidence |
|---|---|
| Local `read_named_parameters` returns the **raw register** (decivolts) while cloud `read_parameters` returns the **already-scaled value in volts** — the same reading, two representations | The **transformation** is `verified-against-code` (the local read path returns the register word; the cloud path returns a scaled string). The **agreement** between the two — a live read of reg 228 giving `595` locally and `"59.5"` from the portal — is `portal-correlated` (`memory/voltage-param-scaling-cloud-vs-local.md`). This is one reading seen twice, **not** a before/after pair, so it does not meet the `hardware-proven` bar |
| A blind ÷10 makes the cloud read 10× low → fails the entity range → blank/unavailable | `verified-against-code` — normalization at `number.py:283-294` |
| Normalize **by magnitude** (`value/10 if value >= 100 else value`) for battery-bank voltages: 400–640 decivolts vs 40–64 volts is unambiguous | `verified-against-code` — `number.py:283-294` |
| This trick **cannot** work for PV Start Voltage (90–500 V overlaps the decivolt range) — that needs a mode-aware fix, shipped as `VoltageNumberSpec.decivolt_threshold = 600` | `verified-against-code` — `number.py:2739` (`VoltageNumberSpec`) |
| **The write side is uniform:** raw decivolts (value × 10) for both transports. Only reads need normalization | `verified-against-code` — `number.py:491-536` |
| Cloud **named** writes take engineering units; the raw→string conversion must use the canonical ScaleFactor (`%g` format) | The conversion is `verified-against-code` (pylxpweb's named-write path applies the ScaleFactor). That a write→readback→restore delta test succeeded is `verified-against-code` for the **code path**; that the write reached the intended physical setting is `asserted-unverified` — a readback confirms storage and transport, never the physical semantic (`memory/cloud-raw-register-write-broken.md`) |
| Unit conventions per register (energy resolution, power units, charge-power units, current scaling) | **Owned by [../40-hardware/registers.md](../40-hardware/registers.md)**, which grades each register individually — several energy rows there are `lineage-inferred`, not proven. Do not summarise them as a single "everywhere" rule |

### 3.1 Compare physical values, never scale symbols

**Rule:** two scale tables disagreeing on the *symbol* is not evidence of a bug. Convert both to
the physical quantity first; if they agree, there is nothing to fix. Different raw units producing
the same amps, volts, or kWh is normal across the cloud and Modbus paths.

The worked case — cloud `maxChgCurr` versus Modbus register 81, where two independent reviewers
called a 10× bug that did not exist and a prior session had already "fixed" it into a wrong reading
— is recorded as **S7** in
[../60-history/superseded-claims.md](../60-history/superseded-claims.md). The genuine
counter-example (a real scale mismatch, #172) is recorded there too. Read both before acting on any
scale report.

**Standing rule:** every scaling fix must be validated against a live system — production HA or
real cloud payloads — before shipping. Unit tests cannot settle a scale question, because they
encode the same assumption they are meant to test.
(`asserted-unverified` — `memory/feedback_empirical-register-validation.md`.)

## 4. Energy: monotonicity, clamps, and the two consumption meters

### 4.1 NEVER add a reset-to-zero or never-decrease clamp to a `total_increasing` sensor

> An unbounded `if curr < prev: keep prev` clamp at the coordinator layer **pinned daily
> consumption at the running peak and ate every midnight reset** (LOCAL only, because only the
> LOCAL path computes consumption). That is #218/#227.
>
> HA natively treats a >10 % drop as a meter reset. **Trust `total_increasing`.**
>
> Evidence: `asserted-unverified` — `memory/issue-227-consumption-no-reset-local-clamp.md` for the
> field symptom; the Home Assistant reset semantics and the current threshold are
> `verified-against-code` (`base_entity.py` → `_guard_total_increasing` and its comment).

### 4.2 The sanctioned alternative

`_guard_total_increasing` at the **entity** layer: pin dips **≤10 %** to the prior high-water mark;
let >10 % drops through unchanged.

| Property | Detail | Cite |
|---|---|---|
| Threshold | `_RESET_DETECTION_THRESHOLD = 0.9` — matches HA recorder's own reset threshold | `base_entity.py:309` |
| Why bounded | Sub-10 % dips are virtually always cloud rounding noise (e.g. `consumption_lifetime` stepping 2917.1 → 2917.0), which produce recorder "state is not strictly increasing" warnings | `base_entity.py:302-308` |
| Why >10 % passes | Midnight rollover, inverter replacement, lifetime counter wrap are all genuine | `base_entity.py:305-308` |
| Non-numeric / `None` / non-`total_increasing` | Returned untouched; cache not updated | `base_entity.py:314-329` |

All rows: `verified-against-code`.

> **Ship both halves.** Removing the coordinator clamp *without* adding the bounded entity guard
> re-surfaces the recorder warnings from 0.1 kWh rounding jitter.

### 4.3 Consumption and load are two distinct meters

| Concept | CLOUD | LOCAL / HYBRID | Authoritative when a GridBOSS is present |
|---|---|---|---|
| `consumption` / `consumption_lifetime` | cloud `todayUsage` (server-computed) | `_energy_balance()` = yield + discharge + grid_import − charge − grid_export | the **parallel-GROUP** value via the GridBOSS CT overlay |
| `load_power` | — | reg 170, Modbus-only | — |
| `total_load_power` | — | Modbus-only | — |

Evidence: `asserted-unverified` for the per-mode source mapping
(`memory/consumption-energy-sources.md`); the overlay tables themselves are
`verified-against-code` (`coordinator_mixins.py` → `_GRIDBOSS_PG_OVERLAY`, `_TRANSPORT_OVERLAY`,
`_ENERGY_OVERLAY`).

| Claim | Grade |
|---|---|
| A divergence of roughly 7 % between a computed value and a counter value is **expected, not a bug** | `asserted-unverified` — `memory/consumption-energy-sources.md` |
| `hybridPower` has **no Modbus register** — it is cloud-computed and must be derived locally | `portal-correlated` — `memory/consumption-energy-sources.md`; register absence is owned by [../40-hardware/registers.md](../40-hardware/registers.md) |
| Per-inverter consumption is computed from `energy_balance`, not from the Eload register and not from cloud `totalUsage` | `verified-against-code` (`coordinator_mixins.py` → the consumption computation) for what the code does; `asserted-unverified` for whether that is the right source |

#### The lifetime-consumption source is CONTESTED — no binding rule here

`memory/consumption-energy-sources.md` contains **both** of these, sequenced by date and never
reconciled:

| Position | Text |
|---|---|
| Earlier | Whole-home consumption ≈ cloud GROUP `todayUsage`, "so `energy_balance` for the GROUP is right" |
| Later | "`energy_balance` is unusable for LIFETIME consumption. Sum 10.6 MWh vs true 34.71 MWh" — lifetime must come from the cloud group (CLOUD/HYBRID) or GridBOSS UPS+Load CT totals (LOCAL) |

This is **C4** in
[../60-history/open-contradictions.md](../60-history/open-contradictions.md#c4--consumption-source-an-early-conclusion-was-reversed-and-both-texts-still-read-as-current),
status **UNRESOLVED**. Neither position is adopted here: issuing the later one as a "must never"
imperative would resolve the contradiction by fiat, which the conventions forbid.

What is safe to act on today:

| Statement | Grade |
|---|---|
| The two positions exist and disagree | `asserted-unverified` — both appear in `memory/consumption-energy-sources.md`. An observation about what a **prose** file says is never a code grade, however directly it can be read off the page |
| The later position carries a concrete arithmetic discrepancy (10.6 MWh vs 34.71 MWh) that the earlier one does not address | `asserted-unverified` — `memory/consumption-energy-sources.md` |
| The same file separately retracts its own older table for using a lifetime register with slave counter-drift | `asserted-unverified` — same file |
| Therefore: **do not lift the earlier table**, and **do not ship a lifetime-source change** on the strength of either position until C4 is adjudicated | `inferred` — from the two rows above |

### 4.4 Other energy validation facts

| Fact | Where | Evidence |
|---|---|---|
| Lifetime counters are protected in **pylxpweb** (`validate_energy_monotonicity`), not in the coordinator. Warm-up bypasses the first reads; self-heal accepts a persistent drift after a bounded number of rejections | pylxpweb `validation.py` | `verified-against-code` (pylxpweb → `validate_energy_monotonicity`) for the mechanism; `asserted-unverified` (`memory/data-validation-architecture.md`) for the specific counts, not re-read here |
| Daily bounds scale with rated power and **elapsed measured from the last value change**, not from the poll interval — which is why logs show sub-poll-interval windows | pylxpweb `validation.py` | `asserted-unverified` — `memory/data-validation-architecture.md` |
| **Widening a validation cap requires evidence of a stale source**, not just a large delta. The post-outage lifetime catch-up widening is armed only by `lost` payloads or a link-down transition, never by transient fetch errors; idle devices keep the tight canary | #479 | `portal-correlated` — the `lost` flag is a portal field; `memory/issue-479-cloud-lost-freeze.md` |
| Battery temperature has a "no reading" sentinel that must be normalised to `None` on **every** read path, including the raw cloud property that bypasses `__post_init__` — and the temperature canary must **not** be widened to accommodate it | #348 | The sentinel value and its register are owned by [../40-hardware/registers.md](../40-hardware/registers.md) (I67 rows) — read the grade there. The integration-side rule is `verified-against-code` (pylxpweb normalises on all read paths; the canary is unchanged) |

#### Bank-current canary thresholds (owned by this page)

The corrupt-read guard on aggregate battery-bank current is **not** a flat cap: a flat cap falsely
rejected a large bank's genuine solar-noon charging current, staling the bank sensors exactly at
peak (#367).

| Element | Value | Grade |
|---|---|---|
| Per-battery allowance | 150 A | `verified-against-code` — pylxpweb `transports/data.py` → `BatteryBankData.is_corrupt`, `max_amps = min(max(500.0, count * 150.0), 2000.0)` |
| Floor | 500 A | `verified-against-code` — same expression |
| Ceiling | 2000 A | `verified-against-code` — same expression; the comment derives it as the 20-battery count canary × a 100 A-class physical max |
| Count used | `max(battery_count, batteries actually present in this read)` | `verified-against-code` — same method. Register 96 alone is not trusted: it shares the BMS block with the current register, so a correlated desync can garble both, and it under-reports on some rotating firmware |
| Rationale for a ceiling at all | Keeps the canonical corrupt value rejected even when a garbled-but-plausible count inflates the scaled cap | `verified-against-code` — the method's own comment |
| Sibling canaries | Per-battery current bound, per-battery SOC/SOH bounds, and a battery-count bound, all in the same module | `verified-against-code` — pylxpweb `transports/data.py` → the per-battery and bank `is_corrupt` methods |

**Rule:** a canary threshold must scale with the installation. A constant that is correct for a
4-battery bank rejects real data on a 9-battery bank.

## 5. Float tolerance on quantized deltas

> `4.4 - 4.3 == 0.10000000000000053` — it **overshoots** a 0.1 floor.
> `5.1 - 5.0 == 0.09999999999999964` — it does not.

| Consequence | Detail |
|---|---|
| A `delta > floor` comparison on quantized floats **rejects or accepts depending on the base value** | Valid 0.1 kWh daily ticks were rejected (#345/#346) |
| The existing boundary test **passed by luck** — its chosen pair happened not to overshoot | This is why the bug survived |
| Fix | `DELTA_FLOAT_TOLERANCE = 1e-6` |
| Test discipline | Pick test pairs that **actually overshoot**. A boundary test that does not exercise the overshoot proves nothing |

Evidence: `asserted-unverified` — `memory/issue-346-daily-energy-float-boundary.md` for the field
case; the IEEE-754 arithmetic is `verified-against-code` (reproducible in any Python REPL).

**Generalization:** any `delta > floor` or `delta >= floor` comparison over values that arrive
quantized (0.1 kWh, 0.1 A, decivolts) needs an explicit tolerance.

## 6. Battery accumulation: key by SERIAL, distrust reg 96

### 6.1 The protocol ceiling belongs to the hardware chapter

The dongle Modbus window's **four-slot battery ceiling** — the register block, its extent, and the
evidence for it — is owned by
[../40-hardware/registers.md](../40-hardware/registers.md#individual-battery-extended-input-ledger).
The refuted "fifth slot" is recorded as **S6** in
[../60-history/superseded-claims.md](../60-history/superseded-claims.md). Read the grade there;
this page does not restate it and must not out-grade it.

What this page owns is the **behavioural consequence** for the integration:

| Consequence | Grade |
|---|---|
| Banks larger than the readable window are reachable only via rotation accumulation, cloud backfill, or another transport — never by widening the read | `inferred` — from the ceiling fact owned by `40-hardware/registers.md` |
| Therefore the accumulator keys on **serial** and does not evict on a short page (§6.3) | `verified-against-code` (`coordinator_local.py` → `_merge_round_robin_batteries`) |
| Therefore eviction must be **age-bounded rather than absence-triggered**, or a rotating bank evicts itself every poll (§1.1 rule 4) | `verified-against-code` (`coordinator_local.py` → `_evict_aged_rr_batteries`) |
| A proposal to "read the 5th slot" is a refuted design, not a feature request | see S6 in `60-history/superseded-claims.md` |

### 6.2 Register 96 (battery count) is unreliable and ambiguous

| Claim | Grade |
|---|---|
| A logged `reg 96 = 0` is **ambiguous**: it can mean a genuine firmware zero / rotation state, or a dropped read | `inferred` — from the two structural facts below plus field reports in `memory/issue-258-battery-rr-reg96-unreliable.md` |
| Register 96 is decoded from the `bms_data` register group, which is the **only** group allowed to fail non-fatally, while battery voltage/SOC come from the `power_energy` group | `verified-against-code` — pylxpweb `transports/data.py`, group definitions and the non-fatal `bms_data` branch |
| A bms-only drop therefore yields a **half-empty bank** (SOC valid, count `None`) that can overwrite a good cache, whereas a *full* read failure is safe | `verified-against-code` — pylxpweb read path; the asymmetry follows from the group split above |
| Distinguish the two by the `bms_data registers unavailable` debug line | `verified-against-code` — pylxpweb debug logging |
| Fix: return `battery=None` on a failed/short bms read so callers preserve the last-good cache | `verified-against-code` — pylxpweb read path |
| In this integration, reg 96 is used **only as a rotation hint** (values greater than slots-per-page) | `verified-against-code` — `coordinator_local.py` → `_merge_round_robin_batteries` docstring and body |
| A momentary reg-96 = 0 under-report is explicitly guarded against | `verified-against-code` — `coordinator_local.py`, the battery-bank creation guard |
| The bank-current canary deliberately takes `max(reg 96, batteries present in this read)` for the same reason | `verified-against-code` — pylxpweb `transports/data.py` → `BatteryBankData.is_corrupt` (§4.4) |

### 6.3 Accumulation rules

| Rule | Grade |
|---|---|
| **Accumulate by serial, never by slot position** | `verified-against-code` — serial-keyed accumulation in `coordinator_local.py` → `_merge_round_robin_batteries` |
| Within-page duplicate serials are disambiguated as `{serial}@pos{N}` and re-verified on the next clean read of that position | `verified-against-code` — pylxpweb; consumed in `coordinator_local.py` → the rr-cache merge |
| **Do not diagnose serial collisions from the `Pos N:` debug dump without checking its width first.** A truncated dump printing 14 of the 15 serial characters makes distinct packs look identical | `verified-against-code` — pylxpweb now prints the full serial; `asserted-unverified` (`memory/issue-258-battery-rr-reg96-unreliable.md`) for the truncated-dump episode |
| Rotation is **firmware-dependent and its trigger is unknown.** At least one reporter's firmware never rotates and shows a different battery count by day and by night | `asserted-unverified` — reporter capture recorded in `memory/issue-258-battery-rr-reg96-unreliable.md`; the raw page-by-page capture is not reproduced here |
| Diagnostics must log the **RAW physical-slot → identity page** *before* accumulation. The accumulator's own dump is a merged/virtual map and will print a frozen value indefinitely | `asserted-unverified` — `memory/issue-258-battery-rr-reg96-unreliable.md` |
| Positional battery retirement/migration is **deliberately conservative**: rotating packs and duplicate serials suppress migration for that inverter for the session; colliding canonical targets are dropped with a WARNING | `verified-against-code` — `coordinator.py` → the positional-retirement helpers |

## 7. Parameter cache seeding after writes

| Rule | Detail | Evidence |
|---|---|---|
| After a successful write, **seed the parameter cache with the written value** | Otherwise the entity displays a stale read | `verified-against-code` — `coordinator.py:1110-1144`; router seeding `utils.py:259-267` |
| **Seed unconditionally** — never gate the seed on the success of a preceding read | A conditional seed leaves the entity showing a stale value whenever the read that would have refreshed it failed, which is exactly when the seed is needed | `verified-against-code` — the seed is unconditional in `coordinator.py`; `asserted-unverified` (repo `CHANGELOG.md`, v3.5.0) for the Quick Charge Duration field symptom |
| Seeds must live **outside** `self.data` when the store is replaced each cycle | A HYBRID healthy-local parameter refresh **hard-replaces** `data["parameters"][serial]`, wiping cloud-only keys hourly and after every other control write. Hence `CloudParamStoreSpec` stores with their own per-serial/per-field seed registries | `verified-against-code` — `coordinator_mixins.py:303-337`, `coordinator.py:1273-1347` |
| **Per-field** seed timestamps | A later write to one store key must not renew an older key's seed, or an in-flight read of a legitimate portal change gets clobbered | `verified-against-code` — `coordinator.py:1304-1310` |
| A seed may only be superseded when a read **observes a concrete value for that field** (`seed.at <= now AND observed[field] is not None`) — not merely because a read started | Otherwise a partial range-read returning `None` clears the seed and reverts a just-written state | `verified-against-code` — `coordinator.py` → the seed-supersede predicate |
| A seed expires on its own TTL, with a shorter grace window once the write is confirmed | Bounds how long an acknowledged write can override a genuine read. Values live in `coordinator.py` — read them there rather than copying them | `verified-against-code` — `coordinator.py` → the write-seed TTL and confirmed-grace constants |

Write-then-refresh retention semantics and the data-object-identity check live in
[controls-and-writes.md](controls-and-writes.md) §4–5.

## 8. The `time.monotonic()` fresh-boot throttle trap

### 8.1 The trap

`time.monotonic()` on Linux is **host uptime**. A throttle written as:

```python
if now - last.get(key, 0.0) < INTERVAL:   # ← WRONG
    return False
```

reports "throttled" for the **first-ever call** on any host whose uptime is below `INTERVAL` —
which is **every CI runner**, and real production for `INTERVAL` seconds after a HAOS host reboot.
The work then **silently never fires**.

### 8.2 The fix

Use a **`None` sentinel**. Throttle only when a previous stamp exists.

```python
# coordinator.py:678-686
# Per-transport last-poll timestamps (monotonic).  ``None`` means the
# transport gate has never fired; a numeric zero is not a safe sentinel
# because monotonic time is host uptime and may still be below the poll
# interval immediately after boot.
self._last_modbus_poll: float | None = None
self._last_dongle_poll: float | None = None
```

```python
# coordinator.py:1435-1439
if last_poll is not None and now - last_poll < interval:
    return False
setattr(self, ts_attr, now)
return True
```

Evidence: `verified-against-code` — `coordinator.py:678-686`, `:1414-1439`; `_should_poll_transport`
docstring explicitly says *"Returns True on the first call (timestamp is `None`), including
immediately after a fresh host boot."*

### 8.3 History and scope

| Fact | Evidence |
|---|---|
| It bit two PRs on the same day, #378 and #380 | `asserted-unverified` — PRs #378/#380 and fix commit `d66cc92`; the commit is the durable artifact, and neither it nor the PRs were re-read here |
| A 2026-08-02 audit found further sites (finding INT-08) | `asserted-unverified` — `docs/audits/2026-08-02-register-race-performance-audit.md` |
| Regression-test it by patching `monotonic` to a small value, simulating a freshly booted host | `verified-against-code` — this is the shape the existing throttle tests use |

**Every** monotonic-based throttle, fetch stamp, and poll gate in this codebase must use the
`None` sentinel. Grep for `time.monotonic()` before adding one.

### 8.4 Two sibling throttle traps

| Trap | Failure | Evidence |
|---|---|---|
| A **shared throttle stamp consumed inside a per-item loop** starves every item after the first. With 2+ same-type local devices, only the first was ever polled | Pre-compute one due-decision per cadence class per cycle | `verified-against-code` — `coordinator_local.py:2013-2024`, `coordinator_http.py:151-157` |
| A throttle stamp must record **success**, not attempt — except where the code deliberately stamps on a due cycle regardless of per-device outcome **and** queues the incomplete devices into a retry set with its own floor (#282's shape) | Stamping attempt without a retry set blanks controls for an hour | `verified-against-code` — `coordinator_local.py:2174-2202` |

## 9. Cloud payload robustness

These are **cloud/portal** behaviours. None of them is a hardware observation, so none carries a
hardware grade.

| Rule | Grade |
|---|---|
| **Any cloud live-measurement field must be Optional.** A device that goes offline returns a partial payload; a required field turns that into a total entity blackout (#256) | `portal-correlated` — the partial payload came from the live portal; `memory/issue-256-offline-inverter-blackout.md`. The fix is `verified-against-code` (pylxpweb models declare the omittable live fields Optional) |
| This class has recurred at least three times: `InverterRuntime`/`BatteryInfo` (#256); `UserVisitRecord` on login (#258 — the portal reports a parallel GROUP as the "last visited device", omitting fields declared required, which broke logins for that account); the firmware `UpdateStatus` enum missing `WAITING` (#353) | `portal-correlated` — all three are portal-payload shapes; `memory/issue-258-battery-rr-reg96-unreliable.md`, `memory/issue-353-firmware-status-round2.md` |
| **Any vendor enum needs an unknown-value fallback** (`_missing_`) | `verified-against-code` — pylxpweb firmware enums implement it |
| **A silent `except` on a fetch hides the whole class.** One HTTP fetch swallowed every exception at DEBUG while its sibling already split `ValidationError` → WARNING; that diagnostic gap sent #348 down three wrong hypotheses | `verified-against-code` for the asymmetry between the two fetch helpers; `asserted-unverified` (`memory/issue-348-one-inverter-all-unknown.md`) for the investigation cost |
| **Fake-confident zeros are their own family** (#490 internal temperature, #497 known-state, #514 capacity percent): the cloud returns a structurally valid 0 for a field it cannot compute. **Detect by contradiction with a live sibling value** (capacity 0 while SOC is non-zero), then derive or blank — do not trust the 0 | `portal-correlated` — the zeros are cloud-payload values contradicted by live sibling fields in the same payload; `memory/issue-514-capacity-percent-fake-zero.md` |
| A truthiness check on a schema-shaped result is **not** a reachability check. Store getters returning truthy all-`None` schema dicts on total failure hid failures inside normal returns, so the breaker never opened (#511/#516). **Only a non-`None` value proves reachability** (`False`/`0` count) | `verified-against-code` — `coordinator_mixins.py` → `_breakered_cloud_call` and the store getters |
| `0 if 0 else None` — **falsy-vs-absent confusion in a merge is a whole bug class.** A merge written `inv if inv else bms` turned a healthy 0 into `None` (#261) | `asserted-unverified` — `memory/issue-261-hybrid-sensor-flicker.md` |

## 10. Grading a new register claim

The evidence-grade legend — including the **register-annotation refinement** (toggle-proven >
canonical definition plus an independent capture > canonical definition alone > vendor table) — is
defined once, in [../README.md](../README.md#evidence-grade-legend). This page does not define a
vocabulary. Use README's, and record register claims themselves in
[../40-hardware/registers.md](../40-hardware/registers.md).

Two consequences that bite integration code specifically:

> **The contract harness is valuable but NOT independent.** It resolves against the same pylxpweb
> tables the runtime uses, so it catches internal drift but **cannot prove an address is correct on
> hardware**. A green harness is not evidence for a register mapping.
> (`verified-against-code` — `tests/test_register_contract_harness.py` resolves against pylxpweb.)

> **A wrong-but-writable bit is firmware-ACKed.** No exception, no cloud fallback, no log above
> DEBUG — and readback cannot catch it, because writing a bit sets that bit and reads back true
> whether or not the feature moved. **Gating is the only mitigation** for an unproven bit mapping.
> The falsification case is **S2** in
> [../60-history/superseded-claims.md](../60-history/superseded-claims.md); read the grade there.

## 11. Quick regression checklist

Before shipping a change in this area, confirm each line:

| # | Check |
|---|---|
| 1 | No new `0.0` default in a `time.monotonic()` throttle — use `None` |
| 2 | No key **dropped** to express "no value" — extract-then-null |
| 3 | No capability gate keyed on a model-name substring alone |
| 4 | Every family gate handles the literal `"UNKNOWN"` explicitly, and chooses fail-open vs fail-closed deliberately |
| 5 | No reset-to-zero / never-decrease clamp added at the coordinator layer for a `total_increasing` sensor |
| 6 | Every `delta > floor` on quantized values carries a tolerance |
| 7 | Battery data keyed by **serial**, and reg 96 used only as a hint |
| 8 | Every write path that can land via cloud also seeds the parameter cache |
| 9 | Every never-evict rule has a bound, and eviction runs unconditionally per merge |
| 10 | New staleness rules checked against what the existing three already assume |
| 11 | The **sibling mode path** grepped and fixed too (HTTP vs LOCAL vs the HYBRID delegate) |
| 12 | Any new register claim is recorded in `40-hardware/registers.md` with a grade from README's legend, and no local write ships on a bit mapping weaker than toggle-proven without a gate |
