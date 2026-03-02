# Automated Issue Triage Design

**Date**: 2026-03-01
**Status**: Approved
**Scope**: eg4_web_monitor + pylxpweb repositories

## Problem

Both repositories are getting increased issue volume. Manual triage is time-consuming
and reporters don't always provide enough information for investigation. Support
questions belong in community forums, not GitHub issues.

## Design

### Issue Templates (enforced, blank issues disabled)

**Bug Report** (`bug_report.yml`):
- Integration/library version, HA version, connection mode, device model
- Description, steps to reproduce, logs, screenshots
- pylxpweb variant is simpler (no HA-specific fields)

**Feature Request** (`feature_request.yml`):
- Problem/use case, proposed solution, alternatives, affected devices

**Config** (`config.yml`):
- `blank_issues_enabled: false` — forces template use
- Contact links to HA Community and DIYSolarForum for support

### Auto-Triage Workflow (`issue-triage.yml`)

Triggers on `issues: [opened]`. Two jobs:

1. **rate-limit-check**: Queries GitHub API for issues opened by user in last 24h.
   Max 2/day per user per repo. If exceeded, posts polite message and skips triage.

2. **triage**: Runs Claude Code Action with codebase access. Claude:
   - Classifies: bug / enhancement / support / duplicate
   - Researches relevant code and existing issues
   - Support → redirects to community forums, labels `support`
   - Duplicate → links original, labels `duplicate`
   - Bug → analyzes code, requests missing info (`needs-info`) or validates and assigns `btli`
   - Enhancement → feasibility assessment, assigns `btli`

### @claude Follow-Up (updated `claude.yml`)

- Contributor gate: only `COLLABORATOR`, `MEMBER`, or `OWNER` can invoke
- Added `issues: write` permission for labeling/assigning

### Abuse Prevention

- Rate limit: 2 issues/day per user per repo
- Contributor gate on @claude follow-up
- Forced templates prevent unstructured input

### Labels

Created on both repos: `needs-info`, `duplicate`, `support`
(plus existing `bug`, `enhancement`)

## File Inventory (per repo)

```
.github/
├── ISSUE_TEMPLATE/
│   ├── bug_report.yml
│   ├── feature_request.yml
│   └── config.yml
└── workflows/
    ├── claude.yml          # Updated (eg4) or new (pylxpweb)
    └── issue-triage.yml    # New
```
