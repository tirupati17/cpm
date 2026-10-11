#!/usr/bin/env python3
"""Submit an existing iOS review basket with exactly one specified version/build.

    cpm appstore submit --version 1.2.3 --build 42
    cpm appstore submit --version 1.2.3 --build 42 --commit

Requires a READY_FOR_REVIEW version already added for review in App Store Connect.
Does not upload, attach, edit metadata, create items or cancel existing reviews.
"""
import argparse


def validate_version(document, version, build):
    record = document['data']
    attrs = record['attributes']
    if (attrs['platform'], attrs['versionString'], attrs['appStoreState']) != (
            'IOS', version, 'READY_FOR_REVIEW'):
        raise ValueError('expected iOS version is not READY_FOR_REVIEW')
    relation = record.get('relationships', {}).get('build', {}).get('data')
    attached = next((item for item in document.get('included', [])
                     if relation and item['type'] == 'builds' and item['id'] == relation['id']), None)
    if not attached or attached['attributes'].get('version') != build:
        raise ValueError('attached build does not match --build')
    if attached['attributes'].get('processingState') != 'VALID' or attached['attributes'].get('expired'):
        raise ValueError('attached build is not valid or has expired')
    return record['id']


def validate_items(items, version_id):
    if len(items) != 1:
        raise ValueError('basket must contain exactly one item; inspect extra or missing items in App Store Connect')
    item = items[0]
    relation = item.get('relationships', {}).get('appStoreVersion', {}).get('data')
    if (relation != {'type': 'appStoreVersions', 'id': version_id}
            or item['attributes']['state'] != 'READY_FOR_REVIEW'):
        raise ValueError('basket does not contain the expected ready version')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', required=True)
    p.add_argument('--build', required=True)
    p.add_argument('--bundle-id')
    p.add_argument('--commit', action='store_true')
    args = p.parse_args(argv)
    import _asc
    asc = _asc.ASC()
    app_id, name = asc.app(_asc.resolve_bundle_id(args.bundle_id))
    versions = asc.get_all(f'/v1/apps/{app_id}/appStoreVersions?filter[platform]=IOS&limit=200')
    found = [v for v in versions if v['attributes']['versionString'] == args.version]
    if len(found) != 1:
        p.error('expected exactly one matching iOS store version')
    version_id = found[0]['id']
    version_path = f'/v1/appStoreVersions/{version_id}?include=build'
    try:
        validate_version(asc.get(version_path), args.version, args.build)
    except ValueError as error:
        p.error(str(error))
    submissions = asc.get_all(f'/v1/reviewSubmissions?filter[app]={app_id}&filter[platform]=IOS'
                              '&filter[state]=READY_FOR_REVIEW&limit=200')
    matching = []
    for submission in submissions:
        items = asc.get_all(f"/v1/reviewSubmissions/{submission['id']}/items?include=appStoreVersion&limit=200")
        if any((item.get('relationships', {}).get('appStoreVersion', {}).get('data') or {}).get('id')
               == version_id for item in items):
            try:
                validate_items(items, version_id)
            except ValueError as error:
                p.error(str(error))
            matching.append(submission)
    if len(matching) != 1:
        p.error('expected exactly one READY_FOR_REVIEW basket containing this version')
    submission_id = matching[0]['id']
    print(f'{name}: iOS {args.version} ({args.build}), review basket {submission_id}')
    if not args.commit:
        print('DRY RUN. Would submit this existing basket; nothing written.')
        return
    # Recheck immediately before the mutation to catch edits after the initial plan.
    try:
        validate_version(asc.get(version_path), args.version, args.build)
        validate_items(asc.get_all(f'/v1/reviewSubmissions/{submission_id}/items'
                                  '?include=appStoreVersion&limit=200'), version_id)
    except ValueError as error:
        p.error(str(error))
    asc.call('PATCH', f'/v1/reviewSubmissions/{submission_id}', {'data': {
        'type': 'reviewSubmissions', 'id': submission_id, 'attributes': {'submitted': True}}})
    submission = asc.get(f'/v1/reviewSubmissions/{submission_id}')['data']['attributes']
    version = asc.get(version_path)['data']['attributes']
    print(f"READBACK: submission {submission['state']}; version {version['appStoreState']}; "
          f"submitted {submission.get('submittedDate')}")


if __name__ == '__main__':
    main()
