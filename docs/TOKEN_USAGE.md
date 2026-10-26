# Token usage and measurement

Just Build is a skill executed by the selected host/model. It does not have a fixed token cost. Research breadth, context size, reviews, retries, tools, model and caching affect each run. Python regression tests do not call a model; running those tests adds no model-token usage by itself. An agent reading their results still uses model tokens.

## Observed development usage

Snapshot through **2026-10-25T12:32:45.587Z**. These are observed local per-response usage counters, not text-length estimates, billing amounts or an average build budget.

| Scope | Input | Cached input, included in input | Output | Input + output |
|---|---:|---:|---:|---:|
| Main development chat | 82,406,933 | 81,093,760 | 432,730 | 82,839,663 |
| Development chat and recorded descendant agents | 145,686,086 | 142,374,784 | 849,401 | 146,535,487 |

The combined recorded input includes **3,311,302 uncached input tokens**. Cached input is already included in input; reasoning output is already included in output. Adding either subset again would double count it. Large totals reflect repeated processing of context across a long iterative development effort. They do not describe unique words written or a single prompt's context size.

The audit used 1384 unique response records from 36 related threads. It followed explicit parent/descendant session metadata, included only each record's owning thread, rejected conflicting response identities and summed per-response usage rather than cumulative snapshots. It excluded inherited fork records and duplicates where present. The [sanitized snapshot](metrics/development-usage.json) records the method, cutoff, per-role totals, private source-prefix hashes and limitations. Raw transcripts, personal paths, credentials and session/response identifiers are excluded from this repository.

This is an **observed lower bound** for project development. Missing/deleted logs, unreported usage, platform supervision and independent native CLI runs are outside that total. It is not account-wide usage or an invoice. The snapshot is fixed; work after its cutoff is excluded. Internal local rollout fields were inspected as present on this machine and are not a supported stable API.

## Earlier build observations

| Recorded builder branch | Input | Cached input, included in input | Output | Input + output |
|---|---:|---:|---:|---:|
| CSV Preflight Auto builder and its descendant agents | 10,704,447 | 10,536,192 | 47,805 | 10,752,252 |
| CSV Intake Check named builder and its descendant agents | 5,788,200 | 5,724,672 | 21,375 | 5,809,575 |

These are partial historical builder-branch measurements. They exclude maintainer interventions and separately coordinated reviews in other branches, and both builds needed assistance. They are neither complete end-to-end costs nor representative performance estimates. An assisted run and a valid experiment/no-build must retain their actual outcome.

## One measured native run

The historical [native offline reading-time trial](NATIVE_TRIAL.md) ran for 497.216 seconds with zero builder interventions and one startup environment escalation. Its actual captured turn used **1,230,191 tokens**: 1,216,432 input (including 1,167,616 cached), plus 13,759 output. Uncached input was 48,816. These native CLI counters are outside the earlier development snapshot's scope.

The tracker honestly remained incomplete at Quality because browser usability could not be exercised. Complete captured-turn usage is not a completed skill build. One named offline partial run is not an average cost or a future budget. See the [machine-readable usage summary](metrics/native-trial-usage.json).

## Capture a new native Codex run

Codex documents machine-readable `codex exec --json` output, including a completed-turn `usage` record. See the [official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Host versions can differ; inspect your installed `codex exec --help`. Do not copy these counters from examples and present them as measurements.

Save one complete JSONL capture per independent run in a **private directory outside the skill and distribution roots**. A transcript can contain project data, prompts, file contents, commands and tool output. Review and sanitize before sharing any evidence. The repository ignores `*.jsonl`; Git ignore rules are not a security boundary, and release tools distribute files under their explicit source roots.

From the repository root, summarize explicitly selected disjoint captures:

```sh
python tools/token_usage.py ../private/run.jsonl --output ../private/usage.json
```

The tool reads only supplied files, uses no network/model service, and emits a transcript-free JSON summary with source hashes and coverage. It never scans your account or automatically imports your host history. Keep output outside the skill folder: creating it inside a tracked project or package may change its source fingerprint. The output must be a new file; existing files and input bytes are preserved.

Exit status 0 means complete reported coverage for the recognized captured turns, 1 means partial/unknown coverage, and 2 means invalid input or an operational error. A missing usage record is unknown, not zero. Reported contributions can exist in an incomplete/failed capture; coverage must accompany the number. File bounds or rejected malformed input produce no saved report.

Pass all reviewer/child captures separately if the parent does not report their usage. The CLI cannot prove completeness outside the supplied traces. It rejects duplicated paths, file identities and identical contents, but cannot detect every overlap across edited or partial captures because completed-turn events do not provide a stable turn identifier. Select disjoint full captures yourself. Do not add usage from a child twice if a host already included it in the parent's counters. This tool supports the documented Codex exec event shape; Claude Code and local internal-rollout formats are not automatically supported.

## Keep work proportional

Use a named project when the user already chose one; it skips unnecessary idea selection. Bound the first user journey and research uncertainties before implementation. Load mode-specific references when needed, and give reviewers compact relevant context instead of the entire development history. Use deterministic helpers for repeatable validation and rerun the checks affected by actual edits or failures. Preserve required independent reviews and freshness gates.

Set an explicit time/usage budget when the host can expose or enforce one. If essential evidence is unavailable or the budget runs out, return an honest partial result or no-build decision. Do not silently remove gates or claim the budget was enforced by a prompt. These are practical controls, not a measured token-saving guarantee.

## Compare runs responsibly

Record the source/package digest, task, host/model/version, available tools, outcome, elapsed time, interventions and coverage alongside counts. Use the same fixed public acceptance cases when comparing changes. Keep development totals, individual build results, partial attempts and static context sizes separate. More recorded tokens do not imply a better project; fewer do not prove a reliable one.

For cost comparison use your provider's actual current billing/plan rules and uncached-input, cached-input and output categories; a subscription usage limit is not a token invoice. This repository does not infer money spent or convert model tokens to dollars.

See [clean-host evaluation](HOST_VALIDATION.md), [current evaluation status](EVALUATION.md) and the [development guide](DEVELOPMENT.md).
