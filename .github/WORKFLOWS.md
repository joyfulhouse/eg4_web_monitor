# GitHub Actions Workflows

This repository uses streamlined GitHub Actions workflows for quality validation and issue automation. AI code review runs off-CI — see [Polly Review (external)](#polly-review-external).

## Active Workflows

### 1. Quality Validation (`quality-validation.yml`)

**Purpose:** Comprehensive quality tier validation with proper dependency chain

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches
- Manual workflow dispatch

**Validation Flow:**
```
Bronze Tier (10 jobs)
    ↓
Silver Tier (9 jobs)
    ↓
Gold Tier (5 jobs)
```

**Bronze Tier Requirements (18 total):**
- Python syntax validation
- Config flow test coverage
- Manifest validation
- Service documentation
- Runtime data pattern
- Action setup pattern
- Entity naming pattern
- Unique ID implementation
- Code quality (Ruff)
- Security scan (Bandit)

**Silver Tier Requirements (10 total):**
- Service exception handling
- Config entry unload support
- Documentation completeness
- Entity availability implementation
- Integration owner (codeowners)
- Unavailability logging
- Parallel update count specification
- Reauthentication flow
- Test coverage infrastructure

**Gold Tier Requirements (5 total):**
- Translation support (strings.json + translations/)
- Reconfiguration flow with tests
- User documentation quality
- Comprehensive test coverage with pytest
- Manifest completeness

## Polly Review (external)

AI code review is no longer part of CI. Instead, an off-CI "polly review" runs on
the repository owner's local infrastructure:

1. A `pull_request_review` webhook fires when a PR is approved.
2. A trust gate checks the approver against the maintainer allowlist in
   [`.github/MAINTAINER`](MAINTAINER) — only maintainer approvals proceed.
3. The owner's local infrastructure runs an Omnigent polly review of the PR.
4. The result is posted as an advisory PR comment marked
   `<!-- polly-review-bot sha=<head_sha> -->`.

The polly review is advisory only: it is not a required check and never blocks
merge. To retrigger a review (e.g. after pushing new commits), re-approve the PR.

## Workflow Design Principles

1. **Sequential Dependencies:** Each tier must pass before the next begins
2. **Fail Fast:** Bronze failures prevent Silver/Gold execution, saving CI time
3. **Clear Progression:** Easy to see where validation failed in the pipeline
4. **Maintainability:** Single workflow file instead of multiple scattered files
5. **Efficiency:** Job-level parallelism within each tier, tier-level sequencing

## Migration from Old Workflows

**Removed workflows:**
- `bronze-tier-validation.yml` → Consolidated into `quality-validation.yml`
- `silver-tier-validation.yml` → Consolidated into `quality-validation.yml`
- `gold-tier-validation.yml` → Consolidated into `quality-validation.yml`
- `claude-issue-assistant.yml` → Removed (was superseded by `claude.yml`, itself since removed)
- `claude-code-review.yml.disabled` → Removed; in-CI AI review replaced by the external polly review
- `code-review.yml` → Removed (automatic on-open Claude review, deleted in 72a854f)
- `claude.yml` → Removed (the `@claude` mention responder; maintainer decision to drop it)

**Benefits of consolidation:**
- 535 fewer lines of YAML (1,272 → 737 lines)
- Single source of truth for quality validation
- Clear dependency chain prevents partial validation
- Better CI/CD resource utilization

## Running Workflows Locally

### Quality Validation

You can run individual validation scripts locally:

```bash
# Bronze tier checks run as dedicated jobs in quality-validation.yml;
# there is no standalone Bronze validator.

# Silver tier
python tests/validate_silver_tier.py

# Gold tier
python tests/validate_gold_tier.py

# Platinum tier (includes an actual strict-mypy run)
python tests/validate_platinum_tier.py

# All tests with coverage
pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing
```

### Code Quality Checks

```bash
# Ruff linting
ruff check .

# Ruff formatting
ruff format --check .

# Security scan
bandit -r . -ll -i -x ./test_env,./venv,./tests
```

## Workflow Status Badges

Add to README.md:

```markdown
[![Quality Validation](https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/quality-validation.yml/badge.svg)](https://github.com/joyfulhouse/eg4_web_monitor/actions/workflows/quality-validation.yml)
```

## Troubleshooting

### Bronze Tier Failures
- Check Python syntax with `python -m compileall`
- Ensure all required fields in `manifest.json`
- Verify service documentation in README.md

### Silver Tier Failures
- Ensure `ServiceValidationError` is used in services
- Verify `async_unload_entry` exists in `__init__.py`
- Check `MAX_PARALLEL_UPDATES` in all platform files

### Gold Tier Failures
- Validate `strings.json` structure
- Ensure reconfiguration flow implemented
- Check test coverage with pytest
- Verify all README.md sections present

### Polly Review Not Posting
- The polly review runs off-CI on the owner's local infrastructure; nothing
  appears in the Actions tab
- It only triggers on an approving review from a login in `.github/MAINTAINER`
- Re-approve the PR to retrigger; the comment is advisory and never blocks merge

## Future Enhancements

Potential workflow improvements:
- [x] Add Platinum tier validation (implemented in `tests/validate_platinum_tier.py`)
- [ ] Integration with Home Assistant's official validation tools
- [ ] Automated HACS validation
- [ ] Performance benchmarking
- [ ] Dependency security scanning with Dependabot
