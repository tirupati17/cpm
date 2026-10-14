import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLKIT / 'lib'))
from cpmkit import workspace


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cpm-workspace-')
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'workspace with spaces'
        self.root.mkdir()
        self.remote = self.base / 'origin'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.remote)], check=True)
        subprocess.run(['git', '-C', str(self.remote), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture'], check=True)
        self.manifest('app\trepos/app folder\t' + str(self.remote) + '\tmain\n')

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self, text):
        (self.root / '.cpm-repos').write_text(text)

    def clone(self):
        return workspace.clone_missing(self.root, workspace.read_repos(self.root), True)

    def bash(self, command, cwd=None):
        return subprocess.run(['bash', '-eu', '-c', command], cwd=cwd or self.root, capture_output=True, text=True, check=True)

    def test_clone_is_dry_by_default_and_preserves_existing_dirty_work(self):
        repos = workspace.read_repos(self.root)
        self.assertEqual(workspace.clone_missing(self.root, repos)[0]['state'], 'missing')
        self.assertFalse((self.root / 'repos').exists())
        self.assertEqual(self.clone()[0]['state'], 'ready')
        repo = self.root / repos[0].path
        (repo / 'unfinished.txt').write_text('keep me')
        before = workspace.state(self.root, repos[0])
        self.assertEqual(workspace.clone_missing(self.root, repos, True)[0], before)
        self.assertEqual((repo / 'unfinished.txt').read_text(), 'keep me')
        self.assertFalse(repo.is_symlink())

    def test_stable_ids_resolve_from_root_and_nested_working_directories(self):
        self.clone()
        repo = self.root / 'repos/app folder'
        self.assertEqual(workspace.resolve_repo('app', self.root), (repo, 'app'))
        self.assertEqual(workspace.resolve_repo(str(repo), self.root), (repo, 'app'))
        self.assertEqual(workspace.resolve_repo('app', repo), (repo, 'app'))

    def test_refuses_conflicts_before_cloning_any_repo(self):
        (self.root / 'occupied').mkdir()
        self.manifest('new\tnew\t' + str(self.remote) + '\tmain\noccupied\toccupied\t' + str(self.remote) + '\tmain\n')
        with self.assertRaises(ValueError): workspace.clone_missing(self.root, workspace.read_repos(self.root), True)
        self.assertFalse((self.root / 'new').exists())

    def test_registry_rejects_traversal_duplicates_nested_repos_and_symlinks(self):
        for rows in ['a\t../escape', 'a\t/escape', 'a\t.', 'a\tone\n' + 'a\ttwo', 'a\tone\n' + 'b\tone/child']:
            self.manifest(''.join(row + '\t' + str(self.remote) + '\tmain\n' for row in rows.splitlines()))
            with self.subTest(rows=rows), self.assertRaises(ValueError): workspace.read_repos(self.root)
        (self.root / 'outside').symlink_to(self.remote, target_is_directory=True)
        self.manifest('a\toutside\t' + str(self.remote) + '\tmain\n')
        with self.assertRaises(ValueError): workspace.read_repos(self.root)

    def test_flat_and_grouped_detection_and_hooks_survive_workspace_move(self):
        self.clone()
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ['detect-projects.sh', 'install-hooks.sh', 'log-commit.sh']:
            shutil.copy2(TOOLKIT.parent / 'scripts' / name, scripts / name)
        for name in ['summarize.sh', 'generate-truth.sh']:
            (scripts / name).write_text('#!/usr/bin/env bash\nexit 0\n'); (scripts / name).chmod(0o755)
        result = self.bash('source scripts/detect-projects.sh; printf "%s\\n" "${CPM_PROJECTS[@]}"; cpm_repo_dir app')
        self.assertEqual(result.stdout.splitlines(), ['app', str(self.root / 'repos/app folder')])
        # A child may itself contain CPM source; its hook still belongs to the outer workspace.
        child_scripts = self.root / 'repos/app folder/scripts'
        child_scripts.mkdir()
        (child_scripts / 'detect-projects.sh').write_text('# child CPM source, not the workspace root\n')
        hooks = self.root / 'repos/app folder/.git/hooks'
        (hooks / 'post-commit').write_text('#!/bin/bash\nprintf custom > custom-hook-ran\n')
        self.bash('bash scripts/install-hooks.sh')
        self.bash('bash scripts/install-hooks.sh')
        self.assertEqual((hooks / 'post-commit').read_text().count('# --- [cpm]'), 1)
        old = self.root
        self.root = self.base / 'renamed workspace'
        old.rename(self.root)
        repo = self.root / 'repos/app folder'
        self.bash('git -c user.name=Fixture -c user.email=fixture@example.invalid commit --allow-empty -m after-move', repo)
        self.assertEqual((repo / 'custom-hook-ran').read_text(), 'custom')
        self.assertTrue(list((self.root / 'memory/changelogs/app').glob('*.md')))
        self.assertNotIn(str(old), (repo / '.git/hooks/post-commit').read_text())
        (self.root / '.cpm-repos').unlink()
        self.assertIn('app-folder', self.bash('source scripts/detect-projects.sh; printf "%s\\n" "${CPM_PROJECTS[@]}"').stdout)

    def test_skill_sync_materializes_owned_links_and_preserves_custom_skills(self):
        scripts = self.root / 'scripts'; scripts.mkdir()
        shutil.copy2(TOOLKIT.parent / 'scripts/sync-skills.py', scripts / 'sync-skills.py')
        source = self.root / 'skills/service'; source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('---\nname: service\ndescription: fixture\n---\n')
        dest = self.root / '.claude/skills'; dest.mkdir(parents=True)
        (dest / 'service').symlink_to('../../skills/service', target_is_directory=True)
        custom = dest / 'custom'; custom.mkdir(); (custom / 'SKILL.md').write_text('keep me')
        self.bash('python3 scripts/sync-skills.py')
        self.assertFalse((dest / 'service').is_symlink())
        self.assertEqual((dest / 'service/SKILL.md').read_text(), (source / 'SKILL.md').read_text())
        self.assertEqual((custom / 'SKILL.md').read_text(), 'keep me')
        (dest / 'service/stale.txt').write_text('stale')
        self.bash('python3 scripts/sync-skills.py')
        self.assertFalse((dest / 'service/stale.txt').exists())


if __name__ == '__main__': unittest.main()
