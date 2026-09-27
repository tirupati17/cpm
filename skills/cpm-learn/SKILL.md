---
name: cpm-learn
description: Use right after finishing a task that took real effort against an external service or API (a store console, billing, ads, analytics, push, cloud) and that is likely to come up again, or when the user says "remember how to do this", "make this a skill", or "teach cpm". Turns what was just done into a reusable CPM skill and, where it is repeatable, a toolkit command.
---

# Teach CPM what you just did

The point is that the next project, or the next session, does not rediscover it.

## 1. Decide what it is

- **A fact about this project** (an id, a decision, a quirk of this app): write
  it to `memory/`, not a skill.
- **Knowledge that holds for any project** (how the API behaves, what the
  console hides, the failure that looked like success): that is a skill.
- **A sequence of API calls you ran by hand** and would run again: that is a
  toolkit command, plus a skill that says when to run it.

## 2. Write the skill

Copy `skills/_template/` to `skills/<service>-<task>/` (or extend the existing
`skills/<service>/SKILL.md` if it fits there). Keep:

- a `description` that says **when** to use it, in the words a user would say;
- the credentials by name, and where each one is obtained;
- the commands, dry run first;
- the traps, each as symptom, cause, how to tell, what to do.

Strip every project-specific value: app ids, package names, account and
customer ids, key ids, prices, people. Those belong in credentials or memory.

## 3. If it is repeatable, add a command

`toolkit/services/<service>/<command>.py`, first docstring line is the summary
`cpm` lists. Rules the existing commands follow:

- credentials only through `cpmkit.creds.get(NAME)`; declare new names in
  `SERVICES` in `toolkit/lib/cpmkit/creds.py` with a `help` saying where to get them;
- anything that changes state is a dry run unless `--commit`, and reads the
  result back afterwards rather than trusting the response;
- third-party imports happen late, so `--help` works on a bare machine;
- never print a secret, never write one outside `~/.config/cpm/`;
- a unit test in `toolkit/tests/` for the pure logic.

## 4. Link it

Run `scripts/cpm-check.sh` (it links new skills into `.claude/skills/`), and
mention the new skill in the commit message so the changelog records it.
