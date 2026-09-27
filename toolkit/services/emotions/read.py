#!/usr/bin/env python3
"""Read what a stretch of git history felt like, as a mood-journal entry.

    cpm emotions read <repo>                   # commits since this repo's last ledger entry
    cpm emotions read <repo> --range A..B      # an explicit range
    cpm emotions read <repo> --record          # also append it to the ledger
    cpm emotions read <repo> --record --log    # and send it to the journal's MCP server
    cpm emotions read --tag release            # every ledger entry carrying #release
    cpm emotions read --tags                   # every tag, with how often it appears

Prints JSON shaped for a `log_emotion` MCP tool: emotion, intensity, triggers
and a note that opens in plain English and ends in #tags, plus `related`, the
earlier entries that share a tag with this one.

The reading follows effort (see `feel` and `complexity`): a revert
disappoints, the same thing fixed over and over frustrates, a tiny fix for a
slip amuses, a store release makes proud, a long hard fix late at night
drains, a big feature satisfies, a new feature makes happy, a fix for
something broken relieves, housekeeping is calm. Intensity follows how big
and how wide the change was. The first trigger is always `tasks`, which marks
an entry as coming from git rather than from a person; a second names what the
work touched (money, community, education, health).

Settings (cpm creds set NAME VALUE; none is a secret, all optional):
  EMOTION_LEDGER      ledger path (default ~/.config/cpm/<project>/emotions.jsonl)
  EMOTION_MCP_SERVER  name of the journal's MCP server in Claude Code's config;
                      --log reads its URL and Authorization header from there,
                      so re-pairing the journal never breaks this
  EMOTION_TAG_WORDS   comma-separated words worth a tag the first time they appear

The git pre-push hook installed by scripts/install-hooks.sh runs
`read --record --log` in the background once the push has landed.
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from cpmkit import creds, http


def setting(name):
    # Read without prompting: this runs from a git hook with no terminal.
    return os.environ.get(name) or creds.load().get(name) or ""


PROJECT = creds.project_name()
LEDGER = Path(setting("EMOTION_LEDGER") or creds.project_dir() / "emotions.jsonl").expanduser()

# Words worth a tag even the first time they appear. Anything else becomes a
# tag only once an earlier entry already used it, which is how links form.
DOMAIN = {
    "release", "billing", "paywall", "ads", "subscription", "premium", "onboarding", "notification",
    "reminder", "widget", "privacy", "security", "localization", "i18n", "sync", "backup", "crash",
    "outage", "analytics", "flag", "search", "landing", "beta", "auth", "login", "api",
} | {w.strip().lower() for w in setting("EMOTION_TAG_WORDS").split(",") if w.strip()}
STOP = {
    "the", "and", "for", "with", "from", "into", "that", "this", "when", "then", "than", "them",
    "only", "every", "each", "once", "more", "most", "less", "just", "also", "still", "never",
    "now", "not", "one", "two", "three", "all", "any", "its", "their", "your", "our", "out", "off",
    "add", "adds", "added", "fix", "fixes", "fixed", "make", "makes", "use", "uses", "keep", "keeps",
    "chore", "feat", "docs", "perf", "refactor", "test", "tests", "sync", "bump", "through", "instead",
}
# Tags too common to link two entries on their own.
GENERIC = {PROJECT, "work", "tasks", "feat", "fix", "chore", "docs", "perf", "refactor", "test"}

CONVENTIONAL = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?!?:\s*(?P<subject>.+)$")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def ledger():
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]


def commits(repo, rng):
    """Oldest first: sha, ISO date, subject, body and lines changed. `rng` is a
    git range, or a --since=... option."""
    meta = git(repo, "log", "--no-merges", "--format=%h%x1f%aI%x1f%s%x1f%b%x1e", rng)
    items = []
    for chunk in meta.split("\x1e"):
        parts = chunk.strip("\n").split("\x1f")
        if len(parts) < 4:
            continue
        items.append({"sha": parts[0], "date": parts[1], "subject": parts[2].strip(), "body": parts[3].strip(), "lines": 0})
    stats, current = {}, None
    for line in git(repo, "log", "--no-merges", "--format=%h", "--numstat", rng).splitlines():
        if re.fullmatch(r"[0-9a-f]{7,}", line.strip()):
            current = line.strip(); stats[current] = {"lines": 0, "files": set()}
        elif current and line.count("\t") == 2:
            add, rem, path = line.split("\t")
            # Generated and translation files inflate a change without adding effort.
            weight = 0.1 if re.search(r"\.xcstrings$|/values-[^/]+/|lock|\.min\.|translations", path) else 1
            stats[current]["lines"] += int(((int(add) if add.isdigit() else 0) + (int(rem) if rem.isdigit() else 0)) * weight)
            stats[current]["files"].add(path)
    for c in items:
        st = stats.get(c["sha"], {"lines": 0, "files": set()})
        c["lines"], c["files"] = st["lines"], st["files"]
    return list(reversed(items))


def area(path):
    """The part of the project a file belongs to: its first two meaningful folders."""
    # Every language folder is one area: translations, not 19 separate places.
    path = re.sub(r"values-[^/]+|[a-z]{2}(-[A-Za-z]+)?\.lproj", "values", path)
    parts = [p for p in path.split("/")[:-1] if p.lower() not in {"app", "src", "main", "java", "kotlin", "com", "org", "res", "lib", "sources", PROJECT}]
    return "/".join(parts[:2]) or "root"


def complexity(cs):
    """0-7 points: size of the change, how many places it touched, how many steps it took."""
    lines = sum(c["lines"] for c in cs)
    files = set().union(*(c["files"] for c in cs)) if cs else set()
    areas = {area(f) for f in files}
    size = 0 if lines < 40 else 1 if lines < 300 else 2 if lines < 1500 else 3
    breadth = 0 if len(areas) <= 1 else 1 if len(areas) <= 4 else 2
    steps = 1 if len(cs) >= 5 else 0
    return size + breadth + steps, lines, len(files), len(areas)


SILLY = re.compile(r"\b(typo|forgot|missing|wrong|oops|stray|leftover|actually|again|rename|trailing|whitespace)\b")


def feel(cs):
    """(emotion, intensity, reason) from what the commits show and how hard they were."""
    parsed = [CONVENTIONAL.match(c["subject"]) for c in cs]
    types = [m.group("type") if m else "other" for m in parsed]
    scopes = [m.group("scope") for m in parsed if m and m.group("scope")]
    text = " ".join(c["subject"] + " " + c["body"] for c in cs).lower()
    n = len(cs)
    fixes = types.count("fix")
    feats = types.count("feat")
    releases = sum(1 for c in cs if re.match(r"chore\(release\)", c["subject"]) or
                   re.search(r"app store|play production|testflight", c["subject"].lower()))
    reverts = sum(1 for c in cs if c["subject"].lower().startswith("revert"))
    repeated_fix = max(collections.Counter(m.group("scope") for m in parsed
                                           if m and m.group("type") == "fix" and m.group("scope")).values(), default=0)
    late = any(dt.datetime.fromisoformat(c["date"]).hour < 5 for c in cs)
    trouble = bool(re.search(r"outage|broke|broken|silent|crash|regression|leak|lost|hang|rejected|failed|stuck", text))
    score, lines, files, areas = complexity(cs)
    silly = fixes and not feats and lines <= 30 and bool(SILLY.search(text))

    if reverts:
        emotion, why = "disappointed", "had to undo work that did not hold up"
    elif repeated_fix >= 3:
        emotion, why = "frustrated", f"the same thing needed fixing {repeated_fix} times before it held"
    elif silly:
        emotion, why = "amused", "a small slip, easy to fix once seen"
    elif releases:
        emotion, why = "proud", "it went out to users"
    elif n >= 10 and areas >= 5:
        emotion, why = "overwhelmed", f"{n} changes across {areas} parts of the project at once"
    elif fixes > feats and trouble and score >= 4 and late:
        emotion, why = "drained", "a long, hard fix that ran late"
    elif fixes >= feats and fixes and trouble:
        emotion, why = "relieved", "something was quietly broken, and now it is not"
    elif feats and score >= 5:
        emotion, why = "satisfied", "a big piece of work that came together"
    elif feats and trouble:
        emotion, why = "relieved", "built it, and caught what was broken on the way"
    elif feats:
        emotion, why = "happy", "something new works"
    elif fixes:
        emotion, why = "relieved", "a fix landed"
    else:
        emotion, why = "calm", "tidying up"

    # Intensity follows effort: 1 for a one-liner, 5 for a large change across many places.
    intensity = 1 + round(score * 4 / 7)
    if emotion in {"proud", "frustrated", "disappointed", "drained"}:
        intensity += 1
    if emotion == "amused":
        intensity = min(intensity, 2)
    if late:
        why += ". Done late at night"
    return emotion, max(1, min(5, intensity)), why, types, scopes


IMPACT = [  # second trigger: what the work touched, beyond "a push"
    ("money", r"paywall|billing|price|pricing|ads|subscription|revenue|purchase|conversion|store"),
    ("community", r"friend|share|sharing|social|community|invite"),
    ("education", r"docs|readme|guide|plan|tutorial|onboarding"),
    ("health", r"voice|coach|meditation|exercise|sleep|wellness|breath"),
]


def impact(text):
    for key, pattern in IMPACT:
        if re.search(pattern, text):
            return [key]
    return []


def plain(subject):
    """Commit subject without its conventional prefix, as a sentence."""
    m = CONVENTIONAL.match(subject)
    text = (m.group("subject") if m else subject).strip().rstrip(".")
    # Leave identifiers alone: app://join, /pricing, npx ... stay as written.
    return text if re.match(r"^\S*[:/@.]|^[a-z]+[A-Z_]", text) else text[:1].upper() + text[1:]


def story(repo, cs, emotion, why, score, lines, files, areas):
    """Plain-English first line, then the details."""
    size = ("A release to the stores" if emotion == "proud" else "A tiny change" if score == 0 else
            "A small change" if score == 1 else "A solid piece of work" if score <= 3 else "A big, involved change")
    what = plain(cs[-1]["subject"]) if len(cs) == 1 else f"{len(cs)} changes, ending with: {plain(cs[-1]['subject'])[:1].lower() + plain(cs[-1]['subject'])[1:]}"
    lead = f"{what}. {size}. Felt {emotion}: {why}."
    detail = [f"- {plain(c['subject'])}" for c in cs[-6:]]
    if len(cs) > 6:
        detail.insert(0, f"- ...and {len(cs) - 6} earlier")
    detail.append(f"({repo}, {lines} lines across {files} files in {areas} area{'s' if areas != 1 else ''})")
    return lead + "\n\n" + "\n".join(detail)


def short(repo_name):
    """myapp-ios -> ios, when repos are named after the project."""
    return repo_name[len(PROJECT) + 1:] if repo_name.lower().startswith(PROJECT + "-") else repo_name


def tags_for(repo_name, cs, types, scopes, known):
    tags = [PROJECT, short(repo_name)]
    tags += sorted({t for t in types if t != "other"})
    vocabulary = DOMAIN | known
    # One tag per idea: "milestones" and "milestone" are the same link.
    def one(w):
        return w[:-1] if w.endswith("s") and (w[:-1] in vocabulary or w[:-1] in DOMAIN) else w
    tags += sorted({one(s.lower().replace(" ", "-")) for s in scopes})
    words = [one(w) for w in re.findall(r"[a-z][a-z0-9-]{2,}", " ".join(c["subject"] for c in cs).lower())]
    tags += sorted({w for w in words if w not in STOP and w in vocabulary})
    for c in cs:
        v = re.search(r"\b(\d+\.\d+\.\d+)\b", c["subject"])
        if v and "release" in c["subject"].lower():
            tags.append("v" + v.group(1))
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", help="repo directory (absolute, or relative to here)")
    ap.add_argument("--range", help="git range; default: since this repo's last ledger entry, else the last 12 hours")
    ap.add_argument("--record", action="store_true", help="append the entry to the ledger")
    ap.add_argument("--log", action="store_true", help="send it to the journal MCP server named by EMOTION_MCP_SERVER")
    ap.add_argument("--emotion", help="override the reading (an emotion key the journal accepts)")
    ap.add_argument("--intensity", type=int, help="override the intensity, 1-5")
    ap.add_argument("--tag", help="list ledger entries carrying this tag")
    ap.add_argument("--tags", action="store_true", help="list every tag with its count")
    a = ap.parse_args()
    entries = ledger()

    if a.tags:
        for t, n in collections.Counter(t for e in entries for t in e["tags"]).most_common():
            print(f"#{t}  {n}")
        return
    if a.tag:
        t = a.tag.lstrip("#").lower()
        for e in entries:
            if t in e["tags"]:
                print(f"{e['id']}  {e['emotion']}/{e['intensity']}  {e['repo']}  {e['summary']}  " + " ".join("#" + x for x in e["tags"]))
        return
    if not a.repo:
        ap.error("repo is required unless --tag or --tags is given")

    repo = Path(a.repo).expanduser().resolve()
    a.repo = repo.name
    if a.range:
        rng = a.range
    else:
        last = next((e["head"] for e in reversed(entries) if e["repo"] == a.repo), None)
        rng = f"{last}..HEAD" if last else "--since=12.hours"
    cs = commits(repo, rng)
    if not cs:
        sys.exit(json.dumps({"skip": True, "reason": f"no new commits in {a.repo} ({rng})"}))

    emotion, intensity, why, types, scopes = feel(cs)
    if a.emotion:
        emotion, why = a.emotion, why + "; overridden from the conversation"
    if a.intensity:
        intensity = max(1, min(5, a.intensity))
    known = {t for e in entries for t in e["tags"]}
    tags = tags_for(a.repo, cs, types, scopes, known)
    linking = set(tags) - GENERIC - {short(a.repo)}
    related = [e for e in entries if linking & set(e["tags"])][-5:]

    headline = cs[-1]["subject"] if len(cs) == 1 else f"{len(cs)} commits, last: {cs[-1]['subject']}"
    triggers = ["tasks"] + impact(" ".join(tags + [c["subject"].lower() for c in cs]))
    score, lines, files, areas = complexity(cs)
    note = story(a.repo, cs, emotion, why, score, lines, files, areas)
    if related:
        note += "\nLinked: " + "; ".join(f"{e['id']} {e['emotion']} ({', '.join('#' + t for t in sorted(linking & set(e['tags'])))})" for e in related) + "."
    note += "\n\n" + " ".join("#" + t for t in tags)
    now = dt.datetime.now().astimezone()
    entry = {
        "id": now.strftime("%Y%m%d-%H%M%S-") + short(a.repo), "at": now.isoformat(timespec="seconds"), "repo": a.repo,
        "head": git(repo, "rev-parse", "--short", "HEAD").strip(), "commits": [c["sha"] for c in cs],
        "emotion": emotion, "intensity": intensity, "triggers": triggers, "why": why,
        "summary": headline[:160], "tags": tags, "related": [e["id"] for e in related],
    }
    if a.record:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logged = log(emotion, intensity, triggers, note[:2000]) if a.log else None
    print(json.dumps({"emotion": emotion, "intensity": intensity, "triggers": triggers, "note": note[:2000],
                      "tags": tags, "related": entry["related"], "recorded": a.record, "logged": logged},
                     ensure_ascii=False, indent=2))


def mcp_server(name):
    """URL and headers for an MCP server in Claude Code's config: a project
    (local) entry for this directory wins over the user-wide one."""
    cfg = json.loads((Path.home() / ".claude.json").read_text())
    here = Path.cwd().resolve()
    for project, value in cfg.get("projects", {}).items():
        if here == Path(project) or Path(project) in here.parents:
            if name in (value.get("mcpServers") or {}):
                return value["mcpServers"][name]
    if name in cfg.get("mcpServers", {}):
        return cfg["mcpServers"][name]
    raise SystemExit(f"No MCP server {name!r} in ~/.claude.json. Connect the journal to Claude Code first.")


def log(emotion, intensity, triggers, note):
    """Call the journal's log_emotion tool directly. Stateless JSON-RPC over
    streamable HTTP; the answer may come back as SSE."""
    name = setting("EMOTION_MCP_SERVER")
    if not name:
        raise SystemExit("--log needs EMOTION_MCP_SERVER: cpm creds set EMOTION_MCP_SERVER <name>")
    server = mcp_server(name)
    reply = http.request("POST", server["url"], headers={**(server.get("headers") or {}),
                         "Accept": "application/json, text/event-stream"},
                         body={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                             "name": "log_emotion", "arguments": {"emotion": emotion, "intensity": intensity,
                                                                  "triggers": triggers, "note": note}}})
    text = reply if isinstance(reply, str) else json.dumps(reply)
    data = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")] or [json.loads(text)]
    result = data[-1]
    if "error" in result or (result.get("result") or {}).get("isError"):
        raise SystemExit(f"log_emotion failed: {json.dumps(result)[:300]}")
    return True


if __name__ == "__main__":
    main()
