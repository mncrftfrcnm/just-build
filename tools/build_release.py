#!/usr/bin/env python3
"""Build deterministic local skill/source ZIPs. Never publishes anything."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile

from check_repo import ROOT, HOSTS, ROOT_FILES, SOURCE_DIRS, check, source_files


def archive(path, entries):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for name, source in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, source.read_bytes(), compresslevel=9)
    with zipfile.ZipFile(path) as result:
        if result.testzip() is not None or len(result.namelist()) != len(set(result.namelist())):
            raise ValueError('Release archive validation failed')


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    check(root)
    output = Path(output).resolve() if output is not None else root / 'dist'
    distribution_paths = [root / name for name in (*ROOT_FILES, *SOURCE_DIRS)]
    if any(output.is_relative_to(path) or path.is_relative_to(output)
           for path in distribution_paths):
        raise ValueError('Release output must not overlap distribution source paths or their ancestors')
    names = [f'just-build-{host}.zip' for host in (*HOSTS, 'source')]
    if any((output / name).exists() for name in (*names, 'SHA256SUMS')):
        raise ValueError('Refusing to overwrite release artifacts; use a fresh output directory')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Release output must be an empty directory; use a fresh output directory')
    output.mkdir(parents=True, exist_ok=True)
    files = source_files(root)
    for host, name in zip(HOSTS, names):
        base = root / host
        archive(output / name, [(file.relative_to(base).as_posix(), file)
                                for file in files if file.is_relative_to(base)])
    archive(output / names[-1], [('just-build/' + file.relative_to(root).as_posix(), file) for file in files])
    checksums = ''.join(hashlib.sha256((output / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in names)
    (output / 'SHA256SUMS').write_text(checksums, encoding='utf-8', newline='\n')
    from verify_release import verify
    verify(root, output)
    return [output / name for name in (*names, 'SHA256SUMS')]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Fresh output directory; defaults to dist/')
    args = parser.parse_args()
    try:
        for artifact in build(output=args.output):
            print(artifact)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
