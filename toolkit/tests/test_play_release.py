"""Cover the publish payload, because a wrong one is only visible after it ships."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services' / 'play'))
from _release import find_gradle, load_notes, read_version, release_body, stage_artifacts, verify_artifacts


class ReleaseBodyTests(unittest.TestCase):
    notes = [{'language': 'en-US', 'text': 'Hello.'}]

    def test_full_rollout_is_completed_without_a_fraction(self):
        release = release_body('production', 17, 100, self.notes)['releases'][0]
        self.assertEqual(release['status'], 'completed')
        self.assertNotIn('userFraction', release)

    def test_partial_rollout_is_in_progress_with_a_fraction(self):
        release = release_body('production', 17, 20, self.notes)['releases'][0]
        self.assertEqual(release['status'], 'inProgress')
        self.assertEqual(release['userFraction'], 0.2)

    def test_version_code_is_a_string_as_play_requires(self):
        self.assertEqual(release_body('internal', 17, 100, self.notes)['releases'][0]['versionCodes'], ['17'])

    def test_version_name_becomes_the_release_name(self):
        self.assertEqual(release_body('beta', 17, 100, self.notes, version_name='1.2.0')['releases'][0]['name'], '1.2.0')

    def test_unknown_track_is_refused(self):
        with self.assertRaises(SystemExit):
            release_body('prod', 17, 100, self.notes)

    def test_rollout_outside_the_range_is_refused(self):
        for bad in (0, -5, 101):
            with self.assertRaises(SystemExit):
                release_body('production', 17, bad, self.notes)


class NotesTests(unittest.TestCase):
    def test_each_language_file_becomes_an_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'en-US.txt').write_text('What changed.')
            (Path(directory) / 'hi-IN.txt').write_text('क्या बदला.', encoding='utf-8')
            self.assertEqual([n['language'] for n in load_notes(directory)], ['en-US', 'hi-IN'])

    def test_over_the_play_limit_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'en-US.txt').write_text('x' * 501)
            with self.assertRaises(SystemExit):
                load_notes(directory)

    def test_empty_notes_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'en-US.txt').write_text('   ')
            with self.assertRaises(SystemExit):
                load_notes(directory)

    def test_missing_folder_is_refused(self):
        with self.assertRaises(SystemExit):
            load_notes('/nonexistent/release-notes/9.9.9')


class VersionTests(unittest.TestCase):
    def test_kotlin_dsl(self):
        text = 'defaultConfig {\n  versionCode = 28\n  versionName = "1.0.15"\n}'
        self.assertEqual(read_version(text), ('1.0.15', 28))

    def test_groovy_dsl(self):
        text = "defaultConfig {\n  versionCode 7\n  versionName '2.1-beta.3'\n}"
        self.assertEqual(read_version(text), ('2.1-beta.3', 7))

    def test_computed_version_is_refused(self):
        with self.assertRaises(SystemExit):
            read_version('versionCode = computeCode()\nversionName = libs.versions.app.get()')

    def test_build_file_is_found_kts_first(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'app').mkdir()
            (Path(directory) / 'app/build.gradle').write_text('')
            self.assertEqual(find_gradle(directory).name, 'build.gradle')
            (Path(directory) / 'app/build.gradle.kts').write_text('')
            self.assertEqual(find_gradle(directory).name, 'build.gradle.kts')

    def test_missing_build_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit):
                find_gradle(directory)


class ArtifactTests(unittest.TestCase):
    def stage(self, directory, payload=b'bundle', version='1.0.5', code=17, digest=None):
        aab = Path(directory) / 'app-1.0.5.aab'
        aab.write_bytes(payload)
        (Path(directory) / 'release.json').write_text(json.dumps({
            'versionName': version, 'versionCode': code, 'signerSha256': 'a' * 64,
            'files': {'aab': {'filename': aab.name, 'bytes': len(payload),
                              'sha256': digest or hashlib.sha256(payload).hexdigest()}},
        }))

    def test_matching_artifacts_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.stage(directory)
            aab, manifest = verify_artifacts(directory, '1.0.5', 17)
            self.assertTrue(aab.is_file())
            self.assertEqual(manifest['versionCode'], 17)

    def test_stale_artifacts_from_an_earlier_build_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            self.stage(directory, version='1.0.4', code=16)
            with self.assertRaises(SystemExit):
                verify_artifacts(directory, '1.0.5', 17)

    def test_a_bundle_that_does_not_match_its_hash_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            self.stage(directory, digest='b' * 64)
            with self.assertRaises(SystemExit):
                verify_artifacts(directory, '1.0.5', 17)

    def test_missing_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit):
                verify_artifacts(directory, '1.0.5', 17)

    def test_staged_artifacts_verify_and_a_rebuild_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory) / 'app-release.aab'
            build.write_bytes(b'first build')
            out = Path(directory) / 'artifacts' / '1.0.5'
            manifest = stage_artifacts(out, '1.0.5', 17, build, basename='demo', extra={'signerSha256': 'c' * 64})
            self.assertEqual(manifest['files']['aab']['filename'], 'demo-1.0.5.aab')
            self.assertEqual(manifest['signerSha256'], 'c' * 64)
            verify_artifacts(out, '1.0.5', 17)
            (out / 'demo-1.0.5.aab').write_bytes(b'another build')
            with self.assertRaises(SystemExit):
                verify_artifacts(out, '1.0.5', 17)

    def test_staging_a_missing_bundle_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit):
                stage_artifacts(Path(directory) / 'out', '1.0.5', 17, Path(directory) / 'nope.aab')


if __name__ == '__main__':
    unittest.main()
