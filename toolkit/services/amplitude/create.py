#!/usr/bin/env python3
"""Create a boolean flag OFF at zero rollout, then attach its deployments.

Dry run unless --commit. Existing flags are read-only: this command never
changes their variants, targeting, rollout or deployment assignments.
"""
import argparse
import re
import _amplitude as amp


def deployment_ids(flag):
    # List flags and flag details may return different deployment shapes.
    return {str(d.get('id')) if isinstance(d, dict) else str(d)
            for d in flag.get('deployments', [])}


def verify(flag, wanted):
    if flag.get('enabled') is not False or flag.get('rolloutPercentage') != 0:
        raise SystemExit('Flag is not OFF at 0%. Nothing else will be changed.')
    if not set(wanted) <= deployment_ids(flag):
        raise SystemExit('Flag is OFF but deployment verification failed. Check its assignments.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('key')
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--deployment-id', action='append', required=True)
    parser.add_argument('--name')
    parser.add_argument('--description', default='')
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.key):
        parser.error('key must contain only letters, numbers, underscores or hyphens')
    found = [f for f in amp.all_flags() if f.get('key') == args.key and str(f.get('projectId')) == args.project_id]
    if found:
        details = amp.management('GET', f"/api/1/flags/{found[0]['id']}")
        verify(details, args.deployment_id)
        print(f"Already present: {args.key} (id {details['id']}), OFF at 0%, requested deployments verified. No change.")
        return 0
    print(f"Create {args.key} in project {args.project_id}: OFF at 0%, variant on, deployments {', '.join(args.deployment_id)}")
    if not args.commit:
        print('DRY RUN. Re-run with --commit to create.')
        return 0
    # Never attach an SDK deployment until OFF + zero rollout have been read back.
    created = amp.management('POST', '/api/1/flags', body={
        'projectId': args.project_id, 'key': args.key, 'name': args.name or args.key,
        'description': args.description, 'variants': [{'key': 'on'}],
        'rolloutWeights': {'on': 1}, 'evaluationMode': 'remote',
    })
    identifier = created.get('id')
    if not identifier:
        raise SystemExit('Create response lacked an ID. Check the dashboard before retrying.')
    path = f'/api/1/flags/{identifier}'
    amp.management('PATCH', path, body={'enabled': False, 'rolloutPercentage': 0})
    verify(amp.management('GET', path), [])
    amp.management('POST', path + '/deployments', body={'deployments': args.deployment_id})
    verify(amp.management('GET', path), args.deployment_id)
    print(f"Verified {args.key} (id {identifier}): OFF at 0%, deployments attached. No rollout started.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
