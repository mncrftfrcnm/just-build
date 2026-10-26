# Developing Just Build

## Prepare a repository environment

Use Python 3.11 or newer and Git 2.36 or newer. The installed skill packages require only the standard library. Repository workflow-policy checks use the exact development dependency in `requirements-dev.txt`.

Create an isolated environment with `python -m venv .venv`. Use its interpreter directly, or activate it using your platform's normal workflow:

| Platform | Environment interpreter |
|---|---|
| Windows | `.venv\Scripts\python.exe` |
| Linux/macOS | `.venv/bin/python` |

Below, `python` means that interpreter. No shell execution-policy change is needed when calling it directly.

```sh
python -m pip install -r requirements-dev.txt
python tools/check_repo.py
python tools/run_repository_tests.py > test-results-repository.json
```

Keep TEMP/TMP writable. Tests create disposable repositories, link fixtures, subprocesses and loopback servers; diagnose restrictions instead of silently skipping acceptance. Reports belong outside skill folders. See [evaluation limits](EVALUATION.md).

## Shared host code

Use `codex/just-build/` as the canonical shared implementation. Keep Claude's `SKILL.md`, `references/host.md` and Codex's `agents/openai.yaml` host-specific. Shared scripts, references, examples, tests and licenses must match.

```sh
python tools/sync_hosts.py --check
python tools/sync_hosts.py --apply
python tools/check_repo.py
```

Check is the default and changes nothing. Apply preflights both package trees, then replaces individual shared files atomically. It reports unexpected Claude files for manual resolution and never deletes them automatically. Review the diff before and after. It rejects linked/private/oversized inputs and preserves host-specific files. The batch is not a filesystem transaction or defense against a concurrent malicious writer; close competing editors while syncing.

## Validate the affected behavior

Run focused regressions while changing code, then the required checks for the affected area. Do not add tests that only match implementation wording or trivial success. Keep real agent trials separate from deterministic fixtures.

| Area | Required local checks |
|---|---|
| Root tooling, docs or CI | `python tools/check_repo.py`, `python tools/run_repository_tests.py > test-results-repository.json` |
| Shared skill behavior | Both host commands below, on unchanged source |
| Generated examples | `python tools/run_examples.py --report test-results-examples.json` |
| Release tooling | Build into a fresh directory, then `python tools/verify_release.py --artifacts dist` |

Run both installed-package suites from the repository root:

```sh
python codex/just-build/scripts/run_skill_tests.py --report test-results-codex.json
python claude-code/just-build/scripts/run_skill_tests.py --report test-results-claude.json
```

Source digest equality can carry forward an earlier full skill report for unchanged package bytes; do not describe that as a fresh test run. Hosted Actions is configured for Windows/Ubuntu and Python 3.11/3.13. A local result cannot establish that unobserved matrix passed.

## Submit and release

Explain the concrete problem, resulting behavior, actual validation and limits in the PR. Review dependency/action changes; pinned versions and commits need updates rather than blind auto-merge. Follow [community conduct](../CODE_OF_CONDUCT.md) and [security reporting](../SECURITY.md).

Update [CHANGELOG.md](../CHANGELOG.md) for meaningful release changes. [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) covers exact-commit verification, candidate artifacts and account-side GitHub settings. A maintainer chooses publication explicitly; these workflows never publish automatically.

## Native usage and host evidence

Use [TOKEN_USAGE.md](TOKEN_USAGE.md) for explicitly captured per-run model counters and [HOST_VALIDATION.md](HOST_VALIDATION.md) for clean-host/browser runs. The token summarizer is repository maintenance tooling, not an installed host telemetry collector. Keep raw transcripts private and publish only reviewed aggregate records with their coverage.

Repository reports use stdout for JSON and stderr for diagnostics; preserve their source binding and review omissions. See [CI_EVIDENCE.md](CI_EVIDENCE.md). The community-file checker is included in `check_repo.py`; update its reviewed subset deliberately when extending GitHub configuration.
