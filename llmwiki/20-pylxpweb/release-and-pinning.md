---
canonical-for: pylxpweb version derivation and eg4_web_monitor dependency pin mechanics
sources:
  - pylxpweb@204b95d:pyproject.toml
  - pylxpweb@204b95d:src/pylxpweb/__init__.py
  - eg4_web_monitor@9f6d6e2:custom_components/eg4_web_monitor/manifest.json
  - eg4_web_monitor@9f6d6e2:tests/requirements-test.txt
  - eg4_web_monitor@9f6d6e2:.github/workflows/quality-validation.yml
verified-against:
  pylxpweb: 204b95d
  eg4_web_monitor: 9f6d6e2
last-verified: 2026-08-08
---

# Release and pinning

Evidence grades follow the [canonical llmwiki legend](../README.md).

## Version authority

| Context | Authority | Evidence |
|---|---|---|
| Build metadata | `pyproject.toml` declares `version = "0.9.39b10"`. | `verified-against-code` — `pyproject.toml:1-4` in the pylxpweb repository |
| Installed runtime | `pylxpweb.__version__` comes from `importlib.metadata.version("pylxpweb")`. | `verified-against-code` — `src/pylxpweb/__init__.py:42-42`, `src/pylxpweb/__init__.py:97-100` |
| Uninstalled source checkout | Missing distribution metadata falls back to `"0.0.0-dev"`. | `verified-against-code` — `src/pylxpweb/__init__.py:97-100` |

Do not edit a hard-coded package `__version__`; there is none. The installed distribution metadata is runtime-authoritative. `verified-against-code` — `src/pylxpweb/__init__.py:97-100`.

## Canonical release process

Two-repository ordering and publication trust are owned by the [canonical release process](../50-operations/release-process.md); this page keeps only dependency-pin mechanics.

## Current integration floor

| File | Required value | Evidence |
|---|---|---|
| `custom_components/eg4_web_monitor/manifest.json` | `pylxpweb>=0.9.39b10` | `verified-against-code` — `custom_components/eg4_web_monitor/manifest.json:13-14` |
| `tests/requirements-test.txt` | `pylxpweb>=0.9.39b10` | `verified-against-code` — `tests/requirements-test.txt:17-17` |

The requirement is a minimum, not an exact lock; a later compatible release may resolve. During beta development the floor must still name the matching beta because a stable-only specifier can hide prerelease-only APIs from type checking. `verified-against-code` — `.github/workflows/quality-validation.yml:791-801`.

## Pin mechanics

| Mechanic | Required action | Evidence |
|---|---|---|
| Select the floor | Use the version approved by the canonical release process; do not derive it from source-checkout `__version__`, which may be `0.0.0-dev`. | `verified-against-code` — pylxpweb `src/pylxpweb/__init__.py:97-100` |
| Update runtime dependency | Change the `pylxpweb>=...` entry in `custom_components/eg4_web_monitor/manifest.json`. | `verified-against-code` — `custom_components/eg4_web_monitor/manifest.json:13-14` |
| Update test dependency | Apply the identical minimum in `tests/requirements-test.txt`; its inline comment requires lockstep with the manifest. | `verified-against-code` — `tests/requirements-test.txt:17-17` |
| Preserve beta visibility | When the integration consumes prerelease-only APIs, keep the prerelease minimum explicit so the type-check job installs the intended surface. | `verified-against-code` — `.github/workflows/quality-validation.yml:791-801` |
| Verify the pair | Compare both requirement strings in the same integration change; a one-file pin update is incomplete. | `verified-against-code` — `custom_components/eg4_web_monitor/manifest.json:13-14`, `tests/requirements-test.txt:17-17` |
