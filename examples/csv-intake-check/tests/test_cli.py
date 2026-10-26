import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def invoke(*args):
    result = subprocess.run([sys.executable, str(PROJECT / 'app.py'), *map(str,args)], capture_output=True, text=True, timeout=8)
    assert 'Traceback' not in result.stderr, result.stderr
    return result


class Checks(unittest.TestCase):
    def fixture(self, content, expected_valid, rows, errors=()):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.csv'
            original=content.encode('utf-8') if isinstance(content,str) else content
            path.write_bytes(original)
            a=invoke('check',path,'--json'); b=invoke('check',path,'--json')
            self.assertEqual(a.returncode,0 if expected_valid else 2,a.stdout+a.stderr)
            self.assertEqual(a.stdout,b.stdout)
            self.assertEqual(a.stderr,'')
            self.assertEqual(path.read_bytes(),original)
            data=json.loads(a.stdout)
            self.assertEqual(data['valid'],expected_valid)
            self.assertEqual(data['rows'],rows)
            self.assertEqual([(e['line'],e['code']) for e in data['errors']],list(errors))
            for error in data['errors']:
                self.assertIsInstance(error['line'],int)
                self.assertTrue(error['message'].strip())
            return data

    def test_journey(self):
        self.fixture('name,note\nAlice,"hello, world"\nBob,"one\ntwo"\n',True,2)
        self.fixture(b'\xef\xbb\xbfname,city\r\nNora,Dubai\r\n',True,1)
        self.fixture('one\r\nvalue\r\n',True,1)
        self.fixture('name,city',True,0)
        self.fixture('a,b\n\n , \n,\n',True,2)
        self.fixture('a,b\r1,2\r3,4',True,2)
        self.fixture('a,b\n"x""y",z\n',True,1)

    def test_edge(self):
        self.fixture('',False,0,[(1,'empty-header')])
        self.fixture('\n\n',False,0,[(1,'empty-header')])
        self.fixture(',\n1,2\n',False,1,[(1,'empty-header'),(1,'empty-header')])
        self.fixture(' Name ,NAME\nx,y\n',False,1,[(1,'duplicate-header')])
        self.fixture('a, ,c\n1,2,3\n',False,1,[(1,'empty-header')])
        self.fixture('a,b\n"one\ntwo",x\nshort\n1,2,3\n',False,3,[(4,'row-width'),(5,'row-width')])
        self.fixture('a,b\n \n',False,1,[(2,'row-width')])
        self.fixture(b'a,b\n\xff,2\n',False,0,[(1,'read-error')])
        self.fixture('a,b\n"unterminated\n',False,0,[(2,'read-error')])
        with tempfile.TemporaryDirectory() as folder:
            result=invoke('check',Path(folder)/'missing.csv','--json')
            self.assertEqual(result.returncode,2)
            self.assertEqual(json.loads(result.stdout)['errors'][0]['code'],'read-error')
            self.assertEqual(list(Path(folder).iterdir()),[])
            result=invoke('check',folder,'--json')
            self.assertEqual(result.returncode,2)
            self.assertEqual(json.loads(result.stdout)['errors'][0]['code'],'read-error')

    def test_first_run(self):
        result=invoke('--help')
        self.assertEqual(result.returncode,0)
        for expected in ['check','--json','Exit codes','examples/valid.csv']:
            self.assertIn(expected,result.stdout)
        data=json.loads(invoke('check',PROJECT/'examples/valid.csv','--json').stdout)
        self.assertEqual(data,{'valid':True,'rows':2,'errors':[]})

    def test_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'corrected.csv'
            bad=invoke('check',path,'--json')
            self.assertEqual(bad.returncode,2)
            self.assertIn('check the path',json.loads(bad.stdout)['errors'][0]['message'])
            self.assertFalse(path.exists())
            path.write_bytes(b'name\nAda\n')
            good=invoke('check',path,'--json')
            self.assertEqual(good.returncode,0)
            self.assertEqual(json.loads(good.stdout),{'valid':True,'rows':1,'errors':[]})
            self.assertEqual(path.read_bytes(),b'name\nAda\n')

    def test_smoke(self):
        result=invoke('check',PROJECT/'examples/valid.csv','--json')
        self.assertEqual(result.returncode,0)
        self.assertEqual(json.loads(result.stdout),{'valid':True,'rows':2,'errors':[]})


if __name__=='__main__':
    label=sys.argv[1] if len(sys.argv)>1 else 'all'
    names={'journey':'test_journey','edge':'test_edge','first-run':'test_first_run','recovery':'test_recovery','smoke':'test_smoke'}
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Checks) if label=='all' else unittest.TestSuite([Checks(names[label])])
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
