# Optional advanced prompting patterns

Use inside existing phases, not as mandatory extra agents. Do not request private reasoning or claim that a simulated reviewer is independent.


7. **Context engineering / evidence-first packets.** Before Quality, Polish, Securer, or a repair handoff, optionally run `python3 <skill-dir>/scripts/context_packet.py --state-dir RUN --role quality|polish|security|repair`. It prints a bounded evidence index, separating executed local checks from agent claims. Then read only the relevant source files and plan sections. No raw tool output or retrieved-page prose goes into the packet. It is not a confidentiality or prompt-injection security guarantee.
8. **Hypothesis-driven tool calls.** Before a nontrivial online implementation search, name the uncertain claim, a source/experiment that could disprove it, and the decision that depends on it. Inspect the result; record one small decision delta (keep, revise or defer), not a web-search transcript. Skip redundant research when an adequate verified source already resolves the same question.
9. **Risk-based counterexample tests.** After the first happy-path test, choose the *most likely costly failure* for this slice: invalid input, persistence loss, permission boundary, inaccessible UI, rate-limit recovery or upstream outage. Write one outside-in observable check that fails on that counterexample. If the risk is genuinely inapplicable, explain why; do not add a theatrical assertion.
10. **Small evaluation rubric and delta review.** At the start of a slice, name 3-5 applicable qualities (working journey, recovery, usability, maintainability, security). After a change, report only which qualities changed and what tests support them. A polished explanation or agent consensus is not evidence of a working app.

Use these only when relevant; do not chain extra agents, request hidden reasoning, or add mandatory prompts for trivial tasks. Stop researching when the uncertainty is resolved; keep the original user objective and scope authoritative.
