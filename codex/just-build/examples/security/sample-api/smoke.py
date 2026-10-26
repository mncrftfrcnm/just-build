"""Small public entry verification; external HTTP behavior is checked separately."""
import subprocess
import sys
from pathlib import Path
project = Path(__file__).parent
p = subprocess.run([sys.executable, str(project/'server.py'), '--help'], capture_output=True, text=True, timeout=3)
assert p.returncode == 0 and '--port' in p.stdout
