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
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
  - /tmp/llmwiki-research/integration-architecture.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Data semantics — the rules behind this project's repeated regressions

Line numbers pinned to `9f6d6e2`; symbol names are the durable anchor.

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
| 5 | **Freshness must be relative, not absolute.** The supplemental-battery gate counts a transport battery as "surfaced" only if its `last_seen` is within 2 minutes **of the freshest sibling** | Relative ⇒ poll-interval agnostic, needs no clock read, and is shorter than the 5-minute overlay window so cloud data is ready before the overlay switches | `asserted-unverified` — corpus; the 5-min overlay constant is `verified-against-code` (`coordinator_http.py:71`) |
| 6 | **Status codes may be carried forward; measurements may not.** `fault_code` / `warning_code` carry forward across link-down polls (no other source of truth); measurements stay honestly absent | | `asserted-unverified` — corpus rule from #261 |
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
> Evidence: `asserted-unverified` — postmortem #170/#258.

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
> (**closed**). Each direction was chosen so that the *unknown* case does the harmless thing for
> that specific consumer. Do not "unify" them.

### 2.3 `INVERTER_FAMILY_UNKNOWN` is a TRUTHY STRING

```python
# const/device_types.py:48-55
INVERTER_FAMILY_UNKNOWN = "UNKNOWN"
```

| Fact | Evidence |
|---|---|
| The value is the **literal string `"UNKNOWN"`**, not `None` and not an absent key | `verified-against-code` — `const/device_types.py:55` |
| pylxpweb's `InverterFeatures.model_family` defaults to `InverterFamily.UNKNOWN`, and `detect_features()` returns that default **without raising** when the parameter fetch leaves `parameters` unavailable | `verified-against-code` — comment at `const/device_types.py:48-54` |
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
> Final shape: **no gate, no purge.** Blank a cloud-sourced *exact* 0 to `None`, scoped by
> `transport_runtime is not None`.
>
> Evidence: `verified-against-code` — the value-scoped handling at
> `coordinator_mixins.py:2652-2660`. The two-owner observation split is `asserted-unverified`
> (reporter data).

**Two observations do not make a family rule.** Prefer a value-scoped fix over a gate whenever the
evidence is thin, because a wrong purge is irreversible for the user and a wrong gate is not
self-correcting.

### 2.5 Family-scoped register facts

| Fact | Evidence |
|---|---|
| Reg 67 (AC Charge SOC Limit) is **grid-tied-only**; off-grid firmware rejects it | `hardware-proven` (#331 — live `REMOTE_SET_ERROR`) + `portal-correlated` (absent from the off-grid portal page) |
| Regs 160/161 (AC Charge Start/End Battery SOC) are the off-grid equivalents | `portal-correlated` (#331) |
| Off-grid families NAK reg 233 (Quick Charge) entirely → must be cloud-routed | `hardware-proven` (#296/#308 — family-wide ILLEGAL DATA ADDRESS) |
| Off-grid reg 123 is an ARM-local ~1 Hz **counter**; hybrid reg 123 is genuine generator power. Regs 124/125/126 are status bitfields, not energy | `hardware-proven` (#544 — firmware disassembly: one increment site, one memset) |
| Reg 110 green-mode bit is **14**, not 8 | `hardware-proven` (#476 — toggle-proven on 18kPV) |

> **Portal page presence per family is real evidence** for register applicability (#331). It is
> weaker than a hardware toggle but stronger than lineage inference.

## 3. Value scaling: cloud vs local divergence

| Fact | Evidence |
|---|---|
| Local `read_named_parameters` returns the **raw register** (decivolts: reg 228 → `595`). Cloud `read_parameters` returns the **already-scaled value in volts** (`"59.5"`, whole-volt regs as `"40"`) | `hardware-proven` — cross-transport live comparison |
| A blind ÷10 makes the cloud read 10× low → fails the entity range → blank/unavailable | `verified-against-code` — normalization at `number.py:283-294` |
| Normalize **by magnitude** (`value/10 if value >= 100 else value`) for battery-bank voltages: 400–640 decivolts vs 40–64 volts is unambiguous | `verified-against-code` — `number.py:283-294` |
| This trick **cannot** work for PV Start Voltage (90–500 V overlaps the decivolt range) — that needs a mode-aware fix, shipped as `VoltageNumberSpec.decivolt_threshold = 600` | `verified-against-code` — `number.py:2739` (`VoltageNumberSpec`) |
| **The write side is uniform:** raw decivolts (value × 10) for both transports. Only reads need normalization | `verified-against-code` — `number.py:491-536` |
| Cloud **named** writes take engineering units; the raw→string conversion must use the canonical ScaleFactor (`595 → "59.5"`, `%g` format) | `hardware-proven` — established by delta test during the cloud-write repair |
| Unit conventions | energy raw = 0.1 kWh everywhere; power raw = watts; AC/PV charge power regs 66/74 = 100 W units; grid peak shaving reg 206 = 0.1 kW (`hardware-proven`, #328); charge/discharge currents = 0.1 A (`DIV_10`, not `DIV_100`) |

### 3.1 "Two scale tables disagree" is necessary but not sufficient

> The `maxChgCurr` episode: cloud `maxChgCurr` raw 6000 is 0.01 A (→ 60.0 A); Modbus reg 81 raw 600
> is 0.1 A (→ 60.0 A). **Same physical amps, different raw units.** Two independent reviewers called
> it a 10× bug; a prior session had already "fixed" it into a 600 A reading. Only validation against
> real payloads settled it.
>
> **Compare resulting physical values, never scale symbols.**
>
> Evidence: `asserted-unverified` — postmortem; the counter-example (#172, a genuine `DIV_100`
> where `DIV_10` was correct) proves *some* scale disagreements are real.

**Standing rule:** every scaling fix must be validated against a live system (prod HA or real cloud
payloads) before shipping. Unit tests cannot settle a scale question.

## 4. Energy: monotonicity, clamps, and the two consumption meters

### 4.1 NEVER add a reset-to-zero or never-decrease clamp to a `total_increasing` sensor

> An unbounded `if curr < prev: keep prev` clamp at the coordinator layer **pinned daily
> consumption at the running peak and ate every midnight reset** (LOCAL only, because only the
> LOCAL path computes consumption). That is #218/#227.
>
> HA natively treats a >10 % drop as a meter reset. **Trust `total_increasing`.**
>
> Evidence: `asserted-unverified` — postmortem #227; the HA reset semantics are
> `verified-against-code` via the comment at `base_entity.py:302-308`.

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

Evidence: `asserted-unverified` for the per-mode source mapping (corpus); the overlay tables
themselves are `verified-against-code` (`coordinator_mixins.py:408`, `:446`, `:483`).

| Rule | Detail |
|---|---|
| A documented divergence of **~7 %** between a computed value and a counter value is **expected, not a bug** | `asserted-unverified` — corpus |
| **Whole-home LIFETIME consumption must never come from per-inverter `energy_balance`** — it wraps. Sum was 10.6 MWh vs a true 34.71 MWh. Use the cloud group value (CLOUD/HYBRID) or GridBOSS UPS+Load CT totals (LOCAL) | `asserted-unverified` — corpus, explicitly a **reversal** of an earlier conclusion in the same source file. Do not lift the earlier table |
| `hybridPower` has **no Modbus register** — it is cloud-computed and must be derived locally | `portal-correlated` |
| Per-inverter consumption uses `energy_balance`, **not** the Eload register and **not** cloud `totalUsage` | `asserted-unverified` — corpus |

### 4.4 Other energy validation facts

| Fact | Where | Evidence |
|---|---|---|
| Lifetime counters are protected in **pylxpweb** (`validate_energy_monotonicity`), not in the coordinator. Warm-up bypasses the first 2 reads; self-heal accepts a persistent downward drift after 3 rejections / upward after 5 | pylxpweb | `asserted-unverified` — corpus |
| Daily bounds = `rated_power × elapsed × 2`, floored at the 0.1 kWh resolution, with **elapsed measured from the last value change**, not the poll interval — which is why logs show 4.1 s / 17.9 s windows on a 15 s poll | pylxpweb | `asserted-unverified` — corpus |
| **Widening a validation cap requires evidence of a stale source**, not just a large delta. The post-outage lifetime catch-up widening is armed only by `lost` payloads or a link-down transition, never by transient fetch errors; idle devices keep the tight canary | #479 | `portal-correlated` |
| Bank-current canary scales with installation size (150 A/battery, 500 A floor, 2000 A ceiling, with present-battery corroboration) | #367 | `asserted-unverified` — corpus |
| Battery temperature: the **exact** value 127 (0x7F) is a "no reading" sentinel on a no-BMS secondary. Normalize the exact sentinel → `None` on every read path (including the raw cloud property, which bypasses `__post_init__`) — **never widen the >100 °C canary** | #348 | `hardware-proven` — reproduced on the reporter's unit |

## 5. Float tolerance on quantized deltas

> `4.4 - 4.3 == 0.10000000000000053` — it **overshoots** a 0.1 floor.
> `5.1 - 5.0 == 0.09999999999999964` — it does not.

| Consequence | Detail |
|---|---|
| A `delta > floor` comparison on quantized floats **rejects or accepts depending on the base value** | Valid 0.1 kWh daily ticks were rejected (#345/#346) |
| The existing boundary test **passed by luck** — its chosen pair happened not to overshoot | This is why the bug survived |
| Fix | `DELTA_FLOAT_TOLERANCE = 1e-6` |
| Test discipline | Pick test pairs that **actually overshoot**. A boundary test that does not exercise the overshoot proves nothing |

Evidence: `asserted-unverified` — postmortem #345/#346; the IEEE-754 arithmetic is verifiable in
any Python REPL.

**Generalization:** any `delta > floor` or `delta >= floor` comparison over values that arrive
quantized (0.1 kWh, 0.1 A, decivolts) needs an explicit tolerance.

## 6. Battery accumulation: key by SERIAL, distrust reg 96

### 6.1 The protocol ceiling

| Fact | Evidence |
|---|---|
| The inverter dongle Modbus protocol exposes **at most 4 battery slots** (regs 5002–5121 = 120 registers = 4 × 30, read atomically to fit the FC04 125-register PDU limit) | `hardware-proven` — 5- and 6-slot probe reads return EMPTY |
| A "dedicated 5th slot" commit was written, proved wrong, and **reverted** | `hardware-proven` — the refuted read |
| The other community integration (`ant0nkr/luxpower-ha-integration`) reads batteries identically with a hard 4-block ceiling | `asserted-unverified` — cross-integration agreement |
| **The ceiling is the protocol, not the code.** >4 batteries are reachable only via rotation accumulation, cloud backfill, or a direct RS485-to-BMS path | `hardware-proven` |

### 6.2 Register 96 (battery count) is unreliable and ambiguous

| Fact | Evidence |
|---|---|
| A logged `reg 96 = 0` can mean genuine firmware-0 / rotation **or** a dropped read | `hardware-proven` |
| Why: reg 96 lives in the `bms_data` group (80–112), the **only** group allowed to fail non-fatally, while battery voltage/SOC live in `power_energy` (0–31) | `hardware-proven` |
| A bms-only drop therefore yields a **half-empty bank** (SOC valid, count `None`) that overwrites the good cache — whereas a *full* read failure is safe | `hardware-proven` |
| Distinguish by the `bms_data registers unavailable` debug line | `verified-against-code` — pylxpweb debug output |
| Fix: return `battery=None` on a failed/short bms read so callers preserve the last-good cache | `verified-against-code` — pylxpweb |
| In this integration, reg 96 is used **only as a rotation hint** (values > slots-per-page) | `verified-against-code` — `coordinator_local.py:200-201` |
| A momentary reg-96 = 0 under-report is explicitly guarded against | `verified-against-code` — `coordinator_local.py:1485` |

### 6.3 Accumulation rules

| Rule | Evidence |
|---|---|
| **Accumulate by serial, never by slot position** | `verified-against-code` — serial-keyed accumulation in `coordinator_local.py:177-527` |
| Within-page duplicate serials are disambiguated as `{serial}@pos{N}` and re-verified on the next clean read of that position | `verified-against-code` — pylxpweb; consumed at `coordinator_local.py:376-429` |
| **Never diagnose serial collisions from the `Pos N:` debug dump** — it decoded only 14 of the 15 serial characters (the final character is the low byte of offset 24; the high byte is the bank position) | `hardware-proven` — this red herring cost a full investigation |
| Rotation is **firmware-dependent and its trigger is unknown.** One reporter's firmware never rotates (reg 5001 static at 0 across 220 reads) and shows 1 battery by day, 5 at night | `hardware-proven` — reporter capture |
| Diagnostics must log the **RAW physical-slot → identity page** *before* accumulation. The accumulator's own dump is a merged/virtual map and will happily print a frozen value forever | `asserted-unverified` — corpus rule |
| Positional battery retirement/migration is **deliberately conservative**: rotating packs and duplicate serials permanently suppress migration for that inverter *this session*; colliding canonical targets are dropped with a WARNING | `verified-against-code` — `coordinator.py:1441-1551` |

## 7. Parameter cache seeding after writes

| Rule | Detail | Evidence |
|---|---|---|
| After a successful write, **seed the parameter cache with the written value** | Otherwise the entity displays a stale read | `verified-against-code` — `coordinator.py:1110-1144`; router seeding `utils.py:259-267` |
| **Seed unconditionally.** A conditional seed left Quick Charge Duration showing a stale preference whenever the preceding status read had failed | | `asserted-unverified` — postmortem (3.5.0 pre-ship fix) |
| Seeds must live **outside** `self.data` when the store is replaced each cycle | A HYBRID healthy-local parameter refresh **hard-replaces** `data["parameters"][serial]`, wiping cloud-only keys hourly and after every other control write. Hence `CloudParamStoreSpec` stores with their own per-serial/per-field seed registries | `verified-against-code` — `coordinator_mixins.py:303-337`, `coordinator.py:1273-1347` |
| **Per-field** seed timestamps | A later write to one store key must not renew an older key's seed, or an in-flight read of a legitimate portal change gets clobbered | `verified-against-code` — `coordinator.py:1304-1310` |
| A seed may only be superseded when a read **observes a concrete value for that field** (`seed.at <= now AND observed[field] is not None`) — not merely because a read started | Otherwise a partial range-read returning `None` clears the seed and reverts a just-written state. (Found by a post-PR review after two tri-vendor rounds missed it) | `verified-against-code` — `coordinator.py:1273-1347` |
| Seed TTL / confirmed grace | 1800 s / 120 s | `verified-against-code` — `coordinator.py:141`, `:146` |

Write-then-refresh retention semantics and the data-object-identity check live in
[controls-and-writes.md](controls-and-writes.md) §3–4.

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
| This bit **two PRs on the same day** (#378, #380; fix commit `d66cc92`) | `asserted-unverified` — corpus / repo `CLAUDE.md` |
| A later audit (2026-08-02) found **five more sites** (INT-08) | `asserted-unverified` — corpus |
| Regression-test it by patching `monotonic` to a small value | `asserted-unverified` — corpus test recipe |

**Every** monotonic-based throttle, fetch stamp, and poll gate in this codebase must use the
`None` sentinel. Grep for `time.monotonic()` before adding one.

### 8.4 Two sibling throttle traps

| Trap | Failure | Evidence |
|---|---|---|
| A **shared throttle stamp consumed inside a per-item loop** starves every item after the first. With 2+ same-type local devices, only the first was ever polled | Pre-compute one due-decision per cadence class per cycle | `verified-against-code` — `coordinator_local.py:2013-2024`, `coordinator_http.py:151-157` |
| A throttle stamp must record **success**, not attempt — except where the code deliberately stamps on a due cycle regardless of per-device outcome **and** queues the incomplete devices into a retry set with its own floor (#282's shape) | Stamping attempt without a retry set blanks controls for an hour | `verified-against-code` — `coordinator_local.py:2174-2202` |

## 9. Cloud payload robustness

| Rule | Evidence |
|---|---|
| **Any cloud live-measurement field must be Optional.** Any device can go offline and return a partial payload; a required field turns that into a total entity blackout (#256) | `hardware-proven` — reproduced |
| This class has recurred **at least three times**: `InverterRuntime`/`BatteryInfo` (#256); `UserVisitRecord` on login (#258 — the cloud reports a parallel GROUP as the "last visited device", omitting ten fields declared required, breaking ~96 % of logins for that account); the firmware `UpdateStatus` enum missing `WAITING` (#353) | `hardware-proven` |
| **Any vendor enum needs an unknown-value fallback** (`_missing_`) | `verified-against-code` — pylxpweb firmware enums |
| **A silent `except` on a fetch hides the whole class.** `_fetch_runtime_http` swallowed every exception at DEBUG while `_fetch_battery_http` already split `ValidationError` → WARNING. That diagnostic gap made #348 take three wrong hypotheses | `asserted-unverified` — postmortem |
| **Fake-confident zeros are their own family** (#490 internal temperature, #497 known-state, #514 capacity percent): the cloud returns a structurally valid 0 for a field it cannot compute. **Detect by contradiction with a live sibling value** (capacity 0 while SOC is 52), then derive or blank — do not trust the 0 | `hardware-proven` (#514, reporter-confirmed pattern) |
| A truthiness check on a schema-shaped result is **not** a reachability check. Store getters returning truthy all-`None` schema dicts on total failure hid failures inside normal returns, so the breaker never opened (#511/#516). **Only a non-`None` value proves reachability** (`False`/`0` count) | `verified-against-code` — breaker at `coordinator_mixins.py:173-174` |
| `0 if 0 else None` — **falsy-vs-absent confusion in a merge is a whole bug class.** `inv if inv else bms` turned a healthy 0 into `None` (#261) | `asserted-unverified` — postmortem |

## 10. What "verified" means for a register claim

Use this hierarchy when annotating any new mapping. It exists because **`# verified` in a register
table has historically meant "the names matched", not "a toggle was observed"** — the false
annotation on reg 110 bit 8 caused #476, and the same conflation was re-committed *in the comment
documenting the fix*.

| Grade | Meaning |
|---|---|
| 1. **toggle-proven** | A live named-control/UI action correlated to raw before/after values **on the target family**, with restoration |
| 2. canonical + independent capture | A canonical pylxpweb definition **plus** an independent hardware capture |
| 3. canonical alone | Read-only diagnostics only — never a write path |
| 4. vendor/third-party table | A family-specific **hypothesis**, nothing more |

Evidence: `asserted-unverified` — the hierarchy is a corpus audit product; the #476 falsification is
`hardware-proven`.

> **The contract harness is valuable but NOT independent.** It resolves against the same pylxpweb
> tables, so it catches internal drift but **cannot prove an address is correct on hardware**.
> (`verified-against-code` — `tests/test_register_contract_harness.py` resolves against pylxpweb.)

> **A wrong-but-writable bit is firmware-ACKed.** No exception, no cloud fallback, no log above
> DEBUG — and readback cannot catch it, because writing bit 14 sets bit 14 and reads back True
> whether or not the feature moved. **Gating is the only mitigation** for an unproven bit mapping.
> (`hardware-proven` — #476.)

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
| 12 | Any new register claim carries its evidence grade, and no write ships on grade 3 or 4 |
