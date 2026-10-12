"""Canonical skill tests (CHECKPOINT-017).

Hermetic: no network; project bootstraps use temporary directories. The Master
System repository is only read.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.opencode.validators import audit_contracts, validate_skill  # noqa: E402
from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

CANONICAL_SKILLS = [
    "checkpoint-release",
    "dbg-systematic",
    "impl-tdd",
    "rev-adversarial",
    "verification-review",
    "visual-frontend-engineering",
    "work-mode-selection",
]

REQUIRED_SECTIONS = [
    "purpose",
    "when_to_use",
    "when_not_to_use",
    "inputs",
    "preconditions",
    "procedure",
    "evidence",
    "validation",
    "failure_modes",
    "outputs",
    "restrictions",
]


class CanonicalSkillTests(unittest.TestCase):
    def skills_root(self):
        return Path(support.REPO_ROOT) / "SKILLS"

    def test_required_skills_exist_and_validate(self):
        root = self.skills_root()
        present = sorted(p.parent.name for p in root.glob("*/SKILL.md"))
        self.assertEqual(present, CANONICAL_SKILLS)
        for name in CANONICAL_SKILLS:
            errors = validate_skill(root / name / "SKILL.md", name)
            self.assertEqual(errors, [], f"{name}: {errors}")

    def test_frontmatter_name_and_description(self):
        for name in CANONICAL_SKILLS:
            text = (self.skills_root() / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), name)
            lines = text.splitlines()
            self.assertTrue(any(l.startswith("name: ") for l in lines), f"{name}: name")
            self.assertTrue(any(l.startswith("description: ") for l in lines), f"{name}: description")
            self.assertTrue(any(l.startswith("metadata:") for l in lines), f"{name}: metadata")

    def test_required_sections_present(self):
        for name in CANONICAL_SKILLS:
            text = (self.skills_root() / name / "SKILL.md").read_text(encoding="utf-8")
            for section in REQUIRED_SECTIONS:
                self.assertIn(f"## {section}", text, f"{name}: missing ## {section}")

    def test_sidecar_contracts_valid(self):
        schemas = support.schemas()
        root = self.skills_root()
        skill_ids = set()
        for name in CANONICAL_SKILLS:
            sidecar = root / name / "SKILL.json"
            self.assertTrue(sidecar.exists(), f"{name}: missing SKILL.json")
            data = load_json(sidecar)
            errors = validate(data, schemas["skill_contract"])
            self.assertEqual(errors, [], f"{name}: {errors}")
            self.assertEqual(data["name"], name)
            self.assertEqual(data["version"], "0.1.0")
            skill_ids.add(data["skill_id"])
        self.assertEqual(len(skill_ids), len(CANONICAL_SKILLS), "skill ids must be unique")


class SkillValidatorTests(unittest.TestCase):
    def _write(self, text):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "SKILL.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_description(self):
        path = self._write("---\nname: x\nmetadata:\n  a: b\n---\n# X\n")
        self.assertIn("no description", validate_skill(path, "x")[0])

    def test_missing_metadata(self):
        path = self._write("---\nname: x\ndescription: A skill.\n---\n# X\n")
        errors = validate_skill(path, "x")
        self.assertTrue(any("no metadata" in e for e in errors))

    def test_name_must_match_folder(self):
        path = self._write(
            "---\nname: other\ndescription: A skill.\nmetadata:\n  a: b\n---\n# X\n"
        )
        errors = validate_skill(path, "expected")
        self.assertTrue(any("does not match folder" in e for e in errors))


class SkillInstallationTests(unittest.TestCase):
    def test_bootstrap_installs_selected_skills(self):
        from se_core.paths import load_json

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = support.run_cli(
                "init", str(project), "--agents", "architect",
                "--skills", ",".join(CANONICAL_SKILLS),
            )
            self.assertEqual(code, 0, out)
            for name in CANONICAL_SKILLS:
                generated = (project / ".opencode" / "skills" / name / "SKILL.md")
                self.assertTrue(generated.exists(), name)
                canonical = Path(support.REPO_ROOT) / "SKILLS" / name / "SKILL.md"
                self.assertEqual(generated.read_bytes(), canonical.read_bytes(), name)
            manifest = load_json(project / "MASTER-SYSTEM-MANIFEST.json")
            self.assertEqual(manifest["installed"]["skills"], CANONICAL_SKILLS)
            self.assertEqual(manifest["metadata"]["counts"]["skills"], len(CANONICAL_SKILLS))

    def test_unselected_skill_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = support.run_cli(
                "init", str(project), "--agents", "architect", "--skills", "checkpoint-release"
            )
            self.assertEqual(code, 0, out)
            self.assertTrue((project / ".opencode" / "skills" / "checkpoint-release").exists())
            self.assertFalse((project / ".opencode" / "skills" / "verification-review").exists())
            manifest = load_json(project / "MASTER-SYSTEM-MANIFEST.json")
            self.assertEqual(manifest["installed"]["skills"], ["checkpoint-release"])


class SkillKindTests(unittest.TestCase):
    """ARCH-ADAPT-001: optional `skill_kind` classification (knowledge/behavioral/workflow)."""

    def base_sidecar(self, **over):
        data = {
            "schema_version": "1",
            "skill_id": "SK-9999",
            "name": "example",
            "version": "0.1.0",
            "description": "Example skill.",
        }
        data.update(over)
        return data

    def test_sidecar_without_skill_kind_is_valid(self):
        errors = validate(self.base_sidecar(), support.schemas()["skill_contract"])
        self.assertEqual(errors, [], f"{errors}")

    def test_sidecar_with_valid_skill_kind(self):
        for kind in ("knowledge", "behavioral", "workflow"):
            errors = validate(
                self.base_sidecar(skill_kind=kind), support.schemas()["skill_contract"]
            )
            self.assertEqual(errors, [], f"{kind}: {errors}")

    def test_sidecar_with_invalid_skill_kind(self):
        errors = validate(
            self.base_sidecar(skill_kind="magic"), support.schemas()["skill_contract"]
        )
        self.assertNotEqual(errors, [])


class SkillIdUniquenessTests(unittest.TestCase):
    """AUTO-07: Skill IDs are unique across the corpus (rule owned by audit_contracts)."""

    TEMPLATE = "impl-tdd"

    def minimal_root(self, tmp, specs):
        """Build a minimal canon root with the requested skills only.

        ``specs`` is a list of (folder_name, skill_id).
        """
        root = Path(tmp)
        for rel in ("SCHEMAS", "AGENTS", "COMMANDS", "POLICIES"):
            shutil.copytree(Path(support.REPO_ROOT) / rel, root / rel)
        template_dir = Path(support.REPO_ROOT) / "SKILLS" / self.TEMPLATE
        template_md = (template_dir / "SKILL.md").read_text(encoding="utf-8")
        template_json = load_json(template_dir / "SKILL.json")
        for name, skill_id in specs:
            skill_dir = root / "SKILLS" / name
            skill_dir.mkdir(parents=True)
            text = template_md.replace(f"name: {self.TEMPLATE}\n", f"name: {name}\n", 1)
            assert f"name: {name}\n" in text
            (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
            sidecar = dict(template_json, name=name, skill_id=skill_id)
            (skill_dir / "SKILL.json").write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return root

    def test_duplicate_skill_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.minimal_root(tmp, [("alpha", "SK-0001"), ("beta", "SK-0001")])
            errors, _counts = audit_contracts(root, schemas=support.schemas())
            duplicates = [e for e in errors if "duplicate skill_id" in e]
            self.assertEqual(len(duplicates), 1, errors)
            self.assertIn("'alpha'", duplicates[0])
            self.assertIn("'beta'", duplicates[0])

    def test_distinct_skill_ids_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.minimal_root(tmp, [("alpha", "SK-0001"), ("beta", "SK-0002")])
            errors, counts = audit_contracts(root, schemas=support.schemas())
            self.assertEqual(errors, [], f"{errors}")
            self.assertEqual(counts["skills"], 2)

    def test_canonical_skill_ids_are_unique(self):
        errors, counts = audit_contracts(Path(support.REPO_ROOT))
        self.assertEqual(errors, [], f"{errors}")
        self.assertEqual(counts["skills"], len(CANONICAL_SKILLS))


class SkillValidatorRuleTests(unittest.TestCase):
    """AUTO-07: per-skill rules are reported once each, with the right severity."""

    def _corpus(self, tmp, text, name="alpha", sidecar=None, extra=None):
        skill_dir = Path(tmp) / "SKILLS" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
        if sidecar is not None:
            (skill_dir / "SKILL.json").write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        for rel, payload in (extra or {}).items():
            (skill_dir / rel).write_text(payload, encoding="utf-8")
        return skill_dir

    def sidecar(self, **over):
        data = {
            "schema_version": "1",
            "skill_id": "SK-0001",
            "name": "alpha",
            "version": "0.1.0",
            "description": "Alpha skill.",
        }
        data.update(over)
        return data

    def body(self, frontmatter):
        sections = "\n".join(f"## {s}\n\ntext\n" for s in REQUIRED_SECTIONS)
        return f"---\n{frontmatter}---\n# alpha\n\n{sections}"

    def test_description_over_1024_is_reported_exactly_once(self):
        long_desc = "d" * 1500
        text = self.body(f"name: alpha\ndescription: {long_desc}\nmetadata:\n  a: b\n")
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(tmp, text, sidecar=self.sidecar())
            errors = validate_skill(skill_dir / "SKILL.md", "alpha")
            limit = [e for e in errors if "exceeds 1024" in e]
            self.assertEqual(len(limit), 1, errors)

    def test_description_of_1024_chars_is_accepted(self):
        desc = "d" * 1024
        text = self.body(f"name: alpha\ndescription: {desc}\nmetadata:\n  a: b\n")
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(tmp, text, sidecar=self.sidecar())
            self.assertEqual(validate_skill(skill_dir / "SKILL.md", "alpha"), [])

    def test_invalid_skill_name_format_is_rejected(self):
        text = self.body("name: Bad_Name\ndescription: A skill.\nmetadata:\n  a: b\n")
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(tmp, text, name="Bad_Name", sidecar=self.sidecar(name="Bad_Name"))
            errors = validate_skill(skill_dir / "SKILL.md", "Bad_Name")
            self.assertTrue(any("invalid name format" in e for e in errors), errors)

    def test_missing_required_section_is_reported_once(self):
        text = self.body("name: alpha\ndescription: A skill.\nmetadata:\n  a: b\n")
        text = text.replace("## evidence\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(tmp, text, sidecar=self.sidecar())
            errors = validate_skill(skill_dir / "SKILL.md", "alpha")
            missing = [e for e in errors if "missing required section" in e]
            self.assertEqual(len(missing), 1, errors)
            self.assertIn("evidence", missing[0])

    def test_non_string_metadata_value_is_rejected(self):
        text = "---\nname: alpha\ndescription: A skill.\nmetadata:\n  count: 3\n---\n# alpha\n"
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(tmp, text, sidecar=self.sidecar())
            errors = validate_skill(skill_dir / "SKILL.md", "alpha")
            self.assertTrue(any("values must be strings" in e for e in errors), errors)

    def test_resource_entry_that_is_not_a_directory_is_rejected(self):
        text = self.body("name: alpha\ndescription: A skill.\nmetadata:\n  a: b\n")
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(
                tmp, text, sidecar=self.sidecar(), extra={"references": "not a dir\n"}
            )
            errors = validate_skill(skill_dir / "SKILL.md", "alpha")
            self.assertTrue(
                any("references exists but is not a directory" in e for e in errors), errors
            )

    def test_missing_sidecar_is_reported(self):
        text = self.body("name: alpha\ndescription: A skill.\nmetadata:\n  a: b\n")
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(tmp, text)
            errors = validate_skill(skill_dir / "SKILL.md", "alpha")
            self.assertIn("skill alpha: missing SKILL.json sidecar", errors)

    def test_unrecognized_compatibility_is_rejected(self):
        text = self.body(
            "name: alpha\ndescription: A skill.\ncompatibility: emacs\nmetadata:\n  a: b\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = self._corpus(tmp, text, sidecar=self.sidecar())
            errors = validate_skill(skill_dir / "SKILL.md", "alpha")
            self.assertTrue(any("compatibility 'emacs' not recognized" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
