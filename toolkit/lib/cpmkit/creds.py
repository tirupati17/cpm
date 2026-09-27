"""Credentials for the toolkit: asked for once, stored per project, never in git.

Every helper script asks for what it needs by name:

    from cpmkit import creds
    package = creds.get('PLAY_PACKAGE')
    key_file = creds.get('PLAY_SERVICE_ACCOUNT_JSON')

A name resolves, in order, from:

  1. the environment (so CI and one-off overrides need no files at all),
  2. ~/.config/cpm/<project>/credentials.env,
  3. a prompt, when a person is at the terminal. The answer is saved to (2).

Key files (.p8, service account .json) are copied into
~/.config/cpm/<project>/keys/ and the stored value is that copy's path, so a
fork of the workspace never carries a secret and moving the workspace breaks
nothing. Directories are 0700 and files 0600. Secret values are never printed.

The project is the one thing that separates two apps' credentials. It comes
from --project, then CPM_PROJECT, then a `.cpm-project` file found walking up
from the current directory (one line: the name), then the name of the CPM
workspace (the directory holding `.cpm-initialized`).
"""
import getpass
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Need:
    name: str
    label: str
    secret: bool = True
    file: bool = False
    optional: bool = False
    help: str = ''


# Every credential any helper asks for. `cpm creds setup <service>` walks the
# list for that service; scripts may still ask for a single name on its own.
SERVICES = {
    'play': [
        Need('PLAY_PACKAGE', 'Android package name (applicationId)', secret=False),
        Need('PLAY_SERVICE_ACCOUNT_JSON', 'Google Play service account key (.json)', file=True,
             help='GCP console > IAM > Service accounts > Keys > Add key > JSON. Then invite that '
                  'account in Play Console > Users and permissions with release rights for the app.'),
    ],
    'appstore': [
        Need('ASC_BUNDLE_ID', 'iOS bundle identifier', secret=False),
        Need('ASC_KEY_ID', 'App Store Connect API key ID', secret=False,
             help='App Store Connect > Users and Access > Integrations > Team Keys. Admin or App Manager role.'),
        Need('ASC_ISSUER_ID', 'App Store Connect issuer ID', secret=False,
             help='Shown above the key list on the same page.'),
        Need('ASC_KEY_PATH', 'App Store Connect private key (AuthKey_<id>.p8)', file=True,
             help='Downloadable once, when the key is created.'),
        Need('ASC_TEAM_ID', 'Apple Developer team ID (10 characters)', secret=False, optional=True,
             help="Only asked when the app target has no DEVELOPMENT_TEAM. developer.apple.com > Account > Membership details."),
    ],
    'revenuecat': [
        Need('REVENUECAT_API_KEY', 'RevenueCat secret API key, v2 (sk_...)',
             help='RevenueCat > Project settings > API keys > + New secret API key (v2). '
                  'Grant only the permissions the task needs.'),
        Need('REVENUECAT_PROJECT_ID', 'RevenueCat project ID (proj...)', secret=False,
             help='The id in the dashboard URL: app.revenuecat.com/projects/<id>/...'),
        Need('REVENUECAT_V1_API_KEY', 'RevenueCat secret API key, v1 (legacy sk_...)', optional=True,
             help='Only for the v1 calls v2 has no equal (a lifetime promotional grant). Same page, '
                  'a legacy v1 secret key. Leave empty to try REVENUECAT_API_KEY on v1 too.'),
    ],
    'onesignal': [
        Need('ONESIGNAL_APP_ID', 'OneSignal app ID', secret=False,
             help='OneSignal > Settings > Keys & IDs.'),
        Need('ONESIGNAL_REST_API_KEY', 'OneSignal REST API key',
             help='Same page. Newer keys start with os_v2_app_.'),
        Need('ONESIGNAL_ORG_API_KEY', 'OneSignal organization API key (User Auth key)', optional=True,
             help='Organization > Keys & IDs. Only `cpm onesignal app` needs it: reading an app\'s '
                  'settings and subscriber counts is an organization-level call.'),
    ],
    'amplitude': [
        Need('AMPLITUDE_API_KEY', 'Amplitude project API key', secret=False,
             help='Amplitude > Settings > Projects > <project> > General.'),
        Need('AMPLITUDE_SECRET_KEY', 'Amplitude project secret key',
             help='Same page. Used for the Dashboard REST and Export APIs.'),
        Need('AMPLITUDE_MANAGEMENT_KEY', 'Amplitude Experiment management API key', optional=True,
             help='Experiment > Management API. Needed only to list or change feature flags.'),
        Need('AMPLITUDE_REGION', 'Amplitude data region (us or eu)', secret=False, optional=True),
    ],
    'gcp': [
        Need('GCP_PROJECT_ID', 'Google Cloud project ID', secret=False),
        Need('GCP_SERVICE_ACCOUNT_JSON', 'Google Cloud service account key (.json)', file=True,
             help='IAM > Service accounts > Keys > Add key > JSON. Give it only the roles the task needs.'),
    ],
    'googleads': [
        Need('GOOGLE_ADS_DEVELOPER_TOKEN', 'Google Ads API developer token',
             help='Google Ads (manager account) > Tools > API Center. Basic access is enough for your own accounts.'),
        Need('GOOGLE_ADS_CUSTOMER_ID', 'Google Ads customer ID (digits, no dashes)', secret=False),
        Need('GOOGLE_ADS_LOGIN_CUSTOMER_ID', 'Manager (MCC) customer ID, if you go through one',
             secret=False, optional=True),
        Need('GOOGLE_ADS_CLIENT_ID', 'OAuth client ID (Desktop app)', secret=False,
             help='GCP console > APIs & Services > Credentials > OAuth client ID > Desktop app. '
                  'Enable the Google Ads API on that project first.'),
        Need('GOOGLE_ADS_CLIENT_SECRET', 'OAuth client secret'),
        Need('GOOGLE_ADS_REFRESH_TOKEN', 'OAuth refresh token (scope adwords)',
             help='Run `cpm googleads auth` to mint one in the browser.'),
    ],
}

NEEDS = {need.name: need for needs in SERVICES.values() for need in needs}


def config_home():
    base = os.environ.get('CPM_CONFIG_HOME')
    if base:
        return Path(base).expanduser()
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'cpm'


def _slug(name):
    slug = re.sub(r'[^a-z0-9._-]+', '-', name.strip().lower()).strip('-')
    if not slug:
        raise SystemExit(f'{name!r} is not usable as a project name.')
    return slug


def project_name(explicit=None, start=None):
    if explicit:
        return _slug(explicit)
    if os.environ.get('CPM_PROJECT'):
        return _slug(os.environ['CPM_PROJECT'])
    here = Path(start or os.getcwd()).resolve()
    for directory in (here, *here.parents):
        marker = directory / '.cpm-project'
        if marker.is_file():
            return _slug(marker.read_text().strip().splitlines()[0])
    for directory in (here, *here.parents):
        if (directory / '.cpm-initialized').exists():
            return _slug(directory.name)
    raise SystemExit('Which project are these credentials for? Pass --project <name>, set '
                     'CPM_PROJECT, or put the name in a .cpm-project file at the repo root.')


def project_dir(project=None):
    return config_home() / project_name(project)


def _store(project):
    return project_dir(project) / 'credentials.env'


def load(project=None):
    """Everything saved for the project, as a dict. Missing file means empty."""
    path = _store(project)
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value
    return values


def _private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    if config_home() in path.parents:
        os.chmod(config_home(), 0o700)


def _write(values, project):
    directory = project_dir(project)
    _private_dir(directory)
    body = '# Written by cpm creds. Never commit this file.\n'
    body += ''.join(f'{key}={values[key]}\n' for key in sorted(values))
    tmp = directory / '.credentials.env.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(body)
    os.replace(tmp, _store(project))


def save(name, value, project=None):
    if '\n' in value:
        raise SystemExit(f'{name} cannot contain a newline. Store multi-line keys as a file.')
    values = load(project)
    values[name] = value
    _write(values, project)


def unset(name, project=None):
    values = load(project)
    if values.pop(name, None) is None:
        return False
    _write(values, project)
    return True


def keep_file(name, source, project=None):
    """Copy a key file into the project's private keys/ folder and return the copy."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f'No file at {source}.')
    keys = project_dir(project) / 'keys'
    _private_dir(keys)
    target = keys / source.name
    if source != target:
        shutil.copyfile(source, target)
    os.chmod(target, 0o600)
    return str(target)


def mask(need, value):
    if not value:
        return ''
    if need and (need.file or not need.secret):
        return value
    return value[:4] + '…' + f'({len(value)} chars)' if len(value) > 8 else '•' * len(value)


def interactive():
    return sys.stdin.isatty() and sys.stderr.isatty() and not os.environ.get('CPM_NO_PROMPT')


def ask(name, project=None):
    """Prompt for one credential and save it. Returns the stored value (or '' if skipped)."""
    need = NEEDS.get(name, Need(name, name))
    project = project_name(project)
    print(f'\n[{project}] {need.label}  ({name})', file=sys.stderr)
    if need.help:
        print(f'  {need.help}', file=sys.stderr)
    if need.file:
        answer = input('  path to the file: ').strip().strip('"\'')
        if not answer:
            return ''
        value = keep_file(name, answer, project)
        print(f'  copied to {value}', file=sys.stderr)
    elif need.secret:
        value = getpass.getpass('  value (hidden): ').strip()
    else:
        value = input('  value: ').strip()
    if not value:
        return ''
    save(name, value, project)
    return value


def get(name, project=None, required=True):
    """Resolve a credential by name. See the module docstring for the order."""
    if os.environ.get(name):
        return os.environ[name]
    stored = load(project).get(name)
    if stored:
        need = NEEDS.get(name)
        if need and need.file and not Path(stored).is_file():
            raise SystemExit(f'{name} points at {stored}, which is gone. '
                             f'Run: cpm creds set {name} --project {project_name(project)}')
        return stored
    optional = not required or (name in NEEDS and NEEDS[name].optional)
    if interactive():
        value = ask(name, project)
        if value or optional:
            return value
    if optional:
        return ''
    raise SystemExit(f'Missing {name} for project "{project_name(project)}". '
                     f'Run: cpm creds set {name} --project {project_name(project)}  '
                     f'(or export {name}=...)')


def require(service, project=None):
    """Resolve every non-optional credential a service needs, prompting for the gaps."""
    if service not in SERVICES:
        raise SystemExit(f'Unknown service {service!r}. One of: {", ".join(SERVICES)}')
    return {need.name: get(need.name, project, required=not need.optional) for need in SERVICES[service]}
