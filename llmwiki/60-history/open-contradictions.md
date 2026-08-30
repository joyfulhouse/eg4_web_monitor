---
canonical-for:
  - "Unresolved contradictions between project sources (C1-C12)"
sources:
  - docs/claude/FINAL_VALIDATION_REPORT.md
  - docs/claude/MODE_COMPARISON_REPORT.md
  - docs/claude/DEVICE_OBJECTS_DESIGN_PRINCIPLES.md
  - docs/audits/2026-08-02-register-race-performance-audit.md
  - llmwiki/20-pylxpweb/transports.md
  - llmwiki/40-hardware/firmware-re.md
  - issue eg4-hpwq
  - memory/consumption-energy-sources.md
  - memory/soc-charge-limit-101-top-balance.md
  - memory/release-3.4.0-beta.18-status.md
  - https://github.com/joyfulhouse/eg4_web_monitor/issues/570
  - https://github.com/joyfulhouse/eg4_web_monitor/pull/569
verified-against:
  # eg4 pin moved for the C6/C7 refresh (#569 cloud-only routing shipped;
  # #570 sweep evidence ingested); C7's quoted pre-#569 exposure is history.
  eg4_web_monitor: e9853eb
  pylxpweb: 204b95d
last-verified: 2026-08-29
see-also:
  - superseded-claims.md
  - bug-postmortems.md
---

# Open contradictions

Twelve places where two project sources make incompatible claims and **no adjudication
has been made**. Every entry is published UNRESOLVED, with both sides quoted, pending
a human decision.

**Do not resolve one of these by writing a wiki page that picks a side.** If your page
needs a contested fact, cite this page and state that the fact is contested. If you
acquire real evidence, record it here and hand the adjudication to the maintainer.

Each entry names the file it quotes; those files are the durable sources. Grade for every
quotation: `asserted-unverified` — several are historical artefacts under `docs/claude/`
or notes in the maintainer's out-of-repo `memory/` directory, and none has been
re-verified against hardware or code here.

---

## C1 — Unique-ID format: a documented format that was never implemented

> `docs/claude/FINAL_VALIDATION_REPORT.md:148,152` states: `unique_id = f"{serial}_{data_type}_{sensor_key}"` and `…_{batteryKey}`.

> `memory/queue-cleanup-2026-07-26.md`: "The `{serial}_{data_type}_{sensor_key}` unique-ID format documented in eg4's `CLAUDE.md` was **NEVER IMPLEMENTED** — device IDs are `{serial}_{sensor_key}` today and at v3.2.0, and no Python in the repo's history emits a data-type segment. But a test fixture had been written to match the documentation, and a registry-cleanup matcher was then designed to satisfy that fixture."

**Status: UNRESOLVED as a document conflict.** The real emitted forms are
`verified-against-code` and owned by
[`10-integration/entities-identity-availability.md`](../10-integration/entities-identity-availability.md),
so the *fact* is settled. The stale claim nevertheless survives uncorrected in
`FINAL_VALIDATION_REPORT.md`, a file that reads as an authoritative validation report and
carries no warning. What a human must decide: whether that file is deleted,
banner-tombstoned, or kept as an archive.

**Working rule meanwhile:** never lift an entity-ID or unique-ID format from
`FINAL_VALIDATION_REPORT.md`. The mechanism by which this fiction became production
code is documented in [superseded-claims.md](superseded-claims.md), which owns that fact.

---

## C2 — Entity counts per mode disagree across six documents

> `docs/claude/MODE_COMPARISON_REPORT.md` (2026-02-03): "Cloud 451 | Local 415 | Hybrid 452".

> `docs/claude/baseline-*.md` (2026-02-08, v3.2.0-beta.25): cloud 410 / local 360 / hybrid 415.

> `memory/architecture-patterns.md`: "FULL PARITY: Cloud 410/410, Local 360/360, Hybrid 415/415."

> `docs/claude/entity-comparison.md`: refactor branch local = 395, "Parity: FAIL".

> `memory/release-3.4.0-beta.18-status.md`: "cloud 555 / local 588 / hybrid 622".

> `memory/merge-2026-08-03-codex-remediation-wave.md`: "cloud 572 / local 592 / hybrid 630".

**Status: UNRESOLVED.** These are snapshots at different versions, but none of the older
files says so, and `architecture-patterns.md` states its numbers as a standing fact.
What a human must decide: which set, if any, belongs in a wiki page, and whether the
rest are version-stamped or deleted.

**Working rule meanwhile:** treat every entity count as a dated snapshot. Never compare
against a count you did not capture yourself, and compare **registries by unique_id**,
not states.

---

## C3 — "NEVER use `client.api.*`" versus the current write routing convention

> `docs/claude/DEVICE_OBJECTS_DESIGN_PRINCIPLES.md`: "**Rule**: The integration must NEVER directly call `client.api.*` methods… **Exception: THERE ARE NO EXCEPTIONS**."

> `memory/battery-control-mode-soc-vs-voltage.md`: "**Routing convention:** entities/coordinator write via `coordinator.write_named_parameter` (local) and `client.api.control.write_parameters(...)` / `control_function` (cloud) — **NOT the pylxpweb device methods** (those need the inverter's transport + reconnect handling)."

**Status: UNRESOLVED.** Directly opposed. The later note gives a mechanical reason; the
older document is presented as an absolute architectural law. What a human must decide:
whether the older principle is retired outright or scoped to reads.

---

## C4 — Consumption source: an early conclusion was reversed, and both texts still read as current

> `memory/consumption-energy-sources.md`, early section: "**Whole-home consumption = cloud GROUP `todayUsage` (40.5) ≈ `energy_balance`** … So `energy_balance` for the GROUP is right."

> Later section of the **same file**: "**Decisive new finding: `energy_balance` is unusable for LIFETIME consumption.** Sum 10.6 MWh vs true 34.71 MWh." and "whole-home LIFETIME must come from cloud group (CLOUD/HYBRID) or GridBOSS UPS+Load CT totals (LOCAL) — never per-inverter energy_balance."

**Status: UNRESOLVED as a document conflict.** The file is sequenced by date and also
retracts itself internally ("the OLD table above (rows 21-24) used LIFETIME reg 172
which has slave counter-drift"). A reader lifting the first table would ship the wrong
lifetime source. What a human must decide: whether the early table is struck out.

---

## C5 — Register 110 bit 8 versus bit 14

> `memory/issue-476-green-mode-bit14.md`: pylxpweb's 18kPV/`EG4_HYBRID` table mapped `FUNC_GREEN_EN` at bit 8 and was "falsely annotated `# verified`"; a hardware toggle proves bit 14.

> `memory/release-3.5.1-beta.3-shipped.md`: after the correction shipped, the changelog over-claimed a **third** time about bit 8 — saying it "controls something and those toggles were changing it", when "only the write attempt and ACK were established".

**Status: UNRESOLVED — what bit 8 does.** The bit-14 mapping is settled: it is graded by
[`40-hardware/registers.md`](../40-hardware/registers.md) (row `H110 b14`) and its history
is in [superseded-claims.md](superseded-claims.md). What stays open is bit 8. The keeper
records it as **function unknown** (row `H110 b8`); the only thing ever established is
that a write to it was accepted and ACKed. What a human must decide: what, if anything,
bit 8 does. Until then any claim about bit 8's semantics is `asserted-unverified` and must
not be shipped.

**The durable trap:** bit 8 has been over-claimed three times, twice *after* the
correction landed. The mechanism is the register's own behaviour — a wrong-but-writable
bit is firmware-ACKed, so every attempt to describe it produced a confident sentence and
no evidence, and each writer had a successful write to point at.

---

## C6 — Register 161 (AC Charge End SOC): "top-balance candidate" versus "INERT/legacy"

> `memory/release-3.4.0-beta.18-status.md` (beta.26): "reg 161 = pinned SOC-101 top-balance candidate".

> `memory/soc-charge-limit-101-top-balance.md`: "**reg 161 ac_charge_end_soc — RESOLVED, NOT a candidate** … write reg161=101 is a NO-OP even in SOC/Volt mode (success=True but stays raw 0). reg 161 is INERT/legacy on this firmware".

**Status: UNRESOLVED.** The second is a direct test result on an 18kPV; the first is a
portal-derived expectation; and later work (#331) does ship a register-161-backed
entity on off-grid. What a human must decide: whether "inert" is family-specific.

**2026-08-13 second-unit confirmation (strengthens, does not resolve).** The #570 live
sweep reproduced the identical inert signature on a FlexBOSS21 — cloud write success=True,
raw H161 stayed 0 on `valueFrame` readback, original confirmed — and the same firmware
session proved the H161 mapping (range 20..100, ≥H160) **on the CEAA/CCAA off-grid
images**, where no live write has ever been run. Both grid-tied hybrids tested are now
inert; the off-grid half of the question has firmware proof but no live test, so this
stays formally open pending off-grid hardware. Sweep and resolution:
[#570 sweep comment](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287046586),
[#570 resolution comment](https://github.com/joyfulhouse/eg4_web_monitor/issues/570#issuecomment-5287056672);
graded rows in [`40-hardware/registers.md`](../40-hardware/registers.md).

---

## C7 — Register 161 writability: "read-only on FlexBOSS" versus a shipped off-grid write entity

> `memory/release-3.4.0-beta.18-status.md`: pylxpweb b28 "old 'reg 161 read-only' FlexBOSS note family-scoped NOT deleted (grid-tied observation preserved; offgrid LOCAL write UNVERIFIED)".

> The integration ships a register-161-backed control on `EG4_OFFGRID` anyway. `verified-against-code` (`number.py` → `ACChargeEndBatterySOCNumber`, writing with `verify_register=161`), whose own docstring records that "LOCAL Modbus writes to reg 161 are hardware-UNVERIFIED on the off-grid family — all #331 write evidence is the cloud holdParam path".

**Status: UNRESOLVED.** The load-bearing register status lives with the keeper:
[`40-hardware/registers.md`](../40-hardware/registers.md) row `H161` records **LOCAL
writability unresolved** and "do not treat H161 as a safe local write". A writable control
entity for that register is nevertheless shipped on off-grid. What a human must decide:
whether the off-grid LOCAL write is validated, and whether a shipped control may stand on
a write path nothing has confirmed.

**What actually ships (updated 2026-08-29).** Since PR #569 (merged 2026-08-13, "Fixes
#558") the reg-161 write is **routed cloud-only** on EG4_OFFGRID and on any unresolved/
UNKNOWN family — `verified-against-code` at `e9853eb`
(`number.py` → `ACChargeEndBatterySOCNumber.async_set_native_value` passes
`local_write_blocked_reason` from `_offgrid_cloud_only_reason`; `utils.py` →
`async_write_with_cloud_fallback` never attempts the local path and raises on a
pure-LOCAL install). The #570 evidence sweep then derived the protected set over every
scalar register the number platform writes. An earlier revision of this entry recorded
the pre-#569 local-first exposure; that is history now, not the shipped state. What
remains open is the *underlying* writability question: the #570 firmware session proved
the H161 **mapping** on the CEAA/CCAA off-grid images, but no live off-grid write has
ever been run (targeted retest deferred on #570), and the tested grid-tied hybrids are
inert (two units, see C6). This entry stays open until a live off-grid H161 write lands
or the control is withdrawn.

**The durable trap:** the code's stated mitigation is a post-write parameter readback.
Readback proves storage and transport only — never that the firmware acted on the value —
so it cannot detect a write that landed on the wrong target and cannot close this gap. See
the legend's rule in [README](../README.md#rules); it is the same mechanism that let
register 110 bit 8 ship wrong (C5), and the same one live on H179 b11 (#471/#472).

---

## C8 — PV string count: "3 is not a default" versus the shipped default of 3

> `memory/maintainability-findings-and-live-bugs.md`: "**3 is NOT a default** — our devices … just coincidentally have 3 … Authoritative per-model counts are the crux and are NOT in the codebase/docs — must be confirmed, not guessed."

> Same file, E7: "`from_device_type_code` reproduces the old table EXACTLY and **`pv_string_count=3` for every family** (= sensor.py's default) so PV-sensor creation is unchanged."

**Status: UNRESOLVED.** The stated principle and the shipped implementation disagree.
The implementation is explicitly labelled behaviour-neutral, so this is a known gap
rather than a mistake — but nothing tracks it. What a human must decide: whether to
source authoritative per-model string counts, or to document 3 as an accepted default.

---

## C9 — Line-number references drift and cannot all be right

> `issue-348` cites `coordinator_mixins.py:1056`; `issue-261` cites `~626` / `~955`; `issue-253` cites `base_entity.py:407` and `~447` versus `~641`.

**Status: UNRESOLVED, and mostly not worth resolving.** These cannot all still be
correct after the #517-#535 remediation wave. What a human must decide: nothing, unless
a specific citation is load-bearing.

**Working rule meanwhile — this one is binding:** do not migrate line numbers into the
wiki as standalone facts. Migrate symbol names and let the reader grep. Line numbers
are acceptable only on a page whose `verified-against:` commit pins them.

---

## C10 — Availability contract: the audit contests a base-entity behaviour the bug notes rely on

> `memory/issue-261-hybrid-sensor-flicker.md` treats "missing key → unknown, stays available" as the correct, deliberate `EG4BaseSensor` behaviour.

> `docs/audits/2026-08-02-register-race-performance-audit.md`, deferred follow-ups: "base-entity convergence treats None cache state as fresh data (**deliberate, contested**)".

**Status: UNRESOLVED — flagged in the audit as an open design disagreement, not settled.**
This matters more than it looks: multiple shipped fixes (#253, #258, #261, #479) were
built on the first reading. What a human must decide: whether the current availability
semantics are the intended contract or a defect with dependents.

---

## C11 — Off-grid Forced Discharge: portal widget suppressed versus absent

> `memory/release-3.4.0-beta.18-status.md` (beta.23): "INVERSE finding: offgrid portal DOES carry a full 3-window Forced Discharge widget … that we suppress → #317, blocked on hardware write evidence", and later "#317: classic Forced Discharge family (82-89 + reg21 bit10) fully present+clean on XP-v2 — register case complete, write-acceptance the sole blocker".

> `memory/release-3.4.0-history.md`: "**#317 CLOSED** (portal renders NO FD widget on XP-v2 — regs exist but EG4 doesn't expose it)".

**Status: UNRESOLVED.** A direct factual contradiction about whether the off-grid portal
shows a Forced Discharge widget, from the same author days apart. What a human must
decide: re-observe the portal on an off-grid unit and record which is true.

---

## C12 — WLAN listener capacity versus conservative client-access policy

> Pylxpweb `src/pylxpweb/transports/dongle.py` at `204b95d` repeatedly documents a
> one-client assumption and enforces serialized connects/operations. Issue `eg4-hpwq`
> repeats that position as an operational safety rule.

> `40-hardware/firmware-re.md` records the shipped V1.1 firmware server configuration with
> a maximum of two local clients.

**Status: UNRESOLVED.** Pylxpweb's locks and disabled concurrent-read capability are
`verified-against-code` as client policy; the claimed one-socket hardware limit is
`asserted-unverified` (issue `eg4-hpwq`). The configured maximum of two is
`firmware-proven` for the V1.1 image, not a live concurrency result and not proof for V1.2.
These statements are not necessarily incompatible: a listener may accept two sockets while
requiring conservative single-client request access.

A controlled target-firmware test must use two independent clients and record connection
acceptance, simultaneous request behavior, response routing, disconnect behavior and exact
firmware version before any physical-dongle client advertises capacity or concurrency. The
Home Assistant-hosted emulator exposes no local listener, so C12 is no longer a product
gate for that feature; this scope decision does not adjudicate the contradictory evidence.

**Working rule meanwhile:** require exclusive access as a physical-dongle safety policy, do
not state a universal socket limit, and do not use either number as a sizing or compatibility
claim.

---

## Adjudication log

Empty. Append a row when a contradiction is decided; do not delete the entry.

| Ref | Decided | Decision | Evidence |
|---|---|---|---|
| — | — | — | — |
