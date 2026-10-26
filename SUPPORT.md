# Getting help

Start with the [installation guide](INSTALL.md) and [first-run examples](README.md), the [development guide](docs/DEVELOPMENT.md) for repository tools, and the [evaluation record](docs/EVALUATION.md) for supported evidence and limits.

For a reproducible bug, use the repository's Bug report issue form. Include the prepared release/commit, host, OS, Python version, exact command, expected behavior and redacted actual result. Prefer a tiny fictional fixture over a private project or chat transcript. A blocked or no-build outcome can be legitimate; report the evidence or behavior that seems wrong.

For a suggested improvement, use Feature request and describe the user outcome and a concrete example. For actual skill runs, use Evaluation report, distinguishing live agent work from deterministic fixtures and noting assistance, review-role reuse and failures.

For suspected vulnerabilities or exposed secrets, follow [SECURITY.md](SECURITY.md). Keep sensitive material out of public issues. Support is handled through repository issues; response times are not guaranteed.

The installed skills use Python's standard library; repository-maintenance checks additionally use the pinned development requirement. A passing source-package test is not an actual host run. GitHub settings and CI results only exist once configured/observed in the chosen repository.
