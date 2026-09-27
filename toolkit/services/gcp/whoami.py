#!/usr/bin/env python3
"""Which service account and project these credentials are, and the roles it holds there.

--offline reads the key file only and makes no calls.
"""
import _gcp


def roles_for(client, member):
    policy = client.call('POST', f'{_gcp.CRM}/projects/{client.project}:getIamPolicy', {})
    return sorted(b['role'] for b in policy.get('bindings') or [] if member in (b.get('members') or []))


def run(argv, client=None):
    p = _gcp.parser(__doc__)
    p.add_argument('--offline', action='store_true', help='read the key file only, no network')
    args = p.parse_args(argv)
    client = client or _gcp.Client(args.gcp_project)
    info = client.info
    print(f'service account  {client.email}')
    print(f'key file         {client.key_file}')
    print(f'key home project {info.get("project_id", "?")}')
    print(f'target project   {client.project}')
    if info.get('project_id') and info['project_id'] != client.project:
        print('  note: the key belongs to another project. Quota and API enablement are '
              'charged to the key\'s project, and roles must be granted on the target one.')
    if args.offline:
        return 0
    project = client.call('GET', f'{_gcp.CRM}/projects/{client.project}')
    print(f'display name     {project.get("displayName", "")}')
    print(f'project number   {project.get("name", "").rsplit("/", 1)[-1]}')
    print(f'state            {project.get("state", "")}')
    try:
        roles = roles_for(client, f'serviceAccount:{client.email}')
    except SystemExit as err:
        print(f'roles            (cannot read the IAM policy: {str(err).splitlines()[0]})')
        return 0
    print('roles            ' + (', '.join(roles) if roles else '(none granted directly on this project)'))
    return 0


if __name__ == '__main__':
    _gcp.main(run)
