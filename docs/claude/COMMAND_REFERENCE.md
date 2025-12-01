# Claude Code Command Reference

Quick reference guide for all custom Claude Code slash commands.

**Last Updated**: 2025-11-18
**Phase**: 1 & 2 Complete

---

## Quality & Testing Commands

### `/quality-check`
**Run complete pre-commit quality validation**

```
/quality-check
```

**What it does**:
- Runs ruff linting with auto-fix
- Runs mypy type checking
- Runs pytest with coverage
- Runs project-specific validators (HA tiers)
- Auto-fixes failures (max 3 iterations)
- Generates comprehensive report

**When to use**: Before any commit, before creating PR

**Time saved**: ~58 min/week

---

### `/ha-quality`
**Home Assistant quality scale validation**

```
/ha-quality
```

**What it does**:
- Validates all tiers (Bronze, Silver, Gold, Platinum)
- Checks manifest compliance
- Validates translations completeness
- Verifies entity naming conventions
- Checks HACS compliance
- Reports current tier status

**When to use**: HA projects only, before releases

**Time saved**: ~25 min/week

---

### `/chrome-test`
**Autonomous browser testing with Chrome DevTools**

```
/chrome-test
```

**What it does**:
- Auto-starts dev server
- Tests all routes
- Checks console errors
- Tests all locales (multilingual)
- Captures screenshots of failures
- Auto-fixes errors (max 3 iterations)
- Stops server cleanly

**When to use**: After UI changes, before deployment

**Time saved**: ~77 min/week

---

## Git Workflow Commands

### `/git:cm`
**Stage and commit with conventional commit messages**

```
/git:cm
```

**What it does**:
- Reviews all modified files
- Generates conventional commit message
- Checks for sensitive files
- Splits commits if needed
- Creates local commit (NO push)
- Displays commit hash and stats

**When to use**: Individual commits during development

**Time saved**: ~1 min/commit (20 min/week)

**Note**: NO AI attribution signatures

---

### `/git:cp`
**Commit and push** (existing command)

```
/git:cp
```

**What it does**:
- Same as `/git:cm` but also pushes to remote

**When to use**: When ready to push immediately

---

### `/git:pr`
**Create pull request** (existing command)

```
/git:pr [to-branch] [from-branch]
/git:pr main feature/my-branch
```

**What it does**:
- Creates PR using gh CLI
- Defaults: to=main, from=current

**When to use**: After pushing feature branch

---

### `/git:feature`
**Complete feature branch workflow**

```
/git:feature "Add quick charge support"
/git:feature "Fix battery voltage" --base develop
```

**What it does**:
1. Creates feature branch (auto-generates name)
2. Implements feature with progress tracking
3. Runs `/quality-check`
4. Creates conventional commit
5. Pushes to remote
6. Creates PR with auto-generated description
7. Links related issues
8. Reports PR URL

**When to use**: Starting new feature development

**Time saved**: ~45 min/week

---

### `/git:cleanup`
**Repository maintenance and cleanup**

```
/git:cleanup
/git:cleanup --dry-run
/git:cleanup --aggressive
```

**What it does**:
- Fetches and prunes remotes
- Lists merged branches
- Deletes local merged branches
- Prunes remote-tracking branches
- Asks confirmation for remote deletion
- Runs garbage collection
- Verifies repository health
- Generates cleanup report

**When to use**: Weekly/monthly, after sprints

**Time saved**: ~15 min/week

---

## Subagent Skills (Phase 3)

### `/skill:qa-agent`
**Launch Quality Assurance subagent for autonomous testing**

```
/skill:qa-agent
```

**What it does**:
- Runs complete quality validation suite
- Auto-fixes errors (max 3 iterations)
- Context isolation (~20-30k tokens saved)
- Returns concise summary report

**When to use**: Before commits, after refactoring, when CI fails

**Time saved**: ~60 min/week

---

### `/skill:chrome-agent`
**Launch Chrome Testing subagent for browser testing**

```
/skill:chrome-agent
```

**What it does**:
- Starts dev server automatically
- Tests all routes and locales
- Checks for console/network errors
- Auto-fixes UI issues (max 3 iterations)
- Context isolation (~40-50k tokens saved)
- Returns test summary with screenshots (if errors)

**When to use**: After UI changes, before deployments

**Time saved**: ~77 min/week

---

### `/skill:docs-agent`
**Launch Documentation Research subagent**

```
/skill:docs-agent
/skill:docs-agent research Next.js App Router
```

**What it does**:
- Researches library documentation
- Uses context7, mui-mcp, WebFetch intelligently
- Synthesizes findings from multiple sources
- Context isolation (~30-50k tokens saved)
- Returns concise, actionable summary

**When to use**: Learning new libraries, researching APIs, fixing deprecation warnings

**Time saved**: ~20 min/week

---

## Complete Workflow Commands

### `/test-fix-deploy`
**Complete development cycle: test → commit → merge → deploy**

```
/test-fix-deploy
/test-fix-deploy --skip-deploy
/test-fix-deploy --release v2.3.0
```

**What it does**:
1. Runs `/quality-check` with auto-fix
2. Creates commit with `/git:cm`
3. Merges to main
4. Deletes feature branch
5. Creates release tag (if --release)
6. Pushes to remote
7. Monitors CI/CD pipeline
8. Deploys to production (unless --skip-deploy)
9. Validates deployment
10. Generates comprehensive report

**When to use**: Ready to deploy to production

**Time saved**: ~140 min/week

**Safety**: Asks confirmation for production deployment

---

## Command Combinations

### New Feature Development
```
/git:feature "Add battery monitoring"
# Implement feature
/quality-check
# Fix any issues
/git:cm
# Create PR automatically
```

### Quick Bug Fix
```
# Make changes
/quality-check
/git:cm
/git:cp
```

### Deploy to Production
```
/test-fix-deploy --release v2.3.0
```

### Weekly Maintenance
```
/git:cleanup
```

---

## Command Flags & Arguments

### `/test-fix-deploy`
- `--skip-deploy` - Skip deployment step
- `--release VERSION` - Create release tag (e.g., v2.3.0)

### `/git:feature`
- First argument: Feature description (required)
- `--base BRANCH` - Base branch (default: main)

### `/git:cleanup`
- `--dry-run` - Preview without executing
- `--aggressive` - More thorough cleanup
- `--base BRANCH` - Custom base branch

### `/git:pr`
- First argument: Target branch (default: main)
- Second argument: Source branch (default: current)

---

## Command Behavior

### Autonomous Execution
All commands continue automatically without "continue?" prompts:
- Testing, linting, building steps
- Error recovery attempts (max 3 iterations)
- Progress tracked with TodoWrite

### Confirmation Required Only For
- Manual decisions (architecture, library choices)
- Destructive operations (delete files, force push)
- Production deployments
- Deleting remote branches
- Large commits (>50 files)
- Breaking changes detected

### Error Recovery
All commands attempt automatic fixes:
- Linting errors → `ruff check --fix`
- Test failures → analyze and fix
- Max 3 iterations per issue
- Report if unable to fix

### Security Features
All commands check for sensitive files:
- .env files
- API keys, tokens, credentials
- Database credentials
- Private keys
- Automatically exclude from commits

---

## Workflow Patterns

### Daily Development
```
# Morning: Start new feature
/git:feature "implement user auth"

# During day: Regular commits
/git:cm

# End of day: Quality check
/quality-check
```

### Before PR
```
/quality-check
/git:cm
/git:cp
```

### Release Process
```
/test-fix-deploy --release v2.4.0
/git:cleanup
```

### Weekly Sprint
```
# Monday-Thursday: Features
/git:feature "feature 1"
/git:feature "feature 2"

# Friday: Deploy and cleanup
/test-fix-deploy
/git:cleanup
```

---

## Time Savings Summary

### Phase 1: Quality & Testing
| Command | Frequency | Time Saved | Weekly Total |
|---------|-----------|------------|--------------|
| `/quality-check` | 10x | 5.8 min | 58 min |
| `/ha-quality` | 2x | 12.5 min | 25 min |
| `/chrome-test` | 5x | 15.4 min | 77 min |
| **Phase 1 Total** | | | **160 min (2.7 hrs/week)** |

### Phase 2: Git & Deployment
| Command | Frequency | Time Saved | Weekly Total |
|---------|-----------|------------|--------------|
| `/git:cm` (enhanced) | 20x | 1 min | 20 min |
| `/git:feature` | 5x | 9 min | 45 min |
| `/test-fix-deploy` | 8x | 17.5 min | 140 min |
| `/git:cleanup` | 1x | 15 min | 15 min |
| **Phase 2 Total** | | | **220 min (3.7 hrs/week)** |

### Phase 3: Subagents
| Subagent | Frequency | Time Saved | Weekly Total |
|----------|-----------|------------|--------------|
| `/skill:qa-agent` | 8x | 7.5 min | 60 min |
| `/skill:chrome-agent` | 5x | 15.4 min | 77 min |
| `/skill:docs-agent` | 4x | 5 min | 20 min |
| **Phase 3 Total** | | | **157 min (2.6 hrs/week)** |

### Cumulative Impact
| Phase | Weekly Savings |
|-------|----------------|
| Phase 1 | 2.7 hours |
| Phase 2 | 3.7 hours |
| Phase 3 | 2.6 hours |
| **Total** | **9.0 hours/week** |

**Annual Savings**: 468 hours (~11.7 work weeks)
**ROI Break-even**: <1 week

---

## Integration Map

```
Feature Development Flow:
/git:feature "description"
  ↓
  Implement
  ↓
  /quality-check (auto)
  ↓
  /git:cm (auto)
  ↓
  Create PR (auto)

Deployment Flow:
/test-fix-deploy
  ↓
  /quality-check (auto)
  ↓
  /git:cm (auto)
  ↓
  Merge & Push (auto)
  ↓
  Deploy (auto)
  ↓
  Validate (auto)

Maintenance Flow:
/git:cleanup
  ↓
  Clean branches
  ↓
  Prune references
  ↓
  Optimize repo
```

---

## Troubleshooting

### Command Not Found
- Check file exists: `ls ~/.claude/commands/`
- Restart Claude Code session
- Verify file permissions

### GitHub CLI Required
- Install: `brew install gh`
- Authenticate: `gh auth login`
- Required for `/git:feature` PR creation

### Quality Checks Failing
- Review error messages
- Run manually first to debug
- Check test environment setup

### Deployment Issues
- Verify deployment configuration
- Check credentials and permissions
- Review CI/CD pipeline logs

---

## Best Practices

### DO
- Run `/quality-check` before every commit
- Use `/git:feature` for new features
- Regular `/git:cleanup` maintenance
- Let commands auto-fix issues
- Trust autonomous execution

### DON'T
- Skip quality checks
- Commit sensitive files (commands prevent this)
- Force push to protected branches
- Ignore auto-fix suggestions
- Manually do what commands automate

---

## Quick Reference Card

```
QUALITY & TESTING
/quality-check    → Pre-commit validation
/ha-quality       → HA tier validation
/chrome-test      → Browser testing

GIT BASICS
/git:cm           → Commit (conventional)
/git:cp           → Commit and push
/git:pr           → Create PR

GIT WORKFLOWS
/git:feature      → Complete feature flow
/git:cleanup      → Repo maintenance

DEPLOYMENT
/test-fix-deploy  → Test → Commit → Deploy

FLAGS
--skip-deploy     → Skip deployment
--release v2.x.x  → Create release tag
--dry-run         → Preview only
--base BRANCH     → Custom base branch
```

---

## Documentation Links

- [Phase 1 Implementation](./PHASE1_IMPLEMENTATION.md) - Quality & testing commands
- [Phase 2 Implementation](./PHASE2_IMPLEMENTATION.md) - Git & deployment commands
- [Full Analysis](./CLAUDE_CODE_SUGGESTIONS.md) - Complete optimization recommendations

---

**Version**: 3.0 (All Phases Complete)
**Last Updated**: 2025-11-18
**Status**: Production Ready
**Total Commands**: 10 slash commands + 3 subagent skills
