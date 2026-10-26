#!/usr/bin/env python3
"""Check shared host files; --apply copies Codex files without deleting extras.

Only the two just-build packages are traversed. Standard Python/tool caches are
ignored, while credentials, local agent configuration and run ledgers are
rejected. Links are rejected before traversal; cache contents are not traversed.
This is a local contributor tool, not a sandbox against concurrent filesystem
replacement by another process. Close tools that edit these files while syncing.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from check_repo import HOST_SPECIFIC, ROOT, linked

HOST_SPECIFIC_CANONICAL = {name.casefold(): name for name in HOST_SPECIFIC}
MAX_FILE_BYTES = 8_000_000
MAX_TOTAL_BYTES = 32_000_000
MAX_FILES = 2048
MAX_ENTRIES = 8192
MAX_DEPTH = 32
CACHE_DIRS = {'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
PRIVATE_DIRS = {'.git', '.codex', '.claude', '.agents', '.aws', '.ssh',
                '.just-build', '.venv', 'venv', 'node_modules'}
PRIVATE_FILES = {'credentials', 'credentials.json', 'token.json', '.netrc',
                 '.npmrc', '.pypirc', '.coverage'}


def _plain(path, *, directory=None, missing=False):
    """Inspect each lexical component without resolving a linked component."""
    path = Path(os.path.abspath(path))
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if missing:
                return path
            raise ValueError(f'Missing required path: {component}') from None
        if linked(component):
            raise ValueError(f'Linked path is not allowed: {component}')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise ValueError(f'Hard-linked file is not allowed: {component}')
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f'Non-directory path component: {component}')
    if directory is True and not stat.S_ISDIR(info.st_mode):
        raise ValueError(f'Expected directory: {path}')
    if directory is False and not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Expected regular file: {path}')
    return path


def _read(path, budget):
    _plain(path, directory=False)
    before = path.stat()
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError(f'File exceeds {MAX_FILE_BYTES} byte limit: {path}')
    with path.open('rb') as source:
        value = source.read(MAX_FILE_BYTES + 1)
    after = path.stat()
    if (len(value) > MAX_FILE_BYTES or len(value) != before.st_size
            or (before.st_size, before.st_mtime_ns, before.st_ino)
            != (after.st_size, after.st_mtime_ns, after.st_ino)):
        raise ValueError(f'File changed while reading or exceeds limit: {path}')
    budget['bytes'] += len(value)
    budget['files'] += 1
    if budget['bytes'] > MAX_TOTAL_BYTES or budget['files'] > MAX_FILES:
        raise ValueError('Host packages exceed sync file/byte limits')
    return value


def _root(root):
    root = _plain(root, directory=True)
    _plain(root / 'README.md', directory=False)
    for host in ('codex', 'claude-code'):
        package = _plain(root / host / 'just-build', directory=True)
        for name in ('SKILL.md', 'references/host.md'):
            _plain(package / name, directory=False)
    _plain(root / 'codex/just-build/agents/openai.yaml', directory=False)
    return root


def _packages(root):
    budget = {'files': 0, 'bytes': 0, 'entries': 0}
    tables = []
    aliases = {}
    for host in ('codex', 'claude-code'):
        package = root / host / 'just-build'
        table = {}
        names = set()

        def visit(path, depth=0):
            if depth > MAX_DEPTH:
                raise ValueError('Host package exceeds sync directory depth limit')
            _plain(path)
            budget['entries'] += 1
            if budget['entries'] > MAX_ENTRIES:
                raise ValueError('Host packages exceed sync entry limit')
            rel = path.relative_to(package).as_posix()
            folded = rel.casefold()
            host_specific = HOST_SPECIFIC_CANONICAL.get(folded)
            if host_specific is not None and rel != host_specific:
                raise ValueError(f'Noncanonical host-specific path spelling: {rel}; expected {host_specific}')
            if folded in names:
                raise ValueError(f'Case-colliding package paths: {rel}')
            names.add(folded)
            if rel not in HOST_SPECIFIC:
                existing = aliases.setdefault(folded, rel)
                if existing != rel:
                    raise ValueError(f'Cross-host case-colliding paths: {existing}, {rel}')
            name = path.name.lower()
            if path.is_dir():
                if name in PRIVATE_DIRS:
                    raise ValueError(f'Private or local-state directory in host package: {rel}')
                if name in CACHE_DIRS:
                    return
                # Bound enumeration before sorting, including directories and ignored entries.
                children = []
                for child in path.iterdir():
                    if len(children) + budget['entries'] >= MAX_ENTRIES:
                        raise ValueError('Host packages exceed sync entry limit')
                    children.append(child)
                for child in sorted(children):
                    visit(child, depth + 1)
                return
            if not path.is_file():
                raise ValueError(f'Non-regular package path: {rel}')
            if name.endswith(('.pyc', '.pyo')):
                return
            if (name in PRIVATE_FILES or name == '.env'
                    or (name.startswith('.env.') and name != '.env.example')
                    or path.suffix.lower() in {'.pem', '.key'}):
                raise ValueError(f'Private configuration in host package: {rel}')
            value = _read(path, budget)
            text = value.decode('utf-8')
            if re.search(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----', text):
                raise ValueError(f'Private key material in host package: {rel}')
            table[rel] = value

        visit(package)
        tables.append(table)
    return tables


def _difference(tables):
    source, destination = tables
    canonical = set(source) - HOST_SPECIFIC
    target = set(destination) - HOST_SPECIFIC
    return {
        'changed': sorted(name for name in canonical & target if source[name] != destination[name]),
        'missing': sorted(canonical - target),
        'unexpected': sorted(target - canonical),
    }


def synchronize(root=ROOT, *, apply=False):
    """Return a JSON-ready report, raising on unsafe input before any writes.

    Codex is canonical. Host-specific files are preserved byte-for-byte. Extra
    Claude shared files require manual resolution and always leave in_sync false.
    Every input is preflighted before --apply writes anything. Each replacement
    is atomic; the complete batch is not a filesystem transaction.
    """
    root = _root(root)
    tables = _packages(root)
    differences = _difference(tables)
    changes = sorted(differences['changed'] + differences['missing'])
    destination = root / 'claude-code/just-build'
    # A missing file may conceal a conflicting directory or a non-directory
    # ancestor. Reject every such target before repairing any earlier file.
    for name in changes:
        _plain(destination / name, directory=False, missing=True)
    projected = dict(tables[1])
    projected.update({name: tables[0][name] for name in changes})
    if (len(tables[0]) + len(projected) > MAX_FILES
            or sum(map(len, tables[0].values())) + sum(map(len, projected.values())) > MAX_TOTAL_BYTES):
        raise ValueError('Sync result would exceed file/byte limits')
    applied = []
    if apply and changes:
        # Repeat the complete preflight immediately before creating directories.
        if _packages(root) != tables:
            raise ValueError('Host packages changed during sync preflight; retry')
        for name in changes:
            target = destination / name
            _plain(target, missing=True)
            parent = target.parent
            absent = []
            while not parent.exists():
                absent.append(parent)
                parent = parent.parent
            _plain(parent, directory=True)
            for directory in reversed(absent):
                directory.mkdir()
                _plain(directory, directory=True)
            descriptor, temporary = tempfile.mkstemp(prefix='.sync-hosts-', suffix='.tmp', dir=target.parent)
            temporary = Path(temporary)
            try:
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(tables[0][name])
                    output.flush()
                    os.fsync(output.fileno())
                _plain(target, missing=True)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            applied.append(name)
        differences = _difference(_packages(root))
    return {'in_sync': not any(differences.values()),
            'mode': 'apply' if apply else 'check', 'applied': applied,
            **differences,
            'canonical': 'codex/just-build',
            'destination': 'claude-code/just-build',
            'unexpected_policy': 'Manual resolution required; no files are deleted'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Repository root (default: this checkout)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Read-only check (the default)')
    mode.add_argument('--apply', action='store_true', help='Copy changed/missing shared Codex files to Claude')
    args = parser.parse_args(argv)
    try:
        result = synchronize(args.root, apply=args.apply)
    except (OSError, ValueError) as exc:
        print(json.dumps({'in_sync': False, 'error': str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['in_sync'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
