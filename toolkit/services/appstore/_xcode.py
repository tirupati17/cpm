"""Local Xcode project facts for the appstore commands (private module, stdlib only).

Everything here reads files and answers a question; nothing builds, signs or
talks to the network, so all of it is unit-tested.
"""
import glob
import os
import re
import subprocess
import sys

PROG = os.path.basename(sys.argv[0]).removesuffix('.py') or 'appstore'
NOTES_LIMIT = 4000  # App Store Connect's cap on What's New, per locale
EM_DASH = '—'


def die(message):
    sys.exit(f'{PROG}: {message}')


def repo_root(explicit=None):
    """--repo, else the git toplevel of the current directory, else the directory itself."""
    if explicit:
        path = os.path.abspath(os.path.expanduser(explicit))
        if not os.path.isdir(path):
            die(f'--repo {explicit} is not a directory')
        return path
    try:
        return subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return os.getcwd()


def _one(candidates, kind, root, flag):
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    names = ', '.join(os.path.basename(c) for c in candidates)
    die(f'{root} has several {kind} ({names}); pick one with {flag}')


def find_container(root, project=None, workspace=None):
    """('workspace'|'project', path). A workspace wins when there is exactly one,
    because a CocoaPods or multi-project setup only builds through it."""
    if workspace:
        return 'workspace', os.path.join(root, workspace)
    if project:
        return 'project', os.path.join(root, project)
    workspaces = sorted(glob.glob(os.path.join(root, '*.xcworkspace')))
    found = _one(workspaces, 'workspaces', root, '--workspace')
    if found:
        return 'workspace', found
    found = _one(sorted(glob.glob(os.path.join(root, '*.xcodeproj'))), 'projects', root, '--xcodeproj')
    if found:
        return 'project', found
    die(f'no .xcodeproj or .xcworkspace in {root}; pass --xcodeproj or --workspace (or --repo)')


def pbxproj_path(root, project=None):
    """The project.pbxproj to read settings from. Needs a project, not a workspace."""
    if project:
        path = os.path.join(root, project)
    else:
        path = _one(sorted(glob.glob(os.path.join(root, '*.xcodeproj'))), 'projects', root, '--xcodeproj')
        if not path:
            die(f'no .xcodeproj in {root}; pass --xcodeproj')
    pbx = os.path.join(path, 'project.pbxproj') if not path.endswith('.pbxproj') else path
    if not os.path.isfile(pbx):
        die(f'cannot read {pbx}')
    return pbx


def shared_schemes(*containers):
    found = set()
    for container in containers:
        found.update(os.path.basename(p)[:-len('.xcscheme')]
                     for p in glob.glob(os.path.join(container, 'xcshareddata', 'xcschemes', '*.xcscheme')))
    return sorted(found)


def pick_scheme(containers, explicit=None):
    """--scheme, else a shared scheme named after a container, else the only shared one."""
    if explicit:
        return explicit
    if isinstance(containers, str):
        containers = [containers]
    schemes = shared_schemes(*containers)
    for container in containers:
        stem = os.path.splitext(os.path.basename(container))[0]
        if stem in schemes:
            return stem
    if len(schemes) == 1:
        return schemes[0]
    listed = ', '.join(schemes) or 'none shared'
    die(f'cannot tell which scheme to archive ({listed}); pass --scheme')


def target_settings(pbxproj_text, bundle_id):
    """Build-settings blocks of the target whose bundle id is exactly `bundle_id`.

    Matching on the trailing semicolon matters: without it `com.example.App`
    also matches `com.example.App.Widget`, whose version is the wrong one and is
    exactly the value the release overwrites.
    """
    needle = re.compile(r'PRODUCT_BUNDLE_IDENTIFIER = "?' + re.escape(bundle_id) + r'"?;')
    return [block for block in re.findall(r'buildSettings = \{(.*?)\};\n', pbxproj_text, re.S)
            if needle.search(block)]


def _setting(blocks, name):
    for block in blocks:
        found = re.search(rf'\b{name} = ([^;]+);', block)
        if found:
            return found.group(1).strip().strip('"')
    return None


def marketing_version(pbxproj_text, bundle_id):
    """The app target's MARKETING_VERSION.

    Every embedded target is archived with this value, because projects drift:
    an app at 1.0.96 can carry a widget at 1.0.7 and a watch app at 1.0.1, and
    Apple rejects an upload during processing when an embedded extension's
    version differs from the app containing it. Read from the project rather
    than hardcoded, so bumping it in Xcode stays the one place it is done.
    """
    return _setting(target_settings(pbxproj_text, bundle_id), 'MARKETING_VERSION')


def development_team(pbxproj_text, bundle_id):
    return _setting(target_settings(pbxproj_text, bundle_id), 'DEVELOPMENT_TEAM')


def release_notes(folder, forbid_em_dash=False):
    """{locale: text} from <folder>/<locale>.txt. en-US is required: it is the
    fallback for every store locale without its own file."""
    notes = {}
    for path in sorted(glob.glob(os.path.join(folder, '*.txt'))):
        with open(path, encoding='utf-8') as handle:
            text = handle.read().strip()
        if not text:
            die(f'{path} is empty')
        if len(text) > NOTES_LIMIT:
            die(f"{path} is over App Store Connect's {NOTES_LIMIT} characters")
        if forbid_em_dash and EM_DASH in text:
            die(f'{path} uses an em dash; the house style forbids them in user-facing copy')
        notes[os.path.basename(path)[:-4]] = text
    if 'en-US' not in notes:
        die(f'write {folder}/en-US.txt first (the fallback for every other locale)')
    return notes


def whats_new_for(locale, notes):
    """(text, source) for a store locale: exact file, then its language, then en-US."""
    if locale in notes:
        return notes[locale], locale
    language = locale.split('-')[0]
    if language in notes:
        return notes[language], language
    return notes['en-US'], 'en-US fallback'


def upload_was_duplicate(log_text):
    """A build still being processed is invisible to the builds API, so a re-run
    can upload it twice. Apple's rejection of the duplicate means the first
    upload landed; the caller carries on to the processing wait."""
    lowered = log_text.lower()
    return any(marker in lowered for marker in ('redundant', 'already been uploaded', 'has already been used'))
