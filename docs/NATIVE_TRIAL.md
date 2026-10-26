# Native offline browser-tool trial

This historical trial predates the strict-audit repairs; it has not been rerun since those repairs.

One fresh project-local installation of the Codex skill was explicitly invoked as `$just-build` by the installed **codex-cli 0.163.0-alpha.10.2**. The supplied task was a tiny accessible offline reading-time calculator, with no dependency installation or external services. No model override was supplied; the configured model identity was not exposed in native events.

**Outcome: runnable implementation, incomplete tracked workflow.** This is not an additional completed application-delivery benchmark. The model ran for **497.216 seconds**, exited normally with status 0 and did not time out. A process exit of zero is not proof of skill-workflow completion.

## Actual measurement

| Counter | Tokens |
|---|---:|
| Input | 1,216,432 |
| Cached input, already included in input | 1,167,616 |
| Uncached input | 48,816 |
| Output | 13,759 |
| Reasoning output, already included in output | 2,527 |
| Input + output | **1,230,191** |

These are actual completed-turn counters, independently reproduced by `tools/token_usage.py` from the private JSONL capture. The [usage summary](metrics/native-trial-usage.json) has complete reported coverage for that captured turn. That coverage says nothing about workflow success, undocumented child usage or billing. No dollar cost or representative average is inferred. See [measurement guidance](TOKEN_USAGE.md).

## What actually happened

- A fresh project-local `.agents/skills/just-build` copy was used. Native command events show the host reading its entry point and references; the logical skill files were unchanged afterward. This verifies native discovery for this one installation, not a clean-machine/personal-profile matrix.
- The initial restricted launch failed in 0.153 seconds before a model turn began because the runtime state DB/app-server initialization was denied. One approved sandbox escalation enabled the same pristine project to run. This environment assistance is recorded; there were **zero builder steering or repair interventions** during the model run.
- The builder created a local HTML/JavaScript app, README and tests. Seven initial tracked commands passed: event probe, journey, edge, first-run, recovery, loopback smoke and markup. The app's initial draft preceded the recorded plan; that chronology is retained rather than reconstructed.
- Research, Plan, Implement and Verify reached done. **Quality remained blocked**; Polish, final verification and handoff remained pending. Read-only diagnostics independently confirmed `complete: false` and current stage Quality. No complete final handoff report was observed.
- Actual delegation encountered a thread-store/context error. The builder disclosed sequential single-agent fallback; there is no independent-review claim. Offline research limitations were also retained.
- A separate evaluator reran four builder-authored Node test groups: journey, edge, first-run and recovery. They execute the delivered JavaScript event boundaries in a minimal DOM fixture. They do not establish browser rendering, keyboard interaction or screen-reader behavior.
- The evaluator's later loopback smoke was environment-blocked by the outer sandbox socket policy (WinError 10013); it was not retried or relabeled a pass. The independent browser tool rejected the README's file-URL launch by policy. No alternate URL/server/browser workaround was attempted, and there were no real-browser observations.

The [portable trial record](metrics/native-trial.json) retains stages, profiles, durations, usage and failures. Raw logs, personal paths, credentials and the private ledger are excluded. A separately delivered source demo preserves the seven public program/test/document files, with packaging metadata clearly separate from their recorded hashes.

## Interpretation

This trial adds observed native Codex discovery and a concrete token measurement. It also demonstrates that a runnable app and successful unit checks can still receive an honest partial workflow result when required usability evidence is missing. It does not close the web/UI public-journey gate, test Auto idea discovery, establish Claude Code compatibility or estimate general autonomous success.

Next collect actual browser first-use/recovery/keyboard/narrow-layout checks, current-source independent reviews and final verification. Use [HOST_VALIDATION.md](HOST_VALIDATION.md). A later assisted completion is a separate follow-up; it must not rewrite this original unassisted builder outcome.
