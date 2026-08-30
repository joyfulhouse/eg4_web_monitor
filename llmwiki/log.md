---
canonical-for:
  - "Chronological record of operations performed on llmwiki"
sources:
  - PR #553 and the sibling chapter PRs
  - the round-by-round adjudication record for this build — a host-local orchestrator
    ledger, NOT published in this repo and not openable by a reader
verified-against: 9f6d6e2
last-verified: 2026-08-09
see-also:
  - index.md
  - README.md
---

# Log

Append-only record of what has been done to this wiki and why. Newest entries at the
bottom.

**Entry format.** Every entry starts `## [YYYY-MM-DD] <op> | <subject>`, so the log stays
parseable:

```
grep '^## \[' log.md | tail -5      # the last five operations
```

**Operations.** `ingest` — a source was read and filed into pages. `query` — a question was
answered from the wiki and the answer was worth keeping. `lint` — a health pass over the
wiki itself. `build` — structural work on the wiki's own scaffolding.

**Rules.** Append, never rewrite: a wrong entry gets a later correcting entry, because the
sequence is the value. Record what changed and *why it was wrong before* — the reasoning is
the durable part, and several entries below exist only because a plausible answer turned
out to be unsound. Keep entries short and link the pages that changed.

---

## [2026-08-09] build | Wiki created — 33 pages across seven sections

Initial construction of `llmwiki/` as a durable knowledge base for the EG4 Web Monitor
integration and its two-repo system, written for an agent that must not guess.

The motivating defect was **duplication**: an accuracy pass over the repo's own
documentation catalogued dozens of software-accuracy defects, and the dominant cause was
one fact living in three or four documents, being corrected in one, and rotting in the
rest. The wiki's answer is the canonical-source policy — one fact, one owner, everyone else
links. Corrections to the source documents themselves ship separately as PR #557.

Sections: `00-orientation`, `10-integration`, `20-pylxpweb`, `30-portal-api`,
`40-hardware`, `50-operations`, `60-history`, plus [`README.md`](README.md) (legend and
rules) and [`_conventions.md`](_conventions.md) (page template).

## [2026-08-09] lint | Ten-round adversarial review — a full three-engine tribunal for four of them

Grade: `asserted-unverified`. The round-by-round record is a host-local orchestrator ledger
that is **not published in this repo**, so a reader cannot open it and this entry is not
independently corroborated here. What a reader can reach is the durable residue:
PRs #551–#556, issue #558, and this branch's commit history.

**Ten rounds**, each closed by a binding adjudication. The three-engine roster held for four
of them:

| Rounds | Third engine | Recorded status at the time |
|---|---|---|
| 1–2 | **substituted** — `pi` running `moonshotai/kimi-k3` in place of the kimi harness | explicitly *not* a protocol-clean attestation. Never reached full-diff coverage: round 1 covered two of six branches, round 2 covered two before its OpenRouter key hit a monthly cap (HTTP 403) and died permanently |
| 3–6 | **absent** | two engines only. kimi reported no usable model provider (`sys_list_models`: `source: none`, provider resolution KeyError); pi was past its billing cap. All four rounds recorded as explicitly not protocol-clean |
| 7–10 | **seated** — kimi as a real engine | three genuine engines, which happened only because the maintainer approved its shell prompts interactively |

So: ten rounds, four with a genuine three-engine tribunal, two with a substituted third
engine, four with two engines.

The four two-engine rounds were avoidable, and the reason is the durable part: the provider
report that justified them was **wrong**. kimi ran here as soon as its approval prompts were
answered. A capability report was taken as ground truth without a live dispatch ever being
attempted, and four rounds ran with a measurably weaker net. The rule that earns: a worker is
unavailable only after a dispatch fails, never on a catalog or capability report alone.

Most rounds produced at least one BLOCKER. No per-round severity split is published here,
because the earlier version of this entry stated a ratio it could not source.

The most valuable findings came from the late three-engine rounds, not the early ones. Round 8
is the convergence case: all three engines independently found the same BLOCKER. **Round 9 is
the stronger argument for the third seat, because there the engines disagreed** — one returned
CLEAN, one four BLOCKERs, one a single BLOCKER. Two of them had independently re-derived the
same count of router bypasses and were both right *within a frame that was too narrow*; the
dissenting engine questioned the frame and was correct. A third lens earns its seat by
disagreeing, not by concurring.

The recurring finding was not factual error but **structural**: the same defect class
regrowing in new places after each local fix.

- **The borrowed-grade loophole** — a page granting an evidence grade whose stated minimum
  proof it did not meet — regrew five times in five different places. Patching each
  instance did nothing; the cause was that two structures (the legend and the ladder) both
  named grades, so whichever one faced weaker evidence eventually bent. Fixed structurally:
  the ladder now classifies evidence and decides write access but **names no grade**, and
  the legend is the sole grading authority. [`_conventions.md`](_conventions.md) carries a
  maintenance note declaring any out-of-legend grant a defect by construction.
- **False safety gates** — text asserting a protection the code does not implement — kept
  reappearing after each local fix. The instance found in the glossary was the *fourth*, and
  it was the most dangerous placement: a reader who learns "unproven implies unwritable" in
  the page that defines what grades mean stops looking for the gate everywhere else. The
  sweep that instance prompted found **four more**. All of them now state the required policy
  and name it as unenforced.
- **Completeness claims** ("every X", "only these three") proved false in every instance
  where the set was derived by code rather than maintained by hand.

## [2026-08-09] lint | Register proof ratio recomputed four times: 45 → 27 → 33 → 30 → 31

The share of register claims backed by hardware proof was published, challenged,
recomputed and republished four times. Each move followed a tightened standard rather than
new evidence:

- **45** — the original figure, which counted claims whose only support was a code comment
  or a `# verified` annotation.
- **27** — after excluding source code, READMEs and comments as hardware evidence.
- **33** — after restoring rows whose durable record genuinely contained a named action,
  raw before/after values and restoration, which the previous pass had over-corrected away.
- **30** — after requiring that a "raw pair" mean actual integer register words. Scaled
  engineering values read through a display conversion are evidence, but they are not raw
  captures.
- **31** — after a single row's evidence was found in a durable issue-tracker artifact
  rather than the code comment that repeated it.

The direction of travel is the point: every move was toward a more defensible number, and
none was a defence of the previous one. Per-row grades are owned by
[`40-hardware/registers.md`](40-hardware/registers.md).

## [2026-08-09] lint | Three frame corrections to the write-path derivation

The most instructive failure of the build. Three consecutive rounds each found a way a
device gets written that the previous round's method **structurally could not see** — not
missing entries within a frame, but a missing frame.

1. A curated list of write paths was replaced by a derivation procedure, after the list
   went wrong three times. Critically, the lists were not *stale*: at the unchanged commit
   they were written against, they were already incomplete. The method was wrong, not the
   upkeep.
2. A grep over the coordinator's write primitives was found blind to writes mediated by the
   library — `_execute_switch_action` resolves a pylxpweb method by name and awaits it,
   touching no coordinator primitive.
3. That, in turn, was blind to entities calling `inverter.<method>()` **directly**, with
   neither the router nor the switch-action helper in the chain; and to background writes
   with no entity at all, such as the hourly DST station-setting sync; and to dispatch
   resolving against a **runtime subclass**, so that verifying a method against the base
   class checks code that never runs.

Two blocking engines independently confirmed an exhaustive count during this arc, and both
were right *within a frame that was itself too narrow*. An exhaustive count over an
incomplete frame reads as rigour and is not.

**Consequence, and the reason this entry matters more than the fixes:** the wiki stopped
claiming to enumerate this surface. [`README.md`](README.md) now publishes the derivation
method and its four proven blind spots, plus a dated inventory labelled incomplete by
default. The blind spots are the durable content; the inventory will rot.

## [2026-08-09] build | Added `index.md` and `log.md`

Added the two navigation files: [`index.md`](index.md) as the content-oriented catalog an
agent reads first, and this log as the chronological record. [`README.md`](README.md)
remains the owner of conventions and the legend and now points at the index for
navigation, so the catalog is not duplicated.

Seeded the log with the build history above, because that history is itself knowledge: it
records which *kinds* of claim have failed here, which is what a future maintainer needs in
order to not repeat them.

## [2026-08-09] lint | The derivation's step-5 discriminator deleted — wrong at two of three call sites

Step 5 of the write-surface derivation told a reader to classify `_execute_switch_action`
callers by the **type** of their `enable_method` argument: a bound callable meant
cloud-routed, a plain string meant a library method the transport may drive local-first.
Checked against the code at `9f6d6e2`, the rule misclassifies two of the three call sites:

- `base_entity.py:1766` passes a plain **string** (`cloud_enable_method: str | None`,
  docstring "Inverter method **name**"), and is the router's own **cloud** leg — cloud by
  construction. The owning page's derivation says to discard this site outright.
- `switch.py:1511` passes a plain **string** from `_WORKING_MODE_METHODS`, on the branch
  guarded `has_http_api() and methods` — the explicitly cloud-only route.
- `switch.py:627` (quick charge) matches the rule. It is the site the rule was read off,
  generalized into a law.

Same root cause as the round's other corrections: **an eg4-side surface feature standing in
for a routing decision that lives entirely inside pylxpweb.** A string/callable split that
separates correctly at one of three sites is exactly the "right by luck" that the same
page's trap table warns about. The rule also contradicted its canonical owner,
[`10-integration/controls-and-writes.md`](10-integration/controls-and-writes.md) § 2.1
("You cannot predict whether a switch-action write goes local by reading eg4. Read the
pylxpweb method."), which is correct — and it contradicted the surrounding text of
[`README.md`](README.md) itself, leaving a reader with two irreconcilable procedures.

Step 5 is now a **pointer** to that page's § 2.3 instead of a second, divergent procedure.
No replacement rule was written: the owner already carries three correct discriminators
(site identity, branch guard, pylxpweb routing policy), and a fourth one living on this
page is what produced the defect.

**Open item — ownership of the runtime-subclass fact.** `20-pylxpweb/write-paths.md` is the
natural long-term owner of "dispatch resolves against the runtime subclass, so
`HybridInverter` can override a base-class routing policy" — currently the third blind spot
in [`README.md`](README.md). Deliberately not moved in this shipping pass: that chapter has
drawn no findings for four consecutive rounds, and reopening it to relocate one fact buys
nothing now. The blind-spot row keeps citing pylxpweb `hybrid.py` directly until a
maintenance session makes the move.

## [2026-08-09] lint | Erratum: this log overstated its own review

The review entry above was published claiming **"Eight-round adversarial review across three
blocking engines"** — that every page was reviewed by three independent engines over eight
rounds, and that "seven of the eight produced at least one BLOCKER". Three claims, all wrong,
all in the flattering direction:

| Claimed | Actual |
|---|---|
| eight rounds | **ten** |
| three independent engines throughout | three genuine engines in **four** rounds; a substituted third in two; **two engines** in four |
| "seven of the eight produced at least one BLOCKER" | a ratio computed on the wrong denominator, and no sourced per-round severity split was ever held |

The entry has been corrected in place rather than left standing with a later retraction —
a deliberate departure from this log's append-never-rewrite rule, taken because the false
version was a **provenance claim**, and a reader who stops at the entry would have carried
away the inflated one. This erratum is the compensating record: it preserves what the entry
said and why it was wrong, which is what that rule exists to protect.

**How it was caught, and why that matters more than the numbers.** Not by re-reading the
entry. The docs-corrections author opened this log to verify an unrelated fact, and found the
round count disagreed with the maintainer's. Peer review of the log worked exactly as
intended — the log was treated as a claim, not as a record.

**Why this is the worst page in the wiki to over-claim on.** The entire thesis here is that
unearned confidence is the defect: every structural finding above is some version of a
statement asserting more coverage than it has. An inflated review count in the wiki's own
provenance entry is that same defect, applied to the wiki's own credibility, and it is the
one page where the over-claim refutes the document making it. Six of the ten rounds ran with
a measurably weaker net; a reader taking the old entry at its word believed every page got
three independent reviews.

**The rule this earns:** claims about *our own process* get graded like claims about the
hardware. This entry is now `asserted-unverified` and says plainly that its detailed record
is not in the repo — because it is not, and the previous version's confident tone was doing
work that no reader-openable source supported.

## [2026-08-11] ingest | H179 b15 = FUNC_ON_GRID_ALWAYS_ON (GH #559)

Pinned Grid Always On to holding register 179 bit 15 from the EG4 mobile app
`Local12KSetFragment.getBitByFunction` smali resolver (app write-path evidence,
graded `firmware-proven` for the name→bit binding; explicitly **not**
`hardware-toggle-proven`). Validated 4-for-4 against confirmed H179 anchors
b3/b7/b9/b10. Updated `40-hardware/registers.md` (split former b12-b15 unknown
row) and `10-integration/controls-and-writes.md` landmine #2 (local write now
allowed once pylxpweb PR #270 maps the bit). #476 wrong-bit ACK caveat retained.

## [2026-08-11] lint | Erratum: H179 b15 grade was overstated as firmware-proven

The prior ingest entry graded the Grid Always On name→bit binding
`firmware-proven`. That grade requires disassembly of a shipped **inverter
firmware** image. The evidence is the EG4 **mobile app** write-path resolver
(`Local12KSetFragment.getBitByFunction`), which the legend grades
`portal-correlated` ("portal or mobile app exposes it, and it agrees with our
reading"). Corrected `40-hardware/registers.md` and
`10-integration/controls-and-writes.md` landmine #2. Still explicitly **not**
`hardware-toggle-proven`; #476 wrong-bit ACK caveat unchanged. Scratchpad smali
path dropped as a durable source (conventions: working artifacts are not
sources); durable cites are #559 / pylxpweb PR #270.

## [2026-08-11] lint | H179 b15 re-graded `app-write-path-proven` (new legend grade)

The erratum above downgraded the Grid Always On name→bit binding to
`portal-correlated`, but that grade's definition ("exposes it, and it agrees
with our reading") undersells what the evidence is: a binding recovered from
the decompiled **write path** of the official EG4 mobile app
(`Local12KSetFragment.getBitByFunction`), validated 4-for-4 against
independently confirmed anchor bits on the same register, each
`portal-correlated` or better — b3 `hardware-toggle-proven` (#135), b7
`portal-correlated`, b9/b10 `portal-correlated` (#48). The legend had no rung for that class, so the erratum's
grade was the least-wrong available — a legend gap, not an evidence change.
Extended `README.md`'s Proof grades with `app-write-path-proven` (below
`firmware-proven`, above `portal-correlated`; minimum proof: decompiled
official-client write-path binding + ≥3 independently confirmed same-register
anchors (`portal-correlated` or better), naming each anchor and its grade;
explicitly NOT proof the firmware honors the write — wrong-bit writes ACK,
#476) and placed the class at annotation-ladder rung 2 (reads; writes only
with a gate). Re-graded `40-hardware/registers.md` H179 b15 and
`10-integration/controls-and-writes.md` landmine #2 accordingly; accounting
header/table re-derived from the audit command (336 counted claims — the
ingest entry above had added the b15 row without updating the 335 total).
Still **not** `hardware-toggle-proven`; #476 caveat unchanged. Durable cites:
#559 / pylxpweb PR #270.

## [2026-08-12] ingest | H179 b15 promoted to hardware-toggle-proven; #559 pins moved to mainline

Release cut for v3.5.1-beta.11 (pylxpweb 0.9.39b11 on PyPI). Two operations:

1. **Grade promotion.** 2026-08-12 live evidence met the `hardware-toggle-proven`
   minimum: portal named toggle of Grid Always On flipped the local raw reg-179
   read 0x1048 → 0x9048 (single-bit XOR exactly 0x8000 = bit 15), and the restore
   returned 0x1048, verified via both cloud and local reads, on FlexBOSS21
   SYNTH00003. `40-hardware/registers.md` H179 b15 re-graded
   `app-write-path-proven` → `hardware-toggle-proven`, scoped to the tested unit
   (component firmware unrecorded); the app-resolver lineage is retained in the
   row as history and still carries the family-wide extension. Accounting ledger
   re-derived: 27 firmware-proven + 5 hardware-toggle-proven = 32 proven of 336
   (awk reproduction run and matched). `10-integration/controls-and-writes.md`
   §ladder row updated to match. The legend's `app-write-path-proven` rung stays
   defined in README.md (count now 0; other rows may use it later).

2. **Re-pin to mainline.** The #559 pages carried PR-branch SHAs that became
   non-mainline on squash-merge, as their own frontmatter comments predicted.
   `registers.md`: pylxpweb `aafc4e3` → `ab87902` (0.9.39b11 release commit;
   #270 merged as `9c10a07`). `controls-and-writes.md`: eg4 `0e2366f` →
   `e146d91` (PR #562 merge), pylxpweb `aafc4e3` → `ab87902`. Claims re-verified
   at the new pins: `FUNC_ON_GRID_ALWAYS_ON` at reg-179 index 15 confirmed at
   `ab87902` (registers.py:935); between the eg4 pins only
   `coordinator_mappings.py`/`coordinator_mixins.py` changed (the #560 merge),
   shifting `_perform_dst_sync` 4563 → 4559 — re-numbered; every other cited
   line re-checked unchanged.

## [2026-08-12] lint | registers.md eg4 pin also moved to e146d91 (tribunal blocker)

The release-cut entry above re-pinned `registers.md` for pylxpweb only; its
`verified-against.eg4_web_monitor` stayed `9f6d6e2` — pre-#562, where Grid
Always On is cloud-only, contradicting the page's own H179 b15 row. Re-pinned
to `e146d91` and re-checked every eg4 line citation on the page: drifted
anchors re-numbered (`switch.py` L280→282, L477→478, L605→606, L789→799,
L958→959, L1196→1197; `device_types.py` L48→55, tightened from the comment to
the constant), and `number.py` L697/L815, `utils.py` L165/L185,
`base_entity.py` L1543 confirmed unchanged. Claim text of the affected rows
(H110 b14 append-before-gate, H179 b11 ACK contract and routing,
H233 `_prefers_cloud_control` boundary) re-read against the files at
`e146d91`. Stale pre-promotion grade comments in code/tests were also
corrected in the same commit (comment-only): `const/modbus.py`,
`const/working_modes.py`, `switch.py` `_WORKING_MODE_PARAMETERS`, and the
contract harness's `_CONTROL_REGISTER_CONTRACT` entry.

## [2026-08-12] lint | generate_entity_id citation after #571 deletion

`10-integration/entities-identity-availability.md` §4.1 still cited
`utils.generate_entity_id` (`utils.py:649-674`) as `verified-against-code` after
PR #571 removed that helper (and its sole feeder `clean_model_name`) as dead code
left from the #550/#566 `_attr_entity_id` cleanup. Reworded to past tense
(removed in #571), re-pinned `verified-against.eg4_web_monitor` `9f6d6e2` →
`7641b96`, refreshed `last-verified` to 2026-08-12, and re-numbered the live
`generate_unique_id` cite (`utils.py:677-693` → `:675-691`). Grep across
`llmwiki/` found no other references; left
`docs/claude/DEVICE_OBJECTS_REFACTOR_PLAN.md` alone (historical).

## [2026-08-12] lint | entities-identity pin e42ed86 — §4 past-tense + page-wide re-cite

Tribunal round 1 on #571: bumping the page pin to a PR-branch SHA (`7641b96`)
falsified §4's present-tense "17 `_attr_entity_id` assignments" claim (grep is
0 since #566) and left in-body `verified-against-code` pins at `9f6d6e2` that
the front matter no longer carried. Re-pinned `verified-against.eg4_web_monitor`
to main-reachable `e42ed86` (`origin/main` at this correction). Rewrote §4 to
past tense for the #566 removals; stated `generate_entity_id` /
`clean_model_name` as **orphans still defined at `e42ed86`**, with deletion
verified at the PR #571 head and landing as the #571 squash. Re-grepped the
whole page and re-numbered drifted cites (inheritance graph, availability
table + 21→22 `def available` frame including `EG4QuickChargeSwitch`, §2.4
overrides, §3 pipeline, §5 unique_id / `generate_unique_id` `:722-738`, §6
DeviceInfo, §7 enabled_default). Rule paid: a pin move is never a local edit.

## [2026-08-12] lint | §2.4 QuickCharge row + ≤10% guard + update.py:54

Tribunal round 2 on #571 (codex MEDIUM/LOW, kimi LOW). (1) §2.4's completeness
claim omitted `EG4QuickChargeSwitch` while the §2 frame already counted it as
contract-changing — added the row at `switch.py:525` (`_offgrid_without_cloud`
gate) and reconciled the frame's "§2.4 plus …" hedge so the table alone owns
the 8 contract-changers. (2) `_guard_total_increasing` suppresses dips
`new_val >= 0.9 * last` including exactly 10% — reworded "smaller than 10%" to
"≤10%" with the boundary test cite. (3) Inheritance-tree `EG4FirmwareUpdateEntity`
anchor `update.py:55` → `:54` (class keyword at pin `e42ed86`).

## [2026-08-13] ingest | Physical WLAN dongle dump and Ethernet local-listener omission

Dumped an attached ESP32-D0WD-V3 WLAN dongle read-only and decompiled its sole
factory application (`V1.1`, app SHA-256 `bf557329…ae1cc18`). Filed the result in
[`40-hardware/firmware-re.md`](40-hardware/firmware-re.md): the plaintext port-8000
server and `C1`–`C4` response dispatcher are intact, but only Wi-Fi startup calls the
server initializer; Ethernet creates `eth_task` and returns. Compared it with official
`WL_LINK_V1_2`, which repeats the omission while changing the server to TLS-PSK, and
recorded the existing one-jump local-listener patch as untested on hardware. Issue
`eg4-x00j` preserves the evidence record. The full flash was not committed because NVS
may contain network credentials.

## [2026-08-13] ingest | Second WLAN dongle factory V1.2 identity

Dumped a second ESP32-D0WD-V3 WLAN dongle read-only and added the specimen to
[`40-hardware/firmware-re.md`](40-hardware/firmware-re.md). Its sole factory application
is `V1.2`; both OTA slots are erased. The 947,680-byte application is byte-identical to
the previously downloaded official `WL_LINK_V1_2.bin` (SHA-256 `325e12b0…fec0f`) and is
not the local-listener-patched artifact. Issue `eg4-gzol` preserves the hardware and
comparison record. The full 8 MiB flash remains uncommitted because its NVS may contain
network credentials.

## [2026-08-13] ingest | V1.2 Ethernet-listener patch flashed and read back

Reviewed the local-listener patch as a two-byte functional jump change plus regenerated
ESP checksum/hash, then wrote it only to the second dongle's factory application partition.
The pre-write readback matched official `V1.2`; esptool's write verification passed; and an
independent post-write readback matched patched SHA-256 `ab67fc31…922551` byte-for-byte.
Recorded the result and its boundary in
[`40-hardware/firmware-re.md`](40-hardware/firmware-re.md): the adapter could not reset the
unit out of the ROM stub, so boot and port-8000 behavior remain unproven pending a physical
power cycle and live probe. Issue `eg4-vr06` preserves the operation record.

## [2026-08-13] query | WLAN dongle serial-number source

Answered where the dongle gets its serial and filed the durable distinction in
[`40-hardware/firmware-re.md`](40-hardware/firmware-re.md). The application contains the
parameter schema and default `0000000000`, while the unit-specific ten-character value is
read from NVS namespace `device_param`, key `device_sn`, at parameter index 9. It is
separate from both the eFuse MAC and the inverter serial. The application-only listener
patch therefore preserved it. Issue `eg4-vypa` records the evidence without publishing
credential-bearing NVS contents; the exact factory provisioning tool remains unknown.

## [2026-08-13] ingest | Home Assistant-hosted dongle-emulation contract

Added [`40-hardware/dongle-emulation.md`](40-hardware/dongle-emulation.md) as the
canonical phased specification for replacing a physical WLAN dongle with a single-owner
local bus plus optional protocol emitters. Repository, firmware, capture and homelab
investigations supported the bus-owner and offline-engine foundation; a two-vendor design
debate disagreed on whether the first useful surface should be cloud emission or a local
listener. The contract preserves that dissent by separating the single-owner foundation,
live cloud participation, controls and port-8000 compatibility into independently gated
phases. It forbids production identities in repository artifacts and records admission,
duplicate-identity, TLS, legal/ToS, write-semantics and rollback evidence as live-use
blockers rather than assumptions. Issue `eg4-asjv` owns the research record.

## [2026-08-13] lint | Dongle-emulation requirements made executable

The first cross-vendor requirements review found that the new dongle-emulation contract
described exclusive bus ownership as a convention, prohibited the synthetic identities its
own tests require, left parser/queue/reconnect/baseline/cutover limits unnamed, and kept the
listener-capacity question outside the contradiction register. Replaced the convention with
a sole raw-transport registry/factory plus static/runtime bypass tests; added explicit
internal policy defaults and boundary behavior; scoped the secret ban to production data;
time-boxed cutover and unknown-write rollback; made performance and capture windows
reproducible; strengthened the affirmative authorization gate; and added C12 to
[`60-history/open-contradictions.md`](60-history/open-contradictions.md).

A primary-source recheck then narrowed C12: pylxpweb enforces and documents conservative
one-client access, while V1.1 firmware is configured for two listener clients. Those may
coexist, so the entry now separates verified client policy, an unverified hardware-limit
claim and firmware-proven configuration, and names the two-independent-client experiment
needed for adjudication.

The convergence review also required a durable sanitized capture summary. Added it and the
complete live-use unresolved set to issue `eg4-asjv`; removed an issue citation that only
contained an early single-client hypothesis; and made parser memory, queue policy,
session-expiry observation, local-only soak and per-field portal parity numerically
testable.

## [2026-08-13] lint | Deployment identities removed from the tracked wiki frame

Replaced deployment-specific identifiers in the affected integration and hardware pages
with stable synthetic identities. The repository guard now derives its text frame from
Git-tracked files and reports only path and category, so future findings cannot disclose
the matched value. Issue `eg4-jhto` and draft PR #575 own the remediation record.

## [2026-08-13] ingest | Dongle emulation limited to direct local transports

The owner clarified that emulation is available only when a qualifying direct local
transport exists: derived `local` and `hybrid` entries may qualify, while cloud-only,
legacy-unmigrated, empty-local and `wifi_dongle`-only entries do not. Updated
[`40-hardware/dongle-emulation.md`](40-hardware/dongle-emulation.md) with mechanical
configuration/setup checks and HYBRID anti-loopback rules covering second polling, cloud
echo re-ingestion, parsed-value reserialization, duplicate identity and listener feedback.

Port-8000 emulation is now permanently out of scope rather than a deferred phase. C12 remains
an unresolved fact about physical-dongle listener capacity, but is no longer a product gate
for this emulator. Planning item 1 and PR #577's offline-sanitizer scope are unchanged.

## [2026-08-14] lint | Identifier guard narrowed to audited deployment values

Corrected PR #575's overbroad private-address rule: generic RFC1918 examples and the
network-scan fallback are operational fixtures, not deployment identities. The guard now
matches the audited private addresses by integer encoding and the audited plant/cloud
identifiers by digest, with mutation checks proving both the false-positive boundary and
continued detection.

## [2026-08-14] lint | Identifier scrub restricted to deployment-owned data

Reworked PR #575's regression guard so every audited address, encoded address, serial,
plant, cloud-host and physical-location value is represented only by a SHA-256 digest.
Synthetic mutation fixtures now prove dotted and bare-integer address detection, serial
matching in prose and entity IDs, camel-case plant fields, location matching, worktree
reads, exact path exclusions and the RFC1918 scan-default boundary. Restored generic
private-network examples and public vendor ingestion endpoints, and repaired the probe,
monitor and firmware-capture helper regressions identified by tribunal review.

## [2026-08-14] lint | Vendor infrastructure excluded from deployment audit

Corrected the prior entry's worktree-reader claim: the guard now reads index blobs so it
audits the exact bytes a commit would contain. Local gitignored vectors prove the committed
digests against the deployment values without republishing them. Vendor cloud hosts, public
cloud addresses, MAC OUIs and generic private gateways remain actionable documentation;
only audited full MACs and deployment-owned identifiers are blocked.

## [2026-08-14] lint | Synthetic script fixtures exempted from identity defaults

The PR merge check exposed that the operational-default rule treated explicitly named
`SYNTHETIC_*` and `DOCUMENTATION_*` constants as live defaults. Narrowed that rule to keep
those safe fixtures while continuing to reject ordinary script identity defaults; the
digest-backed repository scan remains authoritative for audited deployment values.

## [2026-08-14] lint | Maintainer gateway returned to scrub scope

Corrected the vendor-infrastructure boundary: the deployment's UDM gateway is maintainer
infrastructure, not a generic example. Removed its shell default and documentation literals,
restored its dotted and integer digests, and extended the operational-default regression
check to quoted IP assignments in shell scripts.

## [2026-08-21] lint | Single-maintainer release approval policy corrected

Corrected [`50-operations/release-process.md`](50-operations/release-process.md), which still
required a PyPI environment reviewer other than the dispatcher. That rule was stale after
pylxpweb PR #306 and is impossible in a repository with one human maintainer. The current
contract intentionally requires zero reviewers and locks that decision with
`test_binding_releases_merged_pr_with_zero_reviews`; release safety remains enforced by CI,
tag-bound protected environments, disabled admin bypass, OIDC scoping and terminal artifact
verification. GitHub branch protection and environments already required zero approvals, so no
repository setting was weakened.

## [2026-08-29] ingest | #570 off-grid write-evidence sweep — grades, H161 anomaly, protected-set derivation

Ingested the issue #570 evidence artifacts into the keeper
([`40-hardware/registers.md`](40-hardware/registers.md)): the `fw-verify-offgrid-writes`
firmware verdicts (2026-08-12, CEAA 12000XP + CCAA 6000XP ARM+DSP images — H158–H161
mapping/range checks `firmware-proven`; H66 writable 0..100 but semantics NOT verifiable;
H21 b7 `firmware-proven` inert; H233 CEAA rejection `firmware-proven`, CCAA partial) and
the 2026-08-13 live cloud toggle/restore sweep (FlexBOSS21 + 18kPV: H158/H159/H160
`hardware-toggle-proven` on the tested units; H161 write-inert on a second grid-tied unit
— resolved as the pre-documented family quirk, strengthening C6, not a write-path fault).
Accounting moved 336→345 counted claims, 32→41 proven. Recorded both pylxpweb range
conflicts (H160 min 1 not 0; H66 raw ≤100) as filed (#271/#272) and fixed (pylxpweb PR
#273, merged). Grade rules honored: the toggle proofs are scoped to the tested units
(firmware unrecorded); the firmware proofs are mapping/range proofs and did NOT promote
H66's semantic row or license a local-write upgrade for H158–H161 (recorded as a
version-gated candidate on #570 only).

Falsification sweep: PR #569's shipped cloud-only routing had invalidated the pre-#569
"local-first, ungated" narratives in
[`10-integration/data-semantics.md`](10-integration/data-semantics.md),
[`10-integration/controls-and-writes.md`](10-integration/controls-and-writes.md) §1/§2.4,
the keeper's H233 boundary and H227 shipped-path notes, README's keeper cache, and
[C7](60-history/open-contradictions.md) ("not routed cloud-only") — all updated to the
shipped fail-closed routing, with the pre-#569 exposure preserved as history. C6/C7 stay
open pending a live off-grid H161 write.

Code half of the audit (same change set, tracked on #570): the protected set is now
derived, not enumerated — every scalar holding register the number platform writes through
the local-first router lacks a local off-grid delta-test, so all of them (74, 101, 102,
105, 125, 202, 227, 228, 169, 100, 22, joining 66/158–161) route cloud-only on
EG4_OFFGRID/unresolved families. Blind spots recorded in `_offgrid_cloud_only_reason`'s
docstring: bit-level switch/select writes, schedule `write_register` calls, direct library
calls, and the QuickChargeDuration live-adjust remain outside the gate, with per-bit risk
held by the keeper and C7.

## [2026-08-29] lint | QuickChargeDuration blind-spot rationale corrected — reg-234 local write was reachable on off-grid

The previous entry (and the `_offgrid_cloud_only_reason` docstring it described) claimed the
QuickChargeDuration live reg-234 adjust could not run on off-grid because it is "gated on a
live local H233 b0 read, which the recorded off-grid boundary itself rejects." A PR #600
adversarial-review finding (Kimi, MED) exposed that as wrong, and code adjudication confirmed
it — wrong twice: (1) on EG4_OFFGRID + HYBRID the active check is **cloud-routed**
(`coordinator_mixins.py` → `_quick_charge_prefers_cloud`, the #296 mitigation), so a
cloud-started charge reports active without any local H233 read standing in the way; (2) the
H233 rejection is CEAA-scoped anyway — the keeper's own CCAA row in this same change set says
the address is implemented there. The local reg-234 write on off-grid HYBRID was therefore
reachable **by design** ("#296 round 2":
`coordinator_mixins.py` → `_read_offgrid_quick_charge_minute` deliberately mirrors reg 234
locally so the number's read and write sides agree), on a register with no off-grid write
evidence (H234 `portal-correlated`). The failure mechanism was the classic one: a
lineage-scoped negative claim quietly generalized to the family.

Fix (same change set): the live-adjust branch now requires
`is_positively_non_offgrid_family`; off-grid/unresolved families take the CLOUD-branch
behavior (store the start preference, applied as the next cloud start's `minute` parameter).
Regression tests in `tests/test_offgrid_write_routing.py`
(`TestQuickChargeDurationOffgridLiveAdjust`). Pages updated: the keeper's H234 row,
[`10-integration/data-semantics.md`](10-integration/data-semantics.md) gate-limits note, and
[`10-integration/controls-and-writes.md`](10-integration/controls-and-writes.md) router
parameter row. The local reg-234 **read** (off-grid HYBRID mirroring) is unchanged — reads
carry no wrong-write hazard.

## [2026-08-29] lint | Review round 2 — H22 ledger gap closed, H105 range mismatch, stale evidence claims, change-set pins

Corrections from PR #600 adversarial round 2 (Codex + Grok), all landed in the PR branch
commit `1f39ad1`:

- **H22 was a shipped control with no keeper row** — a violation of the every-claim-graded
  rule that the sweep's own frame derivation used ("no ledger row at all") without filing
  the row it implied. Added the H22 row (`portal-correlated`: canonical pylxpweb definition
  at `ab87902` + the PR #359 verified named-volts cloud route; the reg-22-carries-LSP-bits
  note and the 140 V firmware floor recorded `asserted-unverified`). Accounting 345→346
  counted claims, 41 proven (11.8%). The README partial-inventory line and the code/test
  comments that said "no ledger row" were updated — that phrasing was a fact about a gap,
  not a permanent property.
- **H105 range mismatch surfaced by the sweep routing**: the entity advertised 0–100 while
  the canonical H105 definition and pylxpweb's `set_battery_soc_limits` enforce 10–90, so
  the new off-grid cloud-only route raised a raw ValueError at the boundaries. The entity
  (the outlier) now advertises/validates/reads 10–90; H125 is 0–100 everywhere and
  unchanged. The keeper needed no change — the canonical definition was already right.
- **Stale evidence claims**: `_offgrid_cloud_only_reason`'s rationale still carried the
  pre-sweep H158/H159/H66 wording this same change set's keeper rows had superseded;
  README's write-surface worked example still said pure-LOCAL off-grid drives the local
  H233 path (closed by PR #569); controls-and-writes §1.3 still described the
  QuickChargeDuration error contract without the family gate. All updated — same defect
  class as the round-1 finding: a page or docstring asserting what a sibling document said
  before the same change set falsified it.
- **Change-set pins**: claims describing this PR's own routing were pinned only to
  pre-PR commits. Following the #559 precedent, the affected pages' front matter now
  names the PR #600 branch commit `1f39ad1` for those claims, to be re-pinned to the
  mainline merge SHA at the release cut.

## [2026-08-29] lint | Review round 4 — quick-charge switch fails closed on unresolved families; firmware bounds reach the entities

Corrections from PR #600 adversarial round 4 (Codex 3 MED + 2 LOW, Grok corroborating):

- **Quick Charge switch, unresolved families**: `_prefers_cloud_control` gated on
  *positive off-grid identification*, so an UNKNOWN/missing family with cloud + local
  transport still ran pylxpweb's local-first paired H233/H234 write. #569's recorded
  rationale ("the fallback works") predates the CCAA firmware verdict: on CCAA the H233
  write is silently ACCEPTED with unproven bit-0 semantics, and a silent ACK never
  triggers a fallback — the #476 mechanism. The predicate now fails closed
  (`not is_positively_non_offgrid_family(...) and has_http_api()`); resolved non-off-grid
  families keep local-first. Keeper H233 boundary row, data-semantics and
  controls-and-writes §2.4 updated to the new routing.
- **Firmware-proven bounds now reach the entities, family-scoped because the evidence
  is**: AC Charge Power (H66) advertises/accepts at most 10 kW on off-grid/unresolved
  (CEAA/CCAA writer rejects raw >100 — the 15 kW ceiling survives only on positively
  resolved non-off-grid families, where it is shipped status quo without firmware proof
  either way); AC Charge Start SOC (H160) floors at 1 on off-grid/unresolved (0 →
  exception 03 — resolved non-off-grid keeps the shipped 0 floor, unverified but not
  disproven). Read windows track the same bounds so out-of-window values read unknown
  instead of tripping HA's out-of-range state error. Boundary tests added both sides.
- **Docstring falsifications**: the QuickChargeDuration class docstring still described
  an unqualified LOCAL/HYBRID live reg-234 adjust, and
  `_read_offgrid_quick_charge_minute` still said the setter "writes reg 234 whenever a
  local transport is configured" — the exact sentence a future "restore read/write
  symmetry" fix would cite to reopen the gated write. Both now state the fail-closed
  family gate explicitly, and the mirror-read helper carries a do-not-restore-symmetry
  warning naming what the symmetry claim would reopen.

## [2026-08-29] lint | Review round 5 — one derivation pass over every fail-open `is_offgrid_family` site

Rounds 4 and 5 found the same defect class three times (switch write gate, coordinator
status gate, fail-open creation branch), so this round ran ONE derivation pass over every
`is_offgrid_family(` call site instead of fixing the reported instances alone. Result,
landed in the PR #600 branch:

- **Creation/suppression gates stay fail-open by design** (`number.py`, `switch.py`,
  `time.py` gate table, Repairs flags, off-grid read blocks, off-grid-only
  sensors/buttons): suppression needs positive identification (#259/#219), and the
  off-grid-only surfaces are conservative when they fail open (absence, or read-only).
- **Every write or routing decision now fails closed on
  `is_positively_non_offgrid_family`**: the coordinator's `_quick_charge_prefers_cloud`
  (Grok MED — round 4 moved unresolved-family WRITES to the cloud while the READ side
  still sent the next status poll to the local H233/H234 detail read, reintroducing the
  #296 invisibility bug on exactly the protected population); the fail-open-CREATED
  grid-tied number setters reachable in the first-run window before family resolution
  (Codex MED — H67/H82/H83/H103/H116 route cloud-only, and the RAW H117 write, having no
  cloud path, is refused outright); and the schedule time entities' packed
  `write_register` path (found by the pass, not by a reviewer — the clear-schedule
  button had already declared local off-grid schedule writes unsanctioned while the
  entities still wrote local-first).
- Pages updated: the keeper's schedule-write-boundary row, README's H117 cells,
  controls-and-writes router-parameter row, data-semantics gate table and limits note.
- The remaining fail-open-adjacent write surfaces are the bit-level switch/select
  writes and direct library calls — recorded in `_offgrid_cloud_only_reason`'s
  docstring and C7, deliberately not converted (per-bit mappings, different mechanism,
  tracked risk).
