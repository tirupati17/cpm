"""Test helpers: temp credential home, fake Google HTTP, and loading service commands by path."""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLKIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLKIT / 'lib'))
from cpmkit import creds, google  # noqa: E402


def load(service, command):
    """Import toolkit/services/<service>/<command>.py (hyphens allowed) with its folder on sys.path."""
    folder = str(TOOLKIT / 'services' / service)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    name = f'svc_{service}_{command.replace("-", "_")}'
    spec = importlib.util.spec_from_file_location(name, os.path.join(folder, f'{command}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeGoogle:
    """Stands in for cpmkit.google.call. Routes are (method, url substring) -> reply or callable."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, token=None, body=None, headers=None, form=None, timeout=None):
        self.calls.append({'method': method, 'url': url, 'token': token, 'body': body,
                           'headers': headers or {}, 'form': form})
        for (want_method, fragment), reply in self.routes:
            if want_method == method and fragment in url:
                return reply(body, url) if callable(reply) else reply
        raise AssertionError(f'unexpected request {method} {url}')

    def bodies(self, fragment):
        return [c['body'] for c in self.calls if fragment in c['url']]


class ServiceTest(unittest.TestCase):
    ENV = {}

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.saved_env = dict(os.environ)
        for name in creds.NEEDS:
            os.environ.pop(name, None)
        os.environ.pop('GOOGLE_ADS_API_VERSION', None)
        os.environ.update(CPM_CONFIG_HOME=self.home.name, CPM_NO_PROMPT='1', CPM_PROJECT='demo')
        os.environ.update(self.ENV)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)
        self.home.cleanup()

    def fake(self, routes):
        fake = FakeGoogle(routes)
        patcher = mock.patch.object(google, 'call', fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def run_cmd(self, module, argv, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = module.run(argv, **kwargs)
        self.assertIn(code, (0, None))
        return out.getvalue()
