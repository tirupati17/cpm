#!/usr/bin/env python3
"""Show what every Play track serves right now (read only).

    cpm play status
    cpm play status --track production

Opens an edit, reads the tracks and deletes the edit; nothing is changed.
Useful before a release (is a staged rollout still in progress?) and after one.
"""
import argparse

import _play
from _release import TRACKS

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--track', choices=TRACKS, help='only this track (default: all)')
parser.add_argument('--package', help='application id (default: PLAY_PACKAGE credential)')
args = parser.parse_args()

PACKAGE = _play.package(args.package)
edits = _play.service().edits()


def read(edit_id):
    if args.track:
        return [edits.tracks().get(packageName=PACKAGE, editId=edit_id, track=args.track).execute()]
    return edits.tracks().list(packageName=PACKAGE, editId=edit_id).execute().get('tracks', [])


print(PACKAGE)
for track in _play.read_back(edits, PACKAGE, read):
    releases = track.get('releases') or []
    if not releases:
        print(f'  {track["track"]:<12} (empty)')
    for release in releases:
        fraction = f' userFraction={release["userFraction"]}' if 'userFraction' in release else ''
        print(f'  {track["track"]:<12} {release.get("name", "?")} {release.get("versionCodes")} '
              f'{release.get("status")}{fraction}')
