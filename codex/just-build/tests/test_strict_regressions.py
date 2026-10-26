"""Concrete local regressions found by the strict installed-helper audit."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import load_example
from just_build import InvalidSpec
import run_tracker as tracker


class AcceptanceWorkingDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.checks = self.project / 'checks'
        self.checks.mkdir(parents=True)
        self.command = [sys.executable, '-B', 'check.py']
        self.state = self.root / 'state'
        tracker.init(self.state, self.project, 'auto', 'continue', 'Check a nested acceptance script')
        tracker.record_stage(self.state, 'research', 'done', 'Synthetic local regression')
        tracker.record_stage(self.state, 'plan', 'active', 'Bind nested acceptance')
        plan = load_example('enhanced-build-plan.json')
        plan['contract_profile'] = 'standard'
        for task in plan['tasks']:
            task['test_command'] = self.command
        for check in plan.get('experience_checks', []):
            check['test_command'] = self.command
        plan['smoke_command'] = self.command
        self.label = plan['tasks'][0]['test_label']
        source = self.root / 'plan.json'
        source.write_text(json.dumps(plan), encoding='utf-8')
        tracker.set_plan(self.state, source)
        tracker.record_stage(self.state, 'plan', 'done', 'Acceptance frozen')
        tracker.record_stage(self.state, 'implement', 'active', 'Implement fixture')
        tracker.record_stage(self.state, 'implement', 'done', 'Ready to check')
        tracker.record_stage(self.state, 'verify', 'active', 'Run nested command')

    def test_real_nested_python_script_is_inspected_and_runs(self):
        (self.checks / 'check.py').write_text('assert 2 + 2 == 4\n', encoding='utf-8')
        evidence, _ = tracker.actual_test(self.state, self.command, cwd=self.checks, label=self.label)
        self.assertEqual(evidence['exit_code'], 0)
        self.assertEqual(evidence['cwd'], str(self.checks.resolve()))
        self.assertTrue(evidence['snapshot_stable'])

    def test_root_script_cannot_supply_assertions_for_nested_print_only_script(self):
        (self.project / 'check.py').write_text('assert 2 + 2 == 4\n', encoding='utf-8')
        (self.checks / 'check.py').write_text('print("no acceptance executed")\n', encoding='utf-8')
        with self.assertRaisesRegex(InvalidSpec, 'observable assertions'):
            tracker.actual_test(self.state, self.command, cwd=self.checks, label=self.label)
        self.assertEqual(tracker.load(self.state)[1]['tests'], [])


if __name__ == '__main__':
    unittest.main()
