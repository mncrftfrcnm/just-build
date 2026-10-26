import hashlib
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_release import build
from check_repo import ROOT, source_files
from verify_release import verify, verify_archive


class CompressedStreamTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.source = self.folder / 'expected.txt'
        self.source.write_bytes(b'expected')
        self.path = self.folder / 'member.zip'
        self.name = b'just-build/expected.txt'

    def tearDown(self):
        self.temporary.cleanup()

    def write_archive(self, compressed, method=zipfile.ZIP_DEFLATED):
        payload = self.source.read_bytes()
        crc = zlib.crc32(payload)
        local = struct.pack('<4s5H3L2H', b'PK\x03\x04', 20, 0, method, 0, 0,
                            crc, len(compressed), len(payload), len(self.name), 0)
        local += self.name + compressed
        central = struct.pack('<4s6H3L5H2L', b'PK\x01\x02', 20, 20, 0, method, 0, 0,
                              crc, len(compressed), len(payload), len(self.name), 0,
                              0, 0, 0, 0, 0) + self.name
        end = struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 1, 1,
                          len(central), len(local), 0)
        self.path.write_bytes(local + central + end)

    def compress(self, payload, finish=zlib.Z_FINISH):
        compressor = zlib.compressobj(wbits=-15)
        return compressor.compress(payload) + compressor.flush(finish)

    def verify(self):
        return verify_archive(self.path, {self.name.decode(): self.source})

    def test_complete_deflate_streams_are_accepted_including_multiple_chunks(self):
        for payload in (b'', b'expected', b'x' * 200000, random.Random(0).randbytes(200000)):
            with self.subTest(size=len(payload)):
                self.source.write_bytes(payload)
                self.write_archive(self.compress(payload))
                self.assertEqual(1, self.verify())

    def test_actual_expansion_must_not_exceed_declared_member_size(self):
        self.write_archive(self.compress(self.source.read_bytes() + b'HIDDEN' * 100000))
        with self.assertRaisesRegex(ValueError, 'expansion exceeds declared'):
            self.verify()

    def test_complete_payload_without_a_final_deflate_block_is_rejected(self):
        self.write_archive(self.compress(self.source.read_bytes(), zlib.Z_SYNC_FLUSH))
        with self.assertRaisesRegex(ValueError, 'Incomplete compressed'):
            self.verify()

    def test_trailing_compressed_bytes_and_second_stream_are_rejected(self):
        complete = self.compress(self.source.read_bytes())
        for trailing in (b'trailing', self.compress(b'other stream')):
            with self.subTest(trailing=trailing):
                self.write_archive(complete + trailing)
                with self.assertRaisesRegex(ValueError, 'Trailing compressed'):
                    self.verify()

    def test_stored_members_cannot_hide_bytes_beyond_declared_size(self):
        self.write_archive(self.source.read_bytes() + b'hidden', zipfile.ZIP_STORED)
        with self.assertRaisesRegex(ValueError, 'Stored ZIP size differs'):
            self.verify()


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / 'repository'
        for source in source_files():
            target = self.root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.output = self.base / 'artifacts'
        self.artifacts = build(self.root, self.output)

    def tearDown(self):
        self.temporary.cleanup()

    def refresh_checksums(self):
        self.artifacts[-1].write_text(''.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in self.artifacts[:-1]), encoding='ascii')

    def rewrite_archive(self, transform):
        path = self.artifacts[0]
        with zipfile.ZipFile(path) as archive:
            entries = [(info, archive.read(info)) for info in archive.infolist()]
        entries = transform(entries)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for info, payload in entries:
                    archive.writestr(info, payload)
        self.refresh_checksums()

    def test_verified_release_preserves_four_artifact_api_and_install_layout(self):
        result = verify(self.root, self.output)
        self.assertTrue(result['passed'])
        self.assertEqual(len(self.artifacts), 4)
        self.assertEqual(self.artifacts[-1].name, 'SHA256SUMS')
        self.assertEqual(list(result['archives']), [item.name for item in self.artifacts[:-1]])
        self.assertGreater(min(result['archives'].values()), 1)

    def test_source_zip_keeps_release_metadata_and_simple_directory(self):
        with zipfile.ZipFile(self.artifacts[2]) as source:
            self.assertIn('just-build/README.md', source.namelist())
            self.assertEqual((self.root / 'VERSION').read_bytes(), source.read('just-build/VERSION'))

    def test_missing_and_extra_artifacts_are_rejected(self):
        extra = self.output / 'unexpected.txt'
        extra.write_text('fixture')
        with self.assertRaisesRegex(ValueError, 'missing or extra'):
            verify(self.root, self.output)
        extra.unlink()
        self.artifacts[0].unlink()
        with self.assertRaisesRegex(ValueError, 'missing or extra'):
            verify(self.root, self.output)

    def test_checksum_names_are_exact_with_no_duplicate_entries(self):
        path = self.artifacts[-1]
        original = path.read_text()
        cases = [original + original.splitlines()[0] + '\n',
                 '\n'.join(original.splitlines()[1:]) + '\n',
                 original + '0' * 64 + '  unexpected.zip\n',
                 original.replace(self.artifacts[0].name, '../escape.zip')]
        for text in cases:
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError, 'SHA256SUMS'):
                    verify(self.root, self.output)

    def test_archive_damage_cannot_pass_original_checksum(self):
        with self.artifacts[0].open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            verify(self.root, self.output)

    def test_rehashed_tampered_member_is_rejected_against_checkout(self):
        def change(entries):
            info, payload = entries[0]
            return [(info, bytes([payload[0] ^ 1]) + payload[1:]), *entries[1:]]
        self.rewrite_archive(change)
        with self.assertRaisesRegex(ValueError, 'content differs'):
            verify(self.root, self.output)

    def test_missing_and_extra_archive_members_are_rejected(self):
        original = self.artifacts[0].read_bytes()
        self.rewrite_archive(lambda entries: entries[1:])
        with self.assertRaisesRegex(ValueError, 'contents differ'):
            verify(self.root, self.output)
        self.artifacts[0].write_bytes(original)
        self.rewrite_archive(lambda entries: [*entries, (zipfile.ZipInfo('just-build/extra.txt'), b'extra')])
        with self.assertRaisesRegex(ValueError, 'contents differ'):
            verify(self.root, self.output)

    def test_duplicate_and_case_alias_archive_paths_are_rejected(self):
        original = self.artifacts[0].read_bytes()
        self.rewrite_archive(lambda entries: [*entries, entries[0]])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            verify(self.root, self.output)
        self.artifacts[0].write_bytes(original)
        self.rewrite_archive(lambda entries: [*entries, (zipfile.ZipInfo(entries[0][0].filename.upper()), entries[0][1])])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            verify(self.root, self.output)

    def test_unsafe_archive_paths_are_rejected_without_extracting(self):
        original = self.artifacts[0].read_bytes()
        for name in ('../escape.txt', '/absolute.txt', 'just-build/../escape.txt',
                     'just-build\\escape.txt', 'C:/escape.txt', 'just-build//extra.txt'):
            with self.subTest(name=name):
                self.artifacts[0].write_bytes(original)
                self.rewrite_archive(lambda entries: [*entries, (zipfile.ZipInfo(name), b'fixture')])
                if '\\' in name:
                    # ZipInfo normalizes the native separator on Windows. Put
                    # the raw unsafe spelling back into both ZIP name records.
                    path = self.artifacts[0]
                    path.write_bytes(path.read_bytes().replace(name.replace('\\', '/').encode(), name.encode()))
                    self.refresh_checksums()
                with self.assertRaisesRegex(ValueError, 'Unsafe archive path'):
                    verify(self.root, self.output)
        self.assertFalse((self.base / 'escape.txt').exists())

    def test_linked_archive_entry_is_rejected(self):
        original = self.artifacts[0].read_bytes()
        for attributes in (0o120777 << 16, (0o100644 << 16) | 0x400, (0o100644 << 16) | 0x10):
            with self.subTest(attributes=attributes):
                self.artifacts[0].write_bytes(original)
                def link(entries):
                    info, payload = entries[0]
                    info.create_system = 3
                    info.external_attr = attributes
                    return [(info, payload), *entries[1:]]
                self.rewrite_archive(link)
                with self.assertRaisesRegex(ValueError, 'Linked or non-regular'):
                    verify(self.root, self.output)

    def test_compressed_size_limit_precedes_archive_parsing(self):
        with patch('verify_release.MAX_ARCHIVE_BYTES', 1), patch('verify_release.zipfile.ZipFile') as opened:
            with self.assertRaisesRegex(ValueError, 'compressed size limit'):
                verify(self.root, self.output)
            opened.assert_not_called()

    def test_expansion_and_member_count_limits_precede_payload_reads(self):
        for constant in ('MAX_MEMBER_BYTES', 'MAX_EXPANDED_BYTES', 'MAX_MEMBERS'):
            with self.subTest(constant=constant), patch('verify_release.' + constant, 1):
                with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('payload read')):
                    with self.assertRaisesRegex(ValueError, 'expanded size limit|too many entries'):
                        verify(self.root, self.output)

    def test_forged_entry_count_and_large_directory_are_bounded_before_zip_parse(self):
        path = self.artifacts[0]
        original = path.read_bytes()
        raw = bytearray(original)
        end = raw.rfind(b'PK\x05\x06')
        struct.pack_into('<HH', raw, end + 8, 10001, 10001)
        path.write_bytes(raw)
        self.refresh_checksums()
        with patch('verify_release.zipfile.ZipFile') as opened:
            with self.assertRaisesRegex(ValueError, 'too many entries'):
                verify(self.root, self.output)
            opened.assert_not_called()
        path.write_bytes(original)
        self.refresh_checksums()
        with patch('verify_release.MAX_CENTRAL_DIRECTORY_BYTES', 1), patch('verify_release.zipfile.ZipFile') as opened:
            with self.assertRaisesRegex(ValueError, 'central directory exceeds'):
                verify(self.root, self.output)
            opened.assert_not_called()
        raw = bytearray(original)
        struct.pack_into('<HH', raw, end + 8, 1, 1)
        path.write_bytes(raw)
        self.refresh_checksums()
        with self.assertRaisesRegex(ValueError, 'inconsistent entry count'):
            verify(self.root, self.output)

    def test_malformed_zip_with_updated_checksum_is_rejected(self):
        self.artifacts[0].write_bytes(b'not a zip archive')
        self.refresh_checksums()
        with self.assertRaisesRegex(ValueError, 'Invalid release archive'):
            verify(self.root, self.output)

    def test_invalid_deflate_stream_is_a_clean_verification_failure(self):
        path = self.artifacts[0]
        with zipfile.ZipFile(path) as archive:
            offset = archive.infolist()[0].header_offset
        raw = bytearray(path.read_bytes())
        name_length, extra_length = struct.unpack_from('<HH', raw, offset + 26)
        # Reserved DEFLATE block type, inside a valid ZIP central directory.
        raw[offset + 30 + name_length + extra_length] = 0xff
        path.write_bytes(raw)
        self.refresh_checksums()
        with self.assertRaisesRegex(ValueError, 'Invalid release archive'):
            verify(self.root, self.output)

    def test_output_overlapping_any_distribution_source_is_rejected_without_writes(self):
        for path in (self.root, self.base, self.root / 'README.md',
                     *(self.root / name / 'release-output' for name in
                       ('docs', 'tools', 'examples', '.github', 'codex', 'claude-code'))):
            with self.subTest(path=path):
                existed = path.exists()
                with self.assertRaisesRegex(ValueError, 'overlap distribution source'):
                    build(self.root, path)
                self.assertEqual(existed, path.exists())

    def test_default_dist_is_allowed_and_rebuild_cannot_overwrite(self):
        artifacts = build(self.root)
        before = {path.name: path.read_bytes() for path in artifacts}
        self.assertEqual(artifacts[0].parent, self.root / 'dist')
        self.assertTrue(verify(self.root)['passed'])
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            build(self.root)
        self.assertEqual(before, {path.name: path.read_bytes() for path in artifacts})

    def test_nonempty_output_directory_is_rejected_before_artifacts_are_created(self):
        output = self.base / 'nonempty'
        output.mkdir()
        (output / 'keep.txt').write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'empty directory'):
            build(self.root, output)
        self.assertEqual([item.name for item in output.iterdir()], ['keep.txt'])

    def test_cli_reports_verification_and_nonzero_for_missing_artifacts(self):
        command = [sys.executable, '-B', str(ROOT / 'tools/verify_release.py'),
                   '--root', str(self.root), '--artifacts', str(self.output)]
        good = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertTrue(json.loads(good.stdout)['passed'])
        bad = subprocess.run([*command, '--artifacts', str(self.base / 'missing')], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('must be a regular, existing directory', bad.stderr)


if __name__ == '__main__':
    unittest.main()
