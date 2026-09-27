#!/usr/bin/env python3
"""Sign in with Google in the browser and save a Google Ads refresh token.

Uses the installed-app (loopback) OAuth flow with PKCE: a one-shot server on
127.0.0.1 receives the code, which is swapped for a refresh token and saved as
GOOGLE_ADS_REFRESH_TOKEN. Nothing secret is printed.

Needs GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET from a *Desktop app*
OAuth client. Sign in as a Google user with access to the Ads account.
If the OAuth consent screen is still in Testing, the token dies after 7 days.
"""
import base64
import hashlib
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import _ads
from cpmkit import creds, google

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'


def authorize_url(client_id, redirect_uri, state, challenge):
    return AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
        'scope': _ads.SCOPE, 'access_type': 'offline',
        # prompt=consent forces Google to return a refresh token even if this user
        # already granted the app once; without it the second run gets none.
        'prompt': 'consent', 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})


def pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def wait_for_code(server, timeout):
    """Serve until Google redirects back; returns the query parameters."""
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if 'code' not in query and 'error' not in query:
                self.send_response(404)
                self.end_headers()
                return
            result.update(query)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            message = 'Signed in. You can close this tab.' if 'code' in query else 'Sign-in was cancelled.'
            self.wfile.write(f'<p style="font-family:sans-serif">{message}</p>'.encode())

        def log_message(self, *args):
            pass

    server.RequestHandlerClass = Handler
    server.timeout = 1
    waited = 0
    while not result and waited < timeout:
        server.handle_request()
        waited += 1
    return result


def exchange(client_id, client_secret, code, verifier, redirect_uri):
    return google.call('POST', google.TOKEN_URL, form={
        'grant_type': 'authorization_code', 'code': code, 'client_id': client_id,
        'client_secret': client_secret, 'redirect_uri': redirect_uri, 'code_verifier': verifier})


def run(argv):
    p = _ads.argparse.ArgumentParser(description=__doc__.strip().splitlines()[0], epilog=__doc__,
                                     formatter_class=_ads.argparse.RawDescriptionHelpFormatter)
    p.add_argument('--no-browser', action='store_true', help='print the sign-in URL instead of opening it')
    p.add_argument('--port', type=int, default=0, help='loopback port (default: any free port)')
    p.add_argument('--timeout', type=int, default=300, help='seconds to wait for the browser (default 300)')
    args = p.parse_args(argv)

    client_id = creds.get('GOOGLE_ADS_CLIENT_ID')
    client_secret = creds.get('GOOGLE_ADS_CLIENT_SECRET')
    server = http.server.HTTPServer(('127.0.0.1', args.port), http.server.BaseHTTPRequestHandler)
    redirect_uri = f'http://127.0.0.1:{server.server_port}'
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce()
    url = authorize_url(client_id, redirect_uri, state, challenge)

    print('Open this URL, sign in as a user with access to the Ads account, and allow access:\n', file=sys.stderr)
    print(url + '\n', file=sys.stderr)
    if not args.no_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    print(f'Waiting for Google to redirect to {redirect_uri} ...', file=sys.stderr)
    try:
        reply = wait_for_code(server, args.timeout)
    finally:
        server.server_close()

    if not reply:
        raise SystemExit('Timed out waiting for the browser. Re-run, or pass --timeout.')
    if reply.get('error'):
        raise SystemExit(f'Google returned {reply["error"]}. If it says access_denied and the consent screen '
                         'is in Testing, add this Google account as a test user.')
    if reply.get('state') != state:
        raise SystemExit('The redirect did not carry our state value. Not using it.')
    try:
        tokens = exchange(client_id, client_secret, reply['code'], verifier, redirect_uri)
    except google.GoogleError as err:
        raise SystemExit(f'Token exchange failed: {err}') from None
    refresh = tokens.get('refresh_token')
    if not refresh:
        raise SystemExit('Google returned no refresh token. Revoke the app at '
                         'myaccount.google.com/permissions and run this again.')
    creds.save('GOOGLE_ADS_REFRESH_TOKEN', refresh)
    print(f'Saved GOOGLE_ADS_REFRESH_TOKEN for project {creds.project_name()} ({len(refresh)} chars).')
    print('Check it with: cpm googleads accounts')
    return 0


if __name__ == '__main__':
    _ads.main(run)
