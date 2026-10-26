# CI evidence and community checks

This configuration makes local and hosted failures reviewable. It does not establish that GitHub has run the workflows, that repository protections are configured, or that either actual host completed a build.

## Run and retain repository tests

From the repository root, after preparing the isolated environment in [DEVELOPMENT.md](DEVELOPMENT.md):

```sh
python tools/check_repo.py
python tools/run_repository_tests.py > test-results-repository.json
```

Ordinary test output and tracebacks go to stderr; stdout is the JSON result. Reports belong at the root's ignored `test-results*.json` paths or outside the checkout, never inside distributed folders such as `tools/`, `docs/` or a skill. Shell redirection creates/replaces its destination; choose the report filename deliberately. Do not redirect onto an input or source file.

The runner discovers the actual repository suite and records completion, test/success events, failure/error identities, skips and their reasons, expected failures, unexpected successes, duration, Python/platform and the whole distributed-source digest. It returns a failure for test errors/failures, unexpected success, empty discovery, runner errors or source changes during execution. A report is attributable to a checkout only when its digest matches that exact source.

Standard unittest semantics allow capability skips and expected failures; these are reported as `passed_with_omissions`, never full coverage. To make skips fatal for an environment expected to support every fixture:

```sh
python tools/run_repository_tests.py --fail-on-skip > test-results-repository.json
```

Tests and subtests emit events, so `success_events`, failure/error events and skipped events do not always add up to `tests_run`. Read the actual lists and status rather than subtracting array lengths to invent a passing-test count. The runner is trusted in-process unittest execution; it supplies no independent timeout, output sandbox or hostile-code isolation. Hosted jobs retain their bounded timeout. An interrupted/crashed run can leave an empty or incomplete redirected file; never treat it as a completed report.

## Inspect hosted evidence

Both CI and exact-commit release verification retain the repository report per operating system as `repository-ubuntu-latest` or `repository-windows-latest`, for up to 14 days. Upload runs with `always()` so a normal test failure still leaves its JSON report. A timeout/cancellation or earlier setup failure may prevent a complete report; use the failed job's logs and retain that outcome. Source package and example reports keep their separate existing artifacts.

The workflow policy requires each validation job to retain exactly its intended report or verified package path. Reports cannot be redirected to an unrelated file, duplicated or made success-only without failing the policy. No service secrets, write permissions, new third-party action or publication step is added.

The aggregate `CI` / `Release verification` check examines predecessor **job** results. It rejects failed, cancelled and skipped jobs. It does not parse individual unittest skip lists. Review reported omissions separately before making compatibility claims or changing a release's support status. A passing job/JSON report does not prove actual Claude, browser, market or unassisted-build behavior.

## Community-file policy

`python tools/check_repo.py` includes the same checks as:

```sh
python tools/check_community.py
```

The reviewed subset validates the three issue forms, issue configuration, Dependabot and generated release-note categories. It rejects duplicate/invalid input IDs and labels, unusable dropdowns/defaults, incorrect required-field types, forms without required input, duplicate form names, empty PR templates, missing update ecosystems and release categories that lose or shadow the final fallback. Unknown fields require an explicit policy review, not a silent partial validation.

The evaluation form asks separately for final tracked outcome and optional measured time/usage. A runnable implementation with an incomplete tracker must not be submitted as a completed handoff. Missing usage remains unknown; do not paste private model transcripts or infer billing from token counts.

This is a project-specific subset, not a full GitHub schema or server-rendering test. For changes, consult [GitHub's form schema](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema), [Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference) and [release-note configuration](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes). No labels, owner names, contact destinations, account settings or hosted results are invented.

See [GitHub setup](GITHUB_SETUP.md), [release gates](RELEASE_CHECKLIST.md) and [evaluation limits](EVALUATION.md).
