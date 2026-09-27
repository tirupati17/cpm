#!/usr/bin/env python3
"""Turn one Experiment flag on or off, leaving its rollout, variants and targeting alone.

    cpm amplitude flag <key> --on             # dry run: shows current and new state
    cpm amplitude flag <key> --off --commit

Needs AMPLITUDE_MANAGEMENT_KEY. The key is looked up to find the flag's id,
and only `enabled` is patched. Creating flags, editing variants and changing
rollout stay in the Amplitude UI on purpose: collapsing an A/B test to on/off
from a terminal is how experiments get ruined.

Clients see the change on their next flag fetch, not instantly. Local
evaluation SDKs poll (typically every 30-60s); remote evaluation apps usually
fetch at launch.
"""
import argparse

import _amplitude as amp


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm amplitude flag', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('key')
    state = parser.add_mutually_exclusive_group(required=True)
    state.add_argument('--on', action='store_true')
    state.add_argument('--off', action='store_true')
    parser.add_argument('--commit', action='store_true', help='change it; without this nothing is sent')
    args = parser.parse_args(argv)

    flags = amp.all_flags()
    found = [f for f in flags if f.get('key') == args.key]
    if not found:
        close = [f.get('key') for f in flags if args.key.lower() in (f.get('key') or '').lower()]
        hint = f" Close: {', '.join(close[:8])}" if close else ''
        raise SystemExit(f'No flag {args.key!r}. A flag that does not exist in Amplitude reads as the '
                         f'code\'s local fallback, so create it in the UI first.{hint}')
    flag = found[0]
    want = bool(args.on)
    now = bool(flag.get('enabled'))
    print(f"flag     {flag.get('key')} (id {flag.get('id')})")
    print(f"current  {'ON' if now else 'off'}   rollout {flag.get('rolloutPercentage', '?')}%   "
          f"deployments {len(flag.get('deployments') or [])}")
    print(f"new      {'ON' if want else 'off'}")
    if now == want:
        print('\nAlready in that state. Nothing to do.')
        return 0
    if want and not flag.get('deployments'):
        print('\nWarning: this flag has no deployment, so no client will see it even when ON.')
    if not args.commit:
        print(f"\nDRY RUN. PATCH /api/1/flags/{flag.get('id')} {{\"enabled\": {str(want).lower()}}} not sent. "
              'Re-run with --commit.')
        return 0
    amp.management('PATCH', f"/api/1/flags/{flag.get('id')}", body={'enabled': want})
    print('\nDone. Apps pick it up on their next flag fetch.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
