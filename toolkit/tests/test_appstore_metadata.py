import importlib.util
import pathlib
import unittest

source = pathlib.Path(__file__).resolve().parents[1] / 'services/appstore/metadata.py'
module_spec = importlib.util.spec_from_file_location('asc_metadata', source)
metadata = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(metadata)


class MetadataTests(unittest.TestCase):
    def spec(self, **fields):
        return {'bundleId': 'org.example.App', 'platform': 'IOS', 'version': '1.2',
                'localizations': {'en-US': fields}}

    def test_unicode_keywords_count_bytes(self):
        metadata.validate_spec(self.spec(keywords='心' * 33))
        with self.assertRaisesRegex(ValueError, 'UTF-8 bytes'):
            metadata.validate_spec(self.spec(keywords='心' * 34))

    def test_promo_counts_characters(self):
        metadata.validate_spec(self.spec(promotionalText='心' * 170))
        with self.assertRaises(ValueError):
            metadata.validate_spec(self.spec(promotionalText='心' * 171))

    def test_required_fields_and_unknown_fields(self):
        for fields in ({'description': ''}, {'keywords': None}, {'name': 'App'}, {}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                metadata.validate_spec(self.spec(**fields))
        metadata.validate_spec(self.spec(promotionalText=''))

    def test_duplicate_and_empty_terms(self):
        for value in ('mood,Mood', 'mood,,diary', 'mood, diary'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metadata.validate_spec(self.spec(keywords=value))

    def test_patch_preserves_unnamed_fields(self):
        remote = [{'id': 'one', 'attributes': {'locale': 'en-US', 'description': 'old',
                   'keywords': 'mood', 'promotionalText': 'keep', 'whatsNew': 'keep too'}}]
        result = metadata.plan_changes(self.spec(description='new', keywords='mood'), remote)
        self.assertEqual(result, [{'locale': 'en-US', 'id': 'one',
                                  'attributes': {'description': 'new'}, 'before': {'description': 'old'}}])
        self.assertEqual(metadata.plan_changes(self.spec(description='old'), remote), [])

    def test_no_english_fallback_or_locale_creation(self):
        with self.assertRaisesRegex(ValueError, 'store locales missing'):
            metadata.plan_changes(self.spec(description='new'), [])


if __name__ == '__main__':
    unittest.main()
