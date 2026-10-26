import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1] / "app.py"


class TaskBoardTest(unittest.TestCase):
    def test_add_list_complete_and_persist(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "tasks.json"
            def run(*args):
                return subprocess.run([sys.executable, str(APP), "--data", str(data), *args], capture_output=True, text=True)
            one = run("add", "Write tests")
            self.assertEqual(one.returncode, 0, one.stderr)
            self.assertEqual(json.loads(one.stdout)["id"], 1)
            two = run("add", "Publish notes")
            self.assertEqual(json.loads(two.stdout)["id"], 2)
            self.assertIn("Write tests", run("list").stdout)
            done = run("done", "1")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue(json.loads(data.read_text())[0]["done"])
            self.assertFalse(json.loads(data.read_text())[1]["done"])

    def test_reject_blank_title_and_missing_id(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "tasks.json"
            base = [sys.executable, str(APP), "--data", str(data)]
            self.assertNotEqual(subprocess.run(base + ["add", " "], capture_output=True).returncode, 0)
            self.assertNotEqual(subprocess.run(base + ["done", "99"], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
