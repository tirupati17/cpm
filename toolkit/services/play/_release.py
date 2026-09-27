"""Build and check a Play release payload. Pure logic, no network and no secrets."""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

TRACKS = ('internal', 'alpha', 'beta', 'production')
NOTES_LIMIT = 500


def repo_root(explicit=None):
    """--repo, else the git toplevel of the current directory, else the current directory."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True)
        return Path(top.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd()


def find_gradle(root, explicit=None):
    """The module build file that carries versionName/versionCode."""
    if explicit:
        path = Path(explicit).expanduser()
        path = path if path.is_absolute() else Path.cwd() / path
        if not path.is_file():
            raise SystemExit(f'No build file at {path}.')
        return path
    for name in ('app/build.gradle.kts', 'app/build.gradle'):
        if (Path(root) / name).is_file():
            return Path(root) / name
    raise SystemExit(f'No app/build.gradle(.kts) under {root}. Pass --gradle <module build file>.')


def read_version(text):
    """(versionName, versionCode) from a Kotlin or Groovy Gradle build file.

    Reading them from the build config, rather than taking them as arguments,
    is what makes the thing published always the thing configured.
    """
    name = re.search(r'versionName\s*=?\s*["\']([\w.+-]+)["\']', text)
    code = re.search(r'versionCode\s*=?\s*(\d+)', text)
    if not name or not code:
        raise SystemExit('The build file has no literal versionName and versionCode. '
                         'Computed versions are not supported; pass the literal values in the file.')
    return name.group(1), int(code.group(1))


def load_notes(directory):
    """Every <language>.txt in the folder, as Play's releaseNotes list.

    One file per language, named for the Play language code (en-US.txt, hi-IN.txt).
    Play rejects a release note over 500 characters, so that is checked here rather
    than discovered halfway through an edit.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise SystemExit(f'No release notes at {directory}. Write en-US.txt there first.')
    notes = []
    for file in sorted(directory.glob('*.txt')):
        text = file.read_text(encoding='utf-8').strip()
        if not text:
            raise SystemExit(f'{file.name} is empty. Release notes are shown to users.')
        if len(text) > NOTES_LIMIT:
            raise SystemExit(f'{file.name} is {len(text)} characters; Play allows {NOTES_LIMIT}.')
        notes.append({'language': file.stem, 'text': text})
    if not notes:
        raise SystemExit(f'No <language>.txt files in {directory}.')
    return notes


def release_body(track, version_code, rollout, notes, version_name=None):
    """The tracks().update body.

    A rollout below 100 is 'inProgress' with a userFraction; only a full rollout is
    'completed'. Play rejects userFraction on a completed release, which is the
    usual way a staged rollout silently becomes a full one.
    """
    if track not in TRACKS:
        raise SystemExit(f'Unknown track {track!r}. One of: {", ".join(TRACKS)}')
    if not 0 < rollout <= 100:
        raise SystemExit(f'Rollout must be above 0 and at most 100, got {rollout}.')
    release = {'versionCodes': [str(version_code)], 'releaseNotes': notes}
    if version_name:
        release['name'] = version_name
    if rollout == 100:
        release['status'] = 'completed'
    else:
        release['status'] = 'inProgress'
        release['userFraction'] = round(rollout / 100, 4)
    return {'track': track, 'releases': [release]}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def stage_artifacts(output, version_name, version_code, aab, apk=None, basename=None, extra=None):
    """Copy the built bundle (and APK) into output/ and write release.json.

    The manifest records each file's size and sha256 at staging time, which is
    what lets publish refuse a leftover from an earlier build.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {'versionName': version_name, 'versionCode': version_code, **(extra or {}), 'files': {}}
    for source in filter(None, (apk, aab)):
        source = Path(source)
        if not source.is_file():
            raise SystemExit(f'Missing build output: {source}')
        name = f'{basename or "app"}-{version_name}{source.suffix}'
        dest = output / name
        shutil.copy2(source, dest)
        manifest['files'][source.suffix[1:]] = {
            'filename': name, 'bytes': dest.stat().st_size, 'sha256': _sha256(dest)}
    (output / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def verify_artifacts(artifact_dir, version_name, version_code):
    """Confirm the staged AAB is this build and not a leftover from an earlier one.

    Artifacts live under artifacts/<version>/ and survive a failed build, so a
    stale file will happily upload and look correct in every log. The manifest
    records the hash at staging time; re-checking it here is what makes the
    difference visible.
    """
    artifact_dir = Path(artifact_dir)
    manifest_path = artifact_dir / 'release.json'
    if not manifest_path.is_file():
        raise SystemExit(f'No release.json in {artifact_dir}. Build and stage the release first '
                         '(`cpm play stage`, or your own build script).')
    manifest = json.loads(manifest_path.read_text())
    if manifest['versionName'] != version_name or manifest['versionCode'] != version_code:
        raise SystemExit(
            f"Staged artifacts are {manifest['versionName']} ({manifest['versionCode']}) but the "
            f'build config says {version_name} ({version_code}). Rebuild before publishing.')
    aab = artifact_dir / manifest['files']['aab']['filename']
    if not aab.is_file():
        raise SystemExit(f'Missing {aab.name}.')
    if _sha256(aab) != manifest['files']['aab']['sha256']:
        raise SystemExit(f'{aab.name} does not match release.json. Rebuild before publishing.')
    if aab.stat().st_size != manifest['files']['aab']['bytes']:
        raise SystemExit(f'{aab.name} is the wrong size. Rebuild before publishing.')
    return aab, manifest
