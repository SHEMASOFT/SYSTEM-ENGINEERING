"""AUTO-03 INTENT -> PLAN tests (SE-AUTOMATION-001F).

Hermetic: no network, temporary directories only, READ-ONLY semantics verified.
Covers:
  - ``se intent`` (CMD-0018) as an READ-ONLY se.intent/1 envelope (validation,
    normalization, determinism, no side effects, JSON error semantics).
  - ``se plan --intent/--json`` as a READ-ONLY se.plan/1 envelope: derived
    objective, topological task ordering, dependency edges, entry criteria from
    G2, exit criteria from G3, risks/uncertainties from discovery.json, a
    deterministic completion criterion, determinism and no side effects.
  - Contract validation of both envelopes against intent/plan schemas.
  - Regression: the plan command text mode (coverage) is unchanged.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.reporting import REPORT_ID  # noqa: E402
from se_core.schemas import validate  # noqa: E402

INTENT_VALID = {
    "objective": "Deliver the platform",
    "project_id": "PRJ-TEST-001",
    "context": "Config before code.",
    "scope": "IN: config model. OUT: marketplace.",
    "restrictions": ["No code changes", "Single window"],
    "success_criteria": ["Config without core changes", "Isolation enforced"],
}


def _load(out):
    return json.loads(out)


def _snapshot(project: Path) -> dict:
    return {
        str(p.relative_to(project)): p.read_bytes()
        for p in sorted(project.rglob("*"))
        if p.is_file()
    }


class IntentCommandTests(unittest.TestCase):
    def test_intent_from_file_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            code, out = support.run_cli(
                "intent", "--project", str(project), "--file", str(intent_file), "--json"
            )
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["contract"], "se.intent/1")
            self.assertEqual(data["operation"], "intent")
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(data["validation"], {"errors": []})
            self.assertEqual(data["intent"]["objective"], INTENT_VALID["objective"])
            self.assertEqual(data["intent"]["project_id"], INTENT_VALID["project_id"])
            self.assertEqual(data["intent"]["scope"], INTENT_VALID["scope"])
            self.assertEqual(
                data["intent"]["restrictions"], sorted(INTENT_VALID["restrictions"])
            )
            self.assertEqual(data["intent"]["success_criteria"], INTENT_VALID["success_criteria"])
            self.assertEqual(data["observation"]["tool"], "se")
            self.assertIn("observed_at", data["observation"])
            self.assertNotIn("\x1b", out)

    def test_intent_envelope_validates_against_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, out = support.run_cli(
                "intent", "--project", str(project), "--file", str(intent_file), "--json"
            )
            data = _load(out)
            errors = validate(data, support.schemas()["intent"])
            self.assertEqual(errors, [], errors)

    def test_intent_invalid_scope_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            bad = dict(INTENT_VALID, scope="", success_criteria=[])
            support.write_json(intent_file, bad)
            code, out = support.run_cli(
                "intent", "--project", str(project), "--file", str(intent_file), "--json"
            )
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["contract"], "se.intent/1")
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(data["validation"]["errors"])

    def test_intent_from_objective_derivation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli(
                "intent", "--project", str(project), "--objective", "OBJ-0001", "--json"
            )
            # The OBJECTIVE artifact has no SCOPE, so the derived intent is
            # incomplete against se.intent/1 -> FAIL with a scope error, while
            # the mapped fields themselves are correct.
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["contract"], "se.intent/1")
            self.assertEqual(data["status"], "FAIL")
            self.assertEqual(data["source"], {"objective_id": "OBJ-0001"})
            self.assertEqual(data["intent"]["objective"], "Objective title")
            self.assertEqual(
                data["intent"]["success_criteria"], ["Observable success criterion."]
            )
            self.assertTrue(any("scope" in e for e in data["validation"]["errors"]))

    def test_intent_requires_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("intent", "--project", str(project), "--json")
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(any("source is required" in c for c in data["conflicts"]))

    def test_intent_missing_intent_file_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli(
                "intent", "--project", str(project),
                "--file", str(Path(tmp) / "missing.json"), "--json",
            )
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")

    def test_intent_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            before = _snapshot(project)
            _, out = support.run_cli(
                "intent", "--project", str(project), "--file", str(intent_file), "--json"
            )
            self.assertEqual(_load(out)["status"], "PASS")
            self.assertEqual(_snapshot(project), before)

    def test_intent_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, first = support.run_cli(
                "intent", "--project", str(project), "--file", str(intent_file), "--json"
            )
            _, second = support.run_cli(
                "intent", "--project", str(project), "--file", str(intent_file), "--json"
            )
            a = _load(first)
            b = _load(second)
            a["observation"].pop("observed_at")
            b["observation"].pop("observed_at")
            self.assertEqual(a, b)


class PlanEnvelopeTests(unittest.TestCase):
    def test_plan_from_intent_emits_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            code, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["contract"], "se.plan/1")
            self.assertEqual(data["operation"], "plan")
            self.assertIn(data["status"], {"PASS", "WARN", "MANUAL", "FAIL"})
            self.assertEqual(data["objective"], INTENT_VALID["objective"])
            self.assertEqual(data["project_id"], INTENT_VALID["project_id"])
            self.assertEqual(data["source"]["intent_file"], str(intent_file))
            self.assertEqual(data["source"]["objective"], INTENT_VALID["objective"])
            self.assertIn("observed_at", data["observation"])
            self.assertNotIn("\x1b", out)

    def test_plan_envelope_validates_against_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            data = _load(out)
            errors = validate(data, support.schemas()["plan"])
            self.assertEqual(errors, [], errors)

    def test_plan_steps_topological_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            support.write_json(
                project / "objectives" / "OBJ-0001.json",
                support.objective(),
            )
            support.write_json(
                project / "requirements" / "REQ-0001.json",
                support.requirement(),
            )
            support.write_json(
                project / "tasks" / "TASK-0001.json",
                support.task(id="TASK-0001", status="DONE"),
            )
            support.write_json(
                project / "tasks" / "TASK-0002.json",
                support.task(id="TASK-0002", dependencies=["TASK-0001"]),
            )
            support.write_json(
                project / "tasks" / "TASK-0003.json",
                support.task(id="TASK-0003", dependencies=["TASK-0001"]),
            )
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            data = _load(out)
            steps = data["steps"]
            self.assertEqual([s["task_id"] for s in steps], ["TASK-0001", "TASK-0002", "TASK-0003"])
            self.assertEqual([s["order"] for s in steps], [1, 2, 3])
            self.assertEqual(steps[0]["dependencies"], [])
            self.assertEqual(steps[1]["dependencies"], ["TASK-0001"])
            self.assertTrue(data["dependencies"]["acyclic"])
            self.assertEqual(
                sorted(tuple(e) for e in data["dependencies"]["edges"]),
                sorted({("TASK-0001", "TASK-0002"), ("TASK-0001", "TASK-0003")}),
            )

    def test_plan_cycle_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            support.write_json(
                project / "tasks" / "TASK-0001.json",
                support.task(id="TASK-0001", dependencies=["TASK-0002"]),
            )
            support.write_json(
                project / "tasks" / "TASK-0002.json",
                support.task(id="TASK-0002", dependencies=["TASK-0001"]),
            )
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            data = _load(out)
            self.assertFalse(data["dependencies"]["acyclic"])
            self.assertEqual(
                sorted(tuple(e) for e in data["dependencies"]["edges"]),
                sorted({("TASK-0001", "TASK-0002"), ("TASK-0002", "TASK-0001")}),
            )

    def test_plan_entry_exit_criteria_from_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            data = _load(out)
            entry_ids = [c["id"] for c in data["entry_criteria"]]
            exit_ids = [c["id"] for c in data["exit_criteria"]]
            self.assertTrue(all(cid.startswith("G2.") for cid in entry_ids))
            self.assertTrue(all(cid.startswith("G3.") for cid in exit_ids))
            self.assertTrue(all(c["status"] in {"PASS", "WARN", "MANUAL", "FAIL"} for c in data["entry_criteria"]))
            self.assertTrue(all(c["status"] in {"PASS", "WARN", "MANUAL", "FAIL"} for c in data["exit_criteria"]))

    def test_plan_risks_and_uncertainties_from_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            support.write_json(
                project / "discovery.json",
                {
                    "schema_version": "1",
                    "summary": "Discovery complete.",
                    "findings": [],
                    "unknowns": [
                        {"unknown_id": "UNK-0001", "question": "Market timing", "impact": "medium"},
                        {"unknown_id": "UNK-0002", "question": "Choice of zeppelin", "impact": "low"},
                    ],
                    "assumptions": [],
                    "constraints": [],
                    "risks": [
                        {"risk_id": "RSK-0001", "statement": "Storage might blow up",
                         "impact": "high", "likelihood": "medium"},
                        {"risk_id": "RSK-0002", "statement": "Vendor lock in",
                         "impact": "medium", "likelihood": "low"},
                    ],
                    "reviewed_by": "tester",
                    "reviewed_at": "2024-01-01T00:00:00Z",
                },
            )
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            data = _load(out)
            self.assertEqual([r["id"] for r in data["risks"]], ["RSK-0001", "RSK-0002"])
            self.assertEqual([u["id"] for u in data["uncertainties"]], ["UNK-0001", "UNK-0002"])
            self.assertEqual(data["risks"][0]["statement"], "Storage might blow up")

    def test_plan_completion_criterion_contains_success_criteria(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            data = _load(out)
            self.assertIn("DONE", data["completion_criterion"])
            self.assertIn("Config without core changes", data["completion_criterion"])

    def test_plan_read_only_no_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            before = _snapshot(project)
            _, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            self.assertEqual(_load(out)["contract"], "se.plan/1")
            self.assertEqual(_snapshot(project), before)

    def test_plan_json_without_intent_uses_objective(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("plan", "--project", str(project), "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["contract"], "se.plan/1")
            self.assertEqual(data["source"]["objective_id"], "OBJ-0001")
            self.assertEqual(data["source"]["objective"], "Objective title")
            self.assertIn("canonical", data["source"])
            self.assertIsInstance(data["source"]["canonical"], list)
            self.assertTrue(data["source"]["canonical"])

    def test_plan_rejects_create_tasks_with_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            code, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file),
                "--create-tasks", "--json",
            )
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(any("--create-tasks" in c for c in data["conflicts"]))

    def test_plan_derived_status_fails_when_gates_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            code, out = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["status"], "FAIL")
            fails = [c["id"] for c in data["entry_criteria"] + data["exit_criteria"] if c["status"] == "FAIL"]
            self.assertTrue(fails)

    def test_plan_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            intent_file = Path(tmp) / "intent.json"
            support.write_json(intent_file, INTENT_VALID)
            _, first = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            _, second = support.run_cli(
                "plan", "--project", str(project), "--intent", str(intent_file), "--json"
            )
            a = _load(first)
            b = _load(second)
            a["observation"].pop("observed_at")
            b["observation"].pop("observed_at")
            self.assertEqual(a, b)

    def test_plan_text_mode_coverage_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("plan", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertNotIn("{", out.lstrip())
            self.assertIn("covered", out)


if __name__ == "__main__":
    unittest.main()