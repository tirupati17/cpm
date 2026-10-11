#!/usr/bin/env python3
"""Update localized App Store descriptions, keywords and promotional text from JSON.

    cpm appstore metadata --spec listing.json
    cpm appstore metadata --spec listing.json --backup before.json --commit

The spec names bundleId, platform, version and localizations keyed by store locale.
Each locale contains description, keywords and/or promotionalText. Only named fields
are patched, only existing locales are used, and no English fallback is introduced.
The default is a read-only plan. --commit requires a new backup path, checks for
concurrent edits before each PATCH, and independently reads every change back.
This command never attaches builds, changes images or submits for review.
"""
import argparse
import json
from pathlib import Path

FIELDS = {'description': 4000, 'keywords': 100, 'promotionalText': 170}


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) != {'bundleId', 'platform', 'version', 'localizations'}:
        raise ValueError('spec must contain bundleId, platform, version and localizations')
    for key in ('bundleId', 'version'):
        if not isinstance(spec[key], str) or not spec[key].strip():
            raise ValueError(f'{key} must be a nonempty string')
    if spec['platform'] not in ('IOS', 'MAC_OS', 'TV_OS', 'VISION_OS'):
        raise ValueError('unsupported platform')
    locales = spec['localizations']
    if not isinstance(locales, dict) or not locales:
        raise ValueError('localizations must be a nonempty locale-to-fields object')
    for locale, fields in locales.items():
        if not locale or not isinstance(fields, dict) or not fields or set(fields) - FIELDS.keys():
            raise ValueError(f'{locale}: only description, keywords and promotionalText are supported')
        for field, value in fields.items():
            if not isinstance(value, str) or (field != 'promotionalText' and not value.strip()):
                raise ValueError(f'{locale}.{field}: expected text, not null or an empty required field')
            count = len(value.encode('utf-8')) if field == 'keywords' else len(value)
            if count > FIELDS[field]:
                raise ValueError(f'{locale}.{field}: {count} exceeds {FIELDS[field]} '
                                 f'{"UTF-8 bytes" if field == "keywords" else "characters"}')
            if field == 'keywords':
                terms = value.split(',')
                if any(not term or term != term.strip() for term in terms):
                    raise ValueError(f'{locale}: keywords need nonempty comma-separated terms without padding')
                if len({term.casefold() for term in terms}) != len(terms):
                    raise ValueError(f'{locale}: duplicate keywords')
    return spec


def plan_changes(spec, localizations):
    current = {loc['attributes']['locale']: loc for loc in localizations}
    missing = set(spec['localizations']) - current.keys()
    if missing:
        raise ValueError('store locales missing: ' + ', '.join(sorted(missing)))
    changes = []
    for locale, fields in sorted(spec['localizations'].items()):
        loc = current[locale]
        patch = {key: value for key, value in fields.items() if loc['attributes'].get(key) != value}
        if patch:
            changes.append({'locale': locale, 'id': loc['id'], 'attributes': patch,
                            'before': {key: loc['attributes'].get(key) for key in patch}})
    return changes


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--spec', required=True)
    p.add_argument('--backup', help='new JSON path for the pre-edit snapshot; required with --commit')
    p.add_argument('--commit', action='store_true')
    args = p.parse_args(argv)
    try:
        spec = validate_spec(json.loads(Path(args.spec).read_text(encoding='utf-8')))
    except (ValueError, OSError) as error:
        p.error(str(error))
    if args.commit and not args.backup:
        p.error('--commit requires --backup for a pre-edit snapshot')
    if args.commit and Path(args.backup).exists():
        p.error('backup already exists; choose a new path so earlier evidence is preserved')

    import _asc
    asc = _asc.ASC()
    app_id, name = asc.app(spec['bundleId'])
    versions = asc.get_all(f"/v1/apps/{app_id}/appStoreVersions?filter[platform]={spec['platform']}&limit=200"
                           '&fields[appStoreVersions]=versionString,appStoreState')
    found = [v for v in versions if v['attributes']['versionString'] == spec['version']]
    if len(found) != 1:
        p.error(f"expected exactly one existing {spec['platform']} version {spec['version']}")
    version = found[0]
    # READY_FOR_REVIEW is an unsubmitted basket: metadata can still be edited.
    # Do not cancel it or alter its images/build just to update its text.
    if version['attributes']['appStoreState'] not in _asc.EDITABLE | {'READY_FOR_REVIEW'}:
        p.error('version is not editable; this command never cancels review')
    localizations = asc.get_all(f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations?limit=200")
    try:
        changes = plan_changes(spec, localizations)
    except ValueError as error:
        p.error(str(error))
    print(f"{name} {spec['platform']} {spec['version']} ({version['attributes']['appStoreState']})")
    for change in changes:
        print(f"  {change['locale']}: {', '.join(change['attributes'])}")
        for field, value in change['attributes'].items():
            print(f'    {field}: ' + (f'{len(value)} characters' if field == 'description' else value))
    if not args.commit:
        print(f'DRY RUN. {len(changes)} locales would change. Nothing written.')
        return
    snapshot = {'appId': app_id, 'version': version, 'localizations': localizations}
    with Path(args.backup).open('x', encoding='utf-8') as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    for change in changes:
        path = f"/v1/appStoreVersionLocalizations/{change['id']}"
        before = asc.get(path)['data']['attributes']
        if any(before.get(key) != value for key, value in change['before'].items()):
            p.error(f"{change['locale']} changed since planning; stopped before overwriting the concurrent edit")
        asc.call('PATCH', path, {'data': {'type': 'appStoreVersionLocalizations',
                 'id': change['id'], 'attributes': change['attributes']}})
        after = asc.get(path)['data']['attributes']
        if any(after.get(key) != value for key, value in change['attributes'].items()):
            p.error(f"{change['locale']}: readback mismatch; inspect backup and remote state before retrying")
        print(f"  VERIFIED {change['locale']}", flush=True)
    print(f'UPDATED AND VERIFIED {len(changes)} locales. No review submission performed.')


if __name__ == '__main__':
    main()
