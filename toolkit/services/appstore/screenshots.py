#!/usr/bin/env python3
"""Replace an App Store screenshot or app preview set from a folder (dry run unless --commit).

    cpm appstore screenshots ./shots/en --locale en-US
    cpm appstore screenshots ./shots/en --locale en-US --display APP_IPHONE_67 --version 1.0.2 --commit

Uploads to the EDITABLE store version (Prepare for Submission, Rejected, ...).
A live version's screenshots cannot change, so when none is editable this
creates one: --version names it (the release command later reuses and renames
an editable version, so a placeholder is safe). The folder's .png/.jpg files go
up in name order and replace whatever that display type held in that locale;
other locales and display types are untouched.

Display types: APP_IPHONE_67 takes the 6.9" 1320x2868 and 6.7" 1290x2796
captures; APP_IPHONE_65 the 6.5" 1242x2688; APP_IPHONE_DUO 1398x2034 or
2007x2853; APP_IPAD_PRO_3GEN_129 the 13" 2064x2752; APP_WATCH_ULTRA 422x514.
Up to 10 per set.

--previews uploads app preview videos (.mp4/.mov/.m4v, 15-30 s) instead, to the
preview set of --display (IPHONE_67, IPHONE_65; both take 886x1920). Up to 3.

Credentials: ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH, ASC_BUNDLE_ID.
"""
import argparse
import hashlib
import os
import sys
import time
import urllib.request

SIZES = {
    'APP_IPHONE_67': {(1320, 2868), (1290, 2796)},
    'APP_IPHONE_65': {(1242, 2688), (1284, 2778)},
    'APP_IPHONE_DUO': {(1398, 2034), (2034, 1398), (2007, 2853), (2853, 2007)},
    'APP_IPAD_PRO_3GEN_129': {(2064, 2752), (2752, 2064), (2048, 2732), (2732, 2048)},
    'APP_WATCH_ULTRA': {(410, 502), (422, 514)},
}


def png_size(path):
    """(width, height) of a PNG from its header, or None for anything else."""
    with open(path, 'rb') as f:
        head = f.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    return int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')


def pick_files(folder, exts=('.png', '.jpg', '.jpeg')):
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(exts))
    return [os.path.join(folder, f) for f in files]


# Screenshots and previews share one upload protocol under different names.
KINDS = {
    'screenshots': dict(item='appScreenshots', set='appScreenshotSets', rel='appScreenshotSet',
                        display='screenshotDisplayType', exts=('.png', '.jpg', '.jpeg'), most=10),
    'previews': dict(item='appPreviews', set='appPreviewSets', rel='appPreviewSet',
                     display='previewType', exts=('.mp4', '.mov', '.m4v'), most=3),
}
MIME = {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.m4v': 'video/x-m4v'}


def upload(asc, set_id, path, context, kind=KINDS['screenshots']):
    data = open(path, 'rb').read()
    attrs = {'fileName': os.path.basename(path), 'fileSize': len(data)}
    mime = MIME.get(os.path.splitext(path)[1].lower())
    if mime:
        attrs['mimeType'] = mime
    shot = asc.call('POST', f"/v1/{kind['item']}", {'data': {
        'type': kind['item'], 'attributes': attrs,
        'relationships': {kind['rel']: {'data': {'type': kind['set'], 'id': set_id}}}}})['data']
    for op in shot['attributes']['uploadOperations']:
        chunk = data[op['offset']:op['offset'] + op['length']]
        request = urllib.request.Request(op['url'], data=chunk, method=op['method'],
                                         headers={h['name']: h['value'] for h in op.get('requestHeaders', [])})
        with urllib.request.urlopen(request, context=context, timeout=120) as response:
            response.read()
    asc.call('PATCH', f"/v1/{kind['item']}/{shot['id']}", {'data': {
        'type': kind['item'], 'id': shot['id'],
        'attributes': {'uploaded': True, 'sourceFileChecksum': hashlib.md5(data).hexdigest()}}})
    return shot['id']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder', help='folder of screenshots, uploaded in name order')
    parser.add_argument('--locale', default='en-US')
    parser.add_argument('--display', default='APP_IPHONE_67', help='screenshotDisplayType (default APP_IPHONE_67)')
    parser.add_argument('--version', help='versionString for a new editable version if none exists')
    parser.add_argument('--bundle-id', help='app bundle id (default: ASC_BUNDLE_ID credential)')
    parser.add_argument('--previews', action='store_true', help='upload app preview videos instead of screenshots')
    parser.add_argument('--commit', action='store_true', help='actually change App Store Connect')
    args = parser.parse_args(argv)

    import _asc
    kind = KINDS['previews' if args.previews else 'screenshots']
    if args.previews and args.display == 'APP_IPHONE_67':
        args.display = 'IPHONE_67'
    files = pick_files(args.folder, kind['exts'])
    if not files:
        _asc.die(f"no {'/'.join(kind['exts'])} in {args.folder}")
    if len(files) > kind['most']:
        _asc.die(f"{len(files)} files; a set holds at most {kind['most']}")
    allowed = None if args.previews else SIZES.get(args.display)
    for f in files:
        size = png_size(f)
        if allowed and size and size not in allowed:
            _asc.die(f'{os.path.basename(f)} is {size[0]}x{size[1]}, not a {args.display} size {sorted(allowed)}')

    asc = _asc.ASC()
    app_id, name = asc.app(_asc.resolve_bundle_id(args.bundle_id))
    versions = asc.store_versions(app_id)
    editable, _ = _asc.split_versions(versions)
    # Added to a review submission but not yet submitted: still editable.
    editable = editable or next((v for v in versions if v['attributes']['appStoreState'] == 'READY_FOR_REVIEW'), None)
    print(f'{name}: {len(files)} screenshots -> {args.locale} {args.display}')
    if editable is None:
        if not args.version:
            _asc.die('no editable version; pass --version to create one')
        if not args.commit:
            print(f'  would create iOS version {args.version}, then replace the set')
            for f in files:
                print(f'  would upload {os.path.basename(f)}')
            return 0
        print(f'creating iOS version {args.version}')
        editable = asc.call('POST', '/v1/appStoreVersions', {'data': {
            'type': 'appStoreVersions', 'attributes': {'platform': 'IOS', 'versionString': args.version},
            'relationships': {'app': {'data': {'type': 'apps', 'id': app_id}}}}})['data']
        time.sleep(5)  # the copied localizations appear a moment after the version
    print(f"  version {editable['attributes']['versionString']} ({editable['attributes']['appStoreState']})")

    locs = asc.get(f"/v1/appStoreVersions/{editable['id']}/appStoreVersionLocalizations?limit=50")['data']
    loc = next((l for l in locs if l['attributes']['locale'] == args.locale), None)
    if loc is None:
        _asc.die(f"no {args.locale} localization; have {', '.join(l['attributes']['locale'] for l in locs)}")
    sets = asc.get(f"/v1/appStoreVersionLocalizations/{loc['id']}/{kind['set']}?limit=50")['data']
    target = next((s for s in sets if s['attributes'][kind['display']] == args.display), None)
    old = asc.get(f"/v1/{kind['set']}/{target['id']}/{kind['item']}?limit=50")['data'] if target else []
    print(f"  {len(old)} existing {'previews' if args.previews else 'screenshots'} in that set will be replaced")
    if not args.commit:
        for f in files:
            print(f'  would upload {os.path.basename(f)}')
        print('dry run; pass --commit')
        return 0

    if target is None:
        target = asc.call('POST', f"/v1/{kind['set']}", {'data': {
            'type': kind['set'], 'attributes': {kind['display']: args.display},
            'relationships': {'appStoreVersionLocalization': {
                'data': {'type': 'appStoreVersionLocalizations', 'id': loc['id']}}}}})['data']
    for s in old:
        asc.call('DELETE', f"/v1/{kind['item']}/{s['id']}")
    for f in files:
        upload(asc, target['id'], f, asc._context, kind)
        print(f'  uploaded {os.path.basename(f)}')

    # Apple processes each file after upload; report any it rejected. A video
    # keeps processing for a while, so a preview only reports what it saw.
    for _ in range(24):
        shots = asc.get(f"/v1/{kind['set']}/{target['id']}/{kind['item']}?limit=50")['data']
        states = [(s['attributes'].get('assetDeliveryState') or {}).get('state') for s in shots]
        if all(st in ('COMPLETE', 'FAILED') for st in states):
            break
        time.sleep(5)
    failed = [s['attributes']['fileName'] for s, st in zip(shots, states) if st == 'FAILED']
    print(f"{len(shots)} in set, {states.count('COMPLETE')} processed" + (f", FAILED: {failed}" if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
