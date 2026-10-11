#!/usr/bin/env python3
"""Create or resume a draft screenshot experiment (dry run unless --commit).

cpm appstore experiment --spec round.json [--out result.json] [--replace-inherited] [--commit]

Spec: bundleId, name, platform (IOS), trafficProportion, treatments containing
name and screenshots [{locale, display, folder}]. Folder paths are relative to
the spec. Only named PREPARE_FOR_SUBMISSION drafts are resumed. Existing files
must be an exact prefix of the local set. --replace-inherited replaces only
distinct draft copies whose fingerprints match the current live screenshots.
Never starts a test, submits a review, changes a live page, or edits an app version.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


def validate_spec(spec):
    if not isinstance(spec.get('name'), str) or not 1 <= len(spec['name']) <= 64:
        raise ValueError('Experiment name must contain 1–64 characters.')
    if spec.get('platform', 'IOS') != 'IOS':
        raise ValueError('Only IOS product-page experiments are supported.')
    treatments = spec.get('treatments', [])
    if not 1 <= len(treatments) <= 3:
        raise ValueError('An experiment needs 1–3 treatments.')
    names = [t.get('name') for t in treatments]
    if any(not isinstance(n, str) or not 1 <= len(n) <= 64 for n in names) or len(set(names)) != len(names):
        raise ValueError('Treatment names must be nonempty and unique.')
    traffic = spec.get('trafficProportion')
    if type(traffic) is not int or not 1 <= traffic <= 100:
        raise ValueError('trafficProportion must be an integer from 1 to 100.')
    locale_sets = []
    for treatment in treatments:
        sets = treatment.get('screenshots', [])
        if not sets or any(not s.get('locale') or not s.get('display') or not s.get('folder') for s in sets):
            raise ValueError('Each treatment needs locale, display and folder for each screenshot set.')
        identities = [(s['locale'], s['display']) for s in sets]
        if len(identities) != len(set(identities)):
            raise ValueError('Duplicate locale/display screenshot set.')
        locale_sets.append(set(identities))
    if any(s != locale_sets[0] for s in locale_sets):
        raise ValueError('Treatments must target the same locales and display sizes.')


def verify_draft(experiment, spec):
    attrs = experiment['attributes']
    if attrs.get('state') != 'PREPARE_FOR_SUBMISSION' or attrs.get('startDate'):
        raise ValueError('Only an unstarted PREPARE_FOR_SUBMISSION draft can be resumed.')
    for key in ('name', 'trafficProportion'):
        if attrs.get(key) != spec[key]:
            raise ValueError(f'Existing experiment differs in {key}; refusing to overwrite it.')
    if attrs.get('platform') != spec.get('platform', 'IOS'):
        raise ValueError('Existing experiment platform differs.')


def prefix_length(shots, files):
    if len(shots) > len(files):
        raise ValueError('Remote set contains additional screenshots; refusing to replace it.')
    for shot, file in zip(shots, files):
        a = shot['attributes']
        if a.get('fileName') != file['name'] or a.get('sourceFileChecksum') != file['md5']:
            raise ValueError(f"Remote screenshot differs from {file['name']}; inspect the draft before retrying.")
        if (a.get('assetDeliveryState') or {}).get('state') == 'FAILED':
            raise ValueError(f"Apple rejected {file['name']}; inspect the draft before retrying.")
    return len(shots)


def relationship(kind, identifier):
    return {'data': {'type': kind, 'id': identifier}}


def verified_inherited(shots, control):
    def fingerprint(shot):
        a = shot['attributes']
        return a.get('fileName'), a.get('sourceFileChecksum'), a.get('fileSize')
    return (bool(shots) and len(shots) == len(control)
            and not ({s['id'] for s in shots} & {s['id'] for s in control})
            and all(s['attributes'].get('sourceFileChecksum') for s in shots)
            and [fingerprint(s) for s in shots] == [fingerprint(s) for s in control])


def create(asc, kind, attrs, rels, version='v1'):
    return asc.call('POST', f'/{version}/{kind}', {'data': {
        'type': kind, 'attributes': attrs, 'relationships': rels}})['data']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', help='write verified experiment IDs and asset checksums')
    parser.add_argument('--commit', action='store_true')
    parser.add_argument('--replace-inherited', action='store_true',
                        help='replace distinct draft copies only when they match the live screenshot set')
    args = parser.parse_args(argv)
    path = Path(args.spec).resolve()
    spec = json.loads(path.read_text())
    validate_spec(spec)
    import screenshots
    import _asc
    # Validate every local file before creating any remote object.
    work = []
    for treatment in spec['treatments']:
        sets = []
        for item in treatment['screenshots']:
            folder = path.parent / item['folder']
            files = [Path(f) for f in screenshots.pick_files(folder)]
            if not 1 <= len(files) <= 10:
                raise ValueError(f'{folder}: expected 1–10 screenshots.')
            if item['display'] not in screenshots.SIZES:
                raise ValueError(f"Unsupported display {item['display']}")
            records = []
            for file in files:
                if screenshots.png_size(file) not in screenshots.SIZES[item['display']]:
                    raise ValueError(f'{file}: not a supported PNG screenshot size.')
                records.append({'path': str(file), 'name': file.name,
                                'md5': hashlib.md5(file.read_bytes()).hexdigest()})
            sets.append({**item, 'files': records})
        work.append({'name': treatment['name'], 'sets': sets})
    asc = _asc.ASC()
    app_id, app_name = asc.app(_asc.resolve_bundle_id(spec.get('bundleId')))
    versions = asc.store_versions(app_id)
    live = next((v for v in versions if v['attributes']['appStoreState'] in ('READY_FOR_SALE', 'READY_FOR_DISTRIBUTION')), None)
    if not live:
        raise ValueError('A live iOS app version is required for a product-page experiment.')
    live_locs = asc.get_all(f"/v1/appStoreVersions/{live['id']}/appStoreVersionLocalizations?limit=50")
    locales = {l['attributes']['locale'] for l in live_locs}
    if any(s['locale'] not in locales for t in work for s in t['sets']):
        raise ValueError('A requested localization is absent from the live app version.')
    existing = asc.get_all(f'/v1/apps/{app_id}/appStoreVersionExperimentsV2?limit=200')
    matching = [e for e in existing if e['attributes']['name'] == spec['name']]
    if len(matching) > 1:
        raise ValueError('Multiple experiments share this name; use a unique name.')
    experiment = matching[0] if matching else None
    if not experiment and any(e['attributes']['state'] == 'PREPARE_FOR_SUBMISSION' for e in existing):
        raise ValueError('Apple allows only one draft experiment per app. Finish the existing round before creating another.')
    if experiment:
        verify_draft(experiment, spec)
    print(f"{app_name}: {spec['name']} — draft only; {spec['trafficProportion']}% total treatment traffic", flush=True)
    for t in work:
        print(f"  {t['name']}: " + ', '.join(f"{s['locale']} {s['display']} ({len(s['files'])} files)" for s in t['sets']), flush=True)
    if not args.commit:
        print('DRY RUN. No experiment or assets changed. Re-run with --commit.')
        return
    if not experiment:
        experiment = create(asc, 'appStoreVersionExperiments', {
            'name': spec['name'], 'platform': 'IOS', 'trafficProportion': spec['trafficProportion']},
            {'app': relationship('apps', app_id)}, version='v2')
    eid = experiment['id']
    verify_draft(experiment, spec)
    print(f'Experiment {eid}', flush=True)
    remote = asc.get_all(f'/v2/appStoreVersionExperiments/{eid}/appStoreVersionExperimentTreatments?limit=200')
    expected_names = {t['name'] for t in work}
    if any(t['attributes']['name'] not in expected_names for t in remote):
        raise ValueError('Draft has unexpected treatments; refusing to modify it.')
    report = {'appId': app_id, 'experimentId': eid, 'name': spec['name'], 'treatments': []}
    controls = {}
    for planned in work:
        matches = [t for t in remote if t['attributes']['name'] == planned['name']]
        if len(matches) > 1:
            raise ValueError('Duplicate treatment names in the remote draft.')
        treatment = matches[0] if matches else create(asc, 'appStoreVersionExperimentTreatments',
            {'name': planned['name']}, {'appStoreVersionExperimentV2': relationship('appStoreVersionExperiments', eid)})
        tid = treatment['id']
        localizations = asc.get_all(f'/v1/appStoreVersionExperimentTreatments/{tid}/appStoreVersionExperimentTreatmentLocalizations?limit=50')
        if any(l['attributes']['locale'] not in {s['locale'] for s in planned['sets']} for l in localizations):
            raise ValueError('Treatment has unexpected localizations.')
        entry = {'id': tid, 'name': planned['name'], 'sets': []}
        for planned_set in planned['sets']:
            loc = next((l for l in localizations if l['attributes']['locale'] == planned_set['locale']), None)
            if not loc:
                loc = create(asc, 'appStoreVersionExperimentTreatmentLocalizations', {'locale': planned_set['locale']},
                    {'appStoreVersionExperimentTreatment': relationship('appStoreVersionExperimentTreatments', tid)})
                localizations.append(loc)
            sets = asc.get_all(f"/v1/appStoreVersionExperimentTreatmentLocalizations/{loc['id']}/appScreenshotSets?limit=50")
            target = next((s for s in sets if s['attributes']['screenshotDisplayType'] == planned_set['display']), None)
            if not target:
                target = create(asc, 'appScreenshotSets', {'screenshotDisplayType': planned_set['display']},
                    {'appStoreVersionExperimentTreatmentLocalization': relationship('appStoreVersionExperimentTreatmentLocalizations', loc['id'])})
            sid = target['id']
            shots_path = f'/v1/appScreenshotSets/{sid}/appScreenshots?limit=50'
            shots = asc.get_all(shots_path)
            try:
                offset = prefix_length(shots, planned_set['files'])
            except ValueError:
                if not args.replace_inherited:
                    raise
                key = planned_set['locale'], planned_set['display']
                if key not in controls:
                    live_loc = next(l for l in live_locs if l['attributes']['locale'] == key[0])
                    live_sets = asc.get_all(f"/v1/appStoreVersionLocalizations/{live_loc['id']}/appScreenshotSets?limit=50")
                    live_set = next(s for s in live_sets if s['attributes']['screenshotDisplayType'] == key[1])
                    control_path = f"/v1/appScreenshotSets/{live_set['id']}/appScreenshots?limit=50"
                    controls[key] = (live_set['id'], control_path, asc.get_all(control_path))
                control_id, control_path, control = controls[key]
                if sid == control_id or not verified_inherited(shots, control):
                    raise ValueError('Draft files do not match separate copies of the live set; refusing replacement.')
                verify_draft(asc.get(f'/v2/appStoreVersionExperiments/{eid}')['data'], spec)
                print(f"  {planned['name']}: replacing {len(shots)} verified inherited draft copies", flush=True)
                for shot in shots:
                    asc.call('DELETE', f"/v1/appScreenshots/{shot['id']}")
                offset = 0
            for file in planned_set['files'][offset:]:
                screenshots.upload(asc, sid, file['path'], asc._context)
                print(f"  {planned['name']}/{planned_set['locale']}: {file['name']}", flush=True)
            for _ in range(36):
                shots = asc.get_all(shots_path)
                prefix_length(shots, planned_set['files'])
                if len(shots) == len(planned_set['files']) and all(
                    (s['attributes'].get('assetDeliveryState') or {}).get('state') == 'COMPLETE' for s in shots):
                    break
                time.sleep(5)
            else:
                raise ValueError('Assets are still processing. Resume the same spec later; do not create a duplicate test.')
            entry['sets'].append({'id': sid, 'locale': planned_set['locale'], 'display': planned_set['display'],
                'files': [{'name': f['name'], 'md5': f['md5'], 'state': 'COMPLETE'} for f in planned_set['files']]})
        report['treatments'].append(entry)
    final = asc.get(f'/v2/appStoreVersionExperiments/{eid}')['data']
    verify_draft(final, spec)
    for _, control_path, before in controls.values():
        after = asc.get_all(control_path)
        if [(s['id'], s['attributes'].get('sourceFileChecksum')) for s in after] != [
                (s['id'], s['attributes'].get('sourceFileChecksum')) for s in before]:
            raise ValueError('The control page changed during this operation; inspect before starting the test.')
    report.update(state=final['attributes']['state'], trafficProportion=final['attributes']['trafficProportion'],
                  startDate=final['attributes'].get('startDate'), verifiedAt=datetime.now(timezone.utc).isoformat(),
                  controlScreenshotsPreserved=True)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + '\n')
    print(f"DRAFT VERIFIED: {eid}, {len(work)} treatments, all screenshot checksums and processing states match.", flush=True)


if __name__ == '__main__':
    main()
