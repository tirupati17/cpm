#!/usr/bin/env python3
"""Reprice subscription base plans, offers and one-time products on Play from a JSON spec (dry run unless --commit).

    cpm play prices --spec ladder.json                       # dry run: reads, converts, prints
    cpm play prices --spec ladder.json --markdown table.md   # also a per-region table
    cpm play prices --spec ladder.json --commit              # apply it

The spec format is in _prices.py: a USD price per base plan, offer and product,
hand-set regions, and optionally the App Store prices from `cpm appstore prices
--out` so a region whose currency matches the App Store territory gets the same
price on both stores. The rest is Play's conversion, rounded to a local ending.

The dry run is read only (convertRegionPrices is a read). It also converts the
spec's USD sanity limits per region and flags any price outside them: Play has
no API for its real per-currency limits, so a price that passes here can still
be refused by the save, which then names the region.

With --commit, per subscription:
  1. refuse if the live base plan bills on a different period than the spec says
     (a billing period cannot be changed on an active base plan);
  2. patch the base plan's regional prices. Existing subscribers stay in their
     legacy price cohort: this command never calls migratePrices;
  3. create or update each offer (allowMissing), then activate it;
  4. point the base plan's legacy-compatible offer at the new one, if asked;
     activate the base plan when the spec says activateBasePlan and it is a draft;
  5. deactivate the offers listed in deactivateOffers;
then one-time products: their purchase option's regional prices. Each product is
read back afterwards.
"""
import argparse
import sys

import _play
import _prices as P
from _products import money, newer_regions_version, show

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--spec', required=True, help='price ladder JSON (its "play" section)')
parser.add_argument('--commit', action='store_true', help='actually change prices and offers')
parser.add_argument('--only', help='comma separated product ids from the spec (default: all)')
parser.add_argument('--show', default='US,IN,GB,DE,BR,RU,JP,ID', help='regions to print per product')
parser.add_argument('--markdown', help='write the per-region table into this Markdown file (its own section)')
parser.add_argument('--package', help='application id (default: PLAY_PACKAGE credential)')
args = parser.parse_args()

spec = P.load_spec(args.spec)
if args.only:
    wanted = set(args.only.split(','))
    spec['subscriptions'] = [s for s in spec['subscriptions'] if s['productId'] in wanted]
    spec['oneTime'] = [s for s in spec['oneTime'] if s['productId'] in wanted]

PACKAGE = _play.package(args.package)
monetization = _play.service().monetization()
from googleapiclient.errors import HttpError       # imported late so --help needs no SDK

_converted = {}


def convert(usd):
    if usd not in _converted:
        _converted[usd] = monetization.convertRegionPrices(packageName=PACKAGE, body={'price': money(usd)}).execute()
    return _converted[usd]


low, high = spec['limits']
limits = (convert(low).get('convertedRegionPrices') if low else None,
          convert(high).get('convertedRegionPrices') if high else None)
show_regions = args.show.split(',')
report, problems, plans = {}, [], []


def other(usd):
    return convert(usd).get('convertedOtherRegionsPrice')


def summary(title, rows):
    print(f'\n{title}: {len(rows)} regions, {sum(1 for r in rows if r["new"] != r["current"])} price changes')
    for r in rows:
        if r['region'] in show_regions:
            extra = f'  offer {show(r["offer"])} ({r["discount"]}% off) [{r["offerSource"]}]' if 'offer' in r else ''
            print(f'  {r["region"]} {show(r["current"]):>16} -> {show(r["new"]):>16} [{r["source"]}]{extra}')
    for r in rows:
        if r['flags']:
            problems.append(f'{title} {r["region"]}: {"; ".join(r["flags"])}')
    report[title] = rows


for sub in spec['subscriptions']:
    pid, bp_id = sub['productId'], sub['basePlanId']
    live = monetization.subscriptions().get(packageName=PACKAGE, productId=pid).execute()
    plan = next((b for b in live.get('basePlans', []) if b['basePlanId'] == bp_id), None)
    if not plan:
        sys.exit(f'{pid} has no base plan {bp_id}. Create it in the Play Console (or name another).')
    period = (plan.get('autoRenewingBasePlanType') or {}).get('billingPeriodDuration')
    blocked = sub.get('billingPeriod') and period != sub['billingPeriod']
    if blocked:
        problems.append(f'{pid}/{bp_id}: bills every {period}, the spec says {sub["billingPeriod"]}. '
                        'A live base plan\'s period cannot change: add a new base plan with the right '
                        'period, move the app and billing backend to it, then point the spec at it.')
    current = {c['regionCode']: c['price'] for c in plan.get('regionalConfigs', [])}
    rows = P.plan_prices(current, convert(sub['usd']), sub['regionPrices'], spec['match'],
                         sub.get('matchIos'), 'list', limits)
    offers = {o['offerId']: o for o in monetization.subscriptions().basePlans().offers().list(
        packageName=PACKAGE, productId=pid, basePlanId=bp_id).execute().get('subscriptionOffers', [])}
    for offer in sub.get('offers') or []:
        offer_rows = P.plan_prices(current, convert(offer['usd']), offer['regionPrices'], spec['match'],
                                   offer.get('matchIos'), 'intro', limits)
        P.add_offer(rows, offer_rows, offer, P.amount(money(offer['usd'])) / P.amount(money(sub['usd'])))
    for keep in sub.get('keepOffers') or []:
        state = offers.get(keep, {}).get('state', 'missing')
        print(f'{pid}/{bp_id}: keeps offer {keep} ({state})')
    summary(f'{pid}/{bp_id}', rows)
    if period:
        print(f'  billing period {period}' + ('  <- DOES NOT MATCH THE SPEC' if blocked else ''))
    plans.append(('sub', sub, live, plan, rows, offers, blocked))

for product in spec['oneTime']:
    pid = product['productId']
    live = monetization.onetimeproducts().get(packageName=PACKAGE, productId=pid).execute()
    option_id = product.get('purchaseOptionId') or pid
    option = next((o for o in live.get('purchaseOptions', []) if o['purchaseOptionId'] == option_id), None)
    if not option:
        sys.exit(f'{pid} has no purchase option {option_id}.')
    current = {c['regionCode']: c['price'] for c in option.get('regionalPricingAndAvailabilityConfigs', [])
               if c.get('price')}
    rows = P.plan_prices(current, convert(product['usd']), product['regionPrices'], spec['match'],
                         product.get('matchIos'), 'list', limits)
    summary(f'{pid}/{option_id}', rows)
    plans.append(('one', product, live, option, rows, None, False))

if problems:
    print('\nFlags:')
    for line in problems:
        print('  ' + line)
if args.markdown:
    from cpmkit.mdsection import write_section
    write_section(args.markdown, 'play-prices', '## Google Play\n\n' + P.markdown(report))
    print(f'\nwrote {args.markdown}')
if not args.commit:
    print('\nDRY RUN. Nothing sent. Re-run with --commit.')
    sys.exit(0)

# -- commit ----------------------------------------------------------------------------
version = spec['regionsVersion']
failed = []


def with_regions_version(call):
    """Play names the regions version it wants only in the error for a stale one."""
    global version
    try:
        return call(version)
    except HttpError as error:
        latest = newer_regions_version(error.content.decode(errors='ignore'), version)
        if not latest:
            raise
        print(f'  regions version {version} rejected, retrying with {latest}')
        version = latest
        return call(version)


def patch_subscription(body):
    return with_regions_version(lambda v: monetization.subscriptions().patch(
        packageName=PACKAGE, productId=body['productId'], updateMask='basePlans',
        **{'regionsVersion_version': v}, body=body).execute())


for kind, item, live, target, rows, offers, blocked in plans:
    pid = item['productId']
    if kind == 'sub':
        if blocked:
            failed.append(f'{pid}: skipped, billing period does not match the spec')
            continue
        bp_id = item['basePlanId']
        live['basePlans'] = [P.base_plan_body(b, rows, other(item['usd'])) if b['basePlanId'] == bp_id else b
                             for b in live['basePlans']]
        live = patch_subscription(live)
        print(f'{pid}/{bp_id}: base plan prices saved')
        state = next(b for b in live['basePlans'] if b['basePlanId'] == bp_id).get('state')
        if item.get('activateBasePlan') and state != 'ACTIVE':
            monetization.subscriptions().basePlans().activate(
                packageName=PACKAGE, productId=pid, basePlanId=bp_id, body={}).execute()
            print(f'  base plan {bp_id} activated (was {state})')
        offers_api = monetization.subscriptions().basePlans().offers()
        for offer in item.get('offers') or []:
            body = P.offer_body(PACKAGE, pid, bp_id, offer, rows, other(offer['usd']))
            saved = with_regions_version(lambda v: offers_api.patch(
                packageName=PACKAGE, productId=pid, basePlanId=bp_id, offerId=offer['offerId'], allowMissing=True,
                updateMask='phases,targeting,regionalConfigs,otherRegionsConfig',
                **{'regionsVersion_version': v}, body=body).execute())
            if saved.get('state') != 'ACTIVE':
                offers_api.activate(packageName=PACKAGE, productId=pid, basePlanId=bp_id,
                                    offerId=offer['offerId'], body={}).execute()
            print(f'  offer {offer["offerId"]} saved and active')
        legacy = item.get('legacyCompatibleOfferId')
        if legacy:
            for b in live['basePlans']:
                if b['basePlanId'] == bp_id:
                    b['autoRenewingBasePlanType']['legacyCompatibleSubscriptionOfferId'] = legacy
            live = patch_subscription(live)
            print(f'  legacy-compatible offer -> {legacy}')
        for offer_id in item.get('deactivateOffers') or []:
            if offers.get(offer_id, {}).get('state') == 'ACTIVE':
                offers_api.deactivate(packageName=PACKAGE, productId=pid, basePlanId=bp_id,
                                      offerId=offer_id, body={}).execute()
                print(f'  offer {offer_id} deactivated')
        check = monetization.subscriptions().get(packageName=PACKAGE, productId=pid).execute()
        plan = next(b for b in check['basePlans'] if b['basePlanId'] == bp_id)
        live_prices = {c['regionCode']: c['price'] for c in plan['regionalConfigs']}
    else:
        option_id = target['purchaseOptionId']
        live['purchaseOptions'] = [P.one_time_option(o, rows, other(item['usd'])) if o['purchaseOptionId'] == option_id
                                   else o for o in live['purchaseOptions']]
        with_regions_version(lambda v: monetization.onetimeproducts().patch(
            packageName=PACKAGE, productId=pid, updateMask='purchaseOptions',
            **{'regionsVersion_version': v}, body=live).execute())
        print(f'{pid}/{option_id}: prices saved')
        check = monetization.onetimeproducts().get(packageName=PACKAGE, productId=pid).execute()
        option = next(o for o in check['purchaseOptions'] if o['purchaseOptionId'] == option_id)
        live_prices = {c['regionCode']: c.get('price') for c in option['regionalPricingAndAvailabilityConfigs']}
    off = [r['region'] for r in rows if live_prices.get(r['region']) and
           P.amount(live_prices[r['region']]) != P.amount(r['new'])]
    if off:
        failed.append(f'{pid}: read back differs in {", ".join(off[:20])}')
    else:
        print('  read back: matches the plan')

if failed:
    print('\nNot applied:')
    for line in failed:
        print('  ' + line)
    sys.exit(1)
