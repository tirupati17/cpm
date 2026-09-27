import os
import unittest

from apifake import ApiCase


class OneSignalTest(ApiCase):
    ENV = {'ONESIGNAL_APP_ID': 'app-uuid-1', 'ONESIGNAL_REST_API_KEY': 'os_v2_app_restsecret123'}

    def test_dry_run_prints_payload_and_sends_nothing(self):
        code, out, _ = self.run_cmd('onesignal', 'send', ['--external-id', 'u1,u2', '--title', 'Hi',
                                                          '--body', 'Hello', '--url', 'app://x', '--data', 'k=v'])
        self.assertEqual(code, 0)
        self.assertIn('"external_id": [', out)
        self.assertIn('"u2"', out)
        self.assertIn('"k": "v"', out)
        self.assertIn('DRY RUN', out)
        self.assertEqual(self.http.calls, [])

    def test_send_commit_uses_key_scheme_and_idempotency(self):
        self.route(('POST', 'api.onesignal.com/notifications', 200, {'id': 'n1', 'recipients': 2}))
        code, out, _ = self.run_cmd('onesignal', 'send', ['--external-id', 'u1', '--body', 'Hello', '--commit'])
        self.assertEqual(code, 0)
        self.assertIn('sent n1', out)
        call = self.http.calls[0]
        self.assertEqual(call['headers']['Authorization'], 'Key os_v2_app_restsecret123')
        body = call['body']
        self.assertEqual(body['include_aliases'], {'external_id': ['u1']})
        self.assertEqual(body['target_channel'], 'push')
        self.assertEqual(body['app_id'], 'app-uuid-1')
        self.assertTrue(body['idempotency_key'])

    def test_legacy_key_uses_basic(self):
        os.environ['ONESIGNAL_REST_API_KEY'] = 'legacykeyvalue'
        self.route(('POST', '/notifications', 200, {'id': 'n1'}))
        self.run_cmd('onesignal', 'send', ['--segment', 'Total Subscriptions', '--body', 'x', '--commit'])
        self.assertEqual(self.http.calls[0]['headers']['Authorization'], 'Basic legacykeyvalue')
        self.assertEqual(self.http.calls[0]['body']['included_segments'], ['Total Subscriptions'])

    def test_200_with_errors_is_a_failure(self):
        self.route(('POST', '/notifications', 200, {'id': '', 'errors': ['All included players are not subscribed']}))
        code, _, err = self.run_cmd('onesignal', 'send', ['--external-id', 'nobody', '--body', 'x', '--commit'])
        self.assertEqual(code, 2)
        self.assertIn('not subscribed', err)

    def test_large_audience_is_batched(self):
        ids = ','.join(f'u{i}' for i in range(2500))
        code, out, _ = self.run_cmd('onesignal', 'send', ['--external-id', ids, '--body', 'x'])
        self.assertIn('2 request(s)', out)

    def test_audience_must_be_exactly_one(self):
        code, _, err = self.run_cmd('onesignal', 'send', ['--body', 'x'])
        self.assertEqual(code, 1)
        code, _, err = self.run_cmd('onesignal', 'send', ['--body', 'x', '--segment', 'A', '--external-id', 'u'])
        self.assertIn('exactly one audience', err)

    def test_notifications_list(self):
        self.route(('GET', '/notifications', 200, {'total_count': 7, 'notifications': [
            {'id': 'n1', 'headings': {'en': 'Hello'}, 'successful': 10, 'failed': 1, 'errored': 0,
             'converted': 3, 'queued_at': 1790000000}]}))
        code, out, _ = self.run_cmd('onesignal', 'notifications', ['--kind', 'api', '--limit', '500'])
        self.assertEqual(code, 0)
        self.assertIn('Hello', out)
        self.assertIn('1 of 7', out)
        query = self.http.query(self.http.calls[0])
        self.assertEqual(query, {'app_id': 'app-uuid-1', 'limit': '50', 'offset': '0', 'kind': '1'})

    def test_app_needs_org_key_and_flags_missing_android(self):
        code, _, err = self.run_cmd('onesignal', 'app', [])
        self.assertEqual(code, 1)
        self.assertIn('ONESIGNAL_ORG_API_KEY', err)
        os.environ['ONESIGNAL_ORG_API_KEY'] = 'os_v2_org_orgsecret'
        self.route(('GET', '/apps/app-uuid-1', 200, {'name': 'Demo', 'players': 100, 'messageable_players': 60,
                                                     'apns_env': 'production', 'apns_p8': 'x'}))
        code, out, _ = self.run_cmd('onesignal', 'app', [])
        self.assertEqual(code, 0)
        self.assertIn('Android push (FCM)   NOT configured', out)
        self.assertIn('yes (production)', out)
        self.assertNotIn('os_v2_org_orgsecret', out)
        self.assertEqual(self.http.calls[0]['headers']['Authorization'], 'Key os_v2_org_orgsecret')


if __name__ == '__main__':
    unittest.main()
