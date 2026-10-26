# Clean-host validation

This is a procedure for collecting missing evidence, not a record of passing runs. The recorded results and limitations are in [EVALUATION.md](EVALUATION.md). Source tests for both packages do not establish that both hosts can discover, invoke and complete the skill.

## Prepare the candidate

1. Use the exact reviewed commit, and the release ZIPs built from it. Run `python tools/verify_release.py --artifacts <artifact-directory>` from that trusted checkout before installation. Record the full commit, ZIP SHA-256, package host in a run record outside the skill folder.
2. Use a fresh disposable project and a fresh host conversation. Record the operating system, Python, host and model versions, enabled tools, approval/sandbox settings and any existing user/repository instructions. Record whether personal skills or other customizations remain active; a new conversation alone is not a clean host profile.
3. Install the host ZIP's complete `just-build` folder into the project skill location listed in [README](../README.md#install). Preserve existing installations and avoid two active copies. Use the host's normal refresh/restart process. Do not preload the skill contents or supply private helper paths in the test prompt: discovery and invocation are part of the test.
4. Confirm that Python and the intended web/browser/delegation tools are actually available to the host. An unavailable host or capability is `not run`, with its reason. Do not silently replace a Claude Code run with Codex or a browser journey with source inspection.

Run each host separately. A maintainer may prepare the environment and initial task, but any prompt correction, parser repair, manual ledger edit, injected helper command or implementation rescue during the run makes that run **assisted**. Keep its original failures and time in the record. A later clean attempt is a separate run; it does not erase the assisted attempt.

## Observe the actual host

Use the host-native invocation from README in an otherwise fresh conversation. Save the exact initial request and transcript or tool trace. Use the three scenarios and per-host rubric in the [live evaluation protocol](../codex/just-build/benchmarks/LIVE_EVAL_PROTOCOL.md): blank-folder Auto, a small local web app, and continuation of an unknown dirty repository. Freeze the evaluator's expected public behavior before implementation and give the builder only the task specification, not the evaluator's hidden cases.

The evaluation record must distinguish discovery/invocation, implementation, final tracker status and independent public checks. A complete tracker is evidence of the recorded workflow, not a substitute for the evaluator launching the delivered artifact. A valid experiment/no-build is a selection outcome and must be reported separately from completed application delivery. Missing delegation is a disclosed fallback, not an independent review.

For the web scenario, a useful bounded task is a local task list with a persisted add/complete/reload journey, an understandable empty state and a recoverable invalid-input state. No deployment, account setup or paid service is needed. A separate evaluator who did not author the app should:

- Start from the delivered README on a clean copy and launch through its documented command. Record prerequisites, first launch, port/URL and actual startup failures.
- Exercise the public add, complete and reload paths with real browser controls, checking visible state and persistence. Try empty/invalid input and a documented recovery path. If the design has asynchronous behavior, exercise loading and failure states.
- Check desktop and 390-pixel layouts, keyboard-only operation, visible focus, labels and reduced-motion behavior where applicable. Save screenshots and browser observations actually captured by tools.
- Retest those journeys on the final delivered bytes after reviews or repairs. Record the source/artifact digest, commands, browser viewport and concrete outcome for each check. Passing unit tests or reading event-handler source cannot replace these observations.

If the evaluator changes the application or explains a fix to the builder, retain the failed outcome and mark the repaired run assisted. Do not weaken frozen acceptance to fit the delivered behavior. Use the protocol's 3/3 initial passes per host only as its stated wider-alpha gate; three attempts do not establish a general success rate or market usefulness.

## Keep a reviewable record

For every attempt retain the run identifier, date, host/model/tool versions, exact candidate digest, initial task, result (`pass`, `fail`, `partial` or `not run`), elapsed time, human/maintainer interventions, observed usage and its source, generated artifact, tracker report and independent checks. Use `unknown` for unavailable usage; estimates and helper-process usage must not be presented as native host totals. Redact secrets and personal context before sharing evidence.

Keep hosted release verification separate. Once an owner/repository is chosen, follow [GITHUB_SETUP.md](GITHUB_SETUP.md) to observe standard CI and manually verify the exact reviewed commit. Preserve run URLs, each matrix result and artifact identity only after the aggregate succeeds. Checked-in workflows and local workflow-policy tests do not establish hosted execution, branch protection, release publication or account settings.

Current missing evidence includes an actual Claude Code run, an observed hosted Windows/Ubuntu matrix, a web/UI delivery with independent browser journeys, fresh unassisted repetitions and authorized human feedback. Record new outcomes in the evaluation status only after observing them; no part of this guide closes those gaps by itself.
