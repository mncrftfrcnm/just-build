# Synthetic sample task board

This is a tested **example of a runnable vertical slice**, not output from a live Codex autonomous run. It uses the Python standard library and local JSON storage. Run `python3 app.py --data /tmp/board.json add "Task name"`, then `python3 app.py --data /tmp/board.json list` or `done 1`. Tests: `python3 -m unittest discover -s tests -v`. Smoke: `python3 smoke.py`.

Start by running `list` even without a data file; the CLI provides a useful empty-state hint without creating files. Invalid task IDs explain how to recover. `tests/test_experience.py` covers fresh-user and recovery scenarios, and the external benchmark checks observable CLI behavior and catches empty-state regressions.
