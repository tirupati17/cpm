# CPM — Cross-Project Memory

Your coding agent forgets everything between sessions. CPM writes it down.

It hooks into `git commit` across every repo in a workspace, records what changed
and why, rolls that up per project, and keeps one file the agent reads first.
No daemon, no database, no API key. Shell scripts and markdown.

```
workspace/
  TRUTH.md                              ← the whole workspace, at a glance
  memory/
    changelogs/<project>/<date>_<sha>.md   ← one file per commit, written by a hook
    summaries/<project>.md                 ← what this project is, and where it got to
    plans/  reports/  people/              ← the things you would otherwise re-explain
```

---

## The problem

If you work across several repos with an AI agent, you spend the first ten
minutes of every session re-explaining the same things: what this project is,
what you tried last week, why that odd workaround exists. The agent has a
transcript of the current conversation and nothing else.

Meanwhile the answer is already sitting in your git history, in a form nobody
can read quickly: 4,000 commits saying "fix bug".

CPM turns commits into something an agent can actually use, at the moment the
commit happens, without you doing anything.

## How it works

1. `install-hooks.sh` drops a `post-commit` hook into every git repo it finds.
2. On each commit, `log-commit.sh` writes a changelog entry: the message, the
   files, the diff shape, the author, the branch.
3. In the background it regenerates that project's summary and `TRUTH.md`.
4. Your agent reads `TRUTH.md` first and starts the session already knowing.

Everything is plain markdown in your own repo. You can read it, grep it, edit
it, and delete it. There is nothing to log into.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/tirupati17/cpm/main/install.sh | bash
```

Or clone into the workspace that holds your repos and run `./setup.sh`.

Then, from the workspace root:

```bash
./scripts/install-hooks.sh    # every repo it finds gets a post-commit hook
./scripts/backfill.sh         # optional: build changelogs from existing history
./scripts/cpm-check.sh        # health check + a one-line briefing
```

## Commands

| Command | What it does |
|---|---|
| `cpm-check.sh` | Installs missing hooks, backfills empty dirs, refreshes stale TRUTH.md |
| `generate-report.sh` | Cross-project status report, filtered to your own commits |
| `generate-report.sh --hours 168` | The same, for a week |
| `summarize.sh` | Rebuild every project summary from its changelogs |
| `generate-truth.sh` | Rebuild TRUTH.md |
| `postreport.sh` | Post the report to Slack |
| `add-reviewer.sh` | Onboard a code reviewer whose patterns the review bot enforces |
| `test-cpm.sh` | Diagnostics |

## Telling your agent to use it

Add this to `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, or whatever your tool
reads:

```markdown
On every new session, run ./scripts/cpm-check.sh first. Then read in order:
1. TRUTH.md
2. memory/summaries/<the project you are working on>.md
3. memory/changelogs/<project>/ only when you need commit-level detail
```

That is the whole integration. CPM does not care which agent you use, because
it only writes files.

## Design decisions, and why

**Markdown, not a database.** The memory has to be readable by a human, a
grep, and a language model, on a machine with nothing installed. A database is
better at everything except those three things, which are the only three that
matter here.

**Post-commit, not a watcher.** A commit is the moment a developer has already
decided a change is coherent and described it. Anything more frequent records
noise; anything less relies on remembering.

**In your repo, not a service.** Your commit history is not something to send
somewhere. There is no account, no telemetry, no network call in the hot path.

**Summaries are regenerated, never appended.** A summary that accretes becomes
a log with a worse name. Every regeneration re-reads the changelogs, so old
entries can be corrected by deleting them.

**Background, always.** The hook returns immediately and the summary rebuild
runs detached. A memory system that makes `git commit` slow is a memory system
you will uninstall.

## Requirements

Bash, git, and standard POSIX tools. Tested on macOS. `postreport.sh` needs a
Slack token if you want it; nothing else needs credentials.

## Optional: the review bot

`claude-review-bot/` is a GitHub Action that reviews pull requests against
per-reviewer learnings, so a reviewer's repeated feedback becomes something the
bot enforces before they have to say it again. It is independent of the memory
system; use it or delete the folder.

## Status

Built to solve one person's problem across six repos, and used daily for that.
It works, it is small, and the interfaces are files, so it is easy to bend to a
setup I have not thought of. Issues and pull requests welcome, particularly
from anyone running it on Linux, where it should work and has not been tested.

## Licence

MIT. See [LICENSE](LICENSE).
