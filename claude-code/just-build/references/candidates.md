# Candidate evaluation contract (Auto, or Guided -> new project)

> This is the preliminary/legacy ranking schema. Final new idea selection uses `references/corroborated-selection.md`, including utility and evidence-backed differentiation.

For idea-led new projects, start with `references/idea-discovery.md` and its unscored 9–12 idea pool. Then produce `candidates.json` after shortlisting and before deciding. With a validated idea pool the agent supplies 4–6 candidates from distinct `seed_id` entries across at least three idea lanes (legacy helper still accepts 3–12 without a pool), each with scores 0..5; this helper computes weighted rankings, not evidence itself. Never fabricate trends, user history, or integrations to make a candidate win. If no verifiable dated trend source exists, set `trend_status: unverified` and all candidate `trend` scores to 0. Read `examples/diverse-candidates.json` and `examples/idea-pool.json` for the current shapes. Invoke:

```sh
python3 <skill-dir>/scripts/just_build.py rank --file /path/to/candidates.json --pool /path/to/idea-pool.json
```

Weights: interest alignment 0.35, dated trend evidence 0.25, feasibility of a runnable vertical slice 0.25, differentiation 0.15. A trend can only be called **verified** if at least one public source has a real event/publication date within the last 30 days; later validate the selected project's cited evidence in `spec.json`. A recent mention alone does not prove growth: describe the concrete momentum rather than asserting popularity. If current internet research isn't available, prioritize project utility and feasibility and be transparent about the missing trend signal.

The helper returns a deterministic ranked list, ties alphabetically. Do not overrule a top candidate silently; if practical constraints invalidate it, revise candidates and rerun ranking with an explanation. Keep the input beside the spec in the temporary work area and reference the winning reason in final report. User-provided explicit exclusions override ranking.

For a legacy run, `references/idea-debate.md` can challenge the two finalists using `just_build.py debate`. New idea-led builds proceed to `references/corroborated-selection.md`. Do not call a role-simulated exchange two independent models.
