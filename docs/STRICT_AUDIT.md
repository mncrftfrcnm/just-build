# Strict public-release audit

Recorded 25 October 2026 for an earlier prepared source snapshot. This review replaces the earlier broad publication-confidence judgment with a stricter requirement: what evidence supports presenting the project publicly as dependable software for both advertised hosts?

**61/100 for dependable dual-host readiness.** Sharing an **experimental public preview** is reasonable after this round's repairs and exact local verification. A dependable dual-host release is not established. This is an editorial evidence rubric, not a success probability, security certification or measured reliability percentage. Fixing local defects cannot create missing host or user evidence.

## Evidence rubric

| Criterion | Score |
|---|---:|
| Actual host installation and invocation | 8/25 |
| Repeatable end-to-end delivery | 12/20 |
| Release reproducibility and platform validation | 10/15 |
| Safety and trust boundaries | 12/15 |
| Onboarding and product usability | 11/15 |
| Support and maintainability | 8/10 |
| **Total** | **61/100** |

A separate reviewer started without this conversation's previous scores. It inspected public source and sanitized evidence, checked official host installation guidance, and independently confirmed the immutable pre-audit package digests and all 247 source hashes. Its read-only evidence review did not test actual Claude, hosted CI, browsers, the truth of private transcripts or the separate code repairs. Core and release code received distinct adversarial reviews and regressions; final local validation is reported in [EVALUATION.md](EVALUATION.md).

## Concrete issues repaired

| Finding | Effect before repair | Change |
|---|---|---|
| Nested acceptance cwd (P2) | A real nested test was rejected, or a root assertion-bearing decoy could supply the inspection while a different nested print-only script ran | Resolve the inspected script relative to the actual validated execution directory; retain project boundaries |
| Understated ZIP expansion (P2) | A crafted DEFLATE member could report the expected size/content while hiding additional expansion; incomplete/trailing streams were not fully validated | Check the complete raw stream with bounded output, stream termination and declared-size consistency; reject inconsistent stored sizes |
| Accidental private-material publication (P2) | Standard RSA/EC/OPENSSH key headers and uppercase sensitive filenames passed source preflight | Match standard private-key headers and normalize sensitive names/suffixes before comparison |
| Version grammar mismatch (P3) | Unicode version digits passed source/sync checks but failed ASCII artifact/tag validation | Require ASCII digits consistently before packaging/sync |
| Mixed-slash UNC preflight (P2) | Direct token-summary API calls could reach filesystem inspection for a network-looking path | Normalize separator spelling before rejecting UNC/device inputs; test without network access |
| Claude instructions (P2) | Expanded helper paths split at spaces; ordinary named tasks could be mistaken for an unknown mode | Quote the helper path and parse only an optional leading mode, preserving the task |

Reproductions use synthetic local inputs. No real secret, live target, global install, publishing action or account change was required. New tests target observable defects; they do not prove that assertion heuristics establish semantic test quality or that private-material scanning is comprehensive. The documented trusted-workspace/cooperative-ledger boundary remains.

## Release gates still missing

1. An actual Claude Code clean installation, invocation, completed bounded build and independent artifact check.
2. An observed passing hosted Windows/Ubuntu matrix and exact-commit candidate verification, with the intended repository settings applied by its owner.
3. Fresh completed deliveries without implementation rescue, retaining failed attempts, interventions and time/usage.
4. Real-browser first-use, recovery, keyboard and narrow-layout journeys on final delivered bytes.

Authorized human feedback and representative complete-build cost/usefulness measurements are also missing. A runnable generated app, process exit 0, simulated reviewers, large test count or honest partial result does not close these gates. Keep the limitation visible on the public front page and in any release announcement.

## Publication decision

**Experimental source preview: yes, with the documented scope. Dependable dual-host/public product launch: no.** Keep the prerelease designation, do not promise unattended delivery, and collect the evidence above before changing that positioning. The prepared source is not a published GitHub repository and no observed hosted results or configured protections are implied.
