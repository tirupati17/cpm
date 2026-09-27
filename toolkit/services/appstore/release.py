#!/usr/bin/env python3
"""Archive, upload and submit an iOS app to App Store review in one command.

    cpm appstore release                          # dry run: checks + plan, changes nothing
    cpm appstore release --commit                 # archive, upload, attach, What's New, submit
    cpm appstore release --commit --replace-in-review
    cpm appstore release --commit --archive /tmp/cpm-appstore/App/App-1.2-40.xcarchive   # reuse an archive
    cpm appstore release --commit --no-submit     # stop after attaching; submit by hand

Steps, in order:
  1. Version = the app target's MARKETING_VERSION (see `cpm appstore version`).
     What's New = <notes-dir>/<version>/<locale>.txt, one per App Store locale
     (en-US is the fallback for any locale without a file). Refuses without en-US.
  2. Build number = App Store Connect's highest uploaded build + 1, asked, not
     counted: Xcode, CI and hand uploads all bump it and a local counter drifts.
  3. Archive (Release, generic iOS) with that version forced onto every embedded
     target, then export with destination=upload, signed automatically via the
     API key. Needs an Xcode whose SDK covers every API the app uses.
  4. Wait for App Store Connect to finish processing the build.
  5. Find the iOS version to ship: an editable one, or with --replace-in-review
     cancel the one in review first. Otherwise create a new one. Its version
     string is set to the marketing version so the two stop drifting apart.
  6. Attach the build, write What's New for every locale, submit for review.

Project discovery (all overridable): --repo defaults to the git toplevel of the
current directory; the only .xcworkspace there, else the only .xcodeproj; the
shared scheme named after it, else the only shared scheme; the team from the app
target's DEVELOPMENT_TEAM, else ASC_TEAM_ID.

Credentials (never printed): ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH and
ASC_BUNDLE_ID (or --bundle-id), resolved by `cpm creds`: environment first,
then ~/.config/cpm/<project>/credentials.env, then a one-time prompt.
Set INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = NO in the app target (when
true for your app) so processing does not stop at an export-compliance prompt.
"""
import argparse
import os
import plistlib
import subprocess
import sys
import tempfile
import time

import _xcode
from _xcode import die


# -- local: Xcode ------------------------------------------------------------------

class Xcode:
    """Where and how to archive. Resolved once, printed in the plan."""

    def __init__(self, args, root, bundle_id):
        self.root = root
        self.kind, self.container = _xcode.find_container(root, args.xcodeproj, args.workspace)
        pbx_path = _xcode.pbxproj_path(root, args.xcodeproj)
        # Shared schemes live in the .xcodeproj (and, for a workspace, may live there too).
        self.scheme = _xcode.pick_scheme([self.container, os.path.dirname(pbx_path)], args.scheme)
        with open(pbx_path, encoding='utf-8') as handle:
            pbx = handle.read()
        self.version = _xcode.marketing_version(pbx, bundle_id)
        if not self.version:
            die(f'no MARKETING_VERSION for {bundle_id} in the project; is --bundle-id the app target?')
        self.team = args.team_id or _xcode.development_team(pbx, bundle_id)
        if not self.team:
            from cpmkit import creds
            self.team = creds.get('ASC_TEAM_ID')
        self.build_dir = os.path.abspath(args.build_dir or os.path.join(tempfile.gettempdir(), 'cpm-appstore',
                                                                        self.scheme.replace(' ', '_')))

    def describe(self):
        return (f'{self.kind} {os.path.relpath(self.container, self.root)}  scheme {self.scheme}  '
                f'team {self.team}  build dir {self.build_dir}')


def archive(xcode, asc, version, build):
    os.makedirs(xcode.build_dir, exist_ok=True)
    name = xcode.scheme.replace(' ', '_')
    path = os.path.join(xcode.build_dir, f'{name}-{version}-{build}.xcarchive')
    log = os.path.join(xcode.build_dir, f'archive-{build}.log')
    print(f'archiving {version} ({build}) -> {path}  (log: {log})')
    # Derived data under the temp dir, not the repo: when the repo lives in an
    # iCloud-synced folder, the file provider adds xattrs that break codesigning.
    command = ['xcodebuild', f'-{xcode.kind}', xcode.container, '-scheme', xcode.scheme,
               '-configuration', 'Release', '-destination', 'generic/platform=iOS',
               '-derivedDataPath', xcode.build_dir, '-archivePath', path,
               *asc.auth_flags(), f'CURRENT_PROJECT_VERSION={build}', f'MARKETING_VERSION={version}', 'archive']
    with open(log, 'w') as out:
        if subprocess.call(command, cwd=xcode.root, stdout=out, stderr=subprocess.STDOUT) != 0:
            with open(log) as handle:
                errors = [line for line in handle if ' error: ' in line or 'ARCHIVE FAILED' in line]
            die('archive failed:\n' + ''.join(sorted(set(errors))[:20]))
    return path


def archive_identity(path):
    with open(os.path.join(path, 'Info.plist'), 'rb') as handle:
        info = plistlib.load(handle)['ApplicationProperties']
    return info['CFBundleShortVersionString'], info['CFBundleVersion']


def export_options(team):
    # manageAppVersionAndBuildNumber off: the numbers were chosen on purpose above.
    return {'method': 'app-store-connect', 'destination': 'upload', 'teamID': team, 'uploadSymbols': True,
            'signingStyle': 'automatic', 'manageAppVersionAndBuildNumber': False}


def upload(xcode, asc, path):
    os.makedirs(xcode.build_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        plist = os.path.join(tmp, 'ExportUpload.plist')
        with open(plist, 'wb') as handle:
            plistlib.dump(export_options(xcode.team), handle)
        log = os.path.join(xcode.build_dir, 'upload.log')
        print(f'exporting and uploading  (log: {log})')
        with open(log, 'w') as out:
            code = subprocess.call(['xcodebuild', '-exportArchive', '-archivePath', path, '-exportPath', tmp,
                                    '-exportOptionsPlist', plist, *asc.auth_flags()],
                                   cwd=xcode.root, stdout=out, stderr=subprocess.STDOUT)
        if code != 0:
            with open(log) as handle:
                text = handle.read()
            # A build still being processed is invisible to the builds API, so a
            # re-run can upload it twice. Apple's rejection of the duplicate means
            # the first upload landed; carry on to the processing wait.
            if _xcode.upload_was_duplicate(text):
                print('  this build was already uploaded; waiting for it instead')
                return
            errors = [line for line in text.splitlines(True) if 'error' in line.lower()]
            die('upload failed:\n' + ''.join(errors[-15:]))


# -- remote: App Store Connect -----------------------------------------------------

def wait_for_build(asc, app_id, version, build, minutes=45):
    print(f'waiting for App Store Connect to process build {build}', end='', flush=True)
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        found = asc.find_build(app_id, version, build)
        state = found[0]['attributes']['processingState'] if found else 'NOT_YET_VISIBLE'
        if state == 'VALID':
            print(' VALID')
            return found[0]['id']
        if state in ('FAILED', 'INVALID'):
            die(f'build {build} processing ended {state}')
        print('.', end='', flush=True)
        time.sleep(30)
    die(f'build {build} still not processed after {minutes} minutes; re-run with --archive to continue')


def cancel_review(asc, app_id):
    import _asc
    submissions = asc.get(f'/v1/reviewSubmissions?filter[app]={app_id}&filter[platform]=IOS&limit=10'
                          '&fields[reviewSubmissions]=state')['data']
    for submission in submissions:
        if submission['attributes']['state'] in _asc.CANCELLABLE_SUBMISSION:
            print(f"cancelling review submission {submission['id']} ({submission['attributes']['state']})")
            asc.call('PATCH', f"/v1/reviewSubmissions/{submission['id']}",
                     {'data': {'type': 'reviewSubmissions', 'id': submission['id'], 'attributes': {'canceled': True}}})


def version_to_ship(asc, app_id, version, replace, commit, settle_wait=15):
    import _asc
    versions = asc.store_versions(app_id)
    for v in versions:
        print(f"  iOS version {v['attributes']['versionString']}: {v['attributes']['appStoreState']}")
    editable, reviewing = _asc.split_versions(versions)
    if reviewing and not editable:
        if not replace:
            die(f"version {reviewing['attributes']['versionString']} is {reviewing['attributes']['appStoreState']}; "
                'pass --replace-in-review to cancel it and ship this build instead, or wait for it')
        if not commit:
            print(f"  would cancel review of {reviewing['attributes']['versionString']} and reuse that version")
            return reviewing
        cancel_review(asc, app_id)
        for _ in range(40):  # cancellation settles asynchronously
            state = asc.get(f"/v1/appStoreVersions/{reviewing['id']}?fields[appStoreVersions]=appStoreState"
                            )['data']['attributes']['appStoreState']
            if state in _asc.EDITABLE:
                editable = reviewing
                break
            time.sleep(settle_wait)
        else:
            die('review cancelled but the version never became editable; check App Store Connect')
    if editable is None:
        if not commit:
            print(f'  would create iOS version {version}')
            return None
        print(f'creating iOS version {version}')
        editable = asc.call('POST', '/v1/appStoreVersions', {'data': {
            'type': 'appStoreVersions', 'attributes': {'platform': 'IOS', 'versionString': version},
            'relationships': {'app': {'data': {'type': 'apps', 'id': app_id}}}}})['data']
    if editable['attributes']['versionString'] != version:
        if commit:
            print(f"renaming version {editable['attributes']['versionString']} -> {version}")
            asc.call('PATCH', f"/v1/appStoreVersions/{editable['id']}", {'data': {
                'type': 'appStoreVersions', 'id': editable['id'], 'attributes': {'versionString': version}}})
        else:
            print(f"  would rename version {editable['attributes']['versionString']} -> {version}")
    return editable


def write_whats_new(asc, version_id, notes):
    localizations = asc.get(f'/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations?limit=50')['data']
    for loc in localizations:
        locale = loc['attributes']['locale']
        text, source = _xcode.whats_new_for(locale, notes)
        print(f"  What's New {locale} ({source})")
        asc.call('PATCH', f"/v1/appStoreVersionLocalizations/{loc['id']}", {'data': {
            'type': 'appStoreVersionLocalizations', 'id': loc['id'], 'attributes': {'whatsNew': text}}})


def submit(asc, app_id, version_id):
    open_submission = next((s for s in asc.get(f'/v1/reviewSubmissions?filter[app]={app_id}&filter[platform]=IOS'
                                               '&filter[state]=READY_FOR_REVIEW&limit=5')['data']), None)
    submission = open_submission or asc.call('POST', '/v1/reviewSubmissions', {'data': {
        'type': 'reviewSubmissions', 'attributes': {'platform': 'IOS'},
        'relationships': {'app': {'data': {'type': 'apps', 'id': app_id}}}}})['data']
    items = asc.get(f"/v1/reviewSubmissions/{submission['id']}/items?limit=20")['data']
    if not items:
        asc.call('POST', '/v1/reviewSubmissionItems', {'data': {'type': 'reviewSubmissionItems', 'relationships': {
            'reviewSubmission': {'data': {'type': 'reviewSubmissions', 'id': submission['id']}},
            'appStoreVersion': {'data': {'type': 'appStoreVersions', 'id': version_id}}}}})
    asc.call('PATCH', f"/v1/reviewSubmissions/{submission['id']}", {'data': {
        'type': 'reviewSubmissions', 'id': submission['id'], 'attributes': {'submitted': True}}})
    state = asc.get(f"/v1/reviewSubmissions/{submission['id']}?fields[reviewSubmissions]=state"
                    )['data']['attributes']['state']
    print(f"SUBMITTED for review: submission {submission['id']} is {state}")


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--commit', action='store_true', help='actually build, upload and submit (default: dry run)')
    p.add_argument('--archive', help='upload this existing .xcarchive instead of archiving again')
    p.add_argument('--replace-in-review', action='store_true', help='cancel a version already in review and ship this build')
    p.add_argument('--skip-upload', action='store_true', help='the archive was already uploaded; only wait, attach and submit')
    p.add_argument('--no-submit', action='store_true', help="stop after attaching the build and What's New")
    where = p.add_argument_group('project (discovered when omitted)')
    where.add_argument('--repo', help='repository root (default: git toplevel of the current directory)')
    # Not --project: the cpm dispatcher takes --project as the credentials project.
    where.add_argument('--xcodeproj', help='.xcodeproj, relative to --repo; also where MARKETING_VERSION is read')
    where.add_argument('--workspace', help='.xcworkspace to archive through, relative to --repo')
    where.add_argument('--scheme', help='scheme to archive')
    where.add_argument('--bundle-id', help='app bundle id (default: ASC_BUNDLE_ID credential)')
    where.add_argument('--team-id', help="team for export signing (default: the app target's DEVELOPMENT_TEAM)")
    where.add_argument('--notes-dir', help="What's New root holding <version>/<locale>.txt (default: <repo>/release-notes)")
    where.add_argument('--build-dir', help='derived data, archives and logs (default: <tmp>/cpm-appstore/<scheme>)')
    where.add_argument('--no-em-dash', action='store_true', help="refuse What's New text containing an em dash")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    import _asc

    root = _xcode.repo_root(args.repo)
    bundle_id = _asc.resolve_bundle_id(args.bundle_id)
    asc = _asc.ASC()
    xcode = Xcode(args, root, bundle_id)
    version = xcode.version
    notes = _xcode.release_notes(os.path.join(args.notes_dir or os.path.join(root, 'release-notes'), version),
                                 forbid_em_dash=args.no_em_dash)
    app_id, app_name = asc.app(bundle_id)

    if args.archive:
        archived_version, build = archive_identity(args.archive)
        if archived_version != version:
            die(f'{args.archive} is {archived_version}, the project says {version}')
    else:
        build = str(asc.next_build_number(app_id))
    print(f"{app_name} iOS {version} ({build})  app {app_id}  notes: {', '.join(sorted(notes))}")
    print(f'  {xcode.describe()}')

    if not args.commit:
        version_to_ship(asc, app_id, version, args.replace_in_review, commit=False)
        print('\nDRY RUN. Nothing archived, uploaded or submitted. Re-run with --commit.')
        return

    path = args.archive or archive(xcode, asc, version, build)
    uploaded = asc.find_build(app_id, version, build)
    if uploaded or args.skip_upload:
        print(f'build {build} is already on App Store Connect; not uploading it again')
    else:
        upload(xcode, asc, path)
    build_id = wait_for_build(asc, app_id, version, build)

    target = version_to_ship(asc, app_id, version, args.replace_in_review, commit=True)
    print(f'attaching build {build} to version {version}')
    asc.call('PATCH', f"/v1/appStoreVersions/{target['id']}/relationships/build",
             {'data': {'type': 'builds', 'id': build_id}})
    write_whats_new(asc, target['id'], notes)
    if args.no_submit:
        print('Stopped before submitting (--no-submit). Submit in App Store Connect when ready.')
        return
    submit(asc, app_id, target['id'])


if __name__ == '__main__':
    sys.exit(main())
