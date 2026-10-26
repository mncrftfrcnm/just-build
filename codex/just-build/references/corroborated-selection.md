# Two research passes and one comparison

Use for new projects when the user delegates idea choice. Respect a named project
or Continue instead. This replaces mandatory finalist debate; tracker build stages
stay unchanged. Legacy rank/debate files still work for older runs.

## Research A: relevance and opportunity

Start from the validated, varied pool and its traced shortlist. Freeze both inputs.
Use accessible user statements, actual resources, and public evidence to assess
each shortlisted candidate. Demand and usefulness matter more than hype. A source
mentioning a technology is background, not evidence of growing demand.

Record a sharp need, the smallest runnable journey, resource/privacy constraints,
and at least two existing alternatives (one can be the user's manual workflow).
Describe a concrete advantage in audience, workflow, data, accessibility, latency,
privacy or interaction. Include the observation that would falsify that advantage
and a small test. Do not claim worldwide novelty or invent competitor limitations.
Two product names and a renamed AI wrapper do not establish differentiation.

## Research B: try to disprove it

Use the same frozen pool/shortlist, user constraints and resource inventory.
Withhold A's scores, recommendations and conclusions until B has finished. B may
receive shortlisted IDs/names and unscored concepts; omit preliminary ranking
scores and advocacy prose from B's brief as well. The host keeps the full input
digest for provenance without exposing the ranking to B. In a single context,
collect both evidence sets before writing selection conclusions, and label the
limited independence honestly. If A's conclusions are already in that context,
do not claim a blinded B pass.
B may
rediscover the same facts, but must seek additional material evidence about need
or differentiation from a different editorial origin. Mirrored stories, URL query
variants and two pages from the same author are not independent corroboration.
Actively look for an existing solution, unwanted automation, unavailable data,
integration/maintenance costs, privacy conflicts and a cheaper non-software fix.

Use separate subagents only when available and authorized by the host/user.
Otherwise use two **single-agent** passes and declare that weaker independence.
Blind execution and publisher identity are declarations, not cryptographic proof.
Never claim a second model was used when it was not. If conclusions leaked into B,
mark `blinded: false`; the computed result needs another blinded check before build.

## Compare, then build, experiment, or stop

The comparison role sees both reports. Link every material discrepancy to evidence
from each pass. `select` uses the lower score per dimension, weighted 30% usefulness,
25% user fit, 20% feasibility, 15% differentiation, 10% trend. The earlier `rank`
score is shortlist/debate compatibility only; it does not choose the final build.
No points for trends without two dated editorial origins within 30 days.

Any failed resource, privacy/safety or first-slice constraint rejects that candidate.
Unknown constraints, missing additional evidence, unblinded validation or unresolved
score differences over 1.5 points require an experiment. User fit, usefulness,
feasibility and differentiation must each score at least 3 in **both** reports for
a full build. Unproven user fit yields an exploratory experiment, not an invented
preference or a mandatory questionnaire.
A discrepancy resolution explains evidence; it never raises the conservative score
or waives a constraint. An irrelevant extra citation cannot satisfy corroboration.

Choose the highest-scoring eligible candidate. A margin below 0.15 between the top
two eligible candidates means an experiment, not confident tie-breaking. All weak
or blocked candidates means no build. The arbiter's declared result must match the
computed result. This chooses among researched options; it cannot guarantee the
best possible idea. Keep rejected candidates and decisive objections in the record.

Experiments need hypothesis, procedure, success/failure observations, at most 120
minutes and zero spend by default. A mock-up, local spike or existing-data check
may fit existing authorization. External messages, live account changes and paid
experiments retain their normal authorization requirements. Stop after one experiment
and one reassessment; if still uncertain, deliver findings and the next decision.
Do not run a second research loop merely to force a build.

For focused runs start with at most 12 targeted searches and 30 minutes of research;
these are planning bounds, not measured billing guarantees. Stop earlier when the
decision is clear. Deep runs may use a larger stated budget. Respect actual host
limits. No private text in public search queries. Offline sources are valid when
they establish the claims; unavailable competitive evidence remains uncertainty.

## After a build decision

Read `references/chosen-idea-research.md` before planning. Learn the selected domain and practical constraints, keep the winner fixed, and carry sourced decisions into the build. This bounded briefing does not reopen candidate ranking or replace implementation research. Experiment/no-build outcomes retain their existing bounded handoff.

## Machine-readable handoff

`examples/selection-dossier.json` is a complete **synthetic fixture**, marked
`fixture_only: true` so it cannot authorize a real scaffold. It embeds `candidates`,
`pool`, `primary`, `validation`, `arbitration`, and client-local `as_of` (YYYY-MM-DD).
Create reports separately and assemble the dossier only after B has finished.
Use `proposal_digest(candidates, pool)` and `digest(report)` from
`scripts/idea_validation.py` to compute the input bindings. Hashes detect stale
inputs, not dishonest records. Do not rebind a report to a revised shortlist:
repeat that assessment explicitly. The helper does not browse or fetch URLs.

Report schema (both passes):

- `version: 1`, `role: primary|validation`, `shortlist_sha256`, `created_on`,
  `reviewer: {mode: single-agent|subagent, id}`; B also has boolean `blinded`.
- `sources`: unique `id`, `kind: web|local|user`, `publisher` (editorial origin, not
  a per-page alias), `finding`, `observed_on`; web uses public HTTPS `url`, local/user
  uses a precise permitted `locator`. Optional `published_on` cannot follow access.
  Record source summaries, not private chat transcripts, credentials or raw tool logs.
- One `assessment` per `seed_id`, with five `scores` (0..5), corresponding
  `score_evidence` source IDs, `need` and `disconfirming` (finding + evidence),
  `constraints` for `resources`, `privacy_safety`, `first_slice` (status
  pass/fail/unknown, reason, evidence), and `differentiation` (alternatives with
  name/evidence, advantage, falsifier, test, evidence). A strong user-fit score
  needs an actual user-stated source; inference alone cannot impersonate preference.

Arbitration: `version: 1`, both report SHA256 values, optional `resolutions` (seed_id,
dimension, reason, evidence IDs prefixed `primary:` or `validation:`), and `decision`
(outcome build/experiment/no-build, seed_id or null, reason). Each resolution cites
that dimension's evidence from both passes. For experiment also include `experiment`
(hypothesis, procedure, success, failure, max_minutes, max_cost).

Reports must be at most seven days old as of comparison; source access must be
within thirty days before its report. At scaffold/run startup the comparison must
use today's client date (one UTC day tolerance). Recompare old reports honestly.

```sh
python3 <skill-dir>/scripts/just_build.py select --file selection-dossier.json
python3 <skill-dir>/scripts/just_build.py scaffold --spec spec.json --base-dir . --selection selection-dossier.json
```

Exit 0: build eligible. Exit 3: valid experiment/no-build or synthetic fixture.
Exit 2: invalid evidence/schema/decision. Do not turn exit 3 into an automatic build.
Set `spec.selection_profile: corroborated-v1` and `spec.selected_candidate` to the
computed winner. For new corroborated scaffolds copy `spec.audience`, `spec.problem` and `spec.first_slice` exactly from the selected pool seed's `audience`, `problem` and `first_demo`. The helper derives `selected_seed_id` and a complete frozen `selected_concept`; `PROJECT_BRIEF.md` preserves the same anchor. Structural checks reject changed or duplicated core brief sections or a mismatched decision/dossier. Refine implementation details in the plan; a changed core concept needs revised selection evidence, not a silent substitution. Historical records without binding metadata remain readable. Do not combine `--selection` with legacy selection flags. Scaffold
stores the dossier and hash under `.just-build/`; tracker initialization revalidates
them. Named-project/legacy workflows need no migration. The ledger is editable
local evidence, not an OS security boundary or signed attestation.

Deliver the decision, why alternatives lost, the working journey and test evidence,
plus remaining uncertainty and one useful next step. Do not label an experiment
or no-build outcome as a completed application.
