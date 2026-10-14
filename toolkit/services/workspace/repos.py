#!/usr/bin/env python3
"""List, check or clone the workspace's independent repositories from .cpm-repos.

    cpm workspace repos list
    cpm workspace repos check
    cpm workspace repos clone            # preview missing folders
    cpm workspace repos clone --commit   # clone missing repos; leave existing work untouched

Private repositories need Git authentication supplied by the environment.
This never rewrites a checkout, copies app source into the parent Git repo,
creates shortcuts, installs app dependencies or publishes a release.
"""
import argparse
import json
from cpmkit.workspace import find_root, read_repos, state, clone_missing


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['list', 'check', 'clone'])
    parser.add_argument('--root')
    parser.add_argument('--only', nargs='+', help='Limit to these project IDs')
    parser.add_argument('--commit', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        root = find_root(args.root)
        repos = read_repos(root)
        if args.only:
            unknown = set(args.only) - {r.name for r in repos}
            if unknown: raise ValueError('Unknown project IDs: ' + ', '.join(sorted(unknown)))
            repos = [r for r in repos if r.name in args.only]
        states = clone_missing(root, repos, args.commit) if args.action == 'clone' else [state(root, r) for r in repos]
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    if args.json:
        print(json.dumps({'workspace': str(root), 'repos': states}, indent=2))
    else:
        for item in states:
            print(f"{item['name']:<26} {item['state']:<12} {item['path']}" +
                  (f" ({item['branch']}, {item['dirty']} changes)" if item['state'] == 'ready' else ''))
        if args.action == 'clone' and not args.commit:
            print('Dry run. Add --commit to clone missing repositories into real folders.')
    return int(args.action == 'check' and any(s['state'] != 'ready' for s in states))


if __name__ == '__main__':
    raise SystemExit(main())
