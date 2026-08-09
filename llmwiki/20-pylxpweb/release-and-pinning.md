---
canonical-for: pylxpweb version derivation, publication workflow, and eg4_web_monitor dependency ordering
sources:
  - /tmp/llmwiki-research/pylxpweb-library.md
  - /Users/bryanli/Projects/joyfulhouse/python/pylxpweb@204b95d
  - eg4_web_monitor@9f6d6e2
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Release and pinning

Use the evidence-grade meanings defined in [api-surface.md](api-surface.md).

## Version authority

| Context | Authority | Evidence |
|---|---|---|
| Build metadata | `pyproject.toml` declares `version = "0.9.39b10"`. | `verified-against-code` — `pyproject.toml:1-4` in the pylxpweb repository |
| Installed runtime | `pylxpweb.__version__` comes from `importlib.metadata.version("pylxpweb")`. | `verified-against-code` — `src/pylxpweb/__init__.py:42-42`, `src/pylxpweb/__init__.py:97-100` |
| Uninstalled source checkout | Missing distribution metadata falls back to `"0.0.0-dev"`. | `verified-against-code` — `src/pylxpweb/__init__.py:97-100` |

Do not edit a hard-coded package `__version__`; there is none. The installed distribution metadata is runtime-authoritative. `verified-against-code` — `src/pylxpweb/__init__.py:97-100`.

## pylxpweb release workflow

| Order | Action | Evidence |
|---:|---|---|
| 1 | Bump `pyproject.toml` and update `CHANGELOG.md`. | `verified-against-code` — `docs/DEVELOPMENT.md:30-34` in the pylxpweb repository |
| 2 | Tag the version and publish a GitHub Release, or invoke the workflow manually with the intended environment. | `verified-against-code` — `.github/workflows/release.yml:3-18` in the pylxpweb repository |
| 3 | The workflow checks out the selected tag/ref, installs Python with uv, builds, and runs `twine check`. | `verified-against-code` — `.github/workflows/release.yml:29-62` in the pylxpweb repository |
| 4 | Publish the same build artifact to TestPyPI. | `verified-against-code` — `.github/workflows/release.yml:71-91` in the pylxpweb repository |
| 5 | Publish to PyPI only after the TestPyPI job succeeds; authentication uses OIDC. | `verified-against-code` — `.github/workflows/release.yml:25-27`, `.github/workflows/release.yml:93-112` in the pylxpweb repository |

The active trigger is a **published GitHub Release** or manual dispatch, not merely a pushed tag. Follow the active `release.yml` when older workflow prose disagrees. `verified-against-code` — `.github/workflows/release.yml:1-18` in the pylxpweb repository.

## Two-repository ordering constraint

| Phase | pylxpweb repository | eg4_web_monitor repository | Evidence |
|---:|---|---|---|
| 1 | Merge, version, tag/release, and publish the required pylxpweb wheel to **PyPI first**. | Do not raise the integration minimum yet. | `inferred` — pylxpweb `.github/workflows/release.yml:93-112`; integration `custom_components/eg4_web_monitor/manifest.json:13-14` |
| 2 | Confirm the published version is resolvable from PyPI. | Then bump both dependency declarations in the same integration change. | `inferred` — integration `.github/workflows/quality-validation.yml:791-801` |
| 3 | No further library action is required for the pin. | Keep `custom_components/eg4_web_monitor/manifest.json` and `tests/requirements-test.txt` identical for pylxpweb. | `verified-against-code` — `custom_components/eg4_web_monitor/manifest.json:13-14`, `tests/requirements-test.txt:17-17` |

Publishing pylxpweb to PyPI **after** raising the integration requirement reverses the dependency order. Until that wheel exists, CI's installer and Home Assistant cannot resolve the new floor, so CI and installs break. `inferred` — `custom_components/eg4_web_monitor/manifest.json:13-14`, `.github/workflows/quality-validation.yml:791-801`.

## Current integration floor

| File | Required value | Evidence |
|---|---|---|
| `custom_components/eg4_web_monitor/manifest.json` | `pylxpweb>=0.9.39b10` | `verified-against-code` — `custom_components/eg4_web_monitor/manifest.json:13-14` |
| `tests/requirements-test.txt` | `pylxpweb>=0.9.39b10` | `verified-against-code` — `tests/requirements-test.txt:17-17` |

The requirement is a minimum, not an exact lock; a later compatible release may resolve. During beta development the floor must still name the matching beta because a stable-only specifier can hide prerelease-only APIs from type checking. `verified-against-code` — `.github/workflows/quality-validation.yml:791-801`.

## Release checklist for an integration-facing pylxpweb change

| Check | Stop condition | Evidence |
|---|---|---|
| pylxpweb version | `pyproject.toml` contains the intended new version. | `verified-against-code` — pylxpweb `pyproject.toml:1-4` |
| pylxpweb artifact | TestPyPI succeeds before the PyPI job runs. | `verified-against-code` — pylxpweb `.github/workflows/release.yml:71-112` |
| Publication order | The required wheel is resolvable from PyPI before the integration pin changes. | `inferred` — pylxpweb `.github/workflows/release.yml:93-112`; integration `.github/workflows/quality-validation.yml:791-801` |
| Pin lockstep | Manifest and test requirements carry exactly the same `pylxpweb>=...` floor. | `verified-against-code` — `custom_components/eg4_web_monitor/manifest.json:13-14`, `tests/requirements-test.txt:17-17` |
| Runtime version reporting | Validate an installed wheel when checking `__version__`; a source checkout may report `0.0.0-dev`. | `verified-against-code` — pylxpweb `src/pylxpweb/__init__.py:97-100` |
