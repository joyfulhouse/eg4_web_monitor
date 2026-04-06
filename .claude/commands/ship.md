---
description: "Ship: merge outstanding PRs with full review gate. Does NOT create a release — use /ship-pre or /ship-release for that."
---

# Ship

Merge all reviewed PRs into main with quality gates. This is the merge-only command.

## Workflow

### Step 1: Inventory Open PRs

```bash
gh pr list --state open --json number,title,headRefName,reviewDecision
```

If no PRs are open, stop: "Nothing to ship."

### Step 2: Pre-Merge Quality Gate (per PR)

For each PR, in sequence:

1. **Checkout PR branch**: `gh pr checkout <N>`
2. **Run code-simplifier** on changed files (diff vs main)
3. **Commit simplifier changes** (if any): `git commit -m "refactor: simplify code"`
4. **Run quality gates**:
   ```bash
   uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
   uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
   uv run pytest tests/ -x --tb=short
   ```
5. **Run 3-reviewer gate** (all in parallel):
   - **Code-reviewer** (Opus) — comprehensive review
   - **Codex adversarial** (`/codex:rescue`) — challenge implementation
   - **Gemini adversarial** (`/gemini:adversarial-review`) — challenge approach
6. **Fix all issues** from all three reviewers, push fixes
7. **Re-run quality gates** after fixes
8. **Set merge gate**: `touch .merge-ready`

### Step 3: Merge Sequentially

For each PR that passed the gate:

```bash
gh pr merge <N> --squash --delete-branch
git checkout main && git pull
```

The `pr-merge-guard.sh` hook enforces that `.merge-ready` exists before each merge.

### Step 4: Update CHANGELOG.md

1. Collect all commits just merged:
   ```bash
   git log $(git describe --tags --abbrev=0)..HEAD --oneline --no-merges
   ```
2. If an `[Unreleased]` section exists in CHANGELOG.md, append new entries to it
3. If no `[Unreleased]` section, create one at the top (below the header)
4. Organize entries into Keep a Changelog categories:
   - `### Added` — new features (`feat:`)
   - `### Fixed` — bug fixes (`fix:`)
   - `### Changed` — modifications (`refactor:`, `perf:`)
5. Include GitHub issue references from commit messages
6. Commit:
   ```bash
   git add CHANGELOG.md
   git commit -m "docs: update changelog with merged PRs"
   git push
   ```

### Step 5: Post-Merge Sync

```bash
git checkout main && git pull
GITHUB_TOKEN=$(gh auth token) bd github sync
```

### Step 5: Summary

Print:
```
Ship Complete
=============
PRs merged: N
  - #123: fix: description
  - #456: feat: description

Next steps:
  /ship-pre alpha   — Create alpha pre-release for community testing
  /ship-pre beta    — Create beta pre-release for wider testing
  /ship-release     — Promote to stable release (triggers HACS update)
```

### Rules

- **Sequential merges only** — never merge PRs in parallel
- **All quality gates must pass** — zero tolerance for ruff, mypy, or pytest failures
- **Code-reviewer must pass** — fix all issues before merge
- **Close beads issues** for each merged PR: `bd close <id>`
- Does NOT create a GitHub release or tag — use `/ship-pre` or `/ship-release` for that
