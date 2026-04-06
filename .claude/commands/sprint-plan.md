---
description: "Plan the next sprint: triage unscored issues, rank by priority/effort, select a batch, group into waves, create sprint epic in beads."
---

# Sprint Plan

Plan a sprint without executing it. Produces a sprint epic with linked issues,
wave assignments, and implementation notes for L/XL items.

## Input

- `$ARGUMENTS` — optional sprint name (auto-generates as `SPRINT-<date>-<seq>` if omitted)

## Workflow

### Step 1: Sync and Triage

1. Pull latest issues from GitHub:
   ```bash
   GITHUB_TOKEN=$(gh auth token) bd github sync --pull-only
   ```

2. Count open issues:
   ```bash
   bd ready --json
   ```

3. For any issue without a priority label or with default P2 that hasn't been reviewed:
   - Read issue details: `bd show <id>`
   - Read GitHub comments: `gh issue view <N> --comments`
   - Score priority (P0-P4) and effort (xs/s/m/l/xl)
   - Update beads:
     ```bash
     bd priority <id> <N>
     bd label add <id> "effort:<size>"
     bd label add <id> "<type>"
     ```

### Step 2: Rank and Select

1. List all ready issues sorted by priority, then effort (smallest first within same priority):
   ```bash
   bd ready --json
   ```

2. Apply selection rules:
   - **Always include**: All P0 issues (critical)
   - **Include next**: P1 bugs, then P1 features
   - **Fill remaining**: P2 bugs by effort (xs → xl), then P2 features
   - **Cap at 5 items** per sprint (adjustable)
   - **Skip**: Issues labeled `needs-info`, `wontfix`, `duplicate`
   - **Skip**: Issues requiring pylxpweb changes unless pylxpweb PR is already merged

3. For L/XL items, create an implementation plan:
   - Launch a `feature-dev:code-architect` agent to analyze the codebase
   - Produce a plan file at `docs/plans/<sprint-name>-<issue>.md`
   - Link plan to the beads issue: `bd note <id> "Plan: docs/plans/..."`

### Step 3: Group into Waves

Group selected issues by component affinity for parallel execution:

| Group | Files Touched | Can Parallelize With |
|-------|---------------|---------------------|
| config_flow | `config_flow/`, `strings.json` | sensors, transport |
| coordinator | `coordinator*.py`, `coordinator_mixins.py` | config_flow (if no shared const) |
| sensors | `sensor.py`, `const/sensors/`, `base_entity.py` | config_flow, transport |
| transport | pylxpweb, dongle/modbus code | sensors, config_flow |
| controls | `switch.py`, `number.py`, `select.py` | sensors, config_flow |

Rules:
- Issues touching the same files go in the same wave (sequential)
- Issues in different groups go in the same wave (parallel)
- Schema/const changes (Wave 0) must complete before other waves
- **Max 4 parallel agents per wave**

### Step 4: Create Sprint Epic

1. Create the epic:
   ```bash
   bd create "Sprint: ${SPRINT_NAME}" --type epic --labels "sprint" --priority 1
   ```

2. Link selected issues as children:
   ```bash
   bd link <epic-id> <issue-id> --type parent-child
   ```

3. Add wave assignments as notes:
   ```bash
   bd note <epic-id> "Wave 0: <issue-ids> (sequential - shared const changes)
   Wave 1: <issue-ids> (parallel - independent groups)
   Wave 2: <issue-ids> (parallel - depends on wave 1 merges)"
   ```

### Step 5: Present Plan for Approval

Print the sprint plan as a table:

```
Sprint: SPRINT-2026-04-06-1
Epic: eg4-<id>
═══════════════════════════════════════════════

Wave 0 (sequential):
  P0 #210 [bug] Individual Battery Data Fails To Update  effort:m  coordinator

Wave 1 (parallel, max 4):
  P2 #205 [bug] smart_port_1_status ValueError           effort:s  sensors
  P2 #202 [bug] GridBOSS duplicate unique IDs             effort:s  sensors
  P2 #206 [bug] 12KPV Grid/EPS Voltage Unknown           effort:m  coordinator

Wave 2 (parallel):
  P2 #209 [bug] Dashboard entity names mismatch           effort:s  docs

═══════════════════════════════════════════════
Total: 5 issues | Estimated: ~4.5 hours
Ready to execute? Run: /sprint SPRINT-2026-04-06-1
```

### Rules

- **Do NOT execute any fixes** — this is planning only
- Present the plan and wait for user approval before `/sprint` executes it
- If no P0/P1 issues exist, include a mix of P2 bugs and small enhancements
- If backlog is empty, say so and suggest running `/triage` first
- Always sync with GitHub before and after planning
- L/XL items should have plans written before sprint execution starts
