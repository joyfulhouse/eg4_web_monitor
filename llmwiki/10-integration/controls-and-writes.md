---
canonical-for:
  - async_write_with_cloud_fallback write routing
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
  - /tmp/llmwiki-research/integration-architecture.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Controls and writes

Line numbers pinned to `9f6d6e2`; symbol names are the durable anchor.

Every control platform — switch, number, select, time — and the coordinator's own battery-regime
write funnel through **one** router. Do not add a second write path.

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
| **pylxpweb keeps a transport ATTACHED while its link is down.** Reads keep probing every cycle for recovery, so `has_local_transport()` stays `True` throughout an outage | `verified-against-code` — `coordinator.py:1004-1030` docstring |
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

## 2. Coordinator write primitives

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

### 2.1 Two lock layers

| Lock | Scope | Why | Cite |
|---|---|---|---|
| **Logical transaction locks** | module level, keyed `(serial, control)` | A config-entry reload must not hand out a fresh lock mid-write | `coordinator.py:151`, `:1798-1810` |
| **Endpoint locks** | pylxpweb's `_op_lock` rebound to a HA-scoped, **task-reentrant** `EndpointOperationLock`, keyed by physical `host:port` or tty | pylxpweb's named-parameter read-modify-write **nests** the op lock; a plain `asyncio.Lock` deadlocks | `coordinator.py:1596-1636`, `transport_serialization.py:26-57` |

All rows: `verified-against-code`.

### 2.2 Routing convention

Entity and coordinator writes go through `coordinator.write_named_parameter` (local) and
`client.api.control.*` (cloud) — **not** through pylxpweb device methods, which need the inverter's
own transport plus reconnect handling.

Evidence: `asserted-unverified` — this is a stated convention with a mechanical reason. It
**directly contradicts** an older internal design doc that says the integration must *never* call
`client.api.*` ("there are no exceptions"). The later rule with the mechanical justification is the
one the code follows; the contradiction is unresolved in the corpus and is flagged here rather than
silently picked.

## 3. Switch write envelope

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

### 3.1 Post-write refresh success is judged by data-object identity

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

## 4. Optimistic state and retention

Location: `EG4OptimisticEntity`, `base_entity.py:741-961`. Evidence: `verified-against-code`.

### 4.1 The two exits

Retention ends at the **first** of:

| # | Exit | Condition | Cite |
|---|---|---|---|
| 1 | **Convergence** | A tick whose decoded cache value equals the written value **or** is anything other than the pre-write value | `base_entity.py:949` |
| 2 | **Expiry** | `RETAINED_OPTIMISTIC_TTL = 300 s`, logged as a WARNING | `base_entity.py:951-960` |

Exit 2 is the **silent-firmware-NAK escape**. Without it, a write the firmware quietly rejected
would display as applied forever.

### 4.2 The 300 s TTL coupling — change both or neither

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

### 4.3 The `_cache_state()` contract

| Requirement | Consequence if violated | Cite |
|---|---|---|
| **Side-effect-free** | A peek that mutates state corrupts convergence detection | `base_entity.py:825-834` |
| Must read **genuine device data**, masking the optimistic value **and every other held command** | Otherwise the peek echoes the command back, convergence fires immediately, and the TTL escape is defeated — the write looks confirmed when it was never applied | `base_entity.py:825-834`, `:1388-1408` |
| Quick charge overrides it to also mask `_pending_state` (#296) | The canonical example of "every other held command" | `base_entity.py:1388-1408` |

All rows: `verified-against-code`.

## 5. Per-platform write specifics

| Platform | Mechanism | Notes | Cite |
|---|---|---|---|
| **Number** | `optimistic_value_context()` publishes the optimistic value; the body sets `write.refresh_ok`; the exit either clears or arms retention | `_write_parameter` and `_write_voltage_register` both go through the shared router with `local_values=` seeding. `_refresh_related_entities()` returns a bool and **never raises** | `base_entity.py:984-1026`; `number.py:438-489`, `:491-536`, `:538-555` |
| **Voltage registers** | Local writes by **name**; cloud writes by **raw register address** | Asymmetric on purpose | `number.py:513-525` |
| **Time** | **Explicit** optimistic management — no `finally`-clearing context manager | Because a successful write with a failed refresh must **retain**. LOCAL/HYBRID write one packed FC06 register; CLOUD uses `write_time_parameter` (writeTime families) or separate `*_HOUR` + `*_MINUTE` writes | `base_entity.py:1109-1114`; `time.py:23-33` |
| **Select** | `EG4BaseSelect._cache_state()` masks the optimistic option **synchronously** | | `base_entity.py:1220-1233` |
| **Switch** | Full envelope, §3 | | `base_entity.py:1440-1541` |

All rows: `verified-against-code`.

## 6. Error surfacing

| Exception | When | Cite |
|---|---|---|
| `HomeAssistantError` | The standard control-write failure. Raised by the router when no path exists, by `_write_with_local_transport` on translated transport errors, and by the switch envelope wrapping non-HA exceptions | `utils.py:268-270`, `coordinator.py:1594`, `base_entity.py:1497`, `number.py:169-173` |
| `HomeAssistantError` from `require_client()` | No cloud client **and** no local transport — "No local transport or cloud API available for parameter write." | `coordinator.py:1032-1046` |
| `ServiceValidationError` | **User-input validation only**: service handlers (`__init__.py:369-397`, `services.py`, `history_import.py`) and exactly one control precondition — Grid Peak Shaving power writes while the function is disabled | `number.py:1271` |
| Repairs issue | `flag_offgrid_control_suppression()` raises one issue per `(issue_key, serial)` **only if a matching entity was previously registered**, matching unique-ID suffixes with a serial-boundary guard | `utils.py:362-439` |

All rows: `verified-against-code`. Repairs detail: [diagnostics-repairs.md](diagnostics-repairs.md).

> `DATAFRAME_TIMEOUT` on a cloud write does **not** mean the relay is down. The same error appears
> for a parameter the server's write path cannot handle, and for a firmware NAK when the owning
> mode is disabled (Grid Peak Shaving writes are NAKed and the setpoint zeroed while PS mode is
> off). **Always verify with a read.** Evidence: `hardware-proven` for the PS case (#328,
> confirmed on hardware); `asserted-unverified` for the general taxonomy.

## 7. Firmware update entity

| Behavior | Evidence |
|---|---|
| Module-level `_INSTALL_LOCKS: dict[str, asyncio.Lock]` survive config-entry reloads | `verified-against-code` — `update.py:23-28`, `:100` |
| `in_progress` reports `True` for the **whole chain** while the lock is held, because coordinator-derived status can flicker idle between components of a multi-step update | `verified-against-code` — `update.py:167-189` |
| `async_install` runs `run_firmware_update_to_completion()`, always writes state and requests a coordinator refresh in `finally` (best-effort, must not raise), and raises `HomeAssistantError` when `result.success` is false | `verified-against-code` — `update.py:213-285` |

## 8. Late control discovery

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

## 9. Write-path landmines

| # | Rule | Evidence |
|---|---|---|
| 1 | **A guessed register bit is worse than no local write.** A wrong-but-writable bit is firmware-ACKed: no exception, no cloud fallback, no log above DEBUG — and readback cannot catch it (writing bit 14 sets bit 14 and reads back True whether or not the feature moved). **Gating is the only mitigation** for an unproven bit mapping | `hardware-proven` (#476, toggle-proven on 18kPV) |
| 2 | `FUNC_SMART_LOAD_ENABLE` has **no pinned bit** (179 bit 13 is a placeholder) → Smart Load stays cloud-only | `verified-against-code` — `switch.py:252-262` |
| 3 | `_local_params_can_carry()` probes pylxpweb's `REGISTER_TO_PARAM_KEYS` and doubles as a **version guard**: a param absent from that map can never appear in a local-raw cache, so the switch would report a permanent lying OFF | `verified-against-code` — `switch.py:143-158`, used at `:352-360` |
| 4 | `params_are_local_raw()` must **not** treat the deprecated global-transport fallback as raw. Legacy flat HYBRID entries populate the cache from the cloud (already scaled); treating them as raw shows 12 kW as 1.2 | `verified-against-code` — `coordinator.py:1079-1108` |
| 5 | Voltage scaling is **magnitude-normalized**, not blindly ÷10 — local is decivolts, cloud is already-scaled volts | `verified-against-code` — `number.py:283-294`. See [data-semantics.md](data-semantics.md) §3 |
| 6 | Cloud-only param stores must **never** be seeded into the parameter cache: with a local transport attached, pylxpweb rebuilds `inverter.parameters` from register reads and wipes anything cloud-seeded. Hence the separate `CloudParamStoreSpec` stores with write-seed registries living **outside** `self.data` | `verified-against-code` — `coordinator_mixins.py:303-337`, `coordinator.py:1273-1347` |
| 7 | **Per-field** seed timestamps: a later write to one store key must not renew an older key's seed, or an in-flight read of a legitimate portal change gets clobbered | `verified-against-code` — `coordinator.py:1304-1310` |
| 8 | A seed may only be superseded when a read **observes a concrete value for that field** (`seed.at <= now AND observed[field] is not None`) — not merely because a read started. Otherwise a partial range-read returning `None` clears the seed and reverts a just-written state | `verified-against-code` — seed supersede logic, `coordinator.py:1273-1347` |
| 9 | Only a **delta test** (write → readback → restore) proves a write path works. A no-op write proves format acceptance, not targeting. pylxpweb's cloud `write_parameters({reg: raw})` form-encoded a dict that aiohttp serialized as `data=<key>&data=<key>`, dropping every value **since inception**, while looking successful | `hardware-proven` (the delta test that found it); `asserted-unverified` for the historical scope |
