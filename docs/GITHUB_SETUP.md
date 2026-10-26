# GitHub setup

Checked-in configuration prepares the repository; it does not configure an account or prove hosted checks passed. The owner/name is deliberately unspecified. Extract the source ZIP, preserve hidden `.github` files and push the contents to the chosen repository after review.

## Checks and branch protection

The [CI workflow](../.github/workflows/tests.yml) runs on pushes, pull requests, merge groups and manual dispatch, without path filters. It has read-only repository permissions and commit-pinned Actions. Repository tools run on Windows/Ubuntu with Python 3.13; skill and example matrices cover both systems and Python 3.11/3.13. Its final job is also named **CI**; it uses `always()` and fails if any required predecessor failed, was cancelled or was skipped. An entirely cancelled run must not be accepted as successful.

After the first observed passing run, configure a default-branch ruleset to require the **CI** check from the **CI** workflow. Confirm its exact displayed check name/source in GitHub rather than typing guessed matrix names. Require pull requests and appropriate review; dismiss stale approvals when appropriate; block force pushes and deletion; apply rules consistently to administrators. If enabling merge queues, verify the merge-group check before relying on it. Do not require the manual **Release verification** check for every PR.

Enable private vulnerability reporting and available secret scanning/push protection. Restrict Actions to reviewed sources, require appropriate approval for outside contributors and keep CI on disposable hosted runners without service secrets. The repository policy rejects privilege-bearing contexts, broad permissions, unpinned Actions, persisted checkout credentials, unsupported runners and untrusted shell expressions. This is a narrow project policy, not validation of every GitHub feature or upstream action's source code.

Repository reports are uploaded per OS even after normal test failures. Inspect their completion, exact source binding and skip lists alongside job status; [CI_EVIDENCE.md](CI_EVIDENCE.md) explains the artifacts and their limits. The local community-file validator checks the reviewed forms/maintenance subset before packaging.

## Issues and maintenance

Bug, feature and evaluation forms request reproducible public behavior and redacted evidence; blank issues are disabled. Security reports follow the separate root policy. Enable Discussions only if maintainers want to support it; no chat room or team is assumed. Add actual CODEOWNERS only after repository ownership/review responsibility is known.

Dependabot checks GitHub Actions and the development pip requirement weekly. Review and test those PRs; no auto-merge is configured. Generated release notes use `.github/release.yml` categories; see the [official configuration reference](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes). Optional labels are `breaking-change`, `security` and `skip-changelog`, alongside GitHub's common `bug`, `enhancement`, `documentation` and `dependencies`. Create any missing labels manually if you choose to use them; this file does not create labels. Unmatched PRs fall into Other changes.

## Verify a candidate

1. Review a clean commit with the intended changes and updated changelog, and observe standard CI on that commit.
2. Obtain the full lower-case 40-character commit SHA (`git rev-parse HEAD` from that checkout).
3. Manually run [Verify release candidate](../.github/workflows/release-check.yml), supplying the exact commit SHA. The workflow checks that its checkout matches the supplied SHA and repeats the full test matrix. No prior unobserved success is assumed.
4. Inspect the resulting candidate packages and reports only after **Release verification** succeeds. Artifacts have finite retention, so save reviewed release assets before they expire. Do not use artifacts from a failed/cancelled run.
5. Follow [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for explicit publication. No workflow creates a release, pushes a tag, changes branch rules or writes repository contents.

Local archive verification requires the corresponding trusted checkout. Run `python tools/verify_release.py --artifacts dist` there. It validates the three ZIPs and checksum file, exact member sets/content, host install layout and bounded archive structure without extraction. It detects mismatches against that checkout; it does not establish the checkout's authenticity or cryptographically sign a publisher.
