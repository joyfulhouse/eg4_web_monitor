---
canonical-for: two-repo release ordering, version scheme, manifest pin coupling, HACS zip publish
sources:
  - /tmp/llmwiki-research/repo-operations.md
  - docs/DEVELOPMENT.md
  - CHANGELOG.md
  - custom_components/eg4_web_monitor/manifest.json
  - tests/requirements-test.txt
  - hacs.json
  - .github/workflows/release.yml
  - ../python/pylxpweb/docs/DEVELOPMENT.md
  - ../python/pylxpweb/.github/workflows/release.yml
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Release process

Highest-risk operational rule in this project: **publish pylxpweb to PyPI before bumping the integration pin.** Getting the order wrong breaks CI and Home Assistant installs.

## Two-repo ordering constraint (hard)

**verified-against-code** / operational record — pin locations + CHANGELOG “Requires pylxpweb>=…” coupling; dossier §5.4.

| Step | Repo | Action |
|------|------|--------|
| 1 | **pylxpweb** | Bump `pyproject.toml` version, update CHANGELOG, tag, publish GitHub Release → workflow publishes TestPyPI then PyPI |
| 2 | **wait** | Confirm the wheel is installable (`pip install pylxpweb==…` / PyPI page) |
| 3 | **eg4_web_monitor** | Bump **both** `manifest.json` `requirements` and `tests/requirements-test.txt` in lockstep; add CHANGELOG “Requires pylxpweb>=…” note |
| 4 | **eg4_web_monitor** | Bump `manifest.json` `version`, move Unreleased CHANGELOG entries, tag `vX.Y.Z` / `vX.Y.Z-beta.N`, publish GitHub Release |

**Do not bump the integration pin before the library is on PyPI.** Dev docker bind-mounts bypass PyPI for local validation, but **CI and end users require the published wheel**.

```bash
# 1) pylxpweb: bump pyproject version, changelog, tag, publish GitHub release → PyPI
# 2) Wait until pip can install the new version
# 3) eg4: bump manifest.json requirements + tests/requirements-test.txt + CHANGELOG Requires line
# 4) Tag/publish integration release
```

## Where versions live

| Project | Source of truth | Scheme |
|---------|-----------------|--------|
| eg4_web_monitor | `custom_components/eg4_web_monitor/manifest.json` → `"version"` | SemVer + prerelease: `X.Y.Z`, `X.Y.Z-beta.N`, `X.Y.Z-rc.N`; Git tags `vX.Y.Z` / `vX.Y.Z-beta.N` |
| pylxpweb | `pyproject.toml` `[project].version` | PEP 440 (e.g. `0.9.39b10`); Git tags `v0.9.39b10` |

**verified-against-code** — `docs/DEVELOPMENT.md:57-64`; manifest `version` field; pylxpweb `pyproject.toml`.

Snapshot at `9f6d6e2` (will drift — re-read files, do not hard-code forever):

| Field | Value at verify |
|-------|-----------------|
| Integration version | `3.5.1-beta.10` |
| Integration pin | `pylxpweb>=0.9.39b10` |
| `tests/requirements-test.txt` | `pylxpweb>=0.9.39b10  # keep in sync with manifest.json` |

**Note:** `CLAUDE.md` Current Version may lag the manifest — prefer `manifest.json` — **verified-against-code** vs dossier §9 contradiction table.

## Integration pin locations (must stay equal)

**verified-against-code**

1. `custom_components/eg4_web_monitor/manifest.json` → `"requirements": ["pylxpweb>=…", …]`
2. `tests/requirements-test.txt` → `pylxpweb>=…  # keep in sync with manifest.json`
3. CI Platinum mypy job reads the pin from `tests/requirements-test.txt` dynamically (`quality-validation.yml` ~793–801) so typecheck matches tests.

CHANGELOG convention: each beta/stable header states **Requires pylxpweb>=…** with a GitHub release link — first-class release note, not optional commentary.

## Integration release steps

**verified-against-code** — `docs/DEVELOPMENT.md:57-64`, `.github/workflows/release.yml`

1. Bump `version` in `manifest.json`.
2. Move `Unreleased` CHANGELOG entries under the new version heading (Keep a Changelog).
3. Ensure pylxpweb pin already published (ordering constraint above).
4. Tag `vX.Y.Z` (or `vX.Y.Z-beta.N` / `vX.Y.Z-rc.N`).
5. Publish GitHub Release → `release.yml` builds a zip of `custom_components/eg4_web_monitor` and attaches `eg4_web_monitor.zip`.
6. HACS consumes the tagged release.

Zip exclusions (secrets must never ship) — **verified-against-code** — `release.yml:20-29`:

- `*.env`, `.env`, `secrets.py`
- `*.pyc`, `__pycache__/*`, caches, `.git/*`

## How HACS consumes releases

**verified-against-code** — `hacs.json`

| Key | Value |
|-----|-------|
| `zip_release` | `true` |
| `filename` | `eg4_web_monitor.zip` |
| `homeassistant` | `>=2026.1.0` (minimum HA version) |
| `content_in_root` | `false` |

HACS installs from the GitHub Release asset produced by `release.yml`, not from raw tree contents.

## pylxpweb release / PyPI publish

**verified-against-code** — pylxpweb `docs/DEVELOPMENT.md`, pylxpweb `.github/workflows/release.yml`

1. Bump version in `pyproject.toml`.
2. Update pylxpweb `CHANGELOG.md`.
3. Tag and publish a GitHub Release (e.g. `gh release create v0.9.39b10 …`).
4. Workflow **Publish to PyPI** on `release: published`:
   - Build with `uv build`
   - Publish to **TestPyPI** (OIDC environment `testpypi`)
   - Then publish to **PyPI** (OIDC environment `pypi`)
5. Manual `workflow_dispatch` may allow `skip-publish` / target selection — check the workflow file before relying on it.

## SemVer / prerelease ordering reminder

Observed line: `…-beta.N` < `…-rc.N` < final `X.Y.Z` (e.g. beta.27 < rc.1 < 3.4.0) — **inferred** from CHANGELOG release narrative; treat as project convention when cutting candidates.
