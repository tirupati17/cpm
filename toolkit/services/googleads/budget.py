#!/usr/bin/env python3
"""Set a campaign's daily budget, in account currency units (dry run unless --commit).

  cpm googleads budget "Brand search" 25        # 25.00 per day
A shared budget feeds several campaigns, so changing it changes all of them;
that needs --shared-ok. Amounts round to the nearest cent (10,000 micros).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import _ads


def _amount(text):
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(text) from None


def run(argv, client=None):
    p = _ads.parser(__doc__)
    p.add_argument('campaign', help='campaign id or exact name')
    p.add_argument('amount', type=_amount, help='new daily budget, e.g. 25 or 12.50')
    p.add_argument('--shared-ok', action='store_true',
                   help='allow changing a budget shared by several campaigns')
    _ads.write_args(p)
    args = p.parse_args(argv)
    if args.amount <= 0:
        raise SystemExit('The amount must be above zero. Use `cpm googleads pause` to stop a campaign.')
    micros = int(args.amount.quantize(Decimal('0.01'), ROUND_HALF_UP) * 100) * 10_000
    client = client or _ads.Client(args.customer)
    row = _ads.find_campaign(client, args.campaign)
    name, cid = _ads.pick(row, 'campaign.name'), _ads.pick(row, 'campaign.id')
    budget = _ads.pick(row, 'campaign_budget.resource_name')
    current = int(_ads.pick(row, 'campaign_budget.amount_micros') or 0)
    refs = int(_ads.pick(row, 'campaign_budget.reference_count') or 1)
    shared = _ads.pick(row, 'campaign_budget.explicitly_shared') is True or refs > 1
    if shared and not args.shared_ok:
        raise SystemExit(f'{name} uses a shared budget ({refs} campaigns). Changing it changes all of them. '
                         'Re-run with --shared-ok if that is what you want.')
    if micros == current:
        print(f'{name} ({cid}) already has a daily budget of {_ads.money(current)}. Nothing to do.')
        return 0
    currency = _ads.pick(row, 'customer.currency_code')
    operation = {'update': {'resourceName': budget, 'amountMicros': str(micros)}, 'updateMask': 'amount_micros'}
    _ads.apply(client, 'campaignBudgets', operation, args,
               f'{name} ({cid}) daily budget: {_ads.money(current)} -> {_ads.money(micros)} {currency}'.rstrip())
    return 0


if __name__ == '__main__':
    _ads.main(run)
