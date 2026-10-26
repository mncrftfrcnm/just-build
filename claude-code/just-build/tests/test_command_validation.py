"""Regressions discovered by a fresh host trial using python -B."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import load_example
from just_build import InvalidSpec
import run_tracker as tracker


class PythonAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'tests').mkdir()
        (self.project / 'tests/test_checks.py').write_text(
            'import unittest\nclass Check(unittest.TestCase):\n def test_real(self): self.assertEqual(2+2,4)\n')
        (self.project / 'smoke.py').write_text(
            'import argparse\np=argparse.ArgumentParser();p.add_argument("--check",action="store_true")\n'
            'args=p.parse_args()\nassert args.check\n')
        self.plan = load_example('enhanced-build-plan.json')
        self.plan['contract_profile'] = 'standard'  # continuation compatibility, no external manifest needed here
        command = [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests']
        for task in self.plan['tasks']:
            task['test_command'] = command
        for check in self.plan['experience_checks']:
            check['test_command'] = command
        self.plan['smoke_command'] = [sys.executable, '-B', 'smoke.py', '--check']
        self.state = self.root / 'state'
        tracker.init(self.state, self.project, 'auto', 'continue', 'Exercise actual Python command binding')
        tracker.record_stage(self.state, 'research', 'done', 'Local regression, no web needed')
        tracker.record_stage(self.state, 'plan', 'active', 'Bound Python commands')
        path = self.root / 'plan.json'; path.write_text(json.dumps(self.plan))
        tracker.set_plan(self.state, path)
        tracker.record_stage(self.state, 'plan', 'done', 'Plan frozen')
        tracker.record_stage(self.state, 'implement', 'active', 'Real checking code exists')
        tracker.record_stage(self.state, 'implement', 'done', 'Ready for acceptance')
        tracker.record_stage(self.state, 'verify', 'active', 'Run commands')

    def tearDown(self):
        self.temp.cleanup()

    def test_no_bytecode_unittest_runs_as_bound_acceptance(self):
        task = self.plan['tasks'][0]
        result, output = tracker.actual_test(self.state, task['test_command'], label=task['test_label'])
        self.assertEqual(result['exit_code'], 0)
        self.assertIn('Ran 1 test', output)
        self.assertTrue(result['snapshot_stable'])

    def test_script_arguments_run_with_assertions(self):
        result, _ = tracker.actual_test(self.state, self.plan['smoke_command'], label='smoke')
        self.assertEqual(result['exit_code'], 0)
        self.assertTrue(result['snapshot_stable'])

    def test_combined_safe_interpreter_flags_are_recognized(self):
        tracker.validate_rigorous_command([sys.executable, '-IBu', '-m', 'unittest', 'discover', '-s', 'tests'],
                                          'journey', self.project, self.plan)

    def test_optimization_cannot_disable_acceptance_assertions(self):
        for flags in (['-O'], ['-OO'], ['-BO'], ['-B', '-O']):
            for tail in (['smoke.py', '--check'], ['-m', 'unittest', 'discover', '-s', 'tests']):
                with self.subTest(flags=flags, tail=tail), self.assertRaises(InvalidSpec):
                    tracker.validate_rigorous_command([sys.executable, *flags, *tail], 'smoke', self.project, self.plan)

    def test_inline_execution_stays_rejected(self):
        with self.assertRaises(InvalidSpec):
            tracker.validate_rigorous_command([sys.executable, '-B', '-c', 'print("ok")'], 'smoke', self.project, self.plan)


if __name__ == '__main__':
    unittest.main()
