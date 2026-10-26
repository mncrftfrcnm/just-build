#!/usr/bin/env python3
"""Deterministic, dependency-free helpers for the Just Build Codex skill.

Not an autonomous agent: the hosting Codex agent performs research, decides,
implements code and tests. This program only validates, discovers bounded local
project candidates, and safely creates a fresh project handoff directory.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse, quote
from host_safety import is_link, RESERVED, bounded_json, regular_text
from process_runner import run_command, ProcessSafetyError

SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SKIP = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "Downloads", "Library", ".codex", ".config", ".ssh", ".aws", ".local", ".cache", "sessions", "history"}
MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Gemfile", "README.md")
CHOICES = {
    "project": {"new", "continue"},
    "source": {"all", "local", "web", "apps", "web+apps"},
    "direction": {"original", "trending"},
    "effort": {"focused", "deep"},
}
APP_NAMES = {"github", "google-drive", "gmail", "notion", "linear", "slack", "other"}
WEIGHTS = {"interest": 0.35, "trend": 0.25, "feasibility": 0.25, "differentiation": 0.15}
# Distinct *exploration* lanes, not ranking categories. The initial pool stays unscored.
IDEA_LANES = {"everyday-life", "developer-tools", "creative-play", "learning", "community", "data-insight", "accessibility", "infrastructure"}
IDEA_ORIGINS = {"stated-interest", "observed-work", "adjacent", "exploratory", "public-signal"}
IDEA_INTERACTIONS = {"capture-retrieve", "simulate-replay", "transform-export", "compare-decide", "learn-by-doing", "coordinate-share", "explore-visualize", "adapt-access", "monitor-alert"}
# These core spec values retain the selected seed verbatim. Presentation,
# implementation details and feature lists may be refined independently.
SELECTED_CONCEPT_BINDINGS = {"audience": "audience", "problem": "problem", "first_slice": "first_demo"}




class InvalidSpec(ValueError):
    pass


def ensure_string(value, name, max_chars=500):
    if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
        raise InvalidSpec(f"{name} must be a nonempty string of at most {max_chars} characters")
    if any(ord(ch) < 32 and ch not in "\t\n" for ch in value):
        raise InvalidSpec(f"{name} contains control characters")
    return value.strip()


def ensure_list(value, name, min_count=0, max_count=20):
    if not isinstance(value, list) or not min_count <= len(value) <= max_count:
        raise InvalidSpec(f"{name} must be a list with {min_count}-{max_count} entries")
    return value


def choices_validate(data):
    if not isinstance(data, dict) or data.get("mode") != "guided":
        raise InvalidSpec("choices.mode must equal guided")
    for key, allowed in CHOICES.items():
        if data.get(key) not in allowed:
            raise InvalidSpec(f"choices.{key} must be one of {', '.join(sorted(allowed))}")
    apps = data.get("apps", [])
    if not isinstance(apps, list) or len(apps) > len(APP_NAMES) or len(apps) != len(set(map(str, apps))):
        raise InvalidSpec("choices.apps must be a list of unique app identifiers")
    if any(not isinstance(a, str) or a not in APP_NAMES for a in apps):
        raise InvalidSpec(f"choices.apps must contain only: {', '.join(sorted(APP_NAMES))}")
    if apps and data["source"] not in ("apps", "web+apps", "all"):
        raise InvalidSpec("choices.apps requires an app-capable source")
    return {"mode": "guided", **{key: data[key] for key in CHOICES}, "apps": apps}


def validate_spec(data):
    if not isinstance(data, dict):
        raise InvalidSpec("spec must be a JSON object")
    for key in ("name", "summary", "audience", "problem", "first_slice"):
        ensure_string(data.get(key), key, 1500 if key in ("problem", "first_slice") else 500)
    slug = ensure_string(data.get("slug"), "slug", 48)
    if len(slug) < 3 or not SLUG.fullmatch(slug):
        raise InvalidSpec("slug must be 3-48 chars: lowercase letters, numbers, internal hyphens; start with a letter")
    if slug.casefold() in RESERVED:
        raise InvalidSpec("slug cannot be a reserved Windows device name")
    if data.get("selection_profile") not in (None, "corroborated-v1"):
        raise InvalidSpec("unknown selection_profile")
    for key, allowed in {
        "mode": {"auto", "guided"},
        "direction": {"trending", "original"},
        "effort": {"focused", "deep"},
        "trend_status": {"verified", "unverified", "not_requested"},
    }.items():
        if data.get(key) not in allowed:
            raise InvalidSpec(f"{key} must be one of {', '.join(sorted(allowed))}")
    for key, bounds in {"mvp_features": (2, 5), "stack": (1, 10), "interest_evidence": (0, 10), "assumptions": (0, 15)}.items():
        for i, value in enumerate(ensure_list(data.get(key), key, *bounds)):
            ensure_string(value, f"{key}[{i}]", 400)
    trends = ensure_list(data.get("trend_evidence"), "trend_evidence", 0, 12)
    dated = 0
    for i, item in enumerate(trends):
        if not isinstance(item, dict):
            raise InvalidSpec(f"trend_evidence[{i}] must be an object")
        for key in ("title", "url", "observed_on", "note"):
            ensure_string(item.get(key), f"trend_evidence[{i}].{key}", 600)
        uri = urlparse(item["url"])
        if (uri.scheme not in ("http", "https") or not uri.hostname or uri.username or uri.password
                or any(ch.isspace() or ord(ch) < 32 for ch in item["url"])):
            raise InvalidSpec(f"trend_evidence[{i}].url must be an HTTP(S) source URL")
        date_str = item.get("date", "")
        if not isinstance(date_str, str):
            raise InvalidSpec(f"trend_evidence[{i}].date must be a string")
        for field, d in (("date", date_str), ("observed_on", item["observed_on"])):
            if d:
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except ValueError as exc:
                    raise InvalidSpec(f"trend_evidence[{i}].{field} must be YYYY-MM-DD") from exc
        today = datetime.now(timezone.utc).date()
        observed = date.fromisoformat(item["observed_on"])
        if observed > today:
            raise InvalidSpec(f"trend_evidence[{i}].observed_on cannot be in the future")
        if date_str:
            event_date = date.fromisoformat(date_str)
            if event_date > observed:
                raise InvalidSpec(f"trend_evidence[{i}].date cannot be after observed_on")
            if (observed - event_date <= timedelta(days=30)
                    and today - event_date <= timedelta(days=30)):
                dated += 1
    if data["trend_status"] == "verified" and dated == 0:
        raise InvalidSpec("verified trends require at least one dated public source observed within 30 days of its event/publication")
    alternatives = ensure_list(data.get("alternatives"), "alternatives", 0, 5)
    for i, alt in enumerate(alternatives):
        if not isinstance(alt, dict):
            raise InvalidSpec(f"alternatives[{i}] must be an object")
        ensure_string(alt.get("name"), f"alternatives[{i}].name")
        ensure_string(alt.get("reason"), f"alternatives[{i}].reason")
        score = alt.get("score")
        if type(score) not in (int, float) or not 0 <= score <= 5:
            raise InvalidSpec(f"alternatives[{i}].score must be a number 0..5")
    selected = data.get("selected_candidate")
    if selected is not None:
        ensure_string(selected, "selected_candidate", 100)
    return data



def normalized_words(value):
    return set(re.findall(r"[^\W_]+", value.casefold())) - {"a", "an", "the", "for", "and", "to", "of", "in", "with", "on", "that"}


def validate_idea_pool(data):
    """Validate breadth *before* choosing winners; no ranking, fake evidence or AI generation here."""
    if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1:
        raise InvalidSpec("idea pool requires version: 1")
    context_status = data.get("context_status", "available")
    if context_status not in ("available", "unavailable"):
        raise InvalidSpec("context_status must be available or unavailable")
    if context_status == "unavailable":
        ensure_string(data.get("context_basis"), "context_basis", 400)
    ideas = ensure_list(data.get("ideas"), "ideas", 9, 12)
    ids, names, lanes, origins, interactions, pairs = set(), set(), {}, {}, {}, []
    clean = []
    for i, idea in enumerate(ideas):
        if not isinstance(idea, dict):
            raise InvalidSpec(f"ideas[{i}] must be an object")
        if any(key in idea for key in ("score", "scores", "rank")):
            raise InvalidSpec("idea discovery is deliberately unscored; do not pre-rank concepts")
        ident = ensure_string(idea.get("id"), f"ideas[{i}].id", 48)
        if not SLUG.fullmatch(ident) or ident in ids:
            raise InvalidSpec("idea IDs must be unique lowercase slugs")
        ids.add(ident)
        name = ensure_string(idea.get("name"), f"ideas[{i}].name", 100)
        if name.casefold() in names:
            raise InvalidSpec("idea names must be unique")
        names.add(name.casefold())
        lane = idea.get("lane")
        origin = idea.get("origin")
        interaction = idea.get("interaction")
        if any(not isinstance(value, str) or value not in allowed for value, allowed in ((lane, IDEA_LANES), (origin, IDEA_ORIGINS), (interaction, IDEA_INTERACTIONS))):
            raise InvalidSpec("idea lane/origin/interaction must be a supported category")
        lanes[lane] = lanes.get(lane, 0) + 1
        origins[origin] = origins.get(origin, 0) + 1
        interactions[interaction] = interactions.get(interaction, 0) + 1
        item = {"id": ident, "name": name, "lane": lane, "origin": origin, "interaction": interaction}
        for field in ("audience", "problem", "mechanism", "first_demo", "hook", "interest_basis"):
            item[field] = ensure_string(idea.get(field), f"ideas[{i}].{field}", 280)
        # Match core jobs, not just branding. High-overlap proposals within one
        # audience are likely rewrites of the same idea, even with different names.
        signature = normalized_words(item["problem"] + " " + item["mechanism"])
        audience = normalized_words(item["audience"])
        for prior in pairs:
            overlap = len(signature & prior[0]) / max(1, len(signature | prior[0]))
            aud = len(audience & prior[1]) / max(1, len(audience | prior[1]))
            if signature == prior[0] or (len(signature) >= 5 and overlap >= 0.76 and aud >= 0.5):
                raise InvalidSpec(f"near-duplicate concepts: {name!r} and {prior[2]!r}; diversify the mechanism or problem")
        pairs.append((signature, audience, name))
        clean.append(item)
    if len(lanes) < 6 or max(lanes.values()) > 2:
        raise InvalidSpec("discovery needs at least six distinct lanes and at most two ideas in any lane")
    if len(interactions) < 5 or max(interactions.values()) > 3:
        raise InvalidSpec("discovery needs at least five different interaction patterns and at most three of any one pattern")
    if origins.get("exploratory", 0) + origins.get("adjacent", 0) < 2:
        raise InvalidSpec("include at least two adjacent/exploratory wildcard ideas")
    has_context = any(x["origin"] in ("stated-interest", "observed-work") for x in clean)
    if context_status == "unavailable" and has_context:
        raise InvalidSpec("unavailable context cannot claim stated interests or observed user work")
    if context_status == "available" and not has_context:
        raise InvalidSpec("at least one idea must connect to accessible, non-invented interest context")
    return {"version": 1, "count": len(clean), "lane_count": len(lanes), "interaction_count": len(interactions), "lanes": lanes, "interactions": interactions, "origins": origins,
            "ideas": clean, "context_status": context_status, "status": "unscored discovery pool; category and originality checks are structural, not evidence validation"}


def validate_shortlist(data, pool):
    """Ensure selected candidates actually originate from a broad exploration pool."""
    source = validate_idea_pool(pool)
    entries = ensure_list(data.get("candidates"), "candidates", 4, 6)
    by_id = {x["id"]: x for x in source["ideas"]}
    selected_ids, lanes = set(), set()
    for i, candidate in enumerate(entries):
        if not isinstance(candidate, dict):
            raise InvalidSpec(f"candidates[{i}] must be an object")
        ident = candidate.get("seed_id")
        if not isinstance(ident, str) or ident not in by_id or ident in selected_ids:
            raise InvalidSpec("shortlist candidates must have distinct IDs from the validated idea pool")
        selected_ids.add(ident)
        seed = by_id[ident]
        if candidate.get("name") != seed["name"]:
            raise InvalidSpec("shortlist candidate name must match its seed; revise the pool explicitly")
        lanes.add(seed["lane"])
    if len(lanes) < 3:
        raise InvalidSpec("shortlist should retain at least three different discovery lanes")
    return {"pool_count": source["count"], "pool_lanes": source["lane_count"],
            "shortlist_count": len(entries), "shortlist_lanes": len(lanes),
            "seed_ids": sorted(selected_ids)}


def rank_candidates(data, pool=None):
    """Rank three or more agent-researched ideas; never invent evidence.

    This is deterministic arithmetic, not independent validation of claims.
    If evidence is unavailable, all trend scores become zero.
    """
    if not isinstance(data, dict) or data.get("trend_status") not in ("verified", "unverified"):
        raise InvalidSpec("rank input requires trend_status: verified|unverified")
    diversity = validate_shortlist(data, pool) if pool is not None else None
    candidates = ensure_list(data.get("candidates"), "candidates", 3, 12)
    seen, result = set(), []
    for i, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise InvalidSpec(f"candidates[{i}] must be an object")
        name = ensure_string(candidate.get("name"), f"candidates[{i}].name", 100)
        if name.casefold() in seen:
            raise InvalidSpec("candidate names must be unique")
        seen.add(name.casefold())
        reason = ensure_string(candidate.get("reason"), f"candidates[{i}].reason", 600)
        scores = candidate.get("scores")
        if not isinstance(scores, dict) or set(scores) != set(WEIGHTS):
            raise InvalidSpec(f"candidates[{i}].scores must include exactly {', '.join(WEIGHTS)}")
        for key, value in scores.items():
            if type(value) not in (int, float) or not 0 <= value <= 5:
                raise InvalidSpec(f"candidates[{i}].scores.{key} must be a number 0..5")
        if data["trend_status"] != "verified" and scores["trend"]:
            raise InvalidSpec("trend must score 0 when trend_status is unverified")
        evidence = ensure_list(candidate.get("evidence", []), f"candidates[{i}].evidence", 0, 8)
        for j, value in enumerate(evidence):
            ensure_string(value, f"candidates[{i}].evidence[{j}]", 500)
        total = sum(scores[key] * weight for key, weight in WEIGHTS.items())
        result.append({"name": name, "score": round(total, 3), "scores": scores,
                       "reason": reason, "evidence": evidence, **({"seed_id": candidate["seed_id"]} if pool is not None else {})})
    result.sort(key=lambda row: (-row["score"], row["name"].casefold()))
    return {"trend_status": data["trend_status"], "weights": WEIGHTS,
            **({"discovery": diversity} if diversity is not None else {}),
            "winner": result[0], "ranked": result,
            "caveat": "Scores are agent judgments; helper only validates and calculates them."}



def debate_candidates(ranking_input, debate, pool=None):
    """Validate a bounded two-role challenge to the top two scored ideas.

    Agent/subagent-written arguments are opinions, not executable evidence. A
    changed winner is only permitted after explicit, limited score revisions.
    """
    initial = rank_candidates(ranking_input, pool)
    if not isinstance(debate, dict) or debate.get("reviewer_mode") not in ("subagents", "single-agent-fallback"):
        raise InvalidSpec("debate.reviewer_mode must honestly indicate subagents or single-agent-fallback")
    finalists = [entry["name"] for entry in initial["ranked"][:2]]
    turns = ensure_list(debate.get("messages"), "debate.messages", 2, 7)
    compact = []
    for i, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise InvalidSpec("debate.messages entries must be objects")
        expected = "advocate" if i % 2 == 0 else "challenger"
        if turn.get("role") != expected:
            raise InvalidSpec("debate roles must alternate advocate then challenger")
        if turn.get("candidate") not in finalists:
            raise InvalidSpec("debate may only discuss the two highest-ranked finalists")
        argument = ensure_string(turn.get("argument"), f"debate.messages[{i}].argument", 360)
        basis = ensure_list(turn.get("basis", []), f"debate.messages[{i}].basis", 0, 2)
        basis = [ensure_string(v, f"debate.messages[{i}].basis", 160) for v in basis]
        compact.append({"role": expected, "candidate": turn["candidate"], "argument": argument, "basis": basis})
    changes = ensure_list(debate.get("score_changes", []), "debate.score_changes", 0, 4)
    adjusted = json.loads(json.dumps(ranking_input))
    seen_changes = set()
    applied = []
    for change in changes:
        if not isinstance(change, dict) or change.get("candidate") not in finalists or change.get("dimension") not in WEIGHTS:
            raise InvalidSpec("score change must identify a finalist and valid dimension")
        key = (change["candidate"], change["dimension"])
        if key in seen_changes:
            raise InvalidSpec("duplicate score adjustment")
        seen_changes.add(key)
        target = next(row for row in adjusted["candidates"] if row["name"] == change["candidate"])
        old = target["scores"][change["dimension"]]
        value = change.get("new_score")
        if type(value) not in (int, float) or not 0 <= value <= 5 or not 0 < abs(value-old) <= 1:
            raise InvalidSpec("debate score revisions must change by at most one point and stay in 0..5")
        if change["dimension"] == "trend" and ranking_input["trend_status"] != "verified":
            raise InvalidSpec("debate cannot upgrade an unverified trend score")
        reason = ensure_string(change.get("reason"), "debate.score_changes.reason", 260)
        target["scores"][change["dimension"]] = value
        applied.append({"candidate": change["candidate"], "dimension": change["dimension"],
                        "previous": old, "new": value, "reason": reason})
    final = rank_candidates(adjusted, pool)
    decision = debate.get("decision")
    if not isinstance(decision, dict) or decision.get("winner") != final["winner"]["name"]:
        raise InvalidSpec("debate decision must name the post-revision ranking winner")
    rationale = ensure_string(decision.get("rationale"), "debate.decision.rationale", 500)
    return {"reviewer_mode": debate["reviewer_mode"], "max_messages": 7, "messages_used": len(compact),
            "finalists": finalists, "initial_winner": initial["winner"]["name"],
            "final_winner": final["winner"]["name"], "changed_by_debate": initial["winner"]["name"] != final["winner"]["name"],
            "messages": compact, "score_changes": applied, "decision": {"winner": final["winner"]["name"], "rationale": rationale},
            "final_ranking": final["ranked"], **({"discovery": final["discovery"]} if pool is not None else {}),
            "caveat": "Agent-written arguments and score justifications are not independently verified evidence."}


def inspect_project(path):
    """Explicit-target, read-only status inspection; does not search user home."""
    project = Path(path).expanduser()
    if is_link(project):
        raise InvalidSpec("refusing to inspect a symlinked project root")
    project = project.resolve(strict=True)
    if not project.is_dir():
        raise InvalidSpec("project must be a directory")
    markers = [item for item in MARKERS if (project / item).exists()]
    if not markers:
        raise InvalidSpec("selected directory lacks project markers")
    info = {"project": str(project), "markers": markers,
            "instructions_present": (project / "AGENTS.md").is_file(),
            "git": {"available": False}}
    if (project / ".git").exists():
        try:
            version = run_command(['git', '--version'], project, timeout=5, max_output=4096)
            found = re.search(rb'git version (\d+)\.(\d+)', version.stdout)
            if version.returncode != 0 or not found or tuple(map(int, found.groups())) < (2, 36):
                raise ProcessSafetyError('passive inspection requires Git 2.36 or newer')
            # Status may otherwise execute a repository-configured fsmonitor
            # program. Never recurse into submodules during passive discovery.
            prefix = ["git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false",
                      "-c", "core.hooksPath=" + os.devnull, "-C", str(project)]
            def git_output(*arguments, allow_missing=False):
                observed = run_command(prefix + list(arguments), project, timeout=5, max_output=200_000,
                                       extra_env={"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
                                                  "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
                if observed.returncode != 0 and not (allow_missing and observed.returncode == 1):
                    raise ProcessSafetyError('Git inspection failed or exceeded its resource budget')
                return observed.stdout.decode('utf-8', errors='replace')
            root = git_output("rev-parse", "--show-toplevel").strip()
            if Path(root).resolve() != project:
                info["git"] = {"available": True, "nested_repository": True}
                return info
            configured = git_output('config', '--null', '--name-only', '--get-regexp', '^filter\\.', allow_missing=True)
            if any(key.endswith(('.clean', '.smudge', '.process')) for key in configured.split('\x00')):
                info['git'] = {'available': True, 'safe_to_treat_as_clean': False,
                               'status': 'not-inspected-configured-content-filters',
                               'reason': 'Review configured content filters before executing a baseline; passive inspection did not invoke them.'}
                return info
            status = git_output("status", "--porcelain=v1", "--ignore-submodules=all")
            branch = git_output("branch", "--show-current").strip()
            info["git"] = {"available": True, "branch": branch or "detached-or-unborn",
                           "changes_count": sum(bool(s) for s in status.splitlines()),
                           "safe_to_treat_as_clean": not status.strip()}
        except (ProcessSafetyError, OSError) as exc:
            info["git"] = {"available": False, "reason": type(exc).__name__}
    return info


def check_build(path):
    """Check presence of handoff and implementation; does not execute untrusted code."""
    project = Path(path).expanduser()
    if is_link(project):
        raise InvalidSpec("refusing to check a symlinked project root")
    project = project.resolve(strict=True)
    if not project.is_dir():
        raise InvalidSpec("project must be a directory")
    decision = project / ".just-build" / "decision.json"
    if not decision.is_file():
        raise InvalidSpec("not a just-build scaffold (.just-build/decision.json missing)")
    spec = validate_spec(read_json(decision, root=project))
    if "selected_seed_id" in spec or "selected_concept" in spec:
        dossier = read_json(project / ".just-build" / "idea-validation.json", root=project)
        verify_selection_binding(spec, dossier)
        brief = regular_text(project / "PROJECT_BRIEF.md", 256_000, root=project)
        verify_selected_brief(spec, brief)
    readme = project / "README.md"
    text = regular_text(readme, 256_000, root=project) if readme.is_file() else ""
    handoff_replaced = "This is an initial scaffold only." not in text and "## Implementation handoff" not in text
    ignored = {".git", ".just-build", "node_modules", "dist", "build", ".venv", "__pycache__"}
    source_suffixes = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".html", ".css", ".sh"}
    sources = []
    tests = []
    for folder in [project, project / "src", project / "app", project / "tests", project / "test"]:
        if not folder.is_dir() or is_link(folder):
            continue
        for item in folder.iterdir():
            if item.name in ignored or is_link(item) or not item.is_file():
                continue
            rel = str(item.relative_to(project))
            if item.suffix in source_suffixes:
                sources.append(rel)
            if item.name.startswith("test_") or item.name.endswith((".test.js", ".spec.js", ".test.ts", ".spec.ts")):
                tests.append(rel)
    # Files in tests/ may be named differently from conventional test_ naming.
    evidence = {"readme_has_run_instructions": handoff_replaced and
                any(s in text.lower() for s in ("```", "python", "npm ", "cargo ", "go test", "run:")),
                "source_files_present": bool(sources), "test_files_present": bool(tests),
                "brief_present": (project / "PROJECT_BRIEF.md").is_file()}
    return {"project": str(project), "checks": evidence, "passes_structural_gate": all(evidence.values()),
            "source_files": sorted(sources), "test_files": sorted(tests),
            "note": "Presence check only. Codex must actually run tests and report their real outputs."}


def read_json(path, root=None):
    try:
        return bounded_json(path, root=root)
    except (OSError, ValueError) as exc:
        raise InvalidSpec(f"Cannot load JSON: {exc}") from exc


def discover(root, max_projects=25):
    if is_link(Path(root).expanduser()):
        raise InvalidSpec("discovery root cannot be linked")
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise InvalidSpec("discovery root must be a directory")
    # Only root and immediate children, no recursive crawling or file contents.
    candidates = [root]
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.casefold())
    except OSError as exc:
        raise InvalidSpec(str(exc)) from exc
    for item in children:
        if len(candidates) >= max_projects + 1:
            break
        if item.name.startswith(".") or item.name in SKIP or is_link(item) or not item.is_dir():
            continue
        candidates.append(item)
    projects = []
    for path in candidates:
        matches = [name for name in MARKERS if (path / name).exists()]
        if matches:
            projects.append({"name": path.name, "path": str(path), "markers": matches})
            if len(projects) >= max_projects:
                break
    return {"root": str(root), "scan": "root and immediate subdirectories only", "projects": projects}


def escape_md(s):
    # Prevent accidentally turning untrusted project data into an HTML block.
    value = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = value.replace("\\", "\\\\")
    return re.sub(r"([`*_{}\[\]!|])", r"\\\1", value).replace("\n", " ")


def bullet_list(values):
    return "\n".join(f"- {escape_md(item)}" for item in values) if values else "- None recorded"


def verify_selection_binding(spec, dossier, checked=None):
    """Bind new corroborated records to the selected pool seed, without fuzzy matching.

    Old records with neither binding field remain readable. Any supplied binding
    metadata requires the complete pair and a matching validated pool concept.
    """
    if "selected_seed_id" not in spec and "selected_concept" not in spec:
        return None
    if spec.get("selection_profile") != "corroborated-v1":
        raise InvalidSpec("selected concept binding requires the corroborated selection profile")
    from idea_validation import evaluate_dossier
    checked = evaluate_dossier(dossier) if checked is None else checked
    pool = validate_idea_pool(dossier.get("pool"))
    selected = next((idea for idea in pool["ideas"] if idea["id"] == checked.get("seed_id")), None)
    if (selected is None or checked.get("outcome") != "build"
            or spec.get("selected_seed_id") != selected["id"]
            or spec.get("selected_candidate") != selected["name"]
            or spec.get("selected_concept") != selected):
        raise InvalidSpec("selected concept binding must match the complete validated winner seed")
    for field, seed_field in SELECTED_CONCEPT_BINDINGS.items():
        if spec.get(field) != selected[seed_field]:
            raise InvalidSpec(f"spec.{field} must equal selected_concept.{seed_field}; revise and revalidate the pool to change the core concept")
    return selected


def render_selected_concept(spec):
    if "selected_seed_id" not in spec and "selected_concept" not in spec:
        return ""
    concept = spec["selected_concept"]
    fields = (("Seed ID", spec["selected_seed_id"]), ("Name", concept["name"]),
              ("Lane", concept["lane"]), ("Origin", concept["origin"]),
              ("Interaction", concept["interaction"]), ("Audience", concept["audience"]),
              ("Problem", concept["problem"]), ("Mechanism", concept["mechanism"]),
              ("First demo", concept["first_demo"]), ("Hook", concept["hook"]),
              ("Interest basis", concept["interest_basis"]))
    return "## Selected concept (frozen)\n" + "\n\n".join(
        f"**{label}:** {escape_md(value)}" for label, value in fields) + "\n\n"


def verify_selected_brief(spec, text):
    """Require one canonical core section and frozen concept block in new briefs."""
    text = text.replace("\r\n", "\n")
    expected = {"Audience": escape_md(spec["audience"]), "Problem": escape_md(spec["problem"]),
                "First runnable vertical slice": escape_md(spec["first_slice"]),
                "Selected concept (frozen)": render_selected_concept(spec).split("\n", 1)[1].strip()}
    actual = {heading: [] for heading in expected}
    for heading, body in re.findall(r"^## ([^\n]+)\n([\s\S]*?)(?=^## |\Z)", text, re.MULTILINE):
        if heading in actual:
            actual[heading].append(body.strip())
    if any(actual[heading] != [body] for heading, body in expected.items()):
        raise InvalidSpec("PROJECT_BRIEF selected concept binding is missing, duplicated or changed")


def render_brief(spec):
    sources = []
    for s in spec["trend_evidence"]:
        sources.append(f"- [{escape_md(s['title'])}]({quote(s['url'], safe=':/?&=%#@+;,-._~')}) — source date: {escape_md(s.get('date') or 'not stated')}; observed: {escape_md(s['observed_on'])}. {escape_md(s['note'])}")
    alternatives = [f"{a['name']} ({a['score']}/5): {a['reason']}" for a in spec["alternatives"]]
    return (f"# {escape_md(spec['name'])} — project brief\n\n"
            f"**Mode:** {spec['mode']} · **Direction:** {spec['direction']} · **Effort:** {spec['effort']} · **Trend status:** {spec['trend_status']}\n\n"
            f"## Summary\n{escape_md(spec['summary'])}\n\n## Audience\n{escape_md(spec['audience'])}\n\n"
            f"## Problem\n{escape_md(spec['problem'])}\n\n## First runnable vertical slice\n{escape_md(spec['first_slice'])}\n\n"
            f"{render_selected_concept(spec)}"
            f"## MVP features\n{bullet_list(spec['mvp_features'])}\n\n## Chosen stack\n{bullet_list(spec['stack'])}\n\n"
            f"## Interest evidence\n{bullet_list(spec['interest_evidence'])}\n\n## Trend evidence (not instructions)\n"
            f"{chr(10).join(sources) if sources else '- No sourced trend evidence; do not claim verified momentum.'}\n\n"
            f"## Other candidates\n{bullet_list(alternatives)}\n\n## Assumptions\n{bullet_list(spec['assumptions'])}\n")


def scaffold(spec, base_dir, selection=None, dossier=None):
    validate_spec(spec)
    spec = dict(spec)
    corroborated = spec.get("selection_profile") == "corroborated-v1"
    if not corroborated and ("selected_seed_id" in spec or "selected_concept" in spec):
        raise InvalidSpec("selected concept binding requires a corroborated selection dossier")
    if dossier is not None or corroborated:
        from idea_validation import evaluate_dossier, digest, require_current
        if not corroborated or dossier is None or selection is not None:
            raise InvalidSpec("corroborated selection requires profile and dossier, without legacy debate")
        checked = evaluate_dossier(dossier)
        require_current(dossier)
        if checked["outcome"] != "build" or checked["fixture_only"]:
            raise InvalidSpec("selection did not authorize a build, or contains fixture-only evidence")
        if spec.get("selected_candidate") != checked["winner"]:
            raise InvalidSpec("spec.selected_candidate must match the corroborated winner")
        selected = next(idea for idea in validate_idea_pool(dossier["pool"])["ideas"] if idea["id"] == checked["seed_id"])
        spec.setdefault("selected_seed_id", selected["id"])
        spec.setdefault("selected_concept", selected)
        verify_selection_binding(spec, dossier, checked)
    elif selection is not None:
        if spec["mode"] not in ("auto", "guided") or not isinstance(selection, dict) or not selection.get("final_winner"):
            raise InvalidSpec("candidate selection is invalid")
        if spec.get("selected_candidate") != selection["final_winner"]:
            raise InvalidSpec("spec.selected_candidate must match the validated debate winner")
    base = Path(base_dir).expanduser().resolve(strict=True)
    if not base.is_dir():
        raise InvalidSpec("base-dir must be an existing directory")
    destination = base / spec["slug"]
    # mkdir(exist_ok=False) is exclusive; never overwrite an old project, even if empty.
    destination.mkdir(exist_ok=False)
    try:
        (destination / ".just-build").mkdir()
        (destination / "PROJECT_BRIEF.md").write_text(render_brief(spec), encoding="utf-8")
        (destination / "README.md").write_text(
            f"# {escape_md(spec['name'])}\n\n{escape_md(spec['summary'])}\n\n"
            "## Implementation handoff\n\nThis is an initial scaffold only. Codex must now implement the first working vertical slice, add tests, and replace this note with runnable setup and test instructions before claiming completion.\n\nSee [PROJECT_BRIEF.md](PROJECT_BRIEF.md).\n",
            encoding="utf-8")
        (destination / ".gitignore").write_text(".env\n.env.*\n!.env.example\n__pycache__/\n.pytest_cache/\n.venv/\nnode_modules/\ndist/\nbuild/\n.DS_Store\n", encoding="utf-8")
        record = {**spec, "scaffolded_at_utc": datetime.now(timezone.utc).isoformat()}
        if corroborated:
            record["idea_selection"] = checked
            record["selection_dossier_sha256"] = digest(dossier)
            (destination / ".just-build" / "idea-validation.json").write_text(json.dumps(dossier, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if selection is not None:
            if selection.get("discovery"):
                record["discovery_summary"] = selection["discovery"]
            record["candidate_decision"] = {key: selection[key] for key in
                ("finalists", "initial_winner", "final_winner", "changed_by_debate", "messages_used", "reviewer_mode", "decision", "score_changes")}
        (destination / ".just-build" / "decision.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        # Only remove the folder exclusively created by this call.
        shutil.rmtree(destination)
        raise
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description="Just Build deterministic Codex skill helpers")
    commands = parser.add_subparsers(dest="command", required=True)
    discovery = commands.add_parser("discover", help="Inspect only root and immediate project subfolders")
    discovery.add_argument("--root", default=".")
    discovery.add_argument("--max-projects", type=int, default=25)
    valid = commands.add_parser("validate", help="Validate a new-project JSON spec")
    valid.add_argument("--spec", required=True)
    scaffold_cmd = commands.add_parser("scaffold", help="Create an exclusive, fresh project scaffold")
    scaffold_cmd.add_argument("--spec", required=True)
    scaffold_cmd.add_argument("--base-dir", required=True)
    scaffold_cmd.add_argument("--candidates", help="Validated candidate input to record the finalist decision")
    scaffold_cmd.add_argument("--pool", help="Discovery pool, required for new idea-led workflows")
    scaffold_cmd.add_argument("--debate", help="Bounded debate JSON; requires --candidates")
    scaffold_cmd.add_argument("--selection", help="Corroborated selection dossier; replaces legacy pool/candidates/debate flags")
    selection_cmd = commands.add_parser("select", help="Compare two research passes and validate the arbiter decision")
    selection_cmd.add_argument("--file", required=True)
    choices_cmd = commands.add_parser("choices", help="Validate choices supplied to guided mode")
    choices_cmd.add_argument("--file", required=True)
    rank_cmd = commands.add_parser("rank", help="Validate and score three or more researched candidates")
    rank_cmd.add_argument("--file", required=True)
    rank_cmd.add_argument("--pool", help="Validate candidate origins and shortlist diversity against this idea pool")
    debate_cmd = commands.add_parser("debate", help="Validate a two-role finalist debate (2-7 short messages)")
    debate_cmd.add_argument("--candidates", required=True)
    debate_cmd.add_argument("--file", required=True)
    debate_cmd.add_argument("--pool", help="Require traced finalist origins in this idea pool")
    pool_cmd = commands.add_parser("pool", help="Validate breadth and duplicates before ranking project ideas")
    pool_cmd.add_argument("--file", required=True)
    inspect_cmd = commands.add_parser("inspect", help="Read-only inspection of an explicitly selected project")
    inspect_cmd.add_argument("--project", required=True)
    check_cmd = commands.add_parser("check", help="Structural post-build verification; does not run project code")
    check_cmd.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            if not 1 <= args.max_projects <= 100:
                raise InvalidSpec("max-projects must be between 1 and 100")
            result = discover(args.root, args.max_projects)
        elif args.command == "choices":
            result = choices_validate(read_json(args.file))
        elif args.command == "pool":
            result = validate_idea_pool(read_json(args.file))
        elif args.command == "select":
            from idea_validation import evaluate_dossier
            result = evaluate_dossier(read_json(args.file))
        elif args.command == "rank":
            result = rank_candidates(read_json(args.file), read_json(args.pool) if args.pool else None)
        elif args.command == "debate":
            result = debate_candidates(read_json(args.candidates), read_json(args.file), read_json(args.pool) if args.pool else None)
        elif args.command == "inspect":
            result = inspect_project(args.project)
        elif args.command == "check":
            result = check_build(args.project)
        else:
            spec = validate_spec(read_json(args.spec))
            if args.command == "scaffold":
                if args.selection and (args.pool or args.candidates or args.debate):
                    raise InvalidSpec("--selection replaces legacy selection flags")
                if bool(args.candidates) != bool(args.debate):
                    raise InvalidSpec("--candidates and --debate must be supplied together")
                if args.pool and not args.debate:
                    raise InvalidSpec("--pool requires both --candidates and --debate")
                selection = debate_candidates(read_json(args.candidates), read_json(args.debate), read_json(args.pool) if args.pool else None) if args.debate else None
                result = {"created": str(scaffold(spec, args.base_dir, selection, read_json(args.selection) if args.selection else None))}
                if selection is not None:
                    result["selected_candidate"] = selection["final_winner"]
            else:
                result = {"valid": True, "slug": spec["slug"]}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.command == "select" and (result["outcome"] != "build" or result["fixture_only"]):
            return 3
        return 0
    except (InvalidSpec, ValueError, FileExistsError, FileNotFoundError, PermissionError, NotADirectoryError, OSError) as exc:
        print(f"just-build: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
