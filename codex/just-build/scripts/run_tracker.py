#!/usr/bin/env python3
"""Just Build: snapshot-bound checks, external contracts and sequential review gates.

No autonomous claims: only test commands this script actually executes count as
execution evidence. Codex remains responsible for research and implementation.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
from datetime import datetime, timezone
from urllib.parse import urlsplit
import html
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

from just_build import InvalidSpec, check_build, ensure_string, read_json
from behavior_contract import validate as validate_behavior_contract, run as execute_behavior_contract, ContractError
from api_contract import validate as validate_api_contract, run as execute_api_contract, APIContractError
from security_audit import scan as scan_local_security
from host_safety import is_link, checked_path, regular_bytes, regular_text, walk_regular, safe_relative
from process_runner import run_command, ProcessSafetyError
from usability_review import validate_novice, validate_advocate, digest as usability_digest, MAX_ROUNDS as MAX_USABILITY_ROUNDS

STAGES = ("research", "plan", "implement", "verify", "quality", "polish", "final-verify", "handoff")  # legacy state remains readable; secure review is a guarded pre-final gate
REVIEW_CHECKS = {
    "quality": ("journey", "edge-cases", "test-strength", "security", "documentation"),
    "polish": ("wording", "usability", "consistency", "accessibility", "handoff"),
}
IGNORED = {".git", ".just-build", ".just-build-runs", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", "dist", "build", ".next", "coverage"}
STATES = ("pending", "active", "done", "blocked", "skipped")
NODE_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_EVENTS = 200
TEST_FOCUS = {"journey", "edge", "unit", "integration", "accessibility", "other"}
POLISH_TARGETS = {"first-run", "empty-state", "error-state", "visual-hierarchy", "keyboard", "responsive", "microcopy", "help-output"}
EXPERIENCE_SCENARIOS = {"first-run", "returning-user", "empty-state", "error-recovery", "keyboard-flow", "narrow-layout", "help-discovery", "invalid-input", "integration-boundary"}
SURFACES = {"web", "desktop", "cli", "api", "library"}
MAX_DELIVERY_ARTIFACTS = 32
MAX_DELIVERY_FILE_BYTES = 8_000_000
MAX_DELIVERY_TOTAL_BYTES = 20_000_000


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def escape(value):
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ")


def mermaid_label(value):
    # All Mermaid syntax is authored here; input is only shown as escaped text.
    return html.escape(str(value), quote=True).replace("[", "&#91;").replace("]", "&#93;").replace("{", "&#123;").replace("}", "&#125;").replace("\n", " ").replace("\r", " ").replace("`", "&#96;")


def atomic_write(path, value):
    path = Path(path)
    if is_link(path):
        raise InvalidSpec("refusing to overwrite a symlinked report/state file")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".just-build-write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(value)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def state_path(directory):
    directory = Path(directory).expanduser()
    if is_link(directory):
        raise InvalidSpec("state-dir cannot be a symlink")
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise InvalidSpec("state-dir must be a directory")
    run = directory / "run.json"
    if is_link(run):
        raise InvalidSpec("run.json cannot be a symlink")
    return run


def load(directory):
    path = state_path(directory)
    try:
        data = read_json(path, root=path.parent)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Cannot read run state: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 2 or not isinstance(data.get("stages"), dict) or set(data["stages"]) != set(STAGES):
        raise InvalidSpec("Invalid schema-v2 run state; preserve older run and start a new continuation ledger")
    if any(not isinstance(data["stages"][s], dict) or data["stages"][s].get("status") not in STATES for s in STAGES):
        raise InvalidSpec("Invalid recorded stage status")
    if not isinstance(data.get("tests"), list) or not isinstance(data.get("events"), list) or not isinstance(data.get("reviews", {}), dict) or not isinstance(data.get("research_evidence", []), list):
        raise InvalidSpec("Invalid recorded evidence lists")
    return path, data


def save(path, data):
    for name in ("run.json", "PLAN.md", "PROGRESS.md", "ARCHITECTURE.md", "WORKFLOW.md", "BRIEF.md", "REVIEWS.md", "REPORT.md", "RESEARCH.md", "SECURITY_AUDIT.md", "USABILITY.md"):
        if is_link(path.parent / name):
            raise InvalidSpec(f"refusing to overwrite symlinked generated file: {name}")
    if len(data.get("events", [])) > MAX_EVENTS:
        raise InvalidSpec(f"Run event limit reached ({MAX_EVENTS}); start a new run")
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    render(path.parent, data)


def init(directory, project, mode, operation, goal):
    if mode not in ("auto", "guided") or operation not in ("new", "continue"):
        raise InvalidSpec("Invalid mode or operation")
    goal = ensure_string(goal, "goal", 300)
    project = Path(project).expanduser()
    if is_link(project):
        raise InvalidSpec("project cannot be a symlink")
    project = project.resolve(strict=True)
    if not project.is_dir():
        raise InvalidSpec("project must exist")
    directory = Path(directory).expanduser()
    if is_link(directory):
        raise InvalidSpec("state-dir cannot be a symlink")
    if operation == "continue" and (directory.absolute().is_relative_to(project)
                                    or directory.resolve(strict=False).is_relative_to(project)):
        raise InvalidSpec("continuation state must be outside the existing project")
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=False)
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise InvalidSpec("state-dir must be a directory")
    entries = {p.name for p in directory.iterdir()}
    selection_summary = None
    if entries and not (directory == project / ".just-build" and "decision.json" in entries and entries <= {"decision.json", "idea-validation.json"}):
        raise InvalidSpec("state-dir must be empty (or the new project's untouched .just-build directory)")
    if operation == "new":
        if directory != project / ".just-build" or "decision.json" not in entries:
            raise InvalidSpec("new runs must use the project's scaffold-created .just-build folder")
        check_build(project)  # validates the scaffold decision spec without executing code
        from just_build import read_json
        decision = read_json(directory / "decision.json")
        if decision.get("selection_profile") == "corroborated-v1":
            from idea_validation import evaluate_dossier, digest, require_current
            dossier = read_json(directory / "idea-validation.json")
            checked = evaluate_dossier(dossier)
            require_current(dossier)
            if (checked["outcome"] != "build" or checked["fixture_only"]
                    or checked != decision.get("idea_selection")
                    or digest(dossier) != decision.get("selection_dossier_sha256")
                    or checked["winner"] != decision.get("selected_candidate")):
                raise InvalidSpec("new run selection evidence is stale, missing or inconsistent")
            selection_summary = checked
    record = {"schema_version": 2, "run_id": uuid.uuid4().hex[:12], "started_at": now(),
              "project": str(project), "mode": mode, "operation": operation, "goal": goal,
              "stages": {s: {"status": "active" if s == "research" else "pending", "note": "", "at": None} for s in STAGES},
              "events": [{"at": now(), "stage": "research", "status": "active", "note": "Run started"}],
              "tests": [], "structural_checks": [], "architecture": None, "plan": None, "reviews": {}, "research_evidence": [], "final_fingerprint": None, "behavior_contract": None, "security_scan": None, "security_history": [], "idea_selection": selection_summary}
    save(directory / "run.json", record)
    return record


def record_stage(directory, stage, status, note):
    path, data = load(directory)
    if stage not in STAGES or status not in STATES[1:]:
        raise InvalidSpec("Invalid stage or status")
    note = ensure_string(note, "note", 350)
    item = data["stages"][stage]
    i = STAGES.index(stage)
    if ((status == "done" and stage == "quality") or
            (status in ("active", "done") and stage in ("polish", "final-verify", "handoff"))):
        if not usability_ready(data):
            raise InvalidSpec("A fresh passing novice simulation and usability advocate are required before quality completion, polish or final handoff; rerun inside quality or use recheck after later edits")
    if status in ("active", "done") and stage in ("final-verify", "handoff") and not reviews_current(data):
        if stage == "handoff" and data.get("final_fingerprint") and run_fingerprint(data) != data["final_fingerprint"]:
            raise InvalidSpec("Project changed after final verification; rerun final checks in a new run before marking complete")
        raise InvalidSpec("Fresh passing source-current quality and polish reviews are required before final verification or handoff; use recheck after later edits")
    if status == "skipped" and stage != "research":
        raise InvalidSpec("Only research may be skipped; other stages are required")
    if status == "active":
        if stage == "final-verify" and data.get("plan", {}).get("security_profile") == "full" and not security_review_ready(data):
            raise InvalidSpec("Final verification needs a passing, source-current Securer audit after both reviews")
        if item["status"] not in ("pending", "blocked", "active"):
            raise InvalidSpec("Cannot reactivate a completed stage")
        if any(data["stages"][p]["status"] not in ("done", "skipped") for p in STAGES[:i]):
            raise InvalidSpec("Earlier stages must be done before starting this stage")
    elif status in ("done", "skipped"):
        if item["status"] != "active":
            raise InvalidSpec("Stage must be active before completion or skip")
        if status == "done" and stage == "plan":
            if not data.get("plan"):
                raise InvalidSpec("Record a concrete acceptance plan before marking plan done")
            if data["plan"].get("contract_profile") in ("external-cli", "external-api") and not data.get("behavior_contract"):
                raise InvalidSpec("External behavior contract must be frozen before plan completion")
        if status == "done" and stage == "implement" and data.get("plan", {}).get("autonomy_profile") == "rigorous":
            if not implementation_research_ready(data):
                raise InvalidSpec("Rigorous implementation needs online source evidence for every research topic and a cited application note; block rather than fabricate unavailable research")
            if not any(t.get("stage") == "implement" and t.get("exit_code") == 0 and t.get("snapshot_stable") for t in data["tests"]):
                raise InvalidSpec("Rigorous implementation requires at least one passing in-development probe")
        if status == "done" and stage in ("verify", "final-verify"):
            current_snapshot = run_fingerprint(data)  # surface unsafe-file diagnostics, don't hide them as stale tests
            if not verification_ready(data, stage):
                raise InvalidSpec(f"{stage} requires passing checks on the current unchanged source snapshot and a fresh structural gate for new projects")
            item["verified_fingerprint"] = current_snapshot
        if status == "done" and stage in REVIEW_CHECKS:
            review = data.get("reviews", {}).get(stage, {})
            if review.get("verdict") != "pass":
                raise InvalidSpec(f"{stage} requires its own passing review record")
            if review.get("source_fingerprint") != run_fingerprint(data):
                raise InvalidSpec(f"{stage} review is stale: project changed after its assessment; resubmit review")
        if status == "done" and stage == "final-verify" and data.get("plan", {}).get("security_profile") == "full" and not security_review_ready(data):
            raise InvalidSpec("Securer approval is stale or missing; repeat review and scan after edits")
        if status == "done" and stage == "final-verify":
            data["final_fingerprint"] = item["verified_fingerprint"]
        if status == "done" and stage == "handoff" and run_fingerprint(data) != data.get("final_fingerprint"):
            raise InvalidSpec("Project changed after final verification; rerun final checks in a new run before marking complete")
        if status == "done" and stage == "handoff" and data["stages"]["final-verify"]["status"] != "done":
            raise InvalidSpec("Cannot claim handoff complete without final verification")
    elif status == "blocked" and item["status"] != "active":
        raise InvalidSpec("Only the active stage can be marked blocked")
    item.update(status=status, note=note, at=now())
    data["events"].append({"at": now(), "stage": stage, "status": status, "note": note})
    save(path, data)
    return data


def latest_tests(data, stage="verify"):
    by_label = {}
    for test in data["tests"]:
        if test.get("stage", "verify") == stage:
            by_label[test["label"]] = test
    return list(by_label.values())


def verification_ready(data, stage="verify"):
    """A phase is only ready for a *single* consistent tested source snapshot.

    The historical first verification is sealed at completion; the final phase
    must also match today's files. This permits legitimate reviewer fixes after
    first verification without losing its historical evidence.
    """
    if stage not in ("verify", "final-verify"):
        return False
    if stage == "final-verify" and (not usability_ready(data) or not reviews_current(data)):
        return False
    item = data["stages"][stage]
    if item["status"] == "done" and item.get("verified_fingerprint"):
        if stage == "verify":
            return True
        try:
            return run_fingerprint(data) == item["verified_fingerprint"]
        except (InvalidSpec, OSError):
            return False
    checks = latest_tests(data, stage)
    if not checks or any(t["exit_code"] != 0 or t.get("timeout") or not t.get("snapshot_stable") for t in checks):
        return False
    plan = data.get("plan")
    if not plan:
        return False
    required = {t["test_label"] for t in plan["tasks"]} | {plan["smoke_label"]} | {t["test_label"] for t in plan.get("experience_checks", [])}
    by_label = {t["label"]: t for t in checks}
    if plan.get("contract_profile") in ("external-cli", "external-api"):
        required.add("external-contract")
        contract = data.get("behavior_contract")
        external = by_label.get("external-contract")
        if not contract or not external or external.get("contract_sha256") != contract["sha256"] or not external.get("contract_steps", 0):
            return False
    if not required.issubset(by_label):
        return False
    try:
        current = run_fingerprint(data)
    except (InvalidSpec, OSError):
        return False
    if any(by_label[label].get("source_fingerprint") != current for label in required):
        return False
    if data["operation"] == "new":
        phase_checks = [c for c in data["structural_checks"] if c.get("stage", "verify") == stage]
        return bool(phase_checks) and phase_checks[-1]["passed"] and phase_checks[-1].get("source_fingerprint") == current
    return True


def validate_rigorous_command(argv, label, project, plan, cwd=None):
    """Conservative anti-placebo guard; it cannot prove semantic test quality."""
    joined = " ".join(argv).lower()
    if any(x in joined for x in (" -c ", " -e ", "print(", "console.log(", " /bin/true")) or any(x in argv for x in ("-c", "-e", "--eval")):
        raise InvalidSpec("Rigorous acceptance commands cannot use inline execution or success-only expressions")
    base = Path(argv[0]).name.lower()
    args = argv[1:]
    if base.startswith("python"):
        # Interpreter switches precede -m or the script. These switches keep
        # assertions enabled; in particular, never strip -O / -OO.
        while args and re.fullmatch(r"-[BEIusSq]+", args[0]):
            args = args[1:]
    acceptable = (base.startswith("python") and len(args) >= 2 and args[:2] == ["-m", "unittest"]
                  or base.startswith("python") and len(args) >= 2 and args[:2] == ["-m", "pytest"]
                  or base in ("pytest", "go", "cargo", "npm", "pnpm", "yarn", "node", "npx"))
    if not acceptable and not (base.startswith("python") and args and args[0].endswith(".py")):
        raise InvalidSpec("Rigorous acceptance requires a recognized test runner or a concrete local test script")
    # Check locally executed Python scripts for executable checking constructs.
    if base.startswith("python"):
        if args and args[0].endswith(".py"):
            # Python resolves its script against the execution directory. Inspect
            # that same file, even when a different root script shares its name.
            candidates = [str((Path(cwd) if cwd is not None else project) / args[0])]
        elif len(args) >= 2 and args[:2] == ["-m", "unittest"]:
            pattern = args[args.index("-p")+1] if "-p" in args and args.index("-p")+1 < len(args) else "test*.py"
            candidates = [str(p.relative_to(project)) for p in walk_regular(project, IGNORED) if fnmatch.fnmatch(p.name, pattern)]
        elif len(args) >= 2 and args[:2] == ["-m", "pytest"]:
            candidates = [str(p.relative_to(project)) for p in walk_regular(project, IGNORED) if fnmatch.fnmatch(p.name, 'test*.py')]
        else:
            candidates = []
        if not candidates:
            raise InvalidSpec("Rigorous Python acceptance has no inspectable test code")
        credible = False
        for rel in candidates:
            raw = project / rel
            if is_link(raw):
                raise InvalidSpec("Unsafe test script reference")
            file = raw.resolve(strict=True)
            if not file.is_relative_to(project) or not file.is_file():
                raise InvalidSpec("Unsafe test script reference")
            body = regular_text(raw, 256_000, root=project)
            try:
                tree = ast.parse(body, filename=str(file))
            except SyntaxError as exc:
                raise InvalidSpec(f"Test script has invalid Python syntax: {rel}: {exc.msg}") from exc
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert) and not (isinstance(node.test, ast.Constant) and node.test.value is True):
                    credible = True
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                    if name.startswith("assert") or name in ("raises", "exit") or (name == "run" and any(k.arg == "check" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)):
                        if not (len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and node.args[0].value is True):
                            credible = True
        if not credible:
            raise InvalidSpec("Rigorous Python tests need observable assertions or explicit failure checks; a print-only smoke script is not evidence")


def validate_research(doc):
    if not isinstance(doc, dict) or doc.get("phase") not in ("idea", "implementation"):
        raise InvalidSpec("research evidence needs phase idea or implementation")
    phase = doc["phase"]
    topic = ensure_string(doc.get("topic"), "research.topic", 90)
    finding = ensure_string(doc.get("finding"), "research.finding", 360)
    application = ensure_string(doc.get("application"), "research.application", 260)
    if doc.get("kind") not in ("web", "connector", "local"):
        raise InvalidSpec("research.kind must be web, connector or local")
    url = doc.get("url", "")
    if doc["kind"] == "web":
        if not isinstance(url, str) or len(url) > 500 or any(c.isspace() or ord(c) < 32 for c in url):
            raise InvalidSpec("web research requires a credential-free HTTPS source URL")
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme == 'https' and parsed.hostname and parsed.username is None and parsed.password is None
            parsed.port  # validate the port syntax without accessing the URL
        except ValueError:
            valid = False
        if not valid:
            raise InvalidSpec("web research requires a credential-free HTTPS source URL")
    elif url and (not isinstance(url, str) or len(url) > 500):
        raise InvalidSpec("Invalid research locator")
    at = doc.get("accessed_at")
    try:
        stamp = datetime.fromisoformat(at)
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc) or stamp.year < 2020:
            raise ValueError()
    except (ValueError, TypeError):
        raise InvalidSpec("research.accessed_at must be a plausible timezone-aware ISO timestamp")
    return {"phase": phase, "topic": topic, "finding": finding, "application": application,
            "kind": doc["kind"], "url": url, "accessed_at": at, "source_date": ensure_string(doc.get("source_date", "undated"), "research.source_date", 80),
            "verification": "agent-supplied source record, not independently fetched by tracker"}


def implementation_research_ready(data):
    topics = data.get("plan", {}).get("research_topics", [])
    rows = data.get("research_evidence", [])
    return bool(topics) and all(any(x.get("phase") == "implementation" and x.get("kind") == "web" and x.get("topic") == topic for x in rows) for topic in topics)


def set_research(directory, source):
    path, data = load(directory)
    try:
        doc = read_json(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Cannot read research evidence: {exc}") from exc
    row = validate_research(doc)
    active = data["stages"]["research" if row["phase"] == "idea" else "implement"]["status"]
    if active != "active":
        raise InvalidSpec("Research evidence requires the corresponding active phase")
    if row["phase"] == "implementation" and row["topic"] not in data.get("plan", {}).get("research_topics", []):
        raise InvalidSpec("Implementation research topic must match the acceptance plan")
    data.setdefault("research_evidence", []).append(row)
    data["events"].append({"at": now(), "stage": "research" if row["phase"] == "idea" else "implement", "status": "sourced", "note": f"Recorded {row['kind']} source on {row['topic']}"})
    save(path, data)
    return row


def set_behavior_contract(directory, source):
    """Freeze an outside-the-project observable behavior contract during planning."""
    path, data = load(directory)
    if data["stages"]["plan"]["status"] != "active" or not data.get("plan") or data["plan"].get("contract_profile") not in ("external-cli", "external-api"):
        raise InvalidSpec("Record an enhanced external behavior plan before its contract")
    kind = data["plan"]["contract_profile"]
    try:
        raw = read_json(source)
        manifest = validate_api_contract(raw) if kind == "external-api" else validate_behavior_contract(raw)
    except (ContractError, APIContractError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Invalid behavior contract: {exc}") from exc
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    data["behavior_contract"] = {"manifest": manifest, "sha256": digest, "kind": kind}
    data["events"].append({"at": now(), "stage": "plan", "status": "contract-bound", "note": f"Frozen {kind} behavior contract ({len(manifest['scenarios'])} scenarios)"})
    save(path, data)
    return {"name": manifest["name"], "sha256": digest, "scenarios": len(manifest["scenarios"])}


def run_behavior_contract(directory):
    """Execute frozen assertions on a disposable data location, both verification phases."""
    path, data = load(directory)
    stage = next((s for s in ("verify", "final-verify") if data["stages"][s]["status"] == "active"), None)
    if not stage or not data.get("behavior_contract") or data.get("plan", {}).get("contract_profile") not in ("external-cli", "external-api"):
        raise InvalidSpec("Start a verification phase with a frozen external behavior contract")
    before = run_fingerprint(data)
    started = time.monotonic()
    kind = data["plan"]["contract_profile"]
    outcome = (execute_api_contract if kind == "external-api" else execute_behavior_contract)(data["project"], data["behavior_contract"]["manifest"])
    after = run_fingerprint(data)
    evidence = {"at": now(), "stage": stage, "cwd": "loopback service with temporary data" if kind == "external-api" else "temporary per-scenario data directory", "label": "external-contract",
                "executable": kind, "argv_sha256_prefix": data["behavior_contract"]["sha256"][:12],
                "contract_sha256": data["behavior_contract"]["sha256"], "contract_steps": outcome["steps_total"],
                "exit_code": 0 if outcome["passed"] else 1, "timeout": False, "empty_collection": False,
                "elapsed_seconds": round(time.monotonic() - started, 2), "output_bytes": 0,
                "source_fingerprint": before, "snapshot_stable": before == after}
    data["tests"].append(evidence)
    data["events"].append({"at": now(), "stage": stage, "status": "contract-checked", "note": f"{kind} behavior {outcome['steps_passed']}/{outcome['steps_total']} steps; unchanged source={before == after}"})
    save(path, data)
    return {"outcome": outcome, "source_unchanged": before == after, "contract_sha256": evidence["contract_sha256"]}


def actual_test(directory, argv, timeout=120, cwd=None, label="test"):
    path, data = load(directory)
    active_stage = next((x for x in ("implement", "verify", "final-verify") if data["stages"][x]["status"] == "active"), None)
    if not active_stage:
        raise InvalidSpec("Start implement, verify or final-verify before running tests")
    if not argv or argv == ["--"]:
        raise InvalidSpec("Provide a command after --")
    if argv[0] == "--":
        argv = argv[1:]
    if not argv or any(not isinstance(a, str) or len(a) > 2000 or "\x00" in a for a in argv):
        raise InvalidSpec("Invalid test argv")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", label) or label == "external-contract":
        raise InvalidSpec("test label must be lowercase alphanumeric and cannot use a reserved label")
    if not 1 <= timeout <= 600:
        raise InvalidSpec("timeout must be 1..600 seconds")
    project = Path(data["project"])
    try:
        place = checked_path(Path(cwd).expanduser().absolute(), project) if cwd else project
    except (OSError, ValueError) as exc:
        raise InvalidSpec("test cwd must be an unlinked directory inside the project") from exc
    if not place.is_dir() or not place.is_relative_to(project):
        raise InvalidSpec("test cwd must be within selected project")
    # A label is evidence only for the command specified in the acceptance plan,
    # when one was bound. Prevent a harmless `true` command impersonating a test.
    expected = {t["test_label"]: t.get("test_command") for t in data["plan"]["tasks"]}
    expected[data["plan"]["smoke_label"]] = data["plan"].get("smoke_command")
    expected.update({t["test_label"]: t["test_command"] for t in data["plan"].get("experience_checks", [])})
    if active_stage != "implement" and label in expected and expected[label] is not None and argv != expected[label]:
        raise InvalidSpec(f"Test label {label!r} requires the bound acceptance command")
    if active_stage != "implement" and data["plan"].get("quality_profile") == "enhanced" and label in expected:
        validate_rigorous_command(argv, label, project, data["plan"], cwd=place)
    before = run_fingerprint(data, require_delivery=active_stage != "implement")
    start = time.monotonic()
    output_limited, cleanup_complete = False, False
    try:
        result = run_command(argv, place, timeout=timeout)
        code, timed_out = result.returncode, result.timed_out
        output_limited, cleanup_complete = result.output_limited, result.cleanup_complete
        bytecount = result.output_bytes
        streams = [stream.decode('utf-8', errors='replace') for stream in (result.stdout, result.stderr)]
    except (OSError, ProcessSafetyError) as exc:
        code, timed_out, bytecount = 127, False, 0
        streams = ["", f"Unable to execute: {type(exc).__name__}: {exc}\n"]
    # The entire bounded capture is checked, independently per stream. Large
    # output is a failed execution, never a successful truncated contract.
    pattern = r"\bRan\s+0\s+tests?\b|\bno tests ran\b|\bcollected 0 items\b"
    empty_collection = any(re.search(pattern, stream, re.IGNORECASE) for stream in streams)
    skipped_pattern = r"\bOK\s*\([^\r\n)]*\bskipped=[1-9]\d*\b|\b[1-9]\d*\s+skipped\b"
    skipped_tests = any(re.search(skipped_pattern, stream, re.IGNORECASE) for stream in streams)
    excerpt = (streams[0][-3000:] + streams[1][-3000:])
    # Zero collection and skipped checks can exit 0 without executing acceptance.
    if (empty_collection or skipped_tests) and code == 0:
        code = 86
    after = run_fingerprint(data, require_delivery=active_stage != "implement")
    stable = before == after
    fingerprint = hashlib.sha256(json.dumps(argv, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    evidence = {"at": now(), "stage": active_stage, "cwd": str(place), "label": label, "executable": Path(argv[0]).name,
                "argv_sha256_prefix": fingerprint, "exit_code": code,
                "timeout": timed_out, "empty_collection": empty_collection, "skipped_tests": skipped_tests, "elapsed_seconds": round(time.monotonic() - start, 2),
                "output_limited": output_limited, "cleanup_complete": cleanup_complete,
                "output_bytes": bytecount, "source_fingerprint": before,
                "snapshot_stable": stable}
    # Never persist test stdout/stderr: it may contain secrets. Only display bounded tail.
    data["tests"].append(evidence)
    data["events"].append({"at": now(), "stage": active_stage, "status": "tested",
                           "note": f"Executed test {label} (exit {code}, {evidence['elapsed_seconds']}s; stable={stable})"})
    save(path, data)
    return evidence, excerpt


def structural(directory):
    path, data = load(directory)
    if data["operation"] != "new":
        raise InvalidSpec("Structural scaffold gate applies only to new projects")
    active_stage = next((x for x in ("verify", "final-verify") if data["stages"][x]["status"] == "active"), None)
    if not active_stage:
        raise InvalidSpec("Start verify or final-verify before structural checking")
    results = check_build(data["project"])
    data["structural_checks"].append({"stage": active_stage, "at": now(), "passed": results["passes_structural_gate"], "checks": results["checks"],
                                      "source_fingerprint": run_fingerprint(data)})
    data["events"].append({"at": now(), "stage": active_stage, "status": "checked", "note": "Structural gate: " + ("pass" if results["passes_structural_gate"] else "fail")})
    save(path, data)
    return results



def plan_validate(doc):
    if not isinstance(doc, dict):
        raise InvalidSpec("plan must be an object")
    user_journey = ensure_string(doc.get("user_journey"), "plan.user_journey", 350)
    smoke = ensure_string(doc.get("smoke_test"), "plan.smoke_test", 250)
    smoke_label = doc.get("smoke_label", "smoke")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", str(smoke_label)) or smoke_label == "external-contract":
        raise InvalidSpec("plan.smoke_label is invalid")
    def command(value, name):
        if value is None:
            return None
        if not isinstance(value, list) or not 1 <= len(value) <= 30 or any(not isinstance(x, str) or not x or len(x) > 2000 or "\x00" in x for x in value):
            raise InvalidSpec(f"{name} must be a nonempty argv array of strings")
        if value[0] in ("true", "/bin/true", "echo", "/bin/echo"):
            raise InvalidSpec(f"{name} cannot use a trivial success command")
        return value
    smoke_command = command(doc.get("smoke_command"), "plan.smoke_command")
    contract_profile = doc.get("contract_profile", "standard")
    if contract_profile not in ("standard", "external-cli", "external-api"):
        raise InvalidSpec("contract_profile must be standard, external-cli or external-api")
    profile = doc.get("quality_profile", "legacy")
    if profile not in ("legacy", "enhanced"):
        raise InvalidSpec("plan.quality_profile must be legacy or enhanced")
    if "usability_profile" in doc and (doc["usability_profile"] != "novice-v1" or profile != "enhanced"):
        raise InvalidSpec("usability_profile must be novice-v1 and requires enhanced quality")
    security_profile = doc.get("security_profile", "standard")
    if security_profile not in ("standard", "full") or (security_profile == "full" and profile != "enhanced"):
        raise InvalidSpec("security_profile full requires an enhanced quality plan")
    autonomy = doc.get("autonomy_profile", "standard")
    if autonomy not in ("standard", "rigorous") or (autonomy == "rigorous" and profile != "enhanced"):
        raise InvalidSpec("rigorous autonomy requires an enhanced plan")
    research_topics = doc.get("research_topics", [])
    if autonomy == "rigorous":
        if not isinstance(research_topics, list) or not 2 <= len(research_topics) <= 4 or any(not isinstance(x, str) for x in research_topics) or len(set(research_topics)) != len(research_topics):
            raise InvalidSpec("rigorous plans need 2..4 distinct implementation research topics")
        research_topics = [ensure_string(x, "research topic", 90) for x in research_topics]
    else:
        research_topics = []
    surface = doc.get("surface", "cli")
    if contract_profile == "external-cli" and (surface != "cli" or profile != "enhanced"):
        raise InvalidSpec("External CLI contracts require a CLI surface and enhanced quality plan")
    if contract_profile == "external-api" and (surface != "api" or profile != "enhanced" or security_profile != "full"):
        raise InvalidSpec("External API contracts require an API surface, enhanced quality and full security profile")
    if not isinstance(surface, str) or surface not in SURFACES:
        raise InvalidSpec("plan.surface is invalid")
    if surface == "api" and security_profile == "full" and contract_profile != "external-api":
        raise InvalidSpec("New full-security API plans require a frozen external-api behavior contract")
    polish_targets = doc.get("polish_targets", [])
    if (not isinstance(polish_targets, list) or len(polish_targets) > 8
            or len(polish_targets) != len(set(map(str, polish_targets)))
            or any(not isinstance(x, str) or x not in POLISH_TARGETS for x in polish_targets)):
        raise InvalidSpec("plan.polish_targets must be unique supported targets")
    if profile == "enhanced":
        required = ({"first-run", "error-state", "help-output"} if surface == "cli"
                    else {"first-run", "error-state", "empty-state", "visual-hierarchy", "keyboard", "responsive"} if surface in ("web", "desktop")
                    else {"first-run", "error-state", "microcopy"})
        if not required.issubset(polish_targets):
            raise InvalidSpec("enhanced plan is missing surface-specific polish targets: " + ", ".join(sorted(required - set(polish_targets))))
    tasks = doc.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 6:
        raise InvalidSpec("plan.tasks requires 1..6 verifiable vertical-slice tasks")
    ids = set()
    labels = {smoke_label, "external-contract"}
    clean = []
    for t in tasks:
        if not isinstance(t, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", str(t.get("id", ""))):
            raise InvalidSpec("Invalid plan task id")
        if t["id"] in ids:
            raise InvalidSpec("Duplicate plan task id")
        ids.add(t["id"])
        change = ensure_string(t.get("change"), "plan.task.change", 180)
        acceptance = ensure_string(t.get("acceptance"), "plan.task.acceptance", 300)
        label = t.get("test_label")
        if not isinstance(label, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", label) or label in labels:
            raise InvalidSpec("Task test labels must be valid and unique, separate from smoke")
        labels.add(label)
        focus = t.get("focus", "other")
        if not isinstance(focus, str) or focus not in TEST_FOCUS:
            raise InvalidSpec("plan.task.focus is invalid")
        test_cmd = command(t.get("test_command"), f"plan.tasks[{t['id']}].test_command")
        if profile == "enhanced" and test_cmd is None:
            raise InvalidSpec("enhanced acceptance tasks require bound test commands")
        if profile == "enhanced" and any(x in test_cmd for x in ("-c", "-e", "--eval")):
            raise InvalidSpec("rigorous plans reject inline execution for acceptance checks")
        clean.append({"id": t["id"], "change": change, "acceptance": acceptance, "test_label": label,
                      "focus": focus, "test_command": test_cmd})
    if profile == "enhanced":
        if len(tasks) < 2 or not {"journey", "edge"}.issubset({t["focus"] for t in clean}):
            raise InvalidSpec("enhanced plan needs distinct journey and edge/error acceptance tests")
        if smoke_command is None:
            raise InvalidSpec("enhanced plan requires a bound black-box smoke command")
        if profile == "enhanced" and any(x in smoke_command for x in ("-c", "-e", "--eval")):
            raise InvalidSpec("rigorous plans reject inline execution for smoke checks")
    experience_profile = doc.get("experience_profile", "standard")
    if experience_profile not in ("standard", "v08") or (experience_profile == "v08" and profile != "enhanced"):
        raise InvalidSpec("v08 experience profile requires enhanced quality")
    extra = doc.get("experience_checks", [])
    if not isinstance(extra, list) or len(extra) > 4 or (experience_profile == "v08" and len(extra) < 2):
        raise InvalidSpec("v08 experience profile requires 2..4 separate user-facing checks")
    scenarios, checks = set(), []
    for item in extra:
        if not isinstance(item, dict) or item.get("scenario") not in EXPERIENCE_SCENARIOS or item["scenario"] in scenarios:
            raise InvalidSpec("experience scenarios must be supported and distinct")
        scenarios.add(item["scenario"])
        label = item.get("test_label")
        if not isinstance(label, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", label) or label in labels:
            raise InvalidSpec("experience test labels must be unique and distinct from other test labels")
        labels.add(label)
        test_cmd = command(item.get("test_command"), "experience_checks.test_command")
        if profile == "enhanced" and (test_cmd is None or any(x in test_cmd for x in ("-c", "-e", "--eval"))):
            raise InvalidSpec("enhanced experience checks require executable bound non-inline commands")
        checks.append({"scenario": item["scenario"], "expected": ensure_string(item.get("expected"), "experience check expected", 260),
                       "test_label": label, "test_command": test_cmd})
    if experience_profile == "v08" and ("first-run" not in scenarios or len(scenarios) < 2):
        raise InvalidSpec("v08 needs first-run plus a different meaningful user-facing scenario")
    excluded = doc.get("out_of_scope", [])
    if not isinstance(excluded, list) or len(excluded) > 10:
        raise InvalidSpec("plan.out_of_scope must be a list of at most ten entries")
    result = {"user_journey": user_journey, "security_profile": security_profile, "contract_profile": contract_profile, "experience_profile": experience_profile, "experience_checks": checks, "quality_profile": profile, "autonomy_profile": autonomy, "research_topics": research_topics, "surface": surface, "polish_targets": polish_targets, "tasks": clean, "smoke_test": smoke,
            "smoke_label": smoke_label, "smoke_command": smoke_command, "out_of_scope": [ensure_string(x, "out_of_scope", 180) for x in excluded]}
    if "delivery_artifacts" in doc:
        result["delivery_artifacts"] = validate_delivery_artifacts(doc["delivery_artifacts"])
    if "usability_profile" in doc:
        result["usability_profile"] = doc["usability_profile"]
    return result


def set_plan(directory, source):
    path, data = load(directory)
    if data["stages"]["plan"]["status"] != "active":
        raise InvalidSpec("Start plan stage before recording the acceptance plan")
    try:
        doc = read_json(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Cannot load plan: {exc}") from exc
    plan = plan_validate(doc)
    # Planned outputs may not exist yet, but existing declarations must already
    # be bounded regular files reached without any linked path component.
    delivery_entries(data["project"], plan.get("delivery_artifacts", []), require=False)
    if data["operation"] == "new" and plan["quality_profile"] == "enhanced":
        if plan.get("usability_profile") != "novice-v1":
            raise InvalidSpec("New enhanced plans require usability_profile novice-v1")
        if plan["security_profile"] != "full" or plan["experience_profile"] != "v08":
            raise InvalidSpec("New enhanced plans require full security and v08 experience checks")
        expected_contract = {"cli": "external-cli", "api": "external-api"}.get(plan["surface"])
        if expected_contract and plan["contract_profile"] != expected_contract:
            raise InvalidSpec(f"New enhanced {plan['surface']} plans require {expected_contract}")
    data["plan"] = plan
    data.pop("usability", None)
    data["behavior_contract"] = None  # A revised plan requires its own fresh external contract.
    data["security_scan"] = None
    data["security_history"] = []
    data.get("reviews", {}).pop("security", None)
    data["events"].append({"at": now(), "stage": "plan", "status": "planned", "note": "Recorded verifiable vertical-slice acceptance plan"})
    save(path, data)
    return data["plan"]

def topology_validate(doc):
    if not isinstance(doc, dict) or doc.get("status") not in ("planned", "observed"):
        raise InvalidSpec("architecture.status must be planned or observed")
    nodes, edges = doc.get("nodes"), doc.get("edges")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 16 or not isinstance(edges, list) or not 1 <= len(edges) <= 32:
        raise InvalidSpec("Architecture requires 2..16 nodes and 1..32 edges")
    ids = set()
    for node in nodes:
        if not isinstance(node, dict) or not NODE_ID.fullmatch(str(node.get("id", ""))):
            raise InvalidSpec("Unsafe architecture node ID")
        ensure_string(node.get("label"), "architecture.node.label", 80)
        if node["id"] in ids:
            raise InvalidSpec("Duplicate architecture node ID")
        ids.add(node["id"])
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("from") not in ids or edge.get("to") not in ids:
            raise InvalidSpec("Architecture edges must reference known nodes")
        ensure_string(edge.get("label", "depends on"), "architecture.edge.label", 60)
    return {"status": doc["status"], "nodes": [{"id": n["id"], "label": n["label"]} for n in nodes],
            "edges": [{"from": e["from"], "to": e["to"], "label": e.get("label", "depends on")} for e in edges]}


def set_architecture(directory, source):
    path, data = load(directory)
    try:
        doc = read_json(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Cannot load architecture: {exc}") from exc
    data["architecture"] = topology_validate(doc)
    data["events"].append({"at": now(), "stage": "plan", "status": "diagram", "note": "Architecture diagram recorded as " + doc["status"]})
    save(path, data)
    return data["architecture"]


def validate_delivery_artifacts(value):
    """An explicit file manifest, never a directory or glob expansion."""
    if not isinstance(value, list) or len(value) > MAX_DELIVERY_ARTIFACTS:
        raise InvalidSpec(f"plan.delivery_artifacts must list at most {MAX_DELIVERY_ARTIFACTS} relative file paths")
    clean, seen = [], set()
    for item in value:
        try:
            relative = safe_relative(item).as_posix()
        except ValueError as exc:
            raise InvalidSpec(f"Invalid plan.delivery_artifacts path: {exc}") from exc
        if relative.casefold() in seen:
            raise InvalidSpec("plan.delivery_artifacts paths must be unique, including case aliases")
        seen.add(relative.casefold())
        clean.append(relative)
    return sorted(clean)


def delivery_entries(project, artifacts, *, require=True):
    """Read only declared files, with independent per-file and aggregate limits.

    Missing outputs have a distinct marker during implementation. Acceptance and
    reviews require every output; the marker can never become passing evidence.
    These checks do not isolate the process from a concurrent hostile writer.
    """
    artifacts = validate_delivery_artifacts(artifacts)
    entries, total_bytes = [], 0
    for rel in artifacts:
        try:
            path = checked_path(rel, project, must_exist=False)
            try:
                content = regular_bytes(path, MAX_DELIVERY_FILE_BYTES, root=project)
            except FileNotFoundError:
                if require:
                    raise InvalidSpec(f"Declared delivery artifact is missing: {rel}")
                entries.append((rel, None))
                continue
            total_bytes += len(content)
            if total_bytes > MAX_DELIVERY_TOTAL_BYTES:
                raise InvalidSpec("Delivery artifacts exceed the 20 MB snapshot budget")
            entries.append((rel, hashlib.sha256(content).hexdigest()))
        except (OSError, ValueError) as exc:
            raise InvalidSpec(f"Cannot safely snapshot delivery artifact {rel}: {exc}") from exc
    return entries


def run_fingerprint(data, *, require_delivery=True):
    return project_fingerprint(data["project"], (data.get("plan") or {}).get("delivery_artifacts", []),
                               require_delivery=require_delivery)


def project_fingerprint(project, delivery_artifacts=None, *, require_delivery=True):
    """Bounded source digest plus explicitly declared files in ignored folders."""
    if is_link(project):
        raise InvalidSpec("Cannot snapshot a linked project root")
    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise InvalidSpec("Snapshot root must be a directory")
    entries = []
    total_bytes = 0
    try:
        for path in walk_regular(root, IGNORED | {'.DS_Store'}):
            rel = path.relative_to(root).as_posix()
            content = regular_bytes(path, 2_000_000, root=root)
            total_bytes += len(content)
            if total_bytes > 20_000_000:
                raise InvalidSpec("Project exceeds 20 MB snapshot budget; narrow scope explicitly")
            entries.append((rel, hashlib.sha256(content).hexdigest()))
    except (OSError, ValueError) as exc:
        raise InvalidSpec(f"Cannot safely snapshot project: {exc}") from exc
    delivered = delivery_entries(root, delivery_artifacts if delivery_artifacts is not None else [], require=require_delivery)
    # Preserve historical fingerprints when no explicit files are declared.
    payload = {"source": entries, "delivery_artifacts": delivered} if delivered else entries
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def validate_review(role, doc, plan=None):
    if role not in REVIEW_CHECKS or not isinstance(doc, dict):
        raise InvalidSpec("Invalid review role or document")
    mode = doc.get("reviewer_mode")
    if mode not in ("subagent", "single-agent-fallback"):
        raise InvalidSpec("reviewer_mode must honestly indicate subagent or single-agent-fallback")
    verdict = doc.get("verdict")
    if verdict not in ("pass", "needs-work"):
        raise InvalidSpec("Review verdict must be pass or needs-work")
    summary = ensure_string(doc.get("summary"), "review.summary", 400)
    checks = doc.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(REVIEW_CHECKS[role]):
        raise InvalidSpec("Review must provide exactly the required checklist")
    if any(v not in ("pass", "needs-work", "not-applicable") for v in checks.values()):
        raise InvalidSpec("Invalid review check status")
    findings = doc.get("findings")
    if not isinstance(findings, list) or len(findings) > 12:
        raise InvalidSpec("Review findings must be a list of at most 12")
    result = []
    for f in findings:
        if not isinstance(f, dict) or f.get("severity") not in ("critical", "major", "minor") or f.get("resolution") not in ("fixed", "accepted", "open"):
            raise InvalidSpec("Invalid finding severity/resolution")
        result.append({"severity": f["severity"], "issue": ensure_string(f.get("issue"), "review.issue", 220),
                       "resolution": f["resolution"], "evidence": ensure_string(f.get("evidence"), "review.evidence", 220)})
    changes = doc.get("changes")
    if not isinstance(changes, list) or len(changes) > 12:
        raise InvalidSpec("Review changes must be a list of at most 12")
    changes = [ensure_string(x, "review.change", 180) for x in changes]
    targets = {}
    if role == "polish" and plan and plan.get("quality_profile") == "enhanced":
        supplied = doc.get("target_evidence")
        if not isinstance(supplied, dict) or set(supplied) != set(plan["polish_targets"]):
            raise InvalidSpec("Enhanced polish review must cover every planned polish target")
        for name, entry in supplied.items():
            if not isinstance(entry, dict) or entry.get("status") not in ("pass", "needs-work", "not-applicable"):
                raise InvalidSpec("Invalid polish target evidence status")
            if entry["status"] == "not-applicable" and name in ("first-run", "error-state", "keyboard", "responsive", "help-output"):
                raise InvalidSpec("Required enhanced polish targets cannot be not-applicable")
            targets[name] = {"status": entry["status"], "evidence": ensure_string(entry.get("evidence"), "polish target evidence", 240)}
    if verdict == "pass" and (sum(x == "pass" for x in checks.values()) < 3 or
                              (plan and plan.get("quality_profile") == "enhanced" and role == "quality" and any(x != "pass" for x in checks.values())) or
                              "needs-work" in checks.values() or any(x["resolution"] == "open" and x["severity"] != "minor" for x in result)
                              or any(v["status"] == "needs-work" for v in targets.values())):
        raise InvalidSpec("Cannot pass a review with unresolved major/critical findings or failing checks")
    return {"reviewer_mode": mode, "verdict": verdict, "summary": summary, "checks": checks, "findings": result, "changes": changes, "target_evidence": targets}


def set_review(directory, role, source):
    path, data = load(directory)
    if role not in REVIEW_CHECKS or data["stages"][role]["status"] != "active":
        raise InvalidSpec("Start the matching review stage before submitting its record")
    try:
        doc = read_json(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Cannot load review: {exc}") from exc
    review = validate_review(role, doc, data.get("plan"))
    review["source_fingerprint"] = run_fingerprint(data)
    data.setdefault("reviews", {})[role] = review
    data["events"].append({"at": now(), "stage": role, "status": "reviewed", "note": f"Review verdict: {review['verdict']}; {len(review['findings'])} findings"})
    save(path, data)
    return review


def reviews_current(data):
    """Every profile requires both passing reviews on the current deliverable."""
    reviews = data.get("reviews", {})
    if any(reviews.get(role, {}).get("verdict") != "pass" for role in REVIEW_CHECKS):
        return False
    try:
        current = run_fingerprint(data)
    except (InvalidSpec, OSError):
        return False
    return all(reviews[role].get("source_fingerprint") == current for role in REVIEW_CHECKS)


def usability_scope(data):
    """Bind to the frozen plan and external contract, never relax them for UX."""
    return usability_digest({"plan": data.get("plan"),
                             "contract_sha256": (data.get("behavior_contract") or {}).get("sha256")})


def current_usability_round(data):
    state = data.get("usability")
    if not isinstance(state, dict) or not isinstance(state.get("rounds"), list):
        return None
    active = state.get("active")
    if type(active) is not int or not 0 <= active < len(state["rounds"]) <= MAX_USABILITY_ROUNDS:
        return None
    pair = state["rounds"][active]
    return pair if isinstance(pair, dict) else None


def usability_ready(data):
    if (data.get("plan") or {}).get("usability_profile") != "novice-v1":
        return True  # Historical schema-v2 plans remain readable without this gate.
    pair = current_usability_round(data)
    if not pair or not isinstance(pair.get("novice"), dict) or not isinstance(pair.get("advocate"), dict):
        return False
    novice, advocate = pair["novice"], pair["advocate"]
    try:
        current = run_fingerprint(data)
        scope = usability_scope(data)
        novice_hash = usability_digest({k: v for k, v in novice.items() if k != "sha256"})
        return (novice.get("verdict") == advocate.get("verdict") == "pass"
                and novice.get("sha256") == advocate.get("novice_sha256") == novice_hash
                and novice.get("source_fingerprint") == advocate.get("source_fingerprint") == current
                and novice.get("acceptance_sha256") == advocate.get("acceptance_sha256") == scope)
    except (InvalidSpec, OSError, TypeError, ValueError):
        return False


def usability_status(data):
    if (data.get("plan") or {}).get("usability_profile") != "novice-v1":
        return "legacy / not required"
    pair = current_usability_round(data)
    if not pair:
        return "novice simulation required"
    try:
        if (pair.get("novice", {}).get("source_fingerprint") != run_fingerprint(data)
                or pair.get("novice", {}).get("acceptance_sha256") != usability_scope(data)):
            return "novice observation stale; fresh novice retest and advocate required"
    except (InvalidSpec, OSError):
        return "source unavailable; fresh novice retest and advocate required"
    if not pair.get("advocate"):
        return "advocate required; novice observation recorded"
    return "passed / current" if usability_ready(data) else "needs work or stale; fresh novice retest and advocate required"


def set_usability(directory, role, source):
    path, data = load(directory)
    if role not in ("novice", "advocate") or data["stages"]["quality"]["status"] != "active":
        raise InvalidSpec("Novice and advocate records require the active quality stage; use recheck for later repairs")
    if (data.get("plan") or {}).get("usability_profile") != "novice-v1":
        raise InvalidSpec("Record usability_profile novice-v1 during planning before using this gate")
    try:
        doc = read_json(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Cannot load usability evidence: {exc}") from exc
    # Both snapshots are captured by the tracker, not accepted from JSON claims.
    current, scope = run_fingerprint(data), usability_scope(data)
    state = data.setdefault("usability", {"rounds": [], "active": None})
    if not isinstance(state, dict) or not isinstance(state.get("rounds"), list) or len(state["rounds"]) > MAX_USABILITY_ROUNDS:
        raise InvalidSpec("Invalid bounded usability history")
    if role == "novice":
        if any(not isinstance(pair, dict) or pair.get("advocate") is None for pair in state["rounds"]):
            raise InvalidSpec("The advocate must disposition the previous novice difficulties before a new novice retest")
        if len(state["rounds"]) >= MAX_USABILITY_ROUNDS:
            raise InvalidSpec("Three novice rounds exhausted; record an honest quality blocker instead of continuing the loop")
        result = validate_novice(doc)
        result.update(at=now(), source_fingerprint=current, acceptance_sha256=scope)
        result["sha256"] = usability_digest(result)
        state["rounds"].append({"novice": result, "advocate": None})
        state["active"] = len(state["rounds"]) - 1
        round_index = state["active"]
    else:
        pair = current_usability_round(data)
        round_index = state.get("active")
        # Recheck deliberately clears current approval. It must still permit an
        # advocate to hear the latest retained observation before a fresh round.
        if pair is None and state.get("active") is None and state["rounds"]:
            latest = state["rounds"][-1]
            if isinstance(latest, dict) and latest.get("advocate") is None:
                pair, round_index = latest, len(state["rounds"]) - 1
        if not pair or not isinstance(pair.get("novice"), dict):
            raise InvalidSpec("Record a novice observation before the advocate")
        if pair.get("advocate") is not None:
            raise InvalidSpec("This round already has an advocate; preserve it and record a fresh novice retest")
        novice = pair["novice"]
        captured = usability_digest({k: v for k, v in novice.items() if k != "sha256"})
        if novice.get("sha256") != captured or novice.get("acceptance_sha256") != scope:
            raise InvalidSpec("Captured novice evidence or frozen acceptance changed; record a fresh novice retest")
        result = validate_advocate(doc, novice, captured)
        # Remediation can be declared against an old observation, but it never
        # substitutes for the required novice retest on changed product bytes.
        result.update(at=now(), source_fingerprint=current, acceptance_sha256=scope)
        pair["advocate"] = result
    data["events"].append({"at": now(), "stage": "quality", "status": "usability",
                           "note": f"{role.title()} simulation record: {result['verdict']}; round {round_index + 1}/{MAX_USABILITY_ROUNDS}"})
    save(path, data)
    return result


def security_scan(directory):
    """Passive local audit, never a pen test or a network scan."""
    path, data = load(directory)
    if data.get("plan", {}).get("security_profile") != "full" or data["stages"]["polish"]["status"] != "done" or data["stages"]["final-verify"]["status"] != "pending":
        raise InvalidSpec("Security scanning needs a full security plan, completed polish, and pending final verification")
    fingerprint = run_fingerprint(data)
    try:
        findings = scan_local_security(data["project"])
    except (ValueError, OSError) as exc:
        raise InvalidSpec(f"Security scan blocked: {exc}") from exc
    record = {**findings, "at": now(), "source_fingerprint": fingerprint}
    data["security_scan"] = record
    data.setdefault("security_history", []).append({"at": record["at"], "fingerprint": fingerprint,
        "finding_count": len(record["findings"]),
        "findings": [{k: f[k] for k in ("id", "code", "severity", "path", "line")} for f in record["findings"]]})
    if len(data["security_history"]) > 20:
        raise InvalidSpec("Security scan attempt limit reached; create a fresh continuation run")
    data.get("reviews", {}).pop("security", None)
    data["events"].append({"at": now(), "stage": "security", "status": "scanned", "note": f"Passive scan: {len(record['findings'])} findings (no active probing)"})
    save(path, data)
    return record


def validate_security_review(doc, scan_record, data):
    if not isinstance(doc, dict) or not scan_record:
        raise InvalidSpec("A security review requires a current local scan")
    checks = doc.get("checks")
    required = ("scope", "secrets", "input-validation", "abuse-controls", "dependencies")
    if not isinstance(checks, dict) or set(checks) != set(required) or any(x not in ("pass", "needs-work") for x in checks.values()):
        raise InvalidSpec("Securer must assess all five required controls")
    verdict = doc.get("verdict")
    if verdict not in ("pass", "needs-work"):
        raise InvalidSpec("Securer verdict must be pass or needs-work")
    mode = doc.get("reviewer_mode")
    if mode not in ("subagent", "single-agent-fallback"):
        raise InvalidSpec("Securer mode must reflect actual delegation")
    acknowledgements = doc.get("scan_finding_ids")
    ids = [f["id"] for f in scan_record["findings"]]
    if not isinstance(acknowledgements, list) or len(acknowledgements) != len(set(acknowledgements)) or set(acknowledgements) != set(ids):
        raise InvalidSpec("Securer must acknowledge every finding in the current scan")
    model = doc.get("threat_model")
    if not isinstance(model, dict) or model.get("network_exposure") not in ("none", "local", "public"):
        raise InvalidSpec("Securer threat model requires network_exposure none/local/public")
    actors = ensure_string(model.get("actors"), "threat_model.actors", 250)
    boundary = ensure_string(model.get("trust_boundary"), "threat_model.trust_boundary", 300)
    limits = doc.get("rate_limits")
    if not isinstance(limits, dict):
        raise InvalidSpec("Securer must assess abuse and rate limits")
    applicability = limits.get("applicability")
    if model["network_exposure"] == "public":
        if applicability != "implemented" or limits.get("strategy") not in ("per-client", "per-account", "provider"):
            raise InvalidSpec("Public network services require a documented rate/quota control")
        label = limits.get("test_label")
        plan = data["plan"]
        tasks = plan["tasks"] + plan.get("experience_checks", [])
        matched = next((t for t in tasks if t["test_label"] == label and re.search(r"rate[ -]?limit|throttl|quota|429|retry-after", t.get("acceptance", t.get("expected", "")), re.I)), None)
        if not matched and not (plan.get("contract_profile") == "external-api" and label == "external-contract"):
            raise InvalidSpec("Public rate control needs a dedicated bound acceptance criterion and executed test label")
        first = {t["label"]: t for t in latest_tests(data, "verify")}.get(label)
        if plan.get("contract_profile") == "external-api":
            # Agent-authored acceptance checks alone are weaker than a public HTTP black box.
            if label != "external-contract" or not data.get("behavior_contract", {}).get("kind") == "external-api":
                raise InvalidSpec("External API rate-limit policy must use the frozen external-contract check")
            first = {t["label"]: t for t in latest_tests(data, "verify")}.get("external-contract")
            if not first or first.get("contract_sha256") != data["behavior_contract"]["sha256"] or not first.get("contract_steps", 0):
                raise InvalidSpec("External API rate-limit check requires a matching executed loopback contract")
        if not first or first.get("exit_code") != 0 or not first.get("snapshot_stable"):
            raise InvalidSpec("Public rate-limit check must pass in initial verification")
    elif applicability != "not-applicable":
        raise InvalidSpec("Nonpublic surfaces require explicit not-applicable rate-limit rationale")
    policy = ensure_string(limits.get("policy"), "rate_limits.policy", 300)
    if len(policy) < 25:
        raise InvalidSpec("Explain rate-limit configuration or why it is not applicable")
    probe = doc.get("probe")
    if not isinstance(probe, dict) or probe.get("status") not in ("skipped-not-authorized", "skipped-out-of-scope", "performed-local"):
        raise InvalidSpec("Probing must be explicitly scoped or skipped")
    detail = ensure_string(probe.get("detail"), "security.probe.detail", 240)
    if probe["status"] == "performed-local":
        if probe.get("authorization") != "explicit" or not probe.get("target", "").startswith("local-project:"):
            raise InvalidSpec("Active probes require explicit local-project authorization; never imply permission for external targets")
        # This is a reviewer declaration, not a command execution or independently verified pentest.
    findings = doc.get("findings")
    if not isinstance(findings, list) or len(findings) > 12:
        raise InvalidSpec("Securer findings must be a list of at most 12")
    clean = []
    for entry in findings:
        if not isinstance(entry, dict) or entry.get("severity") not in ("critical", "major", "minor") or entry.get("resolution") not in ("fixed", "accepted", "open"):
            raise InvalidSpec("Invalid Securer finding")
        clean.append({"severity": entry["severity"], "resolution": entry["resolution"],
                      "issue": ensure_string(entry.get("issue"), "security.issue", 220),
                      "evidence": ensure_string(entry.get("evidence"), "security.evidence", 220)})
    changes = doc.get("changes", [])
    if not isinstance(changes, list) or len(changes) > 12:
        raise InvalidSpec("Securer changes must be a list of at most 12")
    changes = [ensure_string(x, "security.change", 180) for x in changes]
    blocking = any(f["severity"] in ("major", "critical") for f in scan_record["findings"])
    if verdict == "pass" and (blocking or any(v != "pass" for v in checks.values()) or any(f["severity"] != "minor" and f["resolution"] == "open" for f in clean)):
        raise InvalidSpec("Cannot pass Securer with major/critical scan findings, unresolved findings or failed controls; fix then rescan")
    return {"reviewer_mode": mode, "verdict": verdict,
            "summary": ensure_string(doc.get("summary"), "security.summary", 400), "checks": checks,
            "findings": clean, "changes": changes, "scan_finding_ids": acknowledgements,
            "threat_model": {"network_exposure": model["network_exposure"], "actors": actors, "trust_boundary": boundary},
            "rate_limits": {"applicability": applicability, "strategy": limits.get("strategy"),
                            "test_label": limits.get("test_label"), "policy": policy},
            "probe": {"status": probe["status"], "detail": detail},
            "source_fingerprint": scan_record["source_fingerprint"], "scan_at": scan_record["at"]}


def set_security_review(directory, source):
    path, data = load(directory)
    scan_record = data.get("security_scan")
    if not scan_record or scan_record["source_fingerprint"] != run_fingerprint(data):
        raise InvalidSpec("Securer requires a fresh scan of unchanged project source")
    if data["stages"]["polish"]["status"] != "done" or data["stages"]["final-verify"]["status"] != "pending":
        raise InvalidSpec("Securer runs after polish and before final verification")
    try:
        doc = read_json(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSpec(f"Cannot load Securer review: {exc}") from exc
    result = validate_security_review(doc, scan_record, data)
    data.setdefault("reviews", {})["security"] = result
    data["events"].append({"at": now(), "stage": "security", "status": "reviewed", "note": f"Securer verdict: {result['verdict']}"})
    save(path, data)
    return result


def security_review_ready(data):
    if (data.get("plan") or {}).get("security_profile") != "full":
        return True
    scan_record = data.get("security_scan")
    review = data.get("reviews", {}).get("security")
    if not scan_record or not review or review.get("verdict") != "pass":
        return False
    try:
        current = run_fingerprint(data)
    except (OSError, InvalidSpec):
        return False
    if scan_record.get("source_fingerprint") != current or review.get("source_fingerprint") != current:
        return False
    # Security edits require renewed quality and polish, never silently inherit old approvals.
    return all(data.get("reviews", {}).get(r, {}).get("source_fingerprint") == current for r in ("quality", "polish"))


def complete(data):
    if not (all(data["stages"][s]["status"] in ("done", "skipped") for s in STAGES)
            and verification_ready(data, "verify") and verification_ready(data, "final-verify")
            and reviews_current(data)
            and bool(data.get("final_fingerprint")) and security_review_ready(data) and usability_ready(data)):
        return False
    try:
        return run_fingerprint(data) == data["final_fingerprint"]
    except (InvalidSpec, OSError):
        return False


def render(directory, data):
    stage = data["stages"]
    secure = (data.get("plan") or {}).get("security_profile") == "full"
    sequence = list(STAGES)
    states = {name: stage[name]["status"] for name in STAGES}
    if secure:
        sequence.insert(sequence.index("final-verify"), "security")
        states["security"] = ("done" if security_review_ready(data) else
                              "active" if stage["polish"]["status"] == "done" and stage["final-verify"]["status"] == "pending" else "pending")
    novice_required = (data.get("plan") or {}).get("usability_profile") == "novice-v1"
    if novice_required:
        sequence.insert(sequence.index("polish"), "usability")
        states["usability"] = ("done" if usability_ready(data) else
                               "active" if stage["quality"]["status"] == "active" else "pending")
    flow = ["flowchart LR"]
    for name in sequence:
        status = states[name]
        flow.append(f'    {name}["{name.title()} — {status.title()}"]')
    for a, b in zip(sequence, sequence[1:]):
        flow.append(f"    {a} --> {b}")
    for state, cls in (("done", "done"), ("active", "active"), ("blocked", "blocked"), ("skipped", "skipped")):
        matched = ",".join(name for name in sequence if states[name] == state)
        if matched:
            flow.append(f"    class {matched} {cls}")
    flow.extend(["    classDef done fill:#d7f2df,stroke:#266a42,color:#173e27", "    classDef active fill:#dceafa,stroke:#245eab,color:#14365d", "    classDef blocked fill:#ffe1df,stroke:#b73434,color:#632020", "    classDef skipped fill:#eee,stroke:#888,color:#444"])
    atomic_write(directory / "WORKFLOW.md", "# Workflow diagram\n\nGenerated from `run.json` stage statuses.\n\n```mermaid\n" + "\n".join(flow) + "\n```\n")
    topo = data.get("architecture")
    if topo:
        lines = ["flowchart LR"]
        for n in topo["nodes"]:
            lines.append(f'    {n["id"]}["{mermaid_label(n["label"])}"]')
        for e in topo["edges"]:
            lines.append(f'    {e["from"]} -->|"{mermaid_label(e["label"])}"| {e["to"]}')
        arch = f"# Architecture diagram\n\n**Status:** {topo['status'].title()} (agent-declared, not independently code-audited).\n\n```mermaid\n" + "\n".join(lines) + "\n```\n"
    else:
        arch = "# Architecture diagram\n\nNot supplied yet. Add a reviewed architecture JSON through `architecture --file`; no components have been assumed.\n"
    atomic_write(directory / "ARCHITECTURE.md", arch)
    current = next((name for name in sequence if states[name] in ("active", "blocked")), "none")
    passed = sum(t["exit_code"] == 0 and not t["timeout"] for t in data["tests"])
    failed = len(data["tests"]) - passed
    rows = [f"| {name.title()} | {states[name]} | {escape(stage[name]['note']) if name in stage else 'Novice simulation / advocate gate' if name == 'usability' else 'Passive audit / reviewer gate'} |" for name in sequence]
    events = [f"- {escape(e['at'])} — **{escape(e['stage'])} / {escape(e['status'])}:** {escape(e['note'])}" for e in data["events"][-10:]]
    lines = ["# Just Build progress", "", f"**Run:** `{data['run_id']}` · **Mode:** {data['mode']} / {data['operation']}",
             f"**Goal:** {escape(data['goal'])}", f"**Project:** `{escape(data['project'])}`", f"**Current stage:** {current}",
             f"**Recorded test executions:** {len(data['tests'])} ({passed} passing, {failed} failing/timeout)",
             f"**Verification gates:** first={'ready' if verification_ready(data) else 'not ready'} · final={'ready' if verification_ready(data, 'final-verify') else 'not ready'}", "",
             "| Stage | Status | Latest note |", "|---|---|---|", *rows, "", "## Recent activity", *events,
             "", "The test results above are from commands executed by the local tracker; research and architecture labels are supplied by the agent. See `WORKFLOW.md`, `ARCHITECTURE.md`, and `run.json`.", ""]
    atomic_write(directory / "PROGRESS.md", "\n".join(lines))
    plan = data.get("plan")
    if plan:
        plan_text = ["# Acceptance plan", "", "## End-to-end user journey", escape(plan["user_journey"]), "",
                     f"**Quality profile:** {plan.get('quality_profile', 'legacy')} · **Security profile:** {plan.get('security_profile', 'standard')} · **Surface:** {plan.get('surface', 'cli')}",
                     "**Polish targets:** " + (", ".join(plan.get("polish_targets", [])) or "not specified"), "",
                     "**Delivery artifacts:** " + (", ".join(f"`{escape(x)}`" for x in plan.get("delivery_artifacts", [])) or "not declared (historical source-only snapshot)"),
                     "Declared delivery files must exist for verification and reviews; only implementation probes allow missing planned outputs.", "",
                     "## Tasks and executable acceptance evidence", "",
                     "| Task | Acceptance condition | Required test label |", "|---|---|---|",
                     *(f"| {escape(t['change'])} | {escape(t['acceptance'])} | `{t['test_label']}` |" for t in plan["tasks"]), "",
                     f"**Smoke test (`{plan['smoke_label']}`):** {escape(plan['smoke_test'])}",
                     "", "## User-experience regression checks",
                     *([f"- **{escape(x['scenario'])}** (`{escape(x['test_label'])}`): {escape(x['expected'])}" for x in plan.get('experience_checks', [])] or ["- Not defined in this historical plan."]),
                     f"**Command-bound labels:** {', '.join(t['test_label'] for t in plan['tasks'] if t.get('test_command')) + (', ' if any(t.get('test_command') for t in plan['tasks']) and plan.get('smoke_command') else '') + (plan['smoke_label'] if plan.get('smoke_command') else '') or 'none (agent-supplied labels; weaker evidence)'}", "", "## Out of scope",
                     *([f"- {escape(x)}" for x in plan["out_of_scope"]] or ["- None specified"]), ""]
    else:
        plan_text = ["# Acceptance plan", "", "Not recorded. Planning must define a user journey, verifiable tasks, and smoke test before completion.", ""]
    atomic_write(directory / "PLAN.md", "\n".join(plan_text))
    done = complete(data)
    test_rows = [f"| {escape(t.get('stage', 'verify'))} / {escape(t['label'])}: {escape(t['executable'])} (args hash {t['argv_sha256_prefix']}) | {t['exit_code']} | {t['elapsed_seconds']} | {escape(t['at'])} |" for t in data["tests"]]
    review_lines = ["# Final reviewer notes", "", "Reviewer observations are agent-supplied, not independent tool proof.", ""]
    for role in (*REVIEW_CHECKS, "security"):
        r = data.get("reviews", {}).get(role)
        review_lines += [f"## {role.title()}", ""]
        if not r:
            review_lines += ["Pending.", ""]
            continue
        review_lines += [f"**Mode:** {r['reviewer_mode']} · **Verdict:** {r['verdict']}", "", escape(r["summary"]), "", "| Check | Status |", "|---|---|",
                         *(f"| {escape(k)} | {escape(v)} |" for k,v in r["checks"].items()), "", "### Findings", ""]
        review_lines += ([f"- **{x['severity']} / {x['resolution']}**: {escape(x['issue'])} — {escape(x['evidence'])}" for x in r["findings"]] or ["- No findings recorded."])
        if r.get("target_evidence"):
            review_lines += ["", "### Planned polish targets", "", "| Target | Status | Evidence |", "|---|---|---|",
                             *(f"| {escape(k)} | {escape(v['status'])} | {escape(v['evidence'])} |" for k,v in r["target_evidence"].items())]
        review_lines += ["", "### Changes", ""] + ([f"- {escape(x)}" for x in r["changes"]] or ["- No changes recorded."]) + [""]
    atomic_write(directory / "REVIEWS.md", "\n".join(review_lines))
    scan_record = data.get("security_scan")
    security_lines = ["# Securer audit", "", "Passive scan only. Heuristic findings and agent-supplied review are not independent proof of security.", ""]
    if scan_record:
        security_lines += [f"**Scanned files:** {scan_record['scanned_files']} · **Findings:** {len(scan_record['findings'])} · **Snapshot:** `{scan_record['source_fingerprint'][:16]}`", "", "| Severity | Finding | Location | Suggested action |", "|---|---|---|---|",
            *[f"| {escape(f['severity'])} | {escape(f['code'])} ({escape(f['id'])}) | {escape(f['path'])}:{f['line']} | {escape(f['remediation'])} |" for f in scan_record['findings']], "",
            f"**Scan history:** {len(data.get('security_history', []))} local snapshot(s).", "",
            *[f"- {escape(h['at'])}: {h['finding_count']} finding(s) (source {h['fingerprint'][:12]})" for h in data.get('security_history', [])[-5:]], ""]
        if not scan_record['findings']:
            security_lines.append("No heuristic findings; this does not imply vulnerability-free software.")
    else:
        security_lines.append("Not scanned. Full security profiles cannot complete without a scan.")
    sec = data.get("reviews", {}).get("security")
    if sec:
        security_lines += ["", f"**Securer verdict:** {sec['verdict']} · **Mode:** {sec['reviewer_mode']}", "", escape(sec['summary']), "",
            f"**Network exposure:** {escape(sec['threat_model']['network_exposure'])}",
            f"**Rate controls:** {escape(sec['rate_limits']['policy'])}",
            f"**Active probing:** {escape(sec['probe']['status'])} — {escape(sec['probe']['detail'])}", "",
            "## Controls reviewed", "", "| Control | Outcome |", "|---|---|",
            *[f"| {escape(k)} | {escape(v)} |" for k, v in sec['checks'].items()], "",
            "## Reviewer findings", "",
            *([f"- {escape(f['severity'])} / {escape(f['resolution'])}: {escape(f['issue'])} — {escape(f['evidence'])}" for f in sec['findings']] or ["- None recorded."]), "",
            "## Recorded remediation", "",
            *([f"- {escape(x)}" for x in sec['changes']] or ["- No changes claimed."]), ""]
    if plan and plan.get("contract_profile") == "external-api" and data.get("behavior_contract"):
        frozen = data["behavior_contract"]["sha256"]
        security_lines += ["", "## Executed local API contract", "", f"**Frozen contract:** `{frozen[:16]}` (HTTP loopback only)"]
        for phase in ("verify", "final-verify"):
            observed = {t["label"]: t for t in latest_tests(data, phase)}.get("external-contract")
            passed = bool(observed and observed.get("contract_sha256") == frozen and observed.get("exit_code") == 0 and observed.get("snapshot_stable"))
            security_lines.append(f"- {phase}: {'passed' if passed else 'not passed / not executed'}; " + (f"{observed.get('contract_steps', 0)} planned requests" if observed else "no execution recorded"))
        security_lines += ["", "This is behavior evidence for the tested source and not an active pentest or production-security certification."]
    atomic_write(directory / "SECURITY_AUDIT.md", "\n".join(security_lines) + "\n")
    usability_lines = ["# Novice simulation and usability advocate", "", f"**Status:** {usability_status(data)}", "",
                       "These are agent-declared simulations, not real-user research or proof of independent identities. "
                       "The tracker captures source and frozen acceptance fingerprints; it does not perform the recorded journey.", ""]
    history = (data.get("usability") or {}).get("rounds", [])
    for index, pair in enumerate(history):
        observation = pair["novice"]
        advocate = pair.get("advocate")
        usability_lines += [f"## Round {index + 1}/{MAX_USABILITY_ROUNDS}", "",
                            f"**Novice:** {escape(observation['reviewer_id'])} / {observation['reviewer_mode']} / {observation['verdict']}",
                            f"**Assistance:** {escape(observation['assistance'])}",
                            f"**Goal:** {escape(observation['goal'])}", f"**Public entry:** {escape(observation['entrypoint'])}",
                            f"**Captured digest:** `{observation['sha256']}`",
                            f"**Source:** `{observation['source_fingerprint']}`", "",
                            "| Step | Action | Expected | Observed | Status |", "|---|---|---|---|---|",
                            *[f"| {escape(s['id'])} | {escape(s['action'])} | {escape(s['expected'])} | {escape(s['observed'])} | {s['status']} |" for s in observation["steps"]], "",
                            "**Difficulties:**", "",
                            *([f"- {escape(d['id'])} / {d['severity']} / {escape(d['step_id'])}: {escape(d['issue'])} — {escape(d['evidence'])}" for d in observation["difficulties"]] or ["- None declared."]), ""]
        if advocate:
            usability_lines += [f"**Advocate:** {escape(advocate['reviewer_id'])} / {advocate['reviewer_mode']} / {advocate['verdict']}",
                                f"**Assistance:** {escape(advocate['assistance'])}", escape(advocate["summary"]), "",
                                *([f"- {escape(d['difficulty_id'])} / {d['resolution']}: {escape(d['evidence'])}" for d in advocate["dispositions"]] or ["- No difficulty dispositions needed."]), "",
                                "**Declared changes:**", "", *([f"- {escape(c)}" for c in advocate["changes"]] or ["- None."]), ""]
        else:
            usability_lines += ["Advocate not recorded for this round.", ""]
    atomic_write(directory / "USABILITY.md", "\n".join(usability_lines) + "\n")
    # A short handoff for a late-stage agent: no whole-chat transcript or test stdout.
    brief = ["# Compact review brief", "", "Read the project itself for code truth; this summary is agent-generated.", "",
             f"**Goal:** {escape(data['goal'])}", f"**Operation:** {data['mode']} / {data['operation']}",
             f"**Project:** `{escape(data['project'])}`", "", "**Journey:** " + (escape(plan['user_journey']) if plan else 'Not planned'),
             "", "**Acceptance labels:** " + (", ".join([t['test_label'] for t in plan['tasks']] + [plan['smoke_label']]) if plan else 'none'),
             "", "**Stage results:** " + ", ".join(f"{x}:{stage[x]['status']}" for x in STAGES),
             "", "**Reviewer outcomes:** " + ", ".join(f"{x}:{data.get('reviews', {}).get(x, {}).get('verdict', 'pending')}" for x in (*REVIEW_CHECKS, "security")),
             "", "**Novice / advocate:** " + usability_status(data) + "; see USABILITY.md",
             "", "See REVIEWS.md for details. Do not treat this brief as executable-test evidence.", ""]
    atomic_write(directory / "BRIEF.md", "\n".join(brief))
    research_lines = ["# Research evidence", "", "Entries are agent-supplied citations. Tracker validates format, not external source truth.", ""]
    for row in data.get("research_evidence", []):
        research_lines += [f"## {escape(row['phase'])}: {escape(row['topic'])}", "", f"Source: {escape(row['url'] or row['kind'])} · Accessed: {escape(row['accessed_at'])}", "", f"Finding: {escape(row['finding'])}", "", f"Applied: {escape(row['application'])}", ""]
    atomic_write(directory / "RESEARCH.md", "\n".join(research_lines))
    contract = data.get("behavior_contract")
    contract_summary = ("**External behavior contract:** " + (contract["manifest"]["name"] + " (frozen; executed separately in each verification phase)" if contract else "not configured"))
    summary = ["# Just Build handoff report", "", f"**Status:** {'complete' if done else 'incomplete / in progress'}", f"**Goal:** {escape(data['goal'])}",
               f"**Project:** `{escape(data['project'])}`", "", "## Executed verification commands", "",
               "| Command | Exit code | Seconds | Executed at (UTC) |", "|---|---:|---:|---|", *(test_rows or ["| No test commands executed | — | — | — |"]), "",
               f"**Reviewer gates:** " + ", ".join(f"{role}: {data.get('reviews', {}).get(role, {}).get('verdict', 'pending')}" for role in (*REVIEW_CHECKS, "security")), "",
               f"**Final retest:** {'passed' if verification_ready(data, 'final-verify') else 'not passed'}", "",
               f"**Novice / advocate:** {usability_status(data)}; see USABILITY.md", "",
               contract_summary, "", "**Security audit:** " + ("required; " + ("passed" if security_review_ready(data) else "pending or stale") if plan and plan.get("security_profile") == "full" else "legacy/standard plan; not required") + "; see SECURITY_AUDIT.md", "", "Tests are snapshot-bound when their label is required; command bindings are optional but recommended. Agent-supplied review records are not independent tool proof.",
               "External research entries are agent-supplied; no independent web fetch by tracker. This report does not imply live Codex or connector integration tests. Test stdout/stderr is not persisted.", ""]
    selection_summary = data.get("idea_selection")
    if selection_summary:
        summary += ["## Idea selection", "", f"**Outcome:** {escape(selection_summary['outcome'])} · **Candidate:** {escape(selection_summary['winner'])}",
                    f"**Compared on:** {escape(selection_summary['as_of'])} · **Reviewer mode:** {escape(selection_summary['reviewer_mode'])}", "",
                    "Two evidence reports were compared before scaffolding; see idea-validation.json for sources, alternatives and objections.",
                    "Scores and source claims remain agent declarations, not a guarantee of demand or novelty.", ""]
    atomic_write(directory / "REPORT.md", "\n".join(summary))


def recheck_allowed(data):
    """The shared recovery predicate; read-only diagnostics must not invent resets."""
    post_quality_repair = (data["stages"]["quality"]["status"] == "done"
                           and data["stages"]["polish"]["status"] in ("pending", "active", "blocked", "done")
                           and data["stages"]["handoff"]["status"] != "done")
    return (post_quality_repair or
            data["stages"]["final-verify"]["status"] == "done" and data["stages"]["handoff"]["status"] != "done")


def diagnose(directory):
    """Inspect current evidence and safe recovery choices without changing files."""
    from run_diagnostics import diagnose as diagnose_run
    return diagnose_run(directory)


def recheck(directory):
    """Safely recover after a post-verification edit by repeating *both* reviews.

    The first verified snapshot stays historical, but no old reviewer judgment
    or final test is reused for changed product code or documentation.
    """
    path, data = load(directory)
    if not recheck_allowed(data):
        raise InvalidSpec("Recheck requires completed quality or final verification with unfinished handoff")
    for stage in ("quality", "polish", "final-verify", "handoff"):
        data["stages"][stage].update(status="active" if stage == "quality" else "pending",
                                     note="Reopened after post-verification source change", at=now())
        data["stages"][stage].pop("verified_fingerprint", None)
    data["reviews"] = {}
    data["security_scan"] = None
    if isinstance(data.get("usability"), dict):
        data["usability"]["active"] = None  # Preserve bounded observations without inheriting approvals.
    data["final_fingerprint"] = None
    data["events"].append({"at": now(), "stage": "quality", "status": "active", "note": "Reopened: fresh quality, polish and final verification required"})
    save(path, data)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="Just Build tracking, external behavior contracts and snapshot-bound verification")
    subs = parser.add_subparsers(dest="command", required=True)
    begin = subs.add_parser("start", help="Initialize run state without overwriting an existing run")
    begin.add_argument("--state-dir", required=True)
    begin.add_argument("--project", required=True)
    begin.add_argument("--mode", choices=("auto", "guided"), required=True)
    begin.add_argument("--operation", choices=("new", "continue"), required=True)
    begin.add_argument("--goal", required=True)
    step = subs.add_parser("step", help="Advance an ordered stage")
    step.add_argument("--state-dir", required=True)
    step.add_argument("--stage", choices=STAGES, required=True)
    step.add_argument("--status", choices=("active", "done", "blocked", "skipped"), required=True)
    step.add_argument("--note", required=True)
    plan_cmd = subs.add_parser("plan", help="Record verifiable user journey and acceptance tasks")
    plan_cmd.add_argument("--state-dir", required=True)
    plan_cmd.add_argument("--file", required=True)
    research = subs.add_parser("research", help="Record scoped, sourced idea or implementation research")
    research.add_argument("--state-dir", required=True)
    research.add_argument("--file", required=True)
    contract = subs.add_parser("contract", help="Freeze or execute an external CLI/API behavior contract")
    contract.add_argument("--state-dir", required=True)
    contract.add_argument("--file", help="Bind a contract JSON during plan stage; omit during verification to execute")
    arch = subs.add_parser("architecture", help="Generate a grounded Mermaid architecture from JSON")
    arch.add_argument("--state-dir", required=True)
    arch.add_argument("--file", required=True)
    structural_cmd = subs.add_parser("structural", help="Record new-project structural gate")
    structural_cmd.add_argument("--state-dir", required=True)
    test = subs.add_parser("test", help="Execute an argv command without a shell; record exit status")
    test.add_argument("--state-dir", required=True)
    test.add_argument("--cwd")
    test.add_argument("--label", default="test")
    test.add_argument("--timeout", type=int, default=120)
    test.add_argument("argv", nargs=argparse.REMAINDER)
    review = subs.add_parser("review", help="Record quality or polish reviewer observations")
    review.add_argument("--state-dir", required=True)
    review.add_argument("--role", choices=(*REVIEW_CHECKS, "security"), required=True)
    review.add_argument("--file", required=True)
    usability_cmd = subs.add_parser("usability", help="Record a first-time user simulation or its usability advocate inside quality")
    usability_cmd.add_argument("--state-dir", required=True)
    usability_cmd.add_argument("--role", choices=("novice", "advocate"), required=True)
    usability_cmd.add_argument("--file", required=True)
    security_cmd = subs.add_parser("security-scan", help="Passive local Securer scan; never probes networks")
    security_cmd.add_argument("--state-dir", required=True)
    retry = subs.add_parser("recheck", help="Reopen quality, usability, polish and final checks after a late repair")
    retry.add_argument("--state-dir", required=True)
    report = subs.add_parser("report", help="Regenerate and display report summary")
    report.add_argument("--state-dir", required=True)
    diagnostic = subs.add_parser("diagnose", help="Read-only current evidence and bounded recovery guidance")
    diagnostic.add_argument("--state-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = init(args.state_dir, args.project, args.mode, args.operation, args.goal)
        elif args.command == "step":
            result = record_stage(args.state_dir, args.stage, args.status, args.note)
        elif args.command == "plan":
            result = set_plan(args.state_dir, args.file)
        elif args.command == "research":
            result = set_research(args.state_dir, args.file)
        elif args.command == "contract":
            result = set_behavior_contract(args.state_dir, args.file) if args.file else run_behavior_contract(args.state_dir)
        elif args.command == "architecture":
            result = set_architecture(args.state_dir, args.file)
        elif args.command == "structural":
            result = structural(args.state_dir)
        elif args.command == "review":
            result = set_security_review(args.state_dir, args.file) if args.role == "security" else set_review(args.state_dir, args.role, args.file)
        elif args.command == "usability":
            result = set_usability(args.state_dir, args.role, args.file)
        elif args.command == "security-scan":
            result = security_scan(args.state_dir)
        elif args.command == "test":
            result, excerpt = actual_test(args.state_dir, args.argv, args.timeout, args.cwd, args.label)
            print("--- Test output (bounded tail, not persisted) ---\n" + excerpt, file=sys.stderr)
        elif args.command == "recheck":
            result = recheck(args.state_dir)
        elif args.command == "diagnose":
            result = diagnose(args.state_dir)
        else:
            path, data = load(args.state_dir)
            render(path.parent, data)
            result = {"run_id": data["run_id"], "stages": {k: v["status"] for k, v in data["stages"].items()},
                      "verification_ready": verification_ready(data), "final_verification_ready": verification_ready(data, "final-verify"), "test_executions": len(data["tests"]),
                      "reviews": {k: v.get("verdict") for k,v in data.get("reviews", {}).items()}, "security_ready": security_review_ready(data), "complete": complete(data),
                      "usability_ready": usability_ready(data), "usability_status": usability_status(data),
                      "research_entries": len(data.get("research_evidence", [])), "report": str(path.parent / "REPORT.md")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (InvalidSpec, ContractError, APIContractError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"just-build run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
