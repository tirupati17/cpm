"""One-time in-app product spec -> Play monetization API bodies. Pure logic.

A spec file (JSON) describes the products; prices are decimal strings:

    {
      "regionsVersion": "2025/03",
      "regionGroups": {"lower-income": ["PK", "BD", "NG"]},
      "products": [{
        "productId": "coins_100",
        "price": "0.99",                        # USD, converted by Play for every region
        "regionPrices": {"IN": "24 INR"},       # set by hand, wins over everything
        "groupPrices": {"lower-income": "0.49"},# USD, converted by Play for that group
        "listings": [{"languageCode": "en-US", "title": "100 coins",
                      "description": "A pack of 100 coins."}],
        "purchaseOptionId": "coins-100"         # optional, default: productId with _ as -
      }]
    }

Consumable vs non-consumable is not a Play setting for one-time products: the
purchase is consumed by the app (or by your billing backend, with the product
typed as a consumable there), which is what lets someone buy the same pack again.
"""
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_REGIONS_VERSION = '2025/03'
PRODUCT_ID = re.compile(r'^[a-z0-9][a-z0-9._]{0,138}$')


def money(text, currency='USD'):
    """'0.99' or '24 INR' -> Play Money {'currencyCode', 'units', 'nanos'}."""
    parts = str(text).split()
    if len(parts) == 2:
        text, currency = parts
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise SystemExit(f'Not a price: {text!r}')
    if value < 0:
        raise SystemExit(f'Negative price: {text!r}')
    units = int(value)
    nanos = int(((value - units) * 1_000_000_000).to_integral_value())
    return {'currencyCode': currency.upper(), 'units': str(units), 'nanos': nanos}


def show(price):
    # Protobuf JSON leaves out zero fields: $0.99 arrives with no "units".
    return f'{price.get("units", "0")}.{int(price.get("nanos", 0)) // 10_000_000:02d} {price["currencyCode"]}'


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    groups = {name: set(codes) for name, codes in spec.get('regionGroups', {}).items()}
    products = spec.get('products') or []
    if not products:
        raise SystemExit(f'{path} has no products.')
    seen = set()
    for product in products:
        pid = product.get('productId', '')
        if not PRODUCT_ID.match(pid):
            raise SystemExit(f'Bad productId {pid!r}: lowercase letters, digits, _ and . only, starting with a letter or digit.')
        if pid in seen:
            raise SystemExit(f'productId {pid} appears twice.')
        seen.add(pid)
        if 'price' not in product:
            raise SystemExit(f'{pid} has no price.')
        money(product['price'])
        if not product.get('listings'):
            raise SystemExit(f'{pid} needs at least one listing (languageCode, title, description).')
        for listing in product['listings']:
            if not all(listing.get(k) for k in ('languageCode', 'title', 'description')):
                raise SystemExit(f'{pid}: every listing needs languageCode, title and description.')
            if len(listing['title']) > 55 or len(listing['description']) > 200:
                raise SystemExit(f'{pid} {listing["languageCode"]}: title max 55, description max 200 characters.')
        for group in product.get('groupPrices', {}):
            if group not in groups:
                raise SystemExit(f'{pid} prices unknown region group {group!r}.')
    return spec.get('regionsVersion', DEFAULT_REGIONS_VERSION), groups, products


def regional_configs(converted, region_prices=None, group_prices=None, groups=None):
    """Per-region prices: a hand-set price wins, then a group's converted price,
    then Play's conversion of the base price.

    converted: convertRegionPrices response for the base price.
    group_prices: {group name: convertRegionPrices response for that group's price}.
    """
    region_prices = {k: money(v) for k, v in (region_prices or {}).items()}
    configs = []
    for region, value in sorted(converted.get('convertedRegionPrices', {}).items()):
        price = value['price']
        if region in region_prices:
            price = region_prices[region]
        else:
            for group, response in (group_prices or {}).items():
                low = response.get('convertedRegionPrices', {})
                if region in (groups or {}).get(group, ()) and region in low:
                    price = low[region]['price']
                    break
        configs.append({'regionCode': region, 'price': price, 'availability': 'AVAILABLE'})
    return configs


def product_body(package, product, configs, other):
    """The onetimeproducts().patch body for one product."""
    pid = product['productId']
    base = money(product['price'])
    return {
        'packageName': package,
        'productId': pid,
        'listings': product['listings'],
        'taxAndComplianceSettings': {'isTokenizedDigitalAsset': False},
        'purchaseOptions': [{
            'purchaseOptionId': product.get('purchaseOptionId') or pid.replace('_', '-').replace('.', '-'),
            'buyOption': {'legacyCompatible': True},
            'regionalPricingAndAvailabilityConfigs': configs,
            'newRegionsConfig': {
                'usdPrice': (other or {}).get('usdPrice', base),
                'eurPrice': (other or {}).get('eurPrice'),
                'availability': 'AVAILABLE',
            },
            'taxAndComplianceSettings': {'withdrawalRightType': 'WITHDRAWAL_RIGHT_DIGITAL_CONTENT'},
        }],
    }


def newer_regions_version(error_text, tried):
    """Play names the regions version it wants only in the error for a stale one."""
    if 'egion' not in error_text:
        return None
    latest = [v for v in re.findall(r'\d{4}/\d{2}', error_text) if v != tried]
    return latest[-1] if latest else None
