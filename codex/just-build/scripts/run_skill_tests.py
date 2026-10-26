#!/usr/bin/env python3
"""Run helper regressions and existing fixture suites without third-party packages."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
import time
import os
import tempfile

from host_safety import is_link, regular_bytes, walk_regular
from process_runner import run_command, ProcessSafetyError


def source_digest(root):
    entries = [(p.relative_to(root).as_posix(), hashlib.sha256(regular_bytes(p, root=root)).hexdigest())
               for p in walk_regular(root, {'__pycache__'}, max_files=2000, max_dirs=4000) if p.suffix != '.pyc']
    return hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', help='Optional JSON report file outside the skill folder')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    report_path = Path(args.report).expanduser().absolute() if args.report else None
    if report_path and (is_link(report_path) or is_link(report_path.parent)):
        parser.error('report path must not be linked')
    report_path = report_path.resolve() if report_path else None
    if report_path and report_path.is_relative_to(root):
        parser.error('store reports outside the tested skill folder')
    before = source_digest(root)
    suites = []
    for name, cwd in (('helpers', root), ('cli-fixture', root / 'examples/sample-task-board'),
                      ('api-fixture', root / 'examples/security/sample-api')):
        started = time.monotonic()
        try:
            # The helper suite includes full lifecycle regressions. Keep a bounded
            # batch budget as coverage grows; application-command limits are separate.
            proc = run_command([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd,
                               timeout=600 if name == 'helpers' else 60)
            output = (proc.stdout + proc.stderr).decode('utf-8', errors='replace')
            sys.stderr.write(output)
            counts = re.findall(r'\bRan (\d+) tests? in ', output)
            count = int(counts[-1]) if counts else 0
            skip_match = re.search(r'\bskipped=(\d+)', output)
            skipped = int(skip_match.group(1)) if skip_match else 0
            suites.append({'suite': name, 'tests': count, 'skipped': skipped, 'exit_code': proc.returncode,
                           'passed': proc.returncode == 0 and count > 0 and skipped == 0 and proc.cleanup_complete,
                           'timeout': proc.timed_out, 'output_limited': proc.output_limited,
                           'seconds': round(time.monotonic() - started, 3)})
        except (OSError, ProcessSafetyError) as exc:
            suites.append({'suite': name, 'tests': 0, 'skipped': 0, 'passed': False, 'error': type(exc).__name__})
    after = source_digest(root)
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
              'platform': platform.system(), 'source_sha256': after, 'source_unchanged': before == after,
              'suites': suites, 'total_tests': sum(row['tests'] for row in suites),
              'passed': before == after and all(row['passed'] for row in suites),
              'scope': 'Local deterministic helpers, synthetic research, CLI and loopback API fixtures. No live market or end-to-end model-agent evaluation.'}
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        if is_link(report_path):
            raise ValueError('refusing a linked report destination')
        fd, temporary = tempfile.mkstemp(dir=report_path.parent, prefix='.test-report-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(json.dumps(report, indent=2) + '\n')
            os.replace(temporary, report_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
