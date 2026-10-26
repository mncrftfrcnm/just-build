# The build loop (both modes)

> Idea-led new builds enter this loop only after a corroborated `build` outcome. Scaffold with `--selection`, not the legacy debate flags; tracker startup revalidates the dossier. See `references/corroborated-selection.md`. The build stages below are unchanged.

The active coding agent implements the actual code; the stdlib tracker enforces stage ordering and records local evidence. Report to the user after selection, plan, significant build milestone/blocker, first verification, and final review/handoff. Don't repeatedly paste the plan or full test logs. Reopen only the reference for the current phase to limit context use.

On resume or a rejected transition, use `diagnose --state-dir "$RUN"` and read `references/diagnostics-and-recovery.md`. It inspects missing/stale evidence and suggests a next action without running tests or rewriting state. It cannot override a gate. Continue state must be outside the entire project; nested paths are rejected before creation.

Stages: **research → plan → implement (scoped online research + incremental probes) → verify → quality → polish → final-verify → handoff**. For rigorous builds read `references/autonomous-development.md`. Record every planned implementation research topic during `implement` using `research --state-dir "$RUN" --file <topic-research.json>`; at least one honest web source is required for each topic, and at least one passing in-development probe before `implement done`. If web is unavailable, fall back to standard enhanced and disclose that rigorous web grounding was not available; don't fabricate sources. `PROGRESS.md`, `WORKFLOW.md`, `PLAN.md`, `ARCHITECTURE.md`, `BRIEF.md`, `REVIEWS.md`, `REPORT.md` regenerate from `run.json`. A green report requires both review records and fresh final acceptance tests. Reviewer observations are agent-supplied, test exit codes are locally executed evidence.

Before completing Research for a new project, follow `references/chosen-idea-research.md`. Record useful background, sources and plan implications in the initialized run; a named project keeps its chosen direction. Continue uses only context needed for its scoped change.

Initialize state: New uses scaffolded `<new-project>/.just-build` (`decision.json` already present). Continue uses a fresh empty state folder **outside** the repo. Example:

```sh
T='python3 <skill-dir>/scripts/run_tracker.py'
$T start --state-dir "$RUN" --project "$PROJECT" --mode auto --operation new --goal 'Concrete user outcome'
# Complete the chosen-idea briefing from references/chosen-idea-research.md here.
# Save CHOSEN_IDEA_RESEARCH.md in RUN and record actual findings with phase: idea.
$T step --state-dir "$RUN" --stage research --status done --note 'Chosen-idea background and plan implications recorded'
$T step --state-dir "$RUN" --stage plan --status active --note 'Acceptance design'
$T plan --state-dir "$RUN" --file /path/to/project-specific-plan.json
# For enhanced CLI/API plans, use `"contract_profile": "external-cli"` or
# `"external-api"` (enhanced API + full security), and freeze a
# project-specific outside-the-project manifest before plan completion:
$T contract --state-dir "$RUN" --file /path/to/behavior-contract.json
$T architecture --state-dir "$RUN" --file /path/to/project-specific-topology.json
$T step --state-dir "$RUN" --stage plan --status done --note 'Plan recorded'
$T step --state-dir "$RUN" --stage implement --status active --note 'Implementing slice'
# The active agent now researches plan-specific APIs or UX patterns using available live web tools,
# saves short source records via `research`, implements working feature slices and regression tests,
# and runs diagnostic probes using `test --label probe-<feature>` while implement is active.
# The active agent writes runnable code, README and tests; replace scaffold placeholders.
$T step --state-dir "$RUN" --stage implement --status done --note 'Runnable slice and assertions implemented'
$T step --state-dir "$RUN" --stage verify --status active --note 'Initial acceptance run'
$T structural --state-dir "$RUN"  # New only
$T contract --state-dir "$RUN"  # When external-cli or external-api is selected; run in both verify phases
$T test --state-dir "$RUN" --label unit -- python3 -m unittest discover -s tests
$T test --state-dir "$RUN" --label smoke -- python3 smoke.py
$T step --state-dir "$RUN" --stage verify --status done --note 'Planned checks passed'
```

For new enhanced CLI or API builds use `references/behavior-contracts.md` with the required `external-cli` or `external-api` profile. New builds should use `examples/rigorous-build-plan-v08.json` (`quality_profile: enhanced`, `autonomy_profile: rigorous`, `experience_profile: v08`) when web tools are available; use `examples/enhanced-build-plan.json` if not. The rigorous plan requires 2–4 distinct implementation research topics. The tracker can check the shape and presence of sourced records, but cannot independently verify URL contents or that the active agent actually browsed. Old plans remain supported through `examples/build-plan.json` (one concrete journey, distinct *journey* and *edge* assertions, 2–6 tasks with unique labels, plus a **different** black-box `smoke_label`). For enhanced plans, include `"test_command": ["python3", "-m", "unittest", "discover", "-s", "tests"]`; include `"smoke_command": ["python3", "smoke.py"]`. Safe Python interpreter switches such as `-B` are supported before `-m` or a local assertion-bearing script; scripts may take arguments. Optimizing switches that disable assertions are rejected. These are exact argv lists, NOT shell command strings: use exactly the same argv when calling `test ... -- <argv>`. Bind real assertion-bearing checks, never placebo commands. Unbound labels are accepted for backward compatibility but have weaker evidence. A failed or stale label must be rerun under the same label. Test commands run without shell and with closed stdin, bounded timeout and output; run state persists command hash/exit/duration/snapshot digest, not stdout or full argv. Review commands for safety first.

When recording a new enhanced plan, the tracker requires `security_profile: full`, `experience_profile: v08` and the matching external contract for CLI/API surfaces. Both recommended templates include these fields; freeze a project-specific contract before completing Plan. Existing recorded plans and Continue remain compatible. Recognized unittest/pytest skipped-test summaries, including partially skipped suites, cannot satisfy required labels; run optional checks separately. This output check is a conservative signal, not proof that an arbitrary test runner executed meaningful assertions.

**Source freshness:** Every required label and (for new apps) the most recent structural check must cover the *same* current content snapshot when completing `verify` or `final-verify`. A test that changes eligible project files cannot count until rerun on stable source. If one acceptance test runs before a code edit, repeat it after the edit. Completed first verification remains historical, allowing the reviewers to make fixes; final verification is live and invalidates on any later eligible source edit. Generated `dist`, `build` and `.next` outputs are excluded by default. Declare the concrete runtime files in optional `plan.delivery_artifacts` (safe relative file paths, no globs/directories). The tracker hashes these declared files into all acceptance/review/security/final snapshots and refuses missing outputs outside implementation probes. Rebuild and exercise the actual delivery path before handoff. Undeclared ignored outputs remain outside freshness guarantees. See `references/delivery-artifacts.md`.

**Execution budgets:** The supervisor captures at most 2 MB of combined stdout/stderr
per command by default, without a disk log. Overflow, timeout or incomplete cleanup
is a failure. It terminates remaining normal descendants when the command ends;
tests must not rely on background services surviving the test command. On Windows
use a reviewed executable/interpreter argv instead of an implicit `.cmd`/`.bat`
launcher, including when adapting npm-based examples. See research-and-safety.md
for the host-privilege and containment limits.

Now follow `references/reviewers.md`: during active Quality, new-project enhanced plans run `references/novice-usability.md` (first-time-user attempt, separate advocate, current-source retest after fixes), then record Quality approval and final Polish. `review --role <quality|polish> --file <JSON>` saves their judgments. `BRIEF.md` and `USABILITY.md` provide compact context to Polish. Any subsequent edits require `recheck` and fresh profiled usability/Quality/Polish approval. Then:

```sh
$T step --state-dir "$RUN" --stage final-verify --status active --note 'Post-review retest'
$T structural --state-dir "$RUN"  # New only; repeat after review edits
$T contract --state-dir "$RUN"    # Required for frozen external-cli/external-api profiles
$T test --state-dir "$RUN" --label unit -- python3 -m unittest discover -s tests
$T test --state-dir "$RUN" --label smoke -- python3 smoke.py
$T step --state-dir "$RUN" --stage final-verify --status done --note 'Fresh acceptance run passed'
$T step --state-dir "$RUN" --stage handoff --status active --note 'Summarizing delivery'
# No project modifications after final-verify; changing project files invalidates the final fingerprint.
$T step --state-dir "$RUN" --stage handoff --status done --note 'Runnable instructions and limitations delivered'
$T report --state-dir "$RUN"
```

Each exact command is illustrative: replace `unit` and `smoke` with **every** label required by the actual plan, and use real project commands. If `final-verify` fails while active, inspect/fix and rerun **every** required check on the new snapshot; never relabel a fake command as acceptance. Source edits also invalidate prior reviews: after completed Quality use `$T recheck --state-dir "$RUN"` before fresh approvals and final tests. Both passing reviews must cover current files in all profiles. If blocked, mark stage `blocked`, explain partial and later reactivate that same stage. `final-verify` is a fresh phase: old passing labels cannot satisfy it. After final verification, source changes block handoff; recheck is available only before handoff is done. It conservatively reopens both reviews and final checks so late fixes receive fresh scrutiny. Once handoff is complete, start a new run. Legacy `run.json` schema v1 is intentionally *not* silently upgraded: preserve it and start a fresh continuation state folder for that repository. Eligible source files are bounded (symlink/large-file protections); report rather than skip unverified files.

When available, update architecture status from `planned` to `observed` backed by real components. Mermaid charts are optional reading aids, not grounds to delay application delivery. Keep project code free of generic marketing copy, lorem ipsum, fake users and unverified metrics.

Use `references/prompting.md` for explicit user outcomes, observable tests, short repair loops and reviewer context compression; never treat its patterns as extra mandatory phases.

## Product quality / UI polish (not skill UI)

An enhanced plan declares `surface` (`cli|web|desktop|api|library`), `polish_targets`, and a `focus` per task. The tracker requires separate **journey** and **edge** acceptance tasks with exact bound test commands, plus bound smoke. Ensure the edge test asserts an actual failure/error state and the smoke runs the public entry point from a user's perspective. For web/desktop, explicitly include visual-hierarchy, empty/error state, narrow viewport and keyboard targets; exercise them with browser facilities when they exist; where unavailable, record the gap rather than marking it tested. For CLI, exercise `--help`, first-run, empty input/output and actionable errors. For API, check documented request/response and structured failure details. Tests should inspect observable behavior, not just file existence. Add targeted regression tests for every substantive reviewer fix; don't pad suites with trivial truth assertions.

For an existing external black-box benchmark, run it as an additional quality check, outside the generated project's own test suite (e.g. `benchmarks/task_board_blackbox.py --project <path>` for the bundled fixture). No benchmark fixture can universally judge arbitrary products; add project-specific real-user checks before promising readiness.

The polish reviewer must include `target_evidence` matching every planned target (see `examples/enhanced-polish-review.json`). Mention the concrete screen, command, fixture or user path examined. A `pass` cannot coexist with a target marked `needs-work`; required targets can't be waved away as not applicable. Keep typography, spacing, control labels, contrast, empty/loading/error states, keyboard flow and responsive layout coherent where relevant. Prefer a restrained, believable product to generic gradients, stock placeholders or invented social proof. Preserve no-UI projects as CLI/API; never build a browser interface for Just Build itself.

## First-run experience profile

For new builds use `examples/rigorous-build-plan-v08.json` with `experience_profile: v08` and 2–4 `experience_checks` (scenario, expected, test_label, test_command). Require first-run plus a different user-visible scenario. Every label is command-bound and must pass in verify and final-verify on stable source, in addition to journey, edge, smoke and structural checks. Legacy plans need no migration. Read `references/experience-and-polish.md` only when planning or reviewing.

New-project enhanced plans also require `usability_profile: novice-v1`. This adds snapshot-bound observation and advocate approval within Quality, before Polish; it does not replace executable experience checks or add tracker stage names. Read `references/novice-usability.md` when dispatching these roles. At most three first-user rounds per run keep repairs bounded; unresolved substantial issues are reported as blocked.

## Final security gate (new enhanced builds)

Set `security_profile: full` during planning. After the polish pass follow `references/securer.md`; scan, remediate, and rerun prior reviews after changes before final verification. A failing security gate blocks completion. Avoid treating offline CLIs as public network servers.
