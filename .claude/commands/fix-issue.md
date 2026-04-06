---
description: "Fix a specific GitHub issue end-to-end: investigate, implement in worktree, test, review, PR. Pass issue number or beads ID."
---

# Fix Issue

Fix a single issue from investigation through PR creation.

## Input

- `$ARGUMENTS` — GitHub issue number (e.g., "210") or beads ID (e.g., "eg4-abc123")

## Workflow

### Step 1: Load Issue Context

If argument is a number, find the beads issue:
```bash
bd search "#$ARGUMENTS"
```

Then read full details:
```bash
bd show <beads-id>
gh issue view $ARGUMENTS --comments
```

Mark as in-progress:
```bash
bd update <beads-id> --status in_progress
```

### Step 2: Investigate

- Read the issue description and all comments
- Identify affected component area (config_flow, coordinator, sensors, transport, controls)
- Use Grep/Glob to find relevant source files
- Trace the execution path from the reported symptom to root cause
- For bugs: understand what changed or what edge case triggers it
- For features: understand where the new capability fits in the architecture

**Do NOT write any code yet.** Investigation first.

### Step 3: Create Worktree

```bash
bd worktree create fix-$ARGUMENTS --branch fix/issue-$ARGUMENTS
```

### Step 4: Implement Fix

Following project conventions:
- Base entity classes in `base_entity.py`
- Coordinator mixins for new data processing
- F-strings for code, %-formatting for logging
- TypedDict for config dictionaries
- `time.monotonic()` for timing (not asyncio event loop)

Add or update tests for the change.

### Step 5: Quality Gates (non-negotiable)

```bash
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
uv run pytest tests/ -x --tb=short
```

All three must pass with zero errors. Max 3 fix attempts if tests fail.

### Step 6: Code Review (3-reviewer gate for m/l/xl effort)

Run all reviewers in parallel:
1. **Code-simplifier** — simplify changed files
2. **Code-reviewer** (Opus) — comprehensive review
3. **Codex adversarial** (`/codex:rescue`) — challenge implementation choices
4. **Gemini adversarial** (`/gemini:adversarial-review`) — challenge approach

Fix all issues from all reviewers, then re-run quality gates.

For xs/s effort issues: code-simplifier + code-reviewer only (skip adversarial).

### Step 7: Ship

1. Commit: `git commit -m "fix: <description> (#$ARGUMENTS)"`
2. Push: `git push -u origin fix/issue-$ARGUMENTS`
3. Create PR:
   ```bash
   gh pr create --title "fix: <description> (#$ARGUMENTS)" --body "..."
   ```
4. Comment on GitHub issue with install/test/debug instructions (per ship-fix template)
5. Close beads issue: `bd close <beads-id>`
6. Sync: `GITHUB_TOKEN=$(gh auth token) bd github sync`

### Step 8: Cleanup

```bash
bd worktree remove fix-$ARGUMENTS
```

### Cross-Repo Fix (pylxpweb)

If the investigation reveals the fix requires pylxpweb changes:

1. **Fix pylxpweb first** in `/Users/bryanli/Projects/joyfulhouse/python/pylxpweb`:
   ```bash
   cd /Users/bryanli/Projects/joyfulhouse/python/pylxpweb
   git checkout -b fix/issue-$ARGUMENTS
   ```
2. **Implement + test pylxpweb**:
   ```bash
   uv run pytest tests/ -x --tb=short
   uv run ruff check src/ --fix && uv run ruff format src/
   uv run mypy --strict src/
   ```
3. **PR + Release pylxpweb**:
   ```bash
   git commit -m "fix: <description> (joyfulhouse/eg4_web_monitor#$ARGUMENTS)"
   git push -u origin fix/issue-$ARGUMENTS
   gh pr create --repo joyfulhouse/pylxpweb
   ```
   After merge: `gh release create vX.Y.Z --repo joyfulhouse/pylxpweb`
4. **Then fix eg4_web_monitor**: update `manifest.json` with new pylxpweb version, adapt integration code
5. **Test with Docker volume mount** to verify end-to-end before pylxpweb release is on PyPI

### Rules

- Max 3 implementation attempts before asking user for help
- Always verify the fix addresses the EXACT symptom described in the issue
- If the issue is unclear or needs more info, label `needs-info` and skip instead of guessing
- For cross-repo fixes, ALWAYS fix pylxpweb first, release, then update eg4_web_monitor
- Run pylxpweb tests (`uv run pytest`) before committing any library changes
- Never break the pylxpweb public API without a deprecation path
