# Maintainer self-use: Doc Path Check

On 25 October 2026, the primary Codex agent used the actual Just Build package to build a small offline Markdown link-checking CLI. The final public tracker `report` returned `complete: true`, with all eight stages done and current passing Quality, Polish, Security and usability gates.

This was a **maintainer-selected named-project trial**. It exercises the development workflow, not Auto idea discovery, real demand or global originality. The agent read the shipped skill/references and used its real helper APIs and CLI reporting. It was not a fresh native skill-discovery/installation test, an uninterrupted autonomous run or a human user study.

## Delivered slice

Doc Path Check inspects local inline Markdown targets, reports line-specific problems, preserves input and creates optional reports exclusively. It runs with Python 3.11+ standard library only. Network requests, reference links, full CommonMark conformance, heading anchors and bulk repository scanning are outside the documented slice.

Research consulted the [CommonMark link specification](https://spec.commonmark.org/0.31.2/#links), [Python 3.11 path handling](https://docs.python.org/3.11/library/pathlib.html#pathlib.Path.resolve) and [URL parsing security guidance](https://docs.python.org/3.11/library/urllib.parse.html#url-parsing-security). Three chosen-project entries and two plan-matched implementation entries recorded concrete scope and test implications.

Before implementation, the run froze five command-bound acceptance/experience labels and a six-step public contract in two scenarios. The contract checks typed JSON, report creation, overwrite refusal, input/report preservation and recovery. It was executed in both verification phases without weakening its assertions.

## What the process found

The first 16 tests passed, but independent Quality review found two parsing defects: an invalid closing fence exposed code as links, and an even backslash count hid a real link. Narrow fixes and two public regressions brought the suite to 18 tests.

Security review then identified a minor resource weakness in malformed-label scanning and amplified output. The maintainer fixed it before handoff: flat labels exclude nested opening brackets, destinations are capped at 2048 characters, and JSON over 256 KiB fails before report creation. Three additional regressions brought the suite to **21 tests**. Fresh independent Quality and Security rechecks passed.

The source change correctly made earlier approvals stale. Read-only diagnostics recommended `recheck`; that operation reopened the reviews while preserving the frozen plan, contract, historical first verification and usability attempts. Two actual first-user simulations and a separate advocate completed the public task on disposable copies. The second actor observed tool status 1 for a duplicate report. The advocate reproduced that wrapper behavior, confirmed the program's native status 2 and preserved report bytes, and accepted the minor capture discrepancy without changing the native contract.

The first reviewer JSON submission exceeded the validator's evidence length. It was rejected and retained; a compact fresh review was accepted. This exposed a useful instruction gap, so both host references now state the actual payload limits. A maintainer driver return-shape mistake and one incorrectly configured temporary-directory attempt were also corrected and retained in external verification evidence. They are not counted as product successes.

## Final evidence and scope

The completed run has **14 tracked test executions**, five research records, two retained novice/advocate rounds, fresh final structural/acceptance/contract checks and current source-bound approvals. The passive scan reported no findings; it is a heuristic scan, not security certification. No active probes, installs, deployment or account changes occurred.

The separately delivered `doc-path-check-demo.zip` preserves the original program, tests, fixtures, README and license, adding a sanitized `verification.json` with source hashes. Private run ledgers are excluded. The snapshot is a declaration of the observed run, not a replayable ledger or cryptographic proof of reviewer independence. This demo is separate from the repository's [two curated full-build examples](../examples/README.md).

This broadens local evidence beyond CSV tooling. An actual Claude Code run, observed hosted CI, web/UI delivery, fresh unassisted repetitions and authorized human feedback remain to be collected. See [evaluation status](EVALUATION.md).
