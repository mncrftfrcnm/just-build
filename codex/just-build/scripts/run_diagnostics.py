"""Read-only, bounded recovery guidance for an existing Just Build ledger.

This inspects recorded evidence and current files. It never runs acceptance
commands, fetches research, repairs history or regenerates reports. Hints are
authored constants; private run text is deliberately not included.
"""
from __future__ import annotations

import re

MAX_ISSUES = 64
LABEL = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
HINTS = {
    "inspect-run": "Inspect the selected ledger; preserve its history before starting a continuation.",
    "new-continuation": "Preserve the completed or exhausted run and start a new continuation for further work.",
    "restore-source": "Restore access to the selected regular project files; diagnostics cannot verify unavailable content.",
    "produce-delivery": "Produce or restore every declared output without changing the frozen acceptance requirements.",
    "resolve-blocker": "Resolve the recorded blocker, then reactivate that same stage; preserve the blocker history.",
    "record-blocker": "Record an honest quality blocker; the bounded usability repair rounds are exhausted.",
    "record-plan": "Record a concrete acceptance plan during the active plan stage.",
    "freeze-contract": "Freeze the required external behavior contract before completing planning.",
    "record-research": "Record sourced implementation research for the missing planned topic indices; do not fabricate unavailable evidence.",
    "run-probe": "Execute a meaningful in-development probe during implementation; no command is executed by diagnostics.",
    "run-verification": "Execute or repair the missing, failed or stale checks in this phase on unchanged files; preserve every frozen acceptance requirement.",
    "record-structural": "Run the new-project structural gate in the active verification phase.",
    "record-novice": "Run a fresh first-time-user simulation through the public entry path, then have the advocate hear it.",
    "record-advocate": "Have the usability advocate disposition the retained novice difficulties before another novice round.",
    "record-review": "Submit a fresh passing review for the indicated active review stage after resolving its findings.",
    "security-scan": "Run the passive local security scan after polish and before final verification.",
    "security-review": "Submit a fresh security review against the current passive scan after resolving its findings.",
    "recheck": "Use recheck to reopen quality, usability, polish and final verification while retaining frozen acceptance and history.",
    "activate-stage": "Activate the indicated pending stage after its earlier gates are satisfied.",
    "finish-stage": "Finish the current stage only after its recorded requirements are satisfied.",
}


def diagnose(directory):
    """Inspect a ledger read-only, returning safe JSON even for damaged evidence."""
    try:
        return _diagnose(directory)
    except (KeyError, TypeError, AttributeError, ValueError, OSError):
        # Existing readable ledger schemas do not validate every nested evidence
        # field. Keep a damaged record from leaking private exception details.
        return {"schema_version": 1, "current_stage": None, "complete": False,
                "issues": [{"code": "STATE_INVALID", "stage": None}],
                "issues_truncated": False, "recheck_allowed": False,
                "next_action": {"action": "inspect-run", "stage": None, "hint": HINTS["inspect-run"]}}


def _diagnose(directory):
    """Return a bounded JSON-compatible status without writing or executing code.

    Labels are validated identifiers; private topics and output paths are exposed
    only as zero-based indices into the already selected plan. The readiness
    booleans come from the same tracker predicates used by stage completion.
    """
    import run_tracker as tracker

    def unreadable(code):
        return {"schema_version": 1, "current_stage": None, "complete": False,
                "issues": [{"code": code, "stage": None}],
                "issues_truncated": False, "recheck_allowed": False,
                "next_action": {"action": "inspect-run", "stage": None, "hint": HINTS["inspect-run"]}}

    try:
        _, data = tracker.load(directory)
    except (OSError, ValueError, TypeError):
        return unreadable("STATE_UNREADABLE")
    # load() deliberately preserves readable historical ledgers. Diagnose also
    # handles damaged nested evidence without echoing parser errors or run text.
    if (not isinstance(data.get("project"), str)
            or any(not isinstance(row, dict) or not isinstance(row.get("label"), str) or not LABEL.fullmatch(row["label"])
                   for row in data["tests"])
            or not isinstance(data.get("structural_checks", []), list)
            or any(not isinstance(row, dict) for row in data.get("structural_checks", []))
            or any(not isinstance(row, dict) for row in data.get("research_evidence", []))
            or any(not isinstance(row, dict) for row in data.get("reviews", {}).values())
            or data.get("behavior_contract") is not None and not isinstance(data["behavior_contract"], dict)
            or data.get("security_scan") is not None and not isinstance(data["security_scan"], dict)):
        return unreadable("STATE_INVALID")
    usability_state = data.get("usability")
    if usability_state is not None and (not isinstance(usability_state, dict)
            or not isinstance(usability_state.get("rounds"), list)
            or len(usability_state["rounds"]) > tracker.MAX_USABILITY_ROUNDS
            or any(not isinstance(row, dict) or not isinstance(row.get("novice"), dict)
                   or row.get("advocate") is not None and not isinstance(row["advocate"], dict)
                   for row in usability_state["rounds"])):
        return unreadable("STATE_INVALID")

    issues = []

    def issue(code, stage, **extra):
        issues.append({"code": code, "stage": stage, **extra})

    stages = {name: data["stages"][name]["status"] for name in tracker.STAGES}
    current_stage = next((name for name in tracker.STAGES if stages[name] not in ("done", "skipped")), "complete")
    plan = data.get("plan")
    if not plan:
        issue("PLAN_MISSING", "plan")
        plan = {}
    else:
        try:
            plan = tracker.plan_validate(plan)
        except (ValueError, TypeError, KeyError):
            issue("PLAN_INVALID", "plan")
            return {"schema_version": 1, "current_stage": current_stage, "stages": stages,
                    "complete": False, "issues": issues, "issues_truncated": False,
                    "recheck_allowed": False,
                    "next_action": {"action": "inspect-run", "stage": "plan", "hint": HINTS["inspect-run"]}}

    for stage, status in stages.items():
        if status == "blocked":
            issue("STAGE_BLOCKED", stage)
    source_available = True
    try:
        tracker.project_fingerprint(data["project"])
    except (OSError, ValueError, TypeError, KeyError):
        source_available = False
        issue("SOURCE_UNAVAILABLE", current_stage)
    artifacts = plan.get("delivery_artifacts", [])
    missing_outputs, delivery_available = [], True
    try:
        entries = tracker.delivery_entries(data["project"], artifacts, require=False)
        missing_outputs = [index for index, (_, digest) in enumerate(entries) if digest is None]
        if missing_outputs:
            issue("DELIVERY_MISSING", current_stage, indices=missing_outputs)
    except (OSError, ValueError, TypeError, KeyError):
        delivery_available = False
        if artifacts:
            issue("DELIVERY_UNAVAILABLE", current_stage)
    fingerprint = None
    if source_available and delivery_available and not missing_outputs:
        try:
            fingerprint = tracker.run_fingerprint(data)
        except (OSError, ValueError, TypeError, KeyError):
            source_available = False
            issue("SOURCE_UNAVAILABLE", current_stage)

    external = plan.get("contract_profile") in ("external-cli", "external-api")
    contract = data.get("behavior_contract")
    if external and not contract:
        issue("CONTRACT_MISSING", "plan")

    required = sorted({task["test_label"] for task in plan.get("tasks", [])}
                      | ({plan["smoke_label"]} if plan else set())
                      | {item["test_label"] for item in plan.get("experience_checks", [])}
                      | ({"external-contract"} if external else set()))

    def verification(phase):
        sealed = phase == "verify" and stages[phase] == "done" and bool(data["stages"][phase].get("verified_fingerprint"))
        target = data["stages"][phase]["verified_fingerprint"] if sealed else fingerprint
        by_label = {row["label"]: row for row in tracker.latest_tests(data, phase)}
        checks = []
        for label in required:
            row = by_label.get(label)
            status = "missing" if row is None else "current"
            if row is not None:
                if (row.get("exit_code") != 0 or row.get("timeout") or not row.get("snapshot_stable")):
                    status = "failed"
                elif label == "external-contract" and (not contract or row.get("contract_sha256") != contract.get("sha256") or not row.get("contract_steps", 0)):
                    status = "failed"
                elif target is None:
                    status = "unavailable"
                elif row.get("source_fingerprint") != target:
                    status = "stale"
            checks.append({"label": label if LABEL.fullmatch(label) else "invalid-label", "status": status})
            if status != "current":
                issue("CHECK_" + status.upper(), phase, label=checks[-1]["label"])
        # The tracker also rejects a failed latest exploratory execution in the
        # phase. Passing required labels alone cannot hide that failure.
        additional_failed = sorted(label for label, row in by_label.items() if label not in required
                                   and (row.get("exit_code") != 0 or row.get("timeout") or not row.get("snapshot_stable")))
        for label in additional_failed[:12]:
            issue("CHECK_FAILED", phase, label=label, required=False)
        structural = "not-required"
        if data.get("operation") == "new":
            rows = [row for row in data.get("structural_checks", []) if row.get("stage", "verify") == phase]
            structural = "missing" if not rows else "current"
            if rows:
                if not rows[-1].get("passed"):
                    structural = "failed"
                elif target is None:
                    structural = "unavailable"
                elif rows[-1].get("source_fingerprint") != target:
                    structural = "stale"
            if structural != "current":
                issue("STRUCTURAL_" + structural.upper(), phase)
        ready = tracker.verification_ready(data, phase)
        return {"ready": ready, "freshness_scope": "sealed-historical" if sealed else "current-files",
                "checks": checks, "additional_failed_labels": additional_failed[:12],
                "additional_failed_count": len(additional_failed), "structural": structural}

    phases = {phase: verification(phase) for phase in ("verify", "final-verify")}
    rigorous = plan.get("autonomy_profile") == "rigorous"
    missing_topics = [index for index, topic in enumerate(plan.get("research_topics", []))
                      if not any(row.get("phase") == "implementation" and row.get("kind") == "web" and row.get("topic") == topic
                                 for row in data.get("research_evidence", []))] if rigorous else []
    probe = any(row.get("stage") == "implement" and row.get("exit_code") == 0 and row.get("snapshot_stable") for row in data["tests"])
    if missing_topics:
        issue("IMPLEMENTATION_RESEARCH_MISSING", "implement", indices=missing_topics)
    if rigorous and not probe:
        issue("IMPLEMENTATION_PROBE_MISSING", "implement")

    def review_state(role):
        row = data.get("reviews", {}).get(role)
        if not row:
            return "missing"
        if row.get("verdict") != "pass":
            return "failed"
        if fingerprint is None:
            return "unavailable"
        return "current" if row.get("source_fingerprint") == fingerprint else "stale"

    reviews = {role: review_state(role) for role in tracker.REVIEW_CHECKS}
    for role, status in reviews.items():
        if status != "current":
            issue(role.upper() + "_" + status.upper(), role)
    secure = plan.get("security_profile") == "full"
    scan = data.get("security_scan")
    scan_status = ("not-required" if not secure else "missing" if not scan else "unavailable" if fingerprint is None
                   else "current" if scan.get("source_fingerprint") == fingerprint else "stale")
    security_status = review_state("security") if secure else "not-required"
    if secure:
        if scan_status != "current":
            issue("SECURITY_SCAN_" + scan_status.upper(), "security")
        if security_status != "current":
            issue("SECURITY_REVIEW_" + security_status.upper(), "security")

    usability_required = plan.get("usability_profile") == "novice-v1"
    state = data.get("usability") or {}
    rounds = state.get("rounds", [])
    pair = tracker.current_usability_round(data)
    orphan = bool(rounds and isinstance(rounds[-1], dict) and rounds[-1].get("advocate") is None)
    usability_ready = tracker.usability_ready(data)
    usability = "not-required"
    if usability_required:
        if usability_ready:
            usability = "current"
        elif orphan:
            usability = "orphaned"
        elif not pair:
            usability = "pending"
        elif fingerprint is None:
            usability = "unavailable"
        elif (pair.get("novice", {}).get("source_fingerprint") != fingerprint
              or pair.get("novice", {}).get("acceptance_sha256") != tracker.usability_scope(data)):
            usability = "stale"
        else:
            usability = "needs-work"
        if usability != "current":
            issue("USABILITY_" + usability.upper().replace("-", "_"), "quality")
    cap = usability_required and len(rounds) >= tracker.MAX_USABILITY_ROUNDS and not usability_ready
    if cap:
        issue("USABILITY_ROUND_LIMIT", "quality")
    allowed = tracker.recheck_allowed(data)
    done = tracker.complete(data)
    if stages["final-verify"] == "done" and not phases["final-verify"]["ready"]:
        issue("FINAL_SNAPSHOT_STALE", "final-verify")

    def action(name, stage=current_stage):
        return {"action": name, "stage": None if stage == "complete" else stage, "hint": HINTS[name]}

    if stages["handoff"] == "done":
        next_action = action("new-continuation", None)
    elif not source_available or not delivery_available:
        next_action = action("restore-source")
    elif missing_outputs:
        next_action = action("produce-delivery")
    elif cap and not orphan:
        next_action = action("recheck" if stages["quality"] == "done" and allowed else
                             "new-continuation" if stages["quality"] == "blocked" else "record-blocker", "quality")
    elif current_stage != "complete" and stages[current_stage] == "blocked":
        next_action = action("resolve-blocker")
    elif allowed and (any(reviews[role] != "current" for role in reviews if stages[role] == "done")
                      or not usability_ready or stages["final-verify"] == "done" and not phases["final-verify"]["ready"]
                      or secure and stages["final-verify"] in ("active", "done") and not tracker.security_review_ready(data)):
        next_action = action("recheck", "quality")
    elif current_stage == "final-verify" and secure and not tracker.security_review_ready(data):
        next_action = action("security-scan" if scan_status != "current" else "security-review", "security")
    elif current_stage != "complete" and stages[current_stage] == "pending":
        next_action = action("activate-stage")
    elif current_stage == "plan" and not plan:
        next_action = action("record-plan")
    elif current_stage == "plan" and external and not contract:
        next_action = action("freeze-contract")
    elif current_stage == "implement" and missing_topics:
        next_action = action("record-research")
    elif current_stage == "implement" and rigorous and not probe:
        next_action = action("run-probe")
    elif current_stage == "quality" and usability_required and not usability_ready:
        next_action = action("record-advocate" if orphan else "record-novice")
    elif current_stage in reviews and reviews[current_stage] != "current":
        next_action = action("record-review")
    elif current_stage in phases and not phases[current_stage]["ready"]:
        check_problem = (any(check["status"] != "current" for check in phases[current_stage]["checks"])
                         or phases[current_stage]["additional_failed_count"] > 0)
        next_action = action("run-verification" if check_problem else "record-structural")
    else:
        next_action = action("finish-stage")
    return {"schema_version": 1, "current_stage": current_stage, "stages": stages, "complete": done,
            "snapshot": {"source_available": source_available, "delivery_available": delivery_available,
                         "declared_outputs": len(artifacts), "missing_output_indices": missing_outputs},
            "verification": phases,
            "implementation": {"research_required": rigorous, "missing_topic_indices": missing_topics,
                               "research_ready": tracker.implementation_research_ready(data) if rigorous else True,
                               "passing_probe_recorded": probe},
            "reviews": reviews,
            "security": {"required": secure, "scan": scan_status, "review": security_status,
                         "ready": tracker.security_review_ready(data)},
            "usability": {"required": usability_required, "status": usability, "ready": usability_ready,
                          "rounds": len(rounds), "round_limit": tracker.MAX_USABILITY_ROUNDS, "at_limit": cap},
            "issues": issues[:MAX_ISSUES], "issues_truncated": len(issues) > MAX_ISSUES,
            "recheck_allowed": allowed, "next_action": next_action}
