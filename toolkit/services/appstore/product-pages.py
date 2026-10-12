#!/usr/bin/env python3
"""Create or resume localized custom product page drafts from verified screenshot folders.

cpm appstore product-pages --spec pages.json --out result.json [--commit]

Spec: bundleId, sourceVersion, platform IOS, pages [{name, campaignLocale,
localizations: [{locale, promotionalText, screenshots: [{display, folder}]}]}].
Relative folders resolve from the spec. Drafts only: never submits a review,
changes the original page, starts a campaign, or changes app availability.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


def validate_spec(spec):
    if spec.get('platform', 'IOS') != 'IOS' or not spec.get('sourceVersion'):
        raise ValueError('An explicit iOS sourceVersion is required.')
    pages = spec.get('pages', [])
    names = [p.get('name') for p in pages]
    if not 1 <= len(pages) <= 70 or any(not isinstance(n, str) or not 1 <= len(n) <= 64 for n in names) or len(set(names)) != len(names):
        raise ValueError('Provide 1–70 pages with unique names of 1–64 characters.')
    for page in pages:
        locales = page.get('localizations', [])
        codes = [l.get('locale') for l in locales]
        if not codes or any(not c for c in codes) or len(set(codes)) != len(codes):
            raise ValueError('Each page needs unique localizations.')
        if page.get('campaignLocale') not in codes:
            raise ValueError('Campaign locale must have matching localized assets.')
        for loc in locales:
            if not isinstance(loc.get('promotionalText'), str) or len(loc['promotionalText']) > 170:
                raise ValueError('Promotional text must be a string of at most 170 characters.')
            sets = loc.get('screenshots', [])
            displays = [s.get('display') for s in sets]
            if not sets or any(not d for d in displays) or len(set(displays)) != len(displays) or any(not s.get('folder') for s in sets):
                raise ValueError('Each locale needs unique display types and screenshot folders.')


def require_draft(version):
    if version['attributes'].get('state') != 'PREPARE_FOR_SUBMISSION':
        raise ValueError('Only a PREPARE_FOR_SUBMISSION custom page draft can be changed.')


def fingerprint(shot):
    a = shot['attributes']
    return a.get('fileName'), a.get('sourceFileChecksum'), a.get('fileSize')


def inspect_reconciliation(remote, files, source):
    """Classify matching files and proven inherited copies. Unknown assets abort."""
    names = [s['attributes']['fileName'] for s in remote]
    if len(set(names)) != len(names):
        raise ValueError('Remote draft contains duplicate file names.')
    wanted = {f['name']: f for f in files}
    source_ids = {s['id'] for s in source}
    source_fingerprints = {fingerprint(s) for s in source if s['attributes'].get('sourceFileChecksum')}
    kept, remove, resume = {}, [], []
    for shot in remote:
        a = shot['attributes']; name = a['fileName']; state = (a.get('assetDeliveryState') or {}).get('state')
        f = wanted.get(name)
        if f and a.get('sourceFileChecksum') == f['md5'] and state == 'COMPLETE':
            kept[name] = shot
        elif f and a.get('sourceFileChecksum') is None and a.get('fileSize') == f['bytes'] and state in ('UPLOAD_COMPLETE', 'AWAITING_UPLOAD'):
            if state == 'AWAITING_UPLOAD':
                resume.append(shot)
            kept[name] = shot
        elif shot['id'] not in source_ids and fingerprint(shot) in source_fingerprints:
            remove.append(shot)
        else:
            raise ValueError(f'Unknown or changed draft screenshot {name}; refusing to overwrite it.')
    return kept, remove, resume


def rel(kind, identifier):
    return {'data': {'type': kind, 'id': identifier}}


def create(asc, kind, attributes, relationships):
    return asc.call('POST', f'/v1/{kind}', {'data': {'type': kind,
        'attributes': attributes, 'relationships': relationships}})['data']


def page_create_body(app_id, source_id, planned):
    version_id = '${page-version}'
    loc_ids = ['${locale-' + str(i) + '}' for i in range(len(planned['localizations']))]
    return {'data': {'type': 'appCustomProductPages', 'attributes': {'name': planned['name']},
        'relationships': {'app': rel('apps', app_id),
            'appStoreVersionTemplate': rel('appStoreVersions', source_id),
            'appCustomProductPageVersions': {'data': [{'type': 'appCustomProductPageVersions', 'id': version_id}]}}},
        'included': [{'type': 'appCustomProductPageVersions', 'id': version_id,
            'relationships': {'appCustomProductPageLocalizations': {'data': [
                {'type': 'appCustomProductPageLocalizations', 'id': lid} for lid in loc_ids]}}}] + [
            {'type': 'appCustomProductPageLocalizations', 'id': lid,
             'attributes': {'locale': loc['locale'], 'promotionalText': loc['promotionalText']}}
            for lid, loc in zip(loc_ids, planned['localizations'])]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args(argv)
    path = Path(args.spec).resolve(); spec = json.loads(path.read_text()); validate_spec(spec)
    import _asc
    import screenshots
    from experiment import prefix_length
    for page in spec['pages']:
        for loc in page['localizations']:
            for target in loc['screenshots']:
                files = [Path(p) for p in screenshots.pick_files(path.parent / target['folder'])]
                if not 1 <= len(files) <= 10 or target['display'] not in screenshots.SIZES:
                    raise ValueError('Each supported display needs 1–10 screenshots.')
                target['files'] = []
                for f in files:
                    if screenshots.png_size(f) not in screenshots.SIZES[target['display']]:
                        raise ValueError(f'Unsupported screenshot dimensions: {f}')
                    target['files'].append({'path': str(f), 'name': f.name, 'bytes': f.stat().st_size,
                                            'md5': hashlib.md5(f.read_bytes()).hexdigest()})
    asc = _asc.ASC(); app_id, app_name = asc.app(_asc.resolve_bundle_id(spec.get('bundleId')))
    versions = asc.store_versions(app_id)
    source = next((v for v in versions if v['attributes']['versionString'] == spec['sourceVersion']), None)
    if not source: raise ValueError('The specified source version is absent.')
    primary = asc.get(f'/v1/apps/{app_id}')['data']['attributes']['primaryLocale']
    source_locs = asc.get_all(f"/v1/appStoreVersions/{source['id']}/appStoreVersionLocalizations?limit=50")
    source_codes = {l['attributes']['locale'] for l in source_locs}
    for p in spec['pages']:
        codes = {l['locale'] for l in p['localizations']}
        if primary not in codes:
            raise ValueError(f"Page {p['name']} requires primary locale {primary}.")
        if not codes <= source_codes:
            missing = ', '.join(sorted(codes - source_codes))
            raise ValueError(f"Page {p['name']}: add {missing} to source iOS version "
                             f"{spec['sourceVersion']} localizations first. Apple rejects custom-page "
                             'locales absent from that version, even when the App Store supports them.')
    remote_pages = asc.get_all(f'/v1/apps/{app_id}/appCustomProductPages?limit=200')
    if len(remote_pages) + sum(not any(r['attributes']['name'] == p['name'] for r in remote_pages) for p in spec['pages']) > 70:
        raise ValueError('The plan exceeds the custom product page limit.')
    for p in spec['pages']:
        matches = [r for r in remote_pages if r['attributes']['name'] == p['name']]
        if len(matches) > 1: raise ValueError('Ambiguous duplicate page name.')
        if matches:
            vs = asc.get_all(f"/v1/appCustomProductPages/{matches[0]['id']}/appCustomProductPageVersions?limit=50")
            if len(vs) != 1: raise ValueError('Refusing an established page with multiple versions.')
            require_draft(vs[0])
        print(f"{p['name']}: " + ', '.join(l['locale'] for l in p['localizations']), flush=True)
    print(f"{app_name}: source iOS {spec['sourceVersion']} ({source['attributes']['appStoreState']}); drafts only.", flush=True)
    if not args.commit:
        print('DRY RUN. No pages, assets or reviews changed.'); return
    report = {'appId': app_id, 'sourceVersion': spec['sourceVersion'], 'sourceVersionId': source['id'],
              'submitted': False, 'pages': [], 'allAssetsVerified': False}
    source_cache = {}; verification = []
    for planned in spec['pages']:
        page = next((r for r in remote_pages if r['attributes']['name'] == planned['name']), None)
        if not page:
            page = asc.call('POST', '/v1/appCustomProductPages', page_create_body(app_id, source['id'], planned))['data']
        pid = page['id']; print(f"Page {pid}: {planned['name']}", flush=True)
        vs = asc.get_all(f'/v1/appCustomProductPages/{pid}/appCustomProductPageVersions?limit=50')
        if not vs: vs = [create(asc, 'appCustomProductPageVersions', {}, {'appCustomProductPage': rel('appCustomProductPages', pid)})]
        if len(vs) != 1: raise ValueError('Unexpected multiple custom page versions.')
        version = vs[0]; require_draft(version); vid = version['id']
        locs = asc.get_all(f'/v1/appCustomProductPageVersions/{vid}/appCustomProductPageLocalizations?limit=50')
        if not {l['attributes']['locale'] for l in locs} <= source_codes:
            raise ValueError('Unexpected locale in custom page draft.')
        entry = {'id': pid, 'name': planned['name'], 'campaignLocale': planned['campaignLocale'],
                 'url': page['attributes'].get('url'), 'versionId': vid, 'state': version['attributes']['state'], 'localizations': []}
        for planned_loc in planned['localizations']:
            code = planned_loc['locale']; promo = planned_loc['promotionalText']
            loc = next((l for l in locs if l['attributes']['locale'] == code), None)
            if not loc:
                loc = create(asc, 'appCustomProductPageLocalizations', {'locale': code, 'promotionalText': promo},
                             {'appCustomProductPageVersion': rel('appCustomProductPageVersions', vid)})
            elif loc['attributes'].get('promotionalText') != promo:
                original = next(l for l in source_locs if l['attributes']['locale'] == code)['attributes'].get('promotionalText')
                if loc['attributes'].get('promotionalText') not in (None, '', original):
                    raise ValueError('Custom promotional text changed externally; refusing overwrite.')
                asc.call('PATCH', f"/v1/appCustomProductPageLocalizations/{loc['id']}", {'data': {
                    'type': 'appCustomProductPageLocalizations', 'id': loc['id'], 'attributes': {'promotionalText': promo}}})
            lid = loc['id']; locale_entry = {'locale': code, 'id': lid, 'promotionalText': promo, 'sets': []}
            sets = asc.get_all(f'/v1/appCustomProductPageLocalizations/{lid}/appScreenshotSets?limit=50')
            for target in planned_loc['screenshots']:
                key = code, target['display']
                if key not in source_cache:
                    sl = next(l for l in source_locs if l['attributes']['locale'] == code)
                    ss = asc.get_all(f"/v1/appStoreVersionLocalizations/{sl['id']}/appScreenshotSets?limit=50")
                    st = next((s for s in ss if s['attributes']['screenshotDisplayType'] == target['display']), None)
                    source_cache[key] = asc.get_all(f"/v1/appScreenshotSets/{st['id']}/appScreenshots?limit=50") if st else []
                st = next((s for s in sets if s['attributes']['screenshotDisplayType'] == target['display']), None)
                if not st:
                    st = create(asc, 'appScreenshotSets', {'screenshotDisplayType': target['display']},
                                {'appCustomProductPageLocalization': rel('appCustomProductPageLocalizations', lid)})
                sid = st['id']; shots_path = f'/v1/appScreenshotSets/{sid}/appScreenshots?limit=50'
                shots = asc.get_all(shots_path)
                kept, remove, resume = inspect_reconciliation(shots, target['files'], source_cache[key])
                require_draft(asc.get(f'/v1/appCustomProductPageVersions/{vid}')['data'])
                for shot in remove: asc.call('DELETE', f"/v1/appScreenshots/{shot['id']}")
                for shot in resume:
                    f = next(f for f in target['files'] if f['name'] == shot['attributes']['fileName'])
                    screenshots.resume_upload(asc, shot['id'], f['path'], asc._context, set_id=sid)
                for f in target['files']:
                    if f['name'] not in kept:
                        screenshots.upload(asc, sid, f['path'], asc._context)
                        print(f"  {code}: uploaded {f['name']}", flush=True)
                shots = asc.get_all(shots_path); by_name = {s['attributes']['fileName']: s for s in shots}
                ordered = [by_name[f['name']] for f in target['files']]
                if len(shots) != len(ordered): raise ValueError('Unexpected screenshots after upload.')
                prefix_length(ordered, target['files'], allow_processing=True)
                if [s['id'] for s in shots] != [s['id'] for s in ordered]:
                    asc.call('PATCH', f'/v1/appScreenshotSets/{sid}/relationships/appScreenshots', {
                        'data': [{'type': 'appScreenshots', 'id': s['id']} for s in ordered]})
                record = {'id': sid, 'display': target['display'], 'files': []}
                locale_entry['sets'].append(record); verification.append((shots_path, target['files'], record))
            locale_entry['promotionalTextVerified'] = asc.get(f'/v1/appCustomProductPageLocalizations/{lid}')['data']['attributes'].get('promotionalText') == promo
            if not locale_entry['promotionalTextVerified']: raise ValueError('Promotional text readback mismatch.')
            entry['localizations'].append(locale_entry)
        latest = asc.get(f'/v1/appCustomProductPages/{pid}')['data']; entry['url'] = latest['attributes'].get('url')
        require_draft(asc.get(f'/v1/appCustomProductPageVersions/{vid}')['data'])
        if not entry['url']: raise ValueError('Apple did not return a product page URL.')
        report['pages'].append(entry)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    # Upload all pages before polling Apple's processing queue.
    for _ in range(12):
        pending = 0
        for shots_path, files, record in verification:
            shots = asc.get_all(shots_path); prefix_length(shots, files, allow_processing=True)
            if len(shots) != len(files): raise ValueError('Missing custom page screenshots.')
            record['files'] = [{'name': s['attributes']['fileName'], 'state': s['attributes']['assetDeliveryState']['state'],
                'md5': s['attributes'].get('sourceFileChecksum'), 'expectedMd5': f['md5']} for s, f in zip(shots, files)]
            pending += sum(f['state'] != 'COMPLETE' for f in record['files'])
        report.update(allAssetsVerified=pending == 0, pendingAssets=pending, checkedAt=datetime.now(timezone.utc).isoformat())
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        if not pending: break
        print(f'Apple processing: {pending} screenshots pending.', flush=True); time.sleep(5)
    print(f"{len(report['pages'])} draft pages created; {report['pendingAssets']} assets processing. Report: {args.out}", flush=True)


if __name__ == '__main__': main()
