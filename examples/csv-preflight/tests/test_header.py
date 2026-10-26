import json
from pathlib import Path
import tempfile
import unittest

from test_app import TMP, run
class HeaderSyntax(unittest.TestCase):
    def test_unterminated_header(self):
        with tempfile.TemporaryDirectory(dir=TMP) as folder:
            p=Path(folder)/'x.csv';p.write_text('"unterminated\n')
            r=run(p,'--json');self.assertEqual(r.returncode,1);self.assertEqual(r.stderr,'')
            j=json.loads(r.stdout);self.assertEqual(j['issues'][0]['code'],'csv-syntax');self.assertEqual(j['issues'][0]['record'],1)
