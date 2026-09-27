import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from cpmkit import creds


class CredsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ.update(CPM_CONFIG_HOME=self.home.name, CPM_NO_PROMPT='1', CPM_PROJECT='Demo App')
        for name in creds.NEEDS:
            os.environ.pop(name, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.home.cleanup()

    def test_project_slug_and_marker(self):
        self.assertEqual(creds.project_name(), 'demo-app')
        del os.environ['CPM_PROJECT']
        with tempfile.TemporaryDirectory() as repo:
            (Path(repo) / '.cpm-project').write_text('Acme\n')
            (Path(repo) / 'sub').mkdir()
            self.assertEqual(creds.project_name(start=Path(repo) / 'sub'), 'acme')

    def test_save_is_private_and_round_trips(self):
        creds.save('PLAY_PACKAGE', 'com.demo')
        creds.save('REVENUECAT_API_KEY', 'sk_abc=def')
        store = creds.project_dir() / 'credentials.env'
        self.assertEqual(stat.S_IMODE(store.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(creds.project_dir().stat().st_mode), 0o700)
        self.assertEqual(creds.get('REVENUECAT_API_KEY'), 'sk_abc=def')
        self.assertTrue(creds.unset('PLAY_PACKAGE'))
        self.assertNotIn('PLAY_PACKAGE', creds.load())

    def test_env_wins_over_store(self):
        creds.save('PLAY_PACKAGE', 'stored')
        os.environ['PLAY_PACKAGE'] = 'from-env'
        self.assertEqual(creds.get('PLAY_PACKAGE'), 'from-env')

    def test_missing_without_terminal_says_how_to_fix(self):
        with self.assertRaises(SystemExit) as caught:
            creds.get('ASC_KEY_ID')
        self.assertIn('cpm creds set ASC_KEY_ID --project demo-app', str(caught.exception))
        self.assertEqual(creds.get('AMPLITUDE_MANAGEMENT_KEY'), '')

    def test_key_file_is_copied_and_checked(self):
        with tempfile.NamedTemporaryFile('w', suffix='.p8', delete=False) as key:
            key.write('-----BEGIN PRIVATE KEY-----')
        copy = creds.keep_file('ASC_KEY_PATH', key.name)
        os.unlink(key.name)
        creds.save('ASC_KEY_PATH', copy)
        self.assertEqual(stat.S_IMODE(Path(copy).stat().st_mode), 0o600)
        self.assertEqual(creds.get('ASC_KEY_PATH'), copy)
        os.unlink(copy)
        with self.assertRaises(SystemExit):
            creds.get('ASC_KEY_PATH')

    def test_projects_are_separate(self):
        creds.save('PLAY_PACKAGE', 'one')
        os.environ['CPM_PROJECT'] = 'other'
        self.assertNotIn('PLAY_PACKAGE', creds.load())

    def test_mask_hides_secrets_only(self):
        self.assertNotIn('abcdefghij', creds.mask(creds.NEEDS['REVENUECAT_API_KEY'], 'sk_abcdefghij'))
        self.assertEqual(creds.mask(creds.NEEDS['PLAY_PACKAGE'], 'com.x'), 'com.x')


if __name__ == '__main__':
    unittest.main()
