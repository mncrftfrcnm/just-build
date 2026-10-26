"""Local regression probes only; no real credentials or external targets."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import http.client
from unittest.mock import patch

from support import ROOT, load_example
import api_contract
import behavior_contract
import host_safety
from just_build import InvalidSpec, inspect_project, read_json
import process_runner
from process_runner import ProcessSafetyError, resolve_executable, run_command
import run_tracker
import security_audit


def directory_link(link, target):
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)],
                                capture_output=True, timeout=5)
        if result.returncode:
            raise AssertionError('Local junction fixture requires filesystem permission')
    else:
        link.symlink_to(target, target_is_directory=True)


def remove_directory_link(link):
    if os.name == 'nt':
        link.rmdir()
    else:
        link.unlink()


class SafeInputTests(unittest.TestCase):
    def test_research_url_cannot_embed_credentials_or_control_characters(self):
        for url in ('https://:synthetic-only@example.org/docs', 'https://example.org/\r\nInjected', 'https://example.org:invalid/docs'):
            with self.subTest(url=url):
                research = load_example('implementation-research.json')
                research['url'] = url
                with self.assertRaises(InvalidSpec):
                    run_tracker.validate_research(research)

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            for text in ('{"safe":true,"safe":false}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(InvalidSpec):
                        read_json(path)

    def test_deep_json_is_a_clean_validation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            path.write_text('[' * 2000 + '0' + ']' * 2000)
            with self.assertRaises(InvalidSpec):
                read_json(path)

    def test_json_depth_limit_ignores_quoted_and_escaped_brackets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            value = {'text': ('[{' * 150) + '\\"' + ('}]' * 150)}
            path.write_text(json.dumps(value))
            self.assertEqual(read_json(path), value)

    def test_actual_bytes_are_bounded_even_if_size_metadata_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.txt'
            path.write_bytes(b'x' * 1024)
            stale = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=0, st_nlink=1)
            with patch.object(host_safety.os, 'fstat', return_value=stale):
                with self.assertRaisesRegex(ValueError, 'grew beyond'):
                    host_safety.regular_bytes(path, maximum=32)

    def test_nonregular_opened_handle_is_never_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.txt'
            path.write_bytes(b'fixture')
            special = SimpleNamespace(st_mode=stat.S_IFIFO, st_size=0, st_nlink=1)
            with patch.object(host_safety.os, 'fstat', return_value=special), patch.object(host_safety.os, 'read') as reader:
                with self.assertRaisesRegex(ValueError, 'regular file'):
                    host_safety.regular_bytes(path)
                reader.assert_not_called()

    def test_oversized_state_cannot_bypass_json_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run.json'
            path.write_text('{"padding":"' + 'x' * 2_000_000 + '"}')
            with self.assertRaises(InvalidSpec):
                run_tracker.load(tmp)

    def test_inaccessible_walk_cannot_produce_a_clean_scan_or_snapshot(self):
        def denied(*args, onerror=None, **kwargs):
            if onerror:
                onerror(PermissionError('synthetic inaccessible directory'))
            return iter(())
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(host_safety.os, 'walk', denied):
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    security_audit.scan(tmp)
                with self.assertRaises(InvalidSpec):
                    run_tracker.project_fingerprint(tmp)

    def test_empty_directory_tree_is_also_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'one' / 'two').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'directory count'):
                list(host_safety.walk_regular(root, max_dirs=2))

    def test_unparseable_source_cannot_receive_a_clean_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'broken.py').write_text('def invalid(:')
            result = security_audit.scan(tmp)
            self.assertTrue(any(row['code'] == 'unparseable-python' and row['severity'] == 'major' for row in result['findings']))

    def test_api_rejects_response_larger_than_contract_budget(self):
        with patch.object(api_contract.http.client, 'HTTPConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.read.return_value = b'x' * 4097
            with self.assertRaises(http.client.HTTPException):
                api_contract._request(12345, 'GET', '/fixture')

    def test_cli_exclusion_checks_cover_output_beyond_old_display_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text('print("No tasks yet" + "x" * 25000 + "FORBIDDEN_FIXTURE")')
            contract = load_example('cli-behavior-contract.json')
            contract['scenarios'][0]['steps'][0]['stdout_excludes'] = ['FORBIDDEN_FIXTURE']
            result = behavior_contract.run(root, contract)
            self.assertFalse(result['passed'])
            self.assertIn('stdout_excludes: forbidden text present', result['outcomes'][0]['failures'])

    def test_relative_json_root_paths_still_work(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            path = Path(tmp) / 'input.json'
            path.write_text('{"fixture":true}')
            relative = path.relative_to(Path.cwd())
            self.assertTrue(host_safety.bounded_json(relative, root=relative.parent)['fixture'])

    def test_scratch_parent_link_inside_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'real'; target.mkdir()
            link = root / 'alias'
            directory_link(link, target)
            try:
                with self.assertRaises(behavior_contract.ContractError):
                    behavior_contract.scratch_file(root, 'alias/fixture.txt')
            finally:
                remove_directory_link(link)

    def test_scratch_hardlink_to_another_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'outside.txt'
            outside.write_text('synthetic fixture; not a secret')
            scratch = root / 'scratch'; scratch.mkdir()
            os.link(outside, scratch / 'linked.txt')
            with self.assertRaises(behavior_contract.ContractError):
                behavior_contract.scratch_file(scratch, 'linked.txt')

    def test_linked_api_entry_parent_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'real'; target.mkdir()
            (target / 'server.py').write_text('raise RuntimeError("must not run")')
            link = root / 'alias'
            directory_link(link, target)
            contract = load_example('security/local-api-contract.json')
            contract['launch']['argv'][1] = '{project}/alias/server.py'
            try:
                with self.assertRaises(api_contract.APIContractError):
                    api_contract.run(root, contract)
            finally:
                remove_directory_link(link)

    def test_reserved_unicode_devices_and_wildcards_are_rejected(self):
        for name in ('COM\u00b9.txt', 'LPT\u00b2', 'file?.json', 'folder/*', 'aux .txt', 'x|y'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                host_safety.safe_relative(name)


class ProcessSupervisionTests(unittest.TestCase):
    def control_pipe(self, limit):
        original_popen = process_runner.subprocess.Popen
        writes = []

        class PartialPipe:
            def __init__(self, stream):
                self.stream = stream

            def write(self, data):
                writes.append(len(data))
                return self.stream.write(data[:limit]) if limit else limit

            def flush(self):
                self.stream.flush()

            def close(self):
                self.stream.close()

        def launch(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            proc.stdin = PartialPipe(proc.stdin)
            return proc

        return patch.object(process_runner.subprocess, 'Popen', side_effect=launch), writes

    def test_partial_control_writes_deliver_the_complete_command(self):
        command = [sys.executable, '-c', 'import sys;print(sys.argv[1])', 'partial delivery ' * 30]
        patched, writes = self.control_pipe(17)
        with patched:
            result = run_command(command, Path.cwd(), timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode().strip(), command[-1].strip())
        self.assertGreater(len(writes), 1)
        self.assertTrue(result.cleanup_complete)

    def test_control_pipe_without_progress_refuses_command_start(self):
        for progress in (0, None):
            with self.subTest(progress=progress), tempfile.TemporaryDirectory() as tmp:
                patched, _ = self.control_pipe(progress)
                with patched, self.assertRaisesRegex(ProcessSafetyError, 'control message'):
                    run_command([sys.executable, '-c', 'from pathlib import Path;Path("started").touch()'], tmp, timeout=5)
                self.assertFalse((Path(tmp) / 'started').exists())

    def test_exact_output_budget_is_accepted(self):
        result = run_command([sys.executable, '-c', 'import sys;sys.stdout.buffer.write(b"x"*8192)'],
                             Path.cwd(), timeout=5, max_output=8192)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout), 8192)
        self.assertEqual(result.output_bytes, 8192)
        self.assertFalse(result.output_limited)
        self.assertTrue(result.cleanup_complete)

    def test_explicit_cancellation_stops_a_running_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with process_runner.ManagedProcess([sys.executable, '-c',
                    'from pathlib import Path;import time;Path("ready").touch();time.sleep(60)'], root, timeout=10) as proc:
                deadline = time.monotonic() + 5
                while not (root / 'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((root / 'ready').exists(), 'the command must start before cancellation')
                result = proc.close()
                self.assertEqual(result.returncode, 125)
                self.assertTrue(result.cleanup_complete)
                self.assertFalse(result.timed_out)
                self.assertEqual(proc.poll(), 125)
                self.assertIs(proc.wait(), result)

    def test_successful_command_preserves_exit_and_bounded_output(self):
        result = run_command([sys.executable, '-c', 'import sys;print("fixture");sys.exit(7)'], Path.cwd(), timeout=5)
        self.assertEqual(result.returncode, 7)
        self.assertIn(b'fixture', result.stdout)
        self.assertTrue(result.cleanup_complete)

    def test_stdout_flood_fails_without_disk_spooling(self):
        result = run_command([sys.executable, '-c', 'import sys;sys.stdout.write("x"*1000000)'], Path.cwd(), timeout=5, max_output=8192)
        self.assertEqual(result.returncode, 87)
        self.assertTrue(result.output_limited)
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 8192)

    def test_stderr_shares_the_same_output_budget(self):
        result = run_command([sys.executable, '-c', 'import sys;sys.stdout.write("a"*5000);sys.stderr.write("b"*5000)'], Path.cwd(), timeout=5, max_output=8192)
        self.assertTrue(result.output_limited)
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 8192)

    def run_descendant_fixture(self, timeout_parent):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = ('from pathlib import Path\nimport time\nPath("ready").write_text("ready")\n'
                     'deadline=time.monotonic()+15\nwhile time.monotonic()<deadline:\n'
                     ' if Path("release").exists():\n  Path("escaped").write_text("must not survive");break\n'
                     ' time.sleep(.01)\n')
            parent = 'import subprocess,sys,time\nfrom pathlib import Path\nsubprocess.Popen([sys.executable,"-c",' + repr(child) + '])\nfor _ in range(200):\n if Path("ready").exists(): break\n time.sleep(.01)\n' + ('time.sleep(10)\n' if timeout_parent else 'print("parent finished")\n')
            (root / 'parent.py').write_text(parent)
            result = run_command([sys.executable, 'parent.py'], root, timeout=5)
            self.assertTrue((root / 'ready').exists(), 'child must actually start for this to test cleanup')
            self.assertTrue(result.cleanup_complete)
            self.assertEqual(result.timed_out, timeout_parent)
            (root / 'release').touch()
            time.sleep(1.2)
            self.assertFalse((root / 'escaped').exists(), 'descendant survived the supervised command')

    def test_timeout_stops_descendant_processes(self):
        self.run_descendant_fixture(True)

    def test_successful_parent_exit_also_stops_descendants(self):
        self.run_descendant_fixture(False)

    def test_cwd_cannot_shadow_a_bare_host_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = Path(sys.executable).name
            (root / name).write_text('synthetic impostor; must never execute')
            search = str(root) + os.pathsep + str(Path(sys.executable).parent)
            with patch.dict(os.environ, {'PATH': search}):
                actual = resolve_executable(name, root)
            self.assertEqual(Path(actual), Path(sys.executable).resolve())

    def test_implicit_windows_batch_execution_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.cmd'
            path.write_text('@echo must not run')
            with self.assertRaises(ProcessSafetyError):
                run_command([str(path), '&', 'untrusted'], tmp)

    def test_secret_and_loader_environment_do_not_reach_target(self):
        command = 'import os;assert "TEST_SECRET" not in os.environ;assert "PYTHONPATH" not in os.environ;print("minimal env")'
        with patch.dict(os.environ, {'TEST_SECRET': 'synthetic-only', 'PYTHONPATH': 'untrusted'}):
            result = run_command([sys.executable, '-c', command], Path.cwd(), timeout=5)
        self.assertEqual(result.returncode, 0)

    def test_windows_job_failure_does_not_start_selected_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [sys.executable, '-c', 'from pathlib import Path;Path("started").touch()']
            with patch.object(process_runner, '_WindowsJob', side_effect=ProcessSafetyError('synthetic job failure')):
                if os.name == 'nt':
                    with self.assertRaises(ProcessSafetyError):
                        run_command(command, root, timeout=5)
                    self.assertFalse((root / 'started').exists())
                else:
                    # POSIX uses its own process-group containment, not Win32.
                    self.assertEqual(run_command(command, root, timeout=5).returncode, 0)


class PassiveGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git = shutil.which('git')
        self.assertIsNotNone(self.git, 'Git is needed for the passive-inspection regression fixture')
        self.call('-c', 'init.templateDir=', 'init', '-q')
        (self.root / 'fixture.txt').write_text('synthetic fixture\n')
        self.call('add', 'fixture.txt')
        self.marker = self.root / 'unexpected-hook'
        hook = self.root / '.git/hooks/fsmonitor-fixture'
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\nprintf invoked > "' + self.marker.as_posix() + '"\nprintf "\\0"\n', encoding='utf-8')
        hook.chmod(0o700)
        self.call('config', 'core.fsmonitor', hook.as_posix())

    def call(self, *args):
        result = run_command([self.git, *args], self.root, timeout=10,
                             extra_env={'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_passive_inspection_never_invokes_configured_fsmonitor(self):
        result = inspect_project(self.root)
        self.assertTrue(result['git']['available'], result)
        self.assertFalse(self.marker.exists())
        self.assertFalse(result['git']['safe_to_treat_as_clean'])

    def test_controlled_hook_fixture_would_execute_without_inspection_guards(self):
        # Counter-check the fixture itself: this known, reviewed hook only
        # creates its marker inside the disposable test repository.
        self.call('status', '--porcelain=v1')
        self.assertTrue(self.marker.exists())

    def test_content_filters_require_review_before_status_execution(self):
        self.call('config', 'filter.fixture.clean', 'must-not-run-synthetic-filter')
        result = inspect_project(self.root)
        self.assertEqual(result['git']['status'], 'not-inspected-configured-content-filters')
        self.assertFalse(result['git']['safe_to_treat_as_clean'])
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
