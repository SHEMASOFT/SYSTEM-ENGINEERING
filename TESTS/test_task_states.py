"""Task state model tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402

EXPECTED = ["PENDING", "READY", "IN_PROGRESS", "BLOCKED", "VERIFYING", "DONE", "CANCELLED"]


class TaskStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_json(support.REPO_ROOT / "CORE" / "tasks" / "task-states.json")

    def test_states_exact(self):
        self.assertEqual([s["id"] for s in self.model["states"]], EXPECTED)

    def test_initial_and_terminal(self):
        self.assertEqual(self.model["initial_state"], "PENDING")
        self.assertEqual(set(self.model["terminal_states"]), {"DONE", "CANCELLED"})

    def test_transitions_reference_known_states(self):
        known = {s["id"] for s in self.model["states"]}
        for transition in self.model["transitions"]:
            self.assertIn(transition["from"], known)
            self.assertIn(transition["to"], known)

    def test_blocked_requires_reason_and_resolution(self):
        self.assertTrue(self.model["blocked_condition"]["reason_required"])
        self.assertTrue(self.model["blocked_condition"]["resolution_required"])


if __name__ == "__main__":
    unittest.main()
