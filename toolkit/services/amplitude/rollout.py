#!/usr/bin/env python3
"""Roll out a simple on/off flag. Refuses experiments and targeted segments.

    cpm amplitude rollout exercise_immersive_enabled --percent 100
    cpm amplitude rollout exercise_immersive_enabled --percent 100 --commit

Dry run by default. Preserve deployments and variants, check concurrent edits,
and verify the final state. Use the dashboard for experiments or targeting.
"""
import argparse
import _amplitude as amp


def check(flag):
    if [v.get('key') for v in flag.get('variants', [])] != ['on']:
        raise SystemExit('Only a single on variant is supported; use the dashboard for experiments.')
    if flag.get('targetSegments'):
        raise SystemExit('Targeted segments require the dashboard; refusing to change their reach.')
    if not flag.get('deployments'):
        raise SystemExit('No deployment attached; attach the intended deployment first.')
    if flag.get('rolloutWeights') not in (None, {}, {'on': 1}, {'on': 100}):
        raise SystemExit('Unexpected variant weights; use the dashboard.')


def signature(flag):
    return {k: flag.get(k) for k in ('enabled', 'rolloutPercentage', 'rolloutWeights',
                                   'deployments', 'variants', 'targetSegments')}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('key')
    p.add_argument('--percent', type=int, required=True, choices=range(101), metavar='0..100')
    p.add_argument('--commit', action='store_true')
    args = p.parse_args(argv)
    flag = next((f for f in amp.all_flags() if f.get('key') == args.key), None)
    if flag is None: raise SystemExit('Flag not found.')
    path = f"/api/1/flags/{flag['id']}"
    before = amp.management('GET', path)
    check(before)
    body = {'enabled': args.percent > 0, 'rolloutPercentage': args.percent}
    print(f"{args.key}: {before.get('enabled')} at {before.get('rolloutPercentage')}% -> {body}")
    if not args.commit:
        print('DRY RUN. No change sent.'); return 0
    current = amp.management('GET', path)
    if signature(current) != signature(before):
        raise SystemExit('Flag changed since inspection; refusing to overwrite a concurrent edit.')
    amp.management('PATCH', path, body=body)
    after = amp.management('GET', path)
    expected = signature(before) | body
    if signature(after) != expected:
        raise SystemExit('Readback differs from the requested rollout; inspect the flag before retrying.')
    print(f"Verified {args.key}: {'ON' if after['enabled'] else 'OFF'} at {after['rolloutPercentage']}%.")
    return 0


if __name__ == '__main__': raise SystemExit(main())
