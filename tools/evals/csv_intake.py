#!/usr/bin/env python3
"""External holdout checks for the named CSV Intake Check evaluation scenario.

Run only against an authorized local project. The app runs with host privileges.
These cases were fixed before observing the builder's implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'codex/just-build/scripts'))
from host_safety import checked_path
from process_runner import run_command


def evaluate(project):
    if not __debug__:
        raise ValueError('Run evaluation without Python optimization flags so all assertions remain active.')
    project = Path(project).resolve(strict=True)
    entry = checked_path('app.py', project)
    outcomes = []

    def record(name, callback):
        try:
            callback()
            outcomes.append({'name': name, 'passed': True})
        except (AssertionError, OSError, ValueError, KeyError, TypeError) as exc:
            outcomes.append({'name': name, 'passed': False, 'reason': str(exc)[:500]})

    def help_case():
        result = run_command([sys.executable, str(entry), '--help'], project, timeout=8)
        assert result.returncode == 0 and result.cleanup_complete, 'help failed'
        assert b'check' in result.stdout and b'Traceback' not in result.stderr, 'help must describe check'

    record('public-help', help_case)
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)

        def case(name, content, valid, rows=None, code=None, line=None):
            path = scratch / (name + '.csv')
            if content is not None:
                path.write_bytes(content)
            before = path.read_bytes() if path.exists() else None
            result = run_command([sys.executable, str(entry), 'check', str(path), '--json'], project, timeout=8)
            assert result.returncode == (0 if valid else 2), f'unexpected exit {result.returncode}'
            assert result.cleanup_complete and not result.output_limited and not result.timed_out, 'execution incomplete'
            assert b'Traceback' not in result.stderr, 'traceback leaked'
            body = json.loads(result.stdout.decode('utf-8-sig'))
            assert type(body.get('valid')) is bool and body['valid'] is valid, 'incorrect validity'
            assert type(body.get('rows')) is int and body['rows'] >= 0, 'missing row count'
            assert isinstance(body.get('errors'), list), 'missing errors array'
            if rows is not None:
                assert body['rows'] == rows, f'incorrect rows {body["rows"]}'
            if valid:
                assert not body['errors'], 'valid input has errors'
            if code:
                matching = [error for error in body['errors'] if error.get('code') == code]
                assert matching, f'missing error code {code}'
                assert all(type(error.get('line')) is int and error['line'] >= 0
                           and isinstance(error.get('message'), str) and error['message'].strip()
                           for error in body['errors']), 'errors need a line and useful message'
                if line is not None:
                    assert any(error['line'] == line for error in matching), 'wrong physical start line'
            after = path.read_bytes() if path.exists() else None
            assert before == after, 'input bytes were modified'

        cases = [
            ('valid-quoted', b'name,note\r\nAda,"one,two"\r\n', True, 1, None, None),
            ('utf8-bom', b'\xef\xbb\xbfname,value\nM\xc3\xbcnchen,1\n', True, 1, None, None),
            ('header-only', b'a,b\n', True, 0, None, None),
            ('multiline-width', b'a,b\n"first\nsecond",ok\nonly-one\n', False, 2, 'row-width', 4),
            ('duplicate-trim-case', b'id, ID \n1,2\n', False, None, 'duplicate-header', 1),
            ('empty-header-cell', b'a,,c\n1,2,3\n', False, None, 'empty-header', 1),
            ('empty-file', b'', False, None, 'empty-header', 1),
            ('missing-file', None, False, None, 'read-error', None),
            ('invalid-utf8', b'a,b\n\xff,2\n', False, None, 'read-error', None),
            ('whitespace-data', b'a,b\n , \n', True, 1, None, None),
        ]
        for params in cases:
            record(params[0], lambda params=params: case(*params))
    return {'passed': all(row['passed'] for row in outcomes), 'cases': outcomes,
            'entry_sha256': hashlib.sha256(entry.read_bytes()).hexdigest(),
            'scope': 'Independent public CLI cases on a supplied evaluation specification; no market-value claim.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = evaluate(args.project)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
