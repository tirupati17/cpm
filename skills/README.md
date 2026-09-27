# Skills

A skill is a folder with a `SKILL.md`: when to use it, what it needs, the
commands, and the traps somebody already paid for. Agents with native skill
support load one only when its `description` matches the task, so a hundred
skills cost nothing until one is needed. Agents without it read
`skills/INDEX.md` (one line per skill) and open the one they need. Either way
it works with any coding agent, and that is how CPM learns on demand.

```
skills/
  cpm-learn/          how to turn work you just did by hand into a new skill
  _template/          copy this to start one
  play-release/       Google Play: publish, listings, images, in-app products
  appstore-release/   App Store Connect: archive, upload, submit
  revenuecat/         subscribers, entitlements, promotional grants, metrics
  onesignal/          push to a user, a segment, or everyone
  amplitude/          feature flags and event totals
  google-ads/         campaigns, budgets, conversions (GAQL)
  gcp/                projects, APIs, service accounts
```

`setup.sh` and `cpm-check.sh` run `scripts/link-skills.sh`, which rewrites
`skills/INDEX.md` and links every folder here into `.claude/skills/` (Claude
Code) and `.agents/skills/` (the shared folder other agents read). Set
`CPM_SKILL_DIRS` to link somewhere else. Skills added to a fork show up in the
next session without any other step.

## The rule

A skill tells the agent what to do; the toolkit does it. Anything with
credentials goes through `cpm <service> <command>` (see `toolkit/README.md`),
which asks for what it needs once per project and keeps it in
`~/.config/cpm/<project>/`. A skill never contains a key, an account id, an
app id, or a price. Those differ per project and live in credentials.

## Writing one

Copy `_template/`, keep it under a page, and lead with the traps. The value of
a skill is the hour it saves the next time, and that hour is almost always a
failure that reported success.
