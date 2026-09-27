#!/usr/bin/env python3
"""List Experiment feature flags: on/off, rollout, variants, targeting, deployments.

    cpm amplitude flags
    cpm amplitude flags --grep paywall
    cpm amplitude flags --all          # include archived flags
    cpm amplitude flags --json

Needs AMPLITUDE_MANAGEMENT_KEY. A flag reaches an app only if it is ON, has a
rollout above 0% (or a targeting segment that matches), and is attached to the
deployment whose key that app uses. Rows failing one of those are marked `!`.

A flag your code checks but that is missing here is not "off": the SDK returns
the code's local fallback, which is whatever the developer typed.
"""
import argparse

import _amplitude as amp


def rollout(flag):
    value = flag.get('rolloutPercentage')
    return '' if value is None else f'{value:g}%'


def problem(flag):
    if not flag.get('enabled'):
        return ''
    if not flag.get('deployments'):
        return '! no deployment'
    if flag.get('rolloutPercentage') == 0 and not flag.get('targetSegments'):
        return '! 0% rollout'
    return ''


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm amplitude flags', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--grep', help='only flags whose key contains this text')
    parser.add_argument('--all', action='store_true', help='include archived flags')
    parser.add_argument('--json', action='store_true', help='print the raw flags')
    args = parser.parse_args(argv)

    flags = amp.all_flags()
    if not args.all:
        flags = [f for f in flags if not f.get('archived')]
    if args.grep:
        flags = [f for f in flags if args.grep.lower() in (f.get('key') or '').lower()]
    if args.json:
        amp.dump(flags)
        return 0
    rows = [{'key': f.get('key', ''), 'state': 'ON' if f.get('enabled') else 'off', 'rollout': rollout(f),
             'variants': len(f.get('variants') or []), 'segments': len(f.get('targetSegments') or []),
             'deployments': len(f.get('deployments') or []), 'note': problem(f)}
            for f in sorted(flags, key=lambda f: f.get('key') or '')]
    print(amp.table(rows, ['key', 'state', 'rollout', 'variants', 'segments', 'deployments', 'note']))
    on = sum(1 for f in flags if f.get('enabled'))
    print(f'\n{len(rows)} flags, {on} on')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
