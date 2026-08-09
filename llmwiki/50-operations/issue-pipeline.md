---
canonical-for: GitHub issue templates, debug-log auto-close, PR conventions, beads work tracking prohibitions
sources:
  - /tmp/llmwiki-research/repo-operations.md
  - /tmp/llmwiki-research/knowledge-corpus-index.VERIFIED-claude_code.md
  - .github/ISSUE_TEMPLATE/bug_report.yml
  - .github/ISSUE_TEMPLATE/feature_request.yml
  - .github/ISSUE_TEMPLATE/config.yml
  - .github/workflows/issue-log-validation.yml
  - .github/workflows/issue-triage.yml
  - AGENTS.md
  - scripts/bd_seed_maintainability.sh
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Issue and PR pipeline

How bugs, features, PRs, and agent work tracking flow in this repo.

## Issue templates

**verified-against-code** — `.github/ISSUE_TEMPLATE/config.yml`

- `blank_issues_enabled: false` — free-form issues are disabled.
- Contact links: Home Assistant Community, DIY Solar Forum, Discord.

### Bug report (required fields)

**verified-against-code** — `.github/ISSUE_TEMPLATE/bug_report.yml`

| Field | Required |
|-------|----------|
| Integration Version | yes |
| Home Assistant Version | yes |
| Connection Mode | yes |
| Device Model(s) | yes |
| Describe the Bug | yes |
| Steps to Reproduce | yes |
| Debug Logs | yes |
| Diagnostics Download | yes |
| Confirmation checkboxes (debug logs + diagnostics) | yes |
| Affected Entity ID(s) | no |
| Screenshots | no |

Auto-label: `bug`.

Template warns: companion-app “share logs” / phone logcat is **rejected** — must be HA debug logging from a browser for this integration — **verified-against-code** — `bug_report.yml:17-21`.

### Feature request (required fields)

**verified-against-code** — `.github/ISSUE_TEMPLATE/feature_request.yml`

| Field | Required |
|-------|----------|
| Problem or Use Case | yes |
| Proposed Solution | yes |
| Affected Device Model(s) | yes (dropdown) |
| Alternatives Considered | no |

Auto-label: `enhancement`.

## Debug-log validation automation

**verified-against-code** — `.github/workflows/issue-log-validation.yml:1-12`, marker at L45

| Behavior | Detail |
|----------|--------|
| Triggers | Issue opened/edited; issue comments |
| Check | Downloads Debug Logs attachments; greps for `custom_components.eg4_web_monitor\|pylxpweb\|eg4_web_monitor` |
| Invalid | Label `needs-logs`, explanatory comment, **close as not planned** |
| Later valid edit/comment | Reopen + remove `needs-logs` |
| Exempt | OWNER / MEMBER / COLLABORATOR |

Form emptiness alone is not enough — phone logcat or screenshots pass the form but fail this workflow.

## Issue triage automation

**verified-against-code** — `.github/workflows/issue-triage.yml` (dossier §4.3)

| Behavior | Detail |
|----------|--------|
| Rate limit | >2 issues / 24h by same user → comment, skip triage |
| Classification | Labels `bug` / `enhancement` / `support` / `duplicate` / `needs-info` |
| Assignment | `@btli` for actionable bugs/enhancements |
| Closing | Must **not** close issues (log-validation workflow is the closer) |

## PR conventions

| Topic | Fact | Grade |
|-------|------|-------|
| In-repo PR template | **None** under `.github/` | verified-against-code — absent |
| Contribution guide | Org `CONTRIBUTING.md`: https://github.com/joyfulhouse/.github/blob/main/CONTRIBUTING.md | verified-against-code — `docs/DEVELOPMENT.md:39-41` |
| CODEOWNERS | `* @btli` | verified-against-code — `.github/CODEOWNERS` |
| Branch naming | Not formally documented in-repo. Observed: `integration/3.4.0`, `integration/3.5.0`, `feat/…` (pylxpweb). Follow the current release-line style | inferred |
| Labels | From templates (`bug`, `enhancement`) + triage (`support`, `duplicate`, `needs-info`, `needs-logs`) | verified-against-code |
| Auto-merge | **Not** enabled for eg4_web_monitor workflows. pylxpweb has Dependabot auto-merge for non-major only | verified-against-code — dossier §4.4 |

## Work tracking (beads / `bd`)

**verified-against-code** — `AGENTS.md`

Source of truth under `.beads/` (`issues.jsonl`, `interactions.jsonl`, `config.yaml`, …).

```bash
bd ready
bd show <id>
bd update <id> --claim   # or --status in_progress
bd close <id>
bd sync
```

### Standing prohibitions

| Prohibition | Why | Grade |
|-------------|-----|-------|
| **Never run `bd github sync` in this repo** | Historically mass-pushed ~90 internal beads records as GitHub issues (#381–#470). Close beads with `bd close`; manage GitHub with `gh` | asserted-unverified in current tree (recorded in verified knowledge-corpus index / research); treat as hard policy |
| **Never re-run `scripts/bd_seed_maintainability.sh`** | **NOT idempotent** — running twice creates duplicate epics | verified-against-code — script header L13–14 |
| Do not use `bd edit` | Opens `$EDITOR`, blocks agents | asserted-unverified in AGENTS/hooks; prefer `bd update` flags |
| Do not use TodoWrite / markdown files for task tracking when beads is the project tracker | Session policy | asserted-unverified (hooks / AGENTS) |

Seed script dry-run only if needed: `./scripts/bd_seed_maintainability.sh --dry-run` — **verified-against-code** — script L14.

### Authority conflict (push)

- `AGENTS.md` “Landing the Plane” says work is incomplete until `git push` succeeds.
- Session hooks / user rules default to **conservative**: commit/push only with explicit authority.

**Agents must treat user/orchestrator instructions as highest precedence** when those conflict — **inferred** from dossier §8.2.

## Agent checklist when filing or answering bugs

1. Require real integration debug logs (not companion logcat).
2. Prefer diagnostics JSON from HA (credentials redacted; serials aliased on recent versions).
3. Do not fight the auto-closer — attach a valid log and let reopen automation run.
4. Track agent work in beads; never `bd github sync`; never re-seed maintainability.
