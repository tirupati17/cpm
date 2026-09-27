import contextlib
import io
import unittest

from apifake import ApiCase
from cpmkit import http

URL = 'https://api.example.com/v1/things'
KEY = 'sk_live_supersecretvalue123'


class HttpTest(ApiCase):
    def test_json_round_trip_and_headers(self):
        self.route(('POST', '/v1/things', 200, {'ok': True}))
        reply = http.request('POST', URL, headers={'Authorization': f'Bearer {KEY}'},
                             params={'a': 1, 'skip': None}, body={'name': 'x'})
        self.assertEqual(reply, {'ok': True})
        call = self.http.calls[0]
        self.assertEqual(call['body'], {'name': 'x'})
        self.assertEqual(self.http.query(call), {'a': '1'})
        self.assertEqual(call['headers']['Content-type'], 'application/json')
        self.assertTrue(call['headers']['User-agent'].startswith('cpm-toolkit/'))

    def test_empty_and_text_bodies(self):
        self.route(('DELETE', '/v1/things', 200, b''), ('GET', '/v1/things', 200, b'plain'))
        self.assertEqual(http.request('DELETE', URL), {})
        self.assertEqual(http.request('GET', URL), 'plain')

    def test_error_carries_status_and_body_but_never_the_key(self):
        self.route(('GET', '/v1/things', 401, {'message': f'bad key {KEY}'}))
        with self.assertRaises(http.ApiError) as caught:
            http.request('GET', URL + '?token=abc', headers={'Authorization': f'Bearer {KEY}'})
        err = caught.exception
        self.assertIsInstance(err, SystemExit)
        self.assertEqual(err.status, 401)
        self.assertEqual(err.payload['message'], f'bad key {KEY}')
        self.assertIn('HTTP 401', err.message)
        self.assertIn('GET https://api.example.com/v1/things', err.message)
        self.assertNotIn(KEY, err.message)
        self.assertNotIn('token=abc', err.message)

    def test_basic_auth_value_is_scrubbed(self):
        auth = http.basic('api', 'secretsecret')
        self.route(('GET', '/v1/things', 500, {'echo': auth}))
        with self.assertRaises(http.ApiError) as caught:
            http.request('GET', URL, headers={'Authorization': auth})
        self.assertNotIn(auth.split(' ')[1], caught.exception.message)

    def test_429_retries_honouring_retry_after(self):
        self.route(('GET', '/v1/things', [429, 429, 200], {'ok': 1}, {'Retry-After': '7'}))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(http.request('GET', URL), {'ok': 1})
        self.assertEqual(len(self.http.calls), 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [7.0, 7.0])

    def test_429_gives_up_after_retries(self):
        self.route(('GET', '/v1/things', [429], {'error': 'slow down'}))
        with self.assertRaises(http.ApiError) as caught, contextlib.redirect_stderr(io.StringIO()):
            http.request('GET', URL, retries=2)
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(len(self.http.calls), 3)

    def test_5xx_is_not_retried(self):
        self.route(('POST', '/v1/things', 503, {'error': 'down'}))
        with self.assertRaises(http.ApiError):
            http.request('POST', URL, body={})
        self.assertEqual(len(self.http.calls), 1)

    def test_retry_after_parsing(self):
        self.assertEqual(http._wait('3', 0), 3.0)
        self.assertEqual(http._wait('9999', 0), http.MAX_WAIT)
        self.assertEqual(http._wait(None, 2), 4)
        self.assertEqual(http._wait('Wed, 21 Oct 2015 07:28:00 GMT', 0), 0.0)
        self.assertEqual(http._wait('garbage', 1), 2)


if __name__ == '__main__':
    unittest.main()
