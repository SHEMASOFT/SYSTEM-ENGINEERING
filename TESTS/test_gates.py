"""Gate model integrity and evaluation tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.gates import CHECKS, evaluate_gate  # noqa: E402
from se_core.paths import load_json  # noqa: E402

EXPECTED_GATES = [f"G{i}" for i in range(9)]


class GateModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_json(support.REPO_ROOT / "CORE" / "gates" / "gates.json")
        cls.lifecycle = load_json(support.REPO_ROOT / "CORE" / "lifecycle" / "lifecycle.json")

    def test_gate_ids(self):
        self.assertEqual([g["id"] for g in self.model["gates"]], EXPECTED_GATES)

    def test_every_check_is_implemented(self):
        for gate in self.model["gates"]:
            for condition in gate["conditions"]:
                self.assertIn(condition["check"], CHECKS, f"{gate['id']} {condition['id']}")

    def test_gate_states_exist(self):
        states = {s["id"] for s in self.lifecycle["states"]}
        for gate in self.model["gates"]:
            self.assertIn(gate["from_state"], states)
            self.assertIn(gate["to_state"], states)

    def test_transition_gates_match(self):
        by_id = {g["id"]: g for g in self.model["gates"]}
        for transition in self.lifecycle["transitions"]:
            for gate_id in transition["gates"]:
                gate = by_id[gate_id]
                self.assertEqual(gate["from_state"], transition["from"])
                self.assertEqual(gate["to_state"], transition["to"])


class GateEvaluationTests(unittest.TestCase):
    def test_g0_fails_without_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate_gate(Path(tmp), "G0")
            self.assertEqual(report["status"], "FAIL")

    def test_full_project_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "proj")
            for gate_id in EXPECTED_GATES:
                report = evaluate_gate(project, gate_id)
                self.assertIn(report["status"], {"PASS", "MANUAL"}, f"{gate_id}: {report}")
            # G7 is fully automated and must PASS outright.
            self.assertEqual(evaluate_gate(project, "G7")["status"], "PASS")
            # Manual gates must never auto-pass.
            self.assertEqual(evaluate_gate(project, "G5")["status"], "MANUAL")

    def test_unknown_gate_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                evaluate_gate(Path(tmp), "G99")


if __name__ == "__main__":
    unittest.main()
