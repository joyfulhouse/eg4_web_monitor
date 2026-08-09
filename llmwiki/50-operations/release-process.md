---
canonical-for: two-repo release ordering, artifact-trust gate before a pin move, version scheme, manifest pin coupling, HACS zip publish
sources:
  - docs/DEVELOPMENT.md
  - CHANGELOG.md
  - custom_components/eg4_web_monitor/manifest.json
  - tests/requirements-test.txt
  - hacs.json
  - .github/workflows/release.yml
  - pylxpweb docs/DEVELOPMENT.md
  - pylxpweb .github/workflows/release.yml
verified-against:
  eg4_web_monitor: 9f6d6e2
  pylxpweb: 204b95d
last-verified: 2026-08-09
---

# Release process

Highest-risk operational rule in this project: **publish pylxpweb to PyPI before bumping the integration pin.** Getting the order wrong breaks CI and Home Assistant installs.

## Two-repo ordering constraint (hard)

This page owns the full ordering procedure. `20-pylxpweb/release-and-pinning.md` owns pin
mechanics (where the floor lives, how `__version__` resolves) and links here for ordering.

| Step | Repo | Action |
|------|------|--------|
| 1 | **pylxpweb** | Bump `pyproject.toml` version, update CHANGELOG, tag, publish GitHub Release → `release.yml` builds once, publishes TestPyPI, then PyPI |
| 2 | **gate** | **Verify the published artifact** — provenance, not availability. See the gate below; it is the step this project has historically shortcut |
| 3 | **eg4_web_monitor** | Bump **both** `manifest.json` `requirements` and `tests/requirements-test.txt` in lockstep; add CHANGELOG “Requires pylxpweb>=…” note |
| 4 | **eg4_web_monitor** | Bump `manifest.json` `version`, move Unreleased CHANGELOG entries, tag `vX.Y.Z` / `vX.Y.Z-beta.N`, publish GitHub Release |

Pin locations and the CHANGELOG “Requires pylxpweb>=…” coupling are `verified-against-code` —
`custom_components/eg4_web_monitor/manifest.json:13`, `tests/requirements-test.txt:17`, `CHANGELOG.md`.

**Do not bump the integration pin before the library is on PyPI.** Dev docker bind-mounts bypass
PyPI for local validation, but **CI and end users require the published wheel** — `inferred` from
`manifest.json:13` (`requirements`) plus the `platinum-strict-typing` job installing the pin from
`tests/requirements-test.txt`.

### Step 2: the artifact-trust gate

`pip install pylxpweb==X` succeeding, or the PyPI page rendering, proves only that **something**
exists at that version. It does not prove that the artifact came from the reviewed commit, that it
was built by the release workflow, or that TestPyPI and PyPI received the same file. Availability is
not provenance. Check all five before moving the pin:

All five re-verified against pylxpweb `.github/workflows/release.yml` at **`204b95d`**; line numbers below
are that revision's.

| # | Check | How | Grade |
|---|-------|-----|-------|
| 1 | **Ref → commit** | Confirm what was actually built. The build job checks out `github.event.release.tag_name \|\| github.ref` — a **published release** builds its tag; a **manual dispatch** builds whatever ref the dispatcher picked. Check the run's ref, then `git rev-parse 'v0.9.39b10^{commit}'` against the reviewed merge commit, and confirm the tag is protected against being moved | `verified-against-code` — pylxpweb@`204b95d` `release.yml:35-37` (`build` → `actions/checkout` `ref:`). See [Sequencing is not provenance](#sequencing-is-not-provenance) |
| 2 | **Commit → version** | `pyproject.toml` `[project].version` **at that tag** equals the version now on PyPI. Nothing overrides it: the job runs a bare `uv build` against the checked-out tree, so the version is whatever that ref declares. A tag on the wrong commit ships the wrong version silently | `verified-against-code` — pylxpweb@`204b95d` `release.yml:52` (`uv build`), `:37` (checkout ref) |
| 3 | **Trusted Publisher provenance** | Publication is OIDC, not a stored API token: the workflow sets `id-token: write` at workflow level and again on each publish job, and both use `pypa/gh-action-pypi-publish@release/v1` against GitHub Environments `testpypi` / `pypi`. On PyPI, confirm the release shows the Trusted Publisher and the originating workflow run | `verified-against-code` — pylxpweb@`204b95d` `release.yml:25-27` (workflow `permissions:`), `:77-79` / `:99-101` (job `environment:` + `permissions:`), `:88` / `:110` (publish action) |
| 4 | **Artifact hashes** | Both publish steps set `print-hash: true`. Take the wheel/sdist hashes from the run log and compare them to the hashes PyPI lists for the release. Equal hashes on the TestPyPI and PyPI steps prove the same file reached both indexes | `verified-against-code` — pylxpweb@`204b95d` `release.yml:91`, `:112` |
| 5 | **Same-artifact promotion** | Nothing is rebuilt between indexes. `build` uploads one artifact (`python-package-distributions`); both publish jobs download **that** artifact rather than rebuilding, so the file `twine check` validated is the file promoted | `verified-against-code` — pylxpweb@`204b95d` `release.yml:57-61` (upload), `:81-85` / `:103-107` (download), `:55` (`twine check`) |

Only after those pass does `pip install pylxpweb==X` in a clean environment mean anything — and then
it is a resolvability check, not a trust check.

```bash
# 1) pylxpweb: bump pyproject version, changelog, tag, publish GitHub release
# 2) GATE: tag→commit, commit→version, Trusted Publisher, hashes, same-artifact promotion
#          then confirm resolvability in a clean env:
#          uv run --isolated --with 'pylxpweb==X' python -c 'import pylxpweb'
# 3) eg4: bump manifest.json requirements + tests/requirements-test.txt + CHANGELOG Requires line
# 4) Tag/publish integration release
```

**What the gate does not cover.** Two limits, both structural:

1. **No smoke test.** The workflow never installs or imports the TestPyPI artifact before promoting
   it. TestPyPI success means "upload accepted", not "the package works". `publish-testpypi` has
   exactly two steps — download the artifact, publish it — and nothing between it and `publish-pypi`.
   The clean-env install above is the only import check in the chain, and it runs after PyPI
   publication — `verified-against-code` — pylxpweb@`204b95d` `release.yml:80-91` (the job's complete
   step list), `:93-112`.
2. **No enforced provenance.** Checks 1–5 are things a human performs *after* the fact; the workflow
   itself never verifies that what it built came from a reviewed, immutable ref. On a manual dispatch
   it builds whatever ref the dispatcher selected. See
   [Sequencing is not provenance](#sequencing-is-not-provenance) and the preconditions that follow it
   before using the manual `pypi` path at all.

## Where versions live

| Project | Source of truth | Scheme |
|---------|-----------------|--------|
| eg4_web_monitor | `custom_components/eg4_web_monitor/manifest.json` → `"version"` | SemVer + prerelease: `X.Y.Z`, `X.Y.Z-beta.N`, `X.Y.Z-rc.N`; Git tags `vX.Y.Z` / `vX.Y.Z-beta.N` |
| pylxpweb | `pyproject.toml` `[project].version` | PEP 440 (e.g. `0.9.39b10`); Git tags `v0.9.39b10` |

`verified-against-code` — eg4_web_monitor@`9f6d6e2` `custom_components/eg4_web_monitor/manifest.json:14`
(`version`); pylxpweb@`204b95d` `pyproject.toml:1-3` (`[project]` … `version = "0.9.39b10"`). The
SemVer/Keep-a-Changelog convention around them is `asserted-unverified` — `docs/DEVELOPMENT.md` "Releasing".

Snapshot at `9f6d6e2` (will drift — re-read files, do not hard-code forever):

| Field | Value at verify |
|-------|-----------------|
| Integration version | `3.5.1-beta.10` |
| Integration pin | `pylxpweb>=0.9.39b10` |
| `tests/requirements-test.txt` | `pylxpweb>=0.9.39b10  # keep in sync with manifest.json` |

**`manifest.json` is the only version authority** — it is what HA and HACS actually read —
`verified-against-code` — `custom_components/eg4_web_monitor/manifest.json:14` (`3.5.1-beta.10` at
`9f6d6e2`). A version copied into prose is a snapshot that stops being true at the next release
unless someone remembers to update it, and that has already gone wrong here by nine betas. Read the
manifest; do not trust a version you find written in a document, including this one.

## Integration pin locations (must stay equal)

1. `custom_components/eg4_web_monitor/manifest.json` → `"requirements": ["pylxpweb>=…", …]` — `verified-against-code` — `manifest.json:13`
2. `tests/requirements-test.txt` → `pylxpweb>=…  # keep in sync with manifest.json` — `verified-against-code` — `tests/requirements-test.txt:17`
3. CI reads the pin from `tests/requirements-test.txt` dynamically so typecheck resolves the same pylxpweb the tests do — `verified-against-code` — `.github/workflows/quality-validation.yml`, job `platinum-strict-typing`, step **Install mypy and dependencies with uv** (`PYLXPWEB_PIN=$(grep -oE '^pylxpweb[><=!~]+[0-9a-zA-Z.]+' tests/requirements-test.txt)`).

The dynamic read exists because a hardcoded `>=`-stable specifier resolved the latest **stable** and
hid prerelease-only APIs from mypy (`0.9.37` → `0.9.38b1`: `run_firmware_update_to_completion` was
invisible) — `verified-against-code` — same step's inline comment.

CHANGELOG convention: each beta/stable header states **Requires pylxpweb>=…** with a GitHub release link — first-class release note, not optional commentary.

## Integration release steps

Steps 1–4 are the documented procedure — `asserted-unverified` — `docs/DEVELOPMENT.md` "Releasing".
Steps 5–6 (what publishing actually triggers) are `verified-against-code` — `.github/workflows/release.yml`.

1. Bump `version` in `manifest.json`.
2. Move `Unreleased` CHANGELOG entries under the new version heading (Keep a Changelog).
3. Ensure pylxpweb pin already published (ordering constraint above).
4. Tag `vX.Y.Z` (or `vX.Y.Z-beta.N` / `vX.Y.Z-rc.N`).
5. Publish GitHub Release → `release.yml` builds a zip of `custom_components/eg4_web_monitor` and attaches `eg4_web_monitor.zip`.
6. HACS consumes the tagged release.

Zip exclusions (secrets must never ship) — `verified-against-code` — `.github/workflows/release.yml`, step **Create release asset** (`zip -x` list):

- `*.env`, `.env`, `secrets.py`
- `*.pyc`, `*.pyo`, `__pycache__/*`, `.mypy_cache/*`, `.ruff_cache/*`, `.git/*`

The integration's `release.yml` has **no** `workflow_dispatch` — `release: published` is its only
trigger, so there is no manual path that attaches a zip — `verified-against-code` — `.github/workflows/release.yml`, `on:`.

## How HACS consumes releases

`verified-against-code` — `hacs.json`

| Key | Value |
|-----|-------|
| `zip_release` | `true` |
| `filename` | `eg4_web_monitor.zip` |
| `homeassistant` | `>=2026.1.0` (minimum HA version) |
| `content_in_root` | `false` |

HACS installs from the GitHub Release asset produced by `release.yml`, not from raw tree contents.

## pylxpweb release / PyPI publish

Steps 1–3 are the documented procedure — `asserted-unverified` — pylxpweb `docs/DEVELOPMENT.md`.
Step 4 and everything below it are `verified-against-code` — pylxpweb@`204b95d` `.github/workflows/release.yml:1-121`.

1. Bump version in `pyproject.toml`.
2. Update pylxpweb `CHANGELOG.md`.
3. Tag and publish a GitHub Release (e.g. `gh release create v0.9.39b10 …`).
4. Workflow **Publish to PyPI** on `release: published`:
   - Build with `uv build`, then `uv run twine check dist/*`
   - Publish to **TestPyPI** (OIDC environment `testpypi`)
   - Then publish to **PyPI** (OIDC environment `pypi`)

### Manual dispatch: inputs, triggers, and the TestPyPI gate

`workflow_dispatch` takes exactly **one** input — `environment`, required, `type: choice` — with
three options: `skip-publish`, `testpypi`, `pypi`. There is no `skip-publish` *flag*; it is one of the
three values of that single input — `verified-against-code` — pylxpweb@`204b95d` `release.yml:9-18`.

**Dispatch cannot bypass the TestPyPI → PyPI gate.** The gate is structural, not conditional:
`publish-pypi` declares `needs: [build, publish-testpypi]`, and no job uses `if: always()`, so a
skipped `publish-testpypi` skips `publish-pypi` too. Every input value is covered —
`verified-against-code` — pylxpweb@`204b95d` `release.yml:75-76` / `:97-98` (`needs:` and `if:` on both publish jobs):

| `environment` input | `publish-testpypi` | `publish-pypi` | Net effect |
|---|---|---|---|
| `skip-publish` | skipped (`if` excludes it) | skipped (`if` requires `pypi`; dependency also skipped) | build + `twine check` only |
| `testpypi` | runs | skipped (`if` requires `pypi`) | TestPyPI only |
| `pypi` | **runs** (`if` is `!= 'skip-publish'`) | runs after it succeeds | TestPyPI **then** PyPI |
| (release published) | runs | runs after it succeeds | TestPyPI then PyPI |

There is no input combination that reaches PyPI without publishing to TestPyPI first.

### Sequencing is not provenance

**TestPyPI-first is an ordering property, not a trust boundary.** It proves the same artifact reached
TestPyPI before PyPI. It proves nothing about *which source* that artifact was built from.

The build job resolves its checkout as
`ref: ${{ github.event.release.tag_name || github.ref }}`. On `workflow_dispatch` there is no release
payload, so it falls through to `github.ref` — **the ref the dispatcher chose**. Any branch, any tag,
reviewed or not. The version published is whatever `pyproject.toml` declares on that ref; nothing
compares it to a tag, a release, or a merged commit — `verified-against-code` — pylxpweb@`204b95d`
`release.yml:35-37`.

Three properties that look protective and are not:

| Looks like a control | What it actually constrains |
|---|---|
| TestPyPI runs first | Order only. Both jobs consume the same artifact, so they agree with each other — including when that artifact was built from an unreviewed ref |
| OIDC / Trusted Publisher | Binds publication to *this repo, this workflow file, this environment*. It attests **who published**, never **what was reviewed**. A dispatch from an arbitrary branch is signed just as legitimately |
| Environment gating on the publish jobs | **`build` declares no `environment:` at all.** Only the two publish jobs do, so environment protection rules never gate the checkout or the build — an unreviewed ref is fetched and built regardless, and the rules can only stop it at upload — `verified-against-code` — pylxpweb@`204b95d`: `build` spans `release.yml:30-69` with no `environment:` key, against `:77` (`environment: testpypi`) and `:99` (`environment: pypi`) |

Absent environment restrictions, this means: **any repository writer can have OIDC publish an
arbitrary ref to PyPI as the real package.** Downstream, `manifest.json` resolves `pylxpweb>=…` from
PyPI, so that artifact lands in Home Assistant installs.

### Preconditions for a production `pypi` dispatch

**Do not dispatch `environment: pypi` unless all three hold.** These are preconditions to *verify*,
not assumptions — the first two live in repository settings and are **not determinable from this
tree**, so confirm them on GitHub each time rather than inheriting a belief about them:

| # | Precondition | How to confirm | Status here |
|---|---|---|---|
| 1 | The `pypi` environment restricts **which refs may deploy** to protected release tags — GitHub evaluates its deployment branch/tag policy against the run's `github.ref`, and it is the only automatic control that constrains *which ref* may publish | Repo → Settings → Environments → `pypi` → deployment branches and tags | **Unverified — settings not in the tree** |
| 2 | The `pypi` environment requires **review by someone other than the dispatcher** | Same screen → required reviewers | **Unverified — settings not in the tree** |
| 3 | An **immutable, protected release tag** exists, and the version in `pyproject.toml` at that tag equals the version being published | `git rev-parse 'v0.9.39b10^{commit}'` against the reviewed merge commit; a tag protection rule or ruleset to stop the tag being moved afterwards | **Unverified — tag protection is a repo setting.** And see below: the release tags carry no immutability of their own |

If any is unconfirmed, **publish through a published GitHub Release instead of a manual dispatch**,
and treat the manual `pypi` path as unavailable. The release path at least binds the checkout to
`github.event.release.tag_name`; note that this still assumes the tag is protected, since an
unprotected git tag can be moved after review (precondition 3 covers both paths).

**The release tags are lightweight, so they carry no evidence of their own.** Checked at the pin:
`git cat-file -t refs/tags/v0.9.39b10` returns `commit`, not `tag` — the ref points straight at the
commit with no tag object behind it. The same holds for `v0.9.39b9`. A lightweight tag has **no
tagger identity, no timestamp and no signature**, and it is an ordinary ref that anyone with push
access can move with `git push --force origin v0.9.39b10`. So a tag matching the artifact proves only
where the ref points *right now*; it is not evidence of who cut the release or that it has not been
repointed since. Precondition 3's immutability therefore rests **entirely** on GitHub tag protection
rules — there is no fallback in the git data — `verified-against-code` — pylxpweb@`204b95d`:
`git cat-file -t` on both release tag refs.

Worked example at the pin, which resolves gate checks 1 and 2 concretely:

| Step | Result |
|---|---|
| `git rev-parse 'v0.9.39b10^{commit}'` | `204b95d…` |
| `git ls-remote --tags origin refs/tags/v0.9.39b10` | `204b95d…` — local and origin agree, so the ref has not been repointed on one side only |
| `git show 204b95d:pyproject.toml` → `[project].version` | `0.9.39b10` — matches the tag name and the floor `manifest.json:13` pins |

That is a clean tag → commit → version chain, and it is what checks 1 and 2 look like when they pass.
It still says nothing about *who* published or whether the tag moved before you looked, which is the
gap the paragraph above describes.

**Who can trigger it.** The workflow declares no actor restriction — `verified-against-code` for the
absence of one (pylxpweb@`204b95d` `release.yml`: the only job-level `if:` conditions are `:76` and
`:98`, both on the publish-target input, and no job tests `github.actor`). It therefore reduces
to GitHub's rule that `workflow_dispatch` requires write access — `asserted-unverified` (GitHub
Actions documented behavior, not a fact in this tree). Repository write access is a much larger set
than release authority, which is what makes preconditions 1 and 2 load-bearing rather than optional.

`concurrency: release-publish` with `cancel-in-progress: false` serializes releases — a second
dispatch queues rather than cancelling the first — `verified-against-code` — pylxpweb@`204b95d` `release.yml:21-23`.

## SemVer / prerelease ordering reminder

Observed line: `…-beta.N` < `…-rc.N` < final `X.Y.Z` (e.g. beta.27 < rc.1 < 3.4.0) — `inferred` from
the `CHANGELOG.md` 3.4.0 release sequence; treat as project convention when cutting candidates.
