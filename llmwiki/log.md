---
canonical-for:
  - "Chronological record of operations performed on llmwiki"
sources:
  - PR #553 and the sibling chapter PRs
  - the round-by-round adjudication record for this build
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

## [2026-08-09] lint | Eight-round adversarial review across three blocking engines

Every page was reviewed by three independent engines over eight rounds, with a binding
adjudication after each. Rounds did not converge quickly: seven of the eight produced at
least one BLOCKER, and the last round to seat all three engines still produced four.

The recurring finding was not factual error but **structural**: the same defect class
regrowing in new places after each local fix.

- **The borrowed-grade loophole** — a page granting an evidence grade whose stated minimum
  proof it did not meet — regrew five times in five different places. Patching each
  instance did nothing; the cause was that two structures (the legend and the ladder) both
  named grades, so whichever one faced weaker evidence eventually bent. Fixed structurally:
  the ladder now classifies evidence and decides write access but **names no grade**, and
  the legend is the sole grading authority. [`_conventions.md`](_conventions.md) carries a
  maintenance note declaring any out-of-legend grant a defect by construction.
- **False safety gates** — text asserting a protection the code does not implement —
  appeared four times, including in the glossary, where it was most dangerous: a reader who
  learns "unproven implies unwritable" stops looking for the gate everywhere else. All
  four now state the required policy and name it as unenforced.
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
