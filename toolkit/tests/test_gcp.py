import base64
import json
import os
import stat
import tempfile
from pathlib import Path

from _support import ServiceTest, creds, load

gcp = load('gcp', '_gcp')
whoami = load('gcp', 'whoami')
apis = load('gcp', 'apis')
accounts = load('gcp', 'service-accounts')

EMAIL = 'bot@home-proj.iam.gserviceaccount.com'
KEY_JSON = {'type': 'service_account', 'client_email': 'new@demo.iam.gserviceaccount.com',
            'private_key': '-----BEGIN PRIVATE KEY-----\nTOP-SECRET-MATERIAL\n-----END PRIVATE KEY-----\n'}


class GcpTest(ServiceTest):
    def setUp(self):
        super().setUp()
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump({'type': 'service_account', 'client_email': EMAIL, 'private_key': 'unused',
                   'project_id': 'home-proj', 'private_key_id': 'kid-should-not-print'}, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        os.environ.update(GCP_PROJECT_ID='demo-proj', GCP_SERVICE_ACCOUNT_JSON=handle.name)

    def client(self):
        return gcp.Client(token='access')

    def test_whoami_offline_notes_foreign_key(self):
        out = self.run_cmd(whoami, ['--offline'], client=self.client())
        self.assertIn(EMAIL, out)
        self.assertIn('target project   demo-proj', out)
        self.assertIn('belongs to another project', out)
        self.assertNotIn('kid-should-not-print', out)

    def test_whoami_reports_project_and_roles(self):
        policy = {'bindings': [{'role': 'roles/viewer', 'members': [f'serviceAccount:{EMAIL}']},
                               {'role': 'roles/owner', 'members': ['user:someone@example.com']}]}
        fake = self.fake([(('GET', '/v3/projects/demo-proj'), {'displayName': 'Demo', 'name': 'projects/42',
                                                               'state': 'ACTIVE'}),
                          (('POST', 'projects/demo-proj:getIamPolicy'), policy)])
        out = self.run_cmd(whoami, [], client=self.client())
        self.assertIn('project number   42', out)
        self.assertIn('roles            roles/viewer', out)
        self.assertNotIn('roles/owner', out)
        self.assertEqual(fake.calls[0]['token'], 'access')

    def test_gcp_project_override(self):
        client = gcp.Client('other-proj', token='t')
        self.assertEqual(client.project, 'other-proj')
        self.assertNotIn('--project', [a for action in gcp.parser('x')._actions for a in action.option_strings])

    def test_apis_lists_every_page(self):
        def services(body, url):
            if 'pageToken=p2' in url:
                return {'services': [{'name': 'projects/1/services/iam.googleapis.com',
                                      'config': {'name': 'iam.googleapis.com'}}]}
            return {'services': [{'name': 'projects/1/services/androidpublisher.googleapis.com'}],
                    'nextPageToken': 'p2'}
        fake = self.fake([(('GET', 'services?filter=state:ENABLED'), services)])
        out = self.run_cmd(apis, [], client=self.client())
        self.assertIn('2 enabled on demo-proj', out)
        self.assertIn('androidpublisher.googleapis.com\niam.googleapis.com', out)
        self.assertEqual(len(fake.calls), 2)

    def test_enable_is_a_dry_run_until_commit(self):
        routes = [(('GET', 'services/googleads.googleapis.com'), {'state': 'DISABLED',
                                                                  'config': {'title': 'Google Ads API'}}),
                  (('POST', 'googleads.googleapis.com:enable'), {'done': True})]
        fake = self.fake(routes)
        out = self.run_cmd(apis, ['enable', 'googleads'], client=self.client())
        self.assertIn('DISABLED -> ENABLED', out)
        self.assertEqual([c['method'] for c in fake.calls], ['GET'])
        out = self.run_cmd(apis, ['enable', 'googleads', '--commit'], client=self.client())
        self.assertIn('Enabled.', out)
        self.assertEqual(fake.calls[-1]['method'], 'POST')

    def test_enable_already_on(self):
        fake = self.fake([(('GET', 'services/iam.googleapis.com'), {'state': 'ENABLED'})])
        out = self.run_cmd(apis, ['enable', 'iam.googleapis.com', '--commit'], client=self.client())
        self.assertIn('already enabled', out)
        self.assertEqual(len(fake.calls), 1)

    def test_list_accounts_and_keys(self):
        self.fake([(('GET', '/serviceAccounts?pageSize'), {'accounts': [{'email': EMAIL, 'displayName': 'Bot'}]}),
                   (('GET', f'serviceAccounts/{EMAIL}/keys'), {'keys': [
                       {'name': f'projects/p/serviceAccounts/{EMAIL}/keys/abcdef1234567890',
                        'validAfterTime': '2020-01-02T00:00:00Z', 'validBeforeTime': '9999-12-31T23:59:59Z'}]})])
        out = self.run_cmd(accounts, [], client=self.client())
        self.assertIn(EMAIL, out)
        out = self.run_cmd(accounts, ['keys', EMAIL], client=self.client())
        self.assertIn('abcdef123456', out)
        self.assertIn('1 user-managed key(s)', out)

    def test_key_create_is_guarded_saved_private_and_never_printed(self):
        created = {'name': f'projects/p/serviceAccounts/{EMAIL}/keys/feedface0000',
                   'privateKeyData': base64.b64encode(json.dumps(KEY_JSON).encode()).decode()}
        fake = self.fake([(('GET', '/keys?keyTypes'), {'keys': []}),
                          (('POST', f'serviceAccounts/{EMAIL}/keys'), created)])
        out = self.run_cmd(accounts, ['key-create', EMAIL], client=self.client())
        self.assertIn('Dry run', out)
        self.assertNotIn('POST', [c['method'] for c in fake.calls])

        out = self.run_cmd(accounts, ['key-create', EMAIL, '--commit', '--save-as', 'PLAY_SERVICE_ACCOUNT_JSON'],
                           client=self.client())
        self.assertEqual(fake.calls[-1]['body']['privateKeyType'], 'TYPE_GOOGLE_CREDENTIALS_FILE')
        self.assertNotIn('TOP-SECRET-MATERIAL', out)
        self.assertNotIn(created['privateKeyData'][:40], out)
        path = Path(creds.load()['PLAY_SERVICE_ACCOUNT_JSON'])
        self.assertTrue(str(path).startswith(self.home.name))
        self.assertEqual(path.parent.name, 'keys')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text())['private_key'], KEY_JSON['private_key'])

    def test_errors_explain_disabled_api_and_missing_role(self):
        from cpmkit import google
        client = self.client()
        text = gcp.explain(google.GoogleError(403, 'Cloud Resource Manager API has not been used in project 1'), client)
        self.assertIn('API is off', text)
        text = gcp.explain(google.GoogleError(403, 'Permission denied'), client)
        self.assertIn(f'{EMAIL} lacks a role', text)
