---
description: "Execute a sprint: select triaged issues, fix them in parallel worktrees, review, merge. Pass a sprint name or let it auto-generate."
---

# Execute Sprint

Run a full sprint cycle using beads molecules. This is the core execution engine.

## Input

- `$ARGUMENTS` — optional sprint name (e.g., "SPRINT-42"). Auto-generates if omitted.

## Workflow

### Phase 0: Initialize Sprint Molecule

```bash
# Cook and pour the sprint formula
bd cook sprint --var sprint_name=${SPRINT_NAME} --var max_items=5 --var priority_cutoff=2 --persist
bd mol pour sprint --var sprint_name=${SPRINT_NAME} --var max_items=5
```

### Phase 1: Plan — Use Existing or Create Sprint Plan

Check if a sprint epic already exists for `${SPRINT_NAME}`:
```bash
bd search "Sprint: ${SPRINT_NAME}" --json
```

- **If epic exists** (from a prior `/sprint-plan` run): load it and its children as the plan.
- **If no epic exists**: run `/sprint-plan ${SPRINT_NAME}` to triage, rank, group, and create
  the sprint epic with wave assignments. Wait for user approval before proceeding.

### Phase 2: Execute — Fix Issues in Parallel Waves

For each wave of non-overlapping groups:

**Step A: Launch parallel agents**

For each issue/group in the wave, launch an Agent (isolation: "worktree"):
- Read the issue: `bd show <id>`
- Read GitHub comments: `gh issue view <N> --comments`
- Mark in-progress: `bd update <id> --status in_progress`
- Investigate root cause (read code, trace execution path)
- Implement fix following project conventions
- Run quality checks:
  ```bash
  uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
  uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
  uv run pytest tests/ -x --tb=short
  ```
- Commit and push branch
- Create PR: `gh pr create --title "fix: <desc> (#N)" --body "..."`

**Step B: Review PRs (3-reviewer gate)**

For each PR created in this wave, run ALL three reviewers in parallel:

1. **Code-simplifier** — simplify changed files for clarity
2. **Code-reviewer** (Opus) — comprehensive code review
3. **Codex adversarial review** (`/codex:rescue`) — challenge implementation choices
4. **Gemini adversarial review** (`/gemini:adversarial-review`) — challenge approach

All four run in parallel. Fix ALL issues from all reviewers, then push fixes.
Re-run quality gates after fixes. This is non-negotiable for m/l/xl effort items.

For xs/s effort items: code-simplifier + code-reviewer only (skip adversarial reviews).

**Step C: Merge sequentially**

Merge PRs one at a time to avoid conflicts:
```bash
gh pr merge <N> --squash --delete-branch
```

After each merge, pull main before next merge:
```bash
git checkout main && git pull
```

**Step D: Close and sync**

```bash
bd close <issue-id>
GITHUB_TOKEN=$(gh auth token) bd github sync
```

### Phase 3: Retro — Summarize Results

1. List all PRs merged in this sprint
2. Count: issues fixed, tests added, files changed
3. List any issues that were deferred or blocked
4. Squash the molecule: `bd mol squash <mol-id>`
5. Comment on each GitHub issue with install/test instructions (per ship-fix template)

### Rules

- **Max 4 parallel agents** per wave to avoid resource contention
- **Sequential merges** — never merge PRs in parallel (lockfile conflicts)
- **Pull main between waves** — ensure each wave starts from latest
- **Quality gates are non-negotiable** — all tests, lint, types must pass
- **Effort-proportional research**:
  - xs/s: read affected code only
  - m: read related components, run adversarial review
  - l/xl: use Explore agents, write implementation plan first
- **Max 3 fix attempts per issue** — if still failing, defer with notes
- **Cross-repo (pylxpweb) issues**:
  - During investigation, if root cause is in pylxpweb, label the issue `cross-repo`
  - Schedule cross-repo issues in their own wave (Wave 0 or last wave)
  - Fix pylxpweb first → PR → release → then update eg4_web_monitor
  - pylxpweb path: `/Users/bryanli/Projects/joyfulhouse/python/pylxpweb`
  - pylxpweb tests: `cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb && uv run pytest tests/ -x`
  - pylxpweb release: `gh release create vX.Y.Z --repo joyfulhouse/pylxpweb`
  - After pylxpweb release, update `manifest.json` in eg4_web_monitor with new version
