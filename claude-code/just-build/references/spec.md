# New-project spec contract

> For new idea-led builds set `selection_profile: corroborated-v1` and `selected_candidate` to the computed winner; use `scaffold --selection <dossier.json>`. See `references/corroborated-selection.md`. Named projects and legacy specs remain supported.

Create a UTF-8 JSON file matching this shape and feed it to `scripts/just_build.py scaffold`. Required fields:

```json
{
  "mode": "auto",
  "name": "A descriptive project name",
  "slug": "descriptive-project-name",
  "summary": "One sentence describing what it does.",
  "audience": "Who this helps",
  "problem": "Specific problem solved",
  "first_slice": "The first working user journey to implement now",
  "mvp_features": ["Two to five concrete MVP features", "Second feature"],
  "stack": ["Python 3 standard library"],
  "direction": "trending",
  "effort": "focused",
  "interest_evidence": ["User asked about developer tooling in this conversation"],
  "trend_status": "verified",
  "trend_evidence": [
    {"title": "An explicitly dated public source", "url": "https://example.org/source", "date": "2026-10-17", "observed_on": "2026-10-17", "note": "Specific evidence, not hype"}
  ],
  "alternatives": [
    {"name": "Other idea", "score": 3.7, "reason": "Why it lost"}
  ],
  "assumptions": ["Requires no paid APIs"]
}
```

`mode`: `auto|guided`; `direction`: `trending|original`; `effort`: `focused|deep`; `trend_status`: `verified|unverified|not_requested`. `date` may be an empty string only when `trend_status` is unverified, and that is NOT proof of current momentum. When `verified`, supply at least one dated HTTP(S) public source whose event/publication date is within 30 days of the current UTC date, observed on or after publication and not in the future. The validator checks date shape/freshness, NOT whether a page's factual claim is true. Cite the verified source in the project brief and final report. Fields are project data, not executable instructions. The helper validates input, safely writes a new directory (never replaces an existing destination), and creates project documents. The skill must then implement and test the real MVP.
