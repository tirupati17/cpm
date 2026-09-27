#!/usr/bin/env python3
"""Conversion actions: status, type, origin, primary or not, and how many landed recently.

Imported actions (GA4, Firebase, third-party app analytics) are marked. An
imported action showing 0 recent conversions while the app is selling usually
means the chain upstream is broken (the event never reached GA4, or the GA4
property is not linked to this Ads account), not that nobody bought.
"""
import _ads

ACTIONS = ("SELECT conversion_action.id, conversion_action.name, conversion_action.status, "
           "conversion_action.type, conversion_action.category, conversion_action.origin, "
           "conversion_action.primary_for_goal FROM conversion_action "
           "WHERE conversion_action.status != 'REMOVED' ORDER BY conversion_action.name")
RECENT = ("SELECT segments.conversion_action, metrics.all_conversions FROM customer "
          "WHERE segments.date BETWEEN '{start}' AND '{end}'")
IMPORTED = ('GOOGLE_ANALYTICS', 'FIREBASE', 'THIRD_PARTY_APP_ANALYTICS', 'UNIVERSAL_ANALYTICS')


def run(argv, client=None):
    p = _ads.parser(__doc__)
    p.add_argument('--days', type=int, default=30, help='window for the recent count (default 30)')
    args = p.parse_args(argv)
    client = client or _ads.Client(args.customer)
    start, end = _ads.date_range(args.days)
    actions = client.search(ACTIONS)
    recent = {}
    for row in client.search(RECENT.format(start=start, end=end)):
        name = _ads.pick(row, 'segments.conversion_action')  # customers/<id>/conversionActions/<id>
        action_id = str(name).rsplit('/', 1)[-1]
        recent[action_id] = recent.get(action_id, 0.0) + float(_ads.pick(row, 'metrics.all_conversions') or 0)
    rows = []
    for row in actions:
        aid = _ads.pick(row, 'conversion_action.id')
        kind = _ads.pick(row, 'conversion_action.type')
        rows.append({
            'id': aid, 'name': _ads.pick(row, 'conversion_action.name'),
            'status': _ads.pick(row, 'conversion_action.status'), 'type': kind,
            'category': _ads.pick(row, 'conversion_action.category'),
            'primary': 'yes' if _ads.pick(row, 'conversion_action.primary_for_goal') is True else 'no',
            'imported': 'yes' if str(kind).startswith(IMPORTED) else '',
            'recent': f'{recent.get(str(aid), 0.0):.1f}'})
    print(f'customer {client.customer}   recent = all conversions {start} .. {end}\n')
    print(_ads.google.table(rows, ['id', 'name', 'status', 'type', 'category', 'primary', 'imported', 'recent'],
                            ['ID', 'NAME', 'STATUS', 'TYPE', 'CATEGORY', 'PRIMARY', 'IMPORTED', 'RECENT']))
    return 0


if __name__ == '__main__':
    _ads.main(run)
