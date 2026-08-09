---
canonical-for:
  - "Unresolved contradictions between project sources (C1-C11)"
sources:
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - superseded-claims.md
  - bug-postmortems.md
---

# Open contradictions

Eleven places where two project sources make incompatible claims and **no adjudication
has been made**. Every entry is published UNRESOLVED, with both sides quoted, pending
a human decision.

**Do not resolve one of these by writing a wiki page that picks a side.** If your page
needs a contested fact, cite this page and state that the fact is contested. If you
acquire real evidence, record it here and hand the adjudication to the maintainer.

Quotations are reproduced from the migration corpus (§4), which quoted the underlying
files. Grade for every quotation: `asserted-unverified` — the corpus is the source, and
several of the quoted files are historical artefacts under `docs/claude/` or in the
maintainer's out-of-repo memory directory.

---

## C1 — Unique-ID format: a documented format that was never implemented

> `docs/claude/FINAL_VALIDATION_REPORT.md:148,152` states: `unique_id = f"{serial}_{data_type}_{sensor_key}"` and `…_{batteryKey}`.

> `memory/queue-cleanup-2026-07-26.md`: "The `{serial}_{data_type}_{sensor_key}` unique-ID format documented in eg4's `CLAUDE.md` was **NEVER IMPLEMENTED** — device IDs are `{serial}_{sensor_key}` today and at v3.2.0, and no Python in the repo's history emits a data-type segment. But a test fixture had been written to match the documentation, and a registry-cleanup matcher was then designed to satisfy that fixture."

**Status: UNRESOLVED as a document conflict.** The repo `CLAUDE.md` now carries the
correction, and the real emitted forms are `verified-against-code` (see
[repo-map.md](../00-orientation/repo-map.md)). The stale claim nevertheless survives
uncorrected in `FINAL_VALIDATION_REPORT.md`. What a human must decide: whether that
file is deleted, banner-tombstoned, or kept as an archive.

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

> `docs/DATA_MAPPING.md:545` now says bit 14 with the correction inline; repo `CLAUDE.md` also says bit 14 "(hardware-verified 2026-07-21, #476; historic bit-8 mapping was wrong)".

**Status: UNRESOLVED in one narrow respect.** No live contradiction remains between
those two files — bit 14 is `hardware-proven` and is recorded in
[superseded-claims.md](superseded-claims.md). But `release-3.5.1-beta.3-shipped.md`
records that the changelog then over-claimed a **third** time about bit 8, saying it
"controls something and those toggles were changing it — only the write attempt and
ACK were established". What a human must decide: what, if anything, bit 8 does. Until
then, any claim about bit 8's semantics is `asserted-unverified` and must not be shipped.

---

## C6 — Register 161 (AC Charge End SOC): "top-balance candidate" versus "INERT/legacy"

> `memory/release-3.4.0-beta.18-status.md` (beta.26): "reg 161 = pinned SOC-101 top-balance candidate".

> `memory/soc-charge-limit-101-top-balance.md`: "**reg 161 ac_charge_end_soc — RESOLVED, NOT a candidate** … write reg161=101 is a NO-OP even in SOC/Volt mode (success=True but stays raw 0). reg 161 is INERT/legacy on this firmware".

**Status: UNRESOLVED.** The second is a direct test result on an 18kPV; the first is a
portal-derived expectation; and later work (#331) does ship a register-161-backed
entity on off-grid. What a human must decide: whether "inert" is family-specific.

---

## C7 — Register 161 writability: "read-only on FlexBOSS" versus a shipped off-grid write entity

> `memory/release-3.4.0-beta.18-status.md`: pylxpweb b28 "old 'reg 161 read-only' FlexBOSS note family-scoped NOT deleted (grid-tied observation preserved; offgrid LOCAL write UNVERIFIED)".

> Repo `CLAUDE.md` register table: "AC Charge Start / End Battery SOC | 160 / 161 | … End 0-100% on EG4_OFFGRID only (read-only on grid-tied, #332 note)".

**Status: UNRESOLVED.** The two are consistent if read carefully, but the shipping
status is "offgrid LOCAL write UNVERIFIED" while the register table presents it as a
control. What a human must decide: whether the register table gains an explicit
verification-status column, and whether the off-grid local write is validated.

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

## Adjudication log

Empty. Append a row when a contradiction is decided; do not delete the entry.

| Ref | Decided | Decision | Evidence |
|---|---|---|---|
| — | — | — | — |
