#!/usr/bin/env python3
"""Stage a built AAB (and APK) under artifacts/<version>/ with a release.json.

    cpm play stage                                   # app/build/outputs/... of the git toplevel
    cpm play stage --aab path/to/app-release.aab --apk path/to/app-release.apk
    cpm play stage --name myapp                      # files named myapp-<version>.aab

Local only: no network, no credentials. The manifest records each file's size
and sha256 at staging time; `cpm play publish` rehashes the bundle against it
and refuses a leftover from an earlier build, which otherwise looks exactly
right in every log because artifacts/<version>/ survives a failed build.

Run this only after your own signing and verification checks pass (signer
certificate, target SDK, zipalign, whatever your store requires). If your build
script already writes release.json in this shape, you do not need this command:

    {"versionName": "1.2.0", "versionCode": 12,
     "files": {"aab": {"filename": "...", "bytes": 123, "sha256": "..."}}}
"""
import argparse
from pathlib import Path

from _release import find_gradle, read_version, repo_root, stage_artifacts

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--repo', help='repository root (default: git toplevel of the current directory)')
parser.add_argument('--gradle', help='build file holding versionName/versionCode (default app/build.gradle(.kts))')
parser.add_argument('--aab', help='bundle to stage (default app/build/outputs/bundle/release/app-release.aab)')
parser.add_argument('--apk', help='APK to stage too (default app/build/outputs/apk/release/app-release.apk if present)')
parser.add_argument('--artifacts', help='output folder (default <repo>/artifacts/<version>)')
parser.add_argument('--name', help='file basename (default: the repository folder name)')
parser.add_argument('--signer', help='signing certificate SHA-256 to record in release.json (informational)')
args = parser.parse_args()

root = repo_root(args.repo)
version, code = read_version(find_gradle(root, args.gradle).read_text())
aab = Path(args.aab) if args.aab else root / 'app/build/outputs/bundle/release/app-release.aab'
apk = Path(args.apk) if args.apk else root / 'app/build/outputs/apk/release/app-release.apk'
if not args.apk and not apk.is_file():
    apk = None
output = Path(args.artifacts) if args.artifacts else root / 'artifacts' / version
extra = {'signerSha256': args.signer.replace(':', '').lower()} if args.signer else {}
manifest = stage_artifacts(output, version, code, aab, apk, basename=args.name or root.name, extra=extra)
for kind, entry in manifest['files'].items():
    print(f'  {kind}  {entry["filename"]}  {entry["bytes"]:,} bytes  sha256 {entry["sha256"][:16]}...')
print(f'Staged {version} ({code}) in {output}')
