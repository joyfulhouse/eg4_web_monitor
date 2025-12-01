# Claude Code Optimization Recommendations
**Project**: EG4 Web Monitor Home Assistant Integration
**Analysis Date**: 2025-11-18
**Based On**: 4,378 Claude Code sessions, Anthropic best practices, current project patterns

---

## Executive Summary

Analysis of our Claude Code usage patterns reveals significant opportunities to improve efficiency through:
1. **Custom skills** for common workflows (saves 9.1 hours/week)
2. **Improved CLAUDE.md instructions** for autonomous operation
3. **MCP server optimization** following Anthropic's latest guidance
4. **Subagent workflows** for complex operations

**Key Finding**: We spend ~12 hours/week on repetitive tasks that could be reduced to ~3 hours (75% time savings) through automation.

---

## Table of Contents

1. [Context Optimization: MCP Server Usage](#context-optimization-mcp-server-usage)
2. [Workflow Pattern Analysis](#workflow-pattern-analysis)
3. [Recommended Custom Skills](#recommended-custom-skills)
4. [CLAUDE.md Improvements](#claudemd-improvements)
5. [Subagent Design Recommendations](#subagent-design-recommendations)
6. [Implementation Roadmap](#implementation-roadmap)
7. [Expected Impact](#expected-impact)

---

## Context Optimization: MCP Server Usage

### Current Context Usage Problem

From Anthropic's latest research ([Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)):

> "As the number of connected tools grows, loading all tool definitions upfront and passing intermediate results through the context window slows down agents and increases costs."

**Our Current MCP Servers:**
- `browser` (Chrome DevTools) - **HIGH context usage**
- `context7` (Library docs) - **MEDIUM context usage**
- `mui-mcp` (MUI docs) - **MEDIUM context usage**

One developer reported their MCP tools consuming **66,000+ tokens** of context before starting a conversation—representing **33% of Claude Sonnet 4.5's 200k token window** just for loading tools.

### Anthropic's Solution: Code Execution with MCP

Instead of direct tool calls, present MCP servers as code APIs. This approach:
- **Reduces tokens by 98.7%** (150k → 2k tokens in Anthropic's case)
- Agents load only needed tools on-demand
- Data processing happens in execution environment
- Tool catalogs stay out of model context

### Recommendations for Our Project

#### 1. Selective MCP Loading
**Current**: All 3 MCP servers load automatically
**Proposed**: Context-aware selective loading

```markdown
## MCP Server Loading Strategy (Add to CLAUDE.md)

Load MCP servers based on task context:

**Always Load:**
- (none) - Load servers on-demand only

**Web Testing Tasks:**
- browser (Chrome DevTools)

**Documentation Research:**
- context7 (when user explicitly asks for library docs)
- mui-mcp (only for MUI component questions)

**Never Load Both:**
- Don't load context7 AND mui-mcp simultaneously
- Use context7 for general library docs
- Use mui-mcp ONLY for MUI-specific questions
```

#### 2. Use Subagents for Heavy MCP Operations

From Anthropic's [Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices):

> "Telling Claude to use subagents to verify details or investigate particular questions it might have, especially early on in a conversation or task, tends to preserve context availability without much downside."

**Apply to our workflows:**
- Use Task tool with `subagent_type=Explore` for codebase research
- Use subagents for Chrome DevTools testing (isolates browser context)
- Use subagents for library documentation research (isolates doc context)

#### 3. Clear Context Frequently

```markdown
## Context Management (Add to CLAUDE.md)

Use /clear command between distinct tasks:
- After completing a feature implementation
- Before starting testing phase
- After deployment workflow
- Between unrelated debugging sessions

This preserves context window for current task.
```

#### 4. Filesystem-Based Tool Discovery

Consider converting heavy MCP usage to code-based patterns:
- Chrome DevTools testing → Playwright/Puppeteer scripts (call on-demand)
- Library documentation → Fetch llms.txt files directly via WebFetch
- MUI docs → Use WebFetch to mui.com docs when needed

**Token Savings**: Converting MUI MCP server to WebFetch on-demand could save ~15-20k tokens per session.

---

## Workflow Pattern Analysis

### Top 10 Task Categories (from 4,378 sessions)

| Rank | Category | Count | % | Automation Potential |
|------|----------|-------|---|---------------------|
| 1 | Git Operations | 825 | 18.8% | **HIGH** |
| 2 | Implementation | 536 | 12.2% | Medium |
| 3 | Debugging & Fixes | 409 | 9.3% | **HIGH** |
| 4 | Testing & Validation | 331 | 7.6% | **VERY HIGH** |
| 5 | Continuation Prompts | 292 | 6.7% | **VERY HIGH** |
| 6 | Deployment | 173 | 4.0% | **VERY HIGH** |
| 7 | Code Quality Checks | 159 | 3.6% | **VERY HIGH** |
| 8 | Research & Analysis | 77 | 1.8% | Medium |
| 9 | Configuration | 51 | 1.2% | Medium |
| 10 | Internationalization | 23 | 0.5% | Low |

### Key Pain Points

1. **Continuation Prompts (357 instances)** - 9.8% of interactions are "continue", "yes", "proceed"
   - **Root Cause**: Claude seeking unnecessary permission
   - **Solution**: Default to autonomous continuation for mechanical tasks

2. **Test-Fix-Continue Cycles (37 sequences)** - Average 3-5 iterations
   - **Root Cause**: Manual intervention between each step
   - **Solution**: Autonomous test-fix loop with max iterations

3. **Repetitive Pre-Commit Validation** - Executed manually 10+ times
   - **Root Cause**: No single command for full validation
   - **Solution**: `/quality-check` skill

4. **Chrome DevTools Testing** - Repeated 3-5 times per feature
   - **Root Cause**: Manual test → fix → re-test cycles
   - **Solution**: `/chrome-test` skill with auto-fix

---

## Recommended Custom Skills

### Priority 1: Quick Wins (Week 1)

#### 1. `/quality-check` Skill ⭐⭐⭐⭐⭐
**Saves**: 58 min/week | **Effort**: Low | **File**: `.claude/commands/quality-check.md`

```markdown
Run complete pre-commit quality validation:

1. **Lint and Format**
   ```bash
   ruff check custom_components/ --fix
   ruff format custom_components/
   ```

2. **Type Check**
   ```bash
   mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/
   ```

3. **Run Tests**
   ```bash
   pytest tests/ -x --tb=short
   ```

4. **Check Coverage**
   ```bash
   pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing
   ```

5. **Validate Tiers**
   ```bash
   python3 tests/validate_platinum_tier.py
   python3 tests/validate_gold_tier.py
   python3 tests/validate_silver_tier.py
   ```

6. **Generate Report**
   - ✅ Pass/Fail status for each check
   - 📊 Coverage percentage
   - ⚠️ Warnings summary
   - 🔧 Auto-fixable issues identified

**Auto-Fix Mode**: Automatically fix linting errors and re-run checks (max 3 iterations).

**Usage**:
```
User: /quality-check
User: /quality-check --fix
```
```

#### 2. `/chrome-test` Skill ⭐⭐⭐⭐
**Saves**: 77 min/week | **Effort**: Medium | **File**: `.claude/commands/chrome-test.md`

```markdown
Validate web application with Chrome DevTools:

**Prerequisites**: Detect dev server configuration (npm/yarn/docker)

**Workflow**:
1. Start dev server automatically
2. Wait for server ready (check localhost:3000)
3. Use browser MCP to test:
   - Navigate to all routes
   - Check console for errors
   - Verify no 404s
   - Test user interactions
   - Validate forms
4. Test all locales (if multilingual project)
5. Capture screenshots of failures
6. Generate test report
7. Stop dev server

**Auto-Fix Mode**: Attempt to fix errors found (max 3 iterations):
- Fix console errors
- Fix routing issues
- Fix missing translations
- Re-test after fixes

**Usage**:
```
User: /chrome-test
User: /chrome-test --pages /,/about,/contact
User: /chrome-test --fix
```

**Note**: Uses subagent to isolate browser MCP context.
```

#### 3. `/ha-quality` Skill ⭐⭐⭐⭐
**Saves**: 25 min/week | **Effort**: Low | **File**: `.claude/commands/ha-quality.md`

```markdown
Home Assistant integration quality scale validation:

**Validation Levels**:
- Platinum (3 requirements)
- Gold (5 requirements)
- Silver (10 requirements)
- Bronze (18 requirements)

**Checks**:
1. Run all tier validation scripts
2. Check manifest.json compliance
3. Validate translations complete
4. Run mypy strict type checking
5. Run ruff linting
6. Run pytest with >95% coverage
7. Verify entity naming conventions
8. Check HACS compliance

**Report**:
- ✅ Requirements met by tier
- ❌ Requirements failed
- 📋 Improvement suggestions
- 🎯 Next tier requirements
- 🏆 Current tier status

**Usage**:
```
User: /ha-quality
User: /ha-quality --tier platinum
```
```

### Priority 2: High-Impact Skills (Weeks 2-4)

#### 4. `/test-fix-deploy` Skill ⭐⭐⭐⭐⭐
**Saves**: 140 min/week | **Effort**: Medium | **File**: `.claude/commands/test-fix-deploy.md`

```markdown
Complete development cycle from testing to deployment:

**Workflow**:
1. **Quality Checks** (via /quality-check)
   - Run linting, type checking, tests
   - Auto-fix issues (max 3 iterations)

2. **Commit Changes** (if all pass)
   - Generate conventional commit message
   - Include co-author attribution
   - Add emoji prefixes

3. **Merge to Main**
   - Switch to main branch
   - Merge feature branch
   - Delete feature branch

4. **Create Release** (optional)
   - Create git tag (v2.x.x)
   - Push tags to remote

5. **Monitor CI/CD**
   - Check GitHub Actions status
   - Report build success/failure

6. **Deploy to Production** (optional)
   - Based on project configuration
   - Validate deployment

7. **Generate Report**
   - Summary of all steps
   - Any warnings or issues
   - Deployment verification results

**Usage**:
```
User: /test-fix-deploy
User: /test-fix-deploy --skip-deploy
User: /test-fix-deploy --release v2.3.0
```

**Safety Checks**:
- Confirm before destructive operations
- Verify no uncommitted secrets
- Check current branch before merge
```

#### 5. `/git:feature` Skill ⭐⭐⭐⭐
**Saves**: 45 min/week | **Effort**: Low | **File**: `.claude/commands/git-feature.md`

```markdown
Complete feature branch workflow:

**Workflow**:
1. Create feature branch from main
   - Auto-generate branch name from description
   - Follow convention: `feature/description-kebab-case`

2. Implement feature
   - Use TodoWrite to track progress
   - Auto-commit checkpoints

3. Run quality checks
   - Via /quality-check

4. Create commit
   - Conventional commit message
   - Co-author attribution

5. Push to remote
   - Create upstream branch

6. Create PR
   - Auto-generate PR description
   - Include test coverage stats
   - Link related issues

**Usage**:
```
User: /git:feature "Add quick charge support"
User: /git:feature "Fix battery voltage scaling" --base develop
```
```

---

## CLAUDE.md Improvements

### Global Instructions (~/.claude/CLAUDE.md)

Add these sections to your global Claude Code configuration:

```markdown
## Autonomous Execution Rules

1. **Default to Continuation**: For mechanical tasks, continue automatically without asking:
   - Testing (pytest, ruff, mypy)
   - Building (npm run build, docker build)
   - Linting/formatting (ruff fix, ruff format)
   - Deploying (after successful validation)

   **Only ask for confirmation on**:
   - Manual decisions (architecture choice, library selection)
   - Destructive operations (delete files, drop database, force push)
   - Production deployments to live systems
   - Operations with cost implications

2. **Progress Tracking**: Use TodoWrite for multi-step tasks to show progress
   instead of asking "continue?" at each step.

3. **Error Recovery**: Attempt automatic fix for common errors:
   - Linting errors → ruff check --fix
   - Import errors → add missing imports
   - Type errors → add type hints (simple cases)
   - Test failures → analyze and fix (if clear)
   - **Max 3 iterations before requesting help**

4. **Test-Fix Loops**: When tests fail:
   - Analyze error message
   - Attempt fix
   - Re-run test
   - Max 3 iterations
   - Report status and request help if unable to fix

## MCP Server Management

**Selective Loading**: Don't load all MCP servers automatically.

**Load based on task context**:
- **Browser Testing** → browser (Chrome DevTools)
- **Library Research** → context7 (only when user asks)
- **MUI Questions** → mui-mcp (only for MUI-specific questions)

**Use Subagents**: For heavy MCP operations (browser testing, doc research),
use subagents to isolate context and preserve main conversation context.

**Clear Context**: Use /clear between distinct tasks to reset context window.

## Standard Pre-Commit Workflow

Before any commit, automatically run:
1. ruff check --fix && ruff format
2. mypy with strict mode
3. pytest with coverage
4. Project-specific validators
5. Only commit if all checks pass

## Multi-Language Projects

For projects with i18n support:
- Check all locales have translations
- Never use hardcoded strings in UI
- Test all language variants
- Use proper names (don't mistranslate proper nouns)
```

### Project-Specific Instructions (CLAUDE.md)

Update the EG4 Web Monitor CLAUDE.md:

```markdown
## Automated Quality Workflow

Before any commit, run automatically (don't ask for confirmation):

```bash
# 1. Run all unit tests
pytest tests/ -x --tb=short

# 2. Run with coverage
pytest tests/ --cov=custom_components/eg4_web_monitor --cov-report=term-missing

# 3. Run tier validations
python3 tests/validate_silver_tier.py
python3 tests/validate_gold_tier.py
python3 tests/validate_platinum_tier.py

# 4. Type checking
mypy --config-file tests/mypy.ini custom_components/eg4_web_monitor/

# 5. Linting
ruff check custom_components/ --fix && ruff format custom_components/
```

**Only commit if all pass**. If tests fail, attempt automatic fix (max 3 iterations).

## Testing Shortcuts

Use these slash commands for common workflows:
- `/quality-check` - Run complete pre-commit validation
- `/ha-quality` - Run Home Assistant quality scale validation
- `/test-fix-deploy` - Complete cycle: test → fix → commit → deploy

## Context Management

Use subagents for:
- Codebase exploration (use Task tool with subagent_type=Explore)
- Chrome DevTools testing (isolates browser context)
- Library documentation research (isolates doc context)

Clear context (/clear) between major task transitions.
```

---

## Subagent Design Recommendations

Based on Anthropic's guidance and our workflow patterns, here are recommended subagent architectures:

### 1. Quality Assurance Subagent

**Trigger**: Pre-commit, pre-deploy, PR creation
**Context Isolation**: Testing operations stay in subagent context

```yaml
Purpose: Autonomous testing and validation

Responsibilities:
  - Run linting (ruff)
  - Run type checking (mypy)
  - Run unit tests (pytest)
  - Check code coverage
  - Run quality validators
  - Generate quality report

Auto-Fix (max 3 iterations):
  - Fix linting errors
  - Add missing imports
  - Format code
  - Add type hints (simple cases)

Report Back to Main:
  - ✅/❌ Pass/fail status
  - Coverage percentage
  - Warnings summary
  - Failed tests details
  - Auto-fix attempts made
  - Recommendations

Implementation:
  Use Task tool with custom prompt:
  "Run complete quality validation suite for this project.
   Attempt auto-fixes for any failures (max 3 iterations).
   Report summary of results."
```

**Context Savings**: ~20-30k tokens (testing output stays in subagent)

### 2. Chrome Testing Subagent

**Trigger**: Post-implementation, before commit
**Context Isolation**: Browser MCP and test results stay in subagent

```yaml
Purpose: Autonomous browser testing with Chrome DevTools

Responsibilities:
  - Start dev server
  - Navigate to all routes
  - Check console errors
  - Test user interactions
  - Validate forms
  - Test all locales
  - Capture screenshots
  - Stop dev server

Auto-Fix (max 3 iterations):
  - Fix console errors
  - Fix routing issues
  - Fix missing translations
  - Re-test after fixes

Report Back to Main:
  - ✅/❌ Test results summary
  - Console errors found
  - 404s detected
  - Missing translations
  - Screenshots of failures
  - Auto-fix attempts made

Implementation:
  Use Task tool with custom prompt:
  "Test this web application with Chrome DevTools.
   Start dev server, test all routes and locales,
   attempt fixes for any errors (max 3 iterations),
   report summary."
```

**Context Savings**: ~40-50k tokens (browser MCP context isolated)

### 3. Codebase Explorer Subagent

**Trigger**: When user asks about code structure/patterns
**Context Isolation**: File search results stay in subagent

```yaml
Purpose: Explore codebase to answer questions

Responsibilities:
  - Use Grep to search code
  - Use Glob to find files
  - Read relevant files
  - Analyze patterns
  - Identify relationships
  - Generate summary

Report Back to Main:
  - Concise answer to question
  - Key file paths referenced
  - Code patterns identified
  - Recommendations

DO NOT report back:
  - Full file contents
  - All search results
  - Detailed exploration logs

Implementation:
  Already available: Task tool with subagent_type=Explore
  "Find files that handle client errors"
  Returns summary, not full search results.
```

**Context Savings**: ~30-60k tokens (search results summarized)

### 4. Documentation Research Subagent

**Trigger**: When researching library docs
**Context Isolation**: MCP doc fetches stay in subagent

```yaml
Purpose: Research library documentation efficiently

Responsibilities:
  - Use context7 MCP to fetch docs
  - Read relevant documentation
  - Extract key information
  - Identify best practices
  - Find code examples
  - Generate summary

Report Back to Main:
  - Concise answer to question
  - Key concepts identified
  - Code examples (short)
  - Best practices
  - Links to full documentation

DO NOT report back:
  - Full documentation pages
  - All search results
  - Detailed API references

Implementation:
  Use Task tool with custom prompt:
  "Research [library] documentation for [topic].
   Use context7 MCP to fetch docs.
   Provide concise summary with key points and examples."
```

**Context Savings**: ~30-50k tokens (doc fetches isolated)

---

## Implementation Roadmap

### Phase 1: Quick Wins (Week 1) - 2-4 hours

**Goal**: Immediate efficiency gains with minimal effort

1. **Update CLAUDE.md files** (30 min)
   - Add autonomous execution rules to global CLAUDE.md
   - Add automated quality workflow to project CLAUDE.md
   - Add MCP server management strategy

2. **Create `/quality-check` command** (30 min)
   - File: `.claude/commands/quality-check.md`
   - Implement as documented above

3. **Create `/ha-quality` command** (20 min)
   - File: `.claude/commands/ha-quality.md`
   - Implement as documented above

4. **Create `/chrome-test` command** (1 hour)
   - File: `.claude/commands/chrome-test.md`
   - Test with subagent approach

5. **Test and validate** (30 min)
   - Run each command to verify functionality
   - Adjust based on results

**Expected Impact**:
- 34 min/week saved (continuation prompts reduced)
- 58 min/week saved (pre-commit validation automated)
- 25 min/week saved (HA validation automated)
- **Total: ~2 hours/week saved**

### Phase 2: High-Impact Skills (Weeks 2-4) - 6-8 hours

**Goal**: Automate end-to-end workflows

1. **Create `/test-fix-deploy` skill** (3 hours)
   - File: `.claude/commands/test-fix-deploy.md`
   - Integrate with /quality-check
   - Add git workflow automation
   - Add CI/CD monitoring
   - Test thoroughly

2. **Create `/git:feature` skill** (2 hours)
   - File: `.claude/commands/git-feature.md`
   - Implement branch workflow
   - Add PR creation
   - Test with real feature

3. **Enhanced `/git:cm` command** (1 hour)
   - Update existing command
   - Add conventional commit messages
   - Add co-author attribution

4. **Create `/git:cleanup` command** (30 min)
   - File: `.claude/commands/git-cleanup.md`
   - Automate branch cleanup

5. **Documentation and testing** (1.5 hours)
   - Document all new skills
   - Create usage examples
   - Test workflows end-to-end

**Expected Impact**:
- 140 min/week saved (deploy workflow automated)
- 45 min/week saved (git feature workflow)
- **Total: ~3 hours/week saved (cumulative: 5 hours/week)**

### Phase 3: Advanced Optimization (Months 2-3) - 8-12 hours

**Goal**: Implement subagent architecture and advanced features

1. **Quality Assurance Subagent** (4 hours)
   - Design subagent architecture
   - Implement with Task tool
   - Add auto-fix logic
   - Test with various scenarios

2. **Chrome Testing Subagent** (4 hours)
   - Design subagent workflow
   - Integrate browser MCP properly
   - Add context isolation
   - Test with real applications

3. **Optimize MCP Server Usage** (2 hours)
   - Implement selective loading
   - Add context management
   - Test token reduction
   - Measure improvements

4. **Documentation and Refinement** (2 hours)
   - Document subagent patterns
   - Create usage guidelines
   - Refine based on usage data

**Expected Impact**:
- 77 min/week saved (chrome testing automated)
- 60+ min/week saved (context optimization)
- **Total: ~2+ hours/week saved (cumulative: 7-9 hours/week)**

---

## Expected Impact

### Time Savings Summary

| Phase | Implementation | Weekly Savings | Cumulative |
|-------|---------------|----------------|------------|
| Phase 1 (Week 1) | 2-4 hours | 2 hours | 2 hours |
| Phase 2 (Weeks 2-4) | 6-8 hours | 3 hours | 5 hours |
| Phase 3 (Months 2-3) | 8-12 hours | 2+ hours | 7-9 hours |

### ROI Analysis

**Total Implementation Time**: 16-24 hours
**Weekly Time Savings**: 7-9 hours
**Break-even Point**: 2-3 weeks
**First Year Savings**: 364-468 hours (9-12 work weeks)

### Quality Improvements

Beyond time savings, these improvements provide:

1. **Consistency**: Automated workflows ensure quality checks always run
2. **Reliability**: Reduced human error in repetitive tasks
3. **Documentation**: Slash commands serve as living documentation
4. **Context Efficiency**: Subagents preserve context for complex tasks
5. **Cognitive Load**: Less mental overhead managing repetitive tasks

### Token Usage Reduction

Based on Anthropic's guidance and our analysis:

| Optimization | Token Savings/Session | Annual Savings |
|--------------|----------------------|----------------|
| Selective MCP loading | 15-20k tokens | ~8M tokens |
| Subagent usage | 20-30k tokens | ~12M tokens |
| Context clearing | 10-15k tokens | ~6M tokens |
| **Total** | **45-65k tokens** | **~26M tokens** |

**Cost Savings** (at Claude Sonnet 4.5 pricing):
- Input: 26M tokens × $3/1M = **$78/year**
- Output savings also significant
- **Plus**: Faster responses due to smaller context

---

## Monitoring and Iteration

### Success Metrics

Track these metrics to measure improvement:

1. **Time Metrics**
   - Time spent on testing per feature
   - Time from commit to deploy
   - Time spent on quality checks
   - Time spent on continuation prompts

2. **Quality Metrics**
   - Test coverage percentage
   - Linting errors caught pre-commit
   - Failed deployments reduced
   - CI/CD build success rate

3. **Context Metrics**
   - Average tokens per session
   - Context overflow incidents
   - Subagent usage frequency

4. **Developer Experience**
   - Cognitive load (subjective)
   - Task completion satisfaction
   - Confidence in automated workflows

### Continuous Improvement

1. **Monthly Review** (30 min)
   - Review time savings data
   - Identify new patterns
   - Adjust skills as needed

2. **Quarterly Enhancement** (2 hours)
   - Refine existing skills
   - Add new skills for emerging patterns
   - Update CLAUDE.md based on learnings

3. **Community Sharing**
   - Share successful patterns with HA community
   - Contribute to Claude Code examples
   - Document lessons learned

---

## Conclusion

This analysis reveals clear opportunities to dramatically improve our Claude Code efficiency through:

1. **Smarter MCP usage** - Selective loading and subagents save 45-65k tokens/session
2. **Custom skills** - Automate repetitive workflows saving 7-9 hours/week
3. **Autonomous operation** - Reduce unnecessary interruptions by 95%
4. **Subagent architecture** - Preserve context while handling complex operations

**Next Steps**:
1. Implement Phase 1 quick wins (Week 1)
2. Test and validate improvements
3. Proceed to Phase 2 based on results
4. Monitor metrics and iterate

**Expected Outcome**:
- **75% reduction** in time spent on repetitive tasks
- **50% reduction** in token usage through context optimization
- **Improved quality** through consistent automated validation
- **Better developer experience** with less cognitive overhead

---

## References

1. [Anthropic: Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) - Context optimization techniques
2. [Anthropic: Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices) - Subagent usage guidance
3. [Scott Spence: Optimising MCP Server Context Usage](https://scottspence.com/posts/optimising-mcp-server-context-usage-in-claude-code) - Practical MCP optimization
4. [Session History Analysis Report](/tmp/claude_history_analysis_report.md) - Full 17-section analysis of 4,378 sessions

---

**Document Version**: 1.0
**Last Updated**: 2025-11-18
**Author**: Claude Code Session Analysis
**Approved By**: [Pending Review]
