import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import token_usage


class TokenUsageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def log(self, name='private.jsonl', events=None):
        if events is None:
            events = self.turn()
        path = self.root / name
        path.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
        return path

    def turn(self, usage=None):
        if usage is None:
            usage = {'input_tokens': 100, 'cached_input_tokens': 70, 'output_tokens': 20}
        return [{'type': 'turn.started'}, {'type': 'turn.completed', 'usage': usage}]

    def run_cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = token_usage.main(args)
        return code, output.getvalue(), error.getvalue()

    def test_subset_accounting_and_hashes_without_transcript_or_paths(self):
        events = [{'type': 'thread.started', 'thread_id': 'PRIVATE_THREAD'},
                  {'type': 'item.completed', 'item': {'text': 'PRIVATE_TRANSCRIPT'}}]
        events += self.turn({'input_tokens': 100, 'cached_input_tokens': 70,
                             'output_tokens': 20, 'reasoning_output_tokens': 12})
        events += self.turn({'input_tokens': 40, 'cached_input_tokens': 10, 'output_tokens': 8})
        path = self.log(events=events)
        report = token_usage.summarize([path])
        usage = report['reported_usage']
        self.assertEqual({'input_tokens': 140, 'cached_input_tokens': 80, 'output_tokens': 28,
                          'uncached_input_tokens': 60, 'input_plus_output_tokens': 168,
                          'reasoning_output_tokens': 12}, usage)
        self.assertEqual('complete', report['coverage']['status'])
        self.assertEqual(1, report['coverage']['reasoning_turns_reported'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), report['sources'][0]['sha256'])
        rendered = json.dumps(report)
        for private in (str(path), path.name, 'PRIVATE_TRANSCRIPT', 'PRIVATE_THREAD'):
            self.assertNotIn(private, rendered)

    def test_zero_is_known_but_absent_usage_is_unknown(self):
        zero = self.log(events=self.turn({'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}))
        report = token_usage.summarize([zero])
        self.assertEqual(0, report['reported_usage']['input_plus_output_tokens'])
        self.assertIsNone(report['reported_usage']['reasoning_output_tokens'])
        self.assertEqual('complete', report['coverage']['status'])
        for terminal in ({'type': 'turn.completed'}, {'type': 'turn.completed', 'usage': None}):
            with self.subTest(terminal=terminal):
                missing = self.log('missing.jsonl', [{'type': 'turn.started'}, terminal])
                report = token_usage.summarize([missing])
                self.assertTrue(all(value is None for value in report['reported_usage'].values()))
                self.assertEqual('unknown', report['coverage']['status'])
                self.assertEqual(1, report['coverage']['completed_turns_without_usage'])

    def test_partial_coverage_and_failures_are_explicit_and_exit_one(self):
        events = self.turn() + [{'type': 'turn.started'}, {'type': 'turn.failed', 'error': {'message': 'PRIVATE'}}]
        events += [{'type': 'error', 'message': 'PRIVATE'}, {'type': 'turn.started'}]
        path = self.log(events=events)
        code, output, error = self.run_cli([str(path)])
        report = json.loads(output)
        self.assertEqual(1, code)
        self.assertEqual('', error)
        self.assertEqual('partial', report['coverage']['status'])
        for field in ('failed_turns', 'unfinished_turns', 'error_events'):
            self.assertEqual(1, report['coverage'][field])
        self.assertEqual(120, report['reported_usage']['input_plus_output_tokens'])
        self.assertNotIn('PRIVATE', output)

    def test_missing_usage_and_empty_files_never_imply_complete_coverage(self):
        complete = self.log()
        empty = self.log('empty.jsonl', [])
        self.assertEqual('unknown', token_usage.summarize([empty])['coverage']['status'])
        self.assertEqual('partial', token_usage.summarize([complete, empty])['coverage']['status'])
        missing = self.log('missing.jsonl', [{'type': 'turn.started'}, {'type': 'turn.completed'}])
        report = token_usage.summarize([complete, missing])
        self.assertEqual('partial', report['coverage']['status'])
        self.assertEqual(100, report['reported_usage']['input_tokens'])

    def test_distinct_sources_and_equal_turn_counts_are_summed(self):
        first = self.log(events=[{'type': 'thread.started', 'thread_id': 'one'}] + self.turn() * 2)
        second = self.log('second.jsonl', [{'type': 'thread.started', 'thread_id': 'two'}] + self.turn())
        report = token_usage.summarize([first, second])
        self.assertEqual(3, report['coverage']['completed_turns_with_usage'])
        self.assertEqual(300, report['reported_usage']['input_tokens'])

    def test_invalid_counters_and_subset_overflows_are_rejected(self):
        invalid = [True, False, -1, 1.5, '10', None, token_usage.MAX_COUNTER + 1]
        for counter in (*token_usage.COUNTERS, 'reasoning_output_tokens'):
            for value in invalid:
                with self.subTest(counter=counter, value=value):
                    usage = {'input_tokens': 10, 'cached_input_tokens': 2, 'output_tokens': 5, counter: value}
                    with self.assertRaisesRegex(token_usage.UsageError, 'counter'):
                        token_usage.summarize([self.log(events=self.turn(usage))])
        for usage in ({}, [], {'input_tokens': 10, 'output_tokens': 5},
                      {'input_tokens': 1, 'cached_input_tokens': 2, 'output_tokens': 5},
                      {'input_tokens': 10, 'cached_input_tokens': 2, 'output_tokens': 5, 'reasoning_output_tokens': 6}):
            with self.subTest(usage=usage), self.assertRaises(token_usage.UsageError):
                token_usage.summarize([self.log(events=self.turn(usage))])

    def test_bad_json_duplicate_keys_nonfinite_and_wrong_formats_have_no_traceback(self):
        path = self.root / 'private.jsonl'
        for value in (b'not json\n', b'\xff\n', b'\n', b'[]\n', b'{"type":"event_msg"}\n',
                      b'{"type":[]}\n', b'{"type":{}}\n',
                      b'{"type":"turn.started","type":"turn.completed"}\n',
                      b'{"type":"turn.started","nested":{"a":1,"a":2}}\n',
                      b'{"type":"turn.started","unused":NaN}\n',
                      b'{"type":"turn.started","unused":' + b'[' * 2000 + b']' * 2000 + b'}\n'):
            with self.subTest(value=value[:60]):
                path.write_bytes(value)
                code, output, error = self.run_cli([str(path)])
                self.assertEqual(2, code)
                self.assertEqual('', output)
                self.assertFalse(json.loads(error)['report_produced'])
                self.assertNotIn('Traceback', error)
                self.assertNotIn(str(path), error)

    def test_duplicate_files_content_and_terminal_events_are_rejected(self):
        first = self.log()
        second = self.log('copy.jsonl')
        for paths in ([first, first], [first, second]):
            with self.subTest(paths=paths), self.assertRaisesRegex(token_usage.UsageError, 'duplicate'):
                token_usage.summarize(paths)
        for events in (self.turn() + [self.turn()[-1]],
                       [{'type': 'turn.started'}, {'type': 'turn.started'}],
                       [{'type': 'thread.started'}, {'type': 'thread.started'}],
                       [{'type': 'turn.failed'}]):
            with self.subTest(events=events), self.assertRaises(token_usage.UsageError):
                token_usage.summarize([self.log(events=events)])

    def test_limits_are_checked_and_sources_are_preserved(self):
        path = self.log()
        before = path.read_bytes()
        cases = [('MAX_FILES', 0), ('MAX_FILE_BYTES', 1), ('MAX_TOTAL_BYTES', 1),
                 ('MAX_RECORD_BYTES', 1), ('MAX_RECORDS', 1)]
        for field, limit in cases:
            with self.subTest(field=field), patch.object(token_usage, field, limit):
                with self.assertRaisesRegex(token_usage.UsageError, 'limit'):
                    token_usage.summarize([path])
            self.assertEqual(before, path.read_bytes())
        with self.assertRaisesRegex(token_usage.UsageError, 'explicit'):
            token_usage.summarize([])

    def test_nonregular_missing_and_linked_sources_are_rejected(self):
        source = self.log()
        for path in (self.root, self.root / 'missing.jsonl'):
            with self.subTest(path=path), self.assertRaises(token_usage.UsageError):
                token_usage.summarize([path])
        alias = self.root / 'hard.jsonl'
        try:
            os.link(source, alias)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaisesRegex(token_usage.UsageError, 'hard-linked'):
                token_usage.summarize([source])
            alias.unlink()
        link = self.root / 'link.jsonl'
        try:
            link.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        with self.assertRaisesRegex(token_usage.UsageError, 'linked'):
            token_usage.summarize([link])

    def test_linked_ancestor_is_rejected(self):
        directory = self.root / 'real'
        directory.mkdir()
        source = directory / 'input.jsonl'
        source.write_bytes(self.log().read_bytes())
        alias = self.root / 'alias'
        try:
            alias.symlink_to(directory, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('directory symlinks unavailable')
        with self.assertRaisesRegex(token_usage.UsageError, 'linked'):
            token_usage.summarize([alias / source.name])

    def test_remote_device_stream_and_invalid_paths_fail_before_filesystem_access(self):
        for path in ('//example.invalid/share/run.jsonl', r'\\example.invalid\share\run.jsonl',
                     r'/\example.invalid/share/run.jsonl', r'\/example.invalid/share/run.jsonl',
                     r'\\?\C:\run.jsonl', 'run.jsonl:hidden', 'run\x00.jsonl'):
            with self.subTest(path=path), patch.object(Path, 'lstat', side_effect=AssertionError('filesystem accessed')):
                with self.assertRaisesRegex(token_usage.UsageError, 'paths are not allowed'):
                    token_usage.summarize([path])
                with self.assertRaisesRegex(token_usage.UsageError, 'paths are not allowed'):
                    token_usage.write_report(path, {})

    def test_changed_input_is_rejected(self):
        source = self.log()
        actual = token_usage._plain
        calls = 0

        def changing(path, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                source.write_bytes(source.read_bytes() + b'\n')
            return actual(path, **kwargs)

        with patch.object(token_usage, '_plain', side_effect=changing):
            with self.assertRaisesRegex(token_usage.UsageError, 'changed'):
                token_usage.summarize([source])

    def test_exclusive_output_preserves_sources_and_existing_files(self):
        source = self.log()
        before = source.read_bytes()
        report = self.root / 'report.json'
        code, output, error = self.run_cli([str(source), '--output', str(report)])
        self.assertEqual(0, code)
        self.assertEqual('', error)
        self.assertEqual(json.loads(output), json.loads(report.read_text(encoding='utf-8')))
        saved = report.read_bytes()
        for target in (report, source):
            with self.subTest(target=target):
                code, output, error = self.run_cli([str(source), '--output', str(target)])
                self.assertEqual(2, code)
                self.assertEqual('', output)
                self.assertIn('exclusively', error)
        self.assertEqual(saved, report.read_bytes())
        self.assertEqual(before, source.read_bytes())

    def test_input_failure_does_not_create_report_or_emit_partial_result(self):
        source = self.log()
        broken = self.log('broken.jsonl', self.turn({'input_tokens': -1, 'cached_input_tokens': 0, 'output_tokens': 0}))
        report = self.root / 'report.json'
        code, output, error = self.run_cli([str(source), str(broken), '--output', str(report)])
        self.assertEqual(2, code)
        self.assertEqual('', output)
        self.assertIn('input 2', error)
        self.assertFalse(report.exists())

    def test_write_failure_removes_new_partial_output(self):
        source = self.log()
        report = self.root / 'report.json'
        with patch.object(token_usage.os, 'fsync', side_effect=OSError('SYNTHETIC_PRIVATE')):
            code, output, error = self.run_cli([str(source), '--output', str(report)])
        self.assertEqual(2, code)
        self.assertEqual('', output)
        self.assertNotIn('SYNTHETIC_PRIVATE', error)
        self.assertFalse(report.exists())

    def test_stdout_failure_identifies_already_completed_report_file(self):
        class BrokenOutput(io.StringIO):
            def write(self, value):
                raise OSError('SYNTHETIC_PRIVATE')

        source = self.log()
        report = self.root / 'report.json'
        error = io.StringIO()
        with contextlib.redirect_stdout(BrokenOutput()), contextlib.redirect_stderr(error):
            code = token_usage.main([str(source), '--output', str(report)])
        self.assertEqual(2, code)
        self.assertTrue(json.loads(error.getvalue())['report_produced'])
        self.assertEqual('complete', json.loads(report.read_text())['coverage']['status'])
        self.assertNotIn('SYNTHETIC_PRIVATE', error.getvalue())

    def test_cli_runs_from_other_working_directory(self):
        source = self.log()
        result = subprocess.run([sys.executable, str(Path(token_usage.__file__)), str(source)],
                                cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('complete', json.loads(result.stdout)['coverage']['status'])


if __name__ == '__main__':
    unittest.main()
