import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_hosts


class HostSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'repository'
        self.root.mkdir()
        (self.root / 'README.md').write_text('Synthetic repository', encoding='utf-8')
        for host in ('codex', 'claude-code'):
            self.write(host, 'SKILL.md', f'{host} entry')
            self.write(host, 'references/host.md', f'{host} host instructions')
            self.write(host, 'scripts/example.py', '# common\n')
        self.write('codex', 'agents/openai.yaml', 'codex policy')

    def tearDown(self):
        self.temporary.cleanup()

    def path(self, host, name):
        return self.root / host / 'just-build' / name

    def write(self, host, name, value):
        path = self.path(host, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
        return path

    def test_matching_packages_are_a_noop_even_on_apply(self):
        with patch.object(sync_hosts.os, 'replace') as replace:
            self.assertTrue(sync_hosts.synchronize(self.root)['in_sync'])
            self.assertEqual([], sync_hosts.synchronize(self.root, apply=True)['applied'])
        replace.assert_not_called()

    def test_dry_run_does_not_mutate_and_apply_repairs_shared_files(self):
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        self.write('codex', 'new/nested/reference.md', 'new shared reference')
        result = sync_hosts.synchronize(self.root)
        self.assertEqual(['scripts/example.py'], result['changed'])
        self.assertEqual(['new/nested/reference.md'], result['missing'])
        self.assertFalse(result['in_sync'])
        self.assertEqual('# stale\n', destination.read_text())
        self.assertFalse(self.path('claude-code', 'new/nested/reference.md').exists())
        repaired = sync_hosts.synchronize(self.root, apply=True)
        self.assertTrue(repaired['in_sync'])
        self.assertEqual(['new/nested/reference.md', 'scripts/example.py'], repaired['applied'])
        self.assertEqual(destination.read_bytes(), self.path('codex', 'scripts/example.py').read_bytes())
        self.assertFalse(list(destination.parent.glob('.sync-hosts-*')))

    def test_host_specific_files_are_preserved(self):
        self.write('claude-code', 'agents/openai.yaml', 'local host-specific policy')
        before = {name: self.path('claude-code', name).read_bytes() for name in sync_hosts.HOST_SPECIFIC}
        self.write('codex', 'scripts/example.py', '# updated\n')
        self.assertTrue(sync_hosts.synchronize(self.root, apply=True)['in_sync'])
        self.assertEqual(before, {name: self.path('claude-code', name).read_bytes() for name in before})

    def test_case_renamed_host_specific_files_are_rejected_before_any_write(self):
        self.write('claude-code', 'agents/openai.yaml', 'local host-specific policy')
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        for host in ('codex', 'claude-code'):
            for name in sorted(sync_hosts.HOST_SPECIFIC):
                with self.subTest(host=host, name=name):
                    canonical = self.path(host, name)
                    alias_name = canonical.name.lower() if canonical.name == 'SKILL.md' else canonical.name.upper()
                    alias = canonical.with_name(alias_name)
                    intermediate = canonical.with_name(canonical.name + '.case-rename')
                    # Two renames force the case-only spelling change on both
                    # case-sensitive and case-insensitive filesystems.
                    canonical.rename(intermediate)
                    intermediate.rename(alias)
                    before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                              for path in self.root.rglob('*') if path.is_file()}
                    try:
                        with patch.object(sync_hosts.os, 'replace') as replace:
                            # Case-sensitive filesystems may reject a missing
                            # canonical marker before scanning the alias itself.
                            with self.assertRaisesRegex(ValueError, 'Noncanonical host-specific|Missing required path'):
                                sync_hosts.synchronize(self.root, apply=True)
                            replace.assert_not_called()
                        after = {path.relative_to(self.root).as_posix(): path.read_bytes()
                                 for path in self.root.rglob('*') if path.is_file()}
                        self.assertEqual(before, after)
                        self.assertEqual('# stale\n', destination.read_text())
                    finally:
                        alias.rename(intermediate)
                        intermediate.rename(canonical)

    def test_unexpected_destination_file_remains_and_cli_reports_failure(self):
        orphan = self.write('claude-code', 'references/orphan.md', 'keep me')
        self.write('codex', 'scripts/example.py', '# updated\n')
        result = sync_hosts.synchronize(self.root, apply=True)
        self.assertFalse(result['in_sync'])
        self.assertEqual(['references/orphan.md'], result['unexpected'])
        self.assertEqual('keep me', orphan.read_text())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(1, sync_hosts.main(['--root', str(self.root)]))
        self.assertIn('orphan.md', output.getvalue())

    def test_private_input_preflight_never_partially_repairs(self):
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        for name in ('.env', '.env.local', 'secrets.pem', '.just-build/run.json',
                     '.codex/config.toml', 'credentials.json'):
            with self.subTest(name=name):
                private = self.write('codex', name, 'SYNTHETIC_ONLY')
                with self.assertRaisesRegex(ValueError, 'Private|local-state'):
                    sync_hosts.synchronize(self.root, apply=True)
                self.assertEqual('# stale\n', destination.read_text())
                private.unlink()
                if private.parent.name in sync_hosts.PRIVATE_DIRS:
                    private.parent.rmdir()

    def test_cache_files_are_ignored_but_env_example_is_shared(self):
        self.write('codex', '__pycache__/example.cpython-313.pyc', 'synthetic cache')
        self.write('codex', 'scripts/example.pyc', 'synthetic cache')
        self.write('codex', '.env.example', 'EXAMPLE_VALUE=replace-me\n')
        result = sync_hosts.synchronize(self.root, apply=True)
        self.assertTrue(result['in_sync'])
        self.assertTrue(self.path('claude-code', '.env.example').exists())
        self.assertFalse(self.path('claude-code', '__pycache__').exists())

    def test_file_and_total_byte_limits_fail_before_repair(self):
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        with patch.object(sync_hosts, 'MAX_FILE_BYTES', 20):
            self.write('codex', 'large.txt', 'x' * 21)
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                sync_hosts.synchronize(self.root, apply=True)
        self.path('codex', 'large.txt').unlink()
        with patch.object(sync_hosts, 'MAX_TOTAL_BYTES', 30):
            with self.assertRaisesRegex(ValueError, 'file/byte limits'):
                sync_hosts.synchronize(self.root, apply=True)
        self.assertEqual('# stale\n', destination.read_text())

    def test_wrong_root_and_nonregular_destination_fail_before_mutation(self):
        with self.assertRaisesRegex(ValueError, 'Missing required'):
            sync_hosts.synchronize(self.path('codex', ''), apply=True)
        target = self.path('claude-code', 'scripts/example.py')
        target.unlink()
        target.mkdir()
        earlier = self.write('claude-code', 'references/a.md', 'stale')
        self.write('codex', 'references/a.md', 'canonical')
        # A directory cannot be atomically replaced as a shared regular file.
        with self.assertRaises(ValueError):
            sync_hosts.synchronize(self.root, apply=True)
        self.assertTrue(target.is_dir())
        self.assertEqual('stale', earlier.read_text())

    def test_missing_readme_is_rejected_before_any_repair(self):
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        (self.root / 'README.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing required'):
            sync_hosts.synchronize(self.root, apply=True)
        self.assertEqual('# stale\n', destination.read_text())

    def test_nontext_or_private_key_material_is_rejected_before_mutation(self):
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        unwanted = self.path('codex', 'references/unwanted.txt')
        for content in (b'\xff', b'-----BEGIN ' + b'RSA PRIVATE KEY-----\nSYNTHETIC_ONLY'):
            with self.subTest(content=content):
                unwanted.write_bytes(content)
                with self.assertRaises(ValueError):
                    sync_hosts.synchronize(self.root, apply=True)
                self.assertEqual('# stale\n', destination.read_text())

    def test_entry_and_file_count_limits_are_enforced(self):
        for limit in ('MAX_ENTRIES', 'MAX_FILES'):
            with self.subTest(limit=limit), patch.object(sync_hosts, limit, 2):
                with self.assertRaisesRegex(ValueError, 'limit'):
                    sync_hosts.synchronize(self.root, apply=True)

    def test_result_byte_budget_is_checked_before_any_repair(self):
        self.write('codex', 'scripts/example.py', 'x' * 200)
        destination = self.write('claude-code', 'scripts/example.py', 'stale')
        current_bytes = sum(path.stat().st_size for host in ('codex', 'claude-code')
                            for path in (self.root / host / 'just-build').rglob('*') if path.is_file())
        with patch.object(sync_hosts, 'MAX_TOTAL_BYTES', current_bytes + 1):
            with self.assertRaisesRegex(ValueError, 'Sync result'):
                sync_hosts.synchronize(self.root, apply=True)
        self.assertEqual('stale', destination.read_text())

    def test_cross_host_case_aliases_are_rejected_before_repair(self):
        self.write('codex', 'references/Case.md', 'canonical')
        self.write('claude-code', 'references/case.md', 'stale')
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        with self.assertRaisesRegex(ValueError, 'case-colliding'):
            sync_hosts.synchronize(self.root, apply=True)
        self.assertEqual('# stale\n', destination.read_text())

    def test_hard_linked_source_does_not_copy_outside_contents(self):
        outside = Path(self.temporary.name) / 'outside.txt'
        outside.write_text('outside sentinel')
        try:
            self.path('codex', 'references/linked.md').hardlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Local hard-link creation unavailable: {exc}')
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        with self.assertRaisesRegex(ValueError, 'Hard-linked'):
            sync_hosts.synchronize(self.root, apply=True)
        self.assertFalse(self.path('claude-code', 'references/linked.md').exists())
        self.assertEqual('outside sentinel', outside.read_text())
        self.assertEqual('# stale\n', destination.read_text())

    def _symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            if directory and os.name == 'nt':
                result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                        capture_output=True, text=True, timeout=10, check=False)
                if result.returncode == 0:
                    return
            self.skipTest(f'Local symlink creation unavailable: {exc}')

    def test_linked_source_is_rejected_without_modifying_destination(self):
        outside = Path(self.temporary.name) / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel.txt'
        sentinel.write_text('outside sentinel')
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        self._symlink(self.path('codex', 'references/linked'), outside, directory=True)
        with self.assertRaisesRegex(ValueError, 'Linked'):
            sync_hosts.synchronize(self.root, apply=True)
        self.assertEqual('outside sentinel', sentinel.read_text())
        self.assertEqual('# stale\n', destination.read_text())

    def test_linked_destination_directory_is_rejected_without_outside_writes(self):
        outside = Path(self.temporary.name) / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel.txt'
        sentinel.write_text('outside sentinel')
        self.write('codex', 'new/file.txt', 'canonical')
        self._symlink(self.path('claude-code', 'new'), outside, directory=True)
        with self.assertRaisesRegex(ValueError, 'Linked'):
            sync_hosts.synchronize(self.root, apply=True)
        self.assertEqual(['sentinel.txt'], [path.name for path in outside.iterdir()])
        self.assertEqual('outside sentinel', sentinel.read_text())

    def test_linked_root_component_is_not_resolved_away(self):
        alias = Path(self.temporary.name) / 'alias'
        self._symlink(alias, self.root, directory=True)
        with self.assertRaisesRegex(ValueError, 'Linked'):
            sync_hosts.synchronize(alias, apply=True)

    def test_default_cli_is_read_only_and_errors_have_distinct_status(self):
        destination = self.write('claude-code', 'scripts/example.py', '# stale\n')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, sync_hosts.main(['--root', str(self.root)]))
            self.assertEqual(0, sync_hosts.main(['--root', str(self.root), '--apply']))
        self.assertEqual('# common\n', destination.read_text())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, sync_hosts.main(['--root', str(self.root / 'missing')]))


if __name__ == '__main__':
    unittest.main()
