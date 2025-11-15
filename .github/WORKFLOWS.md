# GitHub Actions Workflows

This repository uses streamlined GitHub Actions workflows for quality validation and code review.

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
    ↓
Claude Code Review (1 job, PR only)
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

**Claude Code Review:**
- Runs only on pull requests
- Executes only after Gold tier passes
- Reviews code quality, Home Assistant best practices, and Gold tier compliance

### 2. Claude Code (`claude.yml`)

**Purpose:** Interactive Claude Code assistance on issues and PRs

**Triggers:**
- Issue comments containing `@claude`
- Pull request comments containing `@claude`
- New issues with `@claude` mention
- Pull request reviews containing `@claude`

**Permissions:**
- Read: contents, pull-requests, issues, actions
- Write: id-token

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
- `claude-issue-assistant.yml` → Superseded by `claude.yml`
- `claude-code-review.yml.disabled` → Enabled and integrated into `quality-validation.yml`

**Benefits of consolidation:**
- 535 fewer lines of YAML (1,272 → 737 lines)
- Single source of truth for quality validation
- Clear dependency chain prevents partial validation
- Better CI/CD resource utilization

## Running Workflows Locally

### Quality Validation

You can run individual validation scripts locally:

```bash
# Bronze tier
python tests/validate_bronze_tier.py

# Silver tier  
python tests/validate_silver_tier.py

# Gold tier
python tests/validate_gold_tier.py

# All tests with coverage
pytest tests/ --cov=. --cov-report=term-missing
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

### Claude Code Review Failures
- Review will only run on pull requests
- Requires Gold tier to pass first
- Check `CLAUDE_CODE_OAUTH_TOKEN` secret is configured

## Future Enhancements

Potential workflow improvements:
- [ ] Add Platinum tier validation when requirements are defined
- [ ] Integration with Home Assistant's official validation tools
- [ ] Automated HACS validation
- [ ] Performance benchmarking
- [ ] Dependency security scanning with Dependabot
