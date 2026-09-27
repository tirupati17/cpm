"""Shared plumbing for the gcp commands: service-account auth and a small REST client."""
import argparse
import sys

from cpmkit import creds, google

CRM = 'https://cloudresourcemanager.googleapis.com/v3'
SERVICE_USAGE = 'https://serviceusage.googleapis.com/v1'
IAM = 'https://iam.googleapis.com/v1'


def parser(description):
    lines = (description or '').strip().splitlines()
    p = argparse.ArgumentParser(description=lines[0], epilog='\n'.join(lines[1:]),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    # Not --project: the cpm dispatcher takes that one for the credentials project.
    p.add_argument('--gcp-project', help='Google Cloud project id (default GCP_PROJECT_ID)')
    return p


class Client:
    def __init__(self, gcp_project=None, token=None):
        self.project = gcp_project or creds.get('GCP_PROJECT_ID')
        self.key_file = creds.get('GCP_SERVICE_ACCOUNT_JSON')
        self._token = token
        self._info = None

    @property
    def info(self):
        if self._info is None:
            self._info = google.read_service_account(self.key_file)
        return self._info

    @property
    def email(self):
        return self.info['client_email']

    @property
    def token(self):
        if not self._token:
            try:
                self._token = google.token_from_service_account(self.key_file)
            except google.GoogleError as err:
                if not err.status:
                    raise SystemExit(f'Could not reach Google: {err.message}') from None
                raise SystemExit(f'Google refused the service account key: {err}\n'
                                 'The key may be deleted or disabled. List keys with '
                                 '`cpm gcp service-accounts keys <email>` from another identity.') from None
        return self._token

    def call(self, method, url, body=None):
        try:
            return google.call(method, url, token=self.token, body=body)
        except google.GoogleError as err:
            raise SystemExit(explain(err, self)) from None

    def pages(self, url, key):
        items, token = [], ''
        while True:
            sep = '&' if '?' in url else '?'
            reply = self.call('GET', url + (f'{sep}pageToken={token}' if token else ''))
            items.extend(reply.get(key) or [])
            token = reply.get('nextPageToken')
            if not token:
                return items


def explain(err, client):
    hints = []
    text = err.message
    disabled = 'SERVICE_DISABLED' in text or 'has not been used in project' in text
    if disabled:
        hints.append('That API is off in the project that owns the service account. '
                     'Enable it in the console (APIs & Services > Library); the service account '
                     'usually cannot enable its first API itself.')
    if err.status == 403 and not disabled:
        hints.append(f'{client.email} lacks a role for this call on {client.project}. '
                     'Grant it in IAM; changes can take a few minutes to apply.')
    if 'disableServiceAccountKeyCreation' in text:
        hints.append('An organization policy blocks key creation (iam.disableServiceAccountKeyCreation).')
    return '\n'.join([f'Google Cloud: {err}'] + hints)


def service_name(api):
    api = api.strip()
    return api if '.' in api else f'{api}.googleapis.com'


def main(fn):
    try:
        sys.exit(fn(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
