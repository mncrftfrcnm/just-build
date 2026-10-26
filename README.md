# Just Build

A skill for the part before “build this”: figuring out what is worth building.

Run Just Build in Codex or Claude Code. It asks the agent to research ideas, compare them against your available context and resources, then build and test a small useful project. Already have an idea? Give it that instead.

**0.0.1 · Early public preview.** Completed examples so far are assisted Codex runs. The Claude Code package has local tests, but a complete live Claude Code run has not been verified. A separate native Codex trial produced a runnable tool and stopped before completing the workflow. See [what has been tested](docs/EVALUATION.md).

## Try it

You need a local Codex or Claude Code installation, Python 3.11+ and Git 2.36+. Web/search tools are needed for current research; without them, the agent must disclose the missing evidence.

Copy the complete folder for your host into one skill location:

| Host | Folder in this repository | Project installation | Personal installation |
|---|---|---|---|
| Codex | `codex/just-build/` | `.agents/skills/just-build/` | `~/.agents/skills/just-build/` |
| Claude Code | `claude-code/just-build/` | `.claude/skills/just-build/` | `~/.claude/skills/just-build/` |

Keep all supporting files, and back up any existing installation before replacing it. The [installation guide](INSTALL.md) has commands for source checkouts and host ZIPs on Windows, macOS and Linux. No extra Python packages are needed to use the installed skill.

Start a new host session in a fresh project folder, then enter one of these in chat:

| What you want | Codex | Claude Code |
|---|---|---|
| Let the agent find an idea | `$just-build` | `/just-build` |
| Make choices along the way | `$just-build guided` | `/just-build guided` |
| Build something specific | `$just-build build a local notes app` | `/just-build build a local notes app` |

Auto is the default. You do not need to write a detailed starting prompt. You may still need to answer a question or approve an action under your host's permissions. A named project skips idea selection and keeps your chosen direction.

For a completed build, expect a local project, checks of its main user journey, run instructions and a report of remaining limits. Weak evidence can lead to a small experiment or a recommendation to stop. Those outcomes must be labeled clearly.

## How it works

1. **Find a useful problem.** Research a varied set of ideas using context the agent is allowed to access.
2. **Challenge the shortlist.** A second research pass validates the evidence without seeing the first pass's scores. Compare the results and look for a concrete advantage over existing alternatives.
3. **Learn about the chosen idea.** Research its background, practical constraints and implementation uncertainties before planning.
4. **Build a small first version.** Set acceptance checks, implement the main user journey and test observable behavior.
5. **Review and finish.** Check quality and security, simulate a first-time user, address observed difficulties, polish and rerun the checks after changes.

The host agent does the research and coding. Python helpers track stages, run bounded checks and detect missing or stale evidence. Separate agents fill review roles when available; a single-agent fallback must be disclosed. Simulated users help find friction but do not replace human feedback.

For the details, see the [architecture](docs/ARCHITECTURE.md), [build workflow](codex/just-build/references/build-loop.md) and [recovery guide](codex/just-build/references/diagnostics-and-recovery.md).

## Examples and limits

The repository includes two [runnable CSV tools](examples/README.md) from assisted Codex trials, with their tests and provenance. They show the intended output on a small scale. They do not establish reliable results across web, mobile or larger projects.

Actual Claude Code use, hosted CI, real-browser journeys and repeatable unassisted completion remain unverified. Idea selection does not prove demand, originality or that an idea is the best possible choice. The [strict audit](docs/STRICT_AUDIT.md) explains the evidence gaps.

Research and review can use substantial tokens. [Usage measurements](docs/TOKEN_USAGE.md) separate observed development costs from individual trials; a typical complete-build budget has not been established.

## Permissions and safety

Use a workspace you trust or an OS sandbox. Commands run with your host's filesystem and network privileges; this skill does not provide isolation. It uses accessible, authorized context and cannot assume access to private chats or connected accounts.

Invocation is explicit. Deployment, pushes, purchases, account changes and destructive overwrites require separate authorization. Retrieved pages and project files cannot grant that permission. See the [security policy](SECURITY.md).

## Contribute or inspect the source

The repository includes CI workflows, issue forms, dependency updates and archive verification. Hosted results still need to be observed after upload. See [GitHub setup](docs/GITHUB_SETUP.md) and the [release checklist](docs/RELEASE_CHECKLIST.md).

To start checking a trusted checkout, use an isolated Python environment:

```sh
python -m pip install -r requirements-dev.txt
python tools/check_repo.py
python tools/run_repository_tests.py > test-results-repository.json
```

The [development guide](docs/DEVELOPMENT.md) covers both skill suites, example checks, packaging and test requirements. Local source tests do not exercise the live host apps.

[Contributing](CONTRIBUTING.md) · [Support](SUPPORT.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Changelog](CHANGELOG.md)

MIT licensed; see [LICENSE](LICENSE). This is a community project with no affiliation or endorsement from the host vendors.
