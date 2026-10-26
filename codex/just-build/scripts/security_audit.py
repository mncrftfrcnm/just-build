#!/usr/bin/env python3
"""Read-only, bounded local source heuristics. Not a vulnerability scanner or pentest."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path
import re
from host_safety import is_link, regular_bytes, walk_regular

SKIP = {'.git', '.just-build', '.just-build-runs', '.venv', 'venv', 'node_modules', 'dist', 'build', '__pycache__', 'coverage', 'tests', 'fixtures'}
SOURCE = {'.py', '.js', '.jsx', '.ts', '.tsx'}
MAX_FILES = 1000
MAX_BYTES = 256_000
SECRET_NAME = re.compile(r'(api[_-]?key|client[_-]?secret|access[_-]?token|private[_-]?key|password|secret[_-]?key)', re.I)
PLACEHOLDER = re.compile(r'^(?:test|example|demo|fake|changeme|placeholder|your[_-]|xxx|none|dummy)', re.I)


def scan(root):
    if is_link(root):
        raise ValueError('security scan refuses linked project roots')
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('security scan root must be a directory')
    findings, count = [], 0

    def add(path, line, code, severity, description, remediation):
        rel = path.relative_to(root).as_posix()
        key = f'{rel}:{line}:{code}'
        findings.append({'id': hashlib.sha256(key.encode()).hexdigest()[:14], 'path': rel, 'line': line,
                         'code': code, 'severity': severity, 'description': description, 'remediation': remediation})

    for path in walk_regular(root, SKIP, max_files=MAX_FILES):
        rel = path.relative_to(root)
        if any(p in SKIP for p in rel.parts):
            continue
        if is_link(path):
            raise ValueError('security scan refuses symlinked project content')
        if not path.is_file():
            continue
        count += 1
        if count > MAX_FILES:
            raise ValueError('security scan file limit exceeded; review scope manually')
        if path.name in ('.env', '.env.production', '.env.local'):
            add(path, 1, 'environment-file', 'major', 'Environment settings file is present; assess whether it contains secrets and is tracked.', 'Move secrets to a secure store and exclude local environment files from publishing.')
        if path.suffix not in SOURCE:
            continue
        if path.stat().st_size > MAX_BYTES:
            add(path, 1, 'oversized-source', 'major', 'Source exceeds scanner size bound; content was not inspected.', 'Manually inspect and refactor or scope this source before issuing a passing audit.')
            continue
        content = regular_bytes(path, MAX_BYTES, root=root).decode('utf-8', errors='replace')
        if path.suffix == '.py':
            try:
                tree = ast.parse(content)
            except (SyntaxError, RecursionError, ValueError):
                add(path, 1, 'unparseable-python', 'major', 'Python source could not be parsed; the static review is incomplete.', 'Correct or simplify this source, then rescan before passing the security gate.')
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    try:
                        fn = ast.unparse(node.func) if hasattr(ast, 'unparse') else ''
                    except RecursionError:
                        add(path, node.lineno, 'uninspectable-call', 'major', 'A call expression exceeds the static inspection depth.', 'Simplify or manually review this call before passing the security gate.')
                        continue
                    if fn in ('eval', 'exec'):
                        add(path, node.lineno, 'dynamic-execution', 'major', 'Dynamic code execution requires an explicit trust boundary.', 'Remove dynamic execution or use a constrained parser.')
                    if fn in ('pickle.loads', 'pickle.load'):
                        add(path, node.lineno, 'pickle-deserialization', 'major', 'Pickle deserialization may execute code when fed untrusted data.', 'Use a safe data format for untrusted input.')
                    if fn in ('subprocess.run', 'subprocess.call', 'subprocess.Popen', 'subprocess.check_output', 'subprocess.check_call'):
                        if any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                            add(path, node.lineno, 'shell-execution', 'major', 'Shell-enabled subprocess call needs injection review.', 'Use an argument array and shell=False where possible.')
                    if fn.endswith('.run') and any(k.arg == 'debug' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                        add(path, node.lineno, 'debug-enabled', 'major', 'A server may run with debug mode enabled.', 'Disable debug mode for deployed services.')
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    val = node.value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        for target in targets:
                            name = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else ''
                            if SECRET_NAME.search(name) and len(val.value) >= 12 and not PLACEHOLDER.search(val.value):
                                add(path, node.lineno, 'literal-credential', 'major', 'Credential-like string assigned directly in source (value redacted).', 'Use a secret store or environment configuration; rotate exposed credentials.')
        else:
            for number, line in enumerate(content.splitlines(), 1):
                if re.search(r'\b(?:eval)\s*\(', line) or re.search(r'\bnew\s+Function\s*\(', line):
                    add(path, number, 'dynamic-execution', 'major', 'Dynamic script execution requires input trust review.', 'Avoid evaluating user-controlled script text.')
                if re.search(r'\bdebug\s*:\s*true\b', line, re.I):
                    add(path, number, 'debug-enabled', 'minor', 'Debug flag may expose additional diagnostic information.', 'Confirm production configuration is safe.')
    return {'kind': 'read-only-static-heuristic', 'scanned_files': count, 'findings': findings,
            'limitations': 'Heuristics miss many vulnerabilities and may yield false positives. No dependencies installed, network accessed, or active probes executed.'}
