"""Pure logic of the appstore commands. No network, no Xcode, no PyJWT needed."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

TOOLKIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLKIT / 'lib'))
sys.path.insert(0, str(TOOLKIT / 'services' / 'appstore'))
import _asc  # noqa: E402
import _xcode  # noqa: E402
import release  # noqa: E402

PBX = '''
/* app, Debug */
		buildSettings = {
				DEVELOPMENT_TEAM = TEAM123456;
				MARKETING_VERSION = 2.4.1;
				PRODUCT_BUNDLE_IDENTIFIER = com.example.App;
			};
/* widget: its id starts with the app's, and its version is the stale one */
		buildSettings = {
				MARKETING_VERSION = 1.0.7;
				PRODUCT_BUNDLE_IDENTIFIER = com.example.App.Widget;
			};
/* quoted id */
		buildSettings = {
				MARKETING_VERSION = "3.0";
				PRODUCT_BUNDLE_IDENTIFIER = "com.example.Other";
			};
'''


def version(state, name='1.0', vid='v1'):
    return {'id': vid, 'attributes': {'versionString': name, 'appStoreState': state}}


class FakeASC:
    """Answers GETs from a table and records writes. Never touches the network."""

    def __init__(self, versions, states=()):
        self.versions, self.states, self.writes = versions, list(states), []

    def store_versions(self, app_id, platform='IOS', limit=10):
        return self.versions

    def get(self, path):
        if path.startswith('/v1/reviewSubmissions'):
            return {'data': [{'id': 's1', 'attributes': {'state': 'WAITING_FOR_REVIEW'}}]}
        return {'data': {'attributes': {'appStoreState': self.states.pop(0)}}}

    def call(self, method, path, body=None):
        self.writes.append((method, path))
        return {'data': {'id': 'new', 'attributes': body['data']['attributes']}}


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class TokenTest(unittest.TestCase):
    def test_claims_shape(self):
        claims = _asc.token_claims('issuer-uuid', now=1_000)
        self.assertEqual(claims, {'iss': 'issuer-uuid', 'iat': 1000, 'exp': 2100, 'aud': 'appstoreconnect-v1'})
        # App Store Connect refuses tokens living longer than 20 minutes.
        self.assertLessEqual(claims['exp'] - claims['iat'], 20 * 60)

    def test_headers(self):
        self.assertEqual(_asc.token_headers('KEY1234567'), {'kid': 'KEY1234567', 'typ': 'JWT'})


class BuildNumberTest(unittest.TestCase):
    def test_numeric_max_not_string_order(self):
        self.assertEqual(_asc.next_build_from_versions(['9', '100', '11']), 101)

    def test_skips_dotted_and_missing(self):
        self.assertEqual(_asc.next_build_from_versions(['1.2.3', None, ' 42 ', 'abc']), 43)

    def test_first_build(self):
        self.assertEqual(_asc.next_build_from_versions([]), 1)


class ProjectTest(unittest.TestCase):
    def test_marketing_version_ignores_extension_with_prefix_id(self):
        self.assertEqual(_xcode.marketing_version(PBX, 'com.example.App'), '2.4.1')
        self.assertEqual(_xcode.marketing_version(PBX, 'com.example.App.Widget'), '1.0.7')
        self.assertEqual(_xcode.marketing_version(PBX, 'com.example.Other'), '3.0')
        self.assertIsNone(_xcode.marketing_version(PBX, 'com.example'))

    def test_development_team(self):
        self.assertEqual(_xcode.development_team(PBX, 'com.example.App'), 'TEAM123456')
        self.assertIsNone(_xcode.development_team(PBX, 'com.example.App.Widget'))

    def test_discovery(self):
        with tempfile.TemporaryDirectory() as root:
            schemes = Path(root, 'App.xcodeproj', 'xcshareddata', 'xcschemes')
            schemes.mkdir(parents=True)
            for name in ('App', 'AppWidget'):
                (schemes / f'{name}.xcscheme').write_text('')
            Path(root, 'App.xcodeproj', 'project.pbxproj').write_text(PBX)
            kind, container = _xcode.find_container(root)
            self.assertEqual((kind, os.path.basename(container)), ('project', 'App.xcodeproj'))
            self.assertEqual(_xcode.pick_scheme(container), 'App')
            self.assertEqual(_xcode.pick_scheme(container, 'AppWidget'), 'AppWidget')
            self.assertTrue(_xcode.pbxproj_path(root).endswith('App.xcodeproj/project.pbxproj'))
            # A workspace wins; the project's schemes still count.
            Path(root, 'Suite.xcworkspace').mkdir()
            kind, workspace = _xcode.find_container(root)
            self.assertEqual(kind, 'workspace')
            self.assertEqual(_xcode.pick_scheme([workspace, container]), 'App')
            # No scheme named after the container: the only one is fine, two are ambiguous.
            (schemes / 'App.xcscheme').unlink()
            self.assertEqual(_xcode.pick_scheme(container), 'AppWidget')
            (schemes / 'AppTests.xcscheme').write_text('')
            with self.assertRaises(SystemExit) as caught:
                _xcode.pick_scheme(container)
            self.assertIn('--scheme', str(caught.exception))

    def test_two_projects_need_a_flag(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ('A', 'B'):
                Path(root, f'{name}.xcodeproj').mkdir()
            with self.assertRaises(SystemExit) as caught:
                _xcode.find_container(root)
            self.assertIn('--xcodeproj', str(caught.exception))


class NotesTest(unittest.TestCase):
    def notes(self, files, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            for name, text in files.items():
                Path(folder, name).write_text(text, encoding='utf-8')
            return _xcode.release_notes(folder, **kwargs)

    def test_reads_locales(self):
        self.assertEqual(self.notes({'en-US.txt': ' Hello \n', 'de-DE.txt': 'Hallo'}),
                         {'en-US': 'Hello', 'de-DE': 'Hallo'})

    def test_refusals(self):
        for files, kwargs in (({'de-DE.txt': 'Hallo'}, {}),
                              ({'en-US.txt': '   '}, {}),
                              ({'en-US.txt': 'x' * 4001}, {}),
                              ({'en-US.txt': 'calm — clear'}, {'forbid_em_dash': True})):
            with self.assertRaises(SystemExit):
                self.notes(files, **kwargs)
        self.assertEqual(self.notes({'en-US.txt': 'a — b'})['en-US'], 'a — b')

    def test_locale_fallback(self):
        notes = {'en-US': 'en', 'de': 'de', 'fr-FR': 'fr'}
        self.assertEqual(_xcode.whats_new_for('fr-FR', notes), ('fr', 'fr-FR'))
        self.assertEqual(_xcode.whats_new_for('de-DE', notes), ('de', 'de'))
        self.assertEqual(_xcode.whats_new_for('ja', notes), ('en', 'en-US fallback'))

    def test_duplicate_upload_is_recognised(self):
        self.assertTrue(_xcode.upload_was_duplicate('ERROR: The bundle version must be higher. Redundant Binary Upload'))
        self.assertTrue(_xcode.upload_was_duplicate('build 12 has already been used'))
        self.assertFalse(_xcode.upload_was_duplicate('error: No signing certificate'))


class VersionToShipTest(unittest.TestCase):
    def test_split(self):
        editable, reviewing = _asc.split_versions([version('READY_FOR_SALE'), version('IN_REVIEW', vid='r'),
                                                   version('REJECTED', vid='e')])
        self.assertEqual((editable['id'], reviewing['id']), ('e', 'r'))

    def test_in_review_without_flag_refuses(self):
        with self.assertRaises(SystemExit) as caught:
            quiet(release.version_to_ship, FakeASC([version('WAITING_FOR_REVIEW')]), 'app', '1.1', False, False)
        self.assertIn('--replace-in-review', str(caught.exception))

    def test_dry_run_writes_nothing(self):
        for versions in ([version('WAITING_FOR_REVIEW')], [version('READY_FOR_SALE')], [version('REJECTED', '1.0')]):
            fake = FakeASC(versions)
            quiet(release.version_to_ship, fake, 'app', '1.1', True, False)
            self.assertEqual(fake.writes, [])

    def test_commit_creates_or_renames(self):
        fake = FakeASC([version('READY_FOR_SALE')])
        quiet(release.version_to_ship, fake, 'app', '1.1', False, True)
        self.assertEqual(fake.writes, [('POST', '/v1/appStoreVersions')])
        fake = FakeASC([version('PREPARE_FOR_SUBMISSION', '1.0', 'v9')])
        quiet(release.version_to_ship, fake, 'app', '1.1', False, True)
        self.assertEqual(fake.writes, [('PATCH', '/v1/appStoreVersions/v9')])

    def test_replace_in_review_cancels_then_reuses(self):
        fake = FakeASC([version('WAITING_FOR_REVIEW', '1.1', 'v2')], states=['WAITING_FOR_REVIEW', 'DEVELOPER_REJECTED'])
        shipped = quiet(release.version_to_ship, fake, 'app', '1.1', True, True, settle_wait=0)
        self.assertEqual(shipped['id'], 'v2')
        self.assertEqual(fake.writes, [('PATCH', '/v1/reviewSubmissions/s1')])


class ExportOptionsTest(unittest.TestCase):
    def test_upload_does_not_renumber(self):
        options = release.export_options('TEAM123456')
        self.assertEqual(options['destination'], 'upload')
        self.assertFalse(options['manageAppVersionAndBuildNumber'])
        self.assertEqual(options['teamID'], 'TEAM123456')


class ArgsTest(unittest.TestCase):
    def test_dry_run_is_default(self):
        args = release.parser().parse_args([])
        self.assertFalse(args.commit)
        self.assertFalse(args.no_em_dash)
        args = release.parser().parse_args(['--commit', '--scheme', 'App', '--build-dir', '/tmp/x'])
        self.assertTrue(args.commit)
        self.assertEqual(SimpleNamespace(s=args.scheme, b=args.build_dir), SimpleNamespace(s='App', b='/tmp/x'))


if __name__ == '__main__':
    unittest.main()
