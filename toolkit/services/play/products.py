#!/usr/bin/env python3
"""Create or update one-time in-app products on Play from a JSON spec (dry run unless --commit).

    cpm play products --spec play-products.json            # dry run: prints what would be sent
    cpm play products --spec play-products.json --commit   # creates or updates on Play
    cpm play products --spec play-products.json --only coins_100

The spec format is in _products.py (and the play-release skill): a USD base
price converted by Play for every region, optional hand-set prices per region
("24 INR"), and optional lower prices for named region groups.

The dry run still calls Play's price conversion (read only) so the regional
prices it prints are the ones that would be sent. With --commit each product is
saved with allowMissing (create or update), its purchase option is activated if
it is not already, and the saved state is read back.

Product ids are a contract with whatever grants the purchase (your app, or a
billing backend such as RevenueCat): change them there first, never only here.
"""
import argparse

import _play
from _products import load_spec, money, newer_regions_version, product_body, regional_configs, show

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--spec', required=True, help='product spec JSON file')
parser.add_argument('--commit', action='store_true', help='actually create/update; without it nothing changes')
parser.add_argument('--only', help='comma separated product ids from the spec (default: all)')
parser.add_argument('--show-regions', default='US,IN,GB,DE,BR,PK,NG',
                    help='regions to print per product (default US,IN,GB,DE,BR,PK,NG)')
parser.add_argument('--package', help='application id (default: PLAY_PACKAGE credential)')
args = parser.parse_args()

version, groups, products = load_spec(args.spec)
if args.only:
    wanted = set(args.only.split(','))
    unknown = wanted - {p['productId'] for p in products}
    if unknown:
        raise SystemExit(f'Not in the spec: {", ".join(sorted(unknown))}')
    products = [p for p in products if p['productId'] in wanted]

PACKAGE = _play.package(args.package)
monetization = _play.service().monetization()
from googleapiclient.errors import HttpError       # imported late so --help needs no SDK


def convert(price):
    return monetization.convertRegionPrices(packageName=PACKAGE, body={'price': money(price)}).execute()


def save(body, regions_version):
    """Create or update. Play names the regions version it wants only in the
    error for a stale one, so a mismatch is retried once with that value."""
    try:
        return monetization.onetimeproducts().patch(
            packageName=PACKAGE, productId=body['productId'], allowMissing=True,
            updateMask='listings,purchaseOptions,taxAndComplianceSettings',
            **{'regionsVersion_version': regions_version}, body=body).execute()
    except HttpError as error:
        latest = newer_regions_version(error.content.decode(errors='ignore'), regions_version)
        if not latest:
            raise
        print(f'  regions version {regions_version} rejected, retrying with {latest}')
        return save(body, latest)


def activate(product_id, option_id):
    monetization.onetimeproducts().purchaseOptions().batchUpdateStates(
        packageName=PACKAGE, productId=product_id, body={'requests': [{'activatePurchaseOptionRequest': {
            'packageName': PACKAGE, 'productId': product_id, 'purchaseOptionId': option_id}}]}).execute()


for product in products:
    pid = product['productId']
    converted = convert(product['price'])
    group_prices = {g: convert(p) for g, p in product.get('groupPrices', {}).items()}
    configs = regional_configs(converted, product.get('regionPrices'), group_prices, groups)
    body = product_body(PACKAGE, product, configs, converted.get('convertedOtherRegionsPrice', {}))
    by_region = {c['regionCode']: c['price'] for c in configs}
    grouped = {g: sorted(r for r in by_region if r in groups[g]) for g in group_prices}
    print(f'{pid}: {len(configs)} regions  '
          + '  '.join(f'{r} {show(by_region[r])}' for r in args.show_regions.split(',') if r in by_region)
          + ''.join(f'  | {g} in {len(rs)} regions' for g, rs in grouped.items()))
    if not args.commit:
        continue
    result = save(body, version)
    option = result.get('purchaseOptions', [{}])[0]
    if option.get('state') != 'ACTIVE':
        activate(pid, option['purchaseOptionId'])
    # Read the product back rather than trusting the save response.
    option = monetization.onetimeproducts().get(packageName=PACKAGE, productId=pid).execute()['purchaseOptions'][0]
    print(f'  saved: state={option.get("state")} option={option.get("purchaseOptionId")}')
    if option.get('state') != 'ACTIVE':
        raise SystemExit(f'{pid} is saved but not ACTIVE. Check the console.')

if not args.commit:
    print('\nDRY RUN. Nothing sent. Re-run with --commit.')
