---
canonical-for:
  - "What llmwiki is and how to navigate it"
  - "Canonical-source policy"
  - "Evidence-grade legend and grading rules"
  - "Freshness discipline"
sources:
  - CLAUDE.md
  - docs/ARCHITECTURE.md
  - docs/CONFIGURATION.md
  - PR #557 (documentation-defect corrections)
  - issue #549
  - memory/issue-476-green-mode-bit14.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# llmwiki

Durable knowledge base for the EG4 Web Monitor Home Assistant integration and its
two-repo system. Written for an LLM agent that must not guess, and for a hurried
human. Terse, table-heavy, every factual claim carries an evidence grade.

**This is a knowledge base, not documentation.** User- and contributor-facing docs
live in `README.md`, `INSTALL.md`, and `docs/`. `llmwiki/` holds what an agent needs
to work on the system correctly: architecture, register evidence, failure history,
and the traps that have caused shipped bugs.

## Why it exists

An accuracy pass over the repo's own documentation catalogued dozens of software-accuracy
defects across `CLAUDE.md`, `README.md`, `docs/*.md`, and CI config; the corrections are
applied in PR #557 ("correct 38 verified documentation defects against code") and two
were severe enough to file as issues (#549, #550). Three verified here directly: the
config-flow package path, the nonexistent `const.py`, and a fourth docker mode absent
from every document. The dominant cause was not neglect: it was **duplication**. The
same fact — polling intervals, entity-ID formats, config-flow paths, the register table —
lived in three or four documents, was corrected in one, and rotted in the rest.
`llmwiki` answers that with a single rule: one fact, one owner.

## Navigation

| Directory | Owns |
|---|---|
| `00-orientation/` | What the system is, where code lives, vocabulary |
| `10-integration/` | HA integration internals: architecture, data flow by mode, entity identity/availability, controls and writes, config flow, diagnostics, data semantics |
| `20-pylxpweb/` | The `pylxpweb` library: API surface, transports, models and scaling, write paths, release and pinning |
| `30-portal-api/` | EG4 cloud portal API: auth/session, endpoint table, schemas and scaling, errors |
| `40-hardware/` | Registers (with per-claim evidence grades), firmware reverse engineering, GridBOSS, probing playbook |
| `50-operations/` | Dev environment, quality gates, release process, issue pipeline |
| `60-history/` | Bug postmortems, open contradictions, superseded claims |
| `_conventions.md` | The page template every writer follows |

### Cold-start reading order

1. `00-orientation/what-this-project-is.md` — the four moving parts and how a value travels.
2. `00-orientation/repo-map.md` — where code actually lives (several paths are not what the old docs say).
3. `_conventions.md` — before writing any page.
4. `60-history/superseded-claims.md` — before trusting anything you read elsewhere.
5. The `10-`…`50-` directory covering your task.

## Canonical-source policy

1. **Every page declares `canonical-for:`** — the list of facts it owns.
2. **A fact has exactly one owner.** Other pages link to the owner; they do not restate it.
3. **Need a fact you don't own?** Link to it. If a sentence is unreadable without the
   value, restate at most one line and name the owner in the same sentence.
4. **Two pages claiming the same fact is a defect.** The earlier `canonical-for:` claim
   wins; the later page deletes its copy and links.
5. **A fact nobody owns** goes in the page whose subject it belongs to — add it to that
   page's `canonical-for:`. Historical or contested facts go to `60-history/`.
6. **Never copy a fact out of code into the wiki when the code is the natural lookup.**
   Version and dependency pins live in `custom_components/eg4_web_monitor/manifest.json`;
   polling defaults live in `const/config_keys.py`. Wiki pages point at them.

## Evidence-grade legend

**This page is the single legend for the whole wiki.** The vocabulary is exactly **nine
names**: the eight proof grades below, plus `refuted`. No chapter may define, rename, or
locally weaken a grade, introduce a synonym, or carve out an exception that lets a claim
borrow a grade it cannot meet. If you need a distinction that is not here, add it here. A
chapter-local legend does not stay parallel: it drifts toward whatever that chapter's
evidence happens to support, the weaker definition wins by proximity, and every page that
links to it inherits the weakening silently.

### Proof grades

Every factual claim carries exactly one. Ordered strongest first.

| Grade | Means | Minimum proof to use it |
|---|---|---|
| `verified-against-code` | The cited source implements or locks the claim, at the commit in `verified-against:` | Cite the repo path and the symbol (`coordinator_mixins.py` → `_TRANSPORT_OVERLAY`) |
| `firmware-proven` | Established by disassembling a shipped firmware image | Cite the image and family, and the code site — function, increment site, dispatcher entry |
| `hardware-toggle-proven` | A named vendor control or UI action on the target family, correlated to raw values captured before and after, with the original state restored | Cite the action, the raw before/after pair, and the family. Component firmware version is **scope metadata, not a grade gate**: record it when it is known, and when it is not, say so and scope the claim to the tested unit |
| `hardware-proven` | Umbrella for the two above. **Requires a before/after raw value pair.** | As above. A source that merely records "a live-device result", with no raw pair, is `asserted-unverified` — however it was phrased |
| `portal-correlated` | The EG4 portal or mobile app exposes it, and it agrees with our reading | Cite the endpoint, field, or widget |
| `lineage-inferred` | Inherited from a related family or a neighbouring register, with no direct evidence on the target | Name the family or register it was inherited from |
| `inferred` | Deduced from an adjacent proven fact | State what it was inferred from |
| `asserted-unverified` | A source states it; nothing here independently corroborates it | Name a **durable** artifact: a repo path, a `memory/*.md` filename, an issue or PR number |

#### Negative claims

A *negative* claim — that a register is absent, rejected, dead, or repurposed on a
family — is graded exactly like any other claim. No before/after pair can exist for it,
so `hardware-proven` and `hardware-toggle-proven` are simply **unavailable** to it. There
is no exception: a claim that cannot meet a grade's minimum proof does not get to borrow
the grade because the proof is impossible in principle. Grade what was actually captured.

| What you actually have | Grade it earns |
|---|---|
| Disassembly of a shipped image showing the register is unimplemented, or implemented as something else | `firmware-proven` |
| The portal or app omits the field, or exposes it in a way that agrees with our reading | `portal-correlated` |
| A preserved wire-level exchange — the request and the device's exception response (ILLEGAL DATA ADDRESS, NAK), quoted raw | `asserted-unverified`, naming the durable artifact that holds the capture |
| A recollection that "it was rejected", or a read logged as 0, with no preserved exchange | `asserted-unverified`, naming the person, issue, or note |

The last two rows carry the same grade and are not equally useful: only a preserved
exchange can be re-examined by the next reader, so capture it and cite it. A negative
claim that disproves a documented positive one is additionally marked `refuted` (below).

`firmware-proven` stands on the disassembly itself, so a negative claim can reach it — a
register shown to be a counter is proven not to be power (register 123 on the off-grid
image is the worked case). It does **not** thereby become `hardware-proven`: the umbrella
keeps its pair requirement, and a disassembled negative claim never acquires one.

**Scope every negative claim to the units tested.** "Reads 0 on every unit we tested" and
"no family has this register" are different claims, and only the first has ever been
observed here.

### Status, orthogonal to proof strength

| Status | Means | Use |
|---|---|---|
| `refuted` | Actively disproven. **Must not regress.** | Not a weak proof grade — a refutation can itself be `hardware-toggle-proven`. Pair `refuted` with the grade of the disproof and cite it. Applied to a register bit it means: the historical semantic is false **and** no replacement semantic is established, so the bit **must be kept** write-inaccessible — a requirement on us, not a guarantee about the shipped code (see the ladder's binding consequence). |

### Rules

- **Never upgrade a grade you cannot justify.** Downgrade freely; downgrading is cheap
  and correct. Upgrading requires new proof recorded on the page.
- **Readback proves storage and transport only.** It says nothing about semantics. A
  wrong-but-writable bit is firmware-ACKed: writing register 110 bit 8 succeeded, raised
  nothing, logged nothing above DEBUG, and read back true — while Green Mode never
  moved. See the proof standard for bit semantics under the register-annotation ladder
  below. A write → readback → restore **delta test** therefore splits into two claims:
  the code path is `verified-against-code`, the physical semantic is
  `asserted-unverified`. It is never `hardware-proven` — nothing physical was observed.
- **A live cross-transport read is agreement, not observation.** Reading the same
  parameter two ways (raw `595` over Modbus against the portal's `59.5`) also splits: the
  agreement is `portal-correlated`, the transformation that produced it is
  `verified-against-code`. Neither half is a before/after pair, so neither is
  `hardware-proven`.
- **Never grade `hardware-proven` on the strength of source code, a README, or a code
  comment.** Downgrade to `verified-against-code` for what the code does, or
  `asserted-unverified` for the hardware claim the comment repeats.
- **Never cite a prose document as `verified-against-code`.** Re-verify against the real
  source file, or grade `asserted-unverified` naming the document. Citing `CLAUDE.md` as
  code re-imports the exact defect class this wiki exists to end.
- **Do not import a `# verified` annotation as any proof grade.** In this project's
  register tables it has historically meant "the names matched", not "a toggle was
  observed" — the direct cause of issue #476
  (`60-history/superseded-claims.md`).
- **Notation is `` `backticks` ``,** never `[brackets]` and never bare words. Grades are
  machine-extracted.
- **Contradiction is not resolved by grading.** If two sources disagree and neither is
  provable here, both go to `60-history/open-contradictions.md` marked UNRESOLVED.
  Do not pick a winner to make a page read cleanly.

### The register-annotation ladder

Scoped to **register and bit annotations only** — the one case where getting it wrong
writes to unknown hardware. The ladder **classifies evidence and decides write access**.
It does not grade. Cross-linked from `40-hardware/registers.md`, which applies it per row.

| Rung | What evidence exists | What may be built on it |
|---|---|---|
| 1 | A named vendor/UI action on the target family, an independent observation that the intended physical state changed, a complete raw before/after delta, and restoration | Reads and writes |
| 2 | A canonical pylxpweb definition **plus** an independent hardware capture | Reads; writes only with a gate |
| 3 | A canonical definition alone | Read-only diagnostics |
| 4 | A vendor or third-party table | Nothing. It is a family-specific hypothesis |

**Which grade this evidence earns is determined solely by the Evidence-grade legend
above.** If evidence does not meet a grade's stated minimum it does not receive that
grade — there is no exception, no ladder shortcut, and no rung that substitutes for a
requirement. A rung says what you have, never what you may call it.

**Binding consequence:** a bit at rung 3 or 4 **must be kept** write-inaccessible — no
entity, no named-write path, no placeholder key reachable by a write helper. Gating is the
only mitigation for an unproven mapping, because a wrong write cannot be detected after
the fact.

#### The rule is not enforced anywhere in the code

**The rule above is a requirement on us. It is not a description of the current code, and
nothing implements it.** There is no gate that consults a register's evidence grade before
writing it. Grades live in this wiki; the write paths are built from tables in the code
that do not reference them. So the set of writes that violate the rule is not a list
anyone maintains — it is a **consequence of those tables**, and it changes whenever they
do.

Three earlier revisions of this section published a curated list of violations: first two
entries, then three, then a reviewer walked the whole surface and found at least six
classes. Each list was accurate when written and stale within a round. **Do not curate a
fourth.** Derive it.

**How to derive the current local-write surface** (`verified-against-code`, all in
`custom_components/eg4_web_monitor/`):

| Step | Where |
|---|---|
| 1. Working-mode switches | `switch.py` → `_WORKING_MODE_PARAMETERS` — the register/bit each switch writes |
| 2. Always-on number entities | `number.py` → the `entities.extend([...])` block commented "Always-on controls"; these are created for **every inverter, with no family gate** |
| 3. Voltage-limit numbers | `number.py` → `VOLTAGE_NUMBER_SPECS`, expanded one entity per spec in that same block |
| 4. Writes that bypass the router | Grep **three method names** — `write_named_parameter`, `write_raw_parameter`, `write_register` — **matched on the method, not the receiver**, across the control platforms (`number.py`, `switch.py`, `select.py`, `time.py`) **plus `base_entity.py` and `coordinator.py`**. Then classify every hit by the rules below. At `9f6d6e2` this yields two bypasses — `QuickChargeDurationNumber` and `StartChargePowerNumber` (the latter a **raw** register write) — but run the check rather than trusting that |

Cross each writable target against
[`40-hardware/registers.md`](40-hardware/registers.md). Anything the keeper grades below
rung 2, or does not carry a row for at all, is a write standing on an unproven mapping.

**Classifying a step-4 hit.** A hit is a bypass only if no router call encloses it. Three
things make that harder than it looks, and each has already produced a wrong answer:

| Trap | What goes wrong | Worked example at `9f6d6e2` |
|---|---|---|
| **Narrow method set** | `write_register` is a third write method, and `time.py` documents it as that platform's uniform local path. A scan for only the other two cannot see a bypass that uses it | `time.py` → the packed schedule write, inside a `_local_write` closure |
| **Matching the receiver** | Searching `coordinator.write_*` misses the coordinator's calls to **itself**, which read `self.write_*` | `coordinator.py` → the battery-regime `_local_write` closure calls `self.write_named_parameter` twice |
| **Stopping at the first enclosing `def`** | A helper reached *from* a `local_write` closure is router traffic one level deeper, and looks like a bypass if you do not follow the call chain | `base_entity.py` → `_execute_named_parameter_action` calls `coordinator.write_named_parameter`; its only caller is the `local_write` closure in `_execute_local_with_fallback`, so it is **not** a bypass |

**Trace the call chain, not the nearest `def`,** and **discard matches inside docstrings and
comments** — `write_named_parameter`'s own docstring carries two usage examples that a
grep reports as call sites, inside the definition of the method being searched. Counting
them would invent two coordinator "bypasses" that do not exist.

The first two traps hide real bypasses; the last two invent false ones. A scan that lands
on the right answer without applying all four is right by luck — both current bypasses
happen to be `number.py` named/raw calls, which is exactly the coincidence that let the
narrower check look sound.

**Match on raw register constants as well as parameter names.** Steps 1-3 find entities
through their named parameters (`PARAM_HOLD_*`, `FUNC_*`), so a search built only on those
names silently misses any entity that addresses a register **by number** through a `REG_*`
constant. `StartChargePowerNumber` is the worked example: it writes register 117 as
`coordinator.write_raw_parameter(REG_PTOUSER_START_CHARGE, …)` and appears in no
parameter-name search at all. A review of this surface that greps only parameter names will
report a clean result and be wrong — that is not hypothetical, it is how H117 was missed.
Grep `REG_` alongside `PARAM_` and reconcile both against the keeper.

**Family gates do not narrow this set as much as they appear to.** `utils.py` →
`is_family_control_supported` fails **open** by design: a device whose family is missing or
`UNKNOWN` keeps every control. Never assume a family gate suppressed anything.

**What "local-first" means depends on the mode**, and the difference matters here —
`verified-against-code` (`utils.py` → `async_write_with_cloud_fallback`, whose contract
states "without a cloud client the local error propagates unchanged"):

- **HYBRID** — local write first, cloud fallback on failure. A wrong-target local write is
  ACKed, so the fallback never fires and nothing is logged.
- **LOCAL** — there is no cloud client, so there is no fallback. The local write is the
  only write.

#### Registers the keeper marks unresolved

This table is **not** the list of violations — the derivation above is. It is the narrower
set satisfying **both** of these at once:

1. the keeper flags the register's **writability or family scope** as unresolved or
   disputed, **and**
2. a **shipped entity writes it**.

Both conjuncts are load-bearing. The keeper carries other unresolved rows — H231 and the
"Function unknown" bits H110 b5/b6/b8/b9 and H179 b8 — that no entity writes; they fail the
second conjunct and are correctly absent here. Reading the criterion as condition 1 alone
would predict a much larger table than this one.

Because condition 1 is read off the keeper, this table is a **projection** of it rather
than a hand-maintained list — it moves when the keeper's rows move, which is the only
reason it is safe to publish here. That coupling is real and it is tight: this table went
stale inside a single review round when the keeper gained rows while this page was being
edited. If it disagrees with the keeper, the keeper is right and this table is behind.
Grades below are quoted from the keeper; this section reports, it does not award.

| Register | Entity that writes it | What the keeper marks unresolved |
|---|---|---|
| H179 b11 | AC Couple switch | `lineage-inferred`; status "current; live write risk unresolved" |
| H161 | AC Charge End Battery SOC (`EG4_OFFGRID`) | `portal-correlated`; status "current; write unresolved" |
| H110 b14 | Off-Grid / Green Mode switch | Proven on the tested 18kPV, but the switch is created for *every* family and the 12000XP/6000XP row is `lineage-inferred`, status **unresolved** |
| H227 | System Charge SOC Limit number | `hardware-toggle-proven`, but **scoped to the one tested 18kPV**; status "current on tested unit; **cross-family write risk unresolved**". Created in the always-on block for every inverter that reaches it, with no family gate |
| H117 | Start Charge Power Threshold number | `asserted-unverified`, status **unresolved** — the keeper records "no cloud name or validated behavior" |

Two of these deserve singling out.

**H110 b14** is the register from issue #476: its Green-Mode bit was documented as b8 for
years, the wrong b8 write was firmware-ACKed, and no readback detected it. A local-first
write on an unresolved family mapping of that same register is the #476 setup, not an
analogy to it.

**H117 is the sharpest single case here.** It is a **raw** register write —
`coordinator.write_raw_parameter(REG_PTOUSER_START_CHARGE, …)`, bypassing the router
entirely, so it gets none of the router's fallback, cache-seeding or error handling — to a
register with no validated behaviour and no cloud name to check it against. Two things
narrow the exposure without touching the risk: the entity is **disabled by default**
(`_attr_entity_registry_enabled_default = False`), and it is only created where a local
register path exists (`has_local_register_path`). Fewer installations have it live; for
any that enable it, the write is exactly as unproven. `verified-against-code`
(`number.py` → `StartChargePowerNumber`).

**A register's absence from this table is not a clearance.** It means only that the keeper
has not flagged it, or that nothing writes it yet. A mapping proven on one tested unit and
shipped to every family carries the same hazard whether or not a row says so — H227 sat in
exactly that position, unflagged, until the keeper caught up.

#### Snapshot of the wider surface — 2026-08-09, not exhaustive

A reviewer walked the local-write surface on **2026-08-09** and found these classes beyond
the table above, all written to mappings the keeper grades below rung 2 or does not grade
at all. **This is a dated observation, not a maintained list** — re-derive with the
procedure above rather than trusting it. `asserted-unverified` (reviewer walk, 2026-08-09;
cross-check each entry against the keeper and the code before relying on it).

The same walk surfaced H227 and H117, which the keeper has since flagged; they have moved
up into the table above. That is the intended direction of travel — an entry leaves this
snapshot when the keeper takes a position on it, and the snapshot is where a register waits
in the meantime.

| Class | Registers | Note as observed |
|---|---|---|
| Working-mode bits | H110 b3 (Share Battery), b4 (Charge Last) | `lineage-inferred` |
| Battery current + SOC cutoffs | H101, H102, H105, H125 | `lineage-inferred`, always-on block — the most battery-safety-adjacent scalars shipped |
| Voltage cutoffs | H100, H169 | `lineage-inferred` |
| No ledger row at all | reg 22 (PV start voltage), H20 (PV input mode) | Not graded anywhere |
| Function word without a per-bit map | H21 b0, b7, b10, b11, b15 | Word graded `lineage-inferred` |

**Where `portal-correlated` sits.** The snapshot deliberately excludes mappings the keeper
grades `portal-correlated` — H66, H74, H67, H160, H116, H82, H83, H202, H103, H110 b1,
H179 b7, H233 b0/b1, H179 b9/b10, and the schedule-time registers. Including them would
make essentially the entire control surface a violation, which is not a useful line. The
reasoning: `portal-correlated` means the vendor's own portal exposes the parameter and our
reading agrees with it, so the mapping has independent third-party corroboration even
without a toggle capture. That is a real distinction, **but it is a judgement, not a rule
the legend states** — `portal-correlated` still sits below rung 2, and the ladder's text
does not carve it out. Treat the exclusion as a documented scoping decision that a future
reviewer may reopen, not as a safety finding about those registers.

Per-bit grades and scope belong to the keeper,
[`40-hardware/registers.md`](40-hardware/registers.md); the risk is tracked on issue
**#558** and [C7](60-history/open-contradictions.md), which owns the detail. **Never read
the ladder's rule as an assurance that some other page's register is unreachable.** A weak
grade does not close a write path — every time this has been checked, it has not.

Cross-integration agreement sits at rung 2 at best: it is corroboration, not observation.

The contract harness is **not** independent evidence at any rung — it resolves against
the same pylxpweb tables, so it catches internal drift and cannot prove an address is
correct on hardware.

## Freshness discipline

- Every page carries `verified-against:` and `last-verified:` (a date). A claim without
  them is unusable — the reader cannot tell what it was true of. `verified-against:` is a
  bare commit on a page that cites one repository, and **one labelled commit per
  repository** on a page that cites more than one; the schema and both forms are in
  [`_conventions.md`](_conventions.md). A page cannot license a citation into a repo it
  does not pin.
- **Status is not knowledge.** Versions, entity counts, "pending reporter confirmation",
  and release state belong in `60-history/` or `50-operations/`, always date-stamped
  inline. Never write "current" without a date.
- **Do not migrate line numbers as standalone facts.** They drift; the corpus already
  contains three mutually incompatible sets. Cite `file` + symbol name and let the
  reader grep. A line number is acceptable only inside a page whose `verified-against:`
  commit pins it.
- **Cite durable artifacts only.** A source is durable if a future reader can still open
  it: a repo path, a `memory/*.md` filename, an issue or PR number. Working files from an
  authoring run are not durable and must never appear in `sources:` or behind an
  `asserted-unverified` grade — a row whose only support has been deleted is functionally
  ungraded. `llmwiki/` is the durable copy: if a fact matters, it must be written here.
