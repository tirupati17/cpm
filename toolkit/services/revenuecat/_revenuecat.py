"""RevenueCat REST client shared by the revenuecat commands (private module).

API v2 (https://api.revenuecat.com/v2) for everything it covers. v1 only for a
lifetime promotional grant, which v2's grant_entitlement cannot express (it
takes an expiry timestamp, not a duration keyword).

Auth: `Authorization: Bearer <secret key>`. v2 wants a v2 secret key scoped to
the project; v1 is tried with REVENUECAT_V1_API_KEY when set, else with the v2
key (RevenueCat documents the key versions as separate, so expect a 401 there
and store a v1 key if it happens).
"""
import json
import sys
import urllib.parse

from cpmkit import creds, http
from cpmkit.google import table  # noqa: F401  (re-exported for the commands)

HOST = 'https://api.revenuecat.com'
V2 = HOST + '/v2'
V1 = HOST + '/v1'
PAGE = 100


def quote(value):
    return urllib.parse.quote(str(value), safe='')


def project():
    return creds.get('REVENUECAT_PROJECT_ID')


def _headers(key):
    return {'Authorization': f'Bearer {key}'}


def v2(method, path, **kw):
    """Call a v2 path relative to the project: v2('GET', '/products')."""
    url = f'{V2}/projects/{quote(project())}{path}'
    return http.request(method, url, headers=_headers(creds.get('REVENUECAT_API_KEY')), **kw)


def v2_list(path, params=None, limit=None):
    """Every item of a v2 list, following next_page. Stops at `limit` items when given."""
    params = dict(params or {})
    params.setdefault('limit', PAGE)
    page = v2('GET', path, params=params)
    items = list(page.get('items') or [])
    key = creds.get('REVENUECAT_API_KEY')
    while page.get('next_page') and (limit is None or len(items) < limit):
        page = http.request('GET', HOST + page['next_page'], headers=_headers(key))
        items.extend(page.get('items') or [])
    return items[:limit] if limit else items


def v1(method, path, **kw):
    key = creds.get('REVENUECAT_V1_API_KEY', required=False) or creds.get('REVENUECAT_API_KEY')
    return http.request(method, V1 + path, headers=_headers(key), **kw)


def entitlements():
    """All entitlements of the project as a list of {id, lookup_key, display_name}."""
    return v2_list('/entitlements')


def resolve_entitlement(name, known=None):
    """Match an entitlement by id (entl...), lookup key or display name."""
    known = entitlements() if known is None else known
    for match in (lambda e: e.get('id') == name,
                  lambda e: e.get('lookup_key') == name,
                  lambda e: (e.get('display_name') or '').lower() == name.lower()):
        found = [e for e in known if match(e)]
        if found:
            return found[0]
    names = ', '.join(e.get('lookup_key') or e.get('id', '?') for e in known) or 'none'
    raise SystemExit(f'No entitlement {name!r} in this project. Known: {names}')


def dump(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def note(text):
    print(text, file=sys.stderr)


def when(value):
    """A v2 timestamp (ms since epoch) or v1 ISO string as 'YYYY-MM-DD HH:MM' UTC."""
    import datetime
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
    return str(value).replace('T', ' ')[:16]
