---
description: "Triage open GitHub issues: read, score priority/effort, update beads labels. Pass an issue number to triage one, or run without args to triage all unscored."
---

# Triage Issues

Triage open issues from beads, scoring them for sprint planning.

## Input

- `$ARGUMENTS` — optional GitHub issue number or beads ID to triage a single issue
- If no argument, triage ALL open issues that lack priority scoring

## Workflow

### Step 1: Load open issues

```bash
bd ready --json
```

If `$ARGUMENTS` is provided, filter to just that issue. Otherwise process all.

### Step 2: For each issue

1. **Read the issue**: `bd show <id>` to get full details
2. **Read GitHub context**: Use `gh issue view <github_number> --comments` to read reporter conversation
3. **Classify**:
   - `bug` — something broken that worked before
   - `enhancement` — new feature or capability
   - `support` — user confusion, not a bug (label `needs-info` or `wontfix`)
   - `duplicate` — already tracked (link to original, close)
4. **Score priority** (P0-P4):
   - P0: Data loss, security, integration won't load
   - P1: Core functionality broken (sensors missing, controls fail)
   - P2: Non-critical bugs, moderate features
   - P3: Polish, dashboard issues, cosmetic
   - P4: Future ideas, nice-to-have
5. **Estimate effort**:
   - Label `effort:xs` (<30 min, config/const change)
   - Label `effort:s` (30min-2hr, single file fix)
   - Label `effort:m` (2-4hr, multi-file, needs tests)
   - Label `effort:l` (4-8hr, new feature, architecture change)
   - Label `effort:xl` (>8hr, major feature, cross-repo)
6. **Update beads**:
   ```bash
   bd priority <id> <N>
   bd label add <id> "effort:<size>"
   bd label add <id> "<type>"  # bug, enhancement, etc.
   ```

### Step 3: Summary

Print a table of triaged issues with their scores:

```
| Issue | Title | Priority | Effort | Type |
```

### Rules

- If an issue needs more info from reporter, label it `needs-info` and skip scoring
- If an issue is a duplicate, link it and close: `bd link <id> <original> --type related && bd close <id>`
- If an issue is clearly wontfix (works as designed), close with explanation
- Do NOT fix anything during triage — only classify and score
- Sync back to GitHub when done: `GITHUB_TOKEN=$(gh auth token) bd github sync`
