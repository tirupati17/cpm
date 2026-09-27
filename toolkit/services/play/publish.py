#!/usr/bin/env python3
"""Publish a staged AAB to a Play track (dry run unless --commit).

Dry run by default: it uploads, sets the track and asks Play to validate the
edit, then throws the edit away. Nothing reaches users until --commit.

    cpm play publish production                 # rehearse, change nothing
    cpm play publish production --commit        # 100% rollout
    cpm play publish production --rollout 20 --commit
    cpm play publish internal --commit

The repository is --repo, else the git toplevel of the current directory.
Version comes from app/build.gradle(.kts) (or --gradle), so the thing published
is always the thing configured. The bundle comes from artifacts/<version>/,
whose release.json must match it byte for byte (see `cpm play stage`). Release
notes come from release-notes/<version>/<language>.txt and are user-facing copy:
no flag names, no internals.

Credentials: PLAY_PACKAGE and PLAY_SERVICE_ACCOUNT_JSON (cpm creds). The key's
contents are never printed.
"""
import argparse
import json
from pathlib import Path

import _play
from _release import TRACKS, find_gradle, load_notes, read_version, release_body, repo_root, verify_artifacts

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('track', choices=TRACKS)
parser.add_argument('--rollout', type=float, default=100, help='percent of users (default 100)')
parser.add_argument('--commit', action='store_true', help='actually publish; without it nothing changes')
parser.add_argument('--notes', help='release notes folder (default <repo>/release-notes/<version>)')
parser.add_argument('--repo', help='repository root (default: git toplevel of the current directory)')
parser.add_argument('--gradle', help='build file holding versionName/versionCode (default app/build.gradle(.kts))')
parser.add_argument('--artifacts', help='staged artifacts folder (default <repo>/artifacts/<version>)')
parser.add_argument('--package', help='application id (default: PLAY_PACKAGE credential)')
args = parser.parse_args()

root = repo_root(args.repo)
version, code = read_version(find_gradle(root, args.gradle).read_text())

aab, manifest = verify_artifacts(Path(args.artifacts) if args.artifacts else root / 'artifacts' / version, version, code)
notes = load_notes(Path(args.notes) if args.notes else root / 'release-notes' / version)
body = release_body(args.track, code, args.rollout, notes, version_name=version)
PACKAGE = _play.package(args.package)

print(f'{PACKAGE} {version} ({code}) -> {args.track} at {args.rollout:g}%')
print(f'  aab    {aab.name}  {manifest["files"]["aab"]["bytes"]:,} bytes')
if manifest.get('signerSha256'):
    print(f'  signer {manifest["signerSha256"][:16]}...')
print(f'  notes  {", ".join(n["language"] for n in notes)}')

edits = _play.service().edits()
from googleapiclient.errors import HttpError       # imported late so --help needs no SDK
from googleapiclient.http import MediaFileUpload

edit_id = edits.insert(packageName=PACKAGE, body={}).execute()['id']
print(f'\nedit {edit_id}')
committed = False
try:
    # A bundle can already be in Play's library without ever having been released:
    # an upload-only edit is how the Console learns about new permissions (the
    # foreground-service declaration form only lists what it has seen in a bundle).
    # Reuse it only when its sha256 matches the staged artifact; a same-numbered
    # bundle with different bytes is a mistake, not a shortcut.
    library = {b['versionCode']: b for b in
               edits.bundles().list(packageName=PACKAGE, editId=edit_id).execute().get('bundles', [])}
    if code in library:
        if library[code].get('sha256') != manifest['files']['aab']['sha256']:
            raise SystemExit(f'versionCode {code} is already uploaded with different bytes. Bump it.')
        print(f'reusing uploaded versionCode {code} (sha256 matches release.json)')
    else:
        try:
            uploaded = edits.bundles().upload(
                packageName=PACKAGE, editId=edit_id,
                media_body=MediaFileUpload(str(aab), mimetype='application/octet-stream', resumable=True),
            ).execute()
        except HttpError as error:
            if b'already been used' in error.content or b'already exists' in error.content:
                raise SystemExit(f'versionCode {code} is already uploaded. Bump it before publishing again.')
            raise
        if uploaded['versionCode'] != code:
            raise SystemExit(f'Play accepted versionCode {uploaded["versionCode"]}, expected {code}.')
        print(f'uploaded versionCode {uploaded["versionCode"]}')

    # What the track serves right now, so a surprise is visible before it is replaced.
    current = edits.tracks().get(packageName=PACKAGE, editId=edit_id, track=args.track).execute()
    for release in current.get('releases', []):
        print(f'  replacing: {release.get("name", "?")} {release.get("versionCodes")} {release.get("status")}')

    edits.tracks().update(packageName=PACKAGE, editId=edit_id, track=args.track, body=body).execute()
    edits.validate(packageName=PACKAGE, editId=edit_id).execute()
    print(f'validated: {json.dumps(body["releases"][0], ensure_ascii=False)[:160]}...')

    if not args.commit:
        raise SystemExit('\nDRY RUN. Nothing published. Re-run with --commit.')
    edits.commit(packageName=PACKAGE, editId=edit_id).execute()
    committed = True
finally:
    if not committed:
        _play.discard(edits, PACKAGE, edit_id)

# Read the track back rather than trusting the commit response.
live = _play.read_back(edits, PACKAGE, lambda edit: edits.tracks().get(
    packageName=PACKAGE, editId=edit, track=args.track).execute())
# A staged rollout leaves the previous completed release on the track too, so
# look for the one carrying this versionCode instead of taking the first.
releases = live.get('releases') or [{}]
serving = next((r for r in releases if str(code) in (r.get('versionCodes') or [])), releases[0])
print(f'\nPUBLISHED. {args.track} now serves {serving.get("name")} '
      f'{serving.get("versionCodes")} status={serving.get("status")}'
      + (f' userFraction={serving["userFraction"]}' if 'userFraction' in serving else ''))
if str(code) not in (serving.get('versionCodes') or []):
    raise SystemExit('Track does not report the version just published. Check the console.')
