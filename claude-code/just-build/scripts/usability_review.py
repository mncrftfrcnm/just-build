"""Bounded declarations for a simulated first-time user and usability advocate.

These validators cannot establish that an agent actually attempted a journey or
that two claimed identities are independent. The host must execute that work.
"""
from __future__ import annotations

import hashlib
import json
import re

from just_build import InvalidSpec, ensure_string

MAX_ROUNDS = 3
ID = re.compile(r"[a-z][a-z0-9-]{0,39}")
COMMON = {"version", "reviewer_mode", "reviewer_id", "simulation", "assistance", "verdict"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def object_fields(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise InvalidSpec(f"{name} must contain exactly: {', '.join(sorted(fields))}")


def entries(value, name, maximum=12, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise InvalidSpec(f"{name} must contain {minimum}..{maximum} entries")
    return value


def identifier(value, name):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise InvalidSpec(f"{name} must be a short lowercase identifier")
    return value


def common(doc):
    if type(doc.get("version")) is not int or doc["version"] != 1 or doc.get("simulation") is not True:
        raise InvalidSpec("Usability evidence requires version 1 and simulation:true; this is not real-user research")
    if doc.get("reviewer_mode") not in ("subagent", "single-agent-fallback"):
        raise InvalidSpec("Usability reviewer_mode must honestly declare subagent or single-agent-fallback")
    if doc.get("verdict") not in ("pass", "needs-work"):
        raise InvalidSpec("Usability verdict must be pass or needs-work")
    return {"version": 1, "reviewer_mode": doc["reviewer_mode"],
            "reviewer_id": ensure_string(doc.get("reviewer_id"), "usability.reviewer_id", 120),
            "simulation": True, "assistance": ensure_string(doc.get("assistance"), "usability.assistance", 400),
            "verdict": doc["verdict"]}


def submission(doc):
    if isinstance(doc, dict) and "fixture_only" in doc:
        if type(doc["fixture_only"]) is not bool or doc["fixture_only"]:
            raise InvalidSpec("Fixture-only usability examples cannot be submitted as actual observations")
        return {k: v for k, v in doc.items() if k != "fixture_only"}
    return doc


def validate_novice(doc):
    doc = submission(doc)
    object_fields(doc, COMMON | {"goal", "entrypoint", "steps", "difficulties"}, "Novice evidence")
    clean = common(doc)
    clean.update(goal=ensure_string(doc.get("goal"), "novice.goal", 350),
                 entrypoint=ensure_string(doc.get("entrypoint"), "novice.entrypoint", 250))
    steps, seen = [], set()
    for step in entries(doc.get("steps"), "novice.steps", minimum=1):
        object_fields(step, {"id", "action", "expected", "observed", "status"}, "Novice step")
        sid = identifier(step["id"], "novice.step.id")
        if sid in seen or step["status"] not in ("pass", "blocked", "confusing"):
            raise InvalidSpec("Novice steps require distinct IDs and pass, blocked or confusing status")
        seen.add(sid)
        steps.append({"id": sid, "status": step["status"],
                      **{key: ensure_string(step[key], f"novice.step.{key}", 400) for key in ("action", "expected", "observed")}})
    difficulties, ids = [], set()
    for item in entries(doc.get("difficulties"), "novice.difficulties"):
        object_fields(item, {"id", "step_id", "severity", "issue", "evidence"}, "Novice difficulty")
        did = identifier(item["id"], "novice.difficulty.id")
        if (did in ids or not isinstance(item["step_id"], str) or item["step_id"] not in seen
                or item["severity"] not in ("minor", "major", "blocker")):
            raise InvalidSpec("Novice difficulties require distinct IDs, a known step and supported severity")
        ids.add(did)
        difficulties.append({"id": did, "step_id": item["step_id"], "severity": item["severity"],
                             "issue": ensure_string(item["issue"], "novice.difficulty.issue", 300),
                             "evidence": ensure_string(item["evidence"], "novice.difficulty.evidence", 400)})
    if any(s["status"] != "pass" and not any(d["step_id"] == s["id"] for d in difficulties) for s in steps):
        raise InvalidSpec("Every blocked or confusing novice step needs a concrete difficulty")
    if clean["verdict"] == "pass" and (any(s["status"] != "pass" for s in steps)
                                        or any(d["severity"] != "minor" for d in difficulties)):
        raise InvalidSpec("A passing novice retest must complete every step without a major or blocker difficulty")
    clean.update(steps=steps, difficulties=difficulties)
    return clean


def validate_advocate(doc, novice, novice_sha256):
    doc = submission(doc)
    object_fields(doc, COMMON | {"novice_sha256", "summary", "dispositions", "changes", "preserved_acceptance"}, "Advocate evidence")
    clean = common(doc)
    if doc.get("novice_sha256") != novice_sha256:
        raise InvalidSpec("Advocate must reference the exact tracker-captured novice_sha256")
    if doc.get("preserved_acceptance") is not True:
        raise InvalidSpec("Advocate must preserve the frozen acceptance plan and behavior contract")
    if (clean["reviewer_mode"] == novice["reviewer_mode"] == "subagent"
            and clean["reviewer_id"] == novice["reviewer_id"]):
        raise InvalidSpec("Subagent novice and advocate must declare different reviewer identities")
    dispositions, seen = [], set()
    difficulties = {d["id"]: d for d in novice["difficulties"]}
    for item in entries(doc.get("dispositions"), "advocate.dispositions"):
        object_fields(item, {"difficulty_id", "resolution", "evidence"}, "Advocate disposition")
        did = identifier(item["difficulty_id"], "advocate.difficulty_id")
        if did not in difficulties or did in seen or item["resolution"] not in ("fixed", "accepted", "open"):
            raise InvalidSpec("Advocate dispositions must reference each known difficulty exactly once")
        seen.add(did)
        dispositions.append({"difficulty_id": did, "resolution": item["resolution"],
                             "evidence": ensure_string(item["evidence"], "advocate.disposition.evidence", 400)})
    if seen != set(difficulties):
        raise InvalidSpec("Advocate must disposition every novice difficulty")
    if clean["verdict"] == "pass" and (novice["verdict"] != "pass" or any(
            d["resolution"] == "open" or (difficulties[d["difficulty_id"]]["severity"] != "minor"
                                          and d["resolution"] != "fixed") for d in dispositions)):
        raise InvalidSpec("Advocate pass requires a successful fresh novice retest; every difficulty must be fixed or explicitly accepted minor friction")
    clean.update(novice_sha256=novice_sha256, summary=ensure_string(doc.get("summary"), "advocate.summary", 400),
                 dispositions=dispositions, preserved_acceptance=True,
                 changes=[ensure_string(c, "advocate.change", 240) for c in entries(doc.get("changes"), "advocate.changes")])
    return clean
