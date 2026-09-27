#!/usr/bin/env python3
"""Campaigns with status, daily budget, and cost, clicks and conversions for the last N days.

Removed campaigns are hidden. The window ends yesterday, since today is incomplete.
"""
import _ads

LIST = ("SELECT campaign.id, campaign.name, campaign.status, campaign.serving_status, "
        "campaign.advertising_channel_type, campaign_budget.amount_micros, "
        "campaign_budget.explicitly_shared, customer.currency_code "
        "FROM campaign WHERE campaign.status != 'REMOVED' ORDER BY campaign.name")
STATS = ("SELECT campaign.id, metrics.cost_micros, metrics.clicks, metrics.impressions, metrics.conversions "
         "FROM campaign WHERE segments.date BETWEEN '{start}' AND '{end}' AND campaign.status != 'REMOVED'")


def run(argv, client=None):
    p = _ads.parser(__doc__)
    p.add_argument('--days', type=int, default=7, help='how many days of metrics (default 7)')
    args = p.parse_args(argv)
    client = client or _ads.Client(args.customer)
    start, end = _ads.date_range(args.days)
    # Two queries: a date-filtered metrics query drops campaigns with no activity,
    # and a paused campaign with zero spend is exactly the one you want to see.
    campaigns = client.search(LIST)
    stats = {}
    for row in client.search(STATS.format(start=start, end=end)):
        cid = _ads.pick(row, 'campaign.id')
        total = stats.setdefault(cid, {'cost': 0, 'clicks': 0, 'impr': 0, 'conv': 0.0})
        total['cost'] += int(_ads.pick(row, 'metrics.cost_micros') or 0)
        total['clicks'] += int(_ads.pick(row, 'metrics.clicks') or 0)
        total['impr'] += int(_ads.pick(row, 'metrics.impressions') or 0)
        total['conv'] += float(_ads.pick(row, 'metrics.conversions') or 0)
    currency = _ads.pick(campaigns[0], 'customer.currency_code') if campaigns else ''
    rows = []
    for row in campaigns:
        cid = _ads.pick(row, 'campaign.id')
        total = stats.get(cid, {'cost': 0, 'clicks': 0, 'impr': 0, 'conv': 0.0})
        shared = ' (shared)' if _ads.pick(row, 'campaign_budget.explicitly_shared') is True else ''
        rows.append({
            'id': cid, 'name': _ads.pick(row, 'campaign.name'), 'status': _ads.pick(row, 'campaign.status'),
            'serving': _ads.pick(row, 'campaign.serving_status'),
            'type': _ads.pick(row, 'campaign.advertising_channel_type'),
            'budget': _ads.money(_ads.pick(row, 'campaign_budget.amount_micros')) + shared,
            'cost': _ads.money(total['cost']), 'clicks': total['clicks'], 'impr': total['impr'],
            'conv': f"{total['conv']:.1f}"})
    print(f'customer {client.customer}   {start} .. {end}   amounts in {currency or "account currency"}\n')
    print(_ads.google.table(rows, ['id', 'name', 'status', 'serving', 'type', 'budget', 'cost',
                                   'clicks', 'impr', 'conv'],
                            ['ID', 'NAME', 'STATUS', 'SERVING', 'TYPE', 'BUDGET/DAY', 'COST',
                             'CLICKS', 'IMPR', 'CONV']))
    return 0


if __name__ == '__main__':
    _ads.main(run)
