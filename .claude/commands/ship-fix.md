---
description: "Ship a bug fix: simplify code, commit, push, create PR, code review, fix all issues, then comment on GitHub issue with install/test/debug instructions."
---

# Ship Fix

Execute the following steps in order. Do NOT merge to main.

## Step 1: Code Simplifier

Run the code-simplifier agent on the changed files (unstaged diff from main) to clean up code for clarity, consistency, and maintainability while preserving all functionality.

## Step 2: Commit and Push

1. Stage all changes (the fix + any simplifier improvements)
2. Create a commit with a clear message referencing the GitHub issue (e.g., "fix: <description> (#<issue>)")
3. Push the branch to origin

## Step 3: Create Pull Request

Create a PR using `gh pr create` targeting `main`. The PR body should include:
- Summary of the bug and root cause
- What the fix does
- Test plan

## Step 4: Code Review

Run `/code-review:code-review` on the PR. Fix ALL issues found, even those below the confidence threshold. Commit and push fixes.

## Step 5: Comment on GitHub Issue

After the PR is created and reviewed, comment on the associated GitHub issue with testing instructions. Use `gh issue comment`.

The comment should include:

### a) Install instructions

Tell the user to install from the specific branch/commit using HACS custom repository or manual install:

```
# Option 1: HACS (recommended)
# Go to HACS > Integrations > 3-dot menu > Custom Repositories
# Add: https://github.com/joyfulhouse/eg4_web_monitor
# Version: select the fix branch name

# Option 2: Manual install from this specific commit
# Download and replace custom_components/eg4_web_monitor/ from:
# https://github.com/joyfulhouse/eg4_web_monitor/archive/<branch-name>.zip
```

Include the exact branch name and latest commit SHA.

### b) Test steps

Provide specific steps to reproduce and verify the fix based on the issue's original reproduction steps.

### c) Debug logging instructions

Include instructions to enable debug logging for the integration:

```yaml
# Add to configuration.yaml:
logger:
  default: warning
  logs:
    custom_components.eg4_web_monitor: debug
```

Then: restart Home Assistant, reproduce the action, and check logs under Settings > System > Logs.

### d) Feedback request

Ask the user to reply with:
- Whether the fix resolved their issue
- Any relevant debug log output if it didn't work
- Their device model and firmware version for our records
