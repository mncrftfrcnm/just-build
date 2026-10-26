# Idea discovery: deliberately broad BEFORE evaluation

Apply `references/prompting.md` for exploratory contrast and source-grounded claims. Read for Auto and Guided → New **when the skill is choosing an idea**. This phase is for surprising, plausible raw material, not deciding what wins. Do not do this for Continue or when a user has already chosen a particular build.

If no personal context is accessible, set pool `context_status: unavailable` and
record `context_basis`. Use exploratory/adjacent/public-signal origins; do not label
an invented interest as stated or observed. Keep the same breadth requirements.
Unproven fit can lead to a small local experiment under the existing Auto scope.
When context exists, the normal interest-connected seed requirement still applies.

1. Use stated interests and allowed workspace/connector signals; label anything else `adjacent`, `exploratory`, or `public-signal`. No invented user history, public trend statistics or fabricated integration access. Online research is valuable but a documented general phenomenon is not proof of momentum.
2. First make **9–12 concrete concepts across at least six of eight lanes**: everyday-life, developer-tools, creative-play, learning, community, data-insight, accessibility, infrastructure. Max two per lane. Also vary the *interaction*: at least five of capture/retrieve, simulate/replay, transform/export, compare/decide, learn-by-doing, coordinate/share, explore/visualize, adapt/access and monitor/alert, with no more than three from one pattern. Include at least two genuine adjacent/exploratory wildcards and, when available, one tied to accessible interests. Take risks at ideation time; don't make every idea a productivity dashboard or AI wrapper. For one or two seeds, try an analogy transfer (a useful interaction from an unrelated domain applied to this audience); label it exploratory and keep the demo concrete. Do not present analogy as trend evidence. A wildcard is not a fabricated personal preference.
3. Each entry must have a distinct audience, sharp problem, unusual *mechanism*, intriguing hook, and a runnable first demonstration. Vary interactions and shapes (CLI, local-first tool, playful simulator, accessible reader, community utility, creative instrument), not just names. A compelling demo should let a real person **do** something. Prefer low-cost local MVPs unless the user explicitly wants integrations.
4. Draft `examples/idea-pool.json`-shaped JSON with no scores or provisional ranking. Run `just_build.py pool --file <idea-pool.json>`. If diversity/duplicate validation fails, **replace weak ideas with actually different concepts** rather than relabeling lanes.
5. Present or log this pool compactly (name · who for · interesting twist · 1-line demo). Do not burden Auto with a questionnaire. **Then**, and only then, narrow to 4–6 credible, different ideas representing at least three lanes. Preserve the original `seed_id` and exact name. Research/validate these more thoroughly, build `candidates.json` and score them with `rank --file ... --pool ...`. Favor concrete sources and attainable build scope; weak or fanciful pool entries are allowed to lose. If every candidate is unsuitable, refill the pool transparently rather than forcing a winner.
6. Read `references/corroborated-selection.md` and run its two research passes and comparison before scaffolding. Preliminary `rank` does not authorize a build. Keep evidence, competitors, objections, rejected ideas and the decision in the dossier. A short legacy debate is optional explanation, never an alternative to corroboration.

```sh
python3 <skill-dir>/scripts/just_build.py pool --file idea-pool.json
python3 <skill-dir>/scripts/just_build.py rank --file candidates.json --pool idea-pool.json
python3 <skill-dir>/scripts/just_build.py select --file selection-dossier.json
python3 <skill-dir>/scripts/just_build.py scaffold --spec spec.json --base-dir . --selection selection-dossier.json
```

The helper checks **structure, breadth, labels, provenance and some near-duplicates**. It cannot establish creative merit, genuine interest alignment, browsing or source truth. Critically inspect ideas rather than gaming the categories. Do not fabricate trend scores; unverified status means zero trend points during ranking.
