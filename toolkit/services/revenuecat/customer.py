#!/usr/bin/env python3
"""One customer: active entitlements, subscriptions and one-time purchases (API v2).

    cpm revenuecat customer <app_user_id>
    cpm revenuecat customer <app_user_id> --json

The id is the app user id your app passed to RevenueCat (or the $RCAnonymousID
it generated). It is matched exactly, so `ABC` and `abc` are two customers.
Entitlements granted by hand (promotional) show up here like purchased ones.
"""
import argparse

import _revenuecat as rc
from cpmkit import http


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm revenuecat customer', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('app_user_id')
    parser.add_argument('--json', action='store_true', help='print the raw API responses')
    args = parser.parse_args(argv)

    base = f'/customers/{rc.quote(args.app_user_id)}'
    try:
        customer = rc.v2('GET', base)
    except http.ApiError as err:
        if err.status == 404:
            raise SystemExit(f'No customer {args.app_user_id!r} in this project. App user ids are '
                             'case-sensitive; check the exact id the app logged in with.') from None
        raise
    subscriptions = rc.v2_list(base + '/subscriptions')
    purchases = rc.v2_list(base + '/purchases')
    if args.json:
        rc.dump({'customer': customer, 'subscriptions': subscriptions, 'purchases': purchases})
        return 0

    names = {e.get('id'): e.get('lookup_key') or e.get('id') for e in rc.entitlements()}
    products = {p.get('id'): p.get('store_identifier') or p.get('id') for p in rc.v2_list('/products')}

    print(f"customer   {customer.get('id', args.app_user_id)}")
    print(f"first seen {rc.when(customer.get('first_seen_at'))}")
    print(f"last seen  {rc.when(customer.get('last_seen_at'))}")
    active = (customer.get('active_entitlements') or {}).get('items') or []
    print(f'\nactive entitlements ({len(active)})')
    if active:
        print(rc.table([{'entitlement': names.get(e.get('entitlement_id'), e.get('entitlement_id')),
                         'expires': rc.when(e.get('expires_at')) or 'never'} for e in active],
                       ['entitlement', 'expires']))
    print(f'\nsubscriptions ({len(subscriptions)})')
    if subscriptions:
        print(rc.table([{'product': products.get(s.get('product_id'), s.get('product_id')),
                         'store': s.get('store', ''), 'status': s.get('status', ''),
                         'access': 'yes' if s.get('gives_access') else 'no',
                         'renewal': s.get('auto_renewal_status', ''),
                         'period ends': rc.when(s.get('current_period_ends_at'))} for s in subscriptions],
                       ['product', 'store', 'status', 'access', 'renewal', 'period ends']))
    print(f'\none-time purchases ({len(purchases)})')
    if purchases:
        print(rc.table([{'product': products.get(p.get('product_id'), p.get('product_id')),
                         'store': p.get('store', ''), 'status': p.get('status', ''),
                         'purchased': rc.when(p.get('purchased_at'))} for p in purchases],
                       ['product', 'store', 'status', 'purchased']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
