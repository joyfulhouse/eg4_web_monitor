---
canonical-for: GitHub issue templates, debug-log auto-close, PR conventions, beads work tracking prohibitions
sources:
  - .github/ISSUE_TEMPLATE/bug_report.yml
  - .github/ISSUE_TEMPLATE/feature_request.yml
  - .github/ISSUE_TEMPLATE/config.yml
  - .github/workflows/issue-log-validation.yml
  - .github/workflows/issue-triage.yml
  - AGENTS.md
  - scripts/bd_seed_maintainability.sh
  - .github/CODEOWNERS
  - pylxpweb .github/workflows/dependabot-auto-merge.yml
  - memory/sprint-2026-07-16-issue-zeroing.md
  - memory/issue-pipeline-log-enforcement.md
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-09
---

# Issue and PR pipeline

How bugs, features, PRs, and agent work tracking flow in this repo.

## Issue templates

`verified-against-code` — `.github/ISSUE_TEMPLATE/config.yml`

- `blank_issues_enabled: false` — free-form issues are disabled.
- Contact links: Home Assistant Community, DIY Solar Forum, Discord.

### Bug report (required fields)

`verified-against-code` — `.github/ISSUE_TEMPLATE/bug_report.yml`

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

Template warns: companion-app “share logs” / phone logcat is **rejected** — must be HA debug logging from a browser for this integration — `verified-against-code` — `bug_report.yml:17-21`.

### Feature request (required fields)

`verified-against-code` — `.github/ISSUE_TEMPLATE/feature_request.yml`

| Field | Required |
|-------|----------|
| Problem or Use Case | yes |
| Proposed Solution | yes |
| Affected Device Model(s) | yes (dropdown) |
| Alternatives Considered | no |

Auto-label: `enhancement`.

## Debug-log validation automation

`verified-against-code` — `.github/workflows/issue-log-validation.yml:1-12`, marker at L45

| Behavior | Detail |
|----------|--------|
| Triggers | Issue opened/edited; issue comments |
| Check | Downloads Debug Logs attachments; greps for `custom_components.eg4_web_monitor\|pylxpweb\|eg4_web_monitor` |
| Invalid | Label `needs-logs`, explanatory comment, **close as not planned** |
| Later valid edit/comment | Reopen + remove `needs-logs` |
| Exempt | OWNER / MEMBER / COLLABORATOR |

Form emptiness alone is not enough — phone logcat or screenshots pass the form but fail this workflow.

## Issue triage automation

`verified-against-code` — `.github/workflows/issue-triage.yml`

| Behavior | Detail |
|----------|--------|
| Rate limit | >2 issues / 24h by same user → comment, skip triage |
| Classification | Labels `bug` / `enhancement` / `support` / `duplicate` / `needs-info` |
| Assignment | `@btli` for actionable bugs/enhancements |
| Closing | Must **not** close issues (log-validation workflow is the closer) |

## PR conventions

| Topic | Fact | Grade |
|-------|------|-------|
| In-repo PR template | **None** under `.github/` | `verified-against-code` — no `PULL_REQUEST_TEMPLATE` file exists |
| Contribution guide | Org `CONTRIBUTING.md`: https://github.com/joyfulhouse/.github/blob/main/CONTRIBUTING.md | `asserted-unverified` — `docs/DEVELOPMENT.md` "Quality Checks" points there; the linked file lives in another repo and is not checked here |
| CODEOWNERS | `* @btli` | `verified-against-code` — `.github/CODEOWNERS` |
| Branch naming | Not formally documented in-repo. Observed: `integration/3.4.0`, `integration/3.5.0`, `feat/…` (pylxpweb). Follow the current release-line style | `inferred` — `CHANGELOG.md` release narratives |
| Labels | From templates (`bug`, `enhancement`) + triage (`support`, `duplicate`, `needs-info`, `needs-logs`) | `verified-against-code` — `.github/ISSUE_TEMPLATE/*.yml`, `.github/workflows/issue-triage.yml`, `.github/workflows/issue-log-validation.yml` |
| Auto-merge (this repo) | **None.** No workflow in eg4_web_monitor approves or merges anything; nothing here uses `pull_request_target` either | `verified-against-code` — eg4_web_monitor@`9f6d6e2`: the eight files under `.github/workflows/` contain no `--auto`, `auto-merge` or `pull_request_target` |
| Auto-merge (pylxpweb) | pylxpweb **approves and enables auto-merge** on Dependabot PRs for non-major bumps; major bumps get a comment demanding manual review and are not approved | `verified-against-code` — pylxpweb@`204b95d` `.github/workflows/dependabot-auto-merge.yml:27-39` (both the `gh pr review --approve` and `gh pr merge --auto --squash` steps carry `if: steps.metadata.outputs.update-type != 'version-update:semver-major'`), `:41-47` (major → comment only) |

### What the pylxpweb auto-merge actually exposes

Read the surface before changing anything there, because it is the one workflow in either repo that
merges code without a human — `verified-against-code` — pylxpweb@`204b95d` `dependabot-auto-merge.yml`:

| Property | Value | Line |
|---|---|---|
| Trigger | `pull_request_target` on `opened`, `synchronize`, `reopened` | `:9-10` |
| Token permissions | `contents: write`, `pull-requests: write` | `:12-14` |
| Only gate | `if: github.actor == 'dependabot[bot]'` on the single job | `:19` |
| Update classification | `dependabot/fetch-metadata@v3` — the bot's own metadata decides major vs non-major | `:21-25` |

`pull_request_target` runs in the **base** repo context with those write permissions, which is why it
is normally dangerous. The mitigating property here is that the job **never checks out the PR head** —
its four steps only run `gh pr` commands against the PR URL, and the URL is passed via `env:` rather
than interpolated into the shell — `verified-against-code` — `:20-47` (the job's complete step list).
The file states this reasoning itself at `:1-5`.

Two limits worth stating precisely. `gh pr merge --auto` **enables** GitHub's auto-merge; it does not
force a merge, so required status checks still apply — but *which* checks are required is branch
protection, a repository setting, and therefore **not determinable from the tree**. And the
major/non-major split is only as trustworthy as `fetch-metadata`'s classification of the bot's own PR.

## Work tracking (beads / `bd`)

Work state lives under `.beads/`. The tracked files at `9f6d6e2` are `config.yaml`,
`interactions.jsonl`, `metadata.json`, `README.md`, and `.gitignore`. **There is no
`.beads/issues.jsonl`** in this repo — do not go looking for one; the issue store is not a tracked
JSONL here — `verified-against-code` — `git ls-files .beads/`.

The `bd` command set below is the workflow `AGENTS.md` prescribes, not something the tree enforces —
`asserted-unverified` — `AGENTS.md`.

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
| **Never run `bd github sync` in this repo** | Mass-pushed 90 internal beads records as GitHub issues #381–#470. Close beads with `bd close`; manage GitHub with `gh` | `asserted-unverified` — `memory/sprint-2026-07-16-issue-zeroing.md`; the issue range #381–#470 is independently visible on the GitHub repo |
| **Never re-run `scripts/bd_seed_maintainability.sh`** | **NOT idempotent** — running twice creates duplicate epics | `verified-against-code` — `scripts/bd_seed_maintainability.sh:13-14` |
| Do not use `bd edit` | Opens `$EDITOR`, blocks non-interactive agents | `asserted-unverified` — `AGENTS.md` |
| Do not use TodoWrite / markdown files for task tracking when beads is the project tracker | Session policy, not enforced by anything in the tree | `asserted-unverified` — `AGENTS.md` |

Seed script dry-run only if needed: `./scripts/bd_seed_maintainability.sh --dry-run` — `verified-against-code` — `scripts/bd_seed_maintainability.sh:14`.

### Authority conflict (push)

- `AGENTS.md` “Landing the Plane” says work is incomplete until `git push` succeeds.
- Session hooks / user rules default to **conservative**: commit/push only with explicit authority.

**Agents must treat user/orchestrator instructions as highest precedence** when those conflict —
`asserted-unverified` — `AGENTS.md` "Landing the Plane" versus the session-level commit/push policy.

## Agent checklist when filing or answering bugs

1. Require real integration debug logs (not companion logcat).
2. Prefer diagnostics JSON from HA (credentials redacted; serials aliased on recent versions).
3. Do not fight the auto-closer — attach a valid log and let reopen automation run.
4. Track agent work in beads; never `bd github sync`; never re-seed maintainability.
