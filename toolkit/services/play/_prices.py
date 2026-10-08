"""Price ladder spec -> Play subscription base plans, offers and one-time prices. Pure logic.

`cpm play prices` reads the "play" section of a spec file (the "appstore"
section beside it is for `cpm appstore prices`):

    {"play": {
      "regionsVersion": "2025/03",
      "match": "ios-prices.json",         # optional: `cpm appstore prices --out`, relative to the spec
      "limitsUsd": {"min": "0.05", "max": "999.99"},   # sanity range, converted per region
      "subscriptions": [{
        "productId": "pro_yearly", "basePlanId": "yearly", "billingPeriod": "P1Y",
        "usd": "39.99",                   # converted by Play where nothing better applies
        "regionPrices": {"IN": "1499 INR"},  # set by hand, wins over everything
        "matchIos": "yearly",             # same currency as the App Store territory: use its list price
        "keepOffers": ["yearly-trial"],   # named only to say they are left alone
        "offers": [{
          "offerId": "launch80", "duration": "P1Y", "usd": "7.99",
          "regionPrices": {"IN": "299 INR"}, "matchIos": "yearly",   # the App Store intro price
          "newCustomersOnly": true, "discountRange": [78, 82]
        }],
        "deactivateOffers": ["old-trial"],
        "legacyCompatibleOfferId": "launch80"
      }],
      "oneTime": [{"productId": "lifetime", "purchaseOptionId": "lifetime", "usd": "79.99",
                   "regionPrices": {"IN": "3999 INR"}}]
    }}

Price for a region, in order: regionPrices, then the matched App Store price
when the currencies are the same, then Play's conversion of the USD price
rounded to a local ending (round_local). Only regions the plan or product
already sells in are priced; availability is not changed.
"""
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from _products import money, show

PERIODS = {'P1W', 'P1M', 'P3M', 'P6M', 'P1Y'}


def amount(price):
    """Play Money -> Decimal."""
    return Decimal(str(price.get('units', '0'))) + Decimal(int(price.get('nanos', 0))) / Decimal(10 ** 9)


def as_money(value, currency):
    return money(f'{Decimal(value).normalize():f} {currency}')


def discount(offer, list_price):
    if not list_price:
        return None
    return ((1 - offer / list_price) * 100).quantize(Decimal('0.1'), ROUND_HALF_UP)


def _nearest(value, candidates):
    return min(candidates, key=lambda c: (abs(c - value), c))


def round_local(value, whole=False):
    """A converted price -> a price with a local-looking ending.

    Under 10: x.49 or x.99. Under 1,000: x.99 (a whole-number currency: a whole
    number under 100, else ...9).
    Under 10,000: a multiple of 10. Above: three significant figures."""
    value = Decimal(value)
    if value <= 0:
        return value
    if value >= 10000:
        step = Decimal(10) ** (len(str(int(value))) - 3)
        return (value / step).quantize(Decimal(1), ROUND_HALF_UP) * step
    if value >= 1000:
        return (value / 10).quantize(Decimal(1), ROUND_HALF_UP) * 10
    base = int(value)
    if whole:
        if value < 100:
            return max(value.quantize(Decimal(1), ROUND_HALF_UP), Decimal(1))
        lower = Decimal(base // 10 * 10 - 1)
        return _nearest(value, [lower, lower + 10])
    if value < 10:
        options = [Decimal(n) + Decimal(f) for n in range(max(base - 1, 0), base + 2) for f in ('0.49', '0.99')]
    else:
        options = [Decimal(n) + Decimal('0.99') for n in range(max(base - 1, 0), base + 2)]
    return _nearest(value, options)


def is_whole(price):
    """Treat a currency as whole-number when Play converts to it without cents at 100+."""
    return int(price.get('nanos', 0)) == 0 and amount(price) >= 100


# -- spec ------------------------------------------------------------------------------

def _region_prices(mapping, where):
    out = {}
    for region, text in (mapping or {}).items():
        if len(region) != 2 or not region.isupper():
            raise SystemExit(f'{where}: region {region!r} must be two letters like IN.')
        if len(str(text).split()) != 2:
            raise SystemExit(f'{where}: {region} price needs a currency, like "199 INR".')
        out[region] = money(text)
    return out


def load_spec(path):
    path = Path(path)
    spec = json.loads(path.read_text(encoding='utf-8'))
    section = spec.get('play', spec)
    subs, one_time = section.get('subscriptions') or [], section.get('oneTime') or []
    if not subs and not one_time:
        raise SystemExit(f'{path} has no play subscriptions or oneTime products.')
    for sub in subs:
        pid = sub.get('productId')
        if not (pid and sub.get('basePlanId') and sub.get('usd')):
            raise SystemExit(f'Every subscription needs productId, basePlanId and usd ({pid!r}).')
        if sub.get('billingPeriod') and sub['billingPeriod'] not in PERIODS:
            raise SystemExit(f'{pid}: billingPeriod must be one of {sorted(PERIODS)}.')
        money(sub['usd'])
        sub['regionPrices'] = _region_prices(sub.get('regionPrices'), pid)
        for offer in sub.get('offers') or []:
            if not (offer.get('offerId') and offer.get('duration') and offer.get('usd')):
                raise SystemExit(f'{pid}: every offer needs offerId, duration and usd.')
            offer['regionPrices'] = _region_prices(offer.get('regionPrices'), offer['offerId'])
            low, high = offer.get('discountRange') or (0, 100)
            offer['discountRange'] = (Decimal(str(low)), Decimal(str(high)))
    for product in one_time:
        if not (product.get('productId') and product.get('usd')):
            raise SystemExit('Every oneTime product needs productId and usd.')
        product['regionPrices'] = _region_prices(product.get('regionPrices'), product['productId'])
    match = None
    if section.get('match'):
        match_path = (path.parent / section['match']).resolve()
        if not match_path.is_file():
            raise SystemExit(f'No App Store prices at {match_path}. Run `cpm appstore prices --out` first.')
        match = load_match(json.loads(match_path.read_text(encoding='utf-8')))
    limits = section.get('limitsUsd') or {}
    return {'regionsVersion': section.get('regionsVersion', '2025/03'), 'subscriptions': subs,
            'oneTime': one_time, 'match': match, 'limits': (limits.get('min'), limits.get('max'))}


def load_match(exported):
    """`cpm appstore prices --out` JSON -> {iso2 region: {currency, products}}."""
    out = {}
    for entry in (exported.get('territories') or {}).values():
        if entry.get('iso2'):
            out[entry['iso2']] = {'currency': entry['currency'], 'products': entry.get('products') or {}}
    return out


# -- planning --------------------------------------------------------------------------

def choose(region, converted, region_prices, match=None, product=None, key='list'):
    """(Money, source) for one region; converted is Play's conversion for that region."""
    if region in region_prices:
        return region_prices[region], 'set'
    currency = converted['currencyCode']
    entry = (match or {}).get(region)
    if entry and product and entry['currency'] == currency:
        value = (entry['products'].get(product) or {}).get(key)
        if value is not None:
            return as_money(value, currency), 'ios'
    return as_money(round_local(amount(converted), is_whole(converted)), currency), 'converted'


def check_limits(row, price, limits):
    low, high = limits
    region = row['region']
    if low and region in low and amount(price) < amount(low[region]['price']):
        row['flags'].append(f'below Play minimum ~{show(low[region]["price"])}')
    if high and region in high and amount(price) > amount(high[region]['price']):
        row['flags'].append(f'above Play maximum ~{show(high[region]["price"])}')


def plan_prices(current, converted, region_prices, match=None, product=None, key='list', limits=(None, None)):
    """current: {region: Money now}. converted: convertRegionPrices response.
    -> rows {region, currency, current, new (Money), source, flags}."""
    by_region = converted.get('convertedRegionPrices', {})
    rows = []
    for region in sorted(current):
        row = {'region': region, 'currency': current[region]['currencyCode'], 'current': current[region], 'flags': []}
        if region in region_prices:
            row['new'], row['source'] = region_prices[region], 'set'
        elif region in by_region:
            row['new'], row['source'] = choose(region, by_region[region]['price'], {}, match, product, key)
        else:
            row['new'], row['source'] = current[region], 'kept'
            row['flags'].append('Play gave no conversion: price kept')
        if row['new']['currencyCode'] != row['currency']:
            row['flags'].append(f'currency {row["new"]["currencyCode"]} differs from the live {row["currency"]}')
        check_limits(row, row['new'], limits)
        rows.append(row)
    return rows


def add_offer(rows, offer_rows, offer, ratio=None):
    """Merge an offer's per-region prices into the base plan rows, with the discount.

    ratio (offer USD / base USD): a region that would get Play's conversion of the
    offer's USD price gets its new base price times the ratio instead, rounded
    the same way. Converting and rounding both prices separately can land a
    whole-number currency far from the intended discount (PYG: 77.8%)."""
    by_region = {r['region']: r for r in offer_rows}
    low, high = offer['discountRange']
    for row in rows:
        o = by_region.get(row['region'])
        if not o:
            continue
        if ratio is not None and o['source'] == 'converted':
            value = round_local(amount(row['new']) * Decimal(ratio), is_whole(row['new']))
            o = dict(o, new=as_money(value, row['new']['currencyCode']), source='ratio')
        row['offer'], row['offerSource'] = o['new'], o['source']
        row['flags'] += o['flags']
        row['discount'] = discount(amount(o['new']), amount(row['new']))
        if row['discount'] is not None and not low <= row['discount'] <= high:
            row['flags'].append(f'discount {row["discount"]}% outside {low}-{high}%')
        elif row['discount'] is None or amount(o['new']) >= amount(row['new']):
            row['flags'].append('offer is not below the base price')


def base_plan_body(plan, rows, other):
    """The base plan with new regional prices (and new-region prices); everything else kept."""
    prices = {r['region']: r['new'] for r in rows}
    updated = dict(plan)
    updated['regionalConfigs'] = [dict(c, price=prices.get(c['regionCode'], c['price']))
                                  for c in plan.get('regionalConfigs', [])]
    if other:
        kept = plan.get('otherRegionsConfig') or {}
        updated['otherRegionsConfig'] = {'usdPrice': other['usdPrice'], 'eurPrice': other['eurPrice'],
                                         'newSubscriberAvailability': kept.get('newSubscriberAvailability', True)}
    return updated


def offer_body(package, product_id, base_plan_id, offer, rows, other):
    phase = {'recurrenceCount': 1, 'duration': offer['duration'],
             'regionalConfigs': [{'regionCode': r['region'], 'price': r['offer']} for r in rows if 'offer' in r]}
    if other:
        # An offer phase nests the prices one level deeper than a base plan does.
        phase['otherRegionsConfig'] = {'otherRegionsPrices': {'usdPrice': other['usdPrice'],
                                                              'eurPrice': other['eurPrice']}}
    body = {'packageName': package, 'productId': product_id, 'basePlanId': base_plan_id,
            'offerId': offer['offerId'], 'phases': [phase],
            'regionalConfigs': [{'regionCode': r['region'], 'newSubscriberAvailability': True}
                                for r in rows if 'offer' in r],
            'otherRegionsConfig': {'otherRegionsNewSubscriberAvailability': True}}
    if offer.get('newCustomersOnly', True):
        body['targeting'] = {'acquisitionRule': {'scope': {'thisSubscription': {}}}}
    return body


def one_time_option(option, rows, other):
    prices = {r['region']: r['new'] for r in rows}
    updated = dict(option)
    updated['regionalPricingAndAvailabilityConfigs'] = [
        dict(c, price=prices.get(c['regionCode'], c.get('price')))
        for c in option.get('regionalPricingAndAvailabilityConfigs', [])]
    if other:
        kept = option.get('newRegionsConfig') or {}
        updated['newRegionsConfig'] = {'usdPrice': other['usdPrice'], 'eurPrice': other['eurPrice'],
                                       'availability': kept.get('availability', 'AVAILABLE')}
    return updated


# -- output ----------------------------------------------------------------------------

def markdown(products):
    """products: {title: rows}."""
    lines = []
    for title, rows in products.items():
        offer = any('offer' in r for r in rows)
        lines.append(f'### Play `{title}` ({len(rows)} regions)\n')
        head = ['Region', 'Currency', 'Current', 'New', 'Source'] + (['Offer', 'Discount'] if offer else []) + ['Flag']
        lines += ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
        for r in rows:
            cells = [r['region'], r['currency'], show(r['current']) if r.get('current') else '-', show(r['new']),
                     r['source']]
            if offer:
                cells += [show(r['offer']) if 'offer' in r else '-',
                          f'{r["discount"]}%' if r.get('discount') is not None else '-']
            cells.append('; '.join(r['flags']))
            lines.append('| ' + ' | '.join(cells) + ' |')
        lines.append('')
    return '\n'.join(lines)
