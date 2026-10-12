"""Lifecycle model tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402

EXPECTED = [
    "DRAFT", "DISCOVERY", "PLANNING", "ACTIVE", "VERIFICATION",
    "ACCEPTANCE", "RELEASED", "OPERATING", "ARCHIVED",
]


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lifecycle = load_json(support.REPO_ROOT / "CORE" / "lifecycle" / "lifecycle.json")

    def test_states_exact(self):
        self.assertEqual([s["id"] for s in self.lifecycle["states"]], EXPECTED)

    def test_initial_and_terminal(self):
        self.assertEqual(self.lifecycle["initial_state"], "DRAFT")
        self.assertEqual(self.lifecycle["terminal_state"], "ARCHIVED")

    def test_blocked_is_not_a_state(self):
        self.assertNotIn("BLOCKED", [s["id"] for s in self.lifecycle["states"]])
        self.assertFalse(self.lifecycle["conditions"]["BLOCKED"]["is_lifecycle_state"])
        self.assertTrue(self.lifecycle["conditions"]["BLOCKED"]["reason_required"])

    def test_transitions_reference_known_states(self):
        known = {s["id"] for s in self.lifecycle["states"]}
        for transition in self.lifecycle["transitions"]:
            self.assertIn(transition["from"], known)
            self.assertIn(transition["to"], known)

    def test_gate_references_are_known(self):
        gates = {g["id"] for g in load_json(support.REPO_ROOT / "CORE" / "gates" / "gates.json")["gates"]}
        for transition in self.lifecycle["transitions"]:
            for gate in transition["gates"]:
                self.assertIn(gate, gates)


if __name__ == "__main__":
    unittest.main()
