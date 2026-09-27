#!/usr/bin/env python3
"""List offerings, their packages and the products in each (API v2).

    cpm revenuecat offerings
    cpm revenuecat offerings --json

The current offering is marked `*`. It is what `Purchases.getOfferings().current`
returns to apps that do not ask for one by id, and it can be named anything:
do not assume it is called "default".
"""
import argparse

import _revenuecat as rc
from cpmkit import http


def fetch():
    # Ask for packages with their products expanded; fall back to packages alone
    # if this API revision refuses the deeper expand.
    try:
        return rc.v2_list('/offerings', params={'expand': 'items.package.product'})
    except http.ApiError as err:
        if err.status != 400:
            raise
        return rc.v2_list('/offerings', params={'expand': 'items.package'})


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm revenuecat offerings', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true', help='print the raw items')
    args = parser.parse_args(argv)

    offerings = fetch()
    if args.json:
        rc.dump(offerings)
        return 0
    rows = []
    for offering in offerings:
        name = ('* ' if offering.get('is_current') else '  ') + (offering.get('lookup_key') or offering.get('id', ''))
        packages = (offering.get('packages') or {}).get('items') or []
        if not packages:
            rows.append({'offering': name, 'package': '(no packages)', 'products': ''})
        for package in packages:
            products = [(entry.get('product') or {}).get('store_identifier') or (entry.get('product') or {}).get('id', '')
                        for entry in (package.get('products') or {}).get('items') or []]
            rows.append({'offering': name, 'package': package.get('lookup_key') or package.get('id', ''),
                         'products': ', '.join(p for p in products if p) or '?'})
            name = ''
    print(rc.table(rows, ['offering', 'package', 'products']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
