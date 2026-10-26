#!/usr/bin/env python3
"""Execute a small agent-authored *external* CLI behavior contract.

Checks a public entry point, not project-owned unit tests. Each scenario receives
its own temporary data directory; its steps share that directory. This is data
isolation, NOT a security sandbox. Run only against code and manifests you trust.
Test output is never persisted by this helper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
import tempfile
from host_safety import is_link, safe_relative as portable_relative, checked_path, regular_bytes, bounded_json
from process_runner import run_command, ProcessSafetyError
from contract_assertions import json_expectation, strict_json, json_equal

class ContractError(ValueError):
    pass

ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
TOKENS = ("{project}", "{scratch}", "{python}")
UNCHANGED_FILE_MAX_BYTES = 1024 * 1024


def safe_relative(value):
    try:
        return portable_relative(value)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc


def strings(value, field, minimum=0, maximum=5):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ContractError(f"{field} must contain {minimum}..{maximum} entries")
    if any(not isinstance(x, str) or not x or len(x) > 240 or "\x00" in x for x in value):
        raise ContractError(f"Invalid {field} entry")
    return value


def validate(doc):
    if not isinstance(doc, dict) or set(doc) != {"name", "scenarios"}:
        raise ContractError("Contract requires name and scenarios only")
    if not isinstance(doc["name"], str) or not 5 <= len(doc["name"]) <= 100:
        raise ContractError("Invalid contract name")
    cases = doc["scenarios"]
    if not isinstance(cases, list) or not 2 <= len(cases) <= 5:
        raise ContractError("Contract requires 2..5 scenarios")
    names, total, failure, observed, file_check, multi_step = set(), 0, False, False, False, False
    cleaned = []
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "steps"} or not isinstance(case["id"], str) or not ID.fullmatch(case["id"]) or case["id"] in names:
            raise ContractError("Scenario id must be unique and lowercase")
        names.add(case["id"])
        steps = case["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 6:
            raise ContractError("Each scenario requires 1..6 steps")
        multi_step |= len(steps) >= 2
        normalized = []
        for step in steps:
            allowed = {"argv", "exit_code", "stdout_contains", "stderr_contains", "stdout_excludes", "file_exists", "file_absent", "file_contains", "stdout_json_equals", "file_unchanged"}
            if not isinstance(step, dict) or set(step) - allowed or not {"argv", "exit_code"}.issubset(step):
                raise ContractError("Steps need argv and expected exit_code; unknown fields are forbidden")
            argv = strings(step["argv"], "argv", 1, 24)
            if any("{" in arg.replace("{project}", "").replace("{scratch}", "").replace("{python}", "") or "}" in arg.replace("{project}", "").replace("{scratch}", "").replace("{python}", "") for arg in argv):
                raise ContractError("Unsupported command placeholder")
            if not (len(argv) >= 2 and argv[0] == "{python}" and argv[1].startswith("{project}/") and argv[1].endswith(".py") or argv[0].startswith("{project}/")):
                raise ContractError("Command must invoke an explicit public project entry point (Python script or local executable)")
            entry = argv[1] if argv[0] == "{python}" else argv[0]
            rel = entry[len("{project}/"):]
            safe_relative(rel)
            if not rel or "\\" in rel or any(part in (".", "..", "") for part in rel.split("/")):
                raise ContractError("Public entry point must be a safe project-relative path")
            exit_code = step["exit_code"]
            if type(exit_code) is not int or not -255 <= exit_code <= 255:
                raise ContractError("exit_code must be an integer")
            failure |= exit_code != 0
            strings_by_key = {k: strings(step.get(k, []), k) for k in ("stdout_contains", "stderr_contains", "stdout_excludes")}
            checks = {k: [str(safe_relative(x)) for x in strings(step.get(k, []), k)] for k in ("file_exists", "file_absent")}
            contains = step.get("file_contains", {})
            if not isinstance(contains, dict) or len(contains) > 5:
                raise ContractError("file_contains must be a small path-to-text mapping")
            checks["file_contains"] = {}
            for p, snippet in contains.items():
                p = str(safe_relative(p))
                if not isinstance(snippet, str) or not snippet or len(snippet) > 240:
                    raise ContractError("file_contains must use nonempty bounded snippets")
                checks["file_contains"][p] = snippet
            extra = {}
            if "stdout_json_equals" in step:
                try:
                    extra["stdout_json_equals"] = json_expectation(step["stdout_json_equals"])
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"Invalid stdout_json_equals: {exc}") from exc
            if "file_unchanged" in step:
                unchanged = [str(safe_relative(x)) for x in strings(step["file_unchanged"], "file_unchanged", 1, 5)]
                if len({p.casefold() for p in unchanged}) != len(unchanged):
                    raise ContractError("file_unchanged paths must be unique, including case aliases")
                if {p.casefold() for p in unchanged} & {p.casefold() for p in checks["file_absent"]}:
                    raise ContractError("file_unchanged conflicts with file_absent")
                extra["file_unchanged"] = unchanged
            file_check |= any(checks.values())
            file_check |= "file_unchanged" in extra
            observed |= any(strings_by_key.values()) or any(checks.values()) or bool(extra)
            if not any(strings_by_key.values()) and not any(checks.values()) and not extra:
                raise ContractError("Every step needs at least one observable output/file assertion")
            normalized.append({"argv": argv, "exit_code": exit_code, **strings_by_key, **checks, **extra})
            total += 1
        cleaned.append({"id": case["id"], "steps": normalized})
    if total < 4 or not failure or not observed or not file_check or not multi_step:
        raise ContractError("Contract needs 4+ steps, a nonzero-error case, a file-state check and a multi-step scenario")
    return {"name": doc["name"], "scenarios": cleaned}


def scratch_file(base, rel):
    root = base.resolve(strict=True)
    try:
        path = checked_path(root.joinpath(*safe_relative(rel).parts), root, must_exist=False)
        if path.exists() and path.is_file() and path.stat().st_nlink > 1:
            raise ValueError('hard-linked scratch artifacts are forbidden')
        return path
    except (OSError, ValueError) as exc:
        raise ContractError(str(exc)) from exc


def run(project, manifest):
    if is_link(project):
        raise ContractError("linked project roots are forbidden")
    project = Path(project).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ContractError("project must be a directory")
    contract = validate(manifest)
    outcomes = []
    for case in contract["scenarios"]:
        with tempfile.TemporaryDirectory(prefix="just-build-contract-") as tmp:
            scratch = Path(tmp).resolve(strict=True)
            for idx, step in enumerate(case["steps"], 1):
                replacement = {"{project}": str(project), "{scratch}": str(scratch), "{python}": sys.executable}
                argv = [arg.replace("{project}", replacement["{project}"]).replace("{scratch}", replacement["{scratch}"]).replace("{python}", replacement["{python}"]) for arg in step["argv"]]
                entry = argv[1] if step["argv"][0] == "{python}" else argv[0]
                entry_path = Path(entry)
                try:
                    checked_path(entry_path, project)
                except (OSError, ValueError) as exc:
                    raise ContractError('Public entry point must be unlinked and within the project') from exc
                if not entry_path.is_file():
                    raise ContractError("Public entry point must be a regular file inside the project")
                snapshots = {}
                failures = []
                for rel in step.get("file_unchanged", []):
                    try:
                        before = regular_bytes(scratch_file(scratch, rel), UNCHANGED_FILE_MAX_BYTES,
                                               root=scratch, reject_hardlinks=True)
                        snapshots[rel] = hashlib.sha256(before).digest()
                    except (OSError, ValueError):
                        failures.append(f"file_unchanged precondition: {rel} must be a pre-existing unlinked regular file <=1 MiB")
                if failures:
                    outcomes.append({"scenario": case["id"], "step": idx, "passed": False, "failures": failures})
                    return {"name": contract["name"], "passed": False, "steps_passed": sum(x["passed"] for x in outcomes), "steps_total": sum(len(c["steps"]) for c in contract["scenarios"]), "outcomes": outcomes}
                raw_stdout = b""
                try:
                    observed = run_command(argv, scratch, timeout=12)
                    raw_stdout = observed.stdout
                    stdout = observed.stdout.decode('utf-8', errors='replace')
                    stderr = observed.stderr.decode('utf-8', errors='replace')
                    code = observed.returncode
                    failures = []
                    if observed.timed_out or observed.output_limited or not observed.cleanup_complete:
                        failures.append('command exceeded its resource limit or cleanup failed')
                    if code != step["exit_code"]:
                        failures.append(f"expected exit {step['exit_code']}, got {code}")
                except (OSError, ProcessSafetyError) as exc:
                    stdout, stderr, code, failures = "", "", 127, [f"could not execute ({type(exc).__name__})"]
                if "stdout_json_equals" in step:
                    try:
                        actual = strict_json(raw_stdout)
                        if not json_equal(actual, step["stdout_json_equals"]):
                            failures.append("stdout_json_equals: whole JSON value/type differs")
                    except (ValueError, UnicodeError):
                        failures.append("stdout_json_equals: output must be bounded strict UTF-8 JSON")
                for rel, before in snapshots.items():
                    try:
                        after = regular_bytes(scratch_file(scratch, rel), UNCHANGED_FILE_MAX_BYTES,
                                              root=scratch, reject_hardlinks=True)
                        if hashlib.sha256(after).digest() != before:
                            failures.append(f"file_unchanged: {rel} bytes changed")
                    except (OSError, ValueError):
                        failures.append(f"file_unchanged: {rel} is missing, linked, nonregular or oversized")
                for key, stream in (("stdout_contains", stdout), ("stderr_contains", stderr)):
                    for snippet in step[key]:
                        if snippet not in stream:
                            failures.append(f"{key}: missing required text")
                for snippet in step["stdout_excludes"]:
                    if snippet in stdout:
                        failures.append("stdout_excludes: forbidden text present")
                for key, exists in (("file_exists", True), ("file_absent", False)):
                    for rel in step[key]:
                        if scratch_file(scratch, rel).exists() != exists:
                            failures.append(f"{key}: {rel}")
                for rel, snippet in step["file_contains"].items():
                    file = scratch_file(scratch, rel)
                    if not file.is_file() or snippet not in regular_bytes(file, 1024*1024, root=scratch, reject_hardlinks=True).decode('utf-8', errors='replace'):
                        failures.append(f"file_contains: {rel}")
                outcomes.append({"scenario": case["id"], "step": idx, "passed": not failures, "failures": failures})
                if failures:
                    return {"name": contract["name"], "passed": False, "steps_passed": sum(x["passed"] for x in outcomes), "steps_total": sum(len(c["steps"]) for c in contract["scenarios"]), "outcomes": outcomes}
    return {"name": contract["name"], "passed": True, "steps_passed": len(outcomes), "steps_total": len(outcomes), "outcomes": outcomes}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run an external CLI behavior contract (not a sandbox)")
    parser.add_argument("--project", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    try:
        doc = bounded_json(args.file)
        report = run(args.project, doc)
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] else 1
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"behavior-contract: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
