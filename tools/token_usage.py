#!/usr/bin/env python3
"""Summarize explicit, private Codex ``exec --json`` JSONL files locally.

Only documented turn.completed usage is counted. No discovery, transcript
output, pricing, network access, or account/session lookup is performed. Supply
disjoint logs for the project yourself; this cannot establish project coverage.
Close writers first: filesystem checks detect ordinary changes, but this tool
is not a sandbox against concurrent filesystem replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

MAX_FILES = 32
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_RECORDS = 100_000
MAX_JSON_DEPTH = 64
MAX_COUNTER = (1 << 63) - 1
EVENT_TYPES = {'thread.started', 'turn.started', 'turn.completed', 'turn.failed',
               'item.started', 'item.updated', 'item.completed', 'error'}
COUNTERS = ('input_tokens', 'cached_input_tokens', 'output_tokens')
USAGE_FIELDS = (*COUNTERS, 'uncached_input_tokens', 'input_plus_output_tokens',
                'reasoning_output_tokens')


class UsageError(ValueError):
    """A safe diagnostic containing no source paths or transcript content."""


def _local_path(path):
    raw = os.fspath(path)
    path = Path(path)
    if ('\x00' in raw or raw.replace('\\', '/').startswith('//')
            or (path.drive and not path.root)
            or any(':' in part for part in path.parts if part != path.anchor)):
        raise UsageError('remote, device, alternate-stream, or invalid paths are not allowed')
    return Path(os.path.abspath(path))


def _plain(path, *, directory=False):
    """Reject linked/reparse ancestors, hard links, and nonregular inputs."""
    path = _local_path(path)
    for component in (*reversed(path.parents), path):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise UsageError('linked or reparse paths are not allowed')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise UsageError('hard-linked files are not allowed')
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise UsageError('a path ancestor is not a directory')
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise UsageError('expected a plain directory' if directory else 'expected a regular file')
    return path, info


def _identity(info):
    return info.st_dev, info.st_ino


def _snapshot(info):
    # Windows lstat/fstat can disagree on ctime (creation vs change time).
    return (*_identity(info), info.st_size, info.st_mtime_ns, info.st_nlink, info.st_mode)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UsageError('duplicate JSON object key')
        result[key] = value
    return result


def _constant(value):
    raise UsageError('nonfinite JSON number')


def _decode(line):
    text = line.decode('utf-8')
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise UsageError('JSON nesting limit exceeded')
        elif char in ']}':
            depth -= 1
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)


def _usage(value):
    if not isinstance(value, dict) or any(key not in value for key in COUNTERS):
        raise UsageError('usage must contain all three documented counters')
    for key in (*COUNTERS, 'reasoning_output_tokens'):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= MAX_COUNTER):
            raise UsageError('usage counters must be bounded nonnegative integers')
    if value['cached_input_tokens'] > value['input_tokens']:
        raise UsageError('cached input exceeds input tokens')
    if value.get('reasoning_output_tokens', 0) > value['output_tokens']:
        raise UsageError('reasoning output exceeds output tokens')
    result = {key: value[key] for key in COUNTERS}
    result['uncached_input_tokens'] = value['input_tokens'] - value['cached_input_tokens']
    result['input_plus_output_tokens'] = value['input_tokens'] + value['output_tokens']
    result['reasoning_output_tokens'] = value.get('reasoning_output_tokens')
    return result


def _empty():
    return {'records': 0, 'started_turns': 0, 'completed_turns': 0,
            'completed_turns_with_usage': 0, 'completed_turns_without_usage': 0,
            'reasoning_turns_reported': 0, 'failed_turns': 0,
            'unfinished_turns': 0, 'error_events': 0,
            'reported_usage': dict.fromkeys(USAGE_FIELDS)}


def _add_usage(target, usage):
    for key, value in usage.items():
        if value is not None:
            target[key] = (target[key] or 0) + value


def _status(counts):
    if not counts['completed_turns_with_usage']:
        return 'unknown'
    if any(counts[key] for key in ('completed_turns_without_usage', 'failed_turns',
                                  'unfinished_turns', 'error_events')):
        return 'partial'
    return 'complete'


def _read(path, before, budget):
    result = _empty()
    digest = hashlib.sha256()
    size = 0
    opened_turn = False
    thread_started = False
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as source:
        opened = os.fstat(source.fileno())
        if _snapshot(opened) != _snapshot(before) or not stat.S_ISREG(opened.st_mode):
            raise UsageError('input changed before reading')
        while True:
            line = source.readline(MAX_RECORD_BYTES + 1)
            if not line:
                break
            size += len(line)
            budget['bytes'] += len(line)
            result['records'] += 1
            budget['records'] += 1
            number = result['records']
            if size > MAX_FILE_BYTES or budget['bytes'] > MAX_TOTAL_BYTES:
                raise UsageError('input byte limit exceeded')
            if len(line) > MAX_RECORD_BYTES or budget['records'] > MAX_RECORDS:
                raise UsageError('record size or count limit exceeded')
            digest.update(line)
            try:
                event = _decode(line)
            except (ValueError, UnicodeError, RecursionError):
                raise UsageError(f'record {number}: invalid JSON, duplicate key, or nesting limit') from None
            if (not isinstance(event, dict) or not isinstance(event.get('type'), str)
                    or event['type'] not in EVENT_TYPES):
                raise UsageError(f'record {number}: unsupported Codex exec event')
            kind = event['type']
            if kind == 'thread.started':
                if thread_started or result['started_turns']:
                    raise UsageError(f'record {number}: duplicate or misplaced thread start')
                thread_started = True
            elif kind == 'turn.started':
                if opened_turn:
                    raise UsageError(f'record {number}: overlapping or duplicate turn start')
                opened_turn = True
                result['started_turns'] += 1
            elif kind in ('turn.completed', 'turn.failed'):
                if not opened_turn:
                    raise UsageError(f'record {number}: terminal event without an open turn')
                opened_turn = False
                if kind == 'turn.failed':
                    result['failed_turns'] += 1
                    continue
                result['completed_turns'] += 1
                if event.get('usage') is None:
                    result['completed_turns_without_usage'] += 1
                    continue
                try:
                    usage = _usage(event['usage'])
                except UsageError as exc:
                    raise UsageError(f'record {number}: {exc}') from None
                result['completed_turns_with_usage'] += 1
                if usage['reasoning_output_tokens'] is not None:
                    result['reasoning_turns_reported'] += 1
                _add_usage(result['reported_usage'], usage)
            elif kind == 'error':
                result['error_events'] += 1
        after = os.fstat(source.fileno())
    _, current = _plain(path)
    if size != before.st_size or _snapshot(before) != _snapshot(after) or _snapshot(before) != _snapshot(current):
        raise UsageError('input changed while reading')
    result['unfinished_turns'] = int(opened_turn)
    result['status'] = _status(result)
    return {'sha256': digest.hexdigest(), 'bytes': size, **result}


def summarize(paths):
    """Return path-free reported usage; all inputs must validate before return.

    Identical files are rejected to avoid accidental double counting. Equal
    counters on distinct turns are legitimate and are counted separately.
    ``complete`` describes supplied logs only, never all work on a project.
    """
    prepared = []
    aliases = set()
    identities = set()
    declared_bytes = 0
    for number, path in enumerate(paths, 1):
        if number > MAX_FILES:
            raise UsageError('input file count limit exceeded')
        try:
            path, info = _plain(path)
            alias = os.path.normcase(str(path))
            identity = _identity(info)
            if alias in aliases or (info.st_ino and identity in identities):
                raise UsageError('duplicate input file')
            aliases.add(alias)
            identities.add(identity)
            declared_bytes += info.st_size
            if info.st_size > MAX_FILE_BYTES or declared_bytes > MAX_TOTAL_BYTES:
                raise UsageError('input byte limit exceeded')
            prepared.append((path, info))
        except (OSError, UsageError) as exc:
            detail = str(exc) if isinstance(exc, UsageError) else 'cannot inspect input'
            raise UsageError(f'input {number}: {detail}') from None
    if not prepared:
        raise UsageError('at least one explicit input file is required')
    budget = {'bytes': 0, 'records': 0}
    sources = []
    hashes = set()
    for number, (path, info) in enumerate(prepared, 1):
        try:
            source = _read(path, info, budget)
            if source['sha256'] in hashes:
                raise UsageError('duplicate input content')
            hashes.add(source['sha256'])
            sources.append(source)
        except (OSError, UsageError) as exc:
            detail = str(exc) if isinstance(exc, UsageError) else 'cannot read input'
            raise UsageError(f'input {number}: {detail}') from None
    total = _empty()
    for source in sources:
        for key in total.keys() - {'reported_usage'}:
            total[key] += source[key]
        _add_usage(total['reported_usage'], source['reported_usage'])
    usage = total.pop('reported_usage')
    # An empty or unrelated-event-only source has unknown coverage even when
    # another supplied source contains complete usage.
    status = _status(total)
    if status == 'complete' and any(source['status'] != 'complete' for source in sources):
        status = 'partial'
    return {
        'schema_version': 1,
        'source_format': 'codex-exec-jsonl',
        'scope': 'Only explicit supplied files; not a verified project or account total',
        'coverage': {'status': status, 'input_files': len(sources), **total},
        'reported_usage': usage,
        'accounting': {
            'basis': 'Sum of turn.completed usage only; null means unreported, not zero',
            'cached_input_tokens': 'Subset of input_tokens; never added to input_plus_output_tokens',
            'reasoning_output_tokens': 'Optional subset of output_tokens; never added to input_plus_output_tokens',
            'unknown_usage': 'Missing usage and failed/unfinished turns are not estimated',
        },
        'sources': sources,
    }


def write_report(path, report):
    """Create a new report exclusively; preserve all existing files and sources."""
    path = _local_path(path)
    try:
        _plain(path.parent, directory=True)
        data = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode('utf-8')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    except OSError:
        raise UsageError('cannot create report exclusively; use a new file in an existing plain directory') from None
    created = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        try:
            if _identity(path.lstat()) == _identity(created):
                path.unlink()
        except OSError:
            pass
        raise UsageError('report write failed; no complete report was produced') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path, help='Explicit private Codex exec --json JSONL files; no discovery')
    parser.add_argument('--output', type=Path, help='Create this new JSON file exclusively; parent must already exist')
    args = parser.parse_args(argv)
    report_file_produced = False
    try:
        report = summarize(args.inputs)
        if args.output is not None:
            write_report(args.output, report)
            report_file_produced = True
        print(json.dumps(report, indent=2, sort_keys=True))
    except (UsageError, OSError) as exc:
        detail = str(exc) if isinstance(exc, UsageError) else 'I/O failed'
        print(json.dumps({'error': detail, 'report_produced': report_file_produced}), file=sys.stderr)
        return 2
    return 0 if report['coverage']['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
