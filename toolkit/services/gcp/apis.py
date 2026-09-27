#!/usr/bin/env python3
"""List the APIs enabled on the project, or enable one (dry run unless --commit).

  cpm gcp apis                              enabled services
  cpm gcp apis enable androidpublisher      short names get .googleapis.com
  cpm gcp apis enable googleads.googleapis.com --commit
Enabling needs roles/serviceusage.serviceUsageAdmin, and Service Usage itself must
already be on: the first API of a new project is enabled from the console.
"""
import _gcp


def enabled(client):
    url = f'{_gcp.SERVICE_USAGE}/projects/{client.project}/services?filter=state:ENABLED&pageSize=200'
    return sorted(s.get('config', {}).get('name') or s['name'].rsplit('/', 1)[-1]
                  for s in client.pages(url, 'services'))


def run(argv, client=None):
    p = _gcp.parser(__doc__)
    p.add_argument('action', nargs='?', choices=['list', 'enable'], default='list')
    p.add_argument('api', nargs='?', help='service to enable, e.g. googleads or iam.googleapis.com')
    p.add_argument('--commit', action='store_true', help='actually enable it (default: dry run)')
    args = p.parse_args(argv)
    client = client or _gcp.Client(args.gcp_project)
    if args.action == 'list':
        names = enabled(client)
        print(f'{len(names)} enabled on {client.project}\n')
        print('\n'.join(names))
        return 0
    if not args.api:
        p.error('enable needs an API name')
    name = _gcp.service_name(args.api)
    state = client.call('GET', f'{_gcp.SERVICE_USAGE}/projects/{client.project}/services/{name}')
    if state.get('state') == 'ENABLED':
        print(f'{name} is already enabled on {client.project}.')
        return 0
    title = state.get('config', {}).get('title', '')
    print(f'{name}{f" ({title})" if title else ""}: {state.get("state", "unknown")} -> ENABLED on {client.project}')
    if not args.commit:
        print('Dry run: nothing was changed. Re-run with --commit to enable it.')
        return 0
    op = client.call('POST', f'{_gcp.SERVICE_USAGE}/projects/{client.project}/services/{name}:enable', {})
    print('Enabled.' if op.get('done') else f'Started ({op.get("name", "operation")}); it finishes within a minute.')
    return 0


if __name__ == '__main__':
    _gcp.main(run)
