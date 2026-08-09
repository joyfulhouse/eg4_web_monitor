# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Landing the Plane (Session Completion)

When ending a work session, leave nothing stranded in the working tree.

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Commit** - Never leave finished work uncommitted; commit incrementally as you
   go rather than banking a large change set on one final commit
5. **Publish, if you have the authority to** - When the session's operator has
   asked you to push or has granted standing permission for this branch:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # should show "up to date with origin"
   ```
6. **Clean up** - Clear stashes, prune remote branches
7. **Hand off** - Say plainly what is committed, what is pushed, and what is not

**Rules:**
- Committing is not optional — uncommitted work is lost work
- Pushing is an outward-facing action. Do it when asked or pre-authorized; when
  you have not been, stop at the commit and say the branch is ready to push
- Never claim work is pushed unless you have seen the push succeed
- If an authorized push fails, resolve and retry until it succeeds
