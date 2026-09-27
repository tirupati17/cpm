import datetime
import unittest

from apifake import ApiCase

ENTS = {'items': [{'id': 'entl1', 'lookup_key': 'pro', 'display_name': 'Pro'}], 'next_page': None}


class RevenueCatTest(ApiCase):
    ENV = {'REVENUECAT_API_KEY': 'sk_v2_secretkey_abcdef', 'REVENUECAT_PROJECT_ID': 'proj123'}

    def test_metrics_table(self):
        self.route(('GET', '/v2/projects/proj123/metrics/overview', 200, {'metrics': [
            {'id': 'mrr', 'name': 'MRR', 'value': 1234.5, 'unit': '$', 'period': 'P28D'},
            {'id': 'active_subscriptions', 'name': 'Active Subscriptions', 'value': 42, 'unit': '#'}]}))
        code, out, _ = self.run_cmd('revenuecat', 'metrics', [])
        self.assertEqual(code, 0)
        self.assertIn('$1,234.50', out)
        self.assertIn('Active Subscriptions', out)
        self.assertEqual(self.http.calls[0]['headers']['Authorization'], 'Bearer sk_v2_secretkey_abcdef')

    def test_products_follow_pagination(self):
        self.route(('GET', 'starting_after=p1', 200, {'items': [{'id': 'p2', 'store_identifier': 'yearly'}]}),
                   ('GET', '/v2/projects/proj123/products', 200, {
                       'items': [{'id': 'p1', 'store_identifier': 'monthly', 'type': 'subscription'}],
                       'next_page': '/v2/projects/proj123/products?starting_after=p1'}))
        code, out, _ = self.run_cmd('revenuecat', 'products', [])
        self.assertEqual(code, 0)
        self.assertIn('monthly', out)
        self.assertIn('yearly', out)
        self.assertIn('2 products', out)

    def test_customer_summary_and_case_sensitive_404(self):
        self.route(
            ('GET', '/customers/user%2F1/subscriptions', 200, {'items': [
                {'product_id': 'p1', 'store': 'play_store', 'status': 'active', 'gives_access': True,
                 'current_period_ends_at': 1790000000000}]}),
            ('GET', '/customers/user%2F1/purchases', 200, {'items': []}),
            ('GET', '/customers/user%2F1', 200, {'id': 'user/1', 'first_seen_at': 1700000000000,
                                                 'active_entitlements': {'items': [
                                                     {'entitlement_id': 'entl1', 'expires_at': None}]}}),
            ('GET', '/entitlements', 200, ENTS),
            ('GET', '/products', 200, {'items': [{'id': 'p1', 'store_identifier': 'monthly:base'}]}),
            ('GET', '/customers/ABC', 404, {'message': 'not found'}))
        code, out, _ = self.run_cmd('revenuecat', 'customer', ['user/1'])
        self.assertEqual(code, 0)
        self.assertIn('pro', out)
        self.assertIn('never', out)
        self.assertIn('monthly:base', out)
        code, _, err = self.run_cmd('revenuecat', 'customer', ['ABC'])
        self.assertEqual(code, 1)
        self.assertIn('case-sensitive', err)

    def test_grant_dry_run_sends_nothing(self):
        self.route(('GET', '/entitlements', 200, ENTS))
        now = datetime.datetime(2026, 1, 31, tzinfo=datetime.timezone.utc)
        code, out, _ = self.run_cmd('revenuecat', 'grant', ['u1', 'pro', '--duration', 'monthly'], now=now)
        self.assertEqual(code, 0)
        self.assertIn('DRY RUN', out)
        self.assertIn('2026-02-28', out)  # month arithmetic clamps to the month's last day
        self.assertEqual(self.http.by('POST'), [])

    def test_grant_v2_commit(self):
        self.route(('GET', '/entitlements', 200, ENTS),
                   ('POST', '/v2/projects/proj123/customers/u1/actions/grant_entitlement', 201, {}))
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        code, out, _ = self.run_cmd('revenuecat', 'grant', ['u1', 'Pro', '--duration', 'weekly', '--commit'], now=now)
        self.assertEqual(code, 0)
        post = self.http.by('POST')[0]
        expected = int(datetime.datetime(2026, 1, 8, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        self.assertEqual(post['body'], {'entitlement_id': 'entl1', 'expires_at': expected})

    def test_grant_lifetime_uses_v1_with_v1_key(self):
        import os
        os.environ['REVENUECAT_V1_API_KEY'] = 'sk_v1_legacykey_zzz'
        self.route(('GET', '/entitlements', 200, ENTS),
                   ('POST', '/v1/subscribers/u1/entitlements/pro/promotional', 200, {}))
        code, out, _ = self.run_cmd('revenuecat', 'grant', ['u1', 'entl1', '--duration', 'lifetime', '--commit'])
        self.assertEqual(code, 0)
        self.assertNotIn('sk_v1_legacykey_zzz', out)
        post = self.http.by('POST')[0]
        self.assertEqual(post['body'], {'duration': 'lifetime'})
        self.assertEqual(post['headers']['Authorization'], 'Bearer sk_v1_legacykey_zzz')

    def test_grant_rejects_v2_lifetime_and_unknown_entitlement(self):
        code, _, err = self.run_cmd('revenuecat', 'grant', ['u1', 'pro', '--duration', 'lifetime', '--api', 'v2'])
        self.assertEqual(code, 1)
        self.assertIn('v2 grants need an end date', err)
        self.route(('GET', '/entitlements', 200, ENTS))
        code, _, err = self.run_cmd('revenuecat', 'grant', ['u1', 'wallet', '--duration', 'daily'])
        self.assertIn("No entitlement 'wallet'", err)

    def test_offerings_fall_back_when_expand_refused(self):
        self.route(('GET', 'expand=items.package.product', 400, {'message': 'bad expand'}),
                   ('GET', '/offerings', 200, {'items': [
                       {'lookup_key': 'sale', 'is_current': True, 'packages': {'items': [
                           {'lookup_key': '$rc_monthly', 'products': {'items': [
                               {'product': {'store_identifier': 'monthly'}}]}}]}}]}))
        code, out, _ = self.run_cmd('revenuecat', 'offerings', [])
        self.assertEqual(code, 0)
        self.assertIn('* sale', out)
        self.assertIn('$rc_monthly', out)

    def test_missing_credentials_say_how_to_fix(self):
        import os
        del os.environ['REVENUECAT_PROJECT_ID']
        code, _, err = self.run_cmd('revenuecat', 'products', [])
        self.assertEqual(code, 1)
        self.assertIn('cpm creds set REVENUECAT_PROJECT_ID', err)
        self.assertEqual(self.http.calls, [])


if __name__ == '__main__':
    unittest.main()
