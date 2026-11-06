---
type: Convention
title: "Conventions"
description: "The page template every writer follows: front-matter schema, durable-source rules, writing rules, anti-patterns."
canonical-for:
  - "llmwiki page template and front-matter schema"
  - "llmwiki OKF v0.2 conformance: index.md and log.md formats, concept types, validation"
  - "Writing rules for llmwiki pages"
sources:
  - resource: llmwiki/README.md
  - resource: PR #557 (documentation-defect corrections)
  - resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Conventions

Every page in `llmwiki/` follows this template. Grades and the canonical-source policy
are defined in [README.md](README.md); this page defines the mechanics.

## Page template

````markdown
---
type: Reference
title: "Page title"
description: "One sentence: what this page is for. The chapter index entry repeats it."
canonical-for:
  - "One line per fact-set this page owns"
sources:
  - resource: path/or/url/of/each/source
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
| `type` | yes | OKF concept type, the only key OKF itself requires. Use one from the type table below. |
| `title` | yes | The page's `# ` heading, verbatim. |
| `description` | yes | One sentence saying what the page is for. The page's entry in its chapter `index.md` must contain this text, and `okf validate --drift` checks that it does. |
| `canonical-for` | yes | The facts this page owns. Another page must not restate them. Be specific: "per-base-class availability semantics", not "entities". |
| `sources` | yes | Everything the page was written from — **durable artifacts only** (see below). OKF form: a list of `- resource: <path, URL, issue or PR>` entries. The optional OKF keys `id`, `title` and `last_modified` (YYYY-MM-DD) may be added. |
| `verified-against` | yes | The commit(s) the code-citations were checked at — see the two forms below. Use `9f6d6e2` for `eg4_web_monitor` unless you re-verified at a newer one. |
| `last-verified` | yes | ISO date of the last time someone actually re-checked the page, not the last time it was edited. |
| `see-also` | no | Sibling pages a reader will want next. Links, not restatements. |
| `runbook-status` | runbooks only | Whether the procedure on the page has been executed as written. `untested-as-written` until an authorized run says otherwise. |
| `last-executed` | runbooks only | ISO date of the last authorized execution, or `never`. |

Front matter is a fenced YAML block delimited by `---`. Keep it to these fields. Every page
carries all the fields marked required; `runbook-status` and `last-executed` are
optional and belong only on a page that gives an executable procedure
(`40-hardware/probing-playbook.md` is the current case). A runbook that omits them reads
as rehearsed when it is not, which is the failure they exist to prevent.

#### OKF trust and lifecycle keys

OKF also defines `generated: { by, at }`, `verified: [{ by, at }]`, `status`
(`draft` | `stable` | `deprecated`, default `stable`) and `stale_after`. They are optional
here, and **this wiki's trust record remains `verified-against:` plus `last-verified:` and
the per-claim grades in [README.md](README.md)**. OKF tiers are coarser and do not replace
them. If you add one:

- `generated.by` / `verified[].by` must name the real actor: `<agent>/<version>` for an
  agent (for example `claude-code/<model-id>`), `human:<github-login>` for a person. Never
  write a `human:` actor unless that person actually reviewed the page. OKF reads `human:`
  as human-reviewed, so an invented one forges provenance.
- `at` is an ISO 8601 timestamp with an explicit offset (`2026-11-06T00:00:00Z`).
- `status: deprecated` marks a page kept for history. Prefer moving the content to
  `60-history/`.

No page carries `generated:` or `verified:` yet, because neither was recorded when the
pages were written (see the 2026-11-06 `build` entry in [log.md](log.md)).

#### Concept types

OKF requires `type` but fixes no vocabulary. This wiki uses a closed set. Add a type here
before using it.

| `type` | For |
|---|---|
| `Overview` | The cold-start entry page |
| `Reference` | Knowledge about how the system is built and behaves (the default) |
| `Glossary` | Definitions only |
| `Design` | A forward-looking contract or design not yet fully implemented |
| `Research` | Open questions and the evidence that would resolve them |
| `Playbook` | An executable procedure (also carries `runbook-status` / `last-executed`) |
| `Process` | How work is done: dev setup, gates, release, issues |
| `History` | Dated records, postmortems, contradictions, superseded claims |
| `Convention` | Rules for the wiki itself (`README.md`, this page) |

#### The two forms of `verified-against:`

This wiki documents two repositories, so a page pins either one commit or several:

````markdown
verified-against: 9f6d6e2          # the page cites one repository

verified-against:                  # the page cites more than one
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
````

The key is the repository name. Which form a page uses follows from what it cites, not
from which directory it lives in: a `20-pylxpweb/` page that only cites library source
pins `pylxpweb` alone, and the same chapter's page on release-and-pin mechanics cites
both and pins both.

**A page cannot license a citation into a repository it does not pin.** `verified-against:`
is what makes a line range or a symbol reference checkable; a citation into an unpinned
repo is a claim about an unspecified state of the world. Pin the repo, or reduce the
citation to something that does not need pinning.

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

## Index, log and validation (OKF v0.2)

`llmwiki/` is an OKF v0.2 bundle rooted at `llmwiki/`. `index.md` and `log.md` are reserved
names at every depth and are never concept pages.

| File | Format |
|---|---|
| `llmwiki/index.md` | Front matter holds only `okf_version: "0.2"`. Lists the root concepts and one entry per chapter: `* [NN-name/](NN-name/index.md) - <what the chapter owns>.` |
| `llmwiki/<chapter>/index.md` | No front matter. One entry per page in that chapter: `* [<title>](<file>.md) - <description> Owns: <the page's canonical-for, in prose>.` |
| `llmwiki/log.md` | No front matter. `## YYYY-MM-DD` date groups, newest first. Each entry is `### <op> \| <subject>` plus prose. Its header owns the `<op>` vocabulary and the entry rules. |

**Adding or moving a page** means updating its chapter `index.md` in the same change:
add the entry and keep its description identical to the page's `description:`. A new
chapter also needs an entry in the root `index.md`.

**Links.** Link to other wiki pages with relative paths. Links to repo files outside the
bundle (`../../docs/DATA_MAPPING.md`) are allowed and expected. OKF tooling reports them as
broken concept links because they leave the bundle, and the spec says consumers must
tolerate that. Do not convert them to URLs to silence the report.

**Validation.** `tests/test_llmwiki_okf.py` runs in the normal pytest suite and enforces
conformance without extra tooling: every page has front matter with the required keys and
a known `type`, every page is listed in its chapter index with a matching description,
index and log formats are as above, and every relative link resolves to a file. The
optional [`okf` CLI](https://github.com/okf-memory/okf-agent-memory) (setup in
`AGENTS.md`) gives the same conformance check plus search:

```bash
okf validate llmwiki            # OKF conformance; must report "Conformant"
okf validate llmwiki --drift    # also index-description drift and parent-index coverage
okf search "smart port" llmwiki # BM25 search across pages
```

Do not gate on `okf validate --strict`. It also fails on the out-of-bundle links above and
on `index.md` / `log.md` links, which the spec permits.

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

### Maintenance note: granting a grade outside the legend is a defect by construction

**Any page that appears to grant, weaken, or except a grade outside
[README.md](README.md)'s legend is a defect** — however reasonable the local reasoning
looks. Do not weigh the argument on its merits. The argument is always reasonable; that
is the failure mode. Delete the local rule and take the grade from the legend.

This is structural, not hypothetical. The same loophole regrew three times in three
review rounds, in three different places, each written in good faith by someone fixing
something real:

| Where it regrew | The form it took |
|---|---|
| `20-pylxpweb/api-surface.md` | The chapter defined its own, weaker `hardware-proven` |
| `README.md`, evidence legend | A "negative claim" exception waiving the raw before/after pair |
| `README.md`, register-annotation ladder | A rung awarding `hardware-proven` with no raw pair |

Each fix patched its instance and left the cause: a grade's *minimum proof* and the
*evidence a page actually has* pull against each other, so any second structure that
names grades will eventually resolve that tension in favour of the evidence in front of
it. Hence exactly one structure grades. Ladders, register tables, chapter conventions,
and glossary entries describe evidence and its consequences, then defer.

The tell is a sentence of the form "evidence *X* earns grade *Y*" anywhere outside
README's legend. Deleting the sentence never loses information: either the legend
already says it, or it is the defect.

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
