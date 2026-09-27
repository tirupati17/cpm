import contextlib
import io
import os
import threading
import urllib.parse
import urllib.request
from unittest import mock

from _support import ServiceTest, creds, load

ads = load('googleads', '_ads')
query = load('googleads', 'query')
campaigns = load('googleads', 'campaigns')
conversions = load('googleads', 'conversions')
budget = load('googleads', 'budget')
pause = load('googleads', 'pause')
enable = load('googleads', 'enable')
accounts = load('googleads', 'accounts')
auth = load('googleads', 'auth')

ENV = {'GOOGLE_ADS_DEVELOPER_TOKEN': 'devtoken-secret', 'GOOGLE_ADS_CUSTOMER_ID': '123-456-7890',
       'GOOGLE_ADS_LOGIN_CUSTOMER_ID': '999-888-7777', 'GOOGLE_ADS_CLIENT_ID': 'cid.apps.googleusercontent.com',
       'GOOGLE_ADS_CLIENT_SECRET': 'client-secret', 'GOOGLE_ADS_REFRESH_TOKEN': 'refresh-secret'}

CAMPAIGN = {'campaign': {'id': '111', 'name': "Brand 'search'", 'status': 'ENABLED',
                         'resourceName': 'customers/1234567890/campaigns/111'},
            'campaignBudget': {'resourceName': 'customers/1234567890/campaignBudgets/5', 'amountMicros': '10000000',
                               'explicitlyShared': False, 'referenceCount': '1'},
            'customer': {'currencyCode': 'USD'}}


def stream(*rows):
    return [{'results': list(rows), 'fieldMask': 'x'}]


class GoogleAdsTest(ServiceTest):
    ENV = ENV

    def routes(self, search, mutate=None):
        return [(('POST', 'oauth2.googleapis.com/token'), {'access_token': 'access'}),
                (('POST', 'googleAds:searchStream'), search),
                (('POST', ':mutate'), mutate or {'results': [{'resourceName': 'done/1'}]})]

    def test_ids_headers_and_version_in_one_place(self):
        fake = self.fake(self.routes(stream()))
        client = ads.Client()
        client.search('SELECT campaign.id FROM campaign')
        call = fake.calls[-1]
        self.assertEqual(call['url'], f'https://googleads.googleapis.com/{ads.API_VERSION}'
                                      '/customers/1234567890/googleAds:searchStream')
        self.assertEqual(call['headers'], {'developer-token': 'devtoken-secret', 'login-customer-id': '9998887777'})
        self.assertEqual(call['token'], 'access')
        self.assertEqual(fake.calls[0]['form']['grant_type'], 'refresh_token')
        os.environ['GOOGLE_ADS_API_VERSION'] = 'v99'
        client.search('SELECT campaign.id FROM campaign')
        self.assertIn('/v99/', fake.calls[-1]['url'])

    def test_bad_id_and_optional_login(self):
        with self.assertRaises(SystemExit):
            ads.clean_id('12a-456')
        del os.environ['GOOGLE_ADS_LOGIN_CUSTOMER_ID']
        self.assertNotIn('login-customer-id', ads.Client(token='t').headers())

    def test_query_prints_snake_case_fields_across_chunks(self):
        chunks = [{'results': [{'campaign': {'name': 'A'}, 'metrics': {'costMicros': '5'}}]},
                  {'results': [{'campaign': {'name': 'B'}, 'metrics': {'costMicros': '7'}}]}]
        self.fake(self.routes(chunks))
        out = self.run_cmd(query, ['SELECT campaign.name, metrics.cost_micros FROM campaign'])
        self.assertIn('campaign.name  metrics.cost_micros', out)
        self.assertIn('B              7', out)
        self.assertIn('2 row(s)', out)
        self.assertNotIn('secret', out)

    def test_campaigns_keeps_idle_campaigns_and_sums_metrics(self):
        idle = {'campaign': {'id': '222', 'name': 'Idle', 'status': 'PAUSED'},
                'campaignBudget': {'amountMicros': '2500000', 'explicitlyShared': True}}

        def search(body, url):
            if 'segments.date BETWEEN' in body['query']:
                return stream({'campaign': {'id': '111'}, 'metrics': {'costMicros': '1500000', 'clicks': '3',
                                                                      'impressions': '40', 'conversions': 1.5}})
            return stream(CAMPAIGN, idle)

        fake = self.fake(self.routes(search))
        out = self.run_cmd(campaigns, ['--days', '14', '--customer', '555-555-5555'])
        self.assertIn('/customers/5555555555/', fake.calls[-1]['url'])
        self.assertIn('10.00', out)
        self.assertIn('1.50', out)
        self.assertIn('2.50 (shared)', out)
        line = [l for l in out.splitlines() if l.startswith('222')][0]
        self.assertIn('0.00', line)

    def test_conversions_marks_imports_and_recent_counts(self):
        def search(body, url):
            if 'FROM customer' in body['query']:
                return stream({'segments': {'conversionAction': 'customers/1/conversionActions/7'},
                               'metrics': {'allConversions': 4.0}})
            return stream({'conversionAction': {'id': '7', 'name': 'purchase', 'status': 'ENABLED',
                                                'type': 'GOOGLE_ANALYTICS_4_PURCHASE', 'primaryForGoal': True}},
                          {'conversionAction': {'id': '8', 'name': 'Download', 'status': 'ENABLED',
                                                'type': 'GOOGLE_PLAY_DOWNLOAD', 'primaryForGoal': False}})
        self.fake(self.routes(search))
        out = self.run_cmd(conversions, [])
        purchase = [l for l in out.splitlines() if l.startswith('7 ')][0]
        download = [l for l in out.splitlines() if l.startswith('8 ')][0]
        self.assertIn('yes', purchase)
        self.assertTrue(purchase.rstrip().endswith('4.0'))
        self.assertTrue(download.rstrip().endswith('0.0'))
        self.assertNotIn('yes', download.split('GOOGLE_PLAY_DOWNLOAD')[1].replace('0.0', ''))

    def test_budget_dry_run_validates_only(self):
        fake = self.fake(self.routes(stream(CAMPAIGN)))
        out = self.run_cmd(budget, ["Brand 'search'", '12.345'])
        gaql = fake.bodies('searchStream')[0]['query']
        self.assertIn("campaign.name = 'Brand \\'search\\''", gaql)
        [body] = fake.bodies(':mutate')
        self.assertTrue(body['validateOnly'])
        self.assertEqual(body['operations'][0]['update']['amountMicros'], '12350000')
        self.assertEqual(body['operations'][0]['updateMask'], 'amount_micros')
        self.assertIn('campaignBudgets:mutate', fake.calls[-1]['url'])
        self.assertIn('10.00 -> 12.35 USD', out)
        self.assertIn('Nothing was changed', out)

    def test_budget_commit_and_shared_guard(self):
        fake = self.fake(self.routes(stream(CAMPAIGN)))
        self.run_cmd(budget, ['111', '20', '--commit'])
        self.assertNotIn('validateOnly', fake.bodies(':mutate')[0])
        self.assertIn('campaign.id = 111', fake.bodies('searchStream')[0]['query'])
        shared = dict(CAMPAIGN, campaignBudget=dict(CAMPAIGN['campaignBudget'], referenceCount='3'))
        self.fake(self.routes(stream(shared)))
        with self.assertRaises(SystemExit) as caught:
            self.run_cmd(budget, ['111', '20', '--commit'])
        self.assertIn('--shared-ok', str(caught.exception))

    def test_pause_enable_and_no_op(self):
        fake = self.fake(self.routes(stream(CAMPAIGN)))
        out = self.run_cmd(pause, ['111', '--no-validate'])
        self.assertEqual(fake.bodies(':mutate'), [])
        self.assertIn('ENABLED -> PAUSED', out)
        self.run_cmd(pause, ['111', '--commit'])
        op = fake.bodies(':mutate')[0]['operations'][0]
        self.assertEqual(op, {'update': {'resourceName': 'customers/1234567890/campaigns/111', 'status': 'PAUSED'},
                              'updateMask': 'status'})
        out = self.run_cmd(enable, ['111', '--commit'])
        self.assertIn('already ENABLED', out)
        self.assertEqual(len(fake.bodies(':mutate')), 1)

    def test_ambiguous_and_missing_campaign(self):
        self.fake(self.routes(stream(CAMPAIGN, CAMPAIGN)))
        with self.assertRaises(SystemExit) as caught:
            self.run_cmd(pause, ['Brand'])
        self.assertIn('Pass the id', str(caught.exception))
        self.fake(self.routes(stream()))
        with self.assertRaises(SystemExit):
            self.run_cmd(pause, ['Brand'])

    def test_api_errors_carry_hints(self):
        from cpmkit import google
        err = google.GoogleError(404, 'Not Found')
        self.assertIn('GOOGLE_ADS_API_VERSION', ads.explain(err))
        err = google.GoogleError(403, 'authorizationError=DEVELOPER_TOKEN_NOT_APPROVED: x')
        self.assertIn('Basic access', ads.explain(err))

    def test_accounts_lists_without_a_customer_id(self):
        del os.environ['GOOGLE_ADS_CUSTOMER_ID']
        routes = self.routes(stream({'customer': {'descriptiveName': 'Acme', 'manager': True,
                                                  'currencyCode': 'EUR', 'status': 'ENABLED'}}))
        routes.insert(0, (('GET', 'customers:listAccessibleCustomers'),
                          {'resourceNames': ['customers/1112223333']}))
        self.fake(routes)
        out = self.run_cmd(accounts, [])
        self.assertIn('1112223333  Acme  yes', out)


class AuthFlowTest(ServiceTest):
    ENV = {k: v for k, v in ENV.items() if k != 'GOOGLE_ADS_REFRESH_TOKEN'}

    def test_url_asks_for_offline_consent_with_pkce(self):
        verifier, challenge = auth.pkce()
        url = auth.authorize_url('cid', 'http://127.0.0.1:1', 'st', challenge)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertEqual(query['access_type'], 'offline')
        self.assertEqual(query['prompt'], 'consent')
        self.assertEqual(query['scope'], 'https://www.googleapis.com/auth/adwords')
        self.assertEqual(query['code_challenge_method'], 'S256')
        self.assertNotIn(verifier, url)

    def test_loopback_flow_saves_refresh_token_and_prints_none(self):
        """Drives the real 127.0.0.1 server; Google's token endpoint is faked."""
        def browser(url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            back = f"{query['redirect_uri']}/?code=the-code&state={query['state']}"
            threading.Timer(0.2, lambda: urllib.request.urlopen(back, timeout=5).read()).start()
            return True

        fake = self.fake([(('POST', 'oauth2.googleapis.com/token'),
                           {'access_token': 'a', 'refresh_token': '1//minted-refresh-value'})])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(auth.webbrowser, 'open', browser), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(auth.run(['--timeout', '10']), 0)
        form = fake.calls[0]['form']
        self.assertEqual(form['grant_type'], 'authorization_code')
        self.assertEqual(form['code'], 'the-code')
        self.assertTrue(form['code_verifier'])
        self.assertEqual(creds.load()['GOOGLE_ADS_REFRESH_TOKEN'], '1//minted-refresh-value')
        both = out.getvalue() + err.getvalue()
        self.assertNotIn('minted-refresh-value', both)
        self.assertNotIn('client-secret', both)

    def test_state_mismatch_is_refused(self):
        def browser(url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            back = f"{query['redirect_uri']}/?code=c&state=forged"
            threading.Timer(0.2, lambda: urllib.request.urlopen(back, timeout=5).read()).start()

        self.fake([])
        with mock.patch.object(auth.webbrowser, 'open', browser), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                auth.run(['--timeout', '10'])
        self.assertIn('state', str(caught.exception))
        self.assertNotIn('GOOGLE_ADS_REFRESH_TOKEN', creds.load())
