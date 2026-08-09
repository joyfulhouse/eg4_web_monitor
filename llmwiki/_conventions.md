---
canonical-for:
  - "llmwiki page template and front-matter schema"
  - "Writing rules for llmwiki pages"
sources:
  - llmwiki/README.md
  - PR #557 (documentation-defect corrections)
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Conventions

Every page in `llmwiki/` follows this template. Grades and the canonical-source policy
are defined in [README.md](README.md); this page defines the mechanics.

## Page template

````markdown
---
canonical-for:
  - "One line per fact-set this page owns"
sources:
  - path/or/url/of/each/source
verified-against: 9f6d6e2
last-verified: 2026-08-08
see-also:
  - ../10-integration/architecture.md
---

# Page title

One or two sentences: what this page is for and who reads it.

## Section

| Claim | Detail | Grade |
|---|---|---|
| … | … | `verified-against-code` (`coordinator.py` → `EG4DataUpdateCoordinator`) |
````

### Front-matter fields

| Field | Required | Meaning |
|---|---|---|
| `canonical-for` | yes | The facts this page owns. Another page must not restate them. Be specific: "per-base-class availability semantics", not "entities". |
| `sources` | yes | Everything the page was written from — **durable artifacts only** (see below). |
| `verified-against` | yes | The commit the code-citations were checked at. Use `9f6d6e2` unless you re-verified at a newer one. |
| `last-verified` | yes | ISO date of the last time someone actually re-checked the page, not the last time it was edited. |
| `see-also` | no | Sibling pages a reader will want next. Links, not restatements. |

Front matter is a fenced YAML block delimited by `---`. Keep it to these five fields.

### Durable sources only

A source is durable if a future reader can still open it. This applies to `sources:` **and**
to every citation attached to an `asserted-unverified` claim.

| Durable — use these | Not durable — never cite |
|---|---|
| A repo path (`docs/audits/2026-08-02-register-race-performance-audit.md`) | A working file from an authoring run (scratch directories, migration dossiers, review bundles) |
| A `memory/*.md` filename (outside the repo, but stable and named) | A section number in such a file ("corpus §2.10") |
| An issue or PR number (`#476`, `PR #557`) | "the research corpus", "the audit", "the brief" |
| A sibling wiki page that owns the fact | A page that does not declare `canonical-for` on it |

A row whose only support has been deleted is functionally ungraded, which is worse than
an ungraded row because it looks sourced. When the underlying evidence is a working
artifact, name the durable thing behind it: the memory file it distilled, the issue it
came from, or the code it was checked against — or write the claim as
`asserted-unverified` naming the person or issue that asserted it.

## The grading rule

**Every factual claim carries a grade.** No exceptions for claims that "everyone knows".
A page of ungraded prose is indistinguishable from the documentation this wiki replaced.

The grade vocabulary is defined once, in [README.md](README.md). **Do not define, rename,
or locally weaken a grade in your chapter** — that produces two legends and the weaker one
wins by proximity. If you need a distinction that does not exist, add it to README.

- Put the grade in a table column when the section is a table (it should usually be a table).
- **Always write grades in backticks** — `` `verified-against-code` `` — never `[brackets]`
  and never bare words. Grades are machine-extracted; three notations break extraction.
- In prose, put it at the end of the sentence, with its citation:
  `verified-against-code` (`base_entity.py` → `EG4BatteryEntity`).
- Grade the **specific claim**, not the section. If a row's root cause is testimony and
  its fix is verifiable, say so per part rather than averaging them into one grade.
- If you cannot corroborate what a source asserts, the grade is `asserted-unverified`
  and you **name a durable source**. That is a complete, acceptable answer. Silently
  promoting it to `inferred` is not, and neither is citing something the reader cannot open.
- Uncertainty is content. "Unknown", "refuted", and "contested" are legitimate values —
  write them rather than omitting the row.

## Writing rules

| Rule | Why |
|---|---|
| **Tables over prose.** Anything with more than two parallel cases is a table. | An agent extracts a row reliably; it paraphrases a paragraph unreliably. |
| **Write for an agent that must not guess.** State the exact symbol, path, register, family, or field name. Never "the relevant handler". | Vague references get resolved by guessing, and the guess ships. |
| **Cite `file` + symbol, not `file:line`.** | Line numbers drift; three incompatible sets already exist in the corpus. Line numbers are allowed only where `verified-against:` pins them. |
| **No status in a knowledge page.** Versions, counts, "pending", "current" belong in `50-operations/` or `60-history/`, date-stamped. | Status rots on a schedule; knowledge does not. |
| **One fact, one owner.** Link instead of restating. | Duplication produced 39 verified doc defects. |
| **No marketing voice.** No "powerful", "seamless", "robust", no exclamation marks, no reassurance. | Read by machines and hurried humans. |
| **Negative results are content.** Record what was tried and failed, and what a register is *not*. | Several bugs recurred because a refutation was never written down. |
| **Preserve the falsification ask.** When you ship an `inferred` claim, say what observation would refute it. | An inference nobody can test becomes fact by attrition. |
| **Never write a claim you cannot cite.** If the only support is memory, grade it `asserted-unverified` and name the memory file. | — |

## Anti-patterns

| Do not | Instead |
|---|---|
| Copy a value from code into prose as a standalone fact (a default interval, a version, an entity count) | Point at the file that owns it; if the value is essential, quote it with its source path and grade it `verified-against-code` |
| Resolve a contradiction because the page reads better without it | Add it to `60-history/open-contradictions.md`, quote both sources, mark UNRESOLVED |
| Reuse a source's confidence language ("verified", "confirmed") without checking what it meant | Re-grade from the underlying evidence; see the `# verified` trap in [README.md](README.md) |
| Add a page to another writer's directory | Add it to yours and link, or negotiate `canonical-for:` ownership first |
| Write "see the code" | Write the path and the symbol |
