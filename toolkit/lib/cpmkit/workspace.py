"""Portable repository registry for real independent Git checkouts."""
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Repo:
    name: str
    path: str
    url: str
    branch: str


def find_root(start=None):
    here = Path(start or os.getcwd()).resolve()
    for parent in (here, *here.parents):
        if (parent / '.cpm-repos').is_file():
            return parent
    raise ValueError('No .cpm-repos found. Run from the workspace or pass --root.')


def read_repos(root):
    root = Path(root).resolve()
    repos = []
    ids, paths = set(), set()
    for number, line in enumerate((root / '.cpm-repos').read_text().splitlines(), 1):
        if not line.strip() or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 4 or not all(fields):
            raise ValueError(f'.cpm-repos line {number}: expected ID, path, URL and branch separated by tabs')
        repo = Repo(*fields)
        path = Path(repo.path)
        if not re.fullmatch(r'[A-Za-z0-9._-]+', repo.name) or repo.name in {'.', '..'}:
            raise ValueError(f'Invalid project ID: {repo.name}')
        if path.is_absolute() or '..' in path.parts or repo.path in {'.', ''} or '.git' in path.parts:
            raise ValueError(f'Unsafe repository path: {repo.path}')
        target = root / path
        if root not in target.resolve().parents or any(p.is_symlink() for p in (target, *list(target.parents)[:len(path.parts)-1])):
            raise ValueError(f'Repository path must be a real folder inside the workspace: {repo.path}')
        if repo.name in ids or repo.path in paths:
            raise ValueError(f'Duplicate project ID or path: {repo.name}')
        if any(path in Path(other).parents or Path(other) in path.parents for other in paths):
            raise ValueError(f'Repositories may not contain each other: {repo.path}')
        if repo.url.startswith('-') or repo.branch.startswith('-'):
            raise ValueError('Clone URL and branch must not be command options')
        if re.match(r'https?://[^/]*@', repo.url):
            raise ValueError('Do not put GitHub credentials in the repository registry')
        ids.add(repo.name); paths.add(repo.path); repos.append(repo)
    return repos


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True,
                          env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})


def remote_identity(url):
    return re.sub(r'\.git$', '', re.sub(r'^(?:git@|https?://)([^/:]+)[:/]', r'\1/', url)).rstrip('/')


def state(root, repo):
    target = Path(root) / repo.path
    result = {'name': repo.name, 'path': repo.path, 'state': 'missing'}
    if not target.exists():
        return result
    top = git(target, 'rev-parse', '--show-toplevel')
    if target.is_symlink() or top.returncode or Path(top.stdout.strip()).resolve() != target.resolve():
        return {**result, 'state': 'conflict'}
    remote = git(target, 'remote', 'get-url', 'origin')
    if remote.returncode or remote_identity(remote.stdout.strip()) != remote_identity(repo.url):
        return {**result, 'state': 'wrong-origin'}
    return {**result, 'state': 'ready', 'branch': git(target, 'branch', '--show-current').stdout.strip(),
            'head': git(target, 'rev-parse', 'HEAD').stdout.strip(),
            'dirty': len(git(target, 'status', '--porcelain').stdout.splitlines())}


def clone_missing(root, repos, commit=False):
    states = [state(root, repo) for repo in repos]
    conflicts = [s for s in states if s['state'] not in {'ready', 'missing'}]
    if conflicts:
        raise ValueError('Refusing to overwrite existing paths: ' + ', '.join(s['path'] for s in conflicts))
    for repo, current in zip(repos, states):
        if current['state'] == 'ready':
            continue  # No fetch, checkout, reset or pull of existing work.
        if commit:
            target = Path(root) / repo.path
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'clone', '--branch', repo.branch, '--', repo.url, str(target)], check=True)
    return [state(root, repo) for repo in repos] if commit else states


def resolve_repo(value, start=None):
    """Resolve a registry ID or real repo path, retaining its stable memory ID."""
    base = Path(start or os.getcwd()).resolve()
    path = Path(value).expanduser()
    if not path.is_absolute(): path = base / path
    path = path.resolve()
    try:
        root = find_root(base)
    except ValueError:
        return path, path.name
    for repo in read_repos(root):
        target = root / repo.path
        if repo.name == value or target.resolve() == path:
            return target, repo.name
    return path, path.name
