#!/usr/bin/env python3
"""Overview metrics: MRR, revenue, active subscriptions and trials, customers (API v2).

    cpm revenuecat metrics
    cpm revenuecat metrics --currency EUR
    cpm revenuecat metrics --json

These are the numbers on the dashboard's Overview page, computed by RevenueCat.
Revenue is the last 28 days; active counts are right now. The key needs the
charts_metrics:overview:read permission.
"""
import argparse

import _revenuecat as rc


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm revenuecat metrics', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--currency', help='ISO currency for money metrics (default: the project currency)')
    parser.add_argument('--json', action='store_true', help='print the raw API response')
    args = parser.parse_args(argv)

    data = rc.v2('GET', '/metrics/overview', params={'currency': args.currency})
    if args.json:
        rc.dump(data)
        return 0
    rows = []
    for metric in data.get('metrics') or []:
        value = metric.get('value')
        unit = metric.get('unit') or ''
        shown = f'{value:,.2f}' if isinstance(value, float) and not float(value).is_integer() else (
            f'{int(value):,}' if isinstance(value, (int, float)) else str(value))
        rows.append({'metric': metric.get('name') or metric.get('id'), 'id': metric.get('id', ''),
                     'value': f'{unit}{shown}' if unit == '$' else shown,
                     'period': metric.get('period', '')})
    if not rows:
        raise SystemExit('RevenueCat returned no metrics. Run with --json to see the response.')
    print(rc.table(rows, ['metric', 'value', 'period', 'id']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
