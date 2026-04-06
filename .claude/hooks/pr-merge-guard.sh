#!/usr/bin/env bash
# pr-merge-guard.sh — Enforce review gate before merging PRs
# Hook type: PreToolUse (Bash)
#
# Blocks `gh pr merge` until .merge-ready file exists.
# This enforces the review workflow: simplify -> review -> verify -> merge.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Only intercept gh pr merge commands
case "$COMMAND" in
  *"gh pr merge"*) ;;
  *) exit 0 ;;
esac

# Check if merge gate is set
if [ ! -f ".merge-ready" ]; then
  cat <<'EOF'
{"decision": "block", "message": "PR merge blocked: .merge-ready file not found.\n\nComplete the pre-merge checklist first:\n1. Run code-simplifier on changed files\n2. Commit simplifier changes\n3. Run code-reviewer agent\n4. Run quality gates (ruff, mypy, pytest)\n5. Verify all pass\n6. touch .merge-ready\n\nThen retry the merge."}
EOF
  exit 0
fi

# Gate passed — clean up the marker
rm -f .merge-ready
