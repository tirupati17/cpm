# CPM Review Bot

Automated code review bot for multi-platform workspaces (iOS, Android, Web, Server) using Claude AI. The bot enforces per-reviewer code review standards automatically on every PR.

## Status

The framework is in place but **no reviewer learnings are configured yet**. To onboard a reviewer:

```bash
./scripts/add-reviewer.sh --name <name> --github <login> --platform ios|android|web|server
```

Optionally harvest patterns from existing PRs:

```bash
./scripts/add-reviewer.sh --name iraida --github iraida-dev --platform ios --pr 42 --pr 51
```

## How it works

- **Platform detection**: Auto-detects from changed file extensions (`.swift` → iOS, `.kt` → Android, `.tsx`/`.ts` → Web, etc.)
- **Reviewer standards**: Loads JSON learnings from `.github/actions/claude-review/learnings/{platform}-{reviewer}.json`
- **Inline comments**: Posts specific feedback on problematic code lines
- **PR scoring**: 10/10 baseline, deductions per finding severity (critical −3, major −2, minor −0.5)
- **Min score to merge**: 8/10

## Files

- `.github/actions/claude-review/index.js` — main GitHub Action runtime
- `.github/actions/claude-review/learnings/` — per-reviewer JSON pattern files
- `.github/actions/claude-review/prompts/` — review prompt templates
- `.github/workflows/claude-review.yml` — workflow that runs the bot on PR events
- `scripts/harvest-pr-comments.js` — extract patterns from existing PRs
- `scripts/cpm-sync.js` — sync learnings across repos

## Required secrets (in each GitHub repo)

- `ANTHROPIC_API_KEY`
- `GITHUB_TOKEN` (provided by Actions automatically)

## Manual audit before push

Even without the GitHub Action enabled, you can manually audit a diff against reviewer learnings via Claude Code:

> "Audit my staged changes against the iOS reviewer learnings."

Claude will read `learnings/ios-*.json`, score the diff, and flag issues.
