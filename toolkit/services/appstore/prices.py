#!/usr/bin/env python3
"""Reprice subscriptions, intro offers and in-app purchases from a JSON spec (dry run unless --commit).

    cpm appstore prices --spec ladder.json                       # dry run: reads, computes, prints
    cpm appstore prices --spec ladder.json --out ios-prices.json # also save the computed prices
    cpm appstore prices --spec ladder.json --markdown table.md   # and a per-territory table
    cpm appstore prices --spec ladder.json --commit              # apply it

The spec format is in _prices.py. In short: a base price in one territory that
Apple equalizes everywhere else, hand-set prices that win over equalization,
an optional intro offer (exact prices or the point nearest a fraction of the
list price), and in-app purchase price schedules (manual + automatic).

The dry run is read only: it fetches the current prices, the equalizations and
the price points, and prints exactly which point each territory would get. The
--out file is what `cpm play prices --match` reads to price Play the same way.

With --commit, in this order and per product:
  1. subscription prices, one POST per changed territory, with
     preserveCurrentPrice from the spec (true keeps existing subscribers' price);
  2. the instalment plan's prices, if the spec names one;
  3. intro offers. App Store Connect allows one intro offer per territory and
     refuses an overlapping one, so each territory tries the new offer first and,
     only when that is refused as a conflict, deletes the old offer and creates
     the new one straight after (the territory is without an offer for one call).
     If that second create also fails, the old offer is put back and the run
     goes on, listing the territory at the end. Old offers that did not block the
     new one are deleted after it exists.
  4. in-app purchase price schedules (one POST replaces the whole schedule).
Then the prices are read back and compared with the plan.
"""
import argparse
import datetime
import json
import sys

from _asc import ASC, PROG, resolve_bundle_id
import _prices as P
from cpmkit.territories import iso2

parser = argparse.ArgumentParser(prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--spec', required=True, help='price ladder JSON (its "appstore" section)')
parser.add_argument('--commit', action='store_true', help='actually change prices and offers')
parser.add_argument('--only', help='comma separated product ids from the spec (default: all)')
parser.add_argument('--show', default='USA,IND,GBR,DEU,BRA,RUS,JPN,IDN', help='territories to print per product')
parser.add_argument('--out', help='write the computed prices as JSON (for cpm play prices --match)')
parser.add_argument('--markdown', help='write the per-territory table into this Markdown file (its own section)')
parser.add_argument('--bundle-id', help='app bundle id (default: ASC_BUNDLE_ID credential)')
args = parser.parse_args()

subs_spec, iaps_spec = P.load_spec(args.spec)
if args.only:
    wanted = set(args.only.split(','))
    unknown = wanted - {s['productId'] for s in subs_spec + iaps_spec}
    if unknown:
        sys.exit(f'{PROG}: not in the spec: {", ".join(sorted(unknown))}')
    subs_spec = [s for s in subs_spec if s['productId'] in wanted]
    iaps_spec = [s for s in iaps_spec if s['productId'] in wanted]

asc = ASC()
app_id, app_name = asc.app(resolve_bundle_id(args.bundle_id))
today = datetime.date.today().isoformat()
show = args.show.split(',')
print(f'{app_name} ({app_id})')

currencies = {t['id']: t['attributes'].get('currency', '') for t in asc.get_all('/v1/territories?limit=200')}

subscriptions = {s['attributes']['productId']: s
                 for g in asc.get_all(f'/v1/apps/{app_id}/subscriptionGroups?limit=200')
                 for s in asc.get_all(f'/v1/subscriptionGroups/{g["id"]}/subscriptions?limit=200')}
iaps = {p['attributes']['productId']: p for p in asc.get_all(f'/v1/apps/{app_id}/inAppPurchasesV2?limit=200')
        } if iaps_spec else {}

products, kinds, work = {}, {}, []


def points_for(path_prefix, territories):
    """Price points of a product in the named territories (or all, when None)."""
    query = f'{path_prefix}/pricePoints?include=territory&limit=8000'
    if territories:
        query += '&filter[territory]=' + ','.join(sorted(territories))
    data, _ = asc.get_all_with_included(query)
    return P.index_points(data)


def equalizations(kind, point_id):
    data, _ = asc.get_all_with_included(f'/v1/{kind}/{point_id}/equalizations?include=territory&limit=8000')
    return {t: v[0] for t, v in P.index_points(data).items()}


for spec in subs_spec:
    pid = spec['productId']
    sub = subscriptions.get(pid)
    if not sub:
        sys.exit(f'{PROG}: no subscription {pid!r} in {app_name}')
    sid = sub['id']
    records, included = asc.get_all_with_included(
        f'/v1/subscriptions/{sid}/prices?include=subscriptionPricePoint,territory&limit=200')
    current = P.current_prices(records, included, P.UPFRONT, today)
    plan = spec.get('instalmentPlan')
    instalment = P.current_prices(records, included, plan['planType'], today) if plan else None
    # Every point is needed only to pick an intro price or an instalment price.
    need_all = bool(plan) or bool(spec.get('introOffer') and spec['introOffer'].get('fractionOfList'))
    base_t = spec['basePrice']['territory']
    exact_ts = {base_t, *spec['manualPrices'], *((spec.get('introOffer') or {}).get('prices') or {})}
    points = points_for(f'/v1/subscriptions/{sid}', None if need_all else exact_ts)
    base_id = P.exact(points, base_t, spec['basePrice']['price'], pid)
    manual_ids = {base_t: base_id, **{t: P.exact(points, t, p, pid) for t, p in spec['manualPrices'].items()}}
    equalized = equalizations('subscriptionPricePoints', base_id)
    rows = P.plan_subscription(spec, current, base_id, equalized, manual_ids, points, currencies, instalment)
    products[pid], kinds[pid] = rows, 'subscription'
    offers = None
    if spec.get('introOffer'):
        offers = asc.get_all(f'/v1/subscriptions/{sid}/introductoryOffers?include=subscriptionPricePoint&limit=200')
    work.append(('subscription', spec, sid, rows, offers))

for spec in iaps_spec:
    pid = spec['productId']
    iap = iaps.get(pid)
    if not iap:
        sys.exit(f'{PROG}: no in-app purchase {pid!r} in {app_name}')
    iid = iap['id']
    current = {}
    for kind in ('manualPrices', 'automaticPrices'):
        records, included = asc.get_all_with_included(
            f'/v1/inAppPurchasePriceSchedules/{iid}/{kind}?include=inAppPurchasePricePoint,territory&limit=200')
        current.update(P.current_prices(records, included, None, today))
    points = points_for(f'/v2/inAppPurchases/{iid}', set(spec['prices']))
    manual_ids = {t: P.exact(points, t, p, pid) for t, p in spec['prices'].items()}
    equalized = equalizations('inAppPurchasePricePoints', manual_ids[spec['baseTerritory']])
    rows = P.plan_iap(spec, current, equalized, manual_ids, currencies)
    products[pid], kinds[pid] = rows, 'iap'
    work.append(('iap', spec, iid, rows, manual_ids))

# -- report ----------------------------------------------------------------------------
flagged = []
for pid, rows in products.items():
    changes = sum(1 for r in rows if r.get('change', r.get('list') != r.get('current')))
    print(f'\n{pid}: {len(rows)} territories, {changes} price changes')
    for r in rows:
        if r['territory'] in show:
            extra = ''
            if 'intro' in r:
                extra = f'  intro {P.fmt(r["intro"])}' + (f' ({r["discount"]}% off)' if r.get('discount') is not None else '')
            if 'instalment' in r:
                extra += f'  instalment {P.fmt(r.get("instalmentCurrent"))} -> {P.fmt(r["instalment"])}'
            print(f'  {r["territory"]} {r["currency"]:<4} {P.fmt(r["current"]):>9} -> {P.fmt(r.get("list")):>9}'
                  f' [{r.get("source")}]{extra}')
    for r in rows:
        if r['flags']:
            flagged.append(f'{pid} {r["territory"]}: {"; ".join(r["flags"])}')
if flagged:
    print('\nFlags:')
    for line in flagged:
        print('  ' + line)

if args.out:
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump({'generated': today, 'app': app_name, 'territories': P.export(products, iso2)}, handle, indent=1,
                  sort_keys=True)
    print(f'\nwrote {args.out}')
if args.markdown:
    from cpmkit.mdsection import write_section
    write_section(args.markdown, 'appstore-prices', f'## App Store (computed {today})\n\n' + P.markdown(products, kinds))
    print(f'wrote {args.markdown}')

if not args.commit:
    print('\nDRY RUN. Nothing sent. Re-run with --commit.')
    sys.exit(0)

# -- commit ----------------------------------------------------------------------------
failed = []


def post_price(sid, territory, point_id, preserve, plan_type):
    asc.call('POST', '/v1/subscriptionPrices', P.price_body(sid, territory, point_id, preserve, plan_type))


def apply_intro(sid, spec, rows, offers):
    offer = spec['introOffer']
    old = {}
    for o in offers:
        a = o['attributes']
        if a.get('targetSubscriptionPlanType', P.UPFRONT) not in (None, P.UPFRONT):
            continue
        point = ((o.get('relationships') or {}).get('subscriptionPricePoint') or {}).get('data') or {}
        same = (a['offerMode'] == offer['offerMode'] and a['duration'] == offer['duration']
                and a.get('numberOfPeriods') == offer['numberOfPeriods'])
        old.setdefault(P.territory_of(o), []).append((o, same, point.get('id')))
    created = deleted_first = 0
    for r in rows:
        t = r['territory']
        if r.get('intro') is None:
            continue
        existing = old.get(t, [])
        if any(same and point == r.get('introId') for _, same, point in existing):
            continue
        replaceable = [o for o, same, _ in existing if same or o['attributes']['offerMode'] in offer['replaces']]
        body = P.intro_body(sid, t, offer, r.get('introId'))
        result = asc.call('POST', '/v1/subscriptionIntroductoryOffers', body, ok=(201, 409))
        if result.get('errors'):
            for o in replaceable:
                asc.call('DELETE', f'/v1/subscriptionIntroductoryOffers/{o["id"]}')
            result = asc.call('POST', '/v1/subscriptionIntroductoryOffers', body, ok=(201, 409))
            if result.get('errors'):
                for o in replaceable:      # put the old offer back rather than leave the territory without one
                    a = o['attributes']
                    restore = {'offerMode': a['offerMode'], 'duration': a['duration'],
                               'numberOfPeriods': a.get('numberOfPeriods', 1)}
                    point = ((o.get('relationships') or {}).get('subscriptionPricePoint') or {}).get('data') or {}
                    asc.call('POST', '/v1/subscriptionIntroductoryOffers',
                             P.intro_body(sid, t, restore, point.get('id')), ok=(201, 409))
                detail = '; '.join(e.get('detail', '') for e in result['errors'])
                failed.append(f'{spec["productId"]} intro {t}: {detail}')
                continue
            deleted_first += 1
        else:
            for o in replaceable:
                asc.call('DELETE', f'/v1/subscriptionIntroductoryOffers/{o["id"]}')
        created += 1
    print(f'  intro offers: {created} created ({deleted_first} needed the old one deleted first)')


for kind, spec, product_id, rows, extra in work:
    pid = spec['productId']
    print(f'\n{pid}:')
    if kind == 'subscription':
        changed = [r for r in rows if r.get('change')]
        for r in changed:
            post_price(product_id, r['territory'], r['listId'], spec['preserveCurrentPrice'], P.UPFRONT)
        print(f'  prices: {len(changed)} territories')
        plan = spec.get('instalmentPlan')
        if plan:
            moved = [r for r in rows if r.get('instalmentChange')]
            for r in moved:
                post_price(product_id, r['territory'], r['instalmentId'], spec['preserveCurrentPrice'], plan['planType'])
            print(f'  {plan["planType"]} plan prices: {len(moved)} territories')
        if spec.get('introOffer'):
            apply_intro(product_id, spec, rows, extra)
        records, included = asc.get_all_with_included(
            f'/v1/subscriptions/{product_id}/prices?include=subscriptionPricePoint,territory&limit=200')
        live = P.current_prices(records, included, P.UPFRONT, '9999-12-31')
        off = [r['territory'] for r in rows if r.get('listId') and live.get(r['territory'], (0, None))[1] != r['listId']]
    else:
        result = asc.call('POST', '/v1/inAppPurchasePriceSchedules',
                          P.schedule_body(product_id, spec['baseTerritory'], extra))
        print(f'  price schedule saved ({len(extra)} manual, the rest automatic)')
        records, included = asc.get_all_with_included(
            f'/v1/inAppPurchasePriceSchedules/{product_id}/manualPrices?include=inAppPurchasePricePoint,territory&limit=200')
        live = P.current_prices(records, included, None, '9999-12-31')
        off = [t for t, point in extra.items() if live.get(t, (0, None))[1] != point]
    if off:
        failed.append(f'{pid}: read back differs in {", ".join(off[:20])}{" ..." if len(off) > 20 else ""}')
    else:
        print('  read back: matches the plan')

if failed:
    print('\nNot applied:')
    for line in failed:
        print('  ' + line)
    sys.exit(1)
