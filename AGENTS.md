# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Maintaining `llmwiki/`

`llmwiki/` is a knowledge base that agents write and keep current: numbered chapters,
plus `index.md` (the page catalog), `README.md` (canonical-source policy,
evidence-grade legend, freshness discipline), `log.md` (append-only history) and
`_conventions.md` (page template, front-matter schema, writing rules).

**To find a page, start at `llmwiki/index.md`** — it lists every page with a
one-line summary and the facts it owns, so you never scan the tree. **To grade a
claim, go to `llmwiki/README.md`**: it owns the rules the pages follow, not a list
of what exists, and it carries the cold-start reading order.

### Three layers, and the one-way rule

| Layer | What it is | Who writes it |
|---|---|---|
| Raw sources | This repo's code, `pylxpweb` at its pinned commit, `docs/`, `memory/*.md`, GitHub issues and PRs | Normal development |
| The wiki | `llmwiki/` — evidence-graded pages, one owner per fact | Agents |
| The schema | This file and `CLAUDE.md` | Co-evolved; edit it when a workflow proves wrong |

**The wiki follows the code. The code is never changed to make a wiki claim true.**
A documentation task that turns out to need a code change stops and files an issue.
Issues #549 (CI compiles a non-existent `const.py`), #550 (inert `_attr_entity_id`
assignments) and #558 (a live local write whose stated mitigation cannot detect a
wrong mapping) all exist because that rule held instead of being quietly patched in
a docs PR.

### Ingest — new knowledge arrives

A shipped fix, a hardware capture, a contradiction surfaced in review, a new issue:

1. **Read the primary source.** Not a summary of it, not a memory file about it.
2. **Find the owner.** `index.md` → the page whose `canonical-for:` covers the
   fact. If nothing owns it, add it to the page whose subject it belongs to,
   extend that page's `canonical-for:`, and add the row to `index.md`.
3. **Update that page only.** Grade the claim, cite a durable artifact, refresh
   `verified-against:` and `last-verified:`.
4. **Update whatever the new knowledge falsifies.** A promotion or downgrade is
   never a local edit — grep the register, symbol, or path across `llmwiki/` before
   you call it done.
5. **Record it.** Append an entry to `llmwiki/log.md`. Keep the heading prefix
   exact — `## [YYYY-MM-DD] <op> | <subject>` — because
   `grep '^## \[' llmwiki/log.md | tail -5` is how the next agent reads recent
   history; that file's header owns the `<op>` vocabulary and the append-only
   rules, and you are opening it anyway. The commit message is a durable record
   too, and the two serve different readers: the log carries reasoning across
   commits, the commit message explains one diff.

**One fact, one owner.** A fact restated in two places has gone stale in two places
three separate times during this wiki's construction: a test count, a coverage
target, and a register slot-list that a grade promotion one file away silently
falsified.

### Query — answering from the wiki

Find the owner page in `index.md`, read it, and answer with a citation to that page
and its `verified-against:` pin. **State the grade when it changes the answer** —
"portal-correlated, not proven" is a different answer from "proven". If the question
produced a durable new synthesis, file it back into the owning page rather than
leaving it in chat history, and log it as a `query`.

### Lint — periodic health check

- Contradictions between pages. An unresolved one belongs in
  `60-history/open-contradictions.md`, not resolved by assertion.
- Claims whose `verified-against:` pin has moved — recheck or downgrade.
- `verified-against-code` grades whose cited symbol no longer exists at the pin.
- Orphan pages, and facts that no page owns.
- **Completeness claims** — "every", "only these", "all controls". Ask what
  *derives* the set. This repo's most expensive documentation defects are all this
  shape.

### Evidence discipline

The grade vocabulary is closed and defined **only** in `llmwiki/README.md`. Never
coin a grade, weaken one locally, or carve out an exception: that loophole regrew
five times during construction, each time with locally reasonable wording.

- **Never grade `hardware-proven` from source code, a README, or a `# verified`
  comment.** In this project's register tables `# verified` has historically meant
  "the names matched" — the direct cause of issue #476.
- **A claim whose citation does not support it is a defect even when the claim is
  true.** Confirm a cited symbol exists at the pin (`git show <pin>:<path>`) before
  citing it.
- **Prefer a derivation plus its known blind spots over an enumeration.** An
  enumeration is stale the moment the code grows a case.

### Rules paid for in defects

- **Verify the frame before the contents.** An exhaustive count over an incomplete
  frame reads as rigour and is not. Three consecutive review rounds each found a
  write mechanism the previous round's frame had excluded.
- **Resolve the runtime class, not the base class.**
  `HybridInverter._set_schedule` (`pylxpweb/devices/inverters/hybrid.py`) and
  `_set_schedule` on the control endpoint (`pylxpweb/endpoints/control.py`) share a
  name and route differently; grepping the name lands you on whichever comes first.
- **A completeness claim is load-bearing.** Before writing "every" or "only these",
  ask what derives the set.
- **A readback proves storage and transport, never semantics.** A wrong-but-writable
  register is firmware-ACKed and reads back exactly what you wrote, so no readback
  distinguishes "the control worked" from "something else silently changed"
  (#476, #558).
- **Before stating what another document contains, check whether it is being edited
  in the same change set.** A claim about a sibling's contents is verified against a
  branch, not against what will merge, and it can go stale between writing and
  review. This build shipped that defect twice: three pages asserted a banner state
  another PR falsified in the same train, and this schema said `llmwiki/` had no
  `index.md` and no `log.md` about twenty minutes before a parallel branch created
  both. Prefer describing what a document *owns* over what it currently lists.
- **Re-verify a finding against the primary source before acting on it.** Tooling
  and reviews in this build produced confident results that did not reproduce, and a
  proposed "correction" taken from a secondary source would have published a false
  claim. A green check can be wrong — re-run a suspicious pass rather than trusting
  it.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
