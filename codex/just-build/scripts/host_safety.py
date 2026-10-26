"""Portable file checks and a minimal subprocess environment. Not a sandbox."""
from __future__ import annotations

import os
import stat
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath

ENV_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "TEMP", "TMP", "TMPDIR",
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL", "LC_CTYPE",
            "SYSTEMDRIVE", "NUMBER_OF_PROCESSORS"}
RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {f"{p}{n}" for p in ("com", "lpt") for n in '123456789\u00b9\u00b2\u00b3'}


def is_link(path):
    path = Path(path)
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    if os.name == 'nt':
        try:
            return bool(getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except FileNotFoundError:
            return False
    return False


def safe_relative(value):
    if (not isinstance(value, str) or not value or len(value) > 180
            or any(c in value for c in '\\:*?"<>|') or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("path must be a bounded relative POSIX path")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if posix.is_absolute() or windows.drive or windows.root:
        raise ValueError("absolute paths are forbidden")
    for part in value.split("/"):
        if part in ("", ".", "..") or part.startswith("~") or part.endswith((" ", ".")) or part.split(".")[0].rstrip(' .').casefold() in RESERVED:
            raise ValueError("unsafe or reserved path component")
    return posix


def child_env(extra=None):
    """Do not automatically pass API keys, auth tokens or interpreter hooks to tests.

    Programs still have host file/network privileges. HOME is kept for runtime
    compatibility; an OS sandbox is required to protect files or block egress.
    """
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_KEYS}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONUTF8="1")
    if extra:
        env.update(extra)
    return env


def checked_path(path, root, must_exist=True):
    """Reject linked components inside an explicitly selected scope, even if a
    link resolves back inside it. Pin the selected root once; host path aliases
    above that root are not treated as project content.
    """
    selected = Path(root).expanduser().absolute()
    if is_link(selected):
        raise ValueError('scope root cannot be linked')
    root = selected.resolve(strict=True)
    path = Path(path).expanduser()
    path = path.absolute() if path.is_absolute() else root / path
    try:
        parts = path.relative_to(selected).parts if path.is_relative_to(selected) else path.relative_to(root).parts
    except ValueError as exc:
        raise ValueError('path is outside the selected scope') from exc
    current = root
    for part in parts:
        if part in ('.', '..'):
            raise ValueError('relative traversal is forbidden')
        current = current / part
        if is_link(current):
            raise ValueError('linked path components are forbidden')
    resolved = current.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise ValueError('path escapes the selected scope')
    return resolved


def regular_bytes(path, maximum=2_000_000, root=None, reject_hardlinks=False):
    """Bound reads by the opened handle, not just a prior path size check.
    Nonblocking open prevents a substituted FIFO from hanging a local audit.
    This does not replace isolation from a concurrent hostile filesystem writer.
    """
    path = checked_path(Path(path).expanduser().absolute(), root) if root is not None else Path(path).expanduser()
    if is_link(path):
        raise ValueError('linked input is forbidden')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('input must be a regular file')
        if reject_hardlinks and info.st_nlink > 1:
            raise ValueError('hard-linked scratch artifacts are forbidden')
        if info.st_size > maximum:
            raise ValueError('input exceeds its size limit')
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise ValueError('input grew beyond its size limit')
    finally:
        os.close(descriptor)


def regular_text(path, maximum=2_000_000, root=None):
    return regular_bytes(path, maximum, root).decode('utf-8')


def bounded_json(path, maximum=2_000_000, root=None):
    text = regular_text(path, maximum, root)
    depth, quoted, escaped = 0, False, False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in '[{':
            depth += 1
            if depth > 100:
                raise ValueError('JSON nesting exceeds the 100-level limit')
        elif character in ']}':
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON keys are forbidden')
            result[key] = value
        return result

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite JSON numbers are forbidden')
        return number

    def constant(_):
        raise ValueError('nonfinite JSON numbers are forbidden')

    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_float=finite, parse_constant=constant)
    except RecursionError as exc:
        raise ValueError('JSON nesting exceeds the parser limit') from exc


def walk_regular(root, skip=(), max_files=1000, max_dirs=2000):
    """A bounded walk that never silently treats inaccessible content as clean."""
    root = Path(root)
    if is_link(root):
        raise ValueError('linked project roots are forbidden')
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('scope root must be a directory')

    def denied(error):
        raise ValueError('cannot enumerate project content; audit is incomplete') from error

    count = folders = 0
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=denied):
        folders += 1
        if folders > max_dirs:
            raise ValueError('project directory count exceeds the inspection limit')
        dirs[:] = sorted(name for name in dirs if name not in skip)
        for name in dirs:
            if is_link(Path(base) / name):
                raise ValueError('linked project content is forbidden')
        for name in sorted(files):
            if name in skip:
                continue
            path = Path(base) / name
            if is_link(path) or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError('project content must be regular and unlinked')
            count += 1
            if count > max_files:
                raise ValueError('project file count exceeds the inspection limit')
            yield path
