#!/usr/bin/env bash
# careful-guard.sh — Intercept destructive commands before execution
# Hook type: PreToolUse (Bash)
#
# Returns "ask" for commands that need user confirmation.
# Returns nothing (empty) for safe commands.

set -euo pipefail

# Read the tool input from stdin
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Safe patterns — always allow
case "$COMMAND" in
  # Testing and linting
  *"uv run pytest"*|*"uv run ruff"*|*"uv run mypy"*) exit 0 ;;
  # Git read-only
  *"git status"*|*"git log"*|*"git diff"*|*"git branch"*|*"git show"*) exit 0 ;;
  # Git safe writes
  *"git add"*|*"git commit"*|*"git checkout -b"*|*"git switch"*) exit 0 ;;
  # Beads
  *"bd "*) exit 0 ;;
  # GitHub CLI (read)
  *"gh issue"*|*"gh pr view"*|*"gh pr list"*|*"gh pr checks"*) exit 0 ;;
  # Docker read-only
  *"docker logs"*|*"docker ps"*|*"docker inspect"*) exit 0 ;;
  # File listing
  *"ls "*) exit 0 ;;
esac

# Dangerous patterns — require confirmation
BLOCK_REASON=""

case "$COMMAND" in
  *"rm -rf"*|*"rm -r "*|*"rmdir"*)
    # Allow cleaning known safe targets
    case "$COMMAND" in
      *"node_modules"*|*".mypy_cache"*|*"__pycache__"*|*".pytest_cache"*|*".ruff_cache"*) exit 0 ;;
      *".claude/worktrees/"*) exit 0 ;;
      *) BLOCK_REASON="Recursive delete detected: $COMMAND" ;;
    esac
    ;;
  *"git push --force"*|*"git push -f"*)
    BLOCK_REASON="Force push detected — this rewrites remote history"
    ;;
  *"git reset --hard"*)
    BLOCK_REASON="Hard reset — this discards uncommitted changes"
    ;;
  *"git checkout -- "*|*"git restore "*|*"git clean"*)
    BLOCK_REASON="Destructive git operation — discards local changes"
    ;;
  *"docker rm"*|*"docker rmi"*|*"docker system prune"*)
    BLOCK_REASON="Docker cleanup — may remove needed containers/images"
    ;;
  *"DROP TABLE"*|*"DROP DATABASE"*|*"TRUNCATE"*)
    BLOCK_REASON="Destructive SQL operation detected"
    ;;
esac

if [ -n "$BLOCK_REASON" ]; then
  echo '{"decision": "ask", "message": "'"$BLOCK_REASON"'"}'
fi
