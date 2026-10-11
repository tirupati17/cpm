import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVICE = Path(__file__).resolve().parents[1] / 'services/amplitude'
sys.path.insert(0, str(SERVICE))
spec = importlib.util.spec_from_file_location('amplitude_rollout', SERVICE / 'rollout.py')
rollout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)
FLAG = {'id': 1, 'key': 'demo', 'enabled': False, 'rolloutPercentage': 0,
        'variants': [{'key': 'on'}], 'deployments': [2], 'rolloutWeights': {'on': 1}}

class RolloutTest(unittest.TestCase):
    @patch.object(rollout.amp, 'all_flags', return_value=[FLAG])
    def test_dry_run_is_read_only(self, _):
        with patch.object(rollout.amp, 'management', return_value=FLAG) as call:
            rollout.main(['demo', '--percent', '100'])
            call.assert_called_once_with('GET', '/api/1/flags/1')

    @patch.object(rollout.amp, 'all_flags', return_value=[FLAG])
    def test_commit_checks_and_reads_back(self, _):
        after = FLAG | {'enabled': True, 'rolloutPercentage': 100}
        with patch.object(rollout.amp, 'management', side_effect=[FLAG, FLAG, {}, after]) as call:
            rollout.main(['demo', '--percent', '100', '--commit'])
            self.assertEqual(call.call_args_list[2].kwargs['body'], {'enabled': True, 'rolloutPercentage': 100})

    def test_experiments_and_segments_refused(self):
        for update in ({'targetSegments': [{'name': 'staff'}]}, {'variants': [{'key': 'a'}, {'key': 'b'}]}, {'deployments': []}):
            with self.assertRaises(SystemExit): rollout.check(FLAG | update)

    @patch.object(rollout.amp, 'all_flags', return_value=[FLAG])
    def test_concurrent_edit_never_patched(self, _):
        with patch.object(rollout.amp, 'management', side_effect=[FLAG, FLAG | {'enabled': True}]) as call:
            with self.assertRaises(SystemExit): rollout.main(['demo', '--percent', '100', '--commit'])
            self.assertEqual(call.call_count, 2)

    @patch.object(rollout.amp, 'all_flags', return_value=[FLAG])
    def test_failed_readback_is_failure(self, _):
        with patch.object(rollout.amp, 'management', side_effect=[FLAG, FLAG, {}, FLAG]):
            with self.assertRaises(SystemExit): rollout.main(['demo', '--percent', '100', '--commit'])

if __name__ == '__main__': unittest.main()
