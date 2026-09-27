#!/usr/bin/env python3
"""Print the app target's MARKETING_VERSION, read from the Xcode project.

    cpm appstore version                       # project and bundle id discovered
    cpm appstore version --bundle-id com.example.App --xcodeproj App.xcodeproj --repo ~/src/app

The app target is the one whose PRODUCT_BUNDLE_IDENTIFIER is exactly the bundle
id (--bundle-id, else ASC_BUNDLE_ID from the credential store). An extension
whose id merely starts with it is not a match, which is the whole point: its
version is the stale one a release overwrites.

Offline: reads project.pbxproj only. Prints one line on stdout.
"""
import argparse
import sys

import _xcode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repo', help='repository root (default: git toplevel of the current directory)')
    # Not --project: the cpm dispatcher takes --project as the credentials project.
    parser.add_argument('--xcodeproj', help='the .xcodeproj, relative to --repo (default: the only one)')
    parser.add_argument('--bundle-id', help='app bundle id (default: ASC_BUNDLE_ID credential)')
    args = parser.parse_args(argv)

    root = _xcode.repo_root(args.repo)
    pbx = _xcode.pbxproj_path(root, args.xcodeproj)
    from _asc import resolve_bundle_id
    bundle_id = resolve_bundle_id(args.bundle_id)
    with open(pbx, encoding='utf-8') as handle:
        version = _xcode.marketing_version(handle.read(), bundle_id)
    if not version:
        _xcode.die(f'no MARKETING_VERSION for {bundle_id} in {pbx}')
    print(version)


if __name__ == '__main__':
    sys.exit(main())
