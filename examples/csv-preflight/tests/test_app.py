import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TMP=ROOT.parent/'tmp'
TMP.mkdir(exist_ok=True)
def run(*args):
    return subprocess.run([sys.executable,'-B',str(ROOT/'app.py'),*map(str,args)],capture_output=True,text=True)
class Journey(unittest.TestCase):
    def test_audit_and_preserve(self):
        with tempfile.TemporaryDirectory(dir=TMP) as folder:
            p=Path(folder)/'input.csv';raw=b'\xef\xbb\xbfid,name\r\n1,"Ada\r\nLovelace"\r\n2,Lin,extra\r\n';p.write_bytes(raw)
            r=run(p,'--json');self.assertEqual(r.returncode,1,r.stderr)
            j=json.loads(r.stdout);self.assertEqual(j['data_rows'],2);self.assertEqual(j['issues'][0]['record'],3);self.assertEqual(j['issues'][0]['physical_line_end'],4);self.assertEqual(p.read_bytes(),raw);self.assertNotIn('Lovelace',r.stdout)
            q=Path(folder)/'report.json';r=run(p,'--report',q);self.assertEqual(r.returncode,1);self.assertFalse(json.loads(q.read_text())['valid'])
    def test_headers(self):
        with tempfile.TemporaryDirectory(dir=TMP) as f:
            p=Path(f)/'x.csv';p.write_text('id, id ,\n1,2,3\n')
            j=json.loads(run(p,'--json').stdout);self.assertEqual([x['code'] for x in j['issues']],['duplicate-header','blank-header'])
