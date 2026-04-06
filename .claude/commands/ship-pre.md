---
description: "Create a pre-release for community testing. Tags progress: alpha → beta → rc. Pass 'alpha', 'beta', or 'rc' to set the stage."
---

# Ship Pre-Release

Create a pre-release tag for community testing. Tags follow the progression:
`vX.Y.Z-alpha.N` → `vX.Y.Z-beta.N` → `vX.Y.Z-rc.N` → stable (via `/ship-release`).

## Input

- `$ARGUMENTS` — pre-release stage: `alpha`, `beta`, or `rc` (required)

## Workflow

### Step 1: Determine Version

1. Read current version from `custom_components/eg4_web_monitor/manifest.json` → `"version"` field
2. Check existing pre-release tags for this version:
   ```bash
   git tag --list "v${VERSION}-*" --sort=-version:refname
   ```
3. Determine next tag:
   - If `$ARGUMENTS` is `alpha`: `v${VERSION}-alpha.N` (N = next alpha number, starting at 1)
   - If `$ARGUMENTS` is `beta`: `v${VERSION}-beta.N` (must have at least one alpha first)
   - If `$ARGUMENTS` is `rc`: `v${VERSION}-rc.N` (must have at least one beta first)

**Progression enforcement:**
- `alpha` — can always create (first testing stage)
- `beta` — requires at least one `alpha` tag for this version
- `rc` — requires at least one `beta` tag for this version

If progression is violated, warn and ask for confirmation before proceeding.

### Step 2: Update CHANGELOG.md

1. Read `CHANGELOG.md`
2. If no `[Unreleased]` section exists at top, create one
3. Collect all changes since the last tag:
   ```bash
   git log $(git describe --tags --abbrev=0)..HEAD --oneline --no-merges
   ```
4. Organize commits into Keep a Changelog categories:
   - `### Added` — new features (`feat:`)
   - `### Fixed` — bug fixes (`fix:`)
   - `### Changed` — modifications (`refactor:`, `perf:`)
   - `### Removed` — removed features
   - `### Security` — security fixes
5. Add a pre-release section header: `## [${VERSION}-${STAGE}.${N}] - ${DATE}`
6. Include GitHub issue references where available (from commit messages)
7. Commit the changelog update:
   ```bash
   git add CHANGELOG.md
   git commit -m "docs: update changelog for v${VERSION}-${STAGE}.${N}"
   git push
   ```

### Step 3: Create Pre-Release Tag

```bash
git tag "v${VERSION}-${STAGE}.${N}"
git push origin "v${VERSION}-${STAGE}.${N}"
```

### Step 4: Create GitHub Pre-Release

```bash
gh release create "v${VERSION}-${STAGE}.${N}" \
  --title "v${VERSION}-${STAGE}.${N}" \
  --prerelease \
  --notes "$(cat <<'EOF'
## Pre-release: ${STAGE} ${N}

${CHANGELOG_SECTION}

### Testing Instructions

Install this pre-release via HACS:
1. Go to HACS → Integrations → 3-dot menu → Custom Repositories
2. Add: https://github.com/joyfulhouse/eg4_web_monitor
3. Select version: v${VERSION}-${STAGE}.${N}
4. Restart Home Assistant

### Reporting Issues

Please report any issues at https://github.com/joyfulhouse/eg4_web_monitor/issues
Include your device model, firmware version, and connection mode (Cloud/Local/Hybrid).
EOF
)"
```

### Step 5: Summary

Print:
```
Pre-Release Created
===================
Tag: v${VERSION}-${STAGE}.${N}
Stage: ${STAGE} (next: ${NEXT_STAGE})
Changes: N commits since last tag

Pre-release progression for v${VERSION}:
  ✓ alpha.1, alpha.2 (completed)
  → beta.1 (current)
  ○ rc.1 (next)
  ○ stable (via /ship-release)
```

### Rules

- **Always update CHANGELOG.md** before tagging — no changelog, no release
- **Pre-release changelogs are cumulative** — each stage includes changes from prior stages
- **Never delete pre-release tags** — they serve as audit trail (cleanup happens in `/ship-release`)
- **Alpha = internal testing**, beta = community testing, rc = release candidate (feature-frozen)
- **No new features in rc** — only bug fixes allowed after beta stage
- **Quality gates must pass** before any pre-release tag
