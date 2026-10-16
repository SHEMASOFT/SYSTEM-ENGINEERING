"""Contract layer migration tests (CHECKPOINT-003, ADR-0020).

Verifies the corpus (agents + commands) validates against the canonical SCHEMAS
contract layer, carries the canonical vocabulary, stays backward-compatible with
the legacy agent schema, and that SCHEMAS/index.json points at the canonical
agent contract.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

EXPECTED_AGENTS = {
    "shema-ai-coordinador", "explorer", "analyst", "architect", "planner", "implementer",
    "tester", "reviewer", "security", "documentation", "devops", "visual",
}
EXPECTED_COMMANDS = {
    "init", "explore", "new", "update", "transition", "plan", "implement",
    "verify", "review", "release", "doctor", "validate", "gate", "capabilities",
    "context", "health", "auto", "intent", "handoff", "archive", "restore",
    "execute", "observe", "orchestrate",
}
INTENTS = {"CREATE", "READ", "MUTATE", "CONTROL", "ANALYZE", "DEPLOY", "REPORT", "IMPLEMENT"}
RISKS = {"low", "medium", "high", "critical"}


class ContractMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()
        index = load_json(support.REPO_ROOT / "SCHEMAS" / "index.json")
        cls.index = index["schemas"]
        cls.files = sorted((support.REPO_ROOT / "AGENTS").glob("*/agent.json"))
        cls.agents = {path.parent.name: load_json(path) for path in cls.files}
        cls.the_agents = list(cls.agents.values())
        cls.commands = load_json(support.REPO_ROOT / "COMMANDS" / "commands.json")["commands"]
        cls.command_by_name = {c["name"]: c for c in cls.commands}

    # --- agents ----------------------------------------------------------

    def test_all_agents_present(self):
        self.assertEqual(set(self.agents), EXPECTED_AGENTS)

    def test_agents_validate_against_canonical_contract(self):
        for name, agent in self.agents.items():
            errors = validate(agent, self.schemas["agent"])
            self.assertEqual(errors, [], f"{name}: {errors}")

    def test_agents_carry_contract_vocabulary(self):
        for name, agent in self.agents.items():
            self.assertRegex(agent["id"], r"^AG-\d{4}$", name)
            self.assertRegex(agent["version"], r"^\d+\.\d+\.\d+$", name)
            self.assertEqual(agent["role"], agent["name"], name)
            self.assertTrue(agent["description"], name)
            self.assertIsInstance(agent["capabilities"], list)
            self.assertTrue(agent["capabilities"], name)
            self.assertEqual(agent["lifecycle"]["status"], "ACTIVE", name)
            self.assertIn("since", agent["lifecycle"], name)

    def test_agent_ids_are_unique(self):
        ids = [a["id"] for a in self.the_agents]
        self.assertEqual(len(ids), len(set(ids)))

    def test_agents_still_validate_against_legacy_schema(self):
        legacy = load_json(support.REPO_ROOT / "AGENTS" / "_contract" / "agent.schema.json")
        for name, agent in self.agents.items():
            errors = validate(agent, legacy)
            self.assertEqual(errors, [], f"{name}: {errors}")

    def test_index_agent_points_at_canonical_schema(self):
        self.assertEqual(self.index["agent"], "SCHEMAS/agent-contract.schema.json")

    # --- commands --------------------------------------------------------

    def test_all_commands_present(self):
        self.assertEqual({c["name"] for c in self.commands}, EXPECTED_COMMANDS)

    def test_commands_validate_against_command_contract(self):
        commands_file = load_json(support.REPO_ROOT / "COMMANDS" / "commands.json")
        errors = validate(commands_file, self.schemas["command_contract"])
        self.assertEqual(errors, [], f"{errors}")

    def test_commands_carry_contract_vocabulary(self):
        for c in self.commands:
            self.assertRegex(c["id"], r"^CMD-\d{4}$", c["name"])
            self.assertRegex(c["version"], r"^\d+\.\d+\.\d+$", c["name"])
            self.assertTrue(c["description"], c["name"])
            self.assertIn(c["agent"], EXPECTED_AGENTS, c["name"])
            self.assertIn(c["execution_intent"], INTENTS, c["name"])
            self.assertIn(c["risk_level"], RISKS, c["name"])
            self.assertTrue(c["permissions"], c["name"])
            self.assertIsInstance(c["arguments"], list)
            for arg in c["arguments"]:
                self.assertIn("name", arg, c["name"])
                self.assertIn("type", arg, c["name"])
                self.assertIn("required", arg, c["name"])
            self.assertEqual(c["primary_agent"], c["agent"], c["name"])

    def test_command_ids_are_unique(self):
        ids = [c["id"] for c in self.commands]
        self.assertEqual(len(ids), len(set(ids)))

    def test_command_permissions_subset_of_assigned_agent(self):
        for c in self.commands:
            granted = set(self.agents[c["agent"]]["permissions"])
            self.assertTrue(
                set(c["permissions"]).issubset(granted),
                f"{c['name']} requires {c['permissions']} but {c['agent']} grants {sorted(granted)}",
            )

    # --- ADR -------------------------------------------------------------

    def test_adr_0020_valid_against_decision_schema(self):
        adr = load_json(support.REPO_ROOT / "DOCS" / "adr" / "ADR-0020-contract-layer.json")
        errors = validate(adr, self.schemas["decision"])
        self.assertEqual(errors, [], f"{errors}")
        self.assertEqual(adr["status"], "ACCEPTED")


if __name__ == "__main__":
    unittest.main()