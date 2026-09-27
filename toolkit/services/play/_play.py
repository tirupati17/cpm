"""Play Developer API plumbing shared by the play commands.

Google libraries are imported inside the functions, never at module level, so
every command's --help and every local check runs without the SDK installed:

    pip install google-api-python-client google-auth
"""
from pathlib import Path

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
    except ImportError:
        raise SystemExit('The Google API client is not installed. '
                         'Run: pip install google-api-python-client google-auth')
    credentials = service_account.Credentials.from_service_account_file(str(key_file()), scopes=[SCOPE])
    return build('androidpublisher', 'v3', credentials=credentials, cache_discovery=False)


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
