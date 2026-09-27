#!/usr/bin/env python3
"""Add or remove a "user property is value -> variant" targeting segment on a flag.

    cpm amplitude target <key> --property beta_tester --value true            # dry run
    cpm amplitude target <key> --property beta_tester --value true --commit
    cpm amplitude target <key> --property beta_tester --remove --commit
    cpm amplitude target --property beta_tester --value true                  # which flags have it

Needs AMPLITUDE_MANAGEMENT_KEY. This is how a feature goes to one group first
(beta testers, staff) while everyone else keeps the base rollout: the segment
matches before the rollout percentage is applied.

The property must reach the flag fetch. Remote evaluation matches on the user
properties sent with the fetch (and on the Analytics profile, which lags
ingestion), so the app should pass the property in the Experiment user it
fetches with, not only in an Analytics identify.

A flag that is off serves nobody, segment or not. When the flag is off and its
base rollout is 0%, --commit also switches it on: nobody outside the segment
is affected. When the base rollout is above 0%, switching it on would release
the feature to that share of everyone, so the command refuses and says so.

The segment is named after the property ("<property> = <value>") so a rerun
replaces it instead of adding a second copy, and --remove finds it again.
"""
import argparse

import _amplitude as amp


def segment_name(prop, value):
    return f'{prop} = {value}'


def condition_matches(segment, prop):
    for cond in segment.get('conditions') or []:
        if cond.get('prop') in (prop, f'gp:{prop}'):
            return True
    return False


def ours(segment, prop):
    """The segment this command owns for `prop`, found by name or by its condition."""
    name = segment.get('name') or ''
    return name.startswith(f'{prop} = ') or condition_matches(segment, prop)


def build_segment(prop, value, variant):
    return {
        'name': segment_name(prop, value),
        # Custom user properties are addressed as gp:<name>; built-ins
        # (country, platform, version...) are not, and are not what this is for.
        'conditions': [{'type': 'property', 'prop': f'gp:{prop}', 'op': 'is', 'values': [value]}],
        'percentage': 100,
        'rolloutWeights': {variant: 1},
    }


def variant_keys(flag):
    return [v.get('key') for v in flag.get('variants') or [] if v.get('key')]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm amplitude target', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('key', nargs='?', help='flag key; omit to list the flags that carry the segment')
    parser.add_argument('--property', required=True, help='custom user property, without gp:')
    parser.add_argument('--value', default='true', help='value it must equal (default: true)')
    parser.add_argument('--variant', default='on', help='variant the segment serves (default: on)')
    parser.add_argument('--remove', action='store_true', help='remove the segment instead of adding it')
    parser.add_argument('--commit', action='store_true', help='change it; without this nothing is sent')
    args = parser.parse_args(argv)

    flags = [f for f in amp.all_flags() if not f.get('archived')]

    if not args.key:
        rows = [{'key': f.get('key', ''), 'state': 'ON' if f.get('enabled') else 'off',
                 'rollout': f"{f.get('rolloutPercentage', 0):g}%",
                 'segment': next((s.get('name') for s in f.get('targetSegments') or [] if ours(s, args.property)), '')}
                for f in sorted(flags, key=lambda f: f.get('key') or '')]
        rows = [r for r in rows if r['segment']]
        if not rows:
            print(f'No flag targets {args.property}.')
            return 0
        print(amp.table(rows, ['key', 'state', 'rollout', 'segment']))
        return 0

    found = [f for f in flags if f.get('key') == args.key]
    if not found:
        close = [f.get('key') for f in flags if args.key.lower() in (f.get('key') or '').lower()]
        hint = f" Close: {', '.join(close[:8])}" if close else ''
        raise SystemExit(f'No flag {args.key!r}. Create it in the Amplitude UI first.{hint}')
    flag = found[0]
    segments = list(flag.get('targetSegments') or [])
    kept = [s for s in segments if not ours(s, args.property)]
    enabled = bool(flag.get('enabled'))
    base = flag.get('rolloutPercentage') or 0
    body = {}

    if args.remove:
        if len(kept) == len(segments):
            print(f'{args.key} has no {args.property} segment. Nothing to do.')
            return 0
        body['targetSegments'] = kept
    else:
        variants = variant_keys(flag)
        if variants and args.variant not in variants:
            raise SystemExit(f'{args.key} has no variant {args.variant!r} (it has {", ".join(variants)}). '
                             'Pass --variant.')
        body['targetSegments'] = kept + [build_segment(args.property, args.value, args.variant)]
        if not enabled:
            if base > 0:
                raise SystemExit(f'{args.key} is off with a {base:g}% base rollout. Switching it on for the '
                                 f'segment would also release it to {base:g}% of everyone. Set the rollout to '
                                 '0% in the UI first, then rerun.')
            body['enabled'] = True

    print(f"flag      {flag.get('key')} (id {flag.get('id')})")
    print(f"current   {'ON' if enabled else 'off'}   base rollout {base:g}%   segments "
          f"{[s.get('name') for s in segments] or 'none'}")
    print(f"new       {'ON' if body.get('enabled', enabled) else 'off'}   base rollout {base:g}%   segments "
          f"{[s.get('name') for s in body['targetSegments']] or 'none'}")
    if not flag.get('deployments'):
        print('\nWarning: this flag has no deployment, so no client will see it.')
    if not args.commit:
        print(f"\nDRY RUN. PATCH /api/1/flags/{flag.get('id')} not sent. Re-run with --commit.")
        return 0
    amp.management('PATCH', f"/api/1/flags/{flag.get('id')}", body=body)
    print('\nDone. Apps pick it up on their next flag fetch.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
