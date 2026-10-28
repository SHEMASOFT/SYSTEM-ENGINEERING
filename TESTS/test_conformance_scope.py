"""Conformance scope of `se health` (AUTO-07 / AUTO-08).

Why this file exists
--------------------
The conformance scope (CONF-01..CONF-06) shipped without a single test, and one
of its controls was wrong from the start: CONF-06 read `capability_plan.skills`
out of the adapter manifest, a key that does not exist in that schema. The plan
describes PROVIDER capabilities (context7, playwright, firecrawl, ...), not
skills, so the declared set was always empty and every project failed the check
with "In catalog but not in plan: {all 7 skills}".

These tests pin the real contract: the skills the adapter declares must be the
same skills the catalog reports as installed, and the manifest must agree with
itself (artifacts, generated_files and counts). They run the check itself, so a
control can no longer be wrong while green.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import support  # noqa: E402
from se_core import commands  # noqa: E402


def skill_artifact(name: str) -> dict:
    return {
        "type": "skill",
        "format": "markdown",
        "path": f".opencode/skills/{name}/SKILL.md",
        "description": f"Skill {name}",
    }


def catalog(*skills) -> dict:
    """skills: (name, installation_state) pairs."""
    return {
        "schema_version": "1",
        "skills": [
            {"name": name, "version": "0.1.0", "installation_state": state}
            for name, state in skills
        ],
    }


def manifest(*names: str) -> dict:
    artifacts = [skill_artifact(name) for name in names]
    return {
        "schema_version": "1",
        "adapter_id": "opencode",
        "adapter_version": "1.0.0",
        "engine_version": "0.11.0",
        "target": "opencode",
        "capabilities": {},
        "capability_plan": {"available": [], "mapping": [], "registry": "CORE/capabilities/capabilities.json"},
        "output": {
            "artifacts": artifacts,
            "generated_files": [a["path"].removeprefix(".opencode/") for a in artifacts],
        },
        "metadata": {
            "counts": {"agents": 0, "commands": 0, "policies": 0, "skills": len(names)},
            "content_hashes": {},
            "generator": "se_core.opencode",
        },
    }


class ConformanceConf06Tests(unittest.TestCase):
    """CONF-06: the catalog and the adapter must name the same skills."""

    def conf06(self, root: Path) -> dict:
        """Run the conformance checks and return the CONF-06 finding."""
        project = root / "PROJECTS" / "PROBE"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            commands.run_conformance_checks(project, root, Namespace(json=True, project="PROJECTS/PROBE"))
        envelope = json.loads(buffer.getvalue())
        findings = envelope["details"]["conformance"]["findings"]
        return next(f for f in findings if f["control"] == "CONF-06")

    def build_root(self, tmp, cats, man) -> Path:
        root = Path(tmp)
        support.write_json(root / "CATALOG" / "skills.json", cats)
        support.write_json(root / ".opencode" / "adapter-manifest.json", man)
        return root

    def test_coherent_catalog_and_adapter_passes(self):
        cats = catalog(("impl-tdd", "installed"), ("rev-adversarial", "installed"))
        man = manifest("impl-tdd", "rev-adversarial")
        with tempfile.TemporaryDirectory() as tmp:
            finding = self.conf06(self.build_root(tmp, cats, man))
        self.assertEqual(finding["status"], "PASS", finding)
        self.assertIn("2 installed skills", finding["detail"])

    def test_a_catalog_skill_the_adapter_does_not_declare_fails(self):
        cats = catalog(("impl-tdd", "installed"), ("rev-adversarial", "installed"), ("dbg-systematic", "installed"))
        man = manifest("impl-tdd", "rev-adversarial")
        with tempfile.TemporaryDirectory() as tmp:
            finding = self.conf06(self.build_root(tmp, cats, man))
        self.assertEqual(finding["status"], "FAIL", finding)
        self.assertIn("installed in the catalog but not declared", finding["detail"])
        self.assertIn("dbg-systematic", finding["detail"])

    def test_a_declared_skill_the_catalog_does_not_install_fails(self):
        cats = catalog(("impl-tdd", "installed"))
        man = manifest("impl-tdd", "dbg-systematic")
        with tempfile.TemporaryDirectory() as tmp:
            finding = self.conf06(self.build_root(tmp, cats, man))
        self.assertEqual(finding["status"], "FAIL", finding)
        self.assertIn("declared by the adapter but not installed", finding["detail"])
        self.assertIn("dbg-systematic", finding["detail"])

    def test_a_catalog_skill_that_is_not_installed_is_not_required(self):
        """Only INSTALLED skills are the adapter's responsibility."""
        cats = catalog(("impl-tdd", "installed"), ("dbg-systematic", "planned"))
        man = manifest("impl-tdd")
        with tempfile.TemporaryDirectory() as tmp:
            finding = self.conf06(self.build_root(tmp, cats, man))
        self.assertEqual(finding["status"], "PASS", finding)
        self.assertNotIn("dbg-systematic", finding["detail"])

    def test_the_manifest_must_agree_with_its_own_counts(self):
        cats = catalog(("impl-tdd", "installed"), ("rev-adversarial", "installed"))
        man = manifest("impl-tdd", "rev-adversarial")
        man["metadata"]["counts"]["skills"] = 9
        with tempfile.TemporaryDirectory() as tmp:
            finding = self.conf06(self.build_root(tmp, cats, man))
        self.assertEqual(finding["status"], "FAIL", finding)
        self.assertIn("counts 9 skills but declares 2", finding["detail"])

    def test_artifacts_and_generated_files_must_name_the_same_skills(self):
        cats = catalog(("impl-tdd", "installed"), ("rev-adversarial", "installed"))
        man = manifest("impl-tdd", "rev-adversarial")
        man["output"]["generated_files"] = ["skills/impl-tdd/SKILL.md"]
        with tempfile.TemporaryDirectory() as tmp:
            finding = self.conf06(self.build_root(tmp, cats, man))
        self.assertEqual(finding["status"], "FAIL", finding)
        self.assertIn("generated files", finding["detail"])

    def test_a_missing_catalog_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support.write_json(root / ".opencode" / "adapter-manifest.json", manifest("impl-tdd"))
            finding = self.conf06(root)
        self.assertEqual(finding["status"], "FAIL", finding)
        self.assertIn("CATALOG/skills.json not found", finding["detail"])


class RepositoryConformanceTests(unittest.TestCase):
    """The shipped tree must pass its own conformance scope."""

    def test_the_repository_passes_the_conformance_scope(self):
        """The regression that was missing: CONF-06 read a key that never existed.

        `capability_plan.skills`, so the declared set was empty and every
        project failed. Running the real scope over the real tree catches any
        control that only reads fields the schema does not have.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "probe")
            code, out = support.run_cli(
                "health", "--scope", "conformance", "--project", str(project), "--json"
            )
        self.assertEqual(code, 0, f"conformance scope failed in the shipped tree: {out[:400]}")


if __name__ == "__main__":
    unittest.main()
