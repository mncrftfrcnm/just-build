"""End-to-end smoke test for the synthetic local task board."""
from pathlib import Path
import subprocess
import sys
import tempfile

APP = Path(__file__).with_name("app.py")
with tempfile.TemporaryDirectory() as td:
    data = Path(td) / "tasks.json"
    base = [sys.executable, str(APP), "--data", str(data)]
    def run(*args):
        p = subprocess.run(base + list(args), capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        return p.stdout
    run("add", "Finish MVP")
    assert "Finish MVP" in run("list")
    run("done", "1")
    assert "1: done" in run("list")
print("Task lifecycle smoke test passed")
