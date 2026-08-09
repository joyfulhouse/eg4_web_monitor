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

**This page is the single legend for the whole wiki.** No chapter may define, rename, or
locally weaken a grade, and no chapter may introduce a synonym. If you need a distinction
that is not here, add it here. A chapter-local legend does not stay parallel: it drifts
toward whatever that chapter's evidence happens to support, the weaker definition wins by
proximity, and every page that links to it inherits the weakening silently.

### Proof grades

Every factual claim carries exactly one. Ordered strongest first.

| Grade | Means | Minimum proof to use it |
|---|---|---|
| `verified-against-code` | The cited source implements or locks the claim, at the commit in `verified-against:` | Cite the repo path and the symbol (`coordinator_mixins.py` → `_TRANSPORT_OVERLAY`) |
| `firmware-proven` | Established by disassembling a shipped firmware image | Cite the image and family, and the code site — function, increment site, dispatcher entry |
| `hardware-toggle-proven` | A named vendor control or UI action on the target family, correlated to raw values captured before and after, with the original state restored | Cite the action, the raw before/after pair, and the family |
| `hardware-proven` | Umbrella for the two above. **Requires a before/after raw value pair** (one exception below). | As above. A source that merely records "a live-device result", with no raw pair, is `asserted-unverified` — however it was phrased |
| `portal-correlated` | The EG4 portal or mobile app exposes it, and it agrees with our reading | Cite the endpoint, field, or widget |
| `lineage-inferred` | Inherited from a related family or a neighbouring register, with no direct evidence on the target | Name the family or register it was inherited from |
| `inferred` | Deduced from an adjacent proven fact | State what it was inferred from |
| `asserted-unverified` | A source states it; nothing here independently corroborates it | Name a **durable** artifact: a repo path, a `memory/*.md` filename, an issue or PR number |

**The one exception to the raw-pair requirement** is a *negative* claim — that a register
is absent, rejected, or dead on a family — where no pair can exist. There the proof is the
device's own captured response: an ILLEGAL DATA ADDRESS or NAK, or a read that stays
constant while the quantity is demonstrably live. Cite the response and the family, and
scope the claim to the units tested: "reads 0 on every unit we tested" and "no family has
this register" are different claims, and only the first is proven.

### Status, orthogonal to proof strength

| Status | Means | Use |
|---|---|---|
| `refuted` | Actively disproven. **Must not regress.** | Not a weak proof grade — a refutation can itself be `hardware-toggle-proven`. Pair `refuted` with the grade of the disproof and cite it. Applied to a register bit it means: the historical semantic is false **and** no replacement semantic is established, so the bit stays write-inaccessible. |

### Rules

- **Never upgrade a grade you cannot justify.** Downgrade freely; downgrading is cheap
  and correct. Upgrading requires new proof recorded on the page.
- **Readback proves storage and transport only.** It says nothing about semantics. A
  wrong-but-writable bit is firmware-ACKed: writing register 110 bit 8 succeeded, raised
  nothing, logged nothing above DEBUG, and read back true — while Green Mode never
  moved. See the proof standard for bit semantics under the register-annotation ladder
  below.
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

### Named refinement: the register-annotation ladder

Scoped to **register and bit annotations only**. It refines the proof grades above for
the one case where getting it wrong writes to unknown hardware. Cross-linked from
`40-hardware/registers.md`, which applies it per row.

| Rung | Evidence | Grade it earns | What may be built on it |
|---|---|---|---|
| 1 | A named vendor/UI action on the target family, an independent observation that the intended physical state changed, a complete raw before/after delta, and restoration | `hardware-toggle-proven` | Reads and writes |
| 2 | Canonical pylxpweb definition **plus** an independent hardware capture | `hardware-proven` | Reads; writes only with a gate |
| 3 | Canonical definition alone | `verified-against-code` for the definition, `asserted-unverified` for the semantic | Read-only diagnostics |
| 4 | A vendor or third-party table | `lineage-inferred` at best | Nothing. It is a family-specific hypothesis |

**Binding consequence:** a bit at rung 3 or 4 stays **write-inaccessible** — no entity,
no named-write path, no placeholder key reachable by a write helper. Gating is the only
mitigation for an unproven mapping, because a wrong write cannot be detected after the
fact.

Cross-integration agreement sits at rung 2 at best: it is corroboration, not observation.

The contract harness is **not** independent evidence at any rung — it resolves against
the same pylxpweb tables, so it catches internal drift and cannot prove an address is
correct on hardware.

## Freshness discipline

- Every page carries `verified-against:` (a commit) and `last-verified:` (a date). A
  claim without them is unusable — the reader cannot tell what it was true of.
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
