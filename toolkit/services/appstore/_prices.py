"""Price ladder spec -> App Store Connect price points, per territory. Pure logic.

The spec is a JSON file; `cpm appstore prices` reads its "appstore" section
(a "play" section beside it is for `cpm play prices`). Prices are decimal
strings in the territory's own currency.

    {"appstore": {
      "subscriptions": [{
        "productId": "yearly",
        "basePrice": {"territory": "USA", "price": "39.99"},  # Apple equalizes this point everywhere
        "manualPrices": {"IND": "1499"},                     # set by hand, wins over equalization
        "preserveCurrentPrice": true,                        # existing subscribers keep their price
        "introOffer": {                                      # optional; omit to leave intro offers alone
          "offerMode": "PAY_UP_FRONT", "duration": "ONE_YEAR", "numberOfPeriods": 1,
          "prices": {"USA": "7.99", "IND": "299"},           # exact, per territory
          "fractionOfList": "0.20",                          # elsewhere: the point nearest list x fraction
          "discountRange": [78, 82],                         # flag territories outside it
          "replaces": ["FREE_TRIAL"]                         # existing offer modes this one replaces
        },
        "instalmentPlan": {"planType": "MONTHLY", "months": 12}  # optional: the monthly-instalment plan
      }],                                                         # of a yearly, at the point >= list / months
      "inAppPurchases": [{
        "productId": "lifetime", "baseTerritory": "USA",
        "prices": {"USA": "79.99", "IND": "3999"}             # manual prices; every other territory automatic
      }]
    }}

Only territories where the product already has a price are planned: this
command reprices, it does not change availability.
"""
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

OFFER_MODES = {'FREE_TRIAL', 'PAY_AS_YOU_GO', 'PAY_UP_FRONT'}
DURATIONS = {'THREE_DAYS', 'ONE_WEEK', 'TWO_WEEKS', 'ONE_MONTH', 'TWO_MONTHS', 'THREE_MONTHS',
             'SIX_MONTHS', 'ONE_YEAR'}
UPFRONT = 'UPFRONT'


def dec(text):
    try:
        return Decimal(str(text).strip())
    except (InvalidOperation, AttributeError):
        raise SystemExit(f'Not a price: {text!r}')


def fmt(value):
    """7.99 -> '7.99', 199.0 -> '199', None -> '-'."""
    if value is None:
        return '-'
    value = Decimal(value)
    return str(int(value)) if value == value.to_integral_value() else f'{value:.2f}'


def discount(intro, list_price):
    """Percent off list, one decimal: (39.99, 7.99) -> 80.0."""
    if intro is None or not list_price:
        return None
    return ((1 - Decimal(intro) / Decimal(list_price)) * 100).quantize(Decimal('0.1'), ROUND_HALF_UP)


# -- spec -------------------------------------------------------------------------------

def _prices(mapping, where):
    out = {}
    for territory, price in (mapping or {}).items():
        if len(territory) != 3 or not territory.isupper():
            raise SystemExit(f'{where}: territory {territory!r} must be a three-letter code like USA.')
        out[territory] = dec(price)
    return out


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    section = spec.get('appstore', spec)
    subs, iaps = section.get('subscriptions') or [], section.get('inAppPurchases') or []
    if not subs and not iaps:
        raise SystemExit(f'{path} has no appstore subscriptions or inAppPurchases.')
    seen = set()
    for sub in subs:
        pid = sub.get('productId') or ''
        if not pid or pid in seen:
            raise SystemExit(f'Missing or repeated productId {pid!r}.')
        seen.add(pid)
        base = sub.get('basePrice') or {}
        if not base.get('territory') or 'price' not in base:
            raise SystemExit(f'{pid}: basePrice needs territory and price.')
        sub['basePrice'] = {'territory': base['territory'], 'price': dec(base['price'])}
        sub['manualPrices'] = _prices(sub.get('manualPrices'), pid)
        sub.setdefault('preserveCurrentPrice', True)
        offer = sub.get('introOffer')
        if offer:
            if offer.get('offerMode') not in OFFER_MODES:
                raise SystemExit(f'{pid}: introOffer.offerMode must be one of {sorted(OFFER_MODES)}.')
            if offer.get('duration') not in DURATIONS:
                raise SystemExit(f'{pid}: introOffer.duration must be one of {sorted(DURATIONS)}.')
            offer.setdefault('numberOfPeriods', 1)
            offer['prices'] = _prices(offer.get('prices'), f'{pid} introOffer')
            if offer['offerMode'] != 'FREE_TRIAL' and not (offer['prices'] or offer.get('fractionOfList')):
                raise SystemExit(f'{pid}: a paid introOffer needs prices or fractionOfList.')
            offer['fractionOfList'] = dec(offer['fractionOfList']) if offer.get('fractionOfList') else None
            low, high = offer.get('discountRange') or (0, 100)
            offer['discountRange'] = (Decimal(str(low)), Decimal(str(high)))
            offer.setdefault('replaces', ['FREE_TRIAL'])
        plan = sub.get('instalmentPlan')
        if plan:
            plan.setdefault('planType', 'MONTHLY')
            plan['months'] = int(plan.get('months') or 12)
    for iap in iaps:
        pid = iap.get('productId') or ''
        if not pid or pid in seen:
            raise SystemExit(f'Missing or repeated productId {pid!r}.')
        seen.add(pid)
        iap['prices'] = _prices(iap.get('prices'), pid)
        if iap.get('baseTerritory') not in iap['prices']:
            raise SystemExit(f'{pid}: baseTerritory must have a price in "prices".')
    return subs, iaps


# -- reading API pages -----------------------------------------------------------------

def territory_of(record):
    return ((record.get('relationships') or {}).get('territory') or {}).get('data', {}).get('id')


def index_points(records):
    """Price point records -> {territory: [(price, id), ...] ascending}."""
    points = {}
    for record in records:
        territory = territory_of(record)
        if territory:
            points.setdefault(territory, []).append((dec(record['attributes']['customerPrice']), record['id']))
    for values in points.values():
        values.sort()
    return points


def current_prices(records, included, plan_type=UPFRONT, today='9999-12-31'):
    """subscriptionPrices (or IAP price) records -> {territory: (price, point id)} in effect today.

    A record with no startDate has been in effect since the beginning; a later
    startDate on or before today supersedes it; a future one is ignored."""
    points = {i['id']: i['attributes'] for i in included if i['type'].endswith('PricePoints')}
    best = {}
    for record in records:
        attributes = record.get('attributes') or {}
        if plan_type and attributes.get('planType', UPFRONT) != plan_type:
            continue
        start = attributes.get('startDate') or ''
        if start > today:
            continue
        relations = record['relationships']
        point_key = next(k for k in relations if k.endswith('PricePoint'))
        point_id = relations[point_key]['data']['id']
        territory = territory_of(record)
        if territory not in best or start >= best[territory][0]:
            price = points.get(point_id, {}).get('customerPrice')
            best[territory] = (start, dec(price) if price is not None else None, point_id)
    return {t: (price, pid) for t, (_, price, pid) in best.items()}


def exact(points, territory, price, what):
    for value, pid in points.get(territory, ()):
        if value == price:
            return pid
    near = ', '.join(fmt(v) for v, _ in points.get(territory, ()) if abs(v - price) <= price * Decimal('0.15'))
    raise SystemExit(f'{what}: {territory} has no price point at {fmt(price)} (near it: {near or "none"}).')


def nearest(points, target):
    """(price, id) of the point nearest target; a tie goes to the lower price."""
    if not points:
        return None
    return min(points, key=lambda p: (abs(p[0] - target), p[0]))


def at_least(points, target):
    return next((p for p in points if p[0] >= target), None)


# -- planning --------------------------------------------------------------------------

def plan_subscription(sub, current, base_point_id, equalized, manual_ids, points, currencies,
                      current_instalment=None):
    """One row per territory the subscription is sold in.

    current: {territory: (price, point id)} for the up-front plan.
    equalized: {territory: (price, point id)} from the base point's equalizations.
    manual_ids: {territory: point id} for basePrice and manualPrices.
    points: {territory: [(price, id)]} every price point (needed for the intro
        offer's nearest point and the instalment plan; may be {} otherwise).
    """
    base = sub['basePrice']
    manual = dict(sub['manualPrices'])
    manual[base['territory']] = base['price']
    offer, plan = sub.get('introOffer'), sub.get('instalmentPlan')
    rows = []
    for territory in sorted(current):
        now = current[territory][0]
        row = {'territory': territory, 'currency': currencies.get(territory, ''), 'current': now,
               'list': None, 'listId': None, 'source': None, 'flags': []}
        if territory in manual:
            row.update(list=manual[territory], listId=manual_ids[territory],
                       source='base' if territory == base['territory'] else 'manual')
        elif territory in equalized:
            row['list'], row['listId'] = equalized[territory]
            row['source'] = 'equalized'
        else:
            row['flags'].append('no equalized price: left as is')
        row['change'] = row['listId'] is not None and row['listId'] != current[territory][1]
        if offer and row['list'] is not None:
            _plan_intro(row, offer, points.get(territory, []))
        if plan and current_instalment and territory in current_instalment and row['list'] is not None:
            row['instalmentCurrent'] = current_instalment[territory][0]
            choice = at_least(points.get(territory, []), row['list'] / plan['months'])
            if choice:
                row['instalment'], row['instalmentId'] = choice
                row['instalmentChange'] = choice[1] != current_instalment[territory][1]
            else:
                row['flags'].append('no instalment point')
        rows.append(row)
    if base_point_id is None:
        raise SystemExit(f'{sub["productId"]}: no base price point.')
    return rows


def _plan_intro(row, offer, territory_points):
    territory, list_price = row['territory'], row['list']
    if offer['offerMode'] == 'FREE_TRIAL':
        row['intro'], row['introId'] = Decimal(0), None
        return
    if territory in offer['prices']:
        price = offer['prices'][territory]
        match = next((p for p in territory_points if p[0] == price), None)
        if not match:
            row['flags'].append(f'no intro point at {fmt(price)}')
            return
    else:
        match = nearest(territory_points, list_price * offer['fractionOfList'])
        if not match:
            row['flags'].append('no price points for the intro offer')
            return
    row['intro'], row['introId'] = match
    row['discount'] = discount(match[0], list_price)
    low, high = offer['discountRange']
    if match[0] >= list_price:
        row['flags'].append('intro is not below list')
    elif not low <= row['discount'] <= high:
        row['flags'].append(f'discount {row["discount"]}% outside {low}-{high}%')


def plan_iap(iap, current, equalized, manual_ids, currencies):
    """One row per territory with a current price: manual where the spec sets one,
    otherwise Apple's automatic (equalized) price of the base territory's point."""
    rows = []
    for territory in sorted(set(current) | set(iap['prices'])):
        now = current.get(territory, (None, None))[0]
        row = {'territory': territory, 'currency': currencies.get(territory, ''), 'current': now, 'flags': []}
        if territory in iap['prices']:
            row.update(list=iap['prices'][territory], listId=manual_ids[territory], source='manual')
        elif territory in equalized:
            row['list'], row['listId'] = equalized[territory]
            row['source'] = 'automatic'
        else:
            row.update(list=None, listId=None, source=None)
            row['flags'].append('no automatic price')
        rows.append(row)
    return rows


# -- request bodies --------------------------------------------------------------------

def price_body(subscription_id, territory, point_id, preserve, plan_type=UPFRONT, start=None):
    return {'data': {'type': 'subscriptionPrices',
                     'attributes': {'startDate': start, 'preserveCurrentPrice': bool(preserve),
                                    'planType': plan_type},
                     'relationships': {
                         'subscription': {'data': {'type': 'subscriptions', 'id': subscription_id}},
                         'territory': {'data': {'type': 'territories', 'id': territory}},
                         'subscriptionPricePoint': {'data': {'type': 'subscriptionPricePoints', 'id': point_id}}}}}


def intro_body(subscription_id, territory, offer, point_id, plan_type=UPFRONT):
    relationships = {'subscription': {'data': {'type': 'subscriptions', 'id': subscription_id}},
                     'territory': {'data': {'type': 'territories', 'id': territory}}}
    if point_id:
        relationships['subscriptionPricePoint'] = {'data': {'type': 'subscriptionPricePoints', 'id': point_id}}
    return {'data': {'type': 'subscriptionIntroductoryOffers',
                     'attributes': {'duration': offer['duration'], 'offerMode': offer['offerMode'],
                                    'numberOfPeriods': offer['numberOfPeriods'], 'startDate': None,
                                    'endDate': None, 'targetSubscriptionPlanType': plan_type},
                     'relationships': relationships}}


def schedule_body(iap_id, base_territory, manual_ids):
    """inAppPurchasePriceSchedules create: the manual prices, inline; the rest automatic."""
    refs = [{'type': 'inAppPurchasePrices', 'id': f'${{price-{t}}}'} for t in sorted(manual_ids)]
    included = [{'type': 'inAppPurchasePrices', 'id': f'${{price-{t}}}', 'attributes': {'startDate': None},
                 'relationships': {
                     'inAppPurchaseV2': {'data': {'type': 'inAppPurchases', 'id': iap_id}},
                     'inAppPurchasePricePoint': {'data': {'type': 'inAppPurchasePricePoints', 'id': pid}}}}
                for t, pid in sorted(manual_ids.items())]
    return {'data': {'type': 'inAppPurchasePriceSchedules', 'relationships': {
        'inAppPurchase': {'data': {'type': 'inAppPurchases', 'id': iap_id}},
        'baseTerritory': {'data': {'type': 'territories', 'id': base_territory}},
        'manualPrices': {'data': refs}}}, 'included': included}


# -- output ----------------------------------------------------------------------------

def export(products, iso2):
    """{territory: {iso2, currency, products: {productId: {list, intro}}}} for other tools
    (`cpm play prices --match`). Prices are strings in the territory's currency."""
    out = {}
    for pid, rows in products.items():
        for row in rows:
            if row.get('list') is None:
                continue
            entry = out.setdefault(row['territory'], {'iso2': iso2(row['territory']),
                                                      'currency': row['currency'], 'products': {}})
            item = {'list': fmt(row['list'])}
            if row.get('intro') is not None:
                item['intro'] = fmt(row['intro'])
            entry['products'][pid] = item
    return out


def markdown(products, kinds):
    """One table per product. kinds: {productId: 'subscription' | 'iap'}."""
    lines = []
    for pid, rows in products.items():
        intro = any('intro' in r for r in rows)
        instalment = any('instalment' in r for r in rows)
        lines.append(f'### App Store `{pid}` ({len(rows)} territories)\n')
        head = ['Territory', 'Currency', 'Current', 'New list', 'Source']
        if intro:
            head += ['Intro', 'Discount']
        if instalment:
            head += ['Instalment now', 'Instalment new']
        head.append('Flag')
        lines += ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
        for r in rows:
            cells = [r['territory'], r['currency'], fmt(r['current']), fmt(r.get('list')), r.get('source') or '-']
            if intro:
                cells += [fmt(r.get('intro')), f'{r["discount"]}%' if r.get('discount') is not None else '-']
            if instalment:
                cells += [fmt(r.get('instalmentCurrent')), fmt(r.get('instalment'))]
            cells.append('; '.join(r['flags']) or '')
            lines.append('| ' + ' | '.join(cells) + ' |')
        lines.append('')
    return '\n'.join(lines)
