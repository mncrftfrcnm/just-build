"""Public lifecycle regressions for state placement and delivered review freshness."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import ROOT
from just_build import InvalidSpec
import run_tracker as tracker


class ContinuationStatePlacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'app.py').write_text('value = 1\n', encoding='utf-8')

    def start(self, state):
        return tracker.init(state, self.project, 'auto', 'continue', 'Continue the selected existing project')

    def test_missing_nested_state_is_rejected_without_creating_directories(self):
        state = self.project / 'runs' / 'current'
        before = tracker.project_fingerprint(self.project)
        with self.assertRaisesRegex(InvalidSpec, 'outside'):
            self.start(state)
        self.assertFalse((self.project / 'runs').exists())
        self.assertEqual(tracker.project_fingerprint(self.project), before)

    def test_existing_empty_nested_state_is_rejected_without_writes(self):
        state = self.project / 'run-state'
        state.mkdir()
        with self.assertRaisesRegex(InvalidSpec, 'outside'):
            self.start(state)
        self.assertEqual(list(state.iterdir()), [])

    def test_project_itself_is_rejected_without_writes(self):
        before = tracker.project_fingerprint(self.project)
        with self.assertRaisesRegex(InvalidSpec, 'outside'):
            self.start(self.project)
        self.assertEqual(sorted(p.name for p in self.project.iterdir()), ['app.py'])
        self.assertEqual(tracker.project_fingerprint(self.project), before)

    def test_missing_external_state_is_created_without_changing_project(self):
        state = self.root / 'runs' / 'current'
        before = tracker.project_fingerprint(self.project)
        result = self.start(state)
        self.assertEqual(result['project'], str(self.project.resolve()))
        self.assertTrue((state / 'run.json').is_file())
        self.assertEqual(tracker.project_fingerprint(self.project), before)

    def test_fresh_existing_external_state_is_accepted(self):
        state = self.root / 'state'
        state.mkdir()
        self.start(state)
        self.assertTrue((state / 'run.json').is_file())


class StandardCompletionFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'app.py').write_text(
            'import argparse\n'
            'def double(value):\n'
            ' if value < 0: raise ValueError("value must be nonnegative")\n'
            ' return value * 2\n'
            'def main():\n'
            ' parser=argparse.ArgumentParser()\n'
            ' parser.add_argument("value", type=int)\n'
            ' args=parser.parse_args()\n'
            ' try: result=double(args.value)\n'
            ' except ValueError as exc: parser.error(str(exc))\n'
            ' print(result)\n'
            'if __name__ == "__main__": main()\n', encoding='utf-8')
        (self.project / 'journey_check.py').write_text(
            'from app import double\n'
            'assert double(4) == 8\n'
            'assert double(0) == 0\n', encoding='utf-8')
        (self.project / 'smoke.py').write_text(
            'import subprocess, sys\n'
            'ok=subprocess.run([sys.executable,"-B","app.py","3"],capture_output=True,text=True)\n'
            'assert ok.returncode == 0 and ok.stdout.strip() == "6", (ok.returncode,ok.stdout,ok.stderr)\n'
            'bad=subprocess.run([sys.executable,"-B","app.py","-1"],capture_output=True,text=True)\n'
            'assert bad.returncode == 2 and "nonnegative" in bad.stderr, (bad.returncode,bad.stderr)\n',
            encoding='utf-8')
        self.commands = {
            'journey': [sys.executable, '-B', 'journey_check.py'],
            'smoke': [sys.executable, '-B', 'smoke.py'],
        }
        self.state = self.root / 'state'
        tracker.init(self.state, self.project, 'auto', 'continue', 'Deliver the tested local doubling CLI')
        self.step('research', 'done')
        self.step('plan', 'active')
        plan = {
            'user_journey': 'Run the local CLI on a nonnegative number and read the doubled result.',
            'tasks': [{'id': 'double', 'change': 'Double nonnegative numbers',
                       'acceptance': 'Four doubles to eight and zero remains zero.',
                       'test_label': 'journey', 'test_command': self.commands['journey']}],
            'smoke_test': 'Use the public CLI, including its actionable negative-input error.',
            'smoke_label': 'smoke', 'smoke_command': self.commands['smoke'],
            'out_of_scope': [],
        }
        plan_file = self.root / 'plan.json'
        plan_file.write_text(json.dumps(plan), encoding='utf-8')
        tracker.set_plan(self.state, plan_file)
        self.step('plan', 'done')
        self.step('implement', 'active')
        self.step('implement', 'done')
        self.step('verify', 'active')
        self.run_checks()
        self.step('verify', 'done')
        self.initial_verified = self.read()['stages']['verify']['verified_fingerprint']
        self.step('quality', 'active')
        self.finish_review('quality')

    def read(self):
        return tracker.load(self.state)[1]

    def step(self, stage, status):
        return tracker.record_stage(self.state, stage, status, 'Synthetic lifecycle regression')

    def run_checks(self):
        for label, command in self.commands.items():
            evidence, _ = tracker.actual_test(self.state, command, label=label)
            self.assertEqual(evidence['exit_code'], 0)
            self.assertTrue(evidence['snapshot_stable'])
            self.assertTrue(evidence['cleanup_complete'])
            self.assertEqual(evidence['source_fingerprint'], tracker.run_fingerprint(self.read()))

    def finish_review(self, role):
        review = tracker.set_review(self.state, role, ROOT / 'examples' / (role + '-review.json'))
        self.assertEqual(review['source_fingerprint'], tracker.run_fingerprint(self.read()))
        self.step(role, 'done')

    def finish_polish(self):
        self.step('polish', 'active')
        self.finish_review('polish')
        self.assertTrue(tracker.reviews_current(self.read()))

    def edit_documentation(self):
        before = tracker.run_fingerprint(self.read())
        (self.project / 'README.md').write_text('Run python app.py NUMBER for a doubled result.\n', encoding='utf-8')
        self.assertNotEqual(tracker.run_fingerprint(self.read()), before)
        self.assertFalse(tracker.reviews_current(self.read()))

    def finish_final(self):
        self.step('final-verify', 'active')
        self.run_checks()
        self.step('final-verify', 'done')

    def finish_handoff(self):
        self.step('handoff', 'active')
        self.step('handoff', 'done')
        data = self.read()
        self.assertTrue(tracker.complete(data))
        self.assertEqual(data['final_fingerprint'], tracker.run_fingerprint(data))

    def recover_and_complete(self):
        data = self.read()
        old_reviews = {role: row['source_fingerprint'] for role, row in data['reviews'].items()}
        self.assertTrue(tracker.recheck_allowed(data))
        reopened = tracker.recheck(self.state)
        self.assertEqual(reopened['stages']['quality']['status'], 'active')
        self.assertEqual(reopened['reviews'], {})
        self.assertIsNone(reopened['final_fingerprint'])
        self.assertEqual(reopened['stages']['verify']['verified_fingerprint'], self.initial_verified)
        self.assertTrue(tracker.verification_ready(reopened, 'verify'))
        self.finish_review('quality')
        self.finish_polish()
        self.finish_final()
        self.finish_handoff()
        for role, old in old_reviews.items():
            self.assertNotEqual(self.read()['reviews'][role]['source_fingerprint'], old)

    def test_unchanged_standard_lifecycle_still_completes(self):
        self.finish_polish()
        self.finish_final()
        self.finish_handoff()
        self.assertFalse(tracker.recheck_allowed(self.read()))

    def test_late_edit_blocks_final_activation_and_has_honest_recovery(self):
        self.finish_polish()
        self.edit_documentation()
        with self.assertRaisesRegex(InvalidSpec, 'quality.*polish'):
            self.step('final-verify', 'active')
        self.assertEqual(self.read()['stages']['final-verify']['status'], 'pending')
        self.assertFalse(tracker.complete(self.read()))
        self.recover_and_complete()

    def test_edit_during_final_phase_blocks_completion_despite_fresh_passing_checks(self):
        self.finish_polish()
        self.step('final-verify', 'active')
        self.edit_documentation()
        self.run_checks()
        with self.assertRaisesRegex(InvalidSpec, 'quality.*polish'):
            self.step('final-verify', 'done')
        self.assertEqual(self.read()['stages']['final-verify']['status'], 'active')
        self.assertFalse(tracker.complete(self.read()))
        self.recover_and_complete()

    def test_late_edit_blocks_handoff_activation(self):
        self.finish_polish()
        self.finish_final()
        self.edit_documentation()
        with self.assertRaisesRegex(InvalidSpec, 'quality.*polish|changed after final verification'):
            self.step('handoff', 'active')
        self.assertFalse(tracker.complete(self.read()))

    def test_edit_during_handoff_blocks_completion(self):
        self.finish_polish()
        self.finish_final()
        self.step('handoff', 'active')
        self.edit_documentation()
        with self.assertRaisesRegex(InvalidSpec, 'quality.*polish|changed after final verification'):
            self.step('handoff', 'done')
        self.assertEqual(self.read()['stages']['handoff']['status'], 'active')
        self.assertFalse(tracker.complete(self.read()))

    def test_recheck_supports_all_unfinished_post_quality_polish_states(self):
        for status in ('pending', 'active', 'blocked', 'done'):
            with self.subTest(polish=status):
                if status == 'active':
                    self.step('polish', 'active')
                elif status == 'blocked':
                    self.step('polish', 'blocked')
                elif status == 'done':
                    self.step('polish', 'active')
                    self.finish_review('polish')
                self.assertEqual(self.read()['stages']['polish']['status'], status)
                self.assertTrue(tracker.recheck_allowed(self.read()))
        reopened = tracker.recheck(self.state)
        self.assertEqual(reopened['stages']['quality']['status'], 'active')
        self.assertEqual(reopened['stages']['polish']['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
