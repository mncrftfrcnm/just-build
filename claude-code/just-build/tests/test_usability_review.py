"""First-time user simulations remain distinct, bounded and snapshot-bound."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import ROOT, load_example
from just_build import InvalidSpec, scaffold
import run_tracker as tracker
from usability_review import validate_novice, validate_advocate


def novice(failing=False):
    doc = {"version": 1, "reviewer_mode": "subagent", "reviewer_id": "fixture-novice",
           "simulation": True, "assistance": "Synthetic test fixture; public README and help only.",
           "verdict": "needs-work" if failing else "pass", "goal": "Create a first useful result",
           "entrypoint": "README.md quick start",
           "steps": [{"id": "first-result", "action": "Run the README's documented public command",
                      "expected": "A visible successful result", "observed": "Missing input instructions" if failing else "Command completed with the expected result",
                      "status": "blocked" if failing else "pass"}], "difficulties": []}
    if failing:
        doc["difficulties"] = [{"id": "input-location", "step_id": "first-result", "severity": "major",
                                "issue": "Cannot discover where the input file belongs", "evidence": "README command uses an unexplained relative path"}]
    return doc


def advocate(observation, passing=True):
    return {"version": 1, "reviewer_mode": "subagent", "reviewer_id": "fixture-advocate",
            "simulation": True, "assistance": "Synthetic test fixture; read captured novice evidence and public entry path.",
            "verdict": "pass" if passing else "needs-work", "novice_sha256": observation["sha256"],
            "summary": "Review the novice's difficulties while retaining every frozen acceptance requirement.",
            "dispositions": [{"difficulty_id": d["id"], "resolution": "fixed", "evidence": "Added the input location to the public quick start; fresh novice retest is still required"} for d in observation["difficulties"]],
            "changes": [], "preserved_acceptance": True}


class UsabilityValidationTests(unittest.TestCase):
    def test_empty_malformed_and_spoofed_novice_evidence_is_rejected(self):
        invalid = [None, {}, [], {**novice(), "steps": []}, {**novice(), "simulation": False},
                   {**novice(), "version": True}, {**novice(), "assistance": " "},
                   {**novice(), "source_fingerprint": "forged"}, {**novice(), "steps": novice()["steps"] * 13},
                   {**novice(), "steps": novice()["steps"] * 2}]
        for doc in invalid:
            with self.subTest(doc=doc), self.assertRaises(InvalidSpec):
                validate_novice(doc)
        for field, value in (("step_id", []), ("id", {}), ("evidence", "")):
            doc = novice(True)
            doc["difficulties"][0][field] = value
            with self.subTest(field=field), self.assertRaises(InvalidSpec):
                validate_novice(doc)

    def test_blocked_or_confusing_steps_cannot_pass_or_hide_difficulty(self):
        for status in ("blocked", "confusing"):
            doc = novice()
            doc["steps"][0]["status"] = status
            with self.subTest(status=status), self.assertRaises(InvalidSpec):
                validate_novice(doc)
            doc["difficulties"] = novice(True)["difficulties"]
            doc["difficulties"][0]["severity"] = "minor"
            with self.subTest(status=status, minor=True), self.assertRaises(InvalidSpec):
                validate_novice(doc)
        self.assertEqual(validate_novice(novice(True))["verdict"], "needs-work")

    def test_advocate_must_disposition_exact_observation_and_every_difficulty(self):
        observation = {**validate_novice(novice(True)), "sha256": "a" * 64}
        base = advocate(observation, False)
        self.assertEqual(validate_advocate(base, observation, observation["sha256"])["verdict"], "needs-work")
        invalid = [{**base, "novice_sha256": "wrong"}, {**base, "dispositions": []},
                   {**base, "dispositions": base["dispositions"] * 2},
                   {**base, "dispositions": [{**base["dispositions"][0], "difficulty_id": []}]},
                   {**base, "preserved_acceptance": False}, {**base, "verdict": "pass"}]
        for doc in invalid:
            with self.subTest(doc=doc), self.assertRaises(InvalidSpec):
                validate_advocate(doc, observation, observation["sha256"])

    def test_distinct_subagents_and_honest_fallback_are_declared(self):
        observation = {**validate_novice(novice()), "sha256": "a" * 64}
        doc = advocate(observation)
        doc["reviewer_id"] = observation["reviewer_id"]
        with self.assertRaisesRegex(InvalidSpec, "different reviewer"):
            validate_advocate(doc, observation, observation["sha256"])
        observation["reviewer_mode"] = doc["reviewer_mode"] = "single-agent-fallback"
        self.assertEqual(validate_advocate(doc, observation, observation["sha256"])["reviewer_mode"], "single-agent-fallback")

    def test_completed_minor_friction_must_be_fixed_or_explicitly_accepted(self):
        doc = novice()
        doc["difficulties"] = [{**novice(True)["difficulties"][0], "severity": "minor"}]
        observation = {**validate_novice(doc), "sha256": "a" * 64}
        response = advocate(observation)
        response["dispositions"][0]["resolution"] = "accepted"
        self.assertEqual(validate_advocate(response, observation, observation["sha256"])["verdict"], "pass")
        response["dispositions"][0]["resolution"] = "open"
        with self.assertRaisesRegex(InvalidSpec, "fixed or explicitly accepted"):
            validate_advocate(response, observation, observation["sha256"])

    def test_fixture_examples_cannot_be_recorded_as_real_observations(self):
        observation = {**validate_novice(novice()), "sha256": "a" * 64}
        for marker in (True, "false", 0, None):
            with self.subTest(marker=marker), self.assertRaises(InvalidSpec):
                validate_novice({**novice(), "fixture_only": marker})
            with self.subTest(marker=marker, role="advocate"), self.assertRaises(InvalidSpec):
                validate_advocate({**advocate(observation), "fixture_only": marker}, observation, observation["sha256"])
        self.assertEqual(validate_novice({**novice(), "fixture_only": False}), validate_novice(novice()))

    def test_profile_is_explicit_for_new_plans_and_legacy_readable(self):
        legacy = load_example("build-plan.json")
        self.assertNotIn("usability_profile", tracker.plan_validate(legacy))
        for profile in (None, "legacy", "novice-v2", [], True):
            with self.subTest(profile=profile), self.assertRaises(InvalidSpec):
                tracker.plan_validate({**legacy, "usability_profile": profile})
        with tempfile.TemporaryDirectory() as tmp:
            project = scaffold(load_example("spec.json"), tmp)
            state = project / ".just-build"
            tracker.init(state, project, "auto", "new", "Synthetic planning requirement")
            tracker.record_stage(state, "research", "done", "Synthetic fixture")
            tracker.record_stage(state, "plan", "active", "Freeze enhanced plan")
            doc = load_example("enhanced-build-plan.json")
            doc.pop("usability_profile", None)
            source = Path(tmp) / "plan.json"
            source.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(InvalidSpec, "novice-v1"):
                tracker.set_plan(state, source)


class UsabilityGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / "app"
        self.project.mkdir()
        self.script = self.project / "probe.py"
        self.script.write_text("assert 2 + 2 == 4\n", encoding="utf-8")
        self.output = self.project / "dist/app.txt"
        self.output.parent.mkdir()
        self.output.write_text("delivered fixture", encoding="utf-8")
        self.state = self.base / "ledger"
        self.command = [sys.executable, "probe.py"]
        tracker.init(self.state, self.project, "auto", "continue", "Exercise snapshot-bound usability gates")
        tracker.record_stage(self.state, "research", "skipped", "Local synthetic fixture")
        tracker.record_stage(self.state, "plan", "active", "Freeze acceptance before usability")
        plan = load_example("build-plan.json")
        plan.update(quality_profile="enhanced", usability_profile="novice-v1", surface="cli",
                    polish_targets=["first-run", "error-state", "help-output", "microcopy"], delivery_artifacts=["dist/app.txt"],
                    smoke_command=self.command)
        plan["tasks"][0].update(focus="journey", test_command=self.command)
        plan["tasks"].append({"id": "invalid", "change": "Reject an invalid input", "acceptance": "Clear recoverable error", "focus": "edge", "test_label": "edge", "test_command": self.command})
        tracker.set_plan(self.state, self.json_file(plan))
        tracker.record_stage(self.state, "plan", "done", "Acceptance frozen")
        tracker.record_stage(self.state, "implement", "active", "Implement local fixture")
        tracker.record_stage(self.state, "implement", "done", "Fixture exists")
        tracker.record_stage(self.state, "verify", "active", "Actually execute checks")
        self.run_required()
        tracker.record_stage(self.state, "verify", "done", "Initial checks passed")
        tracker.record_stage(self.state, "quality", "active", "Review behavior before polish")

    def json_file(self, value):
        source = self.base / "evidence.json"
        source.write_text(json.dumps(value), encoding="utf-8")
        return source

    def data(self):
        return tracker.load(self.state)[1]

    def run_required(self):
        for label in ("unit", "edge", "smoke"):
            evidence, _ = tracker.actual_test(self.state, self.command, label=label)
            self.assertEqual(evidence["exit_code"], 0)

    def pair(self):
        observation = tracker.set_usability(self.state, "novice", self.json_file(novice()))
        tracker.set_usability(self.state, "advocate", self.json_file(advocate(observation)))
        return observation

    def quality_done(self):
        tracker.set_review(self.state, "quality", ROOT / "examples/quality-review.json")
        tracker.record_stage(self.state, "quality", "done", "Quality and fresh usability passed")

    def polish_done(self):
        tracker.record_stage(self.state, "polish", "active", "Final surface polish")
        tracker.set_review(self.state, "polish", ROOT / "examples/enhanced-polish-review.json")
        tracker.record_stage(self.state, "polish", "done", "Current polish passed")

    def final_done(self):
        tracker.record_stage(self.state, "final-verify", "active", "Repeat all acceptance commands")
        self.run_required()
        tracker.record_stage(self.state, "final-verify", "done", "Current final checks passed")

    def test_quality_cannot_complete_without_sequential_current_pair(self):
        tracker.set_review(self.state, "quality", ROOT / "examples/quality-review.json")
        with self.assertRaisesRegex(InvalidSpec, "fresh passing novice"):
            tracker.record_stage(self.state, "quality", "done", "Missing user path evidence")
        doc = advocate({**novice(), "sha256": "a" * 64})
        with self.assertRaisesRegex(InvalidSpec, "before the advocate"):
            tracker.set_usability(self.state, "advocate", self.json_file(doc))
        observation = tracker.set_usability(self.state, "novice", self.json_file(novice()))
        with self.assertRaisesRegex(InvalidSpec, "exact tracker-captured"):
            tracker.set_usability(self.state, "advocate", self.json_file(doc))
        self.assertFalse(tracker.usability_ready(self.data()))
        tracker.set_usability(self.state, "advocate", self.json_file(advocate(observation)))
        self.quality_done()

    def test_fresh_pair_can_finish_full_workflow_and_renders_honest_report(self):
        self.pair()
        self.quality_done()
        self.polish_done()
        self.final_done()
        tracker.record_stage(self.state, "handoff", "active", "Deliver checked fixture")
        tracker.record_stage(self.state, "handoff", "done", "Fixture delivered")
        data = self.data()
        self.assertTrue(tracker.complete(data))
        report = (self.state / "USABILITY.md").read_text(encoding="utf-8")
        self.assertIn("not real-user research", report)
        self.assertIn("fixture-novice", report)
        self.assertIn("fixture-advocate", report)
        self.assertIn("passed / current", (self.state / "REPORT.md").read_text(encoding="utf-8"))

    def test_failed_observation_and_intermediate_remediation_survive_retest(self):
        initial = tracker.set_usability(self.state, "novice", self.json_file(novice(True)))
        self.script.write_text("assert 3 + 3 == 6\n", encoding="utf-8")
        response = advocate(initial, False)
        response["changes"] = ["Explain where to create the input file in the quick start"]
        tracker.set_usability(self.state, "advocate", self.json_file(response))
        self.assertFalse(tracker.usability_ready(self.data()))
        self.pair()
        data = self.data()
        self.assertTrue(tracker.usability_ready(data))
        self.assertEqual(data["usability"]["rounds"][0]["novice"], initial)
        self.assertEqual(data["usability"]["rounds"][0]["advocate"]["verdict"], "needs-work")
        self.assertIn("input-location", (self.state / "USABILITY.md").read_text(encoding="utf-8"))

    def test_novice_cannot_replace_unheard_difficulties_with_a_clean_retest(self):
        initial = tracker.set_usability(self.state, "novice", self.json_file(novice(True)))
        self.script.write_text("assert 3 > 1\n", encoding="utf-8")
        with self.assertRaisesRegex(InvalidSpec, "advocate must disposition"):
            tracker.set_usability(self.state, "novice", self.json_file(novice()))
        self.assertEqual(len(self.data()["usability"]["rounds"]), 1)
        tracker.set_usability(self.state, "advocate", self.json_file(advocate(initial, False)))
        self.pair()
        self.assertTrue(tracker.usability_ready(self.data()))
        self.assertEqual(self.data()["usability"]["rounds"][0]["novice"], initial)

    def test_recheck_cleared_orphan_needs_listener_but_does_not_deadlock(self):
        initial = tracker.set_usability(self.state, "novice", self.json_file(novice(True)))
        path, data = tracker.load(self.state)
        # Simulate an earlier interrupted in-development ledger: the orphan
        # observation is retained while later stage state requires recheck.
        data["stages"]["quality"]["status"] = "done"
        tracker.save(path, data)
        tracker.recheck(self.state)
        with self.assertRaisesRegex(InvalidSpec, "advocate must disposition"):
            tracker.set_usability(self.state, "novice", self.json_file(novice()))
        tracker.set_usability(self.state, "advocate", self.json_file(advocate(initial, False)))
        self.assertIsNone(self.data()["usability"]["active"])
        self.assertFalse(tracker.usability_ready(self.data()))
        self.pair()
        self.assertTrue(tracker.usability_ready(self.data()))

    def test_source_and_declared_delivery_mutations_require_novice_retest(self):
        observation = self.pair()
        self.assertEqual(observation["source_fingerprint"], tracker.run_fingerprint(self.data()))
        self.script.write_text("assert 5 + 5 == 10\n", encoding="utf-8")
        self.assertFalse(tracker.usability_ready(self.data()))
        self.pair()
        self.assertTrue(tracker.usability_ready(self.data()))
        self.output.write_text("changed delivered fixture", encoding="utf-8")
        self.assertFalse(tracker.usability_ready(self.data()))
        with self.assertRaises(InvalidSpec):
            self.quality_done()

    def test_stale_passing_observation_cannot_be_reused_by_new_advocate(self):
        observation = tracker.set_usability(self.state, "novice", self.json_file(novice()))
        self.script.write_text("assert 4 + 4 == 8\n", encoding="utf-8")
        tracker.set_usability(self.state, "advocate", self.json_file(advocate(observation)))
        self.assertFalse(tracker.usability_ready(self.data()))
        with self.assertRaises(InvalidSpec):
            self.quality_done()

    def test_duplicate_advocate_and_unbounded_rounds_cannot_erase_history(self):
        observation = self.pair()
        with self.assertRaisesRegex(InvalidSpec, "already has an advocate"):
            tracker.set_usability(self.state, "advocate", self.json_file(advocate(observation)))
        self.pair()
        self.pair()
        with self.assertRaisesRegex(InvalidSpec, "Three novice rounds exhausted"):
            self.pair()
        self.assertEqual(len(self.data()["usability"]["rounds"]), 3)

    def test_plan_or_external_contract_mutation_stales_approval(self):
        self.pair()
        path, data = tracker.load(self.state)
        data["behavior_contract"] = {"sha256": "changed-contract", "manifest": {"name": "Synthetic changed boundary"}}
        tracker.save(path, data)
        self.assertFalse(tracker.usability_ready(self.data()))
        with self.assertRaises(InvalidSpec):
            self.quality_done()

    def test_changed_late_polish_can_reopen_quality_without_relaxing_acceptance(self):
        for completed_polish in (False, True):
            with self.subTest(completed_polish=completed_polish):
                if completed_polish:
                    # The first iteration left this new quality round active.
                    self.pair()
                    self.quality_done()
                    self.polish_done()
                else:
                    self.pair()
                    self.quality_done()
                    tracker.record_stage(self.state, "polish", "active", "Inspect first-run wording")
                before = deepcopy(self.data()["plan"])
                self.script.write_text(f"assert {6 + int(completed_polish)} > 1\n", encoding="utf-8")
                reopened = tracker.recheck(self.state)
                self.assertEqual(reopened["plan"], before)
                self.assertEqual(reopened["stages"]["quality"]["status"], "active")
                self.assertIsNone(reopened["usability"]["active"])
                self.assertFalse(tracker.usability_ready(reopened))
                self.assertEqual(len(reopened["usability"]["rounds"]), 1 + int(completed_polish))
        self.pair()
        self.quality_done()
        self.polish_done()
        self.final_done()

    def test_edit_before_polish_activation_can_recover_from_pending_polish(self):
        self.pair()
        self.quality_done()
        original = deepcopy(self.data()["plan"])
        self.script.write_text("assert 9 > 1\n", encoding="utf-8")
        with self.assertRaisesRegex(InvalidSpec, "fresh passing novice"):
            tracker.record_stage(self.state, "polish", "active", "Stale observation cannot enter polish")
        reopened = tracker.recheck(self.state)
        self.assertEqual(reopened["stages"]["quality"]["status"], "active")
        self.assertEqual(reopened["stages"]["polish"]["status"], "pending")
        self.assertEqual(reopened["plan"], original)
        self.assertFalse(tracker.usability_ready(reopened))
        self.pair()
        self.quality_done()
        self.polish_done()
        self.final_done()

    def test_stale_gate_blocks_final_verification_and_completed_status(self):
        self.pair()
        self.quality_done()
        self.polish_done()
        self.final_done()
        self.output.write_text("later delivery mutation", encoding="utf-8")
        data = self.data()
        self.assertFalse(tracker.verification_ready(data, "final-verify"))
        self.assertFalse(tracker.complete(data))
        with self.assertRaisesRegex(InvalidSpec, "fresh passing novice"):
            tracker.record_stage(self.state, "handoff", "active", "Changed delivery cannot hand off")
        reopened = tracker.recheck(self.state)
        self.assertFalse(tracker.usability_ready(reopened))

    def test_legacy_loaded_enhanced_ledger_retains_old_readability(self):
        path, data = tracker.load(self.state)
        data["plan"].pop("usability_profile")
        data.pop("usability", None)
        tracker.save(path, data)
        self.assertTrue(tracker.usability_ready(self.data()))
        with self.assertRaisesRegex(InvalidSpec, "during planning"):
            tracker.set_usability(self.state, "novice", self.json_file(novice()))
        self.quality_done()
        self.polish_done()
        self.final_done()


if __name__ == "__main__":
    unittest.main()
