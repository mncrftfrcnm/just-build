#!/usr/bin/env python3
"""Run generated examples on disposable copies, with independent CLI checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'codex/just-build/scripts'))
from process_runner import run_command
from host_safety import checked_path
from evals.csv_intake import evaluate as evaluate_intake


def run(root=ROOT):
    root = Path(root)
    outcomes = []
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        for name in ('csv-intake-check', 'csv-preflight'):
            project = scratch / name
            shutil.copytree(root / 'examples' / name, project)
            outcomes.append(check_provenance(name, project))
            result = run_command([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                                 project, timeout=120)
            output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
            counts = re.findall(r'\bRan (\d+) tests? in ', output)
            count = int(counts[-1]) if counts else 0
            passed = (result.returncode == 0 and result.cleanup_complete and count > 0
                      and not result.timed_out and not result.output_limited
                      and not re.search(r'\bskipped=[1-9]\d*\b', output))
            outcomes.append({'name': name, 'check': 'project-tests', 'passed': passed, 'tests': count,
                             'exit_code': result.returncode, 'output_tail': output[-2000:] if not passed else ''})
            if name == 'csv-intake-check':
                observed = evaluate_intake(project)
                outcomes.append({'name': name, 'check': 'independent-public-paths', **observed})
            else:
                outcomes.append(check_preflight(project, scratch))
    return {'passed': all(row['passed'] for row in outcomes), 'results': outcomes,
            'scope': 'Generated local CLI examples, public subprocess checks; no live model/API calls.'}


def check_provenance(name, project):
    try:
        evidence = json.loads((project / 'verification.json').read_text(encoding='utf-8'))
        tracker = evidence['tracker_snapshot']
        valid = (tracker['complete'] is True and tracker['final_verification_ready'] is True
                 and tracker['security_ready'] is True)
        files = evidence['unchanged_files']
        paths = [row['path'] for row in files]
        valid = valid and 'app.py' in paths and len(set(paths)) == len(paths)
        for row in files:
            source = checked_path(row['path'], project)
            valid = valid and hashlib.sha256(source.read_bytes()).hexdigest() == row['sha256']
        return {'name': name, 'check': 'recorded-source-hashes', 'passed': bool(valid),
                'scope': 'Integrity of the published snapshot, not independent proof of the recorded trial.'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'name': name, 'check': 'recorded-source-hashes', 'passed': False, 'reason': str(exc)[:500]}


def check_preflight(project, scratch):
    entry = project / 'app.py'
    rows = []
    for name, data, valid, count, code, record, line in (
        ('valid', b'a,b\n1,2\n', True, 1, None, None, None),
        ('utf8-bom', b'\xef\xbb\xbfa,b\n1,2\n', True, 1, None, None, None),
        ('invalid', b'a,b\nonly-one\n', False, 1, 'row-width', 2, 2),
        ('malformed-header', b'"unterminated\n', False, 0, 'csv-syntax', 1, 1),
        ('multiline-location', b'a,b\n"first\nsecond",ok\nonly\n', False, 2, 'row-width', 3, 4),
    ):
        source = scratch / (name + '.csv')
        source.write_bytes(data)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = run_command([sys.executable, str(entry), str(source), '--json'], project, timeout=8)
        try:
            body = json.loads(result.stdout.decode('utf-8'))
            passed = (result.returncode == (0 if valid else 1) and result.cleanup_complete
                      and not result.timed_out and not result.output_limited and isinstance(body, dict)
                      and b'Traceback' not in result.stderr
                      and body.get('valid') is valid and body.get('data_rows') == count
                      and body.get('columns') == (0 if name == 'malformed-header' else 2)
                      and isinstance(body.get('issues'), list)
                      and hashlib.sha256(source.read_bytes()).hexdigest() == before)
            if code:
                passed = passed and any(issue.get('code') == code and issue.get('record') == record
                                        and issue.get('physical_line_end') == line for issue in body['issues'])
            else:
                passed = passed and body.get('issue_count') == 0 and not body['issues']
        except (ValueError, UnicodeError):
            passed = False
        rows.append({'name': name, 'passed': passed, 'exit_code': result.returncode})
    result = run_command([sys.executable, str(entry), '--help'], project, timeout=8)
    rows.append({'name': 'public-help', 'passed': result.returncode == 0 and result.cleanup_complete
                 and b'--report' in result.stdout and b'--delimiter' in result.stdout})
    source = scratch / 'encoding.csv'
    source.write_bytes(b'a,b\nCONFIDENTIAL_FIXTURE,\xff\n')
    result = run_command([sys.executable, str(entry), str(source), '--json'], project, timeout=8)
    rows.append({'name': 'invalid-encoding-no-cell-disclosure',
                 'passed': result.returncode == 2 and result.cleanup_complete
                 and b'UTF-8' in result.stderr and b'CONFIDENTIAL_FIXTURE' not in result.stdout + result.stderr
                 and source.read_bytes() == b'a,b\nCONFIDENTIAL_FIXTURE,\xff\n'})
    source.write_bytes(b'a,b\nCONFIDENTIAL_FIXTURE,2\n')
    report = scratch / 'report.json'
    result = run_command([sys.executable, str(entry), str(source), '--report', str(report)], project, timeout=8)
    report_bytes = report.read_bytes() if report.exists() else b''
    repeated = run_command([sys.executable, str(entry), str(source), '--report', str(report)], project, timeout=8)
    try:
        report_valid = json.loads(report_bytes).get('valid') is True
    except (ValueError, UnicodeError):
        report_valid = False
    rows.append({'name': 'exclusive-location-only-report',
                 'passed': result.returncode == 0 and repeated.returncode == 2
                 and result.cleanup_complete and repeated.cleanup_complete and report_valid
                 and b'CONFIDENTIAL_FIXTURE' not in report_bytes
                 and report.read_bytes() == report_bytes
                 and source.read_bytes() == b'a,b\nCONFIDENTIAL_FIXTURE,2\n'})
    return {'name': 'csv-preflight', 'check': 'independent-public-paths',
            'passed': all(row['passed'] for row in rows), 'cases': rows}


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Run evaluation without Python optimization flags so all assertions remain active.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = run()
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
