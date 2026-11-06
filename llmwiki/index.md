---
okf_version: "0.2"
---

# llmwiki index

**Read this first.** This is the root of an [Open Knowledge Format (OKF)
v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle. It lists the root concepts and the chapters. Each chapter's own `index.md` lists
every page in that chapter, what it is for, and which facts it owns. Open the chapter
index for your task, then open the pages it names. Do not scan the tree.

Two root concepts sit beside this file. [`README.md`](README.md) owns the conventions:
the evidence-grade legend, the canonical-source policy, the freshness rules, and the
reading order by task. [`_conventions.md`](_conventions.md) owns the page template and the
front-matter schema. `log.md` is the dated record of what has been done to the wiki and
why, newest first.

**The one rule that makes this catalog usable:** each fact has exactly one owner. The
"Owns" clause on each entry is that page's `canonical-for:` declaration. If you need a
fact, go to its owner. Other pages link to the owner rather than restating it, and a
second copy anywhere is a defect.

## Root concepts

* [llmwiki](README.md) - The legend and the rules. Evidence grades, the canonical-source policy, the register-annotation ladder, freshness discipline. Owns: Navigation intent, canonical-source policy, evidence-grade legend and grading rules, freshness discipline.
* [Conventions](_conventions.md) - The page template every writer follows: front-matter schema, durable-source rules, writing rules, anti-patterns. Owns: Page template and front-matter schema, writing rules.

## Chapters

* [00-orientation/](00-orientation/index.md) - What the system is, where code lives, vocabulary.
* [10-integration/](10-integration/index.md) - HA integration internals: architecture, data flow by mode, entity identity/availability, controls and writes, config flow, diagnostics, data semantics.
* [20-pylxpweb/](20-pylxpweb/index.md) - The `pylxpweb` library: API surface, transports, models and scaling, write paths, release and pinning.
* [30-portal-api/](30-portal-api/index.md) - EG4 cloud portal API: auth/session, endpoint table, schemas and scaling, errors.
* [40-hardware/](40-hardware/index.md) - Registers (with per-claim evidence grades), firmware reverse engineering, GridBOSS, probing playbook.
* [50-operations/](50-operations/index.md) - Dev environment, quality gates, release process, issue pipeline.
* [60-history/](60-history/index.md) - Bug postmortems, open contradictions, superseded claims, and dated maintenance, production and release-readiness records.
