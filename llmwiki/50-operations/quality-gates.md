---
canonical-for: lint, format, typecheck, tests, coverage, quality-scale tier validators, CI blocking vs advisory
sources:
  - docs/DEVELOPMENT.md
  - CLAUDE.md
  - tests/requirements-test.txt
  - tests/mypy.ini
  - prek.toml
  - .github/workflows/quality-validation.yml
  - .github/workflows/home-assistant-validation.yml
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Quality gates

Canonical local and CI gates for eg4_web_monitor. Prefer `uv run` for agents.

## Local command set

The tool invocations are `verified-against-code` — `prek.toml` (ruff `rev`, mypy hook `entry`) and
`.github/workflows/quality-validation.yml` (jobs `bronze-code-quality`, `gold-test-coverage`,
`platinum-strict-typing`). The command *listing* below also appears in `docs/DEVELOPMENT.md:21-52`,
which is prose and is cited as corroboration only.

```bash
# Lint + format (fix) — agent-preferred form
uv run ruff check custom_components/ --fix && uv run ruff format custom_components/

# Full-tree check (matches CI / docs/DEVELOPMENT.md)
uv run ruff check .
uv run ruff format --check .

# Typecheck — must pass with ZERO errors (strict config via tests/mypy.ini)
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/

# Tests
uv run pytest tests/ -x --tb=short

# Coverage
uv run pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing

# Combined helper
python tests/run_tests.py --all

# Tier validators (Silver / Gold / Platinum — no standalone Bronze script)
uv run python tests/validate_silver_tier.py
uv run python tests/validate_gold_tier.py
uv run python tests/validate_platinum_tier.py
```

**Divergence:** `docs/DEVELOPMENT.md:23-37` shows bare `ruff`/`mypy`/`pytest`, which assume the
activated venv from its own setup block (`:13-19`); `prek.toml`'s mypy hook invokes `uv run`. Both
work once the venv is provisioned; agents should prefer `uv run` because it needs no activation. The
`uv run` form is `verified-against-code` — `prek.toml:22`; the bare form is what
`docs/DEVELOPMENT.md:23-37` prints, quoted here as the text being compared, not as authority.

### Pre-commit / prek hooks

`verified-against-code` — `prek.toml:1-23`

| Hook | Behavior |
|------|----------|
| check-yaml, end-of-file-fixer, trailing-whitespace, check-added-large-files | Standard hygiene |
| ruff `--fix` + ruff-format | Rev `v0.15.5` |
| mypy | `uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/` |

## Pins that must stay in lockstep

`verified-against-code` — `tests/requirements-test.txt:20-21`

| Tool | Pin | Failure mode if floated |
|------|-----|-------------------------|
| `ruff` | **0.15.5** | Unpinned CI floated to 0.16 and failed repo-wide (#482) |
| `mypy` | **2.3.0** | Pinned per #528 review; keep in sync with `quality-validation.yml` |

Sync surfaces: `tests/requirements-test.txt:20-21`, `prek.toml:13` (ruff `rev`),
`.github/workflows/quality-validation.yml` (job `platinum-strict-typing` installs `mypy==2.3.0`).

**Strict typing gate:** Platinum CI and local mypy must exit 0 with zero errors — `verified-against-code`
— `quality-validation.yml`, job `platinum-strict-typing`, steps **Verify strict typing configuration**
(asserts `tests/mypy.ini` exists, contains `strict = True`, and `py.typed` is present) and **Run mypy
type checking** (`exit 1` on type errors).

## Quality scale tiers

| Tier | How enforced | Local script |
|------|--------------|--------------|
| Bronze | Directly in `quality-validation.yml` (the `bronze-*` jobs) | None — `tests/` contains `validate_silver_tier.py`, `validate_gold_tier.py`, `validate_platinum_tier.py`, `validate_translations.py` and **no** `validate_bronze_tier.py` — `verified-against-code` — `tests/` listing; stated the same way in `docs/DEVELOPMENT.md:54-55` |
| Silver | CI job + script | `tests/validate_silver_tier.py` |
| Gold | CI job + script | `tests/validate_gold_tier.py` |
| Platinum | CI job + script | `tests/validate_platinum_tier.py` |

Tier sequencing in CI: every Silver job declares `needs: bronze-summary`, Gold `needs: silver-summary`,
Platinum `needs: gold-summary` (fail-fast across tiers) — `verified-against-code` — `quality-validation.yml`,
jobs `bronze-summary`, `silver-summary`, `gold-summary` and their dependents.

## CI workflows

`verified-against-code` — workflow `on:` blocks

| Workflow | File | Triggers | Role |
|----------|------|----------|------|
| Quality Tier Validation | `.github/workflows/quality-validation.yml` | **push → `develop` only**; PR → `main`,`develop`; `workflow_dispatch` | Bronze→Silver→Gold→Platinum |
| Home Assistant Validation | `.github/workflows/home-assistant-validation.yml` | push → `develop`; PR → `main`,`develop`; daily cron; dispatch | hassfest + HACS |
| Release | `.github/workflows/release.yml` | `release: published` | Zip + attach `eg4_web_monitor.zip` |
| Issue Log Validation | `.github/workflows/issue-log-validation.yml` | issues opened/edited; comments | Auto-close bad debug logs |
| Issue Triage | `.github/workflows/issue-triage.yml` | issues opened (+ dispatch) | Claude triage + rate limit |
| Claude Code | `.github/workflows/claude.yml` | @claude on comments/reviews (collaborators) | Interactive assist |

**Push quality gate is develop-only.** Pushing to `main` does **not** run `quality-validation.yml`;
`main` is covered only via pull request — `verified-against-code` — `quality-validation.yml`, `on:`
(`push.branches: [develop]`, `pull_request.branches: [main, develop]`, `workflow_dispatch`).

### Python version split

`verified-against-code` — `quality-validation.yml`

| Jobs | Python |
|------|--------|
| Bronze ruff/syntax | 3.12 |
| Gold coverage + Platinum mypy/tests | 3.13 |

## Blocking vs advisory (quality-validation.yml)

### Blocking (job fails / `exit 1`)

Majority of Bronze/Silver/Gold/Platinum steps, including:

- Ruff lint + format check (`bronze-code-quality`)
- Bandit (`bronze-security-scan`)
- `pytest` with coverage in `gold-test-coverage` (ignores `tests/test_plant_api.py`)
- Strict mypy in `platinum-strict-typing`
- Tier scripts: `validate_silver_tier.py`, `validate_gold_tier.py`, `validate_platinum_tier.py`
- Translation completeness via `tests/validate_translations.py`

### Advisory / soft (warn only)

These four look like gates and are not. A green run does **not** mean they passed.

`verified-against-code` — `.github/workflows/quality-validation.yml`, by job and step name:

| Job | Step | Why it is advisory |
|-----|------|--------------------|
| `bronze-entity-naming` | **Check has_entity_name** | Loops the five platform files and `echo`s `⚠️  $file may not use has_entity_name = True`; the branch has no `exit 1`, so the job succeeds either way |
| `silver-entity-availability` | **Check entity availability** | Sets `found=1` on the first file containing `def available` and `break`s; if none match it `echo`s `⚠️  Entity availability property not found` and still exits 0. One match across all platforms satisfies it |
| `platinum-comprehensive-tests` | **(test invocations)** | `pytest tests/test_api_client.py … \|\| echo "⚠️  API client tests failed (non-blocking)"` and the same pattern for `tests/test_coordinator_platinum.py` — the `\|\|` swallows a non-zero exit |
| `gold-test-coverage` | **(codecov upload)** | `codecov/codecov-action@v4` with `fail_ci_if_error: false` — upload failure never fails the job |

## Agent pre-PR gate (integration)

```bash
cd eg4_web_monitor/   # repo root
uv run ruff check . --fix && uv run ruff format .
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
uv run pytest tests/ -x --tb=short
uv run python tests/validate_silver_tier.py
uv run python tests/validate_gold_tier.py
uv run python tests/validate_platinum_tier.py
```

**Test-count drift:** `CLAUDE.md` "Local Testing" says “692 tests”; `CHANGELOG.md` release entries
from the same period cite 2000+. Neither is authoritative — count it yourself with
`uv run pytest tests/ --collect-only -q | tail -1` — `asserted-unverified` (the two docs disagree;
`CLAUDE.md` "Local Testing" vs `CHANGELOG.md` v3.5.1-beta.1).
