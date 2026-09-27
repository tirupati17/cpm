"""Google OAuth and JSON-over-HTTPS for the toolkit's Google helpers. Standard library only.

Two ways to get an access token:

    token = google.token_from_refresh(client_id, client_secret, refresh_token)
    token = google.token_from_service_account(key_file, scopes)

The second signs a JWT with RS256. It uses the `cryptography` package when it is
installed and falls back to the `openssl` binary otherwise, so nothing needs
installing on a normal macOS or Linux machine.

Then `google.call(method, url, token=token, body=...)` returns parsed JSON and
raises GoogleError with Google's own message on any HTTP error. Tokens, keys and
request bodies are never printed.
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from cpmkit.http import ssl_context

TOKEN_URL = 'https://oauth2.googleapis.com/token'
CLOUD_SCOPE = 'https://www.googleapis.com/auth/cloud-platform'
TIMEOUT = 60


class GoogleError(Exception):
    def __init__(self, status, message, payload=None):
        super().__init__(f'HTTP {status}: {message}')
        self.status = status
        self.message = message
        self.payload = payload or {}


def _describe(payload, raw):
    """Pull the useful sentence out of a Google error body, including Ads failure details."""
    error = payload.get('error') if isinstance(payload, dict) else None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        error = payload[0].get('error')  # searchStream wraps errors in a list
    if not isinstance(error, dict):
        if isinstance(payload, dict) and payload.get('error_description'):
            return f"{payload.get('error')}: {payload['error_description']}"
        return (raw or '').strip()[:500] or 'no body'
    parts = [error.get('message') or error.get('status') or 'error']
    for detail in error.get('details') or []:
        for failure in detail.get('errors') or []:  # GoogleAdsFailure
            code = failure.get('errorCode') or {}
            kind = ', '.join(f'{k}={v}' for k, v in code.items())
            parts.append(f"  {kind}: {failure.get('message', '')}".rstrip())
        if detail.get('reason'):  # google.rpc.ErrorInfo
            parts.append(f"  reason={detail['reason']} {json.dumps(detail.get('metadata') or {})}")
    return '\n'.join(parts)


def call(method, url, token=None, body=None, headers=None, form=None, timeout=TIMEOUT):
    """One HTTPS request. JSON in (body) or form-encoded (form), JSON out."""
    head = {'Accept': 'application/json', 'User-Agent': 'cpm-toolkit'}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        head['Content-Type'] = 'application/x-www-form-urlencoded'
    elif body is not None:
        data = json.dumps(body).encode()
        head['Content-Type'] = 'application/json'
    if token:
        head['Authorization'] = f'Bearer {token}'
    head.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            raw = response.read().decode('utf-8')
    except urllib.error.HTTPError as err:
        raw = err.read().decode('utf-8', 'replace')
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        raise GoogleError(err.code, _describe(payload, raw), payload) from None
    except urllib.error.URLError as err:
        raise GoogleError(0, f'could not reach {urllib.parse.urlsplit(url).netloc}: {err.reason}') from None
    return json.loads(raw) if raw.strip() else {}


def token_from_refresh(client_id, client_secret, refresh_token):
    try:
        reply = call('POST', TOKEN_URL, form={
            'grant_type': 'refresh_token', 'client_id': client_id,
            'client_secret': client_secret, 'refresh_token': refresh_token})
    except GoogleError as err:
        if 'invalid_grant' in err.message:
            raise SystemExit('Google refused the refresh token (invalid_grant). It was revoked, or it '
                             'expired: tokens from an OAuth consent screen left in "Testing" last 7 days. '
                             'Publish the consent screen (In production) and mint a new one.') from None
        raise
    return reply['access_token']


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _sign_rs256(pem, message):
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        openssl = shutil.which('openssl')
        if not openssl:
            raise SystemExit('Signing a service-account token needs the `cryptography` package or the '
                             '`openssl` binary. Install one: python3 -m pip install cryptography') from None
        with tempfile.TemporaryDirectory() as scratch:
            key_path = os.path.join(scratch, 'key.pem')
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(pem)
            done = subprocess.run([openssl, 'dgst', '-sha256', '-sign', key_path],
                                  input=message, capture_output=True, check=False)
        if done.returncode:
            raise SystemExit('openssl could not sign with the service account key.')
        return done.stdout
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    return key.sign(message, padding.PKCS1v15(), hashes.SHA256())


def read_service_account(key_file):
    with open(key_file, encoding='utf-8') as handle:
        info = json.load(handle)
    missing = [k for k in ('client_email', 'private_key') if not info.get(k)]
    if info.get('type') != 'service_account' or missing:
        raise SystemExit(f'{key_file} is not a service account key (type={info.get("type")!r}). '
                         'An OAuth client secret JSON looks similar and does not work here.')
    return info


def service_account_assertion(info, scopes, now=None):
    now = int(now or time.time())
    header = {'alg': 'RS256', 'typ': 'JWT'}
    if info.get('private_key_id'):
        header['kid'] = info['private_key_id']
    claims = {'iss': info['client_email'], 'scope': ' '.join(scopes),
              'aud': info.get('token_uri') or TOKEN_URL, 'iat': now, 'exp': now + 3600}
    signing_input = f'{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}'
    signature = _sign_rs256(info['private_key'], signing_input.encode())
    return f'{signing_input}.{_b64(signature)}'


def token_from_service_account(key_file, scopes=(CLOUD_SCOPE,)):
    info = read_service_account(key_file)
    assertion = service_account_assertion(info, list(scopes))
    reply = call('POST', info.get('token_uri') or TOKEN_URL, form={
        'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion})
    return reply['access_token']


def table(rows, columns, headers=None):
    """Plain aligned text table. rows are dicts; missing cells print as ''."""
    headers = headers or columns
    cells = [[str(row.get(c, '')) for c in columns] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    lines = ['  '.join(h.ljust(w) for h, w in zip(headers, widths)).rstrip(),
             '  '.join('-' * w for w in widths)]
    lines += ['  '.join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in cells]
    return '\n'.join(lines)
