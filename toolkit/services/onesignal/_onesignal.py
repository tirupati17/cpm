"""OneSignal REST client shared by the onesignal commands (private module).

Base https://api.onesignal.com. Keys created since late 2024 start with
`os_v2_` and authenticate as `Authorization: Key <key>`; older ones use
`Authorization: Basic <key>`. The scheme is picked from the key's shape, and
ONESIGNAL_AUTH_SCHEME=Key|Basic overrides it.
"""
import datetime
import json
import os

from cpmkit import creds, http
from cpmkit.google import table  # noqa: F401  (re-exported for the commands)

BASE = 'https://api.onesignal.com'


def app_id():
    return creds.get('ONESIGNAL_APP_ID')


def auth(key):
    scheme = os.environ.get('ONESIGNAL_AUTH_SCHEME') or ('Key' if key.startswith('os_v2_') else 'Basic')
    return {'Authorization': f'{scheme} {key}'}


def call(method, path, key=None, **kw):
    key = key or creds.get('ONESIGNAL_REST_API_KEY')
    return http.request(method, BASE + path, headers=auth(key), **kw)


def dump(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def when(seconds):
    if not seconds:
        return ''
    return datetime.datetime.fromtimestamp(int(seconds), datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')


def text(field):
    """First language of a {"en": "..."} field, or the field itself."""
    if isinstance(field, dict):
        return field.get('en') or next(iter(field.values()), '')
    return field or ''
