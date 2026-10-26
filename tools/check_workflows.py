#!/usr/bin/env python3
"""Validate this repository's deliberately small, read-only Actions profile.

This is project policy, not a complete GitHub Actions validator or sandbox. It
does not establish whether a pinned upstream action or checked-out code is safe.
New workflow features must be reviewed and explicitly added to this profile.
PyYAML is a development dependency; the installed skills remain stdlib-only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

try:
    import yaml
except ImportError as exc:
    raise SystemExit('Workflow checks require: python -m pip install -r requirements-dev.txt') from exc

ROOT = Path(__file__).resolve().parents[1]
AXES = {'os': ['ubuntu-latest', 'windows-latest'], 'python': ['3.11', '3.13'],
        'host': ['codex', 'claude-code']}
AGGREGATE_RUN = '''python - <<'PY'
import json, os, sys
results = json.loads(os.environ['JOB_RESULTS'])
failed = {name: job['result'] for name, job in results.items() if job['result'] != 'success'}
print(json.dumps(results, indent=2))
if not results or failed:
    sys.exit('Required jobs did not all succeed: ' + json.dumps(failed))
PY'''


class WorkflowLoader(yaml.SafeLoader):
    """Use true/false booleans without treating GitHub's `on` as YAML 1.1 true."""


WorkflowLoader.yaml_implicit_resolvers = {
    key: [(tag, regex) for tag, regex in resolvers if tag != 'tag:yaml.org,2002:bool']
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false)$', re.I), list('tTfF'))


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError(f'Workflow keys must be unique strings: {key!r}')
        result[key] = loader.construct_object(value_node)
    return result


WorkflowLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_workflow(path):
    text = Path(path).read_text(encoding='utf-8')
    if len(text.encode('utf-8')) > 128_000:
        raise ValueError('Workflow exceeds project size limit')
    try:
        if any(isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(text)):
            raise ValueError('Workflow anchors and aliases are outside the supported profile')
        result = yaml.load(text, Loader=WorkflowLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid workflow YAML: {exc}') from exc
    if not isinstance(result, dict):
        raise ValueError('Workflow must be a mapping')
    return result


def _keys(value, allowed, where):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'Unsupported {where} keys or structure')


def _needs(job):
    value = job.get('needs', [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value) or len(value) != len(set(value)):
        raise ValueError('Job needs must be unique literal job IDs')
    return set(value)


def _run_expressions(text, matrix):
    for expression in re.findall(r'\$\{\{(.*?)\}\}', text, flags=re.S):
        match = re.fullmatch(r'\s*matrix\.(os|python|host)\s*', expression)
        if not match or match[1] not in matrix:
            raise ValueError('Untrusted expression in run; pass inputs through environment variables')
    # Expressions must be complete; a malformed opener must not evade policy.
    if '${{' in re.sub(r'\$\{\{.*?\}\}', '', text, flags=re.S):
        raise ValueError('Malformed expression in run')


def validate_workflow(data, filename):
    _keys(data, {'name', 'on', 'permissions', 'concurrency', 'env', 'jobs'}, 'workflow')
    if data.get('permissions') != {'contents': 'read'}:
        raise ValueError('Workflow permissions must be contents: read only')
    if data.get('env') != {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'}:
        raise ValueError('Workflow environment must retain the reviewed Python settings')
    events = data.get('on')
    if isinstance(events, list):
        events = dict.fromkeys(events)
    if not isinstance(events, dict) or not events:
        raise ValueError('Workflow must declare supported events')
    release = filename == 'release-check.yml'
    expected_events = {'workflow_dispatch'} if release else {'push', 'pull_request', 'merge_group', 'workflow_dispatch'}
    if set(events) != expected_events:
        raise ValueError('Unsupported or privileged workflow events; unfiltered CI events are required')
    if not release and any(value is not None for value in events.values()):
        raise ValueError('CI event filters are not supported; required checks must always run')
    if release:
        _keys(events['workflow_dispatch'], {'inputs'}, 'dispatch')
        inputs = events['workflow_dispatch'].get('inputs')
        if not isinstance(inputs, dict) or set(inputs) != {'commit'}:
            raise ValueError('Release verification requires an exact commit input')
        for field in inputs.values():
            _keys(field, {'description', 'required', 'type'}, 'dispatch input')
            if field.get('required') is not True or field.get('type') != 'string':
                raise ValueError('Release inputs must be required strings')
    jobs = data.get('jobs')
    expected_jobs = {'repository', 'test', 'examples', 'packages', 'ci'} | ({'verify-ref'} if release else set())
    if not isinstance(jobs, dict) or set(jobs) != expected_jobs:
        raise ValueError('Workflow jobs must match the reviewed repository/test/examples/packages/ci profile')
    for job_id, job in jobs.items():
        _keys(job, {'name', 'needs', 'runs-on', 'timeout-minutes', 'strategy', 'steps', 'if', 'env'}, 'job')
        timeout = job.get('timeout-minutes')
        if type(timeout) is not int or not 1 <= timeout <= 15:
            raise ValueError('Every job requires a bounded timeout of 1..15 minutes')
        matrix = {}
        if 'strategy' in job:
            _keys(job['strategy'], {'fail-fast', 'matrix'}, 'strategy')
            matrix = job['strategy'].get('matrix')
            expected = ({'os', 'python', 'host'} if job_id == 'test' else
                        {'os', 'python'} if job_id == 'examples' else
                        {'os'} if job_id == 'repository' else set())
            if not isinstance(matrix, dict) or set(matrix) != expected or any(values != AXES[axis] for axis, values in matrix.items()):
                raise ValueError('Workflow matrix must retain the reviewed host/OS/Python combinations')
        elif job_id in ('repository', 'test', 'examples'):
            raise ValueError('Repository, skill and example jobs require their complete matrices')
        runner = job.get('runs-on')
        if runner not in ('ubuntu-latest', 'windows-latest') and not (runner == '${{ matrix.os }}' and 'os' in matrix):
            raise ValueError('Only reviewed GitHub-hosted runners are supported')
        if matrix and runner != '${{ matrix.os }}':
            raise ValueError('Matrix jobs must execute on their declared matrix.os runner')
        needs = _needs(job)
        if not needs <= set(jobs) or job_id in needs:
            raise ValueError('Invalid job dependencies')
        if job_id == 'ci':
            if needs != set(jobs) - {'ci'} or job.get('if') not in ('always()', '${{ always() }}'):
                raise ValueError('Aggregate CI must always depend on every prerequisite job')
            if job.get('name') != ('Release verification' if release else 'CI'):
                raise ValueError('Aggregate status name must be stable')
            if job.get('env') != {'JOB_RESULTS': '${{ toJSON(needs) }}'}:
                raise ValueError('Aggregate CI must inspect every dependency result')
            if job.get('steps') != [{'run': AGGREGATE_RUN}]:
                raise ValueError('Aggregate CI must fail on failed, cancelled or skipped prerequisites')
        else:
            if 'if' in job:
                raise ValueError('Prerequisite jobs must not be conditionally skipped')
            if 'env' in job and job_id != 'verify-ref':
                raise ValueError('Job environment is outside the reviewed profile')
            if release and job_id != 'verify-ref' and 'verify-ref' not in needs:
                raise ValueError('Release jobs must depend on immutable ref verification')
            if job_id == 'packages' and not {'repository', 'test', 'examples'} <= needs:
                raise ValueError('Packages must depend on all test groups')
        steps = job.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('Every job requires steps')
        checkouts = []
        python_setups = []
        uploads = []
        for step in steps:
            _keys(step, {'name', 'uses', 'with', 'run', 'if'}, 'step')
            if ('uses' in step) == ('run' in step):
                raise ValueError('A step must have exactly one uses or run')
            if 'run' in step:
                if not isinstance(step['run'], str):
                    raise ValueError('Run must be literal text')
                if 'if' in step:
                    raise ValueError('Required run steps must not be conditionally skipped')
                _run_expressions(step['run'], matrix)
                continue
            action = step['uses']
            if not isinstance(action, str) or not re.fullmatch(r'actions/(?:checkout|setup-python|upload-artifact)@[0-9a-f]{40}', action):
                raise ValueError('Reviewed Actions must use full commit pins')
            settings = step.get('with', {})
            if not isinstance(settings, dict):
                raise ValueError('Action settings must be a mapping')
            if action.startswith('actions/setup-python@'):
                python_setups.append(settings)
                expected_python = '${{ matrix.python }}' if 'python' in matrix else '3.13'
                if settings.get('python-version') != expected_python:
                    raise ValueError('Jobs must set up the reviewed interpreter: ' + expected_python)
            if action.startswith('actions/checkout@'):
                checkouts.append(settings)
                _keys(settings, {'persist-credentials', 'ref', 'fetch-depth'}, 'checkout')
                if settings.get('persist-credentials') is not False:
                    raise ValueError('Checkout must disable persisted credentials')
                if release and settings.get('ref') != '${{ inputs.commit }}':
                    raise ValueError('Release checkout must use the exact requested commit')
                if not release and 'ref' in settings:
                    raise ValueError('Standard CI must check its triggering revision')
            if action.startswith('actions/upload-artifact@'):
                uploads.append(step)
                retention = settings.get('retention-days')
                if settings.get('if-no-files-found') != 'error' or type(retention) is not int or not 1 <= retention <= 14:
                    raise ValueError('Artifacts must require files and have bounded retention')
                if 'if' in step and step['if'] != 'always()':
                    raise ValueError('Only unconditional artifact upload is supported')
            elif 'if' in step:
                raise ValueError('Required action steps must not be conditionally skipped')
        if job_id != 'ci' and len(checkouts) != 1:
            raise ValueError('Source jobs require exactly one checkout step')
        if job_id in ('repository', 'test', 'examples', 'packages') and len(python_setups) != 1:
            raise ValueError('Validation jobs require exactly one setup-python step for the reviewed interpreter')
        report_path = {'repository': 'test-results-repository.json', 'test': 'test-results.json',
                       'examples': 'test-results-examples.json', 'packages': 'dist/*'}.get(job_id)
        if report_path:
            if len(uploads) != 1 or uploads[0].get('with', {}).get('path') != report_path:
                raise ValueError('Validation jobs must upload exactly their required report or package path')
            if job_id != 'packages' and uploads[0].get('if') != 'always()':
                raise ValueError('Test reports must upload even after a failed test step')
        essential = {
            'repository': {'python -m pip install -r requirements-dev.txt', 'python tools/check_repo.py', 'python tools/run_repository_tests.py > test-results-repository.json'},
            'test': {'python ${{ matrix.host }}/just-build/scripts/run_skill_tests.py --report test-results.json'},
            'examples': {'python tools/run_examples.py --report test-results-examples.json'},
            'packages': {'python -m pip install -r requirements-dev.txt', 'python tools/build_release.py', 'python tools/verify_release.py --artifacts dist'},
        }.get(job_id, set())
        if not essential <= {step.get('run') for step in steps if 'run' in step}:
            raise ValueError('Workflow is missing required validation commands')
    if release:
        ref = jobs['verify-ref']
        if ref.get('env') != {'EXPECTED_COMMIT': '${{ inputs.commit }}'}:
            raise ValueError('Release commit input must be passed through an environment variable')
        if ref.get('steps', [])[-1].get('run') != RELEASE_REF_RUN:
            raise ValueError('Release ref job must verify the exact commit')
    return {'workflow': filename, 'jobs': len(jobs), 'passed': True}


RELEASE_REF_RUN = '''python - <<'PY'
import os, re, subprocess, sys
commit = os.environ['EXPECTED_COMMIT']
if not re.fullmatch(r'[0-9a-f]{40}', commit):
    sys.exit('Commit must be a full lower-case SHA')
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
if head != commit:
    sys.exit('The checked-out commit does not match the requested SHA')
print('Verified immutable release candidate commit:', commit)
PY'''


def check(root=ROOT):
    folder = Path(root) / '.github/workflows'
    files = sorted(folder.iterdir())
    if {file.name for file in files} != {'tests.yml', 'release-check.yml'} or any(not file.is_file() or file.is_symlink() for file in files):
        raise ValueError('All workflow files must be regular reviewed .yml workflows')
    results = [validate_workflow(load_workflow(file), file.name) for file in files]
    return {'passed': True, 'workflows': results,
            'scope': 'Repository-specific read-only workflow policy; not a complete Actions validator or action-code audit'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.root), indent=2))
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
