---
description: "Promote to stable release: consolidate pre-release changelogs, delete alpha/beta/rc tags, create stable GitHub release (triggers HACS update)."
---

# Ship Release

Promote the current version to a stable release. Consolidates all pre-release
changelog entries into a single release entry, cleans up pre-release tags,
and creates the stable GitHub release that triggers HACS update.

## Workflow

### Step 1: Validate Readiness

1. Read version from `custom_components/eg4_web_monitor/manifest.json`
2. Check that at least one pre-release tag exists for this version:
   ```bash
   git tag --list "v${VERSION}-*" --sort=-version:refname
   ```
   If no pre-release tags exist, stop: "No pre-releases found for v${VERSION}. Run /ship-pre first."
3. Check that an `rc` tag exists (recommended but not required):
   ```bash
   git tag --list "v${VERSION}-rc.*"
   ```
   If no RC tag exists, warn: "No RC tag found. Recommended to run /ship-pre rc first." Ask for confirmation.
4. Run quality gates one final time:
   ```bash
   uv run ruff check custom_components/ --fix && uv run ruff format custom_components/
   uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
   uv run pytest tests/ -x --tb=short
   ```

### Step 2: Consolidate CHANGELOG.md

1. Read `CHANGELOG.md`
2. Find ALL pre-release sections for this version:
   - `## [${VERSION}-alpha.N]` sections
   - `## [${VERSION}-beta.N]` sections
   - `## [${VERSION}-rc.N]` sections
3. Merge all entries from pre-release sections into a single stable section:
   - Deduplicate entries (same fix may appear in alpha and beta changelogs)
   - Organize into Keep a Changelog categories: Added, Fixed, Changed, Removed, Security
   - Preserve GitHub issue references
   - Remove pre-release section headers
4. Create the stable release section:
   ```markdown
   ## [${VERSION}] - ${DATE}

   ${CONSOLIDATED_CHANGES}
   ```
5. Remove the individual pre-release sections (they're now consolidated)
6. Remove `[Unreleased]` section if empty
7. Commit:
   ```bash
   git add CHANGELOG.md
   git commit -m "docs: consolidate changelog for v${VERSION} release"
   git push
   ```

### Step 3: Delete Pre-Release Tags

```bash
# List all pre-release tags for this version
PRETAGS=$(git tag --list "v${VERSION}-*")

# Delete remote pre-release tags
for tag in $PRETAGS; do
  git push origin --delete "$tag"
done

# Delete local pre-release tags
for tag in $PRETAGS; do
  git tag --delete "$tag"
done
```

### Step 4: Delete GitHub Pre-Releases

```bash
# Delete all pre-release GitHub releases for this version
for tag in $PRETAGS; do
  gh release delete "$tag" --yes 2>/dev/null
done
```

### Step 5: Create Stable Release Tag

```bash
git tag "v${VERSION}"
git push origin "v${VERSION}"
```

### Step 6: Create GitHub Release (Triggers HACS)

```bash
gh release create "v${VERSION}" \
  --title "v${VERSION}" \
  --latest \
  --notes "$(cat <<'EOF'
## v${VERSION}

${CONSOLIDATED_CHANGELOG_SECTION}

### Installation

#### HACS (Recommended)
This release will appear automatically in HACS. Go to HACS → Integrations → Updates.

#### Manual Install
Download `eg4_web_monitor.zip` from this release and extract to `custom_components/eg4_web_monitor/`.

### Upgrade Notes
${BREAKING_CHANGES_IF_ANY}

Restart Home Assistant after updating.
EOF
)"
```

### Step 7: Post-Release Sync

```bash
GITHUB_TOKEN=$(gh auth token) bd github sync
```

### Step 8: Summary

Print:
```
Release Published
=================
Version: v${VERSION}
Tag: v${VERSION}
Pre-release tags cleaned: N deleted

Changes included:
  Added: N items
  Fixed: N items
  Changed: N items

HACS will pick up this release automatically.

Pre-release history (consolidated):
  alpha.1 (${DATE}) → alpha.2 (${DATE}) → beta.1 (${DATE}) → rc.1 (${DATE}) → stable
```

### Rules

- **CHANGELOG.md must be consolidated** — no release without clean changelog
- **All pre-release tags are deleted** — only the stable tag remains
- **All pre-release GitHub releases are deleted** — clean release page
- **Quality gates must pass** — final verification before stable release
- **The stable GitHub release triggers HACS** — this is the production deploy
- **Never skip the RC stage for major versions** — alpha → beta → rc → stable
- **Patch releases (x.y.Z) can skip alpha/beta** if the fix is trivial and well-tested
