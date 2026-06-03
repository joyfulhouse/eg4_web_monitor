# Development

How to set up a development environment for EG4 Web Monitor.

## Prerequisites

- Python 3.13+ and [`uv`](https://docs.astral.sh/uv/).
- The [pylxpweb](https://github.com/joyfulhouse/pylxpweb) library (the API and
  transport layer this integration is built on).

## Setup

```bash
git clone https://github.com/joyfulhouse/eg4_web_monitor.git
cd eg4_web_monitor
uv sync
```

## Quality Checks

```bash
# Lint and format
uv run ruff check custom_components/ --fix
uv run ruff format custom_components/

# Type check (strict)
uv run mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/

# Tests (with coverage)
uv run pytest tests/ -x --tb=short
uv run pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing
```

Run all of these before opening a pull request. See
[CONTRIBUTING](https://github.com/joyfulhouse/.github/blob/main/CONTRIBUTING.md)
for the contribution workflow.

## Quality Scale

This integration targets the Home Assistant **Platinum** quality tier. Tier
validation scripts live alongside the tests:

```bash
uv run python tests/validate_bronze_tier.py
uv run python tests/validate_silver_tier.py
uv run python tests/validate_gold_tier.py
uv run python tests/validate_platinum_tier.py
```

## Releasing

Releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and
the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format in
[CHANGELOG.md](../CHANGELOG.md). Bump the `version` in
`custom_components/eg4_web_monitor/manifest.json`, update the changelog (move the
relevant `Unreleased` entries under the new version), and tag the release
(`vX.Y.Z`). HACS publishes the tagged release.
