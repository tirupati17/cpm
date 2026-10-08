"""App Store Connect API client shared by the appstore commands (private module).

The key trio and the bundle id come from cpmkit.creds (env first, then
~/.config/cpm/<project>/credentials.env, then a prompt). Key contents are read
from the file only when a token is minted and are never printed.

PyJWT (with cryptography, for ES256) and certifi are imported late, when a token
or a request is actually needed, so `--help` and dry parsing work without them.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from cpmkit.http import ssl_context

API = 'https://api.appstoreconnect.apple.com'
AUDIENCE = 'appstoreconnect-v1'
# App Store Connect refuses tokens that live longer than 20 minutes. Stay just
# under it: the headroom is for clock skew, not for reuse.
TOKEN_LIFETIME = 1100

# States in which a version's build and text can still be changed.
EDITABLE = {'PREPARE_FOR_SUBMISSION', 'DEVELOPER_REJECTED', 'REJECTED', 'METADATA_REJECTED', 'INVALID_BINARY'}
IN_REVIEW = {'WAITING_FOR_REVIEW', 'IN_REVIEW', 'READY_FOR_REVIEW'}
# Review submission states that --replace-in-review cancels.
CANCELLABLE_SUBMISSION = {'WAITING_FOR_REVIEW', 'IN_REVIEW', 'UNRESOLVED_ISSUES', 'READY_FOR_REVIEW'}

PROG = os.path.basename(sys.argv[0]).removesuffix('.py') or 'appstore'


def die(message):
    sys.exit(f'{PROG}: {message}')


def token_claims(issuer, now=None):
    """The JWT payload App Store Connect expects. Pure, so it is testable."""
    now = int(time.time() if now is None else now)
    return {'iss': issuer, 'iat': now, 'exp': now + TOKEN_LIFETIME, 'aud': AUDIENCE}


def token_headers(key_id):
    return {'kid': key_id, 'typ': 'JWT'}


def next_build_from_versions(versions):
    """Highest integer build number + 1, or 1 when there is none.

    Taken numerically: `version` is a string field, so the API orders 9 after
    100. A build numbered "1.2.3" is not ours to reason about; skipping it is
    safer than crashing a release on somebody's old upload.
    """
    numbers = []
    for raw in versions:
        try:
            numbers.append(int(str(raw).strip()))
        except (TypeError, ValueError):
            continue
    return max(numbers, default=0) + 1


def split_versions(versions):
    """(first editable, first in review) from an appStoreVersions list."""
    editable = next((v for v in versions if v['attributes']['appStoreState'] in EDITABLE), None)
    reviewing = next((v for v in versions if v['attributes']['appStoreState'] in IN_REVIEW), None)
    return editable, reviewing


def resolve_credentials(project=None):
    """Key id, issuer and key path, from the credential store. Values never printed."""
    from cpmkit import creds
    key_id = creds.get('ASC_KEY_ID', project)
    issuer = creds.get('ASC_ISSUER_ID', project)
    key_path = os.path.expanduser(creds.get('ASC_KEY_PATH', project))
    return key_id, issuer, key_path


def resolve_bundle_id(explicit=None, project=None):
    if explicit:
        return explicit
    from cpmkit import creds
    return creds.get('ASC_BUNDLE_ID', project)




class ASC:
    def __init__(self, key_id=None, issuer=None, key_path=None, project=None):
        if not (key_id and issuer and key_path):
            key_id, issuer, key_path = resolve_credentials(project)
        self.key_id, self.issuer, self.key_path = key_id, issuer, key_path
        if not os.path.isfile(key_path):
            die(f'no API key at {key_path} (set ASC_KEY_PATH or run `cpm creds set ASC_KEY_PATH`)')
        try:
            import jwt  # noqa: F401  PyJWT with cryptography, for the ES256 token
        except ImportError:
            die("needs PyJWT: pip3 install 'pyjwt[crypto]' certifi")
        with open(key_path) as handle:
            self._key = handle.read()
        self._context = ssl_context()

    def token(self):
        import jwt
        return jwt.encode(token_claims(self.issuer), self._key, algorithm='ES256',
                          headers=token_headers(self.key_id))

    def auth_flags(self):
        """xcodebuild flags that sign and upload with this key, no Apple ID needed."""
        return ['-allowProvisioningUpdates', '-authenticationKeyPath', os.path.abspath(self.key_path),
                '-authenticationKeyID', self.key_id, '-authenticationKeyIssuerID', self.issuer]

    def call(self, method, path, body=None, ok=(200, 201, 204)):
        request = urllib.request.Request(API + path, method=method,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={'Authorization': 'Bearer ' + self.token(),
                                                  'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, context=self._context, timeout=60) as response:
                raw, status = response.read(), response.status
        except urllib.error.HTTPError as error:
            raw, status = error.read(), error.code
        except urllib.error.URLError as error:
            die(f'{method} {path} unreachable: {error.reason}')
        data = json.loads(raw) if raw else {}
        if status not in ok:
            details = '; '.join(e.get('detail') or e.get('title', '') for e in data.get('errors', []))
            die(f'{method} {path} -> {status}: {details or raw[:300]}')
        return data

    def get(self, path):
        return self.call('GET', path)

    def get_all(self, path, limit=None):
        """Follow `links.next` until the list ends (or `limit` items are in hand)."""
        items = []
        while path:
            page = self.get(path)
            items.extend(page.get('data') or [])
            if limit and len(items) >= limit:
                return items[:limit]
            following = (page.get('links') or {}).get('next')
            path = following[len(API):] if following and following.startswith(API) else None
        return items

    def get_all_with_included(self, path):
        """Like get_all, but also keeps every page's `included` records.

        Each page carries only the included records its own data points at, so
        keeping just the first page's silently loses the rest."""
        items, included = [], []
        while path:
            page = self.get(path)
            items.extend(page.get('data') or [])
            included.extend(page.get('included') or [])
            following = (page.get('links') or {}).get('next')
            path = following[len(API):] if following and following.startswith(API) else None
        return items, included

    # -- lookups every command needs ------------------------------------------------

    def app(self, bundle_id):
        """(app id, app name) for a bundle id, or die saying which key could not see it."""
        query = urllib.parse.quote(bundle_id, safe='')
        apps = self.get(f'/v1/apps?filter[bundleId]={query}&fields[apps]=name,bundleId&limit=1')['data']
        if not apps:
            die(f'no app with bundle id {bundle_id} visible to key {self.key_id}')
        return apps[0]['id'], apps[0]['attributes'].get('name', bundle_id)

    def build_versions(self, app_id, limit=200):
        # Sorted by upload date, not by version (see next_build_from_versions).
        builds = self.get(f'/v1/builds?filter[app]={app_id}&sort=-uploadedDate&limit={limit}'
                          '&fields[builds]=version')['data']
        return [(b.get('attributes') or {}).get('version') for b in builds]

    def next_build_number(self, app_id):
        return next_build_from_versions(self.build_versions(app_id))

    def find_build(self, app_id, version, build, fields='processingState'):
        return self.get(f'/v1/builds?filter[app]={app_id}&filter[version]={build}'
                        f'&filter[preReleaseVersion.version]={version}&fields[builds]={fields}')['data']

    def store_versions(self, app_id, platform='IOS', limit=10):
        return self.get(f'/v1/apps/{app_id}/appStoreVersions?filter[platform]={platform}&limit={limit}'
                        '&fields[appStoreVersions]=versionString,appStoreState,createdDate')['data']
