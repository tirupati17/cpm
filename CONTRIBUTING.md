# Contributing

CPM is shell scripts and markdown on purpose, so the bar for a useful change is
low and the bar for breaking somebody's workspace is high.

## Before a pull request

- `bash -n scripts/*.sh install.sh setup.sh` must pass.
- `./scripts/test-cpm.sh` must pass on a scratch workspace.
- Nothing may write outside the workspace root, and nothing may make a network
  call in the commit path. A hook that is slow or chatty gets uninstalled, and
  then the memory stops existing.

## Things that would genuinely help

- **Linux.** It should work and has only been run on macOS.
- **Other agents.** The integration is "read TRUTH.md first", so Cursor, Cody,
  Aider and others should need only a recipe, not code.
- **Better summaries.** `summarize.sh` groups by conventional-commit type. It
  could be smarter without becoming a dependency on a model.

## Things that would not

- A database, a daemon, or a hosted service. The point is that it is files in
  your own repo that you can read and delete.
- Anything that sends commit data anywhere by default.
