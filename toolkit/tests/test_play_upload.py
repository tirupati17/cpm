"""Network-free recovery checks for the Play resumable publisher."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services' / 'play'))
from _play import upload_resumable


class Request:
    def __init__(self, *steps):
        self.steps = iter(steps)
        self.calls = 0

    def next_chunk(self, **kwargs):
        self.calls += 1
        value = next(self.steps)
        if isinstance(value, Exception):
            raise value
        return value


class Progress:
    def progress(self):
        return .5


class UploadTests(unittest.TestCase):
    def test_lost_final_response_resumes_without_creating_another_request(self):
        response = {'versionCode': 42}
        request = Request((Progress(), None), TimeoutError(), (None, response))
        delays, messages = [], []
        self.assertEqual(response, upload_resumable(request, sleep=delays.append, report=messages.append))
        self.assertEqual(3, request.calls)
        self.assertEqual([1], delays)
        self.assertIn('upload 50%', messages)

    def test_transport_retries_are_bounded(self):
        request = Request(*[TimeoutError() for _ in range(4)])
        delays = []
        with self.assertRaises(TimeoutError):
            upload_resumable(request, sleep=delays.append, report=lambda _: None)
        self.assertEqual([1, 2, 4], delays)
        self.assertEqual(4, request.calls)

    def test_non_transport_errors_are_not_retried(self):
        request = Request(ValueError('rejected bundle'))
        with self.assertRaises(ValueError):
            upload_resumable(request, sleep=lambda _: self.fail('must not retry'))
        self.assertEqual(1, request.calls)


if __name__ == '__main__':
    unittest.main()
