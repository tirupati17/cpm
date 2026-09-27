#!/usr/bin/env python3
"""Update the Play listing text (title, short and full description) per language.

The copy lives in <repo>/store-listing/<play-language>.json, one file per
listing, reviewed like code:

    {"title": "...", "shortDescription": "...", "fullDescription": "..."}

This command checks it against Play's limits and metadata policy, shows what
would change against the live listing, and publishes.

    cpm play listing                       # dry run: validate on Play, then discard
    cpm play listing --commit              # publish the listing text
    cpm play listing --languages en-US     # only some languages
    cpm play listing --create              # also add languages with no listing yet

Policy the checks enforce: limits of 30/80/4000 characters, no "best", "#1",
"top", "free", "new" or other ranking or price claims in the title, no emoji or
all-caps words in the title. --forbid-dashes adds a house-style ban on em and
en dashes in every field.
"""
import argparse
import json
from pathlib import Path

import _play
from _listing import LIMITS, changes, problems
from _release import repo_root


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--commit', action='store_true', help='publish; without it nothing changes')
    parser.add_argument('--languages', help='comma separated Play language codes (default: every file in the copy folder)')
    parser.add_argument('--create', action='store_true', help='also create listings for languages Play does not have yet')
    parser.add_argument('--dir', help='copy folder (default <repo>/store-listing)')
    parser.add_argument('--repo', help='repository root (default: git toplevel of the current directory)')
    parser.add_argument('--forbid-dashes', action='store_true', help='reject em and en dashes (house style)')
    parser.add_argument('--package', help='application id (default: PLAY_PACKAGE credential)')
    args = parser.parse_args()

    folder = Path(args.dir) if args.dir else repo_root(args.repo) / 'store-listing'
    files = sorted(folder.glob('*.json'))
    wanted = set(args.languages.split(',')) if args.languages else None
    copies = {f.stem: json.loads(f.read_text(encoding='utf-8')) for f in files if not wanted or f.stem in wanted}
    if not copies:
        raise SystemExit(f'No listing copy selected in {folder}.')

    bad = {lang: p for lang, copy in copies.items() if (p := problems(copy, args.forbid_dashes))}
    for lang, p in bad.items():
        print(f'{lang}: ' + '; '.join(p))
    if bad:
        raise SystemExit('Fix the copy above first. Nothing was sent.')

    PACKAGE = _play.package(args.package)
    edits = _play.service().edits()
    edit = edits.insert(packageName=PACKAGE, body={}).execute()['id']
    committed = False
    try:
        live = {l['language']: l for l in edits.listings().list(packageName=PACKAGE, editId=edit).execute().get('listings', [])}
        for lang, copy in copies.items():
            current = live.get(lang)
            if current is None and not args.create:
                print(f'{lang}: no listing on Play yet, skipped (use --create)')
                continue
            changed = changes(current, copy)
            print(f'{lang}: {"new listing" if current is None else ("unchanged" if not changed else "changes " + ", ".join(changed))}')
            if current is not None and 'title' in changed:
                print(f'    title: {current.get("title")!r} -> {copy["title"]!r}')
            if current is not None and 'shortDescription' in changed:
                print(f'    short: {current.get("shortDescription")!r}\n        -> {copy["shortDescription"]!r}')
            if changed or current is None:
                edits.listings().update(packageName=PACKAGE, editId=edit, language=lang, body={
                    'language': lang, **{f: copy[f] for f in LIMITS}}).execute()
        edits.validate(packageName=PACKAGE, editId=edit).execute()
        print('validated by Play')
        if not args.commit:
            print('\nDRY RUN. Nothing published. Re-run with --commit.')
            return
        edits.commit(packageName=PACKAGE, editId=edit).execute()
        committed = True
    finally:
        if not committed:
            _play.discard(edits, PACKAGE, edit)

    # Read the listings back rather than trusting the commit response.
    after = _play.read_back(edits, PACKAGE, lambda e: {
        l['language']: l for l in edits.listings().list(packageName=PACKAGE, editId=e).execute().get('listings', [])})
    stale = [lang for lang in copies if lang in after and changes(after[lang], copies[lang])]
    if stale:
        print(f'WARNING: Play does not report the new copy for: {", ".join(stale)}. Check the console.')
    print('\nPUBLISHED. Listing changes can take a few hours to appear in search.')


if __name__ == '__main__':
    main()
