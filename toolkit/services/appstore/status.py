#!/usr/bin/env python3
"""Show the latest App Store versions and builds and their states (read-only).

    cpm appstore status
    cpm appstore status --bundle-id com.example.App --builds 10

Lists the store versions for the platform with their appStoreState, the open
review submissions, and the most recent uploaded builds with their processing
state and marketing version. Changes nothing.

Credentials: ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH, ASC_BUNDLE_ID.
"""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bundle-id', help='app bundle id (default: ASC_BUNDLE_ID credential)')
    parser.add_argument('--platform', default='IOS', choices=('IOS', 'MAC_OS', 'TV_OS', 'VISION_OS'))
    parser.add_argument('--versions', type=int, default=5, help='store versions to show (default 5)')
    parser.add_argument('--builds', type=int, default=5, help='recent builds to show (default 5)')
    args = parser.parse_args(argv)

    import _asc
    bundle_id = _asc.resolve_bundle_id(args.bundle_id)
    asc = _asc.ASC()
    app_id, name = asc.app(bundle_id)
    print(f'{name}  ({bundle_id}, app {app_id})')

    print(f'\n{args.platform} store versions')
    for v in asc.store_versions(app_id, args.platform, limit=max(1, args.versions)):
        a = v['attributes']
        print(f"  {a['versionString']:<12} {a['appStoreState']:<28} created {(a.get('createdDate') or '')[:10]}")

    submissions = asc.get(f'/v1/reviewSubmissions?filter[app]={app_id}&filter[platform]={args.platform}'
                          '&limit=10&fields[reviewSubmissions]=state,submittedDate')['data']
    open_ones = [s for s in submissions if s['attributes']['state'] not in ('COMPLETE', 'CANCELING')]
    if open_ones:
        print('\nreview submissions')
        for s in open_ones:
            print(f"  {s['id']}  {s['attributes']['state']:<20} {(s['attributes'].get('submittedDate') or '')[:10]}")

    builds = asc.get(f'/v1/builds?filter[app]={app_id}&sort=-uploadedDate&limit={max(1, args.builds)}'
                     '&fields[builds]=version,processingState,uploadedDate,preReleaseVersion'
                     '&include=preReleaseVersion&fields[preReleaseVersions]=version')
    marketing = {p['id']: p['attributes']['version'] for p in builds.get('included', [])
                 if p['type'] == 'preReleaseVersions'}
    print('\nrecent builds')
    for b in builds['data']:
        a = b['attributes']
        pre = ((b.get('relationships') or {}).get('preReleaseVersion') or {}).get('data') or {}
        print(f"  {marketing.get(pre.get('id'), '?'):<12} ({a['version']})  {a['processingState']:<12} "
              f"uploaded {(a.get('uploadedDate') or '')[:16]}")
    print(f'\nnext build number: {_asc.next_build_from_versions(asc.build_versions(app_id))}')


if __name__ == '__main__':
    sys.exit(main())
