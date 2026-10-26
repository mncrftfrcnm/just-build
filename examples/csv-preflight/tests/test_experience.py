import json
import unittest

from test_app import ROOT, run
class Experience(unittest.TestCase):
    def test_first_run(self):
        r=run('--help');self.assertEqual(r.returncode,0);self.assertIn('--report',r.stdout);self.assertIn('Read-only',r.stdout)
        r=run(ROOT/'examples/good.csv','--json');self.assertEqual(r.returncode,0);self.assertTrue(json.loads(r.stdout)['valid'])
