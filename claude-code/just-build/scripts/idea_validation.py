#!/usr/bin/env python3
"""Evidence-linked selection, not a researcher or a source-truth oracle.

Two frozen research reports are compared conservatively. The comparison cannot
raise scores, waive failed constraints, or turn missing evidence into certainty.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from just_build import InvalidSpec, ensure_list, ensure_string, rank_candidates

PROFILE = "corroborated-v1"
WEIGHTS = {"user_fit": .25, "usefulness": .30, "feasibility": .20,
           "differentiation": .15, "trend": .10}
CONSTRAINTS = {"resources", "privacy_safety", "first_slice"}


def digest(value):
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise InvalidSpec("evidence must contain only finite JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def proposal_digest(candidates, pool):
    return digest({"candidates": candidates, "pool": pool})


def iso_day(value, field):
    if not isinstance(value, str) or len(value) != 10:
        raise InvalidSpec(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidSpec(f"{field} must be YYYY-MM-DD") from exc


def canonical_url(value):
    value = ensure_string(value, "source.url", 1000)
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise InvalidSpec("invalid source URL") from exc
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or port not in (None, 443) or "\\" in value
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise InvalidSpec("web evidence requires a public HTTPS URL without credentials")
    host = url.hostname.lower().rstrip(".")
    if "." not in host or host.endswith((".local", ".localhost", ".internal")):
        raise InvalidSpec("web evidence cannot name local infrastructure")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise InvalidSpec("web evidence cannot name a private address")
    query = sorted((k, v) for k, v in parse_qsl(url.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in ("gclid", "fbclid"))
    return urlunsplit(("https", host.removeprefix("www."), url.path or "/", urlencode(query), ""))


def refs(value, sources, field, minimum=1):
    values = ensure_list(value, field, minimum, 8)
    if any(not isinstance(x, str) or x not in sources for x in values) or len(values) != len(set(values)):
        raise InvalidSpec(f"{field} needs distinct known source IDs")
    return values


def validate_report(doc, role, candidates, pool, as_of):
    if not isinstance(doc, dict) or type(doc.get("version")) is not int or doc["version"] != 1 or doc.get("role") != role:
        raise InvalidSpec(f"expected version-1 {role} report")
    if doc.get("shortlist_sha256") != proposal_digest(candidates, pool):
        raise InvalidSpec("research is stale: shortlist/pool digest mismatch")
    created = iso_day(doc.get("created_on"), "created_on")
    if not 0 <= (as_of - created).days <= 7:
        raise InvalidSpec("research report must be from the last seven days")
    reviewer = doc.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("mode") not in ("single-agent", "subagent"):
        raise InvalidSpec("reviewer.mode must honestly state single-agent or subagent")
    ensure_string(reviewer.get("id"), "reviewer.id", 80)
    if role == "validation" and type(doc.get("blinded")) is not bool:
        raise InvalidSpec("validation must declare whether primary conclusions were withheld")
    if "fixture_only" in doc and type(doc["fixture_only"]) is not bool:
        raise InvalidSpec("fixture_only must be boolean")
    sources, identities = {}, set()
    for source in ensure_list(doc.get("sources"), "sources", 1, 40):
        if not isinstance(source, dict):
            raise InvalidSpec("source must be an object")
        ident = ensure_string(source.get("id"), "source.id", 80)
        publisher = ensure_string(source.get("publisher"), "source.publisher", 100).casefold()
        ensure_string(source.get("finding"), "source.finding", 700)
        observed = iso_day(source.get("observed_on"), "source.observed_on")
        if not 0 <= (created - observed).days <= 30:
            raise InvalidSpec("source access must precede report and be within thirty days")
        kind = source.get("kind")
        if kind == "web":
            identity = canonical_url(source.get("url"))
        elif kind in ("user", "local"):
            identity = kind + ":" + ensure_string(source.get("locator"), "source.locator", 200)
        else:
            raise InvalidSpec("source.kind must be web, user or local")
        published = source.get("published_on")
        if published is not None and iso_day(published, "published_on") > observed:
            raise InvalidSpec("source publication cannot follow access date")
        if ident in sources or identity in identities:
            raise InvalidSpec("duplicate source ID or canonical location")
        sources[ident] = {**source, "publisher": publisher, "identity": identity}
        identities.add(identity)
    expected = {x["seed_id"] for x in candidates["candidates"]}
    assessments = {}
    for item in ensure_list(doc.get("assessments"), "assessments", len(expected), len(expected)):
        if not isinstance(item, dict) or not isinstance(item.get("seed_id"), str) or item["seed_id"] not in expected or item["seed_id"] in assessments:
            raise InvalidSpec("each shortlisted seed needs exactly one assessment")
        scores = item.get("scores")
        evidence = item.get("score_evidence")
        if not isinstance(scores, dict) or set(scores) != set(WEIGHTS) or not isinstance(evidence, dict) or set(evidence) != set(WEIGHTS):
            raise InvalidSpec("scores and score_evidence must cover every selection dimension")
        for dimension, score in scores.items():
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 5:
                raise InvalidSpec("scores must be finite numbers from zero to five")
            cited = refs(evidence[dimension], sources, dimension, 0 if score == 0 else 1)
            if dimension == "user_fit" and score >= 3 and not any(sources[x]["kind"] == "user" for x in cited):
                raise InvalidSpec("strong user fit needs accessible user-stated context")
            if dimension == "trend" and score > 0:
                publishers = set()
                for ident in cited:
                    source = sources[ident]
                    if source["kind"] != "web" or not source.get("published_on") or not 0 <= (as_of - iso_day(source["published_on"], "trend date")).days <= 30:
                        raise InvalidSpec("trend points require current dated web evidence")
                    publishers.add(source["publisher"])
                if len(publishers) < 2:
                    raise InvalidSpec("trend points need two editorial origins, not repeated hype")
        constraints = item.get("constraints")
        if not isinstance(constraints, dict) or set(constraints) != CONSTRAINTS:
            raise InvalidSpec("all hard constraints must be explicitly assessed")
        for constraint in constraints.values():
            if not isinstance(constraint, dict) or constraint.get("status") not in ("pass", "fail", "unknown"):
                raise InvalidSpec("constraint status must be pass, fail or unknown")
            ensure_string(constraint.get("reason"), "constraint.reason", 500)
            refs(constraint.get("evidence"), sources, "constraint.evidence", 0 if constraint["status"] == "unknown" else 1)
        for field in ("need", "disconfirming"):
            record = item.get(field)
            if not isinstance(record, dict):
                raise InvalidSpec(f"assessment requires {field}")
            ensure_string(record.get("finding"), field + ".finding", 600)
            refs(record.get("evidence"), sources, field + ".evidence")
        gap = item.get("differentiation")
        if not isinstance(gap, dict):
            raise InvalidSpec("differentiation needs actual alternatives and a falsifiable advantage")
        for field in ("advantage", "falsifier", "test"):
            ensure_string(gap.get(field), "differentiation." + field, 600)
        names = set()
        for alternative in ensure_list(gap.get("alternatives"), "alternatives", 2, 5):
            if not isinstance(alternative, dict):
                raise InvalidSpec("alternative must be an object")
            name = ensure_string(alternative.get("name"), "alternative.name", 100).casefold()
            if name in names:
                raise InvalidSpec("alternatives must be distinct")
            names.add(name)
            refs(alternative.get("evidence"), sources, "alternative.evidence")
        refs(gap.get("evidence"), sources, "differentiation.evidence")
        assessments[item["seed_id"]] = item
    return sources, assessments


def assessment_refs(item):
    result = set()
    for values in item["score_evidence"].values():
        result.update(values)
    for row in item["constraints"].values():
        result.update(row["evidence"])
    for key in ("need", "disconfirming", "differentiation"):
        result.update(item[key]["evidence"])
    for row in item["differentiation"]["alternatives"]:
        result.update(row["evidence"])
    return result


def select_idea(candidates, pool, primary, validation, arbitration, as_of):
    day = iso_day(as_of, "as_of")
    rank_candidates(candidates, pool)  # preserve discovery breadth/provenance validation
    a_sources, a_rows = validate_report(primary, "primary", candidates, pool, day)
    b_sources, b_rows = validate_report(validation, "validation", candidates, pool, day)
    if primary["reviewer"]["mode"] == validation["reviewer"]["mode"] == "subagent" and primary["reviewer"]["id"] == validation["reviewer"]["id"]:
        raise InvalidSpec("the same reviewer cannot be claimed as two independent subagents")
    if not isinstance(arbitration, dict) or type(arbitration.get("version")) is not int or arbitration.get("version") != 1:
        raise InvalidSpec("expected version-1 arbitration")
    if arbitration.get("primary_sha256") != digest(primary) or arbitration.get("validation_sha256") != digest(validation):
        raise InvalidSpec("arbitration is stale: research report digest mismatch")
    # A mirrored URL cannot become independent merely by renaming its publisher.
    by_identity = {s["identity"]: s["publisher"] for s in a_sources.values()}
    for source in b_sources.values():
        if source["identity"] in by_identity and by_identity[source["identity"]] != source["publisher"]:
            raise InvalidSpec("the same evidence location has conflicting editorial-origin labels")
    known = {"primary:" + k: v for k, v in a_sources.items()}
    known.update({"validation:" + k: v for k, v in b_sources.items()})
    resolutions = {}
    for item in ensure_list(arbitration.get("resolutions", []), "resolutions", 0, 30):
        if not isinstance(item, dict) or not isinstance(item.get("seed_id"), str) or item["seed_id"] not in a_rows or not isinstance(item.get("dimension"), str) or item["dimension"] not in WEIGHTS:
            raise InvalidSpec("resolution must identify a shortlisted seed and score dimension")
        key = (item["seed_id"], item["dimension"])
        if key in resolutions:
            raise InvalidSpec("duplicate discrepancy resolution")
        if abs(a_rows[key[0]]["scores"][key[1]] - b_rows[key[0]]["scores"][key[1]]) <= 1.5:
            raise InvalidSpec("resolution must address an actual material score discrepancy")
        ensure_string(item.get("reason"), "resolution.reason", 600)
        cited = refs(item.get("evidence"), known, "resolution.evidence", 2)
        allowed = {"primary:" + x for x in a_rows[key[0]]["score_evidence"][key[1]]}
        allowed.update("validation:" + x for x in b_rows[key[0]]["score_evidence"][key[1]])
        if not set(cited) <= allowed or not any(x.startswith("primary:") for x in cited) or not any(x.startswith("validation:") for x in cited):
            raise InvalidSpec("resolution must compare this dimension's evidence from both passes")
        resolutions[key] = item
    rows = []
    for seed, a in a_rows.items():
        b = b_rows[seed]
        scores = {k: min(a["scores"][k], b["scores"][k]) for k in WEIGHTS}
        rejected, unresolved = [], []
        for key in CONSTRAINTS:
            statuses = {a["constraints"][key]["status"], b["constraints"][key]["status"]}
            if "fail" in statuses:
                rejected.append("failed constraint: " + key)
            elif "unknown" in statuses:
                unresolved.append("unknown constraint: " + key)
        for dimension in WEIGHTS:
            if dimension == "user_fit" and scores[dimension] < 3:
                unresolved.append("personalization is unproven; try an exploratory local experiment")
            elif dimension != "trend" and scores[dimension] < 3:
                rejected.append("insufficient " + dimension)
            if abs(a["scores"][dimension] - b["scores"][dimension]) > 1.5 and (seed, dimension) not in resolutions:
                unresolved.append("unresolved score discrepancy: " + dimension)
        a_used = [a_sources[x] for x in assessment_refs(a)]
        # Independent *material* evidence must support need or the competitive gap,
        # not an unrelated link dropped into a safety/score field.
        b_material = set(b["need"]["evidence"] + b["differentiation"]["evidence"])
        a_publishers = {x["publisher"] for x in a_used}
        a_locations = {x["identity"] for x in a_used}
        fresh = [b_sources[x] for x in b_material if b_sources[x]["publisher"] not in a_publishers and b_sources[x]["identity"] not in a_locations]
        if not fresh:
            unresolved.append("no additional editorial origin for need or differentiation")
        if not validation["blinded"]:
            unresolved.append("validation saw primary conclusions; repeat a blinded pass")
        total = round(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), 6)
        rows.append({"seed_id": seed, "name": next(x["name"] for x in candidates["candidates"] if x["seed_id"] == seed),
                     "score": total, "scores": scores,
                     "status": "reject" if rejected else "experiment" if unresolved else "build",
                     "reasons": sorted(rejected + unresolved), "additional_origins": sorted({x["publisher"] for x in fresh})})
    rows.sort(key=lambda r: (-r["score"], r["seed_id"]))
    eligible = [r for r in rows if r["status"] == "build"]
    potential = [r for r in rows if r["status"] != "reject"]
    if eligible:
        selected, outcome = eligible[0], "build"
        if len(eligible) > 1 and eligible[0]["score"] - eligible[1]["score"] < .15:
            outcome = "experiment"
    elif potential:
        selected, outcome = potential[0], "experiment"
    else:
        selected, outcome = None, "no-build"
    decision = arbitration.get("decision")
    if not isinstance(decision, dict) or decision.get("outcome") != outcome or decision.get("seed_id") != (selected["seed_id"] if selected else None):
        raise InvalidSpec("arbiter decision must match the conservative computed outcome and candidate")
    ensure_string(decision.get("reason"), "decision.reason", 700)
    if outcome == "experiment":
        experiment = arbitration.get("experiment")
        if not isinstance(experiment, dict):
            raise InvalidSpec("experiment outcome needs a bounded, falsifiable experiment")
        for key in ("hypothesis", "procedure", "success", "failure"):
            ensure_string(experiment.get(key), "experiment." + key, 600)
        if type(experiment.get("max_minutes")) is not int or not 1 <= experiment["max_minutes"] <= 120 or type(experiment.get("max_cost")) not in (int, float) or experiment["max_cost"] != 0:
            raise InvalidSpec("default experiment must be zero-cost and at most 120 minutes")
    return {"profile": PROFILE, "outcome": outcome, "winner": selected["name"] if selected else None,
            "seed_id": selected["seed_id"] if selected else None, "ranked": rows, "weights": WEIGHTS,
            "fixture_only": primary.get("fixture_only", False) or validation.get("fixture_only", False),
            "reviewer_mode": "subagents" if primary["reviewer"]["mode"] == validation["reviewer"]["mode"] == "subagent" else "single-agent-fallback",
            "as_of": as_of, "proposal_sha256": proposal_digest(candidates, pool),
            "primary_sha256": digest(primary), "validation_sha256": digest(validation),
            "arbitration_sha256": digest(arbitration),
            "caveat": "Source truth, editorial independence, blind execution and reviewer identity are declarations; hashes detect changes, not dishonesty. This is a bounded choice, not proof of the best possible idea."}


def evaluate_dossier(dossier):
    if not isinstance(dossier, dict):
        raise InvalidSpec("selection dossier must be an object")
    try:
        return select_idea(**{key: dossier[key] for key in ("candidates", "pool", "primary", "validation", "arbitration", "as_of")})
    except KeyError as exc:
        raise InvalidSpec(f"selection dossier missing {exc.args[0]}") from exc


def require_current(dossier):
    # A client's local date may differ from UTC by one day. Prevent old dossiers
    # being replayed as current research at the build/run boundary.
    delta = (datetime.now(timezone.utc).date() - iso_day(dossier.get("as_of"), "as_of")).days
    if not -1 <= delta <= 1:
        raise InvalidSpec("selection date is stale; compare reports again using today's client date")
