#!/usr/bin/env python3
"""Run trusted repository tests; JSON goes to stdout, diagnostics to stderr.

Redirect stdout to an ignored test-results file outside distribution folders.
CI supplies the job timeout; this in-process unittest runner is not a sandbox
or an independent timeout/output supervisor.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import unittest

from check_repo import ROOT, source_files


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.success_events = 0

    def addSuccess(self, test):
        self.success_events += 1
        super().addSuccess(test)


def source_digest(root=ROOT):
    root = Path(root).resolve()
    entries = [(p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
               for p in source_files(root)]
    return hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode('utf-8')).hexdigest()


def run_suite(suite, stream, fail_on_skip=False):
    started = time.monotonic()
    # Ordinary test prints must not corrupt the JSON stream. Tracebacks remain
    # in the diagnostic stream; the machine report includes identities only.
    with contextlib.redirect_stdout(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                        resultclass=RecordedResult).run(suite)
    skipped = [{'test': test.id(), 'reason': reason} for test, reason in result.skipped]
    passed = bool(result.testsRun and result.wasSuccessful() and not (fail_on_skip and skipped))
    omissions = bool(skipped or result.expectedFailures)
    return {'schema_version': 1, 'completed': True, 'passed': passed,
            'status': ('passed_with_omissions' if omissions else 'passed') if passed else 'failed',
            'tests_run': result.testsRun, 'success_events': result.success_events,
            'failures': [test.id() for test, _ in result.failures],
            'errors': [test.id() for test, _ in result.errors],
            'skipped': skipped,
            'expected_failures': [test.id() for test, _ in result.expectedFailures],
            'unexpected_successes': [test.id() for test in result.unexpectedSuccesses],
            'fail_on_skip': fail_on_skip, 'seconds': round(time.monotonic() - started, 3),
            'counting': 'unittest events; subtest failures/skips need not add up to tests_run',
            'scope': 'Trusted local repository tests, not live host, browser or hosted CI validation'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fail-on-skip', action='store_true', help='Make any skipped test event fail the run')
    args = parser.parse_args(argv)
    try:
        before = source_digest()
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tools/tests'))
        report = run_suite(suite, sys.stderr, args.fail_on_skip)
        after = source_digest()
        report.update(recorded_at_utc=datetime.now(timezone.utc).isoformat(),
                      python=platform.python_version(), platform=platform.system(),
                      source_sha256=after, source_unchanged=before == after)
        if before != after:
            report.update(passed=False, status='source_changed')
    except (OSError, ValueError) as exc:
        report = {'schema_version': 1, 'completed': False, 'passed': False,
                  'status': 'runner_error', 'error_type': type(exc).__name__}
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
