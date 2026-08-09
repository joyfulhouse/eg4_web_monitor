---
canonical-for: lint, format, typecheck, tests, coverage, quality-scale tier validators, CI blocking vs advisory
sources:
  - /tmp/llmwiki-research/repo-operations.md
  - docs/DEVELOPMENT.md
  - CLAUDE.md
  - tests/requirements-test.txt
  - prek.toml
  - .github/workflows/quality-validation.yml
  - .github/workflows/home-assistant-validation.yml
verified-against: 9f6d6e2
last-verified: 2026-08-08
---

# Quality gates

Canonical local and CI gates for eg4_web_monitor. Prefer `uv run` for agents.

## Local command set

**verified-against-code** — `CLAUDE.md` Pre-Commit Validation; `docs/DEVELOPMENT.md:21-52`; `prek.toml`

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

**Divergence:** `docs/DEVELOPMENT.md` shows bare `ruff`/`mypy`/`pytest` after `source .venv/bin/activate`; `CLAUDE.md` and `prek.toml` use `uv run`. Both work if the venv is provisioned; agents should prefer `uv run` — **verified-against-code**.

### Pre-commit / prek hooks

**verified-against-code** — `prek.toml:1-23`

| Hook | Behavior |
|------|----------|
| check-yaml, end-of-file-fixer, trailing-whitespace, check-added-large-files | Standard hygiene |
| ruff `--fix` + ruff-format | Rev `v0.15.5` |
| mypy | `uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/` |

## Pins that must stay in lockstep

**verified-against-code** — `tests/requirements-test.txt:19-21`

| Tool | Pin | Failure mode if floated |
|------|-----|-------------------------|
| `ruff` | **0.15.5** | Unpinned CI floated to 0.16 and failed repo-wide (#482) |
| `mypy` | **2.3.0** | Keep in sync with `quality-validation.yml` |

Sync surfaces: `tests/requirements-test.txt`, `prek.toml`, `.github/workflows/quality-validation.yml`.

**Strict typing gate:** Platinum CI and local mypy must exit 0 with zero errors — **verified-against-code** — `quality-validation.yml` `platinum-strict-typing` job (`exit 1` on failure).

## Quality scale tiers

| Tier | How enforced | Local script |
|------|--------------|--------------|
| Bronze | Directly in `quality-validation.yml` | None (no standalone validator) — **verified-against-code** — `docs/DEVELOPMENT.md:54-55` |
| Silver | CI job + script | `tests/validate_silver_tier.py` |
| Gold | CI job + script | `tests/validate_gold_tier.py` |
| Platinum | CI job + script | `tests/validate_platinum_tier.py` |

Tier sequencing in CI: Silver `needs: bronze-summary` → Gold `needs: silver-summary` → Platinum `needs: gold-summary` (fail-fast across tiers) — **verified-against-code** — `quality-validation.yml`.

## CI workflows

**verified-against-code** — workflow `on:` blocks

| Workflow | File | Triggers | Role |
|----------|------|----------|------|
| Quality Tier Validation | `.github/workflows/quality-validation.yml` | **push → `develop` only**; PR → `main`,`develop`; `workflow_dispatch` | Bronze→Silver→Gold→Platinum |
| Home Assistant Validation | `.github/workflows/home-assistant-validation.yml` | push → `develop`; PR → `main`,`develop`; daily cron; dispatch | hassfest + HACS |
| Release | `.github/workflows/release.yml` | `release: published` | Zip + attach `eg4_web_monitor.zip` |
| Issue Log Validation | `.github/workflows/issue-log-validation.yml` | issues opened/edited; comments | Auto-close bad debug logs |
| Issue Triage | `.github/workflows/issue-triage.yml` | issues opened (+ dispatch) | Claude triage + rate limit |
| Claude Code | `.github/workflows/claude.yml` | @claude on comments/reviews (collaborators) | Interactive assist |

**Push quality gate is develop-only.** Pushing to `main` does **not** run `quality-validation.yml` — **verified-against-code** — `quality-validation.yml:3-7`. Note: `.github/WORKFLOWS.md` is stale if it claims push to `main` or `develop` — prefer the YAML.

### Python version split

**verified-against-code** — `quality-validation.yml`

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

**verified-against-code** — `quality-validation.yml` cited lines:

| Check | Behavior |
|-------|----------|
| `bronze-entity-naming` | Prints `⚠️` if `has_entity_name` missing — **does not `exit 1`** (~152–156) |
| `silver-entity-availability` | `⚠️` if no `def available` found — **no exit 1** (~358–360) |
| `platinum-comprehensive-tests` | API client / coordinator platinum tests use `\|\| echo "⚠️ … (non-blocking)"` (~864–875) |
| Codecov upload | `fail_ci_if_error: false` (~678) |

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

**Test-count drift:** `CLAUDE.md` still says “692 tests”; recent CHANGELOG/CI narratives cite 2000+. Do not treat the CLAUDE.md count as authoritative — **inferred** from dossier §9.
