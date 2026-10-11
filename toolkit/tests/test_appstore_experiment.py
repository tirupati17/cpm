import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('experiment', Path(__file__).parents[1] / 'services/appstore/experiment.py')
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


class ExperimentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.spec = {'name': 'Themes', 'platform': 'IOS', 'trafficProportion': 75,
            'treatments': [{'name': n, 'screenshots': [{'locale': 'en-US', 'display': 'APP_IPHONE_67', 'folder': n}]}
                           for n in ['White', 'Black', 'Cosmic']]}

    def test_allows_three_treatments_and_rejects_four(self):
        experiment.validate_spec(self.spec)
        self.spec['treatments'].append({'name': 'Extra'})
        with self.assertRaises(ValueError):
            experiment.validate_spec(self.spec)

    def test_refuses_duplicate_treatments_or_mismatched_locales(self):
        bad = copy.deepcopy(self.spec)
        bad['treatments'][1]['name'] = 'White'
        with self.assertRaises(ValueError):
            experiment.validate_spec(bad)
        self.spec['treatments'][1]['screenshots'][0]['locale'] = 'de-DE'
        with self.assertRaises(ValueError):
            experiment.validate_spec(self.spec)

    def test_refuses_invalid_traffic(self):
        for value in [-1, 0, 101, 25.5, True]:
            self.spec['trafficProportion'] = value
            with self.assertRaises(ValueError):
                experiment.validate_spec(self.spec)

    def test_will_not_mutate_started_submitted_or_changed_experiment(self):
        attrs = {'name': 'Themes', 'platform': 'IOS', 'trafficProportion': 75, 'state': 'PREPARE_FOR_SUBMISSION'}
        experiment.verify_draft({'attributes': attrs}, self.spec)
        for change in [{'state': 'WAITING_FOR_REVIEW'}, {'startDate': '2026-01-01'}, {'trafficProportion': 50}]:
            with self.assertRaises(ValueError):
                experiment.verify_draft({'attributes': {**attrs, **change}}, self.spec)

    def test_resume_accepts_only_identical_prefix_and_refuses_conflicting_files(self):
        files = [{'name': '01.png', 'md5': 'abc'}, {'name': '02.png', 'md5': 'def'}]
        shots = [{'attributes': {'fileName': '01.png', 'sourceFileChecksum': 'abc', 'assetDeliveryState': {'state': 'COMPLETE'}}}]
        self.assertEqual(experiment.prefix_length(shots, files), 1)
        for changed in [{'fileName': 'other.png'}, {'sourceFileChecksum': 'changed'}, {'assetDeliveryState': {'state': 'FAILED'}}]:
            with self.assertRaises(ValueError):
                experiment.prefix_length([{'attributes': {**shots[0]['attributes'], **changed}}], files)
        with self.assertRaises(ValueError):
            experiment.prefix_length(shots * 3, files)

    def test_inherited_replacement_requires_distinct_ids_and_matching_fingerprints(self):
        control = [{'id': 'live', 'attributes': {'fileName': '01.png', 'sourceFileChecksum': 'abc', 'fileSize': 123}}]
        copied = [{**control[0], 'id': 'draft'}]
        self.assertTrue(experiment.verified_inherited(copied, control))
        self.assertFalse(experiment.verified_inherited(control, control))
        self.assertFalse(experiment.verified_inherited([], control))
        changed = copy.deepcopy(copied)
        changed[0]['attributes']['sourceFileChecksum'] = 'different'
        self.assertFalse(experiment.verified_inherited(changed, control))
        self.assertFalse(experiment.verified_inherited(copied * 2, control))


if __name__ == '__main__':
    unittest.main()
