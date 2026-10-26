import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_repo import ROOT, check, source_files
from build_release import build


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'repository'
        for source in source_files():
            target = self.root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def tearDown(self):
        self.temporary.cleanup()

    def test_clean_repository_passes(self):
        self.assertTrue(check(self.root)['passed'])

    def test_shared_file_drift_is_detected(self):
        file = self.root / 'claude-code/just-build/scripts/process_runner.py'
        file.write_text(file.read_text(encoding='utf-8') + '\n# drift\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'drift'):
            check(self.root)

    def test_extra_host_file_is_detected(self):
        (self.root / 'claude-code/just-build/unmatched.txt').write_text('fixture')
        with self.assertRaisesRegex(ValueError, 'drift'):
            check(self.root)

    def test_private_nested_configuration_is_rejected(self):
        for name in ('.env', '.ENV', '.env.local', '.ENV.LOCAL', 'private.PEM', 'private.KEY'):
            with self.subTest(name=name):
                paths = [self.root / host / 'just-build' / name for host in ('codex', 'claude-code')]
                for path in paths:
                    path.write_text('SYNTHETIC_ONLY=true')
                try:
                    with self.assertRaisesRegex(ValueError, 'Private configuration'):
                        check(self.root)
                finally:
                    for path in paths:
                        path.unlink()

    def test_standard_private_key_headers_are_rejected_without_sensitive_suffixes(self):
        target = self.root / 'docs/synthetic-key-fixture'
        for label in ('PRIVATE KEY', 'RSA PRIVATE KEY', 'EC PRIVATE KEY',
                      'OPENSSH PRIVATE KEY', 'ENCRYPTED PRIVATE KEY'):
            with self.subTest(label=label):
                target.write_text('-----BEGIN ' + label + '-----\nSYNTHETIC-NOT-A-KEY', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Private key material'):
                    check(self.root)

    def test_broken_documentation_link_is_detected(self):
        (self.root / 'docs/EVALUATION.md').write_text('[missing](missing.md)')
        with self.assertRaisesRegex(ValueError, 'Broken local'):
            check(self.root)

    def test_unpinned_action_is_rejected(self):
        file = self.root / '.github/workflows/tests.yml'
        text = file.read_text().replace('3d3c42e5aac5ba805825da76410c181273ba90b1', 'main')
        file.write_text(text)
        with self.assertRaisesRegex(ValueError, 'commit pins'):
            check(self.root)

    def test_release_is_reproducible_and_excludes_local_files(self):
        (self.root / '.env').write_text('SYNTHETIC_ONLY=true')
        (self.root / 'test-results-local.json').write_text('{"private_fixture":true}')
        first = build(self.root, Path(self.temporary.name) / 'one')
        os.utime(self.root / 'README.md', (1600000000, 1600000000))
        second = build(self.root, Path(self.temporary.name) / 'two')
        for a, b in zip(first, second):
            self.assertEqual(a.read_bytes(), b.read_bytes())
        for host, artifact in zip(('codex', 'claude-code'), first[:2]):
            with zipfile.ZipFile(artifact) as package:
                self.assertIn('just-build/SKILL.md', package.namelist())
                self.assertIn('just-build/LICENSE', package.namelist())
                self.assertEqual(package.read('just-build/SKILL.md'), (self.root / host / 'just-build/SKILL.md').read_bytes())
        with zipfile.ZipFile(first[2]) as source:
            self.assertTrue(any(name.endswith('/.github/workflows/tests.yml') for name in source.namelist()))
            for name in ('csv-preflight', 'csv-intake-check'):
                self.assertTrue(any(path.endswith(f'/examples/{name}/app.py') for path in source.namelist()))
            self.assertFalse(any(name.endswith('/.env') or 'test-results-local' in name or '/dist/' in name for name in source.namelist()))
        for line, artifact in zip(first[-1].read_text().splitlines(), first[:-1]):
            digest, name = line.split('  ')
            self.assertEqual(name, artifact.name)
            self.assertEqual(digest, hashlib.sha256(artifact.read_bytes()).hexdigest())

    def test_release_does_not_overwrite(self):
        output = Path(self.temporary.name) / 'releases'
        artifacts = build(self.root, output)
        before = {file.name: file.read_bytes() for file in artifacts}
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            build(self.root, output)
        self.assertEqual(before, {file.name: file.read_bytes() for file in artifacts})

    def test_release_names_are_unversioned(self):
        result = build(self.root, Path(self.temporary.name) / 'releases')
        self.assertEqual([p.name for p in result],
                         ['just-build-codex.zip', 'just-build-claude-code.zip',
                          'just-build-source.zip', 'SHA256SUMS'])


if __name__ == '__main__':
    unittest.main()
