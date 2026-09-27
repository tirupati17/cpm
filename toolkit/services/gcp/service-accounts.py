#!/usr/bin/env python3
"""List service accounts and their keys, or create a key (guarded; the key is saved, never shown).

  cpm gcp service-accounts                         accounts in the project
  cpm gcp service-accounts keys <email>            that account's keys, with ages
  cpm gcp service-accounts key-create <email> --commit [--save-as PLAY_SERVICE_ACCOUNT_JSON]
The new key is written only to ~/.config/cpm/<project>/keys/ (0600). --save-as
also stores its path under a credential name. A key is a long-lived secret:
prefer one per purpose, delete old ones, and never commit the file.
"""
import base64
import datetime
import os
import tempfile

import _gcp
from cpmkit import creds, google


def accounts(client):
    return client.pages(f'{_gcp.IAM}/projects/{client.project}/serviceAccounts?pageSize=100', 'accounts')


def keys(client, email):
    reply = client.call('GET', f'{_gcp.IAM}/projects/-/serviceAccounts/{email}/keys?keyTypes=USER_MANAGED')
    return reply.get('keys') or []


def _age(stamp, today=None):
    try:
        made = datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00')).date()
    except (AttributeError, ValueError):
        return ''
    return f'{((today or datetime.date.today()) - made).days}d'


def create_key(client, email, save_as=None):
    reply = client.call('POST', f'{_gcp.IAM}/projects/-/serviceAccounts/{email}/keys',
                        {'privateKeyType': 'TYPE_GOOGLE_CREDENTIALS_FILE', 'keyAlgorithm': 'KEY_ALG_RSA_2048'})
    key_id = reply.get('name', '').rsplit('/', 1)[-1]
    data = base64.b64decode(reply['privateKeyData'])
    with tempfile.TemporaryDirectory() as scratch:
        os.chmod(scratch, 0o700)
        source = os.path.join(scratch, f'{email.split("@")[0]}-{key_id[:8]}.json')
        fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        path = creds.keep_file(save_as or 'GCP_SERVICE_ACCOUNT_JSON', source)
    if save_as:
        creds.save(save_as, path)
    return key_id, path


def run(argv, client=None):
    p = _gcp.parser(__doc__)
    p.add_argument('action', nargs='?', choices=['list', 'keys', 'key-create'], default='list')
    p.add_argument('email', nargs='?', help='service account email (keys, key-create)')
    p.add_argument('--commit', action='store_true', help='key-create: actually create the key')
    p.add_argument('--save-as', metavar='NAME', help='key-create: store the key path under this credential name')
    args = p.parse_args(argv)
    client = client or _gcp.Client(args.gcp_project)

    if args.action == 'list':
        rows = [{'email': a.get('email', ''), 'name': a.get('displayName', ''),
                 'disabled': 'yes' if a.get('disabled') else ''} for a in accounts(client)]
        print(google.table(rows, ['email', 'name', 'disabled'], ['EMAIL', 'DISPLAY NAME', 'DISABLED']))
        return 0
    if not args.email or '@' not in args.email:
        p.error(f'{args.action} needs a service account email')
    if args.action == 'keys':
        rows = [{'id': k.get('name', '').rsplit('/', 1)[-1][:12], 'created': k.get('validAfterTime', '')[:10],
                 'age': _age(k.get('validAfterTime')), 'expires': k.get('validBeforeTime', '')[:10],
                 'disabled': 'yes' if k.get('disabled') else ''} for k in keys(client, args.email)]
        print(google.table(rows, ['id', 'created', 'age', 'expires', 'disabled'],
                           ['KEY ID', 'CREATED', 'AGE', 'EXPIRES', 'DISABLED']))
        print(f'\n{len(rows)} user-managed key(s). Google allows 10 per account.')
        return 0

    existing = keys(client, args.email)
    print(f'Create a new JSON key for {args.email} ({len(existing)} user-managed key(s) already).')
    print(f'It would be saved under {creds.project_dir()}/keys/ and not printed.')
    if args.save_as:
        print(f'Its path would be stored as {args.save_as}.')
    if not args.commit:
        print('Dry run: nothing was created. Re-run with --commit.')
        return 0
    key_id, path = create_key(client, args.email, args.save_as)
    print(f'Created key {key_id[:12]}… saved to {path}')
    if not args.save_as:
        print(f'Use it with: cpm creds set GCP_SERVICE_ACCOUNT_JSON {path}  (or --save-as next time)')
    return 0


if __name__ == '__main__':
    _gcp.main(run)
