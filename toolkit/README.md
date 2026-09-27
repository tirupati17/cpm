# Toolkit

Helpers that talk to the services an app lives on: the two stores, billing,
push, analytics, ads, cloud. One command, `cpm`, and one rule: **credentials
are asked for once per project and never stored in a repo.**

```bash
toolkit/bin/cpm                            # every service and command
toolkit/bin/cpm play                       # one service's commands
toolkit/bin/cpm play publish internal      # dry run: validates, changes nothing
toolkit/bin/cpm play publish internal --commit
```

Put `toolkit/bin` on your `PATH` to type just `cpm`.

## Credentials

The first time a command needs something it asks, says where to get it, and
saves the answer:

```
~/.config/cpm/<project>/            0700
  credentials.env                   0600   NAME=value, one per line
  keys/                             0700   copies of .p8 / service account .json
```

A name resolves from the environment first (CI, one-off overrides), then that
file, then a prompt. Without a terminal it fails with the exact command to fix
it instead of hanging.

```bash
cpm creds setup play appstore      # answer every question for these services
cpm creds list                     # what is stored (secrets masked), what is missing
cpm creds set REVENUECAT_API_KEY   # prompts, hidden
cpm creds import-env ../admin/.env.local    # copy the names it knows
cpm creds exec revenuecat -- node scripts/report.js   # run anything with them
cpm creds where
```

### Which project

Credentials are per project, so two apps in one workspace never mix. The
project is `--project <name>`, else `CPM_PROJECT`, else the first line of a
`.cpm-project` file found walking up from the current directory, else the
workspace's folder name. A workspace with several apps puts a `.cpm-project`
in each repo.

## Keeping an app repo's own commands

Apps usually document their release commands (`scripts/publish-play.py
production --commit`). Keep those as three-line wrappers that call `cpm` with
the app's project name and repo path, so the docs stay true and the logic lives
here once:

```python
#!/usr/bin/env python3
import os, sys
from pathlib import Path
repo = Path(__file__).resolve().parents[1]
toolkit = Path(os.environ.get('CPM_TOOLKIT') or repo.parent / 'toolkit')
os.environ.setdefault('CPM_PROJECT', 'myapp')
os.execv(sys.executable, [sys.executable, str(toolkit / 'bin/cpm'), 'play', 'publish', '--repo', str(repo), *sys.argv[1:]])
```

## Writing a command

See `skills/cpm-learn/SKILL.md`. In short: credentials only through
`cpmkit.creds.get`, writes are dry runs unless `--commit` and read the result
back, third-party imports stay late so `--help` works on a bare machine, pure
logic gets a test in `toolkit/tests/`. Plain JSON REST APIs go through
`cpmkit.http.request` (429 retry, auth headers scrubbed from errors); tests fake
`urllib.request.urlopen` with `tests/apifake.py`, so nothing touches the network.

```bash
cd toolkit && python3 -m unittest discover -s tests
```
