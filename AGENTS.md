# Agent Instructions

This project uses **bd** (beads v1.0.0) for issue tracking with GitHub sync.

## Issue Tracking

All work is tracked in beads. Issues sync bidirectionally with GitHub.

```bash
bd ready                          # Find available work (open, no blockers)
bd show <id>                      # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>                     # Complete work
bd search "<query>"               # Search issues by text
bd priority <id> <0-4>            # Set priority (0=critical)
bd label add <id> "<label>"       # Add label (effort:xs, effort:s, etc.)
GITHUB_TOKEN=$(gh auth token) bd github sync  # Sync with GitHub
```

## Sprint Workflow

The sprint system uses beads formulas/molecules for structured execution.

### Commands

| Command | Purpose |
|---------|---------|
| `/triage [N]` | Score and label open issues (single or batch) |
| `/sprint-plan [name]` | Triage, rank, group into waves, create sprint epic |
| `/sprint [name]` | Execute a planned sprint in parallel worktrees |
| `/sprint-loop [N]` | Chain N sprint cycles: plan → execute → sync → repeat |
| `/fix-issue <N>` | Fix a single issue end-to-end in worktree |
| `/ship-fix` | Simplify → commit → PR → review → issue comment |

### Sprint Flow

```
/sprint-plan  →  user approves  →  /sprint  →  /ship-fix per issue
     │                                 │
     ├─ Triage unscored issues         ├─ Wave-based parallel execution
     ├─ Rank by priority/effort        ├─ Max 4 agents per wave
     ├─ Group by component             ├─ Sequential merges between waves
     └─ Create epic + wave plan        └─ Close issues + sync GitHub
```

### Formulas

```bash
bd formula list                    # List available formulas
bd cook mol-sprint --dry-run --var sprint_name=SPRINT-1  # Preview sprint
bd mol pour mol-sprint --var sprint_name=SPRINT-1        # Create sprint molecule
bd mol pour mol-fix-issue --var issue_id=210             # Create fix molecule
```

## Quality Gates (Non-Negotiable)

Every code change must pass before commit:

```bash
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
uv run pytest tests/ -x --tb=short
```

## Merge Gate

PR merges are blocked by `pr-merge-guard.sh` hook until:
1. Code-simplifier run on changed files
2. Code-reviewer agent passes
3. All quality gates pass
4. `touch .merge-ready` in project root

## Session Completion

**MANDATORY** — work is NOT complete until `git push` succeeds.

```bash
# 1. File issues for remaining work
bd create "Follow-up: <description>" --type task

# 2. Run quality gates (if code changed)
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pytest

# 3. Update issue status
bd close <finished-id>

# 4. Push everything
git pull --rebase
git push
git status  # MUST show "up to date with origin"

# 5. Sync beads
GITHUB_TOKEN=$(gh auth token) bd github sync
```

## Agent Roles

| Agent | Role | Tools |
|-------|------|-------|
| Main (Opus) | Orchestrator — sprint planning, issue triage, code review coordination | All |
| Worktree agents | Fix implementation — one per issue, isolated worktree | All |
| Code-reviewer | Post-implementation review | Read, Grep, Glob |
| Code-simplifier | Reduce complexity in changed files | All |
| Explore agents | Codebase investigation for L/XL issues | Read, Grep, Glob |

## Project Conventions

- **Python**: `uv` for all operations, Python 3.13+
- **Strings**: f-strings for code, %-formatting for logging only
- **Entities**: Inherit from base classes in `base_entity.py`
- **Coordinator**: Use mixins in `coordinator_mixins.py`
- **Config**: TypedDict for config dictionaries
- **Timing**: `time.monotonic()` (never `asyncio.get_event_loop().time()`)
- **Tests**: `pytest-homeassistant-custom-component`, target >95% coverage
- **Commits**: Conventional commits (`fix:`, `feat:`, `refactor:`)
- **Branches**: `fix/issue-<N>` or `feat/<description>`
