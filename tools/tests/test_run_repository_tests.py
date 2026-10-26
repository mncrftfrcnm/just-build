import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_repository_tests as runner


class RepositoryReportTests(unittest.TestCase):
    def execute(self, case, **kwargs):
        return runner.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(case), io.StringIO(), **kwargs)

    def test_success_and_test_prints_leave_machine_stream_clean(self):
        class Fixture(unittest.TestCase):
            def test_case(self):
                print('ordinary test diagnostic')
        output, diagnostic = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output):
            report = runner.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Fixture), diagnostic)
        self.assertEqual('', output.getvalue())
        self.assertIn('ordinary test diagnostic', diagnostic.getvalue())
        self.assertEqual((True, 'passed', 1, 1),
                         (report['passed'], report['status'], report['tests_run'], report['success_events']))

    def test_failures_errors_and_subtests_are_not_successes(self):
        class Fixture(unittest.TestCase):
            def test_failure(self):
                self.fail('PRIVATE_MESSAGE')
            def test_error(self):
                raise RuntimeError('PRIVATE_MESSAGE')
            def test_subtests(self):
                for value in (1, 2):
                    with self.subTest(value=value):
                        self.assertEqual(value, 0)
        report = self.execute(Fixture)
        self.assertFalse(report['passed'])
        self.assertEqual((3, 0, 3, 1), (report['tests_run'], report['success_events'], len(report['failures']), len(report['errors'])))
        self.assertNotIn('PRIVATE_MESSAGE', json.dumps(report))

    def test_skips_are_visible_and_can_be_fatal(self):
        class Fixture(unittest.TestCase):
            @unittest.skip('capability unavailable')
            def test_case(self):
                pass
        report = self.execute(Fixture)
        self.assertTrue(report['passed'])
        self.assertEqual('passed_with_omissions', report['status'])
        self.assertEqual(0, report['success_events'])
        self.assertEqual('capability unavailable', report['skipped'][0]['reason'])
        self.assertFalse(self.execute(Fixture, fail_on_skip=True)['passed'])

    def test_expected_failures_and_unexpected_success_are_explicit(self):
        class Expected(unittest.TestCase):
            @unittest.expectedFailure
            def test_case(self):
                self.fail('expected')
        class Unexpected(unittest.TestCase):
            @unittest.expectedFailure
            def test_case(self):
                pass
        expected = self.execute(Expected)
        unexpected = self.execute(Unexpected)
        self.assertTrue(expected['passed'])
        self.assertEqual('passed_with_omissions', expected['status'])
        self.assertEqual(1, len(expected['expected_failures']))
        self.assertFalse(unexpected['passed'])
        self.assertEqual(1, len(unexpected['unexpected_successes']))

    def test_empty_suite_is_not_a_passing_check(self):
        report = runner.run_suite(unittest.TestSuite(), io.StringIO())
        self.assertFalse(report['passed'])
        self.assertEqual(0, report['tests_run'])

    def invoke(self, digests=('one', 'one'), fail=False, args=None):
        class Fixture(unittest.TestCase):
            def test_case(self):
                if fail:
                    self.fail('synthetic')
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Fixture)
        output, error = io.StringIO(), io.StringIO()
        with patch.object(runner, 'source_digest', side_effect=digests), \
                patch.object(runner.unittest.defaultTestLoader, 'discover', return_value=suite), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = runner.main(args or [])
        return code, json.loads(output.getvalue())

    def test_main_binds_source_and_returns_actual_failure_status(self):
        code, report = self.invoke()
        self.assertEqual(0, code)
        self.assertTrue(report['source_unchanged'])
        self.assertEqual('one', report['source_sha256'])
        self.assertEqual(1, self.invoke(fail=True)[0])

    def test_changed_source_and_runner_errors_cannot_pass(self):
        code, report = self.invoke(('before', 'after'))
        self.assertEqual(1, code)
        self.assertEqual('source_changed', report['status'])
        output = io.StringIO()
        with patch.object(runner, 'source_digest', side_effect=OSError('PRIVATE')), contextlib.redirect_stdout(output):
            self.assertEqual(1, runner.main([]))
        report = json.loads(output.getvalue())
        self.assertFalse(report['completed'])
        self.assertEqual('runner_error', report['status'])
        self.assertNotIn('PRIVATE', output.getvalue())


if __name__ == '__main__':
    unittest.main()
