"""Agent definition tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

EXPECTED_AGENTS = {
    "coordinator", "explorer", "analyst", "architect", "planner", "implementer",
    "tester", "reviewer", "security", "documentation", "devops", "visual",
}


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()
        cls.files = sorted((support.REPO_ROOT / "AGENTS").glob("*/agent.json"))
        cls.agents = {path.parent.name: load_json(path) for path in cls.files}

    def test_all_agents_present(self):
        self.assertEqual(set(self.agents), EXPECTED_AGENTS)

    def test_agents_validate_against_schema(self):
        for name, agent in self.agents.items():
            errors = validate(agent, self.schemas["agent"])
            self.assertEqual(errors, [], f"{name}: {errors}")

    def test_directory_matches_name(self):
        for name, agent in self.agents.items():
            self.assertEqual(agent["name"], name)

    def test_no_agent_has_destructive_permission(self):
        for name, agent in self.agents.items():
            self.assertNotIn("DESTRUCTIVE", agent["permissions"], name)

    def test_permissions_are_from_the_model(self):
        model = {p["id"] for p in load_json(support.REPO_ROOT / "CORE" / "policies" / "permissions.json")["permissions"]}
        for name, agent in self.agents.items():
            for permission in agent["permissions"]:
                self.assertIn(permission, model, f"{name}: {permission}")

    def test_agents_declare_verification(self):
        for name, agent in self.agents.items():
            self.assertTrue(agent["verification_requirements"], name)


if __name__ == "__main__":
    unittest.main()
