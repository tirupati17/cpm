"""Amplitude REST clients shared by the amplitude commands (private module).

Two different APIs with two different credentials:

  * Analytics (Dashboard REST: /api/2/...): HTTP Basic, project API key as the
    user and project secret key as the password.
  * Experiment Management (/api/1/flags ...): `Authorization: Bearer <key>`
    with a management key. The analytics keys are refused there, and the
    management key is refused by analytics.

Both are region-specific. AMPLITUDE_REGION=eu switches every host; a US key
against an EU host (or the reverse) fails with 401, not with a region hint.
"""
import json
import os

from cpmkit import creds, http
from cpmkit.google import table  # noqa: F401  (re-exported for the commands)

HOSTS = {
    'us': {'analytics': 'https://amplitude.com', 'experiment': 'https://experiment.amplitude.com'},
    'eu': {'analytics': 'https://analytics.eu.amplitude.com', 'experiment': 'https://experiment.eu.amplitude.com'},
}


def region():
    # Read without prompting: a missing region simply means US.
    value = os.environ.get('AMPLITUDE_REGION') or creds.load().get('AMPLITUDE_REGION') or 'us'
    value = value.strip().lower()
    if value not in HOSTS:
        raise SystemExit(f'AMPLITUDE_REGION is {value!r}; use us or eu.')
    return value


def host(kind):
    return HOSTS[region()][kind]


def analytics(path, params=None):
    auth = http.basic(creds.get('AMPLITUDE_API_KEY'), creds.get('AMPLITUDE_SECRET_KEY'))
    return http.request('GET', host('analytics') + path, headers={'Authorization': auth}, params=params)


def management(method, path, **kw):
    key = creds.get('AMPLITUDE_MANAGEMENT_KEY')
    if not key:
        raise SystemExit('Flags need the Experiment management key: cpm creds set AMPLITUDE_MANAGEMENT_KEY  '
                         '(Amplitude > Experiment > Management API > create key)')
    return http.request(method, host('experiment') + path, headers={'Authorization': f'Bearer {key}'}, **kw)


def all_flags(limit=1000):
    """Every flag, following nextCursor. Accepts both {flags: [...]} and a bare list."""
    flags, cursor = [], None
    while True:
        page = management('GET', '/api/1/flags', params={'limit': limit, 'cursor': cursor})
        if isinstance(page, list):
            return flags + page
        flags.extend(page.get('flags') or [])
        cursor = page.get('nextCursor')
        if not cursor:
            return flags


def dump(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))
