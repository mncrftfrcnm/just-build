"""Bounded delivery-output snapshots; all fixtures stay on the local filesystem."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from support import ROOT, load_example
import host_safety
from just_build import InvalidSpec
import run_tracker as tracker


class DeliveryManifestTests(unittest.TestCase):
    def test_historical_plan_and_empty_manifest_remain_readable(self):
        doc = load_example('build-plan.json')
        self.assertNotIn('delivery_artifacts', tracker.plan_validate(doc))
        doc['delivery_artifacts'] = []
        self.assertEqual(tracker.plan_validate(doc)['delivery_artifacts'], [])
        doc['delivery_artifacts'] = ['dist/z.js', 'build/a.html']
        self.assertEqual(tracker.plan_validate(doc)['delivery_artifacts'], ['build/a.html', 'dist/z.js'])

    def test_manifest_rejects_unsafe_paths_aliases_and_unbounded_counts(self):
        values = [None, 'dist/app.js', {}, [1], ['../outside'], ['/absolute'], ['C:/outside'],
                  ['C:relative'], ['dist/app.js:stream'], ['dist\\app.js'], ['dist/../outside'],
                  ['dist//app.js'], ['dist/./app.js'], ['dist/*'], ['dist/NUL.txt'],
                  ['dist/app.js', 'DIST/APP.JS'], ['a' * 181],
                  [f'dist/{i}.js' for i in range(tracker.MAX_DELIVERY_ARTIFACTS + 1)]]
        for value in values:
            with self.subTest(value=value), self.assertRaises(InvalidSpec):
                tracker.validate_delivery_artifacts(value)

    def test_only_explicit_files_are_read_and_historical_digest_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_bytes(b'value = 1\n')
            (root / 'dist').mkdir()
            output = root / 'dist/app.js'
            output.write_bytes(b'first delivered bundle')
            (root / 'dist/undeclared.js').write_bytes(b'unrelated')
            (root / 'node_modules').mkdir()
            (root / 'node_modules/dependency.js').write_bytes(b'uninspected dependency')
            historical = hashlib.sha256(json.dumps([
                ('app.py', hashlib.sha256(b'value = 1\n').hexdigest())
            ], ensure_ascii=False).encode('utf-8')).hexdigest()
            self.assertEqual(tracker.project_fingerprint(root), historical)
            self.assertEqual(tracker.project_fingerprint(root, []), historical)
            with patch.object(tracker, 'regular_bytes', wraps=tracker.regular_bytes) as reader:
                before = tracker.project_fingerprint(root, ['dist/app.js'])
            self.assertEqual({Path(call.args[0]).relative_to(root).as_posix() for call in reader.call_args_list},
                             {'app.py', 'dist/app.js'})
            (root / 'dist/undeclared.js').write_bytes(b'changed unrelated output')
            self.assertEqual(tracker.project_fingerprint(root, ['dist/app.js']), before)
            output.write_bytes(b'changed delivered bundle')
            self.assertNotEqual(tracker.project_fingerprint(root, ['dist/app.js']), before)
            self.assertEqual(tracker.project_fingerprint(root), historical)

    def test_missing_files_are_distinct_during_implementation_and_required_for_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = ['dist/app.js']
            absent = tracker.project_fingerprint(root, manifest, require_delivery=False)
            with self.assertRaisesRegex(InvalidSpec, 'missing'):
                tracker.project_fingerprint(root, manifest)
            (root / 'dist').mkdir()
            (root / 'dist/app.js').write_bytes(b'')
            self.assertNotEqual(tracker.project_fingerprint(root, manifest), absent)

    def test_directory_and_linked_file_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'dist'
            folder.mkdir()
            with self.assertRaises(InvalidSpec):
                tracker.project_fingerprint(root, ['dist'])
            output = folder / 'app.js'
            output.write_bytes(b'local fixture')
            original = host_safety.is_link
            with patch.object(host_safety, 'is_link', side_effect=lambda path: Path(path) == output or original(path)):
                with self.assertRaisesRegex(InvalidSpec, 'linked'):
                    tracker.project_fingerprint(root, ['dist/app.js'])

    def test_directory_symlink_or_windows_reparse_component_is_rejected_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'dist').mkdir()
            (root / 'actual').mkdir()
            (root / 'actual/app.js').write_bytes(b'local fixture')
            link = root / 'dist/linked'
            if os.name == 'nt':
                # The managed Windows filesystem forbids creating junctions.
                # Exercise the real reparse-attribute check with local metadata.
                link.mkdir()
                original = Path.lstat
                def lstat(path, *args, **kwargs):
                    if path == link:
                        return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700,
                                               st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'lstat', lstat):
                    with self.assertRaisesRegex(InvalidSpec, 'linked'):
                        tracker.project_fingerprint(root, ['dist/linked/app.js'])
            else:
                link.symlink_to(root / 'actual', target_is_directory=True)
                try:
                    with self.assertRaisesRegex(InvalidSpec, 'linked'):
                        tracker.project_fingerprint(root, ['dist/linked/app.js'])
                finally:
                    link.unlink()

    def test_per_file_and_aggregate_reads_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'dist').mkdir()
            for name in ('one.js', 'two.js'):
                (root / 'dist' / name).write_bytes(b'12345')
            with patch.object(tracker, 'MAX_DELIVERY_FILE_BYTES', 4):
                with self.assertRaisesRegex(InvalidSpec, 'size limit'):
                    tracker.project_fingerprint(root, ['dist/one.js'])
            with patch.object(tracker, 'MAX_DELIVERY_TOTAL_BYTES', 9):
                with self.assertRaisesRegex(InvalidSpec, 'snapshot budget'):
                    tracker.project_fingerprint(root, ['dist/one.js', 'dist/two.js'])


class DeliveryFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.project, self.state = base / 'project', base / 'state'
        self.project.mkdir()
        self.output = self.project / 'dist/app.js'
        self.script = self.project / 'probe.py'
        self.script.write_text('assert 2 + 2 == 4\n', encoding='utf-8')
        self.command = [sys.executable, 'probe.py']
        tracker.init(self.state, self.project, 'auto', 'continue', 'Track declared local delivered output')
        tracker.record_stage(self.state, 'research', 'skipped', 'Local deterministic fixture')
        tracker.record_stage(self.state, 'plan', 'active', 'Declare an output before it exists')
        self.plan_file = base / 'plan.json'
        self.doc = load_example('build-plan.json')
        self.doc['delivery_artifacts'] = ['dist/app.js']
        self.doc['tasks'][0]['test_command'] = self.command
        self.doc['smoke_command'] = self.command
        self.plan_file.write_text(json.dumps(self.doc), encoding='utf-8')
        tracker.set_plan(self.state, self.plan_file)
        tracker.record_stage(self.state, 'plan', 'done', 'Output may still be absent during planning')
        tracker.record_stage(self.state, 'implement', 'active', 'Build local output')

    def produce_output(self):
        self.output.parent.mkdir(exist_ok=True)
        self.output.write_bytes(b'initial delivered output')

    def verify_active(self, produce=True):
        if produce:
            self.produce_output()
        tracker.record_stage(self.state, 'implement', 'done', 'Implementation completed')
        tracker.record_stage(self.state, 'verify', 'active', 'Verify the delivered files')

    def run_required(self):
        for label in ('unit', 'smoke'):
            evidence, _ = tracker.actual_test(self.state, self.command, label=label)
            self.assertEqual(evidence['exit_code'], 0)
            self.assertTrue(evidence['snapshot_stable'])

    def reviews_done(self):
        for role in ('quality', 'polish'):
            tracker.record_stage(self.state, role, 'active', 'Review delivered output')
            tracker.set_review(self.state, role, ROOT / 'examples' / (role + '-review.json'))
            tracker.record_stage(self.state, role, 'done', 'Local fixture review')

    def final_verified(self):
        self.verify_active()
        self.run_required()
        tracker.record_stage(self.state, 'verify', 'done', 'Initial output passed')
        self.reviews_done()
        tracker.record_stage(self.state, 'final-verify', 'active', 'Repeat acceptance')
        self.run_required()
        tracker.record_stage(self.state, 'final-verify', 'done', 'Final output passed')

    def test_implementation_probe_can_run_before_planned_output_exists(self):
        evidence, _ = tracker.actual_test(self.state, self.command, label='probe')
        self.assertEqual(evidence['exit_code'], 0)
        self.assertTrue(evidence['snapshot_stable'])
        self.assertFalse(self.output.exists())
        self.verify_active(produce=False)
        with patch.object(tracker, 'run_command') as execute:
            with self.assertRaisesRegex(InvalidSpec, 'missing'):
                tracker.actual_test(self.state, self.command, label='unit')
            execute.assert_not_called()
        _, data = tracker.load(self.state)
        self.assertFalse(tracker.verification_ready(data))
        with self.assertRaisesRegex(InvalidSpec, 'missing'):
            tracker.record_stage(self.state, 'verify', 'done', 'Absent output must not pass')

    def test_declared_output_mutation_between_checks_stales_verification(self):
        self.verify_active()
        tracker.actual_test(self.state, self.command, label='unit')
        self.output.write_bytes(b'changed delivered output')
        tracker.actual_test(self.state, self.command, label='smoke')
        _, data = tracker.load(self.state)
        self.assertFalse(tracker.verification_ready(data))
        with self.assertRaises(InvalidSpec):
            tracker.record_stage(self.state, 'verify', 'done', 'Earlier output check is stale')
        tracker.actual_test(self.state, self.command, label='unit')
        tracker.record_stage(self.state, 'verify', 'done', 'Fresh output checks now agree')

    def test_test_that_changes_declared_output_is_unstable(self):
        self.verify_active()
        self.script.write_text('from pathlib import Path\nPath("dist/app.js").write_text("changed")\n', encoding='utf-8')
        evidence, _ = tracker.actual_test(self.state, self.command, label='unit')
        self.assertEqual(evidence['exit_code'], 0)
        self.assertFalse(evidence['snapshot_stable'])

    def test_contract_execution_binds_declared_output_before_and_after(self):
        self.verify_active()
        path, data = tracker.load(self.state)
        data['plan']['contract_profile'] = 'external-cli'
        data['behavior_contract'] = {'manifest': {'name': 'Local synthetic contract'}, 'sha256': 'local-contract'}
        tracker.save(path, data)
        def execute(*args):
            self.output.write_bytes(b'contract changed delivered output')
            return {'passed': True, 'steps_total': 1, 'steps_passed': 1}
        with patch.object(tracker, 'execute_behavior_contract', side_effect=execute):
            result = tracker.run_behavior_contract(self.state)
        self.assertFalse(result['source_unchanged'])
        _, data = tracker.load(self.state)
        self.assertFalse(data['tests'][-1]['snapshot_stable'])
        self.output.unlink()
        with patch.object(tracker, 'execute_behavior_contract') as execute:
            with self.assertRaisesRegex(InvalidSpec, 'missing'):
                tracker.run_behavior_contract(self.state)
            execute.assert_not_called()

    def test_review_cannot_complete_after_declared_output_changes(self):
        self.verify_active()
        self.run_required()
        tracker.record_stage(self.state, 'verify', 'done', 'Initial output passed')
        tracker.record_stage(self.state, 'quality', 'active', 'Review delivered output')
        tracker.set_review(self.state, 'quality', ROOT / 'examples/quality-review.json')
        self.output.write_bytes(b'changed after quality review')
        with self.assertRaisesRegex(InvalidSpec, 'review is stale'):
            tracker.record_stage(self.state, 'quality', 'done', 'Old review must not pass')
        self.output.unlink()
        with self.assertRaisesRegex(InvalidSpec, 'missing'):
            tracker.set_review(self.state, 'quality', ROOT / 'examples/quality-review.json')

    def test_security_scan_and_approval_require_current_declared_output(self):
        self.produce_output()
        path, data = tracker.load(self.state)
        data['plan']['security_profile'] = 'full'
        data['stages']['polish']['status'] = 'done'
        tracker.save(path, data)
        scan = tracker.security_scan(self.state)
        _, data = tracker.load(self.state)
        for role in ('quality', 'polish', 'security'):
            data['reviews'][role] = {'verdict': 'pass', 'source_fingerprint': scan['source_fingerprint']}
        self.assertTrue(tracker.security_review_ready(data))
        self.output.write_bytes(b'changed after security scan')
        self.assertFalse(tracker.security_review_ready(data))
        with self.assertRaisesRegex(InvalidSpec, 'fresh scan'):
            tracker.set_security_review(self.state, ROOT / 'examples/security-review.json')
        self.output.unlink()
        with patch.object(tracker, 'scan_local_security') as execute:
            with self.assertRaisesRegex(InvalidSpec, 'missing'):
                tracker.security_scan(self.state)
            execute.assert_not_called()

    def test_delivered_output_edit_after_final_checks_blocks_handoff(self):
        self.final_verified()
        tracker.record_stage(self.state, 'handoff', 'active', 'Prepare local handoff')
        self.output.write_bytes(b'changed after final checks')
        with self.assertRaisesRegex(InvalidSpec, 'changed after final verification'):
            tracker.record_stage(self.state, 'handoff', 'done', 'Old final evidence cannot complete')

    def test_completed_delivery_stales_on_declared_output_change_or_removal(self):
        self.final_verified()
        tracker.record_stage(self.state, 'handoff', 'active', 'Prepare local handoff')
        tracker.record_stage(self.state, 'handoff', 'done', 'Deliver local fixture')
        _, data = tracker.load(self.state)
        self.assertTrue(tracker.complete(data))
        self.output.write_bytes(b'changed completed delivery')
        self.assertFalse(tracker.verification_ready(data, 'final-verify'))
        self.assertFalse(tracker.complete(data))
        self.output.unlink()
        self.assertFalse(tracker.verification_ready(data, 'final-verify'))
        self.assertFalse(tracker.complete(data))

    def test_set_plan_rejects_existing_directory_artifact(self):
        path, data = tracker.load(self.state)
        data['stages']['plan']['status'] = 'active'
        tracker.save(path, data)
        self.produce_output()
        self.doc['delivery_artifacts'] = ['dist']
        self.plan_file.write_text(json.dumps(self.doc), encoding='utf-8')
        with self.assertRaises(InvalidSpec):
            tracker.set_plan(self.state, self.plan_file)


if __name__ == '__main__':
    unittest.main()
