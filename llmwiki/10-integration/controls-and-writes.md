---
canonical-for:
  - the known control-write shapes, the derivation, and its proven blind spots
  - async_write_with_cloud_fallback write routing
  - _execute_switch_action, where pylxpweb chooses the transport
  - local-vs-cloud write decision, incl. link-down short-circuit
  - optimistic state, retention, and the 300s TTL coupling
  - post-write refresh judged by data-object identity
  - control write error surfacing
sources:
  - custom_components/eg4_web_monitor/utils.py
  - custom_components/eg4_web_monitor/base_entity.py
  - custom_components/eg4_web_monitor/coordinator.py
  - custom_components/eg4_web_monitor/number.py
  - custom_components/eg4_web_monitor/switch.py
  - custom_components/eg4_web_monitor/time.py
  - custom_components/eg4_web_monitor/update.py
  - custom_components/eg4_web_monitor/control_discovery.py
  - memory/cloud-raw-register-write-broken.md
  - memory/issue-476-green-mode-bit14.md
  - memory/battery-control-mode-soc-vs-voltage.md
  - eg4_web_monitor issues #310, #328, #362, #476, #485
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-09
see-also:
  - ../40-hardware/registers.md
  - ../60-history/open-contradictions.md
  - ../60-history/superseded-claims.md
---

# Controls and writes

Line numbers are pinned per repo by the `verified-against:` mapping above — `9f6d6e2` for
`eg4_web_monitor`, `204b95d` for `pylxpweb`. Each citation names its repo where it is not this one.
Symbol names are the durable anchor.

**The rule: do not add a second write path.** Route control writes through
`async_write_with_cloud_fallback` so that fallback, cache seeding and the error contract come with
them.

**The rule is not a description of the current code.** Writes reach the device by several shapes,
not all of which are routed by eg4 — some bypass the router (§1.3), and some hand a method name to
pylxpweb and let the library decide the transport (§2). How many shapes exist is **not** something
this page asserts; §0 explains why and gives you the derivation instead.

**Read §0 before trusting any count of write paths, on this page or anywhere else.**

## 0. The write surface is not reliably enumerable from documentation

Three review rounds, three independent engines, and each round found a write shape the previous
round's frame excluded. That is not a run of bad luck — it is the finding. **This page therefore
does not tell you how many write mechanisms exist.** It describes the ones that are known,
publishes the derivation, and names the blind spots that have actually bitten, so you can re-derive
rather than trust a count.

If you need to know whether a specific control writes a specific register locally: **run §0.2 for
that control**, then read the pylxpweb method it lands on. Do not answer from this page's tables.

### 0.1 Known write shapes

Accurate as descriptions; **not asserted to be all of them.**

| Shape | How the write is issued | Who chooses local vs cloud |
|---|---|---|
| **The router** | eg4 calls a coordinator primitive (`write_named_parameter` / `write_raw_parameter` / `write_register`) inside `utils.py` → `async_write_with_cloud_fallback`. Reached via `_execute_local_with_fallback` (switch), `number.py` → `_write_parameter` / `_write_voltage_register`, the select/time `local_write` closures, and the coordinator's battery-regime write | **eg4**, one policy, one place (§1) |
| **Router bypass** | An entity calls a coordinator primitive directly, outside the router (§1.3) | eg4, ad hoc per entity |
| **Switch action** | `base_entity.py` → `_execute_switch_action`, called **directly by an entity**: resolves `getattr(inverter, method_ref)` — a pylxpweb method *name* — or takes a pre-bound callable, and awaits it | **pylxpweb**, per method (§2) |
| **Direct library call** | An entity awaits a pylxpweb method on the inverter object with no eg4 helper at all — e.g. `await inverter.set_grid_peak_shaving_power(...)` | **pylxpweb**, per method (§2) |
| **Background (no entity)** | Coordinator-scheduled writes with no entity involved — e.g. the hourly portal DST reconciliation | The calling code |

`verified-against-code` at `9f6d6e2` — call sites cited in §1, §1.3, §2.2 and §0.3.

> **Routing and fallback are properties of the pylxpweb method, not of the shape.** An earlier
> version of this page tabulated "cloud fallback: no" against the switch-action shape. That is
> wrong: several library methods implement their **own** cloud fallback internally, so a write eg4
> issued with no fallback of its own may still fall back one layer down. What eg4 loses on the
> non-router shapes is *its* fallback, *its* link-down short-circuit and *its* `local_values`
> seeding — not necessarily fallback as such. **You cannot infer routing or fallback from the eg4
> side at all; open the method.** (§2.1)

### 0.2 The derivation

| Step | Check |
|---|---|
| 1 | `grep -nE '\.write_(named_parameter\|raw_parameter\|register)\(' *.py` — router traffic and its bypasses (§1.4 has the closure-vs-bypass test) |
| 2 | `grep -n '_execute_switch_action' *.py` — switch-action routes (§2.3) |
| 3 | `grep -rnE 'await (inverter\|device)\.[a-z_]+\(' number.py select.py switch.py time.py button.py update.py` — direct library calls; discard reads (`refresh`) and docstring examples |
| 4 | For every pylxpweb method reached by steps 2–3, **resolve the runtime class** and read that method's routing policy (§2.1) |
| 5 | Search the coordinator for scheduled writes with no entity (§0.3, blind spot **d**) |
| 6 | Cross every writable register against [`40-hardware/registers.md`](../40-hardware/registers.md) |

### 0.3 Four blind spots, each with the case that proved it

Every one of these produced a confident, wrong completeness claim in this chapter.

| # | Blind spot | Worked example |
|---|---|---|
| **a** | A coordinator-primitive grep misses **library-mediated writes** entirely, because no `coordinator.write_*` call appears in this repo for them | `EG4QuickChargeSwitch` writes **H233** through `enable_quick_charge`. Invisible to step 1 |
| **b** | An `_execute_switch_action` grep misses **direct `inverter.<method>()` calls** | `number.py:1291` → `set_grid_peak_shaving_power` writes **H206**; `select.py:266` → `set_operating_mode`. `select.py` and `number.py` contain **zero** `_execute_switch_action` calls, so step 2 cannot see them |
| **c** | Reading `base.py` misses **runtime subclass overrides** — resolve the class, then check something **constructs** it | `HybridInverter` overrides `enable_pv_sell_to_grid` to "deliberately remain transport-first" on **H179 b3** (pylxpweb `204b95d`, `devices/inverters/hybrid.py:1294`), and `base.py:3487` warns about the override in its own docstring. A previous revision read only `base.py`, concluded "exactly one entity", and had no basis for it. Resolving the class shows **eg4 never holds a `HybridInverter`**, so that override never runs (§2.2) — but the base method keeps a *clientless* local leg, so the class alone still does not settle where the write lands |
| **d** | An entity-scoped search misses **background writes** | `coordinator_mixins.py:4563` → `_perform_dst_sync` calls `station.sync_dst_setting()` hourly. `dst_sync_enabled` defaults to **`True`** (`coordinator.py:408`). No entity is involved |

Whole table: `verified-against-code` at `9f6d6e2` / pylxpweb `204b95d`.

### 0.4 Partial inventory — observed 2026-08-09

`asserted-unverified` (single walk, date above). **Every previous version of this inventory was
incomplete**, including ones that read as exhaustive. Treat it as a starting point for §0.2, never
as the answer.

| Control | Shape | Library method / primitive | Register |
|---|---|---|---|
| `QuickChargeDurationNumber` | router bypass | `write_named_parameter` | H234 |
| `StartChargePowerNumber` | router bypass | `write_raw_parameter` (raw) | H117 |
| `EG4QuickChargeSwitch` | switch action | `enable_quick_charge` / `disable_quick_charge` — transport-first | H233 |
| `EG4WorkingModeSwitch` (`FUNC_PV_SELL_TO_GRID_EN`) | router; reaches the switch-action branch only via the legacy version guard (§2.2) | `BaseInverter.enable_pv_sell_to_grid` — client-first **per instance**. The `HybridInverter` transport-first override is never constructed | H179 b3 |
| `GridPeakShavingPowerNumber` | direct library call | `set_grid_peak_shaving_power` — transport-first with internal cloud fallback | H206 |
| `EG4OperatingModeSelect` | direct library call | `set_operating_mode` → `set_standby_mode` | — |
| DST reconciliation | background | `station.sync_dst_setting()` | cloud-side |

Register grades belong to [`40-hardware/registers.md`](../40-hardware/registers.md) — read them
there. The register-side criterion and the wider surface are owned by
[README](../README.md#the-rule-is-not-enforced-anywhere-in-the-code).

### 0.5 Cloud-only writers

**Non-exhaustive, and scoped strictly to writes that cannot reach a register locally.** Derive with
§0.2 if completeness matters. Known: `_execute_cloud_function_action` (the generic
`control_function` API); `EG4CloudStoreSwitch._async_set_enabled` and `EG4DSTSwitch._set_dst`;
and the direct `client.api.control.*` writers in `ACCoupleSOCNumberBase` (`number.py:1698`),
`SmartLoadNumber` (`number.py:1996`) and `GridSellBackPowerNumber` (`number.py:2103`).
`verified-against-code` at `9f6d6e2`.

## 1. The router: `async_write_with_cloud_fallback`

Location: `utils.py:185-270`. Evidence for this whole section: `verified-against-code`.

```
local transport attached?  (coordinator.has_local_transport(serial))
├── yes, and link believed UP
│      → await local_write()
│           on HomeAssistantError → cloud_write()  [only if a cloud client exists]
│           no cloud client       → the local error propagates UNCHANGED
├── yes, but coordinator.is_transport_link_down(serial)
│      → skip local entirely, log WARNING, go straight to cloud
└── no
       → cloud_write() if a cloud client exists, else raise HomeAssistantError

after a cloud write while a local transport is attached:
    coordinator.note_parameters_written(serial, local_values)   # local-raw seed
```

| Parameter | Meaning |
|---|---|
| `local_write` | Coroutine factory performing the local register write |
| `cloud_write` | Coroutine factory for the equivalent cloud write, or `None` when the action has no cloud path (raw-register-only controls) — then local errors propagate unchanged |
| `local_values` | The written parameters **in the LOCAL-RAW representation** the attached-transport cache uses. Merged into the parameter cache when the write landed via cloud |

### 1.1 Why a known-down link skips local entirely

| Fact | Evidence |
|---|---|
| **pylxpweb keeps a transport ATTACHED while its link is down.** Reads keep probing every cycle for recovery, so `has_local_transport()` stays `True` throughout an outage | `verified-against-code` at pylxpweb `204b95d` — `devices/base.py` → `transport_link_down` (`:236`), the attached-but-down state described at `:33` and maintained at `:173-180`. (`coordinator.py:1004-1030`'s docstring says the same, but a docstring is prose: evidence of intent, not of library behaviour) |
| Attachment therefore **cannot** safely choose the write route | `verified-against-code` — `utils.py:194-200` docstring |
| `is_transport_link_down()` reports `True` **only** for an attached-but-dead link; its strict guards require an attached transport and a real bool `transport_link_down`, so stale attributes and older pylxpweb versions never report down | `verified-against-code` — `coordinator.py:1004-1030`, delegating to `coordinator_mixins.is_transport_link_down` |
| Skipping local avoids **waiting out a doomed Modbus timeout** before the fallback even starts | `verified-against-code` — `utils.py:206-209` |
| Recovery is automatic: reads re-probe the link each poll, so local writes re-enable themselves | `verified-against-code` — same docstring |

> Both paths set **absolute** state, so a double-write (local failure then cloud retry) is safe.
> This is stated explicitly in the router's contract and is what makes the fallback legal.

### 1.2 Why the cloud path must seed the parameter cache

After a cloud-routed write with a local transport attached, the follow-up parameter refresh
**cannot** read locally on a down link (LOCAL-only: pylxpweb skips it; HYBRID: the cloud re-read
can lag or fail). Without `local_values` seeding, the entity reverts to the **stale pre-write
value** the moment its optimistic state clears — issue #310.

Evidence: `verified-against-code` — `utils.py:259-267` and its docstring; seeding lands in
`coordinator.note_parameters_written` (`coordinator.py:1110-1144`).

**Rule:** any new call site that passes a `cloud_write` must also pass `local_values`, unless the
control genuinely has no local representation.

### 1.3 Router bypasses

**Scope: the router only, and not asserted complete.** These are the coordinator-primitive writes
that do *not* route through `async_write_with_cloud_fallback`, as derived by §1.4 at `9f6d6e2`.
Re-derive rather than trusting the list. It says nothing about the library-mediated shapes, whose
writes never touch a coordinator primitive and so cannot appear here at all — two review engines
independently re-derived this same set and were right within a scope that was itself too narrow,
which is what §0 exists to prevent.

Both call a coordinator write primitive directly from `async_set_native_value`. Neither is a
defect in itself — each has a reason — but **the router's guarantees do not extend to them**, and
that is what a reader must not assume.

| | `QuickChargeDurationNumber` | `StartChargePowerNumber` |
|---|---|---|
| Bypass site | `number.py:1004` | `number.py:2279` |
| Primitive | `coordinator.write_named_parameter` (H234) | `coordinator.write_raw_parameter` (**raw H117**) |
| Why not the router | There is no cloud equivalent of the live H234 write: on CLOUD the value is stored as a start *preference*, not written. A firmware-rejected lone idle write is guarded by a live enable-bit read first (#251) | LOCAL/HYBRID only by construction — H117 has no cloud parameter name, so there is no `cloud_write` to fall back to |
| **Loses: cloud fallback** | n/a — no cloud write exists | n/a — no cloud write exists |
| **Loses: link-down short-circuit** | Yes. `has_local_transport()` stays `True` through an outage, so a known-down link is not detected and the write waits out the Modbus timeout | Yes, same |
| **Loses: `local_values` cache seeding** | Yes — it hand-seeds `quick_charge_status` instead, a different cache | Yes — nothing is seeded |
| **Loses: optimistic envelope** | Yes — no `optimistic_value_context`; it writes, seeds, then calls `async_write_ha_state()` directly, so §5's retention and TTL escape do not apply | No — it runs inside `optimistic_value_context`, so retention applies |
| Error contract | Raises `HomeAssistantError` when the live state read returns `None`, rather than the router's no-path error | Raises `HomeAssistantError` naming the missing cloud path when no local transport is attached |

Whole table: `verified-against-code` — `number.py` → `QuickChargeDurationNumber.async_set_native_value`
and `StartChargePowerNumber.async_set_native_value` at `9f6d6e2`.

> **H117 is the one to watch.** It is written **raw**, and the keeper grades the mapping
> `asserted-unverified`, status **unresolved**, with "no cloud name or validated behavior"
> ([H117 row](../40-hardware/registers.md)). A raw write to an unresolved mapping is the shape
> §10 rule 1 warns about: the firmware ACKs a wrong target and no readback distinguishes it. The
> LOCAL-only guard limits *who* can trigger it; it does not make the target correct.
>
> The register grade is the keeper's — read it there, not here.

### 1.4 Deriving the router's population

**Scope: the router only.** This derives which coordinator-primitive writes go through the
router and which bypass it. It cannot see the library-mediated shapes (§2), and it is not the full local-write
surface — which registers are reachable, and which stand on an unproven mapping, is derived in
[README](../README.md#the-rule-is-not-enforced-anywhere-in-the-code), which owns that question.

A completeness claim about write paths is only as good as the procedure that produced it, so here
is the procedure rather than a curated list. The distinction that matters is **closure versus
bypass**: most direct `.write_*` calls sit inside a `local_write` closure that is handed *to* the
router, and those are router traffic, not exceptions.

| Step | Command / check |
|---|---|
| 1 | `grep -nE '\.write_(named_parameter\|raw_parameter\|register)\(' number.py select.py switch.py time.py base_entity.py coordinator.py` — match on the **method name, not the receiver**: the coordinator calls its own primitives as `self.write_*`, so a `coordinator\.write_` pattern silently misses the battery-regime path |
| 2 | For each hit, find the **enclosing `def`**. A `local_write` / `_local_write` closure is router traffic; resolve one more level if the closure delegates to a helper |
| 3 | A hit whose enclosing `def` is the entity's own `async_set_native_value` / `async_turn_on` / `async_turn_off` is a **bypass** |
| 4 | Confirm each closure's enclosing scope actually calls `async_write_with_cloud_fallback` — a function named `local_write` is not proof it is passed to the router |
| 5 | Discard hits inside docstrings and comments. At `9f6d6e2` two of the fourteen hits are usage examples in a `coordinator.py` docstring, not call sites |

Applying that at `9f6d6e2` yields fourteen hits: **two bypasses**
(`number.py:1004`, `:2279`), ten closure call sites (`number.py:463`, `:514`, `:831`;
`select.py:370`, `:492`, `:629`; `time.py:378`; `base_entity.py:1943`;
`coordinator.py:1870`, `:1874` inside `_async_write_battery_control_mode`), and two docstring
examples (`coordinator.py:1690`, `:1693`).
`switch.py` contains no direct coordinator write call at all — the switch platform reaches the
router through `base_entity.py` → `_execute_local_with_fallback`.

`verified-against-code` — enumerated with the procedure above at `9f6d6e2`.

> **Step 2 is where a survey goes wrong.** `base_entity.py:1943` looks like a bypass: its
> enclosing `def` is `_execute_named_parameter_action`, not a closure. It resolves to router
> traffic only one level further out, because that helper's sole caller is the `local_write`
> closure at `base_entity.py:1731`. A grep that stops at the first enclosing `def` over-reports;
> a grep scoped to the four platform files misses the site entirely.

## 2. Library-mediated writes

These shapes put the transport decision inside pylxpweb: `_execute_switch_action`, and an entity
awaiting a library method directly. They are grouped because the consequence is identical —
**eg4 does not choose the transport, and no eg4-side reading can tell you what it chose.**

### 2.1 What they do, and why the transport is not eg4's decision

`_execute_switch_action` (`base_entity.py:1543-1668`):

```python
method = (getattr(inverter, method_ref, None)      # a pylxpweb method NAME
          if isinstance(method_ref, str)
          else method_ref)                          # or a pre-bound callable
success = await method(**(enable_kwargs or {})) if turn_on else await method()
```

A direct library call skips even that indirection — `await inverter.set_grid_peak_shaving_power(
power_kw=value)` (`number.py:1291`).

Either way eg4 names a method and **pylxpweb performs the write and chooses the transport.**
`_execute_switch_action`'s body contains no call to `async_write_with_cloud_fallback`, so §1's
fallback, link-down short-circuit and `local_values` seeding are not in play. It does keep the
optimistic envelope — it delegates to `_optimistic_write_envelope`, so §5's retention and TTL
escape apply, and a caller may seed the parameter cache through the separate `seed_param_key`
channel. A direct library call gets whatever its own call site arranges.

The code states the consequence at the log site: *"The routing (local transport vs cloud API) is
decided by the called method itself, so the log names the method, not a transport."*

> **Routing and fallback are per method, and the method may not be the one you read.** Three
> traps, all of which have produced a wrong conclusion in this chapter:
>
> | Trap | Case |
> |---|---|
> | Policies point in opposite directions | `enable_quick_charge` is **transport-first** ("With a local transport … this writes … to holding register 233 bit 0"); `enable_ac_charge_mode` is **client-first** ("cloud and HYBRID instances keep the dedicated cloud endpoint") — pylxpweb `204b95d`, `base.py:4011` and `:4359` |
> | A subclass overrides the base — but check anything builds it | `base.py:3481` `enable_pv_sell_to_grid` is client-first; `HybridInverter` **overrides** it to "deliberately remain transport-first", writing H179 b3 via a lock-held named RMW — pylxpweb `204b95d`, `hybrid.py:1294`. Nothing constructs that class, here or in the library, so the override never runs (§2.2). **Resolve the actual class before reading a policy — then confirm it is ever instantiated** |
> | The library has its own fallback | `set_grid_peak_shaving_power` writes H206 locally "falling back to the cloud named-parameter write when no transport is attached, the link is down, or the local write fails" — pylxpweb `204b95d`, `base.py:2996`. So "eg4 provides no fallback here" does **not** mean "this write has no fallback" |
>
> **Open the method on the runtime class.** There is no eg4-side signal for any of this.

### 2.2 Known callers

**Not asserted to be complete** — re-derive with §2.3. Two prior revisions of this section stated a
population as exhaustive and both were wrong (§0.3 **b** and **c**).

| Caller | Site | Shape | Library method | Can it write a register locally? |
|---|---|---|---|---|
| `EG4QuickChargeSwitch._async_set_quick_charge` | `switch.py:627` | switch action | `enable_quick_charge` / `disable_quick_charge` | **Yes** — transport-first, targets **H233** (§2.4) |
| `EG4WorkingModeSwitch._async_set_working_mode` | `switch.py:1511` | switch action, on the `elif self.coordinator.has_http_api() and methods:` branch | one of `_WORKING_MODE_METHODS` | **Not through the override.** All seven resolve to `base.py` — eg4 never holds a `HybridInverter`, so its transport-first `enable_pv_sell_to_grid` never runs. The base method is client-first *per instance* and reaches H179 b3 locally only on a **clientless** inverter (below) |
| `GridPeakShavingPowerNumber.async_set_native_value` | `number.py:1291` | direct library call | `set_grid_peak_shaving_power` | **Yes** — transport-first with internal cloud fallback, targets **H206** |
| `EG4OperatingModeSelect.async_select_option` | `select.py:266` | direct library call | `set_operating_mode` → `set_standby_mode` | Read the runtime class per §2.1 |

`verified-against-code` — call sites and guards at `9f6d6e2`; routing policies and the
class-resolution chain below at pylxpweb `204b95d`, as cited in §2.1 and in the note.

> **Why the working-mode row changed, twice.** A previous revision checked all seven
> `_WORKING_MODE_METHODS` in `base.py`, found them uniformly client-first, and concluded the branch
> could never write locally. A later revision found `HybridInverter` overriding one of the seven and
> flipped the row to "yes, for one mode". **Both were wrong**, because neither resolved which class
> the coordinator actually holds.
>
> **eg4 never holds a `HybridInverter`.** `grep -rn 'HybridInverter' custom_components/eg4_web_monitor/`
> returns **zero** hits. Entities reach the library through
> `coordinator.get_inverter_object()`, which serves `_inverter_cache: dict[str, BaseInverter]`
> (`coordinator.py:526`, `:990-992`), and every path that fills that cache builds a
> **`GenericInverter`**:
>
> | Cache-fill path | Site | Constructs |
> |---|---|---|
> | Cloud station load | `coordinator.py:979-984` → `station.all_inverters` | pylxpweb `station.py:1190` |
> | Transport-backed station device | pylxpweb `station.py:833` `_create_device_with_transport` | `station.py:862` (`MIDDevice` on the GridBOSS leg) |
> | LOCAL/HYBRID factories | `coordinator_local.py:900`/`:905`, `:1235`/`:1239` → `BaseInverter.from_modbus_transport` / `from_dongle_transport` | pylxpweb `base.py:558`; `from_dongle_transport` (`:587`) delegates at `:620` |
>
> In the library itself, `git grep 'HybridInverter('` at `204b95d` matches only the class statement
> (`hybrid.py:25`) and a **docstring example** (`:38`) — pylxpweb never instantiates it either. The
> override is dead code from this integration's point of view.
>
> **What that does and does not settle.** It removes the *cited* reason for a local write, but it
> does not restore the original "exactly one entity" conclusion, because the base method is
> client-first **per instance**, not per mode: `_set_pv_sell_to_grid` (`base.py:3462`) binds a cloud
> callable only `if self._client is not None`, and `_set_client_first_function_bit` (`:2289`) writes
> H179 b3 through `transport.write_named_parameters` whenever that callable is `None`. A
> transport-built inverter carries `client=None` (`base.py:558` passes a `placeholder_client`), so
> the clientless leg is a real local write on a real object.
>
> The branch guard is what makes it moot in practice. `elif self.coordinator.has_http_api() and
> methods:` is reached only when `param_name` is falsy, and for this param that happens **only**
> through the pylxpweb **version guard** (`switch.py:1474-1481`) on an install predating
> `0.9.36b6`. At the pinned `204b95d` the name resolves, so the entity takes the router branch
> (`_execute_local_with_fallback`) instead. Whether any live HYBRID state pairs a clientless cached
> inverter with that legacy-degraded branch is `asserted-unverified`, status **unresolved** — it
> needs a legacy install to exercise, and this page does not claim either answer.
>
> H179 b3 is `hardware-toggle-proven` in the keeper, so the mapping itself is not in doubt. The
> durable lesson survives all three revisions and is the one worth keeping: **resolve the runtime
> class before reading a routing policy — then confirm something constructs it, and check whether
> the policy branches on the instance rather than the class.** That is why §0 publishes blind spots
> instead of counts.

### 2.3 Deriving the callers

| Step | Check |
|---|---|
| 1 | `grep -n '_execute_switch_action' switch.py number.py select.py time.py base_entity.py` |
| 2 | Discard the definition, docstring mentions, and **`base_entity.py:1766`** — that call is the router's own cloud leg, not a direct entity call |
| 3 | `grep -rnE 'await (inverter\|device)\.[a-z_]+\(' number.py select.py switch.py time.py button.py update.py` — direct library calls. Discard reads (`refresh`) and docstring examples (`base_entity.py:1009`) |
| 4 | For each remaining call, read the **branch guard** — but do not stop there: a guard that forces a cloud client does not force a cloud *write* if the method is transport-first |
| 5 | For every method reached, **resolve the runtime class, then confirm something constructs it** — every path here builds `GenericInverter`, so `HybridInverter`'s override never runs (§2.2). Then read the policy on the class that *is* built, and check whether it branches on the **instance** (client attached or not), as `_set_client_first_function_bit` does |
| 6 | Cross the resulting registers against [`40-hardware/registers.md`](../40-hardware/registers.md) |

`verified-against-code` — run at `9f6d6e2` / pylxpweb `204b95d` to produce §2.2. Steps 3 and 5 exist
because their absence produced §0.3 **b** and **c**.

### 2.4 The H233 exposure this makes visible

Running §2.3 surfaces a write that a coordinator-primitive grep cannot see:

| Fact | Grade |
|---|---|
| In pure-LOCAL on an `EG4_OFFGRID` family, `EG4QuickChargeSwitch` attempts a **local H233 write** | `verified-against-code` — `switch.py` → `_prefers_cloud_control` returns `is_offgrid_family(...) and self.coordinator.has_http_api()`; with no cloud client that is False, so `enable_method` stays the transport-first `"enable_quick_charge"` |
| That is the write the same file's docstring describes as firmware-rejected on this family | `verified-against-code` — `_prefers_cloud_control`'s docstring: register 233 is rejected "(ILLEGAL DATA ADDRESS, #296)", and the mitigation is scoped — "Go straight to the cloud start/stop endpoints **when a cloud client is configured**" |
| The keeper marks the H233 off-grid access boundary **unresolved** | grade owned by [`40-hardware/registers.md`](../40-hardware/registers.md#h233-off-grid-access-boundary) — read it there |

**This is a scope gap in a mitigation, not a bug report.** The cloud-preference path was built for
#296 and works wherever a cloud client exists; pure-LOCAL off-grid is the configuration it does
not cover. Tracked on issue **#558**. Changing the routing is a code change and is out of scope
for documentation.

## 3. Coordinator write primitives

| Method | What it calls | Used for | Cite |
|---|---|---|---|
| `write_named_parameter(param, value, serial)` | `transport.write_named_parameters({p: v})` | The default local write | `coordinator.py:1664-1710` |
| `write_raw_parameter(address, value, serial)` | `transport.write_parameters({addr: val})` | Registers with **no name AND no cloud param** (e.g. reg 117) | `coordinator.py:1712-1750` |
| `write_register(register, value, serial)` | same call | Packed schedule registers (FC06) | `coordinator.py:1752-1794` |
| `_write_with_local_transport(...)` | shared shell | Acquire endpoint lock, reconnect if needed, write, translate errors to `HomeAssistantError` | `coordinator.py:1553-1594` |
| `async_write_battery_control_mode` | two-bit reg-179 transaction under `control_transaction_lock` | Battery charge/discharge regime | `coordinator.py:1844-1943` |

All rows: `verified-against-code`.

`write_raw_parameter` and `write_register` are **acknowledged near-duplicates**; the code
explicitly says "do not merge them piecemeal" (`verified-against-code` — `coordinator.py:1768-1770`).

### 3.1 Two lock layers

| Lock | Scope | Why | Cite |
|---|---|---|---|
| **Logical transaction locks** | module level, keyed `(serial, control)` | A config-entry reload must not hand out a fresh lock mid-write | `coordinator.py:151`, `:1798-1810` |
| **Endpoint locks** | pylxpweb's `_op_lock` rebound to a HA-scoped, **task-reentrant** `EndpointOperationLock`, keyed by physical `host:port` or tty | pylxpweb's named-parameter read-modify-write **nests** the op lock; a plain `asyncio.Lock` deadlocks | `coordinator.py:1596-1636`, `transport_serialization.py:26-57` |

All rows: `verified-against-code`.

### 3.2 Routing convention

Entity and coordinator writes go through `coordinator.write_named_parameter` (local) and
`client.api.control.*` (cloud) — **not** through pylxpweb device methods, which need the inverter's
own transport plus reconnect handling.

| Claim | Grade |
|---|---|
| The code routes local writes through `coordinator.write_named_parameter` and cloud writes through `client.api.control.*` | `verified-against-code` — `coordinator.py` → `write_named_parameter`; the cloud legs in `switch.py`, `number.py`, `select.py`, `time.py` |
| The stated reason is that pylxpweb device methods need the inverter's own transport plus reconnect handling | `asserted-unverified` — `memory/battery-control-mode-soc-vs-voltage.md` |
| Whether calling `client.api.*` at all is permitted is **contested** | **C3** in [../60-history/open-contradictions.md](../60-history/open-contradictions.md#c3--never-use-clientapi-versus-the-current-write-routing-convention), status UNRESOLVED: an older internal design doc states the integration must *never* call `client.api.*` ("there are no exceptions") |

This page records what the code does and does not adjudicate C3.

## 4. Switch write envelope

Location: `base_entity.py:1440-1541`. Evidence: `verified-against-code`.

```
_begin_optimistic_write(value)          # snapshot pre-write cache state, publish optimistic
do_write()
  ├─ HomeAssistantError → clear optimistic, re-raise
  └─ other Exception    → clear optimistic, wrap in HomeAssistantError, raise
# ── write acknowledged: nothing below may raise a user-facing write failure ──
seed_param_key ⇒ _seed_cloud_written_parameter()      # BEFORE the refresh
refresh_phase: pre_delay_refresh? → sleep(api_delay=1.0) → do_refresh()
_settle_acknowledged_write(action, pre_write_state, refresh_phase | None)
  refresh ok    → _clear_optimistic()
  refresh fail  → _arm_retention()      (bounded, 300 s)
  refresh None  → deliberate skip (known-down cloud fallback, #485) → retain, log at DEBUG
```

| Detail | Evidence |
|---|---|
| The seed happens **before** the refresh, so the refresh can converge on the written value | `verified-against-code` — envelope ordering |
| Once the write is acknowledged, no later step may surface a write failure to the user | `verified-against-code` — `_settle_acknowledged_write` swallows refresh errors and logs them (`base_entity.py:918-931`) |
| `_execute_local_with_fallback` raises `ValueError` if only one of `cloud_enable_method` / `cloud_disable_method` is supplied — a one-sided call would silently write the wrong `FUNC_` key | `verified-against-code` — `base_entity.py:1713-1718` |
| It keeps the optimistic state across a local failure when a cloud retry follows (`clear_optimistic_on_error = not cloud_available`) | `verified-against-code` — `base_entity.py:1735` |

> **#485.** `_execute_local_with_fallback` originally lacked the link-down short-circuit its sibling
> helper already had, so switch writes attempted a local RMW on a known-down link. The general
> lesson: **when two helpers do "the same thing", diff them.**

### 4.1 Post-write refresh success is judged by data-object identity

```python
# base_entity.py:1422-1438
async def _refresh_coordinator_data(self) -> bool:
    data_before = self.coordinator.data
    await self.coordinator.async_refresh()
    return bool(self.coordinator.last_update_success) and (
        self.coordinator.data is not data_before
    )
```

| Why | Evidence |
|---|---|
| `last_update_success` **lies** during the coordinator's 3-strike tolerance window: the first two consecutive `UpdateFailed` cycles return the OLD `self.data` object unchanged **without** flipping the flag | `verified-against-code` — `base_entity.py:1423-1432` docstring; tolerance implemented at `coordinator.py:897-917` |
| A same-identity data object after the refresh is therefore treated as **failure** — every genuinely successful cycle builds a new dict | `verified-against-code` — `base_entity.py:1436-1438` |

**Never** substitute `last_update_success` for this check. That substitution is bug #362.

## 5. Optimistic state and retention

Location: `EG4OptimisticEntity`, `base_entity.py:741-961`. Evidence: `verified-against-code`.

### 5.1 The two exits

Retention ends at the **first** of:

| # | Exit | Condition | Cite |
|---|---|---|---|
| 1 | **Convergence** | A tick whose decoded cache value equals the written value **or** is anything other than the pre-write value | `base_entity.py:949` |
| 2 | **Expiry** | `RETAINED_OPTIMISTIC_TTL = 300 s`, logged as a WARNING | `base_entity.py:951-960` |

Exit 2 is the **silent-firmware-NAK escape**. Without it, a write the firmware quietly rejected
would display as applied forever.

### 5.2 The 300 s TTL coupling — change both or neither

| Constant | Location | Value |
|---|---|---|
| `RETAINED_OPTIMISTIC_TTL` | `base_entity.py:63` | `300.0` |
| `QUICK_CHARGE_OPTIMISTIC_TTL` | `switch.py:447` | `300` |

> These must stay **numerically equal**. After a quick-charge write-ok + refresh-fail, BOTH holds
> arm within the same call, and **nothing else couples them afterwards** — equal TTLs are the only
> thing keeping them expiring together. The code comment says it outright: *"Change both or
> neither."*
>
> Evidence: `verified-against-code` — `base_entity.py:58-63`.

### 5.3 The `_cache_state()` contract

| Requirement | Consequence if violated | Cite |
|---|---|---|
| **Side-effect-free** | A peek that mutates state corrupts convergence detection | `base_entity.py:825-834` |
| Must read **genuine device data**, masking the optimistic value **and every other held command** | Otherwise the peek echoes the command back, convergence fires immediately, and the TTL escape is defeated — the write looks confirmed when it was never applied | `base_entity.py:825-834`, `:1388-1408` |
| Quick charge overrides it to also mask `_pending_state` (#296) | The canonical example of "every other held command" | `base_entity.py:1388-1408` |

All rows: `verified-against-code`.

## 6. Per-platform write specifics

| Platform | Mechanism | Notes | Cite |
|---|---|---|---|
| **Number** | `optimistic_value_context()` publishes the optimistic value; the body sets `write.refresh_ok`; the exit either clears or arms retention | `_write_parameter` and `_write_voltage_register` both go through the shared router with `local_values=` seeding. `_refresh_related_entities()` returns a bool and **never raises** | `base_entity.py:984-1026`; `number.py:438-489`, `:491-536`, `:538-555` |
| **Voltage registers** | Local writes by **name**; cloud writes by **raw register address** | Asymmetric on purpose | `number.py:513-525` |
| **Time** | **Explicit** optimistic management — no `finally`-clearing context manager | Because a successful write with a failed refresh must **retain**. LOCAL/HYBRID write one packed FC06 register; CLOUD uses `write_time_parameter` (writeTime families) or separate `*_HOUR` + `*_MINUTE` writes | `base_entity.py:1109-1114`; `time.py:23-33` |
| **Select** | `EG4BaseSelect._cache_state()` masks the optimistic option **synchronously** | | `base_entity.py:1220-1233` |
| **Switch** | Full envelope, §4 | | `base_entity.py:1440-1541` |

All rows: `verified-against-code`.

## 7. Error surfacing

| Exception | When | Cite |
|---|---|---|
| `HomeAssistantError` | The standard control-write failure. Raised by the router when no path exists, by `_write_with_local_transport` on translated transport errors, and by the switch envelope wrapping non-HA exceptions | `utils.py:268-270`, `coordinator.py:1594`, `base_entity.py:1497`, `number.py:169-173` |
| `HomeAssistantError` from `require_client()` | No cloud client **and** no local transport — "No local transport or cloud API available for parameter write." | `coordinator.py:1032-1046` |
| `ServiceValidationError` | **User-input validation only**: service handlers (`__init__.py:369-397`, `services.py`, `history_import.py`) and exactly one control precondition — Grid Peak Shaving power writes while the function is disabled | `number.py:1271` |
| Repairs issue | `flag_offgrid_control_suppression()` raises one issue per `(issue_key, serial)` **only if a matching entity was previously registered**, matching unique-ID suffixes with a serial-boundary guard | `utils.py:362-439` |

All rows: `verified-against-code`. Repairs detail: [diagnostics-repairs.md](diagnostics-repairs.md).

> `DATAFRAME_TIMEOUT` on a cloud write does **not** mean the relay is down. The same error appears
> for a parameter the server's write path cannot handle, and for a firmware NAK when the owning
> mode is disabled — Grid Peak Shaving writes are NAKed and the setpoint zeroed while PS mode is
> off. **Always verify with a read.** Evidence: the Grid Peak Shaving register behaviour is owned by
> [../40-hardware/registers.md](../40-hardware/registers.md) (#328) — read the grade there; the
> general error-taxonomy claim is `asserted-unverified`
> (`memory/live-write-window-findings.md`).

## 8. Firmware update entity

| Behavior | Evidence |
|---|---|
| Module-level `_INSTALL_LOCKS: dict[str, asyncio.Lock]` survive config-entry reloads | `verified-against-code` — `update.py:23-28`, `:100` |
| `in_progress` reports `True` for the **whole chain** while the lock is held, because coordinator-derived status can flicker idle between components of a multi-step update | `verified-against-code` — `update.py:167-189` |
| `async_install` runs `run_firmware_update_to_completion()`, always writes state and requests a coordinator refresh in `finally` (best-effort, must not raise), and raises `HomeAssistantError` when `result.success` is false | `verified-against-code` — `update.py:213-285` |

## 9. Late control discovery

Location: `control_discovery.py:122-189`. Evidence: `verified-against-code`.

| Mechanism | Detail |
|---|---|
| One **capability signature** per platform: per-serial type / model / features + a platform-specific `extra_signature` | `control_discovery.py:43-66` |
| Fast-moving sensor values are **deliberately excluded** from the signature | otherwise every tick would rebuild candidates |
| On signature change: rebuild candidates, mark already-registered entities supported/unsupported via `_set_control_discovery_supported`, add only genuinely new unique IDs | `control_discovery.py:122-185` |
| `migrate_model_prefix` renames legacy `{model}_{serial}_{key}` IDs when the suffix match is unambiguous | `control_discovery.py:69-119` |
| The listener is registered **before** the first `_rediscover_controls()` call, so capability convergence happens in the same tick as entity updates | `control_discovery.py:186-189` |

Platform route signatures: `number.py:743-759`, `switch.py:384-404`.

`_control_discovery_supported` feeds directly into control availability — see
[entities-identity-availability.md](entities-identity-availability.md) §2.

## 10. Write-path landmines

| # | Rule | Evidence |
|---|---|---|
| 1 | **A guessed register bit is worse than no local write.** A wrong-but-writable bit is firmware-ACKed: no exception, no cloud fallback, no log above DEBUG — and readback cannot catch it, because writing a bit sets that bit and reads back true whether or not the feature moved. **Gating is the only mitigation** for an unproven bit mapping | The falsification case is **S2** in [../60-history/superseded-claims.md](../60-history/superseded-claims.md); read the grade there. The consequence for write routing is `inferred` from it |
| 2 | `FUNC_SMART_LOAD_ENABLE` has **no pinned bit** (179 bit 13 is a placeholder) → Smart Load stays cloud-only | `verified-against-code` — `switch.py:252-262` |
| 3 | `_local_params_can_carry()` probes pylxpweb's `REGISTER_TO_PARAM_KEYS` and doubles as a **version guard**: a param absent from that map can never appear in a local-raw cache, so the switch would report a permanent lying OFF | `verified-against-code` — `switch.py:143-158`, used at `:352-360` |
| 4 | `params_are_local_raw()` must **not** treat the deprecated global-transport fallback as raw. Legacy flat HYBRID entries populate the cache from the cloud (already scaled); treating them as raw shows 12 kW as 1.2 | `verified-against-code` — `coordinator.py:1079-1108` |
| 5 | Voltage scaling is **magnitude-normalised**, not blindly ÷10 — local is decivolts, cloud is already-scaled volts | `verified-against-code` — `number.py` → the voltage normalisation helper. See [data-semantics.md](data-semantics.md#3-value-scaling-cloud-vs-local-divergence) |
| 6 | Cloud-only param stores must **never** be seeded into the parameter cache: with a local transport attached, pylxpweb rebuilds `inverter.parameters` from register reads and wipes anything cloud-seeded. Hence the separate `CloudParamStoreSpec` stores with write-seed registries living **outside** `self.data` | `verified-against-code` — `coordinator_mixins.py:303-337`, `coordinator.py:1273-1347` |
| 7 | **Per-field** seed timestamps: a later write to one store key must not renew an older key's seed, or an in-flight read of a legitimate portal change gets clobbered | `verified-against-code` — `coordinator.py:1304-1310` |
| 8 | A seed may only be superseded when a read **observes a concrete value for that field** (`seed.at <= now AND observed[field] is not None`) — not merely because a read started. Otherwise a partial range-read returning `None` clears the seed and reverts a just-written state | `verified-against-code` — seed supersede logic, `coordinator.py:1273-1347` |
| 9 | Only a **delta test** (write → readback → restore) demonstrates that a write path carries values at all. A no-op write proves format acceptance, not targeting. pylxpweb's cloud `write_parameters({reg: raw})` form-encoded a dict that aiohttp serialised as `data=<key>&data=<key>`, dropping every value while looking successful | Split by what the pin can actually show. The **fix is present**: the named cloud write applies the canonical `ScaleFactor` — `verified-against-code` at pylxpweb `204b95d`, `endpoints/control.py` → `write_parameters` (`:282`, scaling at `:420-431`). The **historical form-encoding defect is not verifiable from a tree in which it is fixed** — `asserted-unverified` (`memory/cloud-raw-register-write-broken.md`), as is "broken since inception". The delta test is `verified-against-code` for the **code path** only; what the write did **physically** stays `asserted-unverified`, because a readback confirms storage and transport |
