import json
from pathlib import Path
import tempfile
import unittest

from test_app import ROOT, TMP, run
class Errors(unittest.TestCase):
    def test_missing_then_recovery(self):
        r=run(ROOT/'missing.csv');self.assertEqual(r.returncode,2);self.assertIn('Cannot read',r.stderr)
        self.assertEqual(run(ROOT/'examples/good.csv').returncode,0)
    def test_collision_and_invalid_bytes(self):
        with tempfile.TemporaryDirectory(dir=TMP) as f:
            p=Path(f)/'x.csv';p.write_bytes(b'\xffsecret')
            r=run(p);self.assertEqual(r.returncode,2);self.assertIn('UTF-8',r.stderr);self.assertNotIn('secret',r.stderr)
            p.write_text('id\n1\n');r=run(p,'--report',p);self.assertEqual(r.returncode,2);self.assertEqual(p.read_text(),'id\n1\n')
            p.write_text('id,name\n1,"unterminated\n');self.assertEqual(run(p).returncode,1)
    def test_limits_empty_and_delimiter(self):
        with tempfile.TemporaryDirectory(dir=TMP) as f:
            p=Path(f)/'x.csv';p.write_text('');self.assertEqual(run(p).returncode,1)
            p.write_text('id;name\n1;Ada\n');self.assertEqual(run(p,'--delimiter',';').returncode,0)
            self.assertEqual(run(p,'--delimiter','xx').returncode,2)

    def test_syntax_locations_and_preservation(self):
        cases = [
            (b'"unterminated\n', 1, 1, 0),
            (b'id,name\n1,Ada\n2,Lin\n3,"unterminated\n', 4, 4, 2),
            (b'id,name\n1,"Ada\nLovelace"\n2,Lin\n3,"unterminated\nstill open\n', 4, 6, 2),
        ]
        with tempfile.TemporaryDirectory(dir=TMP) as folder:
            path = Path(folder)/'syntax.csv'
            for raw, record, line, rows in cases:
                with self.subTest(record=record, line=line):
                    path.write_bytes(raw)
                    result = run(path, '--json')
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stderr, '')
                    report = json.loads(result.stdout)
                    self.assertEqual(report['data_rows'], rows)
                    self.assertEqual(report['issues'], [{'code':'csv-syntax', 'record':record, 'physical_line_end':line}])
                    self.assertEqual(path.read_bytes(), raw)

    def test_actual_byte_limit(self):
        with tempfile.TemporaryDirectory(dir=TMP) as folder:
            path = Path(folder)/'byte-limit.csv'
            size = 10 * 1024 * 1024
            unit = b'x' * 65535 + b'\n'
            count, tail = divmod(size - len(b'col\n'), len(unit))
            raw = b'col\n' + unit * count + b'x' * (tail - 1) + b'\n'
            self.assertEqual(len(raw), size)
            path.write_bytes(raw)
            result = run(path, '--json')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['valid'])
            with path.open('ab') as stream:
                stream.write(b'x')
            result = run(path, '--json')
            self.assertEqual(result.returncode, 2)
            self.assertIn('10 MiB limit', result.stderr)
            self.assertEqual(path.stat().st_size, size + 1)

    def test_actual_row_limit(self):
        with tempfile.TemporaryDirectory(dir=TMP) as folder:
            path = Path(folder)/'row-limit.csv'
            raw = b'col\n' + b'x\n' * 100000
            path.write_bytes(raw)
            result = run(path, '--json')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['data_rows'], 100000)
            with path.open('ab') as stream:
                stream.write(b'x\n')
            result = run(path, '--json')
            self.assertEqual(result.returncode, 2)
            self.assertIn('100000 data rows', result.stderr)
            self.assertEqual(path.read_bytes(), raw + b'x\n')

    def test_issue_cap_keeps_total(self):
        with tempfile.TemporaryDirectory(dir=TMP) as folder:
            path = Path(folder)/'issues.csv'
            raw = b'a,b\n' + b'short\n' * 101
            path.write_bytes(raw)
            result = run(path, '--json')
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['data_rows'], 101)
            self.assertEqual(report['issue_count'], 101)
            self.assertEqual(len(report['issues']), 100)
            self.assertTrue(report['issues_truncated'])
            self.assertEqual(report['issues'][-1]['record'], 101)
            self.assertEqual(path.read_bytes(), raw)
