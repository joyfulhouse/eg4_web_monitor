---
canonical-for: pylxpweb version derivation and eg4_web_monitor dependency pin mechanics
sources:
  - pylxpweb@cac7a9f498aa20528577a08ce1541fdb59f77481:pyproject.toml
  - pylxpweb@cac7a9f498aa20528577a08ce1541fdb59f77481:src/pylxpweb/__init__.py
  - custom_components/eg4_web_monitor/manifest.json
  - tests/requirements-test.txt
  - .github/workflows/quality-validation.yml
verified-against:
  pylxpweb: cac7a9f498aa20528577a08ce1541fdb59f77481
  eg4_web_monitor: c336cb58ef6be127c03bd3a4b7ac369c06280192
last-verified: 2026-10-25
see-also:
  - ../50-operations/release-process.md
---

# Release and pinning

Evidence grades follow the [canonical llmwiki legend](../README.md). This page owns version derivation and dependency mechanics; publication ordering and artifact trust belong to the [release-process owner](../50-operations/release-process.md).

## Version authority

| Context | Authority | Evidence |
|---|---|---|
| Library build | `pyproject.toml` -> `[project].version` declares the package version; read it at the exact candidate commit. | `verified-against-code` - library `pyproject.toml` |
| Installed runtime | `pylxpweb.__version__` comes from `importlib.metadata.version("pylxpweb")`. | `verified-against-code` - library `src/pylxpweb/__init__.py` -> `__version__` |
| Missing distribution metadata | `PackageNotFoundError` falls back to `"0.0.0-dev"`. A source checkout alone does not identify an installed release. | `verified-against-code` - library `src/pylxpweb/__init__.py` -> version exception handler |
| Integration version/dependency | `custom_components/eg4_web_monitor/manifest.json` owns the integration's `version` and runtime `requirements`. | `verified-against-code` - integration manifest |

Do not introduce a second hard-coded library runtime version. An editable/source installation can expose different source bytes from the distribution metadata it finds; verify import location as well as metadata when checking a published wheel. `inferred` from library `__version__` using installed metadata independently of module source paths.

## Exact integration pin

The integration's pylxpweb requirement uses **`==`**, not a minimum-version floor. Read the actual version from the manifest rather than maintaining another current-version table here. The paired test requirement explicitly requires lockstep. `verified-against-code` - `manifest.json` -> `requirements`; `tests/requirements-test.txt` -> pylxpweb requirement and inline comment.

| Mechanic | Required action | Evidence |
|---|---|---|
| Select artifact | Complete the release-process owner's published-artifact gate before changing the consumer requirement. | `inferred` - [release-process owner](../50-operations/release-process.md#the-artifact-trust-gate) |
| Runtime requirement | Change the complete `pylxpweb==...` requirement in `custom_components/eg4_web_monitor/manifest.json` to the verified release. | `verified-against-code` - manifest `requirements` |
| Test requirement | Apply the identical exact version in `tests/requirements-test.txt`; preserve the lockstep requirement. | `verified-against-code` - test requirement and inline comment |
| Type-check dependency | The `platinum-strict-typing` installation step extracts `PYLXPWEB_PIN` from `tests/requirements-test.txt` and installs that requirement. The extraction supports exact specifiers and optional extras. | `verified-against-code` - `.github/workflows/quality-validation.yml` -> `Install mypy and dependencies with uv`, `PYLXPWEB_PIN` |
| Pair validation | Compare runtime and test requirement strings in the same change. Changing only one leaves consumers and checks on different package requirements. | `inferred` from the two installation sources above |

An explicit prerelease pin prevents a stable-only dependency expression from hiding prerelease-only APIs during type checking. The workflow comment records the earlier `run_firmware_update_to_completion` failure as the reason for extracting the test requirement instead of hard-coding a stable minimum. The extraction is `verified-against-code`; the historical incident is `asserted-unverified` in `.github/workflows/quality-validation.yml` -> the `PYLXPWEB_PIN` comment.
