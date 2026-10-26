# Guided mode (native chat or console)

Ask only missing decisions, in this order. If the native host exposes selectable options, use them; otherwise display a concise numbered menu and accept e.g. `1, 3, 2, 1`. No HTML/browser interface.

1. Project: **New / Continue**.
2. Source: **All available / Local only / Choose**; when Choose: **Public web / Connected apps / Web + apps**. Enumerate only usable/authenticated integrations; ask which ones to prefer only if that actually matters. `all` means all accessible sources, never blanket authorization.
3. Direction: **Original / Trending** (on Continue: next feature direction, not a new unrelated project).
4. Effort: **Focused / Deep**. Focused = one useful user journey, bounded research, minimum meaningful tests. Deep = additional relevant research, edge cases, polish; never an infinite token promise.

Canonical JSON values: `mode: guided`, `project: new|continue`, `source: all|local|web|apps|web+apps`, `direction: original|trending`, `effort: focused|deep`, optional `apps: []` (preferences only). Validate file handoffs with `just_build.py choices --file <path>`.

**Continue:** enumerate bounded local candidate repos with `discover`; optionally query authorized project integrations. A similarly named public repo is not proof of user ownership. If the target was named, don't ask again. Use `inspect`, review instructions and git status, run an existing baseline, then choose one focused change. Never stomp uncommitted work. Record run state in a *separate* directory outside the repository.

**New, when user delegates idea choice:** follow `references/idea-discovery.md` for the varied pool and traced shortlist, then `references/corroborated-selection.md` for two research reports and evidence comparison. Honor source/direction choices. A named project needs no fabricated pool. For a computed build, set `selection_profile: corroborated-v1`, use `scaffold --selection <dossier.json>` and initialize the tracker as described in `references/build-loop.md`. Complete `references/chosen-idea-research.md` during Research before planning and building. Use the same briefing for a user-named new project. For an experiment or no-build, give the honest outcome and perform only the bounded next step covered by existing authorization. Legacy finalist debate is optional and cannot waive the new gate.
