"""Test support for the API helpers: a fake urlopen and a way to run a command in-process.

No test here touches the network. FakeHTTP replaces urllib.request.urlopen,
answers from a route table, and records every request so a test can assert on
method, URL, headers and body (and that a dry run sent nothing).
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from email.message import Message
from pathlib import Path
from unittest import mock

TOOLKIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLKIT / 'lib'))

from cpmkit import creds  # noqa: E402


class Response:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTTP:
    """routes: list of (METHOD, url-substring, status, body[, headers]). First match wins;
    a route whose status is a list is consumed one status per call."""

    def __init__(self, routes=()):
        self.routes = list(routes)
        self.calls = []

    def __call__(self, req, timeout=None, context=None):
        body = json.loads(req.data) if req.data else None
        self.calls.append({'method': req.get_method(), 'url': req.full_url,
                           'headers': dict(req.header_items()), 'body': body})
        for route in self.routes:
            method, fragment, status, payload = route[:4]
            headers = route[4] if len(route) > 4 else {}
            if method == req.get_method() and fragment in req.full_url:
                if isinstance(status, list):
                    status = status.pop(0) if len(status) > 1 else status[0]
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                if status >= 400:
                    msg = Message()
                    for k, v in headers.items():
                        msg[k] = v
                    raise urllib.error.HTTPError(req.full_url, status, 'error', msg, io.BytesIO(raw))
                return Response(raw)
        raise AssertionError(f'unexpected request {req.get_method()} {req.full_url}')

    def by(self, method):
        return [c for c in self.calls if c['method'] == method]

    def query(self, call):
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(call['url']).query).items()}


class ApiCase(unittest.TestCase):
    """Isolated credentials (temp CPM_CONFIG_HOME, no prompts) plus a command runner."""
    ENV = {}

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.saved = dict(os.environ)
        for name in list(creds.NEEDS) + ['ONESIGNAL_AUTH_SCHEME']:
            os.environ.pop(name, None)
        os.environ.update(CPM_CONFIG_HOME=self.home.name, CPM_NO_PROMPT='1', CPM_PROJECT='test-app')
        os.environ.update(self.ENV)
        self.http = FakeHTTP()
        patcher = mock.patch('urllib.request.urlopen', self.http)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch('time.sleep')
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        self.home.cleanup()

    def route(self, *routes):
        self.http.routes.extend(routes)

    def run_cmd(self, service, command, argv, **kw):
        folder = TOOLKIT / 'services' / service
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
        spec = importlib.util.spec_from_file_location(f'cmd_{service}_{command}', folder / f'{command}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = module.main(argv, **kw)
            except SystemExit as exit_:
                code = exit_.code
                if isinstance(code, str):
                    err.write(code)
                    code = 1
        self.assert_no_secrets(out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def assert_no_secrets(self, text):
        for name, value in self.ENV.items():
            need = creds.NEEDS.get(name)
            if need and need.secret and value:
                self.assertNotIn(value, text, f'{name} leaked into output')
