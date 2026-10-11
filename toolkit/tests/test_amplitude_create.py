import unittest
from unittest.mock import Mock, patch
import importlib.util
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / 'services/amplitude'
sys.path.insert(0, str(SERVICE))
spec = importlib.util.spec_from_file_location('amplitude_create', SERVICE / 'create.py')
create = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create)


class CreateFlagTest(unittest.TestCase):
    args = ['demo', '--project-id', '123', '--deployment-id', '456']

    @patch.object(create.amp, 'management')
    @patch.object(create.amp, 'all_flags', return_value=[])
    def test_dry_run_never_mutates(self, flags, management):
        create.main(self.args)
        management.assert_not_called()

    @patch.object(create.amp, 'all_flags', return_value=[])
    def test_deployment_attached_only_after_disabled_readback(self, flags):
        replies = iter([{'id': '789'}, {}, {'enabled': False, 'rolloutPercentage': 0}, {},
                        {'enabled': False, 'rolloutPercentage': 0, 'deployments': ['456']}])
        with patch.object(create.amp, 'management', side_effect=lambda *a, **kw: next(replies)) as management:
            create.main(self.args + ['--commit'])
        self.assertEqual([c.args[0] for c in management.call_args_list], ['POST', 'PATCH', 'GET', 'POST', 'GET'])
        self.assertNotIn('deployments', management.call_args_list[0].kwargs['body'])

    @patch.object(create.amp, 'all_flags', return_value=[])
    def test_bad_disable_readback_never_attaches(self, flags):
        with patch.object(create.amp, 'management', side_effect=[{'id': '789'}, {}, {'enabled': True, 'rolloutPercentage': 100}]) as management:
            with self.assertRaises(SystemExit): create.main(self.args + ['--commit'])
            self.assertEqual(management.call_count, 3)

    @patch.object(create.amp, 'all_flags', return_value=[{'id': '789', 'key': 'demo', 'projectId': '123'}])
    def test_existing_flag_is_read_only_and_object_ids_work(self, flags):
        with patch.object(create.amp, 'management', return_value={'id': '789', 'enabled': False, 'rolloutPercentage': 0, 'deployments': [{'id': 456}]}) as management:
            create.main(self.args + ['--commit'])
            management.assert_called_once_with('GET', '/api/1/flags/789')


if __name__ == '__main__': unittest.main()
