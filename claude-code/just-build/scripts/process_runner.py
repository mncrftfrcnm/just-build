#!/usr/bin/env python3
"""Bounded command supervision. No shell, disk log, or sandbox claim.

A trusted bootstrap waits for its supervisor before starting the selected
command. Windows uses a kill-on-close Job Object; POSIX uses a process group.
The command still has the host's file/network privileges. POSIX code can escape
a process group, and Windows services can start processes outside a Job Object;
use OS isolation for adversarial code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


# This branch runs with Python -I, before importing any local helper or project.
# The selected command is not present in argv and cannot start before the parent
# attaches Windows process containment and sends the bounded control message.
if __name__ == '__main__' and sys.argv[1:] == ['--child']:
    try:
        control = sys.stdin.buffer.readline(65537)
        if not control.endswith(b'\n') or len(control) > 65536:
            raise ValueError('invalid control message')
        command = json.loads(control)['argv']
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, shell=False)
        code = child.wait()
        raise SystemExit(code if code >= 0 else 128 - code)
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit(127)


import math
from pathlib import Path
import signal
import threading
import time
from dataclasses import dataclass
from host_safety import child_env


class ProcessSafetyError(ValueError):
    pass


def resolve_executable(name, cwd):
    """Resolve bare tools only from absolute PATH entries outside the project cwd.
    Explicit local executables remain supported. Windows batch files require an
    explicitly reviewed interpreter invocation rather than implicit shell parsing.
    """
    if not isinstance(name, str) or not name or '\x00' in name:
        raise ProcessSafetyError('invalid executable')
    path = Path(name)
    if path.suffix.lower() in ('.bat', '.cmd'):
        raise ProcessSafetyError('implicit batch execution is disabled; use a reviewed interpreter command')
    cwd = Path(cwd).resolve(strict=True)
    if path.is_absolute() or '/' in name or '\\' in name:
        target = path if path.is_absolute() else cwd / path
        target = target.resolve(strict=True)
        if target.suffix.lower() in ('.bat', '.cmd'):
            raise ProcessSafetyError('implicit batch execution is disabled')
        if not target.is_file():
            raise ProcessSafetyError('executable must be a regular file')
        return str(target)
    extensions = ('', '.exe', '.com') if os.name == 'nt' else ('',)
    for entry in os.get_exec_path():
        folder = Path(entry)
        if not entry or not folder.is_absolute():
            continue
        try:
            folder = folder.resolve(strict=True)
        except OSError:
            continue
        if folder == cwd or folder.is_relative_to(cwd):
            continue
        for extension in extensions:
            target = folder / (name + extension)
            if target.is_file() and os.access(target, os.X_OK):
                return str(target.resolve(strict=True))
    raise ProcessSafetyError('executable not found in an absolute host PATH outside the working directory')


class _WindowsJob:
    def __init__(self, pid):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                        ('min_working', c.c_size_t), ('max_working', c.c_size_t), ('active', w.DWORD),
                        ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', c.c_size_t),
                        ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]
        self.api = c.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.api.OpenProcess.restype = w.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ProcessSafetyError('Windows process containment could not be created')
        process = None
        try:
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
                raise ProcessSafetyError('Windows process containment could not be configured')
            process = self.api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
            if not process or not self.api.AssignProcessToJobObject(self.handle, process):
                raise ProcessSafetyError('Windows process containment unavailable; command was not started')
        except BaseException:
            self.close()
            raise
        finally:
            if process:
                self.api.CloseHandle(process)

    def close(self):
        if self.handle:
            if not self.api.CloseHandle(self.handle):
                raise ProcessSafetyError('Windows process containment could not be closed')
            self.handle = None


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    output_bytes: int
    timed_out: bool
    output_limited: bool
    cleanup_complete: bool


class ManagedProcess:
    def __init__(self, argv, cwd, timeout=120, max_output=2_000_000, extra_env=None):
        if (not isinstance(argv, (list, tuple)) or not 1 <= len(argv) <= 128
                or any(not isinstance(a, str) or '\x00' in a or len(a) > 2000 for a in argv)):
            raise ProcessSafetyError('command must be a bounded argv list')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 600:
            raise ProcessSafetyError('command timeout must be finite and within 600 seconds')
        if type(max_output) is not int or not 1 <= max_output <= 10_000_000:
            raise ProcessSafetyError('invalid output budget')
        command = [resolve_executable(argv[0], cwd), *argv[1:]]
        payload = json.dumps({'argv': command}, ensure_ascii=True).encode() + b'\n'
        if len(payload) > 65536:
            raise ProcessSafetyError('command control message exceeds its size limit')
        self._done, self._cancel, self._overflow = threading.Event(), threading.Event(), threading.Event()
        self._read_error = threading.Event()
        self._lock = threading.Lock()
        self._buffers, self._retained, self._observed = [bytearray(), bytearray()], 0, 0
        self._result, self._job = None, None
        self._timeout, self._max_output = timeout, max_output
        self._started = time.monotonic()
        self._proc = subprocess.Popen([sys.executable, '-I', '-u', str(Path(__file__).resolve()), '--child'],
                                      cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, bufsize=0, env=child_env(extra_env), shell=False,
                                      start_new_session=os.name != 'nt',
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            if os.name == 'nt':
                self._job = _WindowsJob(self._proc.pid)
            self._readers = [threading.Thread(target=self._read, args=(stream, index), daemon=True)
                             for index, stream in enumerate((self._proc.stdout, self._proc.stderr))]
            for reader in self._readers:
                reader.start()
            pending = memoryview(payload)
            while pending:
                written = self._proc.stdin.write(pending)
                if not written:
                    raise ProcessSafetyError('command control message could not be delivered')
                pending = pending[written:]
            self._proc.stdin.flush()
        except BaseException:
            if self._job:
                self._job.close()
            if self._proc.poll() is None:
                self._proc.kill()
            self._proc.wait(timeout=5)
            for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                stream.close()
            raise
        self._monitor = threading.Thread(target=self._supervise, daemon=True)
        self._monitor.start()

    def _read(self, stream, index):
        try:
            while chunk := stream.read(16384):
                with self._lock:
                    self._observed += len(chunk)
                    remaining = max(0, self._max_output - self._retained)
                    retained = chunk[:remaining]
                    self._buffers[index].extend(retained)
                    self._retained += len(retained)
                    if self._observed > self._max_output:
                        self._overflow.set()
        except (OSError, ValueError):
            self._read_error.set()

    def _supervise(self):
        timed_out = cleanup = False
        code = 125
        try:
            while self._proc.poll() is None:
                if self._cancel.is_set() or self._overflow.is_set():
                    break
                if time.monotonic() - self._started >= self._timeout:
                    timed_out = True
                    break
                self._cancel.wait(.01)
            if self._job:
                self._job.close()  # Also stops descendants after a successful parent exit.
            else:
                try:
                    os.killpg(self._proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            code = self._proc.wait(timeout=5)
            for reader in self._readers:
                reader.join(timeout=2)
            cleanup = not any(reader.is_alive() for reader in self._readers) and not self._read_error.is_set()
        except (OSError, ProcessSafetyError, subprocess.SubprocessError):
            if self._proc.poll() is None:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=2)
                except subprocess.SubprocessError:
                    pass
        finally:
            if timed_out:
                code = 124
            elif self._overflow.is_set():
                code = 87
            elif self._cancel.is_set() or not cleanup:
                code = 125
            for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                if cleanup or stream is self._proc.stdin:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        code, cleanup = 125, False
            self._result = CommandResult(code, bytes(self._buffers[0]), bytes(self._buffers[1]),
                                         self._observed, timed_out, self._overflow.is_set(), cleanup)
            self._done.set()

    def poll(self):
        return self._result.returncode if self._done.is_set() else None

    @property
    def output_limited(self):
        return self._overflow.is_set()

    def wait(self):
        self._done.wait()
        self._monitor.join(timeout=1)
        return self._result

    def close(self):
        self._cancel.set()
        return self.wait()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if not self.close().cleanup_complete:
            raise ProcessSafetyError('command cleanup was incomplete; execution cannot count as passing')


def run_command(argv, cwd, timeout=120, max_output=2_000_000, extra_env=None):
    with ManagedProcess(argv, cwd, timeout, max_output, extra_env) as process:
        return process.wait()
