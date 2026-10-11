import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'appstore_submit', Path(__file__).parents[1] / 'services/appstore/submit.py')
submit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(submit)


class SubmitSafetyTests(unittest.TestCase):
    def setUp(self):
        self.document = {'data': {'id': 'v', 'attributes': {
            'platform': 'IOS', 'versionString': '1.2', 'appStoreState': 'READY_FOR_REVIEW'},
            'relationships': {'build': {'data': {'type': 'builds', 'id': 'b'}}}},
            'included': [{'type': 'builds', 'id': 'b', 'attributes': {
                'version': '42', 'processingState': 'VALID', 'expired': False}}]}
        self.item = {'attributes': {'state': 'READY_FOR_REVIEW'}, 'relationships': {
            'appStoreVersion': {'data': {'type': 'appStoreVersions', 'id': 'v'}}}}

    def test_expected_ready_version_and_build(self):
        self.assertEqual(submit.validate_version(self.document, '1.2', '42'), 'v')
        submit.validate_items([self.item], 'v')

    def test_wrong_version_build_or_already_submitted(self):
        for version, build in [('1.3', '42'), ('1.2', '43')]:
            with self.assertRaises(ValueError):
                submit.validate_version(self.document, version, build)
        self.document['data']['attributes']['appStoreState'] = 'WAITING_FOR_REVIEW'
        with self.assertRaises(ValueError):
            submit.validate_version(self.document, '1.2', '42')

    def test_missing_invalid_and_expired_build(self):
        for field, value in [('processingState', 'PROCESSING'), ('expired', True)]:
            document = copy.deepcopy(self.document)
            document['included'][0]['attributes'][field] = value
            with self.assertRaises(ValueError):
                submit.validate_version(document, '1.2', '42')
        self.document['included'] = []
        with self.assertRaises(ValueError):
            submit.validate_version(self.document, '1.2', '42')

    def test_extra_missing_and_unrelated_items(self):
        for items, version in [([], 'v'), ([self.item, self.item], 'v'), ([self.item], 'other')]:
            with self.assertRaises(ValueError):
                submit.validate_items(items, version)
        self.item['attributes']['state'] = 'WAITING_FOR_REVIEW'
        with self.assertRaises(ValueError):
            submit.validate_items([self.item], 'v')


if __name__ == '__main__':
    unittest.main()
