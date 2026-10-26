# Projects built with Just Build

These are two runnable Python standard-library projects produced by actual fresh Codex-agent trials on 24 October 2026. They exercise different workflow entry paths in the same CSV domain.

| Example | How it was chosen | Run from its directory |
|---|---|---|
| [CSV Preflight](csv-preflight/README.md) | Auto researched and compared a pool using an explicit evaluation persona | `python -B app.py examples/bad.csv --json` |
| [CSV Intake Check](csv-intake-check/README.md) | A named project with requirements fixed before implementation | `python app.py check examples/valid.csv --json` |

Preflight offers bounded, location-only audits and optional new report files. Intake Check offers a fixed JSON interface with physical start-line diagnostics. Their header and blank-line policies differ; consult each README. Both preserve input bytes and require no network, account, dependency install or API key to run.

Run both projects' tests, source-integrity checks and additional public CLI checks from the repository root:

```sh
python tools/run_examples.py --report test-results-examples.json
```

The runner copies each project to a temporary directory before testing. It does not call a model, repeat online research or install anything. Windows/Ubuntu and Python 3.11/3.13 CI jobs run this same command.

The original program, test and fixture bytes are preserved. Packaging adds generation notes and sanitized verification snapshots, and adjusts README provenance links. Private workspace paths, host installs, raw events and local `.just-build` ledgers are excluded. The snapshots document actual assisted trials; they are not cryptographic attestations or replayable ledgers. Each [Preflight generation note](csv-preflight/GENERATION.md) and [Intake generation note](csv-intake-check/GENERATION.md) records failures, interventions and reviewer reuse.

These examples demonstrate local CLI delivery. They do not establish market demand, best-possible idea selection, successful web/mobile builds, unattended success rates or Claude Code host behavior. The root [MIT license](../LICENSE) covers these sources.

CSV Preflight later exercised the first-time-user/advocate process. A separate listener added a small returning-use README example, and a fresh unprimed actor completed the task. App/test bytes stayed unchanged. See [actual usability evidence and limitations](../docs/USABILITY_EVALUATION.md).
