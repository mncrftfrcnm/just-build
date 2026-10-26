# Resume diagnostics and recovery

When resuming a run or investigating a rejected transition, first inspect its ledger without changing evidence:

```sh
python3 <skill-dir>/scripts/run_tracker.py diagnose --state-dir "$RUN"
```

The JSON response reports the current stage, completion, required check labels and their missing/failed/stale/current status, source and declared-output availability, review/security/usability readiness and a suggested next action. `schema_version` is 1. Codes and hints are bounded, authored strings; the output omits goals, commands, test output, source URLs and private notes. Research/output gaps use zero-based indices into the selected plan. The command does not execute project code, fetch sources, repair the ledger, create state or regenerate Markdown reports. It can still read the bounded project files needed for fingerprints. An unreadable/damaged ledger returns an inspection status; preserve it rather than inventing a new history.

Completed initial Verify is historical evidence for its sealed snapshot. Final Verify and both passing Quality/Polish approvals must cover current files in every profile, including standard continuations. A green test run cannot revive stale approvals. Diagnose uses the tracker predicates and never grants an exception to a stage gate. Its `next_action` is guidance for the active agent, not an automatically executed command or proof of complete research or product quality.

If files change after Quality is done and handoff is unfinished, use explicit `recheck` when `recheck_allowed` is true:

```sh
python3 <skill-dir>/scripts/run_tracker.py recheck --state-dir "$RUN"
```

This reopens Quality, then Polish and Final Verify, clears their active approvals and security scan, and preserves the frozen plan, contract, first verification and retained history. Profiled usability attempts remain bounded; recheck does not grant extra rounds. Resolve observed problems, obtain current approvals and rerun every required final check. If a stage is blocked, preserve the recorded blocker and reactivate that same stage when resolved. Once handoff is done, further work needs a fresh continuation.

For Continue, initialize an empty state folder outside the entire project directory. A nested/equal state path is rejected before directory creation: writing reports there would change the very source being verified. New builds retain the scaffold-created `.just-build` location. Do not move or edit recorded ledger history to bypass this rule.
