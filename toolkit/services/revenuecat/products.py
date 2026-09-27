#!/usr/bin/env python3
"""List the project's products across every app and store (API v2).

    cpm revenuecat products
    cpm revenuecat products --json

store_identifier is the id the store knows (App Store product id, or Play's
`subscription:base-plan` for subscriptions and the bare sku for one-time
products). That string, not the RevenueCat id, is what webhooks carry.
"""
import argparse

import _revenuecat as rc


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cpm revenuecat products', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true', help='print the raw items')
    args = parser.parse_args(argv)

    items = rc.v2_list('/products')
    if args.json:
        rc.dump(items)
        return 0
    rows = [{'store_identifier': p.get('store_identifier', ''), 'type': p.get('type', ''),
             'app': p.get('app_id', ''), 'name': p.get('display_name') or '', 'id': p.get('id', '')}
            for p in sorted(items, key=lambda p: (p.get('app_id') or '', p.get('store_identifier') or ''))]
    print(rc.table(rows, ['store_identifier', 'type', 'app', 'name', 'id']))
    print(f'\n{len(rows)} products')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
