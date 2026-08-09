---
canonical-for:
  - "What llmwiki is and how to navigate it"
  - "Canonical-source policy"
  - "Evidence-grade legend and grading rules"
  - "Freshness discipline"
sources:
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
  - /tmp/llmwiki-research/docs-accuracy-audit.md
  - .pollux/registry.json
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

An accuracy audit of the repo's own documentation found **39 verified software-accuracy
defects** — 18 of them classed *breaks-agent* — across `CLAUDE.md`, `README.md`,
`docs/*.md`, and CI config (`docs-accuracy-audit.md` §2, §6). The dominant cause was
not neglect: it was **duplication**. The same fact (polling intervals, entity-ID
formats, config-flow paths, the register table) lived in three or four documents, was
corrected in one, and rotted in the rest. `llmwiki` answers that with a single rule:
one fact, one owner.

## Navigation

| Directory | Owns | Status |
|---|---|---|
| `00-orientation/` | What the system is, where code lives, vocabulary | present |
| `10-integration/` | HA integration internals: architecture, data flow by mode, entity identity/availability, controls and writes, config flow, diagnostics, data semantics | planned |
| `20-pylxpweb/` | The `pylxpweb` library: API surface, transports, models and scaling, write paths, release and pinning | planned |
| `30-portal-api/` | EG4 cloud portal API: auth/session, endpoint table, schemas and scaling, errors | planned |
| `40-hardware/` | Registers (with per-claim evidence grades), firmware reverse engineering, GridBOSS, probing playbook | planned |
| `50-operations/` | Dev environment, quality gates, release process, issue pipeline | planned |
| `60-history/` | Bug postmortems, open contradictions, superseded claims | present |
| `_conventions.md` | The page template every writer follows | present |

`planned` = contracted in the orchestration registry (`.pollux/registry.json`, untracked
working-copy state) and authored in parallel branches; the page names above are
`asserted-unverified` until those PRs land. Check the directory before linking.

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

Every factual claim carries one of these five grades. They are ordered strongest first.

| Grade | Means | Minimum proof to use it |
|---|---|---|
| `verified-against-code` | Checked against source in this repo, or a named sibling repo, at the commit in `verified-against:` | Cite the path and the symbol (`coordinator_mixins.py` → `_TRANSPORT_OVERLAY`) |
| `hardware-proven` | Observed on physical hardware — a before/after raw value from a real toggle, read, or write — **or** established by disassembling a shipped firmware image | Cite the observation: raw values, register, device family/serial class |
| `portal-correlated` | The EG4 portal or mobile app exposes it, and it agrees with our reading | Cite the endpoint, field, or widget |
| `inferred` | Deduced from lineage, naming, or an adjacent proven fact. Plausible and unproven. | State what it was inferred from |
| `asserted-unverified` | A source states it; nothing here independently corroborates it | Name the source |

**Rules**

- **Never upgrade a grade you cannot justify.** Downgrade freely; downgrading is cheap
  and correct. Upgrading requires new proof recorded on the page.
- `hardware-proven` requires a **before/after raw value pair**, not a successful write.
  A wrong-but-writable bit is firmware-ACKed: writing register 110 bit 8 succeeded,
  raised nothing, logged nothing above DEBUG, and read back true — while green mode
  never moved. Readback cannot prove targeting; only a delta test can
  (`60-history/superseded-claims.md`).
- **Do not import a `# verified` annotation as `hardware-proven`.** In this project's
  register tables that annotation has historically meant "the names matched", not "a
  toggle was observed". That false annotation is the direct cause of issue #476.
- **Cross-integration agreement is not proof.** It ranks below a toggle and above a
  vendor document: toggle-proven > cross-integration agreement > vendor document >
  lineage inference.
- **Contradiction is not resolved by grading.** If two sources disagree and neither is
  provable here, both go to `60-history/open-contradictions.md` marked UNRESOLVED.
  Do not pick a winner to make a page read cleanly.

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
- **Sources feeding this wiki are ephemeral.** The migration dossiers live in
  `/tmp/llmwiki-research/` and the maintainer's memory corpus lives outside the repo in
  `~/.claude/projects/…/memory/`. Neither is guaranteed to exist when you read this.
  `llmwiki/` is the durable copy — if a fact matters, it must be written here.
