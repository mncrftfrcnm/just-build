# Bind the files users actually run

When runtime output lives in an ignored directory, declare the exact files in the
acceptance plan. Source snapshots already cover normal source files, but ignore
`dist`, `build`, `.next`, dependencies and caches by default.

```json
"delivery_artifacts": ["dist/app.js", "dist/index.html"]
```

Use only project-relative regular file paths: no directory/glob, traversal, drive,
symlink/junction components or duplicate/case-alias entries. Limits are 32 files,
8 MB per delivered file and 20 MB total, in addition to the source snapshot budget.
Declare the public entry and other generated assets required for the actual first
journey. This does not replace running the built user journey or reviewing its
dependencies. Do not list secrets, local ledgers, caches or generated test reports.

Missing outputs are allowed during planning and implementation probes. Required
verification, contracts, structural checks, reviews, security and final handoff
need every declared file. A changed declared output invalidates old results just
as changed source does. A test/build that rewrites outputs cannot count as stable
acceptance until repeated against unchanged delivered bytes; avoid embedding
changing timestamps in release output.

After a later output edit, rebuild as needed, use `recheck`, refresh the reviews
and rerun final acceptance. Never remove a declaration merely to hide a missing or
broken deliverable. Empty/absent manifests preserve historical source-only
snapshots. Undeclared ignored files remain untracked; the manifest is an explicit
honest plan, not proof the agent listed every dependency or an OS isolation boundary.
