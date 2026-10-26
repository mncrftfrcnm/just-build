import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_workflows import (AGGREGATE_RUN, RELEASE_REF_RUN, ROOT, check,
                             load_workflow, validate_workflow)


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.ci = load_workflow(ROOT / '.github/workflows/tests.yml')
        self.release = load_workflow(ROOT / '.github/workflows/release-check.yml')

    def reject(self, workflow, message, filename='tests.yml'):
        with self.assertRaisesRegex(ValueError, message):
            validate_workflow(workflow, filename)

    def test_checked_in_workflows_pass(self):
        self.assertTrue(check()['passed'])
        self.assertEqual(set(self.ci['on']), {'push', 'pull_request', 'merge_group', 'workflow_dispatch'})
        self.assertIs(self.ci['jobs']['repository']['steps'][0]['with']['persist-credentials'], False)

    def test_duplicate_keys_and_aliases_are_rejected(self):
        for fixture in ('name: one\nname: two\n', 'env:\n  X: one\n  X: two\n', 'env: &x {X: one}\njobs: *x\n'):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'workflow.yml'
                path.write_text(fixture, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'unique|anchors'):
                    load_workflow(path)

    def test_privileged_events_and_path_filters_are_rejected(self):
        for event in ('pull_request_target', 'workflow_run'):
            item = copy.deepcopy(self.ci)
            item['on'] = [event]
            self.reject(item, 'privileged')
        item = copy.deepcopy(self.ci)
        item['on'] = {'push': {'paths': ['docs/**']}, 'pull_request': None,
                      'merge_group': None, 'workflow_dispatch': None}
        self.reject(item, 'filters')

    def test_write_permissions_and_job_overrides_are_rejected(self):
        for permission in ({'contents': 'write'}, {'contents': 'read', 'id-token': 'write'}, 'write-all'):
            item = copy.deepcopy(self.ci)
            item['permissions'] = permission
            self.reject(item, 'permissions')
        item = copy.deepcopy(self.ci)
        item['jobs']['test']['permissions'] = {'contents': 'write'}
        self.reject(item, 'job keys')

    def test_action_pins_checkout_credentials_timeouts_and_runners(self):
        mutations = [
            (lambda job: job['steps'][0].update(uses='actions/checkout@main'), 'commit pins'),
            (lambda job: job['steps'][0]['with'].update({'persist-credentials': True}), 'persisted credentials'),
            (lambda job: job.pop('timeout-minutes'), 'timeout'),
            (lambda job: job.update({'runs-on': ['self-hosted', 'linux']}), 'GitHub-hosted'),
            (lambda job: job.update({'continue-on-error': True}), 'job keys'),
            (lambda job: job['steps'][2].update({'continue-on-error': True}), 'step keys'),
            (lambda job: job['steps'][2].update({'if': 'false'}), 'conditionally skipped'),
        ]
        for mutate, message in mutations:
            with self.subTest(message=message):
                item = copy.deepcopy(self.ci)
                mutate(item['jobs']['repository'])
                self.reject(item, message)

    def test_untrusted_run_expressions_are_rejected(self):
        for expression in ('github.event.pull_request.title', 'inputs.commit', 'github.head_ref', 'needs.repository.outputs.command'):
            item = copy.deepcopy(self.ci)
            item['jobs']['repository']['steps'].append({'run': 'echo "${{ ' + expression + ' }}"'})
            self.reject(item, 'Untrusted expression')

    def test_matrix_coverage_and_required_commands_cannot_disappear(self):
        for job_id, axis in (('test', 'host'), ('test', 'os'), ('examples', 'python')):
            item = copy.deepcopy(self.ci)
            item['jobs'][job_id]['strategy']['matrix'][axis].pop()
            self.reject(item, 'matrix')
        item = copy.deepcopy(self.ci)
        item['jobs']['examples']['steps'][2]['run'] = 'echo skipped'
        self.reject(item, 'required validation commands')
        item = copy.deepcopy(self.ci)
        item['jobs']['packages']['needs'].remove('examples')
        self.reject(item, 'depend on all')

    def test_matrix_labels_cannot_substitute_literal_runners_or_interpreters(self):
        for filename, baseline in (('tests.yml', self.ci), ('release-check.yml', self.release)):
            for job_id in ('test', 'examples'):
                for setting in ('runner', 'python'):
                    with self.subTest(workflow=filename, job=job_id, setting=setting):
                        item = copy.deepcopy(baseline)
                        job = item['jobs'][job_id]
                        if setting == 'runner':
                            job['runs-on'] = 'ubuntu-latest'
                        else:
                            setup = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/setup-python@'))
                            setup['with']['python-version'] = '3.13'
                        self.reject(item, 'declared matrix|reviewed interpreter', filename)

    def test_repository_tooling_requires_both_operating_systems_and_python_313(self):
        for filename, baseline in (('tests.yml', self.ci), ('release-check.yml', self.release)):
            self.assertEqual(baseline['jobs']['repository']['strategy']['matrix'],
                             {'os': ['ubuntu-latest', 'windows-latest']})
            for mutation in ('runner', 'os', 'python', 'python-expression', 'strategy'):
                with self.subTest(workflow=filename, mutation=mutation):
                    item = copy.deepcopy(baseline)
                    job = item['jobs']['repository']
                    if mutation == 'runner':
                        job['runs-on'] = 'ubuntu-latest'
                    elif mutation == 'os':
                        job['strategy']['matrix']['os'].pop()
                    elif mutation == 'strategy':
                        job.pop('strategy')
                    else:
                        setup = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/setup-python@'))
                        setup['with']['python-version'] = '3.11' if mutation == 'python' else '${{ matrix.python }}'
                    self.reject(item, 'matrix|matrices|reviewed interpreter', filename)

    def test_matrix_interpreter_setup_cannot_be_removed_or_duplicated(self):
        for filename, baseline in (('tests.yml', self.ci), ('release-check.yml', self.release)):
            for job_id in ('repository', 'test', 'examples', 'packages'):
                for duplicate in (False, True):
                    with self.subTest(workflow=filename, job=job_id, duplicate=duplicate):
                        item = copy.deepcopy(baseline)
                        steps = item['jobs'][job_id]['steps']
                        setup = next(step for step in steps if step.get('uses', '').startswith('actions/setup-python@'))
                        if duplicate:
                            steps.append(copy.deepcopy(setup))
                        else:
                            steps.remove(setup)
                        self.reject(item, 'exactly one setup-python', filename)

    def test_source_jobs_require_one_checkout(self):
        for filename, baseline in (('tests.yml', self.ci), ('release-check.yml', self.release)):
            for job_id in set(baseline['jobs']) - {'ci'}:
                for duplicate in (False, True):
                    with self.subTest(workflow=filename, job=job_id, duplicate=duplicate):
                        item = copy.deepcopy(baseline)
                        steps = item['jobs'][job_id]['steps']
                        checkout = next(step for step in steps if step.get('uses', '').startswith('actions/checkout@'))
                        if duplicate:
                            steps.insert(0, copy.deepcopy(checkout))
                        else:
                            steps.remove(checkout)
                        self.reject(item, 'exactly one checkout', filename)

    def test_packages_require_the_reviewed_python_version(self):
        for filename, baseline in (('tests.yml', self.ci), ('release-check.yml', self.release)):
            item = copy.deepcopy(baseline)
            setup = next(step for step in item['jobs']['packages']['steps']
                         if step.get('uses', '').startswith('actions/setup-python@'))
            setup['with']['python-version'] = '3.11'
            self.reject(item, 'reviewed interpreter', filename)

    def test_aggregate_requires_every_job_and_its_failure_guard(self):
        mutations = [
            (lambda job: job['needs'].remove('packages'), 'every prerequisite'),
            (lambda job: job.pop('if'), 'every prerequisite'),
            (lambda job: job.update(name='CI passed'), 'stable'),
            (lambda job: job.update(steps=[{'run': 'echo passed'}]), 'failed, cancelled or skipped'),
        ]
        for mutate, message in mutations:
            item = copy.deepcopy(self.ci)
            mutate(item['jobs']['ci'])
            self.reject(item, message)

    def test_required_artifacts_cannot_be_removed_or_redirected(self):
        for filename, baseline in (('tests.yml', self.ci), ('release-check.yml', self.release)):
            for job_id in ('repository', 'test', 'examples', 'packages'):
                for mutation in ('missing', 'path', 'duplicate'):
                    with self.subTest(workflow=filename, job=job_id, mutation=mutation):
                        item = copy.deepcopy(baseline)
                        steps = item['jobs'][job_id]['steps']
                        upload = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@'))
                        if mutation == 'missing':
                            steps.remove(upload)
                        elif mutation == 'path':
                            upload['with']['path'] = 'unrelated.json'
                        else:
                            steps.append(copy.deepcopy(upload))
                        self.reject(item, 'required report or package path', filename)

    def test_failure_reports_cannot_be_conditionally_lost(self):
        for filename, baseline in (('tests.yml', self.ci), ('release-check.yml', self.release)):
            for job_id in ('repository', 'test', 'examples'):
                item = copy.deepcopy(baseline)
                upload = next(s for s in item['jobs'][job_id]['steps']
                              if s.get('uses', '').startswith('actions/upload-artifact@'))
                upload.pop('if')
                self.reject(item, 'even after a failed', filename)

    def test_aggregate_guard_executes_failed_cancelled_and_skipped_cases(self):
        script = AGGREGATE_RUN.split('\n', 1)[1].rsplit('\nPY', 1)[0]
        for status in ('success', 'failure', 'cancelled', 'skipped'):
            results = {'repository': {'result': 'success'}, 'test': {'result': status}}
            result = subprocess.run([sys.executable, '-c', script], env={**os.environ, 'JOB_RESULTS': json.dumps(results)}, capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, status == 'success', result.stderr)

    def test_release_verification_requires_exact_commit_and_ref_gate(self):
        item = copy.deepcopy(self.release)
        item['jobs']['test']['steps'][0]['with']['ref'] = '${{ inputs.tag }}'
        self.reject(item, 'exact requested commit', 'release-check.yml')
        item = copy.deepcopy(self.release)
        item['jobs']['verify-ref']['steps'][0]['with']['ref'] = '${{ github.sha }}'
        self.reject(item, 'exact requested commit', 'release-check.yml')
        item = copy.deepcopy(self.release)
        item['jobs']['test']['needs'] = []
        self.reject(item, 'immutable ref verification', 'release-check.yml')
        item = copy.deepcopy(self.release)
        item['jobs']['verify-ref']['steps'][-1]['run'] = 'echo approved'
        self.reject(item, 'exact commit', 'release-check.yml')

    def test_every_workflow_is_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / '.github/workflows'
            shutil.copytree(ROOT / '.github/workflows', folder)
            (folder / 'unreviewed.yaml').write_text('on: pull_request_target\n')
            with self.assertRaisesRegex(ValueError, 'All workflow files'):
                check(root)

    def test_release_ref_guard_checks_exact_requested_commit(self):
        script = RELEASE_REF_RUN.split('\n', 1)[1].rsplit('\nPY', 1)[0]
        with tempfile.TemporaryDirectory() as folder:
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=folder, text=True, stderr=subprocess.STDOUT).strip()
            git('init', '-q')
            (Path(folder) / 'README.md').write_text('fixture\n')
            git('add', 'README.md')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--no-gpg-sign', '-qm', 'fixture')
            commit = git('rev-parse', 'HEAD')
            cases = [(commit, True), ('0' * 40, False), ('HEAD', False),
                     (commit + ';echo injected', False), (commit.upper(), False)]
            for sha, success in cases:
                with self.subTest(sha=sha):
                    result = subprocess.run([sys.executable, '-c', script], cwd=folder,
                                            env={**os.environ, 'EXPECTED_COMMIT': sha},
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, success, result.stderr)


if __name__ == '__main__':
    unittest.main()
