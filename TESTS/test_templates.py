"""Template and ADR artifact validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

TEMPLATE_SCHEMA = {
    "PROJECT.template.json": "project",
    "objective.template.json": "objective",
    "requirement.template.json": "requirement",
    "task.template.json": "task",
    "artifact.template.json": "artifact",
    "evidence.template.json": "evidence",
    "acceptance.template.json": "acceptance",
    "decision.template.json": "decision",
    "release.template.json": "release",
    "discovery.template.json": "discovery",
}


class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_templates_match_their_schemas(self):
        for filename, schema_name in TEMPLATE_SCHEMA.items():
            path = support.REPO_ROOT / "TEMPLATES" / filename
            self.assertTrue(path.exists(), filename)
            errors = validate(load_json(path), self.schemas[schema_name])
            self.assertEqual(errors, [], f"{filename}: {errors}")

    def test_skill_templates_present_and_wired(self):
        root = support.REPO_ROOT / "TEMPLATES" / "skill"
        self.assertTrue((root / "SKILL.md.template").exists())
        self.assertTrue((root / "SKILL.json.template").exists())
        guide = (support.REPO_ROOT / "DOCS" / "reference" / "skills" / "SKILL_AUTHORING.md").read_text(encoding="utf-8")
        self.assertIn("REQUIRED_SECTIONS", guide)
        md_template = (root / "SKILL.md.template").read_text(encoding="utf-8")
        for section in ("purpose", "when_to_use", "when_not_to_use", "inputs",
                        "preconditions", "procedure", "evidence", "validation",
                        "failure_modes", "outputs", "restrictions"):
            self.assertIn(f"## {section}", md_template)

    def test_convention_examples_present(self):
        conventions = [
            "convention.spec.delta.example.md",
            "convention.spec.write.example.md",
            "convention.rev.code_review.example.json",
            "convention.conv.convergence.example.md",
            "convention.plan.roles.example.json",
            "convention.plan.verify.example.json",
            "convention.arch.impact.example.md",
            "convention.impl.subagent.example.md",
            "convention.research.directed.example.md",
        ]
        for name in conventions:
            self.assertTrue((support.REPO_ROOT / "TEMPLATES" / name).exists(), name)

    def test_adrs_are_valid_decision_artifacts(self):
        adrs = sorted((support.REPO_ROOT / "DOCS" / "adr").glob("ADR-*.json"))
        self.assertGreaterEqual(len(adrs), 1)
        for path in adrs:
            errors = validate(load_json(path), self.schemas["decision"])
            self.assertEqual(errors, [], f"{path.name}: {errors}")


if __name__ == "__main__":
    unittest.main()
