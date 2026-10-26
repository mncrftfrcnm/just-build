# Short finalist debate — Auto / Guided New

> Legacy/optional explanation only. New idea-led builds use `references/corroborated-selection.md`; a debate cannot bypass that gate.

Use **only after** candidate research and `rank`. This is an adversarial sanity check, not another brainstorming phase. Keep the two highest-ranked feasible finalists; if neither is feasible, repair research and rerank instead. Do not discuss or search every idea again.

**Default four debate messages; hard ceiling seven total role messages** (not seven rounds). Each argument is at most 360 characters and cites at most two short factual bases already present in research, project inspection, or candidate scores. The positions are:

- Advocate: argue why the initial top-ranked project is practical, useful, and worth building; acknowledge weaknesses.
- Challenger: argue the strongest case for the runner-up, and test the front-runner's assumptions (audience, differentiation, feasibility, dated trend support). Seek disconfirming facts, not rhetorical winning. Name one plausible observation that would reverse the preference; if that fact is unknown, retain uncertainty rather than inventing support.

Start with Advocate, alternate roles, stop as soon as a material objection has been answered (typically after four messages). Do not exceed seven messages even if inconclusive. Use two distinct delegated agents **only if actually available**, with the host coordinating and the final choice checked deterministically. Otherwise perform two explicitly labelled sequential perspectives and record `single-agent-fallback`; never pretend a simulated role is a separate model. Tool calls and the final decision summary are not debate messages; never launch a new open-ended research cycle to evade the cap.

Use `examples/debate.json` as the schema. Validate:

```sh
python3 <skill-dir>/scripts/just_build.py debate --candidates /path/to/candidates.json --file /path/to/debate.json --pool /path/to/idea-pool.json
```

The decision must be the *computed* winner. If a challenger identifies material, already-grounded reasons to change scoring, record at most four dimension revisions, each within one point, with reasons. The helper re-ranks; no unverified trend may be upgraded. A deeper objection requiring new research should cause the candidates file to be transparently revised and ranked again (one concise debate on the new finalists), not an unsupported reversal. Supply `--pool <idea-pool.json> --candidates <candidates.json> --debate <debate.json>` together with `scaffold --spec ... --base-dir ...` and set `spec.selected_candidate` to the validated final winner. This records a compact decision in `.just-build/decision.json` without the transcript. Preserve the full debate.json outside the build-state directory for audit, but the entire dialogue need not be copied into the builder's context. Pass only the winner, decisive objection, answer and residual risk into the build brief.

**Decision priority:** explicit user instructions and exclusions > hard safety/feasibility constraints > grounded scores and reconsideration. The dialogue is decision support, not proof that claims were verified or that two different model backends were used.
