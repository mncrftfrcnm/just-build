"""Independent user-facing regression scenarios run through the public CLI."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1] / "app.py"


class ExperienceTests(unittest.TestCase):
    def invoke(self, path, *args):
        return subprocess.run([sys.executable, str(APP), "--data", str(path), *args],
                              capture_output=True, text=True, timeout=8)

    def test_fresh_user_can_discover_and_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            help_result = subprocess.run([sys.executable, str(APP), "--help"], capture_output=True, text=True, timeout=8)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("add", help_result.stdout)
            initial = self.invoke(path, "list")
            self.assertEqual(initial.returncode, 0, initial.stderr)
            self.assertIn("No tasks yet", initial.stdout)
            self.assertIn("add", initial.stdout)
            self.assertFalse(path.exists(), "read-only first visit must not create state")
            added = self.invoke(path, "add", "Take the first step")
            self.assertEqual(added.returncode, 0, added.stderr)
            self.assertIn("Take the first step", self.invoke(path, "list").stdout)

    def test_bad_input_does_not_break_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            self.assertNotEqual(self.invoke(path, "done", "77").returncode, 0)
            self.assertIn("does not exist", self.invoke(path, "done", "77").stderr)
            self.assertIn("use list", self.invoke(path, "done", "77").stderr)
            self.assertFalse(path.exists())
            self.assertEqual(self.invoke(path, "add", "Recover after typo").returncode, 0)
            self.assertEqual(self.invoke(path, "done", "1").returncode, 0)
            self.assertIn("done", self.invoke(path, "list").stdout)

if __name__ == "__main__":
    unittest.main()
