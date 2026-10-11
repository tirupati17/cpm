import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

spec = importlib.util.spec_from_file_location('screenshots', Path(__file__).parents[1] / 'services/appstore/screenshots.py')
shots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shots)

class UploadRecoveryTests(unittest.TestCase):
    def test_reservation_resume_validates_identity_size_and_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '01.png'; path.write_bytes(b'abc')
            attrs = {'fileName': '01.png', 'fileSize': 3, 'sourceFileChecksum': None,
                     'assetDeliveryState': {'state': 'AWAITING_UPLOAD'}, 'uploadOperations': [{'method': 'PUT'}]}
            client = mock.Mock()
            for change in [{'fileName': 'other.png'}, {'fileSize': 4}, {'sourceFileChecksum': 'x'},
                           {'assetDeliveryState': {'state': 'COMPLETE'}}]:
                client.get.return_value = {'data': {'id': 'id', 'attributes': {**attrs, **change}}}
                with self.assertRaises(ValueError):
                    shots.resume_upload(client, 'id', path, None)
            client.call.assert_not_called()
            client.get.return_value = {'data': {'id': 'id', 'attributes': attrs}}
            with mock.patch.object(shots, '_transfer', return_value='id') as transfer:
                self.assertEqual(shots.resume_upload(client, 'id', path, None), 'id')
                transfer.assert_called_once()

    def test_empty_reservation_replaced_only_after_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '01.png'; path.write_bytes(b'abc')
            client = mock.Mock()
            client.get.return_value = {'data': {'id': 'empty', 'attributes': {
                'fileName': '01.png', 'fileSize': 3, 'sourceFileChecksum': None,
                'assetDeliveryState': {'state': 'AWAITING_UPLOAD'}, 'uploadOperations': None}}}
            with self.assertRaises(ValueError):
                shots.resume_upload(client, 'empty', path, None)
            client.call.assert_not_called()
            with mock.patch.object(shots, 'upload', return_value='new') as upload:
                self.assertEqual(shots.resume_upload(client, 'empty', path, None, set_id='draft-set'), 'new')
                client.call.assert_called_once_with('DELETE', '/v1/appScreenshots/empty')
                self.assertEqual(upload.call_args.args[1], 'draft-set')

    def test_transfer_retries_put_without_creating_another_reservation(self):
        client = mock.Mock()
        shot = {'id': 'id', 'attributes': {'uploadOperations': [
            {'url': 'https://example.test/upload', 'method': 'PUT', 'offset': 0, 'length': 3}]}}
        response = mock.MagicMock()
        with mock.patch.object(shots.urllib.request, 'urlopen', side_effect=[urllib.error.URLError('EOF'), response]) as request, mock.patch.object(shots.time, 'sleep'):
            self.assertEqual(shots._transfer(client, shot, b'abc', None, shots.KINDS['screenshots']), 'id')
            self.assertEqual(request.call_count, 2)
        self.assertEqual(client.call.call_count, 1)
        self.assertEqual(client.call.call_args.args[0], 'PATCH')

    def test_permanent_upload_failure_never_marks_uploaded(self):
        client = mock.Mock()
        shot = {'id': 'id', 'attributes': {'uploadOperations': [
            {'url': 'https://example.test/upload', 'method': 'PUT', 'offset': 0, 'length': 3}]}}
        error = urllib.error.HTTPError('https://example.test', 403, 'Forbidden', {}, None)
        with mock.patch.object(shots.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                shots._transfer(client, shot, b'abc', None, shots.KINDS['screenshots'])
        client.call.assert_not_called()

if __name__ == '__main__': unittest.main()
