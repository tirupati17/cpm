"""Play Developer API plumbing shared by the play commands.

Google libraries are imported inside the functions, never at module level, so
every command's --help and every local check runs without the SDK installed:

    pip install google-api-python-client google-auth
"""
from pathlib import Path
import socket
import ssl
import time

from cpmkit import creds

SCOPE = 'https://www.googleapis.com/auth/androidpublisher'


def package(explicit=None):
    return explicit or creds.get('PLAY_PACKAGE')


def key_file():
    """The service account key path. Its contents are never printed."""
    key = Path(creds.get('PLAY_SERVICE_ACCOUNT_JSON')).expanduser()
    if not key.is_file():
        raise SystemExit(f'No Play service account key at {key}. '
                         'Run: cpm creds set PLAY_SERVICE_ACCOUNT_JSON  (or export it).')
    return key


def service():
    try:
        from google.oauth2 import service_account          # imported late so --help needs no SDK
        from googleapiclient.discovery import build
        from google_auth_httplib2 import AuthorizedHttp
        import httplib2
    except ImportError:
        raise SystemExit('The Google API client is not installed. '
                         'Run: pip install google-api-python-client google-auth')
    credentials = service_account.Credentials.from_service_account_file(str(key_file()), scopes=[SCOPE])
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=180))
    return build('androidpublisher', 'v3', http=http, cache_discovery=False)


def upload_resumable(request, *, max_retries=3, sleep=time.sleep, report=print):
    """Resume the same upload after a lost response, including its final chunk.

    The Google client marks transport failures as an error state. Its next
    next_chunk call asks the server which bytes it already accepted; starting
    another upload instead loses that recovery path. HTTP errors are handled by
    the client's bounded backoff, while transport exceptions need this outer loop.
    """
    failures = 0
    while True:
        try:
            status, result = request.next_chunk(num_retries=3)
        except (TimeoutError, ConnectionError, socket.gaierror, ssl.SSLError):
            if failures >= max_retries:
                raise
            failures += 1
            report(f'upload connection interrupted; resuming ({failures}/{max_retries})')
            sleep(2 ** (failures - 1))
            continue
        failures = 0
        if result is not None:
            return result
        if status is not None:
            report(f'upload {status.progress():.0%}')


def discard(edits, package_name, edit_id):
    """Delete an edit that was not committed.

    Every path that did not commit leaves an edit behind: the dry run, a
    rejected upload, an interrupt. They expire on their own, but an abandoned
    edit blocks nothing only as long as nobody wonders what it was.
    """
    try:
        edits.delete(packageName=package_name, editId=edit_id).execute()
    except Exception:
        pass


def read_back(edits, package_name, reader):
    """Open a throwaway edit, run reader(edit_id), delete the edit.

    Used after every commit: read the live state back rather than trusting the
    commit response.
    """
    edit_id = edits.insert(packageName=package_name, body={}).execute()['id']
    try:
        return reader(edit_id)
    finally:
        discard(edits, package_name, edit_id)
