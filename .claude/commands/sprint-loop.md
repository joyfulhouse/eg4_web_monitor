---
description: "Continuous sprint orchestrator: triage, plan, execute, review, merge in a loop. Pass a number to limit iterations (default: 1)."
---

# Sprint Loop

Orchestrate continuous sprint cycles. Each iteration runs a full sprint:
triage -> plan -> execute -> review -> merge -> retro.

## Input

- `$ARGUMENTS` — number of sprint iterations to run (default: 1, "all" for continuous until backlog empty)

## Workflow

### Initialization

1. Sync GitHub issues into beads:
   ```bash
   GITHUB_TOKEN=$(gh auth token) bd github sync --pull-only
   ```
2. Check current state:
   ```bash
   bd ready --json
   bd count
   ```
3. If no open issues, stop: "Backlog is empty. Nothing to sprint on."

### Sprint Loop

For each iteration (up to `$ARGUMENTS` times):

**Step 1: Generate sprint name**

Use format: `SPRINT-<date>-<seq>` (e.g., `SPRINT-2026-04-06-1`)

**Step 2: Triage**

Run `/triage` to score any unscored open issues.

**Step 3: Plan + Execute Sprint**

Pour a sprint molecule and execute it:

```bash
bd mol pour sprint --var sprint_name=${SPRINT_NAME} --var max_items=5
```

Then follow the `/sprint` workflow:
- Select top issues by priority
- Group by component affinity
- Execute in parallel waves (max 4 agents per wave)
- Review and merge PRs
- Close fixed issues

**Step 4: Post-Sprint Sync**

```bash
GITHUB_TOKEN=$(gh auth token) bd github sync
bd mol squash <mol-id>
```

**Step 5: Check for next iteration**

- If more iterations remain AND open issues exist: continue to next sprint
- Otherwise: print summary and stop

### Between Sprints

- Pull latest main: `git checkout main && git pull`
- Re-sync GitHub issues (new issues may have been filed)
- Check if any P0/P1 issues appeared (prioritize those in next sprint)

### Summary Report

After all iterations, print:

```
Sprint Loop Complete
====================
Sprints run: N
Issues fixed: N
PRs merged: N
Issues remaining: N (list P0/P1 if any)
```

### Rules

- **Each sprint gets a fresh subagent** for context isolation (1M window per sprint)
- **Never skip triage** — new issues may have appeared between sprints
- **Max 5 issues per sprint** to keep sprints focused
- **P0 issues always take priority** regardless of sprint plan
- **If a P0 appears mid-sprint**, interrupt and address it first
- **Max 3 sprint iterations** in a single session unless user explicitly says "all"
- **Sync beads to GitHub after every sprint** to keep external state current
