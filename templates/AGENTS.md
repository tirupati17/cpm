# {{PROJECT_NAME}} — Shared Project Context

> Fill out the bracketed sections. Delete anything you don't need.

{{ONE_LINE_DESCRIPTION}} (e.g. "AI coaching app across iOS, Android, Web, and backend.")

---

## Working Principles — read this FIRST every session

**Before touching code**, every task runs through three phases in order. Do not skip. Do not collapse them into one.

### 1. Truth — what does this requirement actually need?

State the real outcome that fulfills the ask, separated from the wording or the first interpretation.

- Read the context that already exists: `TRUTH.md`, `memory/summaries/<relevant project>.md`, the recent changelogs in `memory/changelogs/<project>/`, the platform's own `CLAUDE.md`, and `MEMORY.md`.
- Look at the actual code referenced before assuming what it does.
- Restate the truth in **one sentence** before moving on. If you cannot state it crisply, you don't have it yet — ask.

### 2. Skills — what already exists that solves this?

Reuse before inventing. Almost every new requirement maps onto managers / services / components / RPCs / patterns that already ship.

- Search the relevant repo for `.shared` singletons, helpers, components, deep links, hooks, etc.
- Produce a **reuse map**: *"I'll wire <new piece> through <existing piece A> + <existing piece B>."*
- Note constraints from the platform CLAUDE.md (feature flags, platform-specific gotchas, etc.).

### 3. Next Steps — ask, process, verify

- **Ask in detail before guessing.** If the truth or the reuse map has gaps, ask focused clarifying questions in **one round**.
- **Once enough info is in**, process the work: small **atomic commits**, conventional messages, one concern per commit, **never push unless explicitly asked**.
- **Once done, cover all test cases that fulfil the truth through context.** Walk every reasonable case the change touches — success path, edge cases, platform-specific guards, accessibility, regressions on adjacent screens. Spell them out in the response **even when you can't run them.**

**The order matters.** Truth without skills produces reinvention. Skills without truth produces the wrong feature. Both without verification produces fragile delivery. If implementation starts before all three phases are clear, **stop and back up**.

---

## Platform Repos

| Repo | Tech Stack | Branch | Deployment |
|------|-----------|--------|------------|
| `{{REPO_1}}/` | {{TECH_1}} | `main` | {{DEPLOY_1}} |
| `{{REPO_2}}/` | {{TECH_2}} | `main` | {{DEPLOY_2}} |

Each repo has its own `.git` — they are NOT submodules. **Always verify you're in the correct repo directory before git operations.**

---

## Git Commit Policy (All Repos)

**Commit after every critical, major, or useful change.** Each commit should be atomic — don't batch unrelated changes. Use clear, concise messages. **Never push without explicit permission.**

---

## CPM — Cross-Project Memory System

This project uses CPM — an automated memory system that tracks every commit across all sub-projects, summarizes changes, and maintains a single source of truth.

### Architecture

```
TRUTH.md                                ← Single source of truth (read this first)
memory/
  changelogs/<project>/<date>_<hash>.md ← One file per commit (auto-generated)
  summaries/<project>.md                ← Feature-oriented summary per project
  reports/report_<date>.md              ← Saved status reports
scripts/
  detect-projects.sh   ← Auto-detects git repos in workspace
  log-commit.sh        ← Called by post-commit hooks
  summarize.sh         ← Per-project summaries from changelogs
  generate-truth.sh    ← Regenerates TRUTH.md
  install-hooks.sh     ← Installs post-commit hooks (auto-detect)
  cpm-check.sh         ← Session health check + daily briefing
  generate-report.sh   ← Cross-project status report
setup.sh               ← Interactive setup wizard (run once on a fresh clone)
```

### Session Start

**On every new Claude Code session, run `./scripts/cpm-check.sh` first** — it auto-installs missing hooks, backfills empty changelog dirs, refreshes stale TRUTH.md, and gives a one-line health summary.

Then read in order:
1. `TRUTH.md` — complete project state at a glance
2. `memory/summaries/<relevant-project>.md` — deeper context for the platform
3. Raw changelogs in `memory/changelogs/<project>/` — only for commit-level detail

### Auto-tracked

After committing in any sub-project, everything happens automatically via the post-commit hook:
1. `log-commit.sh` writes a changelog entry
2. (Background) `summarize.sh` regenerates the project summary
3. (Background) `generate-truth.sh` updates TRUTH.md

No manual steps. To force-refresh: `./scripts/summarize.sh && ./scripts/generate-truth.sh`.

---

## Platform-Specific CLAUDE.md

Each repo can have its own `CLAUDE.md` with platform-specific conventions. The shared one (this file) is for cross-cutting context.

**Always read the platform-specific CLAUDE.md when working in that repo.**

---

## Working Directory Context

When launched from the workspace root, you have access to all repos. When working on a specific platform:
1. Read that repo's `CLAUDE.md` first
2. Run git commands from within that repo's directory
3. Never cross-commit files between repos
