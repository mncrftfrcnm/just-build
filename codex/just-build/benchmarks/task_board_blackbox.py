#!/usr/bin/env python3
"""Independent fixture evaluator. Takes an existing runnable task board path.

This benchmark is deliberately outside the generated project's own test suite.
It validates observable behavior, not an autonomous Codex run.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from host_safety import is_link, checked_path
from process_runner import run_command


def evaluate(project):
    if is_link(project):
        raise AssertionError('linked project roots are forbidden')
    project = Path(project).resolve(strict=True)
    app = checked_path(project / 'app.py', project)
    if not app.is_file():
        raise AssertionError('missing public app.py entry point')
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / 'db.json'
        cmd = [sys.executable, str(app), '--data', str(data)]
        def execute(argv):
            result = run_command(argv, project, timeout=30)
            return subprocess.CompletedProcess(argv, result.returncode,
                result.stdout.decode('utf-8', errors='replace'), result.stderr.decode('utf-8', errors='replace'))
        def run(*args):
            try:
                return execute(cmd + list(args))
            except subprocess.TimeoutExpired as exc:
                raise AssertionError('public CLI timed out on ' + (args[0] if args else 'command')) from exc
        try:
            help_result = execute([sys.executable, str(app), '--help'])
        except subprocess.TimeoutExpired as exc:
            raise AssertionError('public CLI help timed out') from exc
        assert help_result.returncode == 0 and 'add' in help_result.stdout and 'done' in help_result.stdout, 'help path'
        initial = run('list')
        assert initial.returncode == 0 and not data.exists() and 'No tasks yet' in initial.stdout and 'add' in initial.stdout, 'first-run list must explain next action without mutating missing data'
        invalid = run('add', '   ')
        assert invalid.returncode != 0 and ('blank' in invalid.stderr.lower() or 'empty' in invalid.stderr.lower()), 'invalid title error'
        assert not data.exists(), 'failed add must not write file'
        add = run('add', 'File the report')
        assert add.returncode == 0, f'valid add failed: {add.stderr}'
        assert data.exists(), 'successful add must persist a data file'
        saved = json.loads(data.read_text())
        assert len(saved) == 1 and saved[0]['title'] == 'File the report' and saved[0]['done'] is False, 'persisted add state'
        assert 'File the report' in run('list').stdout, 'list reflects persistent task'
        missing = run('done', '999')
        assert missing.returncode != 0 and '999' not in run('list').stdout, 'missing ID must fail without writing bogus task'
        complete = run('done', str(saved[0]['id']))
        assert complete.returncode == 0 and json.loads(data.read_text())[0]['done'] is True, 'completion persists'
        assert 'done' in run('list').stdout, 'list shows completed task'
    return {'passed': True, 'checks': ['help', 'actionable empty-state', 'invalid title', 'no mutation on error', 'persist add', 'list', 'missing id', 'persist complete']}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--project', required=True)
    args = p.parse_args()
    try:
        print(json.dumps(evaluate(args.project), indent=2))
    except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'benchmark failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
