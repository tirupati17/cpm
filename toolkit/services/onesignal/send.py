#!/usr/bin/env python3
"""Send a push to users (external_id), a segment, or subscription ids.

    cpm onesignal send --external-id <uid> --title "Hi" --body "..."             # dry run
    cpm onesignal send --external-id <uid1>,<uid2> --body "..." --url myapp://x --commit
    cpm onesignal send --segment "Total Subscriptions" --body "..." --commit
    cpm onesignal send --subscription <subscription-id> --body "..." --data kind=test --commit

Pick exactly one audience. The dry run prints the full request body and sends
nothing. external_id only reaches a device whose app called
OneSignal.login(<that exact id>); ids are case-sensitive. Each request carries
an idempotency_key, so OneSignal drops an accidental resend of the same call.

A 200 is not proof of delivery: OneSignal answers 200 with an empty id and an
`errors` list when nobody matched (for example "All included players are not
subscribed"). This command treats that as a failure and exits 2.
"""
import argparse
import json
import sys
import uuid

import _onesignal as os1

BATCH = 2000  # aliases per request; larger lists are split


def split(values):
    return [v.strip() for value in values or [] for v in value.split(',') if v.strip()]


def build(args, app_id):
    base = {'app_id': app_id, 'target_channel': 'push', 'contents': {'en': args.body}}
    if args.title:
        base['headings'] = {'en': args.title}
    if args.url:
        base['url'] = args.url
    data = {}
    for pair in args.data or []:
        if '=' not in pair:
            raise SystemExit(f'--data wants key=value, not {pair!r}')
        key, value = pair.split('=', 1)
        data[key] = value
    if args.data_json:
        try:
            data.update(json.loads(args.data_json))
        except ValueError as err:
            raise SystemExit(f'--data-json is not JSON: {err}') from None
    if data:
        base['data'] = data
    if args.send_after:
        base['send_after'] = args.send_after

    external, segments, subs = split(args.external_id), split(args.segment), split(args.subscription)
    if sum(bool(x) for x in (external, segments, subs)) != 1:
        raise SystemExit('Pick exactly one audience: --external-id, --segment or --subscription.')
    if segments:
        return [dict(base, included_segments=segments)]
    field = 'include_aliases' if external else 'include_subscription_ids'
    ids = external or subs
    payloads = []
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        payloads.append(dict(base, **({field: {'external_id': chunk}} if external else {field: chunk})))
    return payloads


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm onesignal send', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--external-id', action='append', help='external_id(s), comma separated or repeated')
    parser.add_argument('--segment', action='append', help='segment name(s) as shown in the dashboard')
    parser.add_argument('--subscription', action='append', help='subscription id(s)')
    parser.add_argument('--title', help='heading (optional on iOS and Android)')
    parser.add_argument('--body', required=True, help='message text')
    parser.add_argument('--url', help='URL or deep link opened on tap')
    parser.add_argument('--data', action='append', help='custom data key=value, repeatable')
    parser.add_argument('--data-json', help='custom data as a JSON object')
    parser.add_argument('--send-after', help='schedule, e.g. "2026-10-01 09:00:00 GMT+0000"')
    parser.add_argument('--commit', action='store_true', help='send; without this nothing leaves the machine')
    parser.add_argument('--json', action='store_true', help='print the raw API responses')
    args = parser.parse_args(argv)

    payloads = build(args, os1.app_id())
    for payload in payloads:
        payload['idempotency_key'] = str(uuid.uuid4())
    if not args.commit:
        for payload in payloads:
            print('POST /notifications')
            os1.dump(payload)
        print(f'\nDRY RUN. {len(payloads)} request(s), nothing sent. Re-run with --commit.')
        return 0

    failed = False
    for payload in payloads:
        reply = os1.call('POST', '/notifications', body=payload)
        if args.json:
            os1.dump(reply)
        errors = reply.get('errors') if isinstance(reply, dict) else None
        if not (isinstance(reply, dict) and reply.get('id')) or errors:
            failed = True
            print(f'Not delivered: {json.dumps(errors or reply, ensure_ascii=False)}', file=sys.stderr)
            continue
        recipients = reply.get('recipients')
        print(f"sent {reply['id']}" + (f'  recipients {recipients}' if recipients is not None else ''))
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
