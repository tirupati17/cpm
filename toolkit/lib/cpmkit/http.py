"""JSON over HTTPS for the toolkit's API helpers. Standard library only.

    from cpmkit import http
    data = http.request('GET', 'https://api.example.com/v1/things',
                        headers={'Authorization': f'Bearer {key}'}, params={'limit': 20})
    http.request('POST', url, headers=..., body={'name': 'x'})

Returns the parsed JSON body ({} when the body is empty, the text when it is not
JSON). Any HTTP error raises ApiError, a SystemExit, so an uncaught one ends the
script with the method, path, status and the API's own error body. Callers that
expect a status (a 404 meaning "no such customer") catch ApiError and read
.status and .payload.

What it guards against, each learned the hard way:

  * 429 is retried, honouring Retry-After (seconds or an HTTP date, capped at
    60s), up to `retries` times. Nothing else is retried: a POST that failed
    with a 5xx may still have happened, and sending a push twice is worse than
    reporting an error once.
  * Auth header values never reach the terminal. They are scrubbed from every
    message, including an error body that echoes them back.
  * The query string is left out of error messages; it is noise at best and a
    credential at worst.
  * Requests carry a named User-Agent. Some edges (Vercel's among them) reject
    the default `Python-urllib/3.x` with a 403 that looks like an auth failure.
  * python.org builds of Python on macOS ship no root certificates, so urllib
    fails with CERTIFICATE_VERIFY_FAILED where curl works. certifi's bundle is
    used when installed; verification is never turned off.
"""
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

USER_AGENT = 'cpm-toolkit/1.0 (python-urllib)'
TIMEOUT = 60
MAX_WAIT = 60
SECRET_HEADERS = {'authorization', 'x-api-key', 'api-key', 'apikey', 'cookie', 'x-auth-token'}


class ApiError(SystemExit):
    """An HTTP call failed. A SystemExit, so it ends a script cleanly when not caught."""

    def __init__(self, message, status=None, payload=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload


def basic(user, password=''):
    """Value for an `Authorization: Basic` header."""
    return 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()


_SYSTEM_BUNDLES = ('/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt')


def ssl_context():
    """A verifying TLS context that works on a bare python.org macOS install.

    certifi when it is installed; otherwise the default store if it has any
    roots; otherwise the OS bundle that curl uses. Verification is never turned off.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    context = ssl.create_default_context()
    if not context.get_ca_certs() and not ssl.get_default_verify_paths().cafile:
        for bundle in _SYSTEM_BUNDLES:
            if os.path.isfile(bundle):
                return ssl.create_default_context(cafile=bundle)
    return context


def _secrets(headers):
    found = []
    for name, value in headers.items():
        if name.lower() in SECRET_HEADERS and value:
            found.append(value)
            scheme, _, token = value.partition(' ')
            if token:
                found.append(token)
    return sorted(set(found), key=len, reverse=True)


def scrub(text, secrets):
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, '[redacted]')
    return text


def _wait(value, attempt):
    """Seconds to wait from a Retry-After header, falling back to exponential backoff."""
    fallback = min(2 ** attempt, MAX_WAIT)
    if not value:
        return fallback
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return fallback
    return max(0.0, min(seconds, MAX_WAIT))


def _parse(raw):
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else (raw or '')
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return text


def _describe(payload, text):
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, ensure_ascii=False)[:800]
    return (text or '').strip()[:800] or 'no body'


def with_params(url, params):
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v is not None}
    if not clean:
        return url
    return url + ('&' if '?' in url else '?') + urllib.parse.urlencode(clean, doseq=True)


def request(method, url, *, headers=None, params=None, body=None, retries=3, timeout=TIMEOUT):
    """Send one request and return the parsed body. See the module docstring."""
    method = method.upper()
    url = with_params(url, params)
    sent = {'Accept': 'application/json', 'User-Agent': USER_AGENT}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        sent['Content-Type'] = 'application/json'
    sent.update(headers or {})
    secrets = _secrets(sent)
    parts = urllib.parse.urlsplit(url)
    where = f'{method} {parts.scheme}://{parts.netloc}{parts.path}'

    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method=method, headers=sent)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as response:
                return _parse(response.read())
        except urllib.error.HTTPError as err:
            raw = err.read() if err.fp is not None else b''
            if err.code == 429 and attempt < retries:
                wait = _wait(err.headers.get('Retry-After') if err.headers else None, attempt)
                print(f'  rate limited by {parts.netloc}, retrying in {wait:.0f}s', file=sys.stderr)
                time.sleep(wait)
                attempt += 1
                continue
            payload = _parse(raw)
            text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
            message = scrub(f'{where} failed: HTTP {err.code}: {_describe(payload, text)}', secrets)
            raise ApiError(message, status=err.code, payload=payload) from None
        except urllib.error.URLError as err:
            raise ApiError(scrub(f'{where} failed: {err.reason}', secrets)) from None
