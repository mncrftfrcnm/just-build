# Contributing

Keep changes focused and report what was actually exercised. Install no credentials or services for the deterministic suites.

## Shared code

The host folders are distributed independently. Maintain shared scripts, tests, examples, licenses and references in Codex, then use `python tools/sync_hosts.py --check` and explicit `--apply` to synchronize. Unexpected files require manual review; the tool never silently deletes them. Only `SKILL.md`, `references/host.md` and Codex's `agents/openai.yaml` are host-specific. Preserve those files and their explicit invocation policies. [The development guide](docs/DEVELOPMENT.md) explains preflight behavior and limits.

## Validation

Run the checks for the affected area in the [development guide](docs/DEVELOPMENT.md#validate-the-affected-behavior). Before preparing release assets, run all repository, both host-package and example checks, then build and verify the archives. New behavior should have a meaningful regression, including a negative case for acceptance or security controls. Do not replace failed checks with tautologies, skips or weaker contracts. Keep synthetic evidence explicitly marked; do not count it as live market research. Curated runnable projects belong under `examples/` with generation notes and truthful verification snapshots. Do not commit private local run ledgers, host installs, logs, credentials or release ZIPs. If example program/test bytes change, update their provenance and verification evidence instead of presenting the old run as a test of new code.

Prepare an isolated environment and install `requirements-dev.txt` before root-tool checks; installed skills remain stdlib-only. CI checks repository tools on Windows/Ubuntu with Python 3.13, and both packages/examples on both systems with Python 3.11/3.13. Packaging and the stable `CI` status require every prerequisite to succeed. Diagnose environment restrictions instead of silently skipping. Manual exact-commit verification repeats these checks without publishing.

Pull requests should explain the problem, resulting behavior, actual validation and remaining limits. Follow [community conduct](CODE_OF_CONDUCT.md). Update [CHANGELOG.md](CHANGELOG.md) when release behavior changes; packages intentionally use unversioned names. Actions and development dependency pins need review; Dependabot proposes updates without auto-merge. Workflow changes must satisfy the parsed policy and be explicitly reviewed before extending its supported profile. Use [SECURITY.md](SECURITY.md) for sensitive reports and [SUPPORT.md](SUPPORT.md) for other reports.

For GitHub-facing changes, run the structured repository suite and keep its report with the PR evidence. The [community and CI guide](docs/CI_EVIDENCE.md) explains schema coverage, report retention and test omissions. The evaluation issue form separates completed handoff from a runnable partial build and allows unknown time/usage rather than invented numbers.
