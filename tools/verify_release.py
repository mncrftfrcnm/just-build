#!/usr/bin/env python3
"""Verify local release artifacts against a trusted checkout, without extracting or executing."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import zipfile
import zlib

from check_repo import ROOT, HOSTS, check, linked, source_files

# Bound compressed input and declared expansion before reading any member payload.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_CENTRAL_DIRECTORY_BYTES = 4 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_archive_name(info):
    name = info.filename
    parts = name.split('/')
    if (info.orig_filename != name or not name or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in parts)
            or any(ord(char) < 32 for char in name) or info.is_dir()):
        raise ValueError(f'Unsafe archive path: {name!r}')
    mode = (info.external_attr >> 16) & 0xffff
    if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or info.external_attr & (0x10 | 0x400):
        raise ValueError(f'Linked or non-regular archive entry: {name}')
    if info.flag_bits & 1:
        raise ValueError(f'Encrypted archive entry: {name}')
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ValueError(f'Unsupported archive compression: {name}')
    return name


def check_zip_envelope(path):
    """Bound even the central-directory allocation before ZipFile parses it."""
    size = path.stat().st_size
    with path.open('rb') as stream:
        stream.seek(max(0, size - (65535 + 22)))
        tail = stream.read(65535 + 22)
    offset = tail.rfind(b'PK\x05\x06')
    if offset < 0 or len(tail) - offset < 22:
        raise ValueError(f'Invalid release archive: {path.name}: missing ZIP end record')
    _, disk, directory_disk, disk_count, count, directory_size, directory_offset, comment = struct.unpack_from(
        '<4s4H2LH', tail, offset)
    if disk or directory_disk or disk_count != count:
        raise ValueError(f'Invalid release archive: {path.name}: multi-disk ZIP is unsupported')
    if count == 65535 or directory_size == 0xffffffff or directory_offset == 0xffffffff:
        raise ValueError(f'Invalid release archive: {path.name}: ZIP64 is unnecessary for bounded releases')
    if count > MAX_MEMBERS:
        raise ValueError(f'Archive has too many entries: {path.name}')
    if directory_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise ValueError(f'Archive central directory exceeds size limit: {path.name}')
    absolute_end = size - len(tail) + offset
    if offset + 22 + comment != len(tail) or directory_offset + directory_size != absolute_end:
        raise ValueError(f'Invalid release archive: {path.name}: inconsistent ZIP envelope')
    return count


def check_deflate_stream(path, info):
    """Check the complete raw stream; ZipExtFile clips at declared file_size."""
    with path.open('rb') as source:
        source.seek(info.header_offset)
        header = source.read(30)
        if len(header) != 30 or header[:4] != b'PK\x03\x04':
            raise ValueError(f'Invalid local ZIP header: {info.filename}')
        name_size, extra_size = struct.unpack_from('<2H', header, 26)
        source.seek(name_size + extra_size, 1)
        remaining = info.compress_size
        expanded = 0
        inflater = zlib.decompressobj(-15)
        while remaining:
            block = source.read(min(65536, remaining))
            if not block:
                raise ValueError(f'Truncated compressed ZIP member: {info.filename}')
            remaining -= len(block)
            while True:
                limit = min(65536, info.file_size - expanded + 1)
                output = inflater.decompress(block, limit)
                expanded += len(output)
                if expanded > info.file_size:
                    raise ValueError(f'Archive expansion exceeds declared size: {info.filename}')
                if inflater.unused_data or (inflater.eof and remaining):
                    raise ValueError(f'Trailing compressed ZIP data: {info.filename}')
                block = inflater.unconsumed_tail
                if not block and len(output) < limit:
                    break
        if not inflater.eof or expanded != info.file_size:
            raise ValueError(f'Incomplete compressed ZIP stream: {info.filename}')


def verify_archive(path, expected):
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError(f'Archive exceeds compressed size limit: {path.name}')
    declared_count = check_zip_envelope(path)
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) != declared_count:
                raise ValueError(f'Invalid release archive: {path.name}: inconsistent entry count')
            if len(entries) > MAX_MEMBERS:
                raise ValueError(f'Archive has too many entries: {path.name}')
            names = [safe_archive_name(info) for info in entries]
            if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
                raise ValueError(f'Duplicate archive paths: {path.name}')
            if set(names) != set(expected):
                missing = sorted(set(expected) - set(names))
                extra = sorted(set(names) - set(expected))
                raise ValueError(f'Archive contents differ: {path.name}; missing={missing[:3]}, extra={extra[:3]}')
            if (any(info.file_size > MAX_MEMBER_BYTES or info.file_size < 0 for info in entries)
                    or sum(info.file_size for info in entries) > MAX_EXPANDED_BYTES):
                raise ValueError(f'Archive exceeds expanded size limit: {path.name}')
            for info in entries:
                source = expected[info.filename]
                if info.file_size != source.stat().st_size:
                    raise ValueError(f'Archive file size differs: {path.name}: {info.filename}')
                # ZipExtFile validates the CRC at EOF. Stream and compare hashes so
                # no member is extracted or held whole in memory.
                digest = hashlib.sha256()
                read_bytes = 0
                with archive.open(info) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        read_bytes += len(block)
                        if read_bytes > info.file_size or read_bytes > MAX_MEMBER_BYTES:
                            raise ValueError(f'Archive expansion exceeds declared size: {info.filename}')
                        digest.update(block)
                if read_bytes != info.file_size or digest.hexdigest() != sha256(source):
                    raise ValueError(f'Archive file content differs: {path.name}: {info.filename}')
                if info.compress_type == zipfile.ZIP_DEFLATED:
                    check_deflate_stream(path, info)
                elif info.compress_size != info.file_size:
                    raise ValueError(f'Stored ZIP size differs: {info.filename}')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ValueError(f'Invalid release archive: {path.name}: {exc}') from exc
    return len(expected)


def verify(root=ROOT, artifacts=None):
    """Validate all four artifacts using the explicitly trusted checkout as authority.

    SHA256SUMS detects accidental damage; it is not a signature or an independent
    authenticity guarantee. A checkout and artifacts changed together can agree.
    """
    root = Path(root).resolve()
    check(root)
    directory = Path(artifacts) if artifacts is not None else root / 'dist'
    if not directory.is_dir() or linked(directory):
        raise ValueError('Release artifact directory must be a regular, existing directory')
    names = [f'just-build-{host}.zip' for host in (*HOSTS, 'source')]
    expected_names = {*names, 'SHA256SUMS'}
    actual_names = set()
    for path in directory.iterdir():
        actual_names.add(path.name)
        if len(actual_names) > len(expected_names):
            raise ValueError('Release artifact directory has missing or extra files')
    if actual_names != expected_names:
        raise ValueError('Release artifact directory has missing or extra files')
    for name in expected_names:
        path = directory / name
        if linked(path) or not path.is_file():
            raise ValueError(f'Release artifact must be a regular file: {name}')
    sums = directory / 'SHA256SUMS'
    if sums.stat().st_size > MAX_CHECKSUM_BYTES:
        raise ValueError('SHA256SUMS exceeds size limit')
    try:
        lines = sums.read_text(encoding='ascii').splitlines()
    except UnicodeError as exc:
        raise ValueError('SHA256SUMS must be ASCII text') from exc
    recorded = {}
    for line in lines:
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] in recorded:
            raise ValueError('SHA256SUMS has a malformed or duplicate entry')
        recorded[match[2]] = match[1]
    if set(recorded) != set(names):
        raise ValueError('SHA256SUMS must list exactly the expected archives')
    for name in names:
        path = directory / name
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError(f'Archive exceeds compressed size limit: {name}')
        if sha256(path) != recorded[name]:
            raise ValueError(f'Archive checksum differs: {name}')
    files = source_files(root)
    counts = {}
    for host, name in zip(HOSTS, names):
        base = root / host
        expected = {file.relative_to(base).as_posix(): file
                    for file in files if file.is_relative_to(base)}
        if 'just-build/SKILL.md' not in expected or any(not item.startswith('just-build/') for item in expected):
            raise ValueError(f'Invalid host installation layout in checkout: {host}')
        counts[name] = verify_archive(directory / name, expected)
    source = {'just-build/' + file.relative_to(root).as_posix(): file for file in files}
    counts[names[-1]] = verify_archive(directory / names[-1], source)
    return {'passed': True, 'archives': counts,
            'scope': 'Exact contents against this trusted checkout; no extraction, execution, signature or live-host evaluation'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Trusted source checkout; defaults to this checkout')
    parser.add_argument('--artifacts', type=Path, help='Directory containing exactly three archives and SHA256SUMS; defaults to dist/')
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.root, args.artifacts), indent=2))
    except (OSError, ValueError, SyntaxError) as exc:
        raise SystemExit(f'Release verification failed: {exc}')
