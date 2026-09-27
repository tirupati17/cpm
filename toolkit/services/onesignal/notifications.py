#!/usr/bin/env python3
"""Recent notifications with delivery counts (sent, failed, errored, clicked).

    cpm onesignal notifications
    cpm onesignal notifications --limit 50 --kind api
    cpm onesignal notifications --json

`failed` is devices that unsubscribed or whose token expired; `errored` is
OneSignal or the platform (APNs/FCM) rejecting the send, usually bad
credentials for that platform. Both climbing is worth a look.
"""
import argparse

import _onesignal as os1

KINDS = {'dashboard': 0, 'api': 1, 'automated': 3}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm onesignal notifications', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--limit', type=int, default=20, help='how many (max 50 per page)')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--kind', choices=list(KINDS), help='only those sent from the dashboard, the API, or automations')
    parser.add_argument('--json', action='store_true', help='print the raw API response')
    args = parser.parse_args(argv)

    reply = os1.call('GET', '/notifications', params={
        'app_id': os1.app_id(), 'limit': max(1, min(args.limit, 50)), 'offset': args.offset,
        'kind': KINDS.get(args.kind)})
    if args.json:
        os1.dump(reply)
        return 0
    rows = []
    for n in reply.get('notifications') or []:
        message = os1.text(n.get('headings')) or os1.text(n.get('contents'))
        rows.append({'queued': os1.when(n.get('queued_at')), 'message': message[:48],
                     'sent': n.get('successful', ''), 'failed': n.get('failed', ''),
                     'errored': n.get('errored', ''), 'clicked': n.get('converted', ''),
                     'id': n.get('id', '')})
    print(os1.table(rows, ['queued', 'message', 'sent', 'failed', 'errored', 'clicked', 'id']))
    print(f"\n{len(rows)} of {reply.get('total_count', len(rows))}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
