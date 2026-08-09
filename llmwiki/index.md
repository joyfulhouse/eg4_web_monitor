---
canonical-for:
  - "Catalog of every llmwiki page and the facts it owns"
sources:
  - llmwiki/*/*.md front matter (canonical-for declarations)
verified-against: 9f6d6e2
last-verified: 2026-08-09
see-also:
  - README.md
  - log.md
---

# Index

**Read this first.** It is the catalog of the wiki: every page, what it is for, and which
facts it owns. Find the pages relevant to your task here, then read those pages — do not
scan the tree.

Two companion files sit beside this one. [`README.md`](README.md) owns the conventions:
the evidence-grade legend, the canonical-source policy, and the freshness rules. Every page
here follows them. [`log.md`](log.md) is the chronological record of what has been done to
the wiki and why.

**The one rule that makes this catalog usable:** each fact has exactly one owner. The
"Owns" column is that page's `canonical-for:` declaration. If you need a fact, go to its
owner — other pages link to it rather than restating it, and a second copy anywhere is a
defect.

## Root

| Page | What it is | Owns |
|---|---|---|
| [`README.md`](README.md) | The legend and the rules. Evidence grades, the canonical-source policy, the register-annotation ladder, freshness discipline | Navigation intent, canonical-source policy, evidence-grade legend and grading rules, freshness discipline |
| [`_conventions.md`](_conventions.md) | The page template every writer follows: front-matter schema, durable-source rules, writing rules, anti-patterns | Page template and front-matter schema, writing rules |
| [`index.md`](index.md) | This catalog | Catalog of every page and the facts it owns |
| [`log.md`](log.md) | Append-only history of ingests, queries and lint passes | Chronological record of the wiki's own evolution |

## 00-orientation — what the system is, where things live, vocabulary

| Page | What it is | Owns |
|---|---|---|
| [`what-this-project-is.md`](00-orientation/what-this-project-is.md) | The four moving parts and how a value travels from register to entity. Start here cold | The four moving parts and their boundaries; the two-repo relationship; device-hierarchy vocabulary; the "cloud is not a separate data source" principle |
| [`repo-map.md`](00-orientation/repo-map.md) | Where code actually lives, and the paths older docs get wrong | Repo layout; path traps (`_config_flow/`, the `const/` package, the two firmware RE trees) |
| [`glossary.md`](00-orientation/glossary.md) | Definitions only — topology, connectivity, registers, data handling, process | Vocabulary used across the wiki and the codebase |

## 10-integration — the Home Assistant integration

| Page | What it is | Owns |
|---|---|---|
| [`architecture.md`](10-integration/architecture.md) | Module inventory by layer, coordinator mixin composition, setup/unload sequence | Module inventory; mixin composition and MRO constraints; config-entry lifecycle |
| [`config-flow.md`](10-integration/config-flow.md) | The `_config_flow` package, real step names, connection-type derivation | Package layout and shim; step names; connection-type derivation; unique-id construction and migration |
| [`controls-and-writes.md`](10-integration/controls-and-writes.md) | How a control write reaches a device, and how to derive each mechanism's population | The control-write mechanisms; write routing; local-vs-cloud decision; optimistic state and TTL; post-write refresh; error surfacing |
| [`data-flow-by-mode.md`](10-integration/data-flow-by-mode.md) | HTTP / LOCAL / HYBRID end to end, and why HYBRID is not a third code path | Per-mode data flow; poll intervals, throttles and cache TTLs; the LOCAL static first-refresh phase |
| [`data-semantics.md`](10-integration/data-semantics.md) | What values mean and the traps in interpreting them | Staleness, carry-forward, eviction; capability gating by family; energy monotonicity and the clamp ban; float tolerance; battery accumulation by serial; parameter cache seeding; the `time.monotonic()` fresh-boot trap |
| [`entities-identity-availability.md`](10-integration/entities-identity-availability.md) | Entity base classes, and why `unknown` and `unavailable` differ by class | Base-class graph; per-class availability semantics; unique-id formats as implemented; entity-id derivation |
| [`diagnostics-repairs.md`](10-integration/diagnostics-repairs.md) | Diagnostics output, redaction, and the Repairs surface | Diagnostics shape and redaction; serial/plant aliasing; repairs issue keys; device-removal ledger |

## 20-pylxpweb — the library

| Page | What it is | Owns |
|---|---|---|
| [`api-surface.md`](20-pylxpweb/api-surface.md) | The seams the integration actually uses | Public client, device-factory and transport-factory seams |
| [`transports.md`](20-pylxpweb/transports.md) | Modbus TCP and WiFi dongle behaviour | Local transport behaviour |
| [`models-and-scaling.md`](20-pylxpweb/models-and-scaling.md) | Portal models, normalized local data, enums, scaling | Models, missing values, enums and scaling |
| [`write-paths.md`](20-pylxpweb/write-paths.md) | How the library routes and verifies a write | Cloud, local, hybrid and schedule write routing and verification |
| [`release-and-pinning.md`](20-pylxpweb/release-and-pinning.md) | Version derivation and the dependency pin | Version derivation and pin mechanics |

## 30-portal-api — the EG4 cloud portal

| Page | What it is | Owns |
|---|---|---|
| [`auth-and-session.md`](30-portal-api/auth-and-session.md) | Login, session lifetime, reauthentication | Authentication; `JSESSIONID` lifecycle; reauthentication and request encoding |
| [`endpoints.md`](30-portal-api/endpoints.md) | The endpoint inventory and identifier model | Endpoint inventory; object and identifier model; OpenAPI coverage boundaries |
| [`schemas-and-scaling.md`](30-portal-api/schemas-and-scaling.md) | Response shapes, value scaling, and where sources disagree | Response shapes; cloud value scaling; parameter read/write representation; schema divergences |
| [`errors.md`](30-portal-api/errors.md) | Error envelopes, retries, throttling | Error envelopes; retry and backoff; throttling and cache policy |

## 40-hardware — registers and firmware

| Page | What it is | Owns |
|---|---|---|
| [`registers.md`](40-hardware/registers.md) | **The register keeper.** Per-row evidence grades for every inverter and GridBOSS register. Authoritative for any register question | Inverter and GridBOSS register ground truth |
| [`gridboss.md`](40-hardware/gridboss.md) | GridBOSS specifics, including the smart-port mode register | GridBOSS POWER_HUB UART map |
| [`firmware-re.md`](40-hardware/firmware-re.md) | Firmware acquisition and decoding methodology, and why the committed RE artefacts are invalid | Acquisition, decoding and register-RE methodology |
| [`probing-playbook.md`](40-hardware/probing-playbook.md) | The safe procedure for dumping and verifying registers on live hardware. **Runbook — read before touching a device** | Safe register dumping and live verification |
| [`open-questions.md`](40-hardware/open-questions.md) | What evidence would resolve each open hardware question | Evidence needed to resolve open hardware and firmware questions |

## 50-operations — running and shipping

| Page | What it is | Owns |
|---|---|---|
| [`dev-environment.md`](50-operations/dev-environment.md) | Local setup, the HA container, four-mode testing and its hazards | Dev setup; bind mounts; four-mode testing; mode-switch hazards |
| [`quality-gates.md`](50-operations/quality-gates.md) | What must pass before a commit, and what only advises | Lint, format, typecheck, tests, coverage, tier validators; blocking vs advisory CI |
| [`release-process.md`](50-operations/release-process.md) | Two-repo release ordering and the pin-move gate | Release ordering; artifact-trust gate; version scheme; manifest pin coupling; HACS publish |
| [`issue-pipeline.md`](50-operations/issue-pipeline.md) | Issue templates, log enforcement, PR conventions | Issue templates; debug-log auto-close; PR conventions; work-tracking prohibitions |

## 60-history — what was believed, what was wrong, what is unresolved

Read this before trusting a confident claim found elsewhere in the repo.

| Page | What it is | Owns |
|---|---|---|
| [`superseded-claims.md`](60-history/superseded-claims.md) | Claims documented with confidence, acted upon, and false — and the mechanism by which each became load-bearing | Superseded claims and their mechanisms |
| [`open-contradictions.md`](60-history/open-contradictions.md) | C1-C11: places two sources disagree and **no adjudication has been made**. Do not resolve one by writing a page that picks a side | Unresolved contradictions between project sources |
| [`bug-postmortems.md`](60-history/bug-postmortems.md) | Symptom, true root cause, fix, and the generalizable lesson for each shipped bug | Postmortem catalogue |

## Where to start, by task

| Task | Read |
|---|---|
| New to the system | `what-this-project-is.md`, then `repo-map.md`, then `_conventions.md` |
| About to touch a register | `40-hardware/registers.md` (the keeper), then `README.md`'s ladder, then `probing-playbook.md` |
| About to write to a device | `README.md` § the write-access rule and its blind spots, then `10-integration/controls-and-writes.md` |
| Debugging wrong or missing values | `10-integration/data-semantics.md`, then `data-flow-by-mode.md`, then `60-history/bug-postmortems.md` |
| Debugging an entity that vanished or went unavailable | `10-integration/entities-identity-availability.md` |
| Adding a page or editing one | `_conventions.md`, then `README.md`'s legend |
| Doubting something you read in the repo | `60-history/superseded-claims.md`, then `open-contradictions.md` |
