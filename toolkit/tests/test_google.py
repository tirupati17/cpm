import base64
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

import _support  # noqa: F401  (puts toolkit/lib on sys.path)
from cpmkit import google


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status, payload):
    return urllib.error.HTTPError('https://x', status, 'err', {}, io.BytesIO(json.dumps(payload).encode()))


class CallTest(unittest.TestCase):
    def test_json_round_trip_and_headers(self):
        seen = {}

        def urlopen(request, timeout, context=None):
            seen['request'] = request
            return Response(b'{"ok": true}')

        with mock.patch('urllib.request.urlopen', urlopen):
            reply = google.call('POST', 'https://api.test/x', token='tok', body={'a': 1},
                                headers={'developer-token': 'dev'})
        self.assertEqual(reply, {'ok': True})
        request = seen['request']
        self.assertEqual(request.get_header('Authorization'), 'Bearer tok')
        self.assertEqual(request.get_header('Developer-token'), 'dev')
        self.assertEqual(json.loads(request.data), {'a': 1})

    def test_ads_failure_details_are_surfaced(self):
        payload = [{'error': {'code': 403, 'message': 'The caller does not have permission', 'details': [{
            '@type': 'type.googleapis.com/google.ads.googleads.v22.errors.GoogleAdsFailure',
            'errors': [{'errorCode': {'authorizationError': 'DEVELOPER_TOKEN_NOT_APPROVED'},
                        'message': 'The developer token is only approved for use with test accounts.'}]}]}}]
        with mock.patch('urllib.request.urlopen', side_effect=http_error(403, payload)):
            with self.assertRaises(google.GoogleError) as caught:
                google.call('GET', 'https://api.test/x')
        self.assertEqual(caught.exception.status, 403)
        self.assertIn('authorizationError=DEVELOPER_TOKEN_NOT_APPROVED', caught.exception.message)

    def test_invalid_grant_explains_testing_consent_screen(self):
        error = http_error(400, {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'})
        with mock.patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(SystemExit) as caught:
                google.token_from_refresh('id', 'secret', 'refresh')
        self.assertIn('7 days', str(caught.exception))

    def test_table(self):
        text = google.table([{'a': 'x', 'b': 12}], ['a', 'b'], ['A', 'BEE'])
        self.assertEqual(text.splitlines(), ['A  BEE', '-  ---', 'x  12'])


def _key_pair():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        return None
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return key, pem


def _unb64(part):
    return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))


@unittest.skipIf(_key_pair() is None, 'cryptography not installed')
class ServiceAccountTest(unittest.TestCase):
    def setUp(self):
        self.key, pem = _key_pair()
        self.info = {'type': 'service_account', 'client_email': 'bot@demo.iam.gserviceaccount.com',
                     'private_key': pem, 'private_key_id': 'abc123', 'project_id': 'demo'}

    def verify(self, token):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        head, claims, sig = token.split('.')
        self.key.public_key().verify(_unb64(sig), f'{head}.{claims}'.encode(), padding.PKCS1v15(), hashes.SHA256())
        return json.loads(_unb64(head)), json.loads(_unb64(claims))

    def test_assertion_is_signed_and_scoped(self):
        head, claims = self.verify(google.service_account_assertion(self.info, [google.CLOUD_SCOPE], now=1000))
        self.assertEqual(head, {'alg': 'RS256', 'typ': 'JWT', 'kid': 'abc123'})
        self.assertEqual(claims['iss'], 'bot@demo.iam.gserviceaccount.com')
        self.assertEqual(claims['aud'], google.TOKEN_URL)
        self.assertEqual(claims['exp'] - claims['iat'], 3600)

    @unittest.skipIf(not shutil.which('openssl'), 'openssl not installed')
    def test_openssl_fallback_signs_the_same_way(self):
        blocked = {name: None for name in ('cryptography.hazmat.primitives',
                                           'cryptography.hazmat.primitives.asymmetric')}
        with mock.patch.dict(sys.modules, blocked):
            token = google.service_account_assertion(self.info, [google.CLOUD_SCOPE])
        self.verify(token)

    def test_token_exchange_uses_jwt_bearer(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump(self.info, handle)
        self.addCleanup(os.unlink, handle.name)
        with mock.patch.object(google, 'call', return_value={'access_token': 'at'}) as call:
            self.assertEqual(google.token_from_service_account(handle.name), 'at')
        form = call.call_args.kwargs['form']
        self.assertEqual(form['grant_type'], 'urn:ietf:params:oauth:grant-type:jwt-bearer')
        self.verify(form['assertion'])

    def test_oauth_client_json_is_rejected(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump({'installed': {'client_id': 'x'}}, handle)
        self.addCleanup(os.unlink, handle.name)
        with self.assertRaises(SystemExit) as caught:
            google.read_service_account(handle.name)
        self.assertIn('OAuth client secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
