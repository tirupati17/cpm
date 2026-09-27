# CPM (Cross-Project Memory)

CPM gives your coding agent a memory across repos, and a toolkit for the app store,
billing and push services a mobile app runs on.

## What it is

- **Memory.** A git `post-commit` hook writes a short note for every commit. The
  notes roll up into one summary per project and a single `TRUTH.md` for the whole
  workspace. Your agent reads `TRUTH.md` at the start of a session and already
  knows where things stand.
- **Toolkit.** One command, `cpm`, for Google Play, App Store Connect, RevenueCat,
  OneSignal, Amplitude, Google Ads and Google Cloud. Every write is a dry run until
  you add `--commit`.
- **Skills.** Short guides the agent loads only when a task needs them, one per
  service.

## How it is made

Bash scripts, git hooks and Markdown files for the memory. Python (standard library
where possible) for the toolkit. No server, no database, no account. Everything is
plain files in your own workspace. Credentials stay in `~/.config/cpm/<project>/`,
never in a repo.

## How it works

**Memory: every commit becomes something your agent can read.**

```mermaid
flowchart LR
    A["git commit<br/>in any repo"] --> B["post-commit hook"]
    B --> C["changelogs/#lt;project#gt;/<br/>one note per commit"]
    C --> D["summaries/#lt;project#gt;.md<br/>rebuilt in the background"]
    D --> E["TRUTH.md<br/>the whole workspace"]
    E --> F["Your agent reads it<br/>at the start of a session"]
```

**Toolkit: the agent picks a skill, the skill runs a `cpm` command.**

```mermaid
flowchart LR
    T["Task<br/>e.g. ship to Play"] --> S["skills/<br/>loaded only when needed"]
    S --> K["cpm #lt;service#gt; #lt;command#gt;<br/>dry run by default"]
    CR["~/.config/cpm/#lt;project#gt;/<br/>credentials"] --> K
    K -- "--commit" --> P["Play, App Store, RevenueCat,<br/>OneSignal, Amplitude, Ads, GCP"]
```

And when you work something out by hand, the `cpm-learn` skill turns it into a new
skill, so the next time is one command.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/tirupati17/cpm-oss/main/install.sh | bash
```

Or clone it into the folder that holds your repos and run `./setup.sh`. Then:

```bash
./scripts/install-hooks.sh    # add the post-commit hook to every repo
./scripts/backfill.sh         # optional: build notes from existing history
./scripts/cpm-check.sh        # health check and a short briefing
```

Add this to your agent's instructions (`CLAUDE.md`, `AGENTS.md`, and so on):

```markdown
At the start of every session, run ./scripts/cpm-check.sh, then read TRUTH.md
and memory/summaries/<project>.md.
```

More detail: [`toolkit/README.md`](toolkit/README.md), [`skills/README.md`](skills/README.md).

## Built with CPM

- [Emotica](https://emotica.me): emotional wellness app for iOS, Android and web.
- [Aastroastra](https://www.aastroastra.com): AI Vedic astrology app.

## Who makes it

CPM is built and maintained by Tirupati Balan, currently its only contributor. I use
it every day to build and ship my own mobile products, and I made it open source so
other developers can use it too. Issues and pull requests are welcome.

## Licence

MIT. See [LICENSE](LICENSE).
