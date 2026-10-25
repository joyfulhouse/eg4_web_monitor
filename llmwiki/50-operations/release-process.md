---
canonical-for: two-repo release ordering, artifact-trust gate before a pin move, version scheme, manifest pin coupling, HACS zip publish
sources:
  - pylxpweb@cac7a9f498aa20528577a08ce1541fdb59f77481:.github/workflows/release.yml
  - pylxpweb@cac7a9f498aa20528577a08ce1541fdb59f77481:.github/WORKFLOWS.md
  - pylxpweb@cac7a9f498aa20528577a08ce1541fdb59f77481:pyproject.toml
  - pylxpweb@204b95d:.github/workflows/release.yml
  - custom_components/eg4_web_monitor/manifest.json
  - tests/requirements-test.txt
  - .github/workflows/release.yml
  - hacs.json
  - CHANGELOG.md
  - docs/production/pylxpweb-b14-publication-2026-10-25.json
verified-against:
  pylxpweb: cac7a9f498aa20528577a08ce1541fdb59f77481
  eg4_web_monitor: c336cb58ef6be127c03bd3a4b7ac369c06280192
last-verified: 2026-10-25
see-also:
  - ../20-pylxpweb/release-and-pinning.md
runbook-status: untested-as-written
last-executed: never
---

# Release process

This page owns two-repository publication ordering and the artifact-trust gate. Dependency-string locations and runtime version derivation belong to [release and pinning](../20-pylxpweb/release-and-pinning.md). Evidence grades follow the [canonical legend](../README.md).

Dated execution evidence is recorded separately in the [October 25 library publication record](../../docs/production/pylxpweb-b14-publication-2026-10-25.json), including source identity, artifact digests, independent checks and smoke outcome. `asserted-unverified` - the named execution record; this page describes the reusable procedure rather than recapturing that run.

## Two-repo ordering constraint (hard)

Publish and verify the library before advancing the integration dependency. Local source checkouts and bind mounts do not establish that Home Assistant or CI can obtain the intended published package. `inferred` from integration `manifest.json` -> `requirements`, `tests/requirements-test.txt`, and library `release.yml` -> `verify-pypi`.

| Stage | Required action | Evidence |
|---|---|---|
| Library candidate | Prepare the final version, lockfile metadata and release notes in one candidate PR. Complete CI on its exact final head. Merge with **Create a merge commit**, not squash or rebase. | `verified-against-code` - library `release.yml` -> `bind-source`; `.github/WORKFLOWS.md` -> Release procedure |
| Publication | Recheck release settings and candidate identity, then tag the current-main merge with `v` plus its package version and publish its GitHub Release. The published-release event starts automatic TestPyPI-to-PyPI promotion. | `verified-against-code` - library `release.yml` -> `on.release`, `bind-source`, `publish-testpypi`, `publish-pypi` |
| Artifact gate | Require successful terminal verification and independently bind the package bytes to the reviewed source; perform a clean installed-artifact smoke test before the consumer pin changes. | `inferred` - library `release.yml` -> `verify-pypi` verifies provenance and bytes, but supplies no installed-package recovery smoke step |
| Consumer pin | Update the paired integration requirements together, describe the dependency change in its changelog, and validate consumers against the verified published artifact. See the pin-mechanics owner for the requirement syntax. | `inferred` from integration `manifest.json`, `tests/requirements-test.txt` lockstep comment, and `CHANGELOG.md` dependency declarations |
| Integration release | Prepare the integration version and release notes, complete its release gates, then publish the integration release asset. A library publication alone does not publish the integration. | `verified-against-code` - integration `.github/workflows/release.yml` -> `on.release`, `Create release asset`, `Upload release asset` |

The workflow has no manual approval pause between the GitHub Release and package promotion. Any publication authorization required by the active task must therefore be obtained before publishing the GitHub Release. The absence of a workflow pause is `verified-against-code` in library `release.yml` and documented in `.github/WORKFLOWS.md` -> Release procedure; workflow capability does not itself grant task authorization.

## Library release identity and protection

| Boundary | Contract | Evidence |
|---|---|---|
| Trigger | `release: published` is the only package-release trigger. There is no `workflow_dispatch` input or branch-form manual publication path. Pushing a tag alone does not trigger this workflow. | `verified-against-code` - library `release.yml` -> `on` |
| Version and tag | The peeled tag, event SHA, checked-out HEAD and tag-resident workflow SHA must identify the same commit; project name and version must match the expected package and tag. | `verified-against-code` - `bind-source` |
| Merge and CI | The tag commit must have two parents, the first parent must be an ancestor of the final PR head, and the merge tree must equal that head's tree. The associated PR must be merged into main and its exact head must have successful repository CI. Review-count approval is not part of this workflow binding. | `verified-against-code` - `bind-source` |
| Main freshness | The workflow fetches main and requires equality at initial binding and again immediately before artifact sealing. Later main movement does not alter the sealed bytes. | `verified-against-code` - `bind-source`, `seal-source` |
| Mutable protections | Recheck main protection, `v*` tag update/deletion rules, tag-only `testpypi`/`pypi` deployment policies, and trusted-publisher bindings before each release. Environment tag filtering is not tag immutability. A GitHub Release is not a substitute for missing tag protection. | `inferred` from `.github/WORKFLOWS.md` -> repository/environment settings requirements; these settings are outside the pinned source tree |
| Concurrency | The workflow concurrency group includes the release tag and does not cancel an existing run. It is not a global mutex across different version tags. | `verified-against-code` - `release.yml` -> `concurrency` |

## The artifact-trust gate

Availability alone does not establish provenance. Successful installation or a visible index page cannot prove which reviewed tree produced the package or that both indexes received identical bytes. The gate derives identity from the workflow, sealed bundle and downloaded artifacts. `inferred` from library `release.yml` -> `bind-source`, `verify-release-bundle`, `classify-pypi-state`.

| Check | Required evidence | Evidence source |
|---|---|---|
| Source binding | Tag, merge, tree, final PR/head, project version and tag-resident workflow identity agree with the approved candidate. | `verified-against-code` - `bind-source`, `write-source-manifest` -> `release-source.json` |
| Reproducible build | Exactly one wheel and one sdist are built once in the pinned uv/Python container with no network, read-only source/root, empty ephemeral cache, and `SOURCE_DATE_EPOCH` derived from the merge commit. Metadata must match the bound package/version. | `verified-against-code` - `build-distributions`, `validate-distributions` |
| Sealed bundle | Exact bundle file set, distribution hashes, source manifest and separate source/build attestations verify. The artifact is identified by its originating run, name, ID, source SHA and upload digest, not by a convenient filename alone. | `verified-against-code` - `assemble-sealed-bundle`, `verify-release-bundle`, `resolve-release-artifact` |
| Attestation identity | `gh attestation verify` binds subjects to the repository, signer workflow, signer digest, tag source-ref and source commit. Verify the source manifest as well as both distributions. | `verified-against-code` - shared `verify-release-bundle` script |
| TestPyPI bytes | Exact non-yanked filenames and SHA-256 values match the sealed artifact; allowlisted HTTPS downloads are rehashed and a second index snapshot checks stability. | `verified-against-code` - `verify-testpypi` |
| PyPI completion | Fresh classification checks the same artifact and remote bytes. **Only successful `verify-pypi` with `EXACT_COMPLETE` establishes workflow completion**, including when the publisher was skipped or its response failed. | `verified-against-code` - `prepare-pypi`, `verify-pypi` -> `require-exact-complete` |
| Consumer smoke | Install the verified wheel in a clean environment, verify distribution version and import location, and exercise relevant offline behavior before advancing the integration pin. Retain the provenance/hashes alongside smoke results. | `inferred` - the workflow's byte/provenance checks do not execute this consumer-level acceptance |

Keep the distinction between a published package, independently verified package bytes, a passing consumer test and an authorized deployment. None establishes hardware register semantics or acceptance on an untested device. `inferred` from the separate library publication workflow and integration release workflow; see the canonical evidence legend.

## Retry and immutable-version handling

Use the library's pinned `.github/WORKFLOWS.md` -> PyPI recovery runbook for the actual recovery invocation. Recovery starts at **`prepare-pypi` and its dependent jobs**, with fresh classification. Do not rerun all jobs, directly retry the publisher, rebuild under an occupied version, or move/delete published tags and releases as ordinary recovery. `asserted-unverified` - operational requirements in library `.github/WORKFLOWS.md` -> PyPI recovery runbook.

| Classifier result | Consequence | Evidence |
|---|---|---|
| `ABSENT` | A stable clean-absence result permits staging the complete pair for publication. | `verified-against-code` - `classify-pypi-state`, `publish-pypi` condition |
| `EXACT_COMPLETE` | Skip republication; terminal verification completes against the existing exact bytes. | `verified-against-code` - `publish-pypi`, `require-exact-complete` |
| `PARTIAL` | Terminal failure; preserve evidence and treat the version as burned. Never top up missing files. | `verified-against-code` - `require-exact-complete` |
| `MISMATCH`, `YANKED`, `EXTRA`, `COMPETING` | Terminal failure; preserve evidence and follow the compromise/new-version runbook. | `verified-against-code` - `require-exact-complete` |
| `UNCERTAIN` | Do not publish. Retry the classifier/verifier recovery chain after the evidence problem is understood; unavailable evidence is not absence. | `verified-against-code` - `classify-pypi-state`, `publish-pypi`, `require-exact-complete` |

## Integration release steps

| Boundary | Behavior | Evidence |
|---|---|---|
| Version and notes | The integration manifest supplies the version; release notes declare the exact library requirement and link its release. The integration uses `X.Y.Z-beta.N` prereleases and matching `v` tags. | `verified-against-code` for manifest/declared requirement; `asserted-unverified` for the release naming convention in `CHANGELOG.md` |
| Trigger and asset | A published GitHub Release triggers creation of `eg4_web_monitor.zip` from the component directory and attaches it to the release. No manual-dispatch path is declared. | `verified-against-code` - integration `.github/workflows/release.yml` |
| Exclusions | The zip command excludes `*.env`, `.env`, `secrets.py`, bytecode, named cache directories and `.git/*`; this is the actual exclusion list, not a guarantee that arbitrary sensitive files cannot be present. | `verified-against-code` - `Create release asset` |
| HACS configuration | `hacs.json` selects zip releases and names `eg4_web_monitor.zip`; consult that file for the HA minimum and other installation settings. | `verified-against-code` - `hacs.json` -> `zip_release`, `filename`, `homeassistant`, `content_in_root` |

## Historical lesson: sequencing is not provenance

At library `204b95d`, the release workflow accepted `workflow_dispatch` with an environment choice and checked out `github.event.release.tag_name || github.ref`. TestPyPI-first promotion did not bind an arbitrary dispatched ref to a reviewed merge. That historical mechanism is **superseded**, not an executable alternative to the tag-bound workflow above. `verified-against-code` - `pylxpweb@204b95d:.github/workflows/release.yml` -> `on.workflow_dispatch`, `build` checkout; compare the current `bind-source`.

The lasting lessons are to distinguish ordering from source identity, OIDC publisher identity from reviewed-content identity, and a tag's observed target from protection against later mutation. Annotated tags add metadata; neither annotated nor lightweight tag shape replaces access controls and attestations. `inferred` from the historical checkout and current source/attestation gates. Recheck mutable settings rather than carrying a historical successful observation forward as a permanent guarantee.
