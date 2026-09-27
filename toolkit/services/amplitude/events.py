#!/usr/bin/env python3
"""Event totals or unique users over the last N days (Dashboard REST API).

    cpm amplitude events                              # every event type, this week's totals
    cpm amplitude events --event app_opened --event purchase --days 30
    cpm amplitude events --event app_opened --metric uniques --daily
    cpm amplitude events --event app_opened --json

With --event it runs one Event Segmentation query per event (sequentially, the
API rate-limits hard), from N-1 days ago through today, UTC. Today is partial.
For uniques the total is Amplitude's own de-duplicated figure over the whole
range, not the sum of daily uniques. Without --event it lists event types with
the totals Amplitude reports for the current week.

An event name Amplitude has never received comes back as HTTP 400, shown here
as "no such event", which usually means a typo or an event only debug builds
send.
"""
import argparse
import datetime
import json

import _amplitude as amp
from cpmkit import http

METRICS = ['totals', 'uniques', 'avg', 'pct_dau']


def total(data, metric):
    collapsed = data.get('seriesCollapsed') or []
    flat = [c for group in collapsed for c in (group if isinstance(group, list) else [group])]
    if flat:
        return sum(c.get('value') or 0 for c in flat if isinstance(c, dict))
    series = data.get('series') or [[]]
    return sum(series[0]) if metric == 'totals' else None


def segmentation(event, metric, start, end):
    return amp.analytics('/api/2/events/segmentation', params={
        'e': json.dumps({'event_type': event}), 'm': metric, 'start': start, 'end': end, 'i': 1})


def main(argv=None, today=None):
    parser = argparse.ArgumentParser(prog='cpm amplitude events', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--event', action='append', help='event type, repeatable')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--metric', choices=METRICS, default='totals')
    parser.add_argument('--daily', action='store_true', help='also print one column per day')
    parser.add_argument('--json', action='store_true', help='print the raw API responses')
    args = parser.parse_args(argv)
    if args.days < 1:
        raise SystemExit('--days must be at least 1')

    if not args.event:
        reply = amp.analytics('/api/2/events/list')
        if args.json:
            amp.dump(reply)
            return 0
        rows = [{'event': e.get('value') or e.get('name', ''), 'this week': e.get('totals', 0)}
                for e in reply.get('data') or [] if not e.get('deleted') and not e.get('hidden')]
        rows.sort(key=lambda r: -(r['this week'] or 0))
        print(amp.table(rows, ['event', 'this week']))
        print(f'\n{len(rows)} event types. Pass --event <name> --days N for a specific range.')
        return 0

    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    start = today - datetime.timedelta(days=args.days - 1)
    fmt = '%Y%m%d'
    rows, raw, days = [], {}, []
    for event in args.event:
        try:
            reply = segmentation(event, args.metric, start.strftime(fmt), today.strftime(fmt))
        except http.ApiError as err:
            if err.status == 400:
                rows.append({'event': event, args.metric: 'no such event'})
                continue
            raise
        raw[event] = reply
        data = reply.get('data') or {}
        row = {'event': event, args.metric: total(data, args.metric)}
        if args.daily:
            days = [str(x)[5:10] for x in data.get('xValues') or []]
            for label, value in zip(days, (data.get('series') or [[]])[0]):
                row[label] = value
        rows.append(row)
    if args.json:
        amp.dump(raw)
        return 0
    print(f'{args.metric}, {start} to {today} UTC ({args.days} days, today partial)\n')
    print(amp.table(rows, ['event', args.metric] + (days if args.daily else [])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
