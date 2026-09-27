"""`cpm creds`: see, set and use a project's stored credentials.

    cpm creds list [service]           what is stored (secrets masked) and what is missing
    cpm creds setup <service>...       ask for every missing credential those services need
    cpm creds set NAME [VALUE]         store one; prompts (hidden) when VALUE is omitted
    cpm creds unset NAME               forget one
    cpm creds import-env FILE          copy known names from a .env file (values never printed)
    cpm creds exec <service> -- CMD    run CMD with that service's credentials in its environment
    cpm creds where                    the folder holding this project's credentials

All take --project <name>; without it the project is resolved from CPM_PROJECT,
a .cpm-project file, or the CPM workspace name.
"""
import os
import sys
from pathlib import Path

from cpmkit import creds


def _list(args):
    project = creds.project_name()
    stored = creds.load()
    services = args or list(creds.SERVICES)
    print(f'project {project}   ({creds.project_dir()})')
    for service in services:
        if service not in creds.SERVICES:
            raise SystemExit(f'Unknown service {service!r}.')
        print(f'\n{service}')
        for need in creds.SERVICES[service]:
            value = os.environ.get(need.name) or stored.get(need.name, '')
            source = 'env ' if os.environ.get(need.name) else ''
            state = '✓' if value else ('·' if need.optional else '✗')
            print(f'  {state} {need.name:<30} {source}{creds.mask(need, value)}')
    extra = sorted(set(stored) - set(creds.NEEDS))
    if extra and not args:
        print('\nother')
        for name in extra:
            print(f'  ✓ {name:<30} {creds.mask(None, stored[name])}')


def _setup(args):
    if not args:
        raise SystemExit('Which services? One or more of: ' + ', '.join(creds.SERVICES))
    if not creds.interactive():
        raise SystemExit('setup asks questions; run it in a terminal.')
    for service in args:
        creds.require(service)
    _list(args)


def _set(args):
    if not args:
        raise SystemExit('cpm creds set NAME [VALUE]')
    name = args[0]
    need = creds.NEEDS.get(name)
    if len(args) > 1:
        value = creds.keep_file(name, args[1]) if need and need.file else args[1]
        creds.save(name, value)
    elif not creds.ask(name):
        raise SystemExit('Nothing stored.')
    print(f'stored {name} for {creds.project_name()}')


def _unset(args):
    for name in args:
        print(('removed ' if creds.unset(name) else 'not stored: ') + name)


def _import_env(args):
    if not args:
        raise SystemExit('cpm creds import-env FILE')
    path = Path(args[0]).expanduser()
    count = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:]
        if '=' not in line or line.startswith('#'):
            continue
        name, value = line.split('=', 1)
        name, value = name.strip(), value.strip().strip('"\'')
        if name in creds.NEEDS and value:
            if creds.NEEDS[name].file:
                value = creds.keep_file(name, (path.parent / value) if not Path(value).is_absolute() else value)
            creds.save(name, value)
            print(f'  imported {name}')
            count += 1
    print(f'{count} imported into {creds.project_name()}')


def _exec(args):
    if '--' not in args:
        raise SystemExit('cpm creds exec <service>... -- COMMAND [ARGS]')
    at = args.index('--')
    services, command = args[:at], args[at + 1:]
    if not command:
        raise SystemExit('Nothing to run after --.')
    env = dict(os.environ)
    for service in services:
        env.update({k: v for k, v in creds.require(service).items() if v})
    os.execvpe(command[0], command, env)


def main(argv):
    for i, arg in enumerate(argv):
        if arg.startswith('--project='):
            argv[i:i + 1] = ['--project', arg.split('=', 1)[1]]
            break
    if '--project' in argv:
        at = argv.index('--project')
        os.environ['CPM_PROJECT'] = argv[at + 1]
        del argv[at:at + 2]
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    command, rest = argv[0], argv[1:]
    actions = {'list': _list, 'setup': _setup, 'set': _set, 'unset': _unset,
               'import-env': _import_env, 'exec': _exec,
               'where': lambda _: print(creds.project_dir())}
    if command not in actions:
        raise SystemExit(f'Unknown: {command}. Run `cpm creds -h`.')
    actions[command](rest)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
