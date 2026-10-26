"""Assertions for invalid input and error recovery through the public CLI."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1] / 'app.py'

class ErrorPathTests(unittest.TestCase):
    def test_blank_title_does_not_write_data(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'tasks.json'
            run = subprocess.run([sys.executable, str(APP), '--data', str(db), 'add', '  '], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('title cannot be blank', run.stderr)
            self.assertFalse(db.exists())

    def test_unknown_id_explains_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'tasks.json'
            run = subprocess.run([sys.executable, str(APP), '--data', str(db), 'done', '999'], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertRegex(run.stderr, r'(task ID does not exist|No task with that ID)')
            self.assertFalse(db.exists())
