"""Project policy tests (CHECKPOINT-016): MANAGED/EXTERNAL categories, `se init` target
hardening, no-overwrite of independent artifacts, doctor category-awareness and
`se validate` compatibility. Hermetic: temporary directories only; PROJECTS/* untouched.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.commands import _reject_infrastructure_target  # noqa: E402
from se_core.doctor import check_secrets, check_self_containment  # noqa: E402
from se_core.paths import repo_root  # noqa: E402
from se_core.projects import (  # noqa: E402
    is_independent_dir,
    project_category,
    project_skip_roots,
    resolve_init_target,
)
from se_core.schemas import validate  # noqa: E402


class CategorySchemaTests(unittest.TestCase):
    def test_metadata_category_valid(self):
        schemas = support.schemas()
        for cat in ("MANAGED", "EXTERNAL"):
            errors = validate(support.manifest(metadata={"category": cat}), schemas["project"])
            self.assertEqual(errors, [], f"{cat}: {errors}")

    def test_metadata_category_other_rejected(self):
        errors = validate(
            support.manifest(metadata={"category": "OTHER"}), support.schemas()["project"]
        )
        self.assertNotEqual(errors, [])

    def test_metadata_category_project_context(self):
        schemas = support.schemas()
        data = {
            "schema_version": "1",
            "project_id": "PRJ-TEST-001",
            "domains": ["software"],
            "master_system_version": "0.7.0",
            "metadata": {"category": "EXTERNAL"},
        }
        self.assertEqual(validate(data, schemas["project_context"]), [])
        bad = dict(data)
        bad["metadata"] = {"category": "SOMETHING"}
        self.assertNotEqual(validate(bad, schemas["project_context"]), [])


class ProjectClassificationTests(unittest.TestCase):
    def test_category_empty_dir_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(project_category(Path(tmp)))

    def test_category_manifest_default_managed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            support.write_json(d / "PROJECT.json", support.manifest())
            self.assertEqual(project_category(d), "MANAGED")

    def test_category_declared_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            support.write_json(
                d / "PROJECT.json", support.manifest(metadata={"category": "EXTERNAL"})
            )
            self.assertEqual(project_category(d), "EXTERNAL")

    def test_category_manifestless_markers_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / ".opencode").mkdir()
            self.assertEqual(project_category(d), "EXTERNAL")

    def test_is_independent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertFalse(is_independent_dir(d))
            for artifact in ("AGENTS.md", ".opencode", "opencode.json", "SDD"):
                if artifact in (".opencode", "SDD"):
                    (d / artifact).mkdir()
                else:
                    (d / artifact).write_text("x", encoding="utf-8")
                self.assertTrue(is_independent_dir(d), artifact)


class InitTargetResolutionTests(unittest.TestCase):
    def test_resolve_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, code, _ = resolve_init_target(str(root / "X"), Path.cwd(), root)
            self.assertEqual(code, 0)
            self.assertEqual(target, root / "X")

    def test_resolve_bare_under_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PROJECTS" / "ALPHA").mkdir(parents=True)
            target, code, _ = resolve_init_target("ALPHA", root, root)
            self.assertEqual(code, 0)
            self.assertEqual(target, root / "PROJECTS" / "ALPHA")

    def test_resolve_bare_missing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PROJECTS").mkdir(parents=True)
            target, code, note = resolve_init_target("MISSING", root, root)
            self.assertEqual(code, 2)
            self.assertIsNone(target)
            self.assertIn("cannot resolve", note)

    def test_resolve_bare_cwd_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PROJECTS").mkdir()
            cwd = Path(tmp) / "here"
            cwd.mkdir()
            (cwd / "EXIST").mkdir()
            target, code, _ = resolve_init_target("EXIST", cwd, root)
            self.assertEqual(code, 0)
            self.assertEqual(target, cwd / "EXIST")

    def test_resolve_relative_multi_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = Path(tmp) / "here"
            cwd.mkdir()
            target, code, _ = resolve_init_target("a/b", cwd, root)
            self.assertEqual(code, 0)
            self.assertEqual(target, cwd / "a" / "b")

    def test_reject_infrastructure_target(self):
        root = repo_root()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertTrue(_reject_infrastructure_target(root, root))
            self.assertTrue(_reject_infrastructure_target(root / "PROJECTS", root))
            with tempfile.TemporaryDirectory() as tmp:
                self.assertFalse(_reject_infrastructure_target(Path(tmp) / "p", root))


class InitNoOverwriteTests(unittest.TestCase):
    def test_init_rejects_external_by_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "ext"
            project.mkdir()
            (project / ".opencode").mkdir()
            (project / "AGENTS.md").write_text("# existing\n", encoding="utf-8")
            code, out = support.run_cli("init", str(project))
            self.assertNotEqual(code, 0)
            self.assertIn("EXTERNAL", out)
            self.assertFalse((project / "PROJECT.json").exists())
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), "# existing\n")

    def test_init_rejects_external_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "ext2"
            project.mkdir()
            support.write_json(
                project / "PROJECT.json", support.manifest(metadata={"category": "EXTERNAL"})
            )
            code, out = support.run_cli("init", str(project))
            self.assertNotEqual(code, 0)
            self.assertIn("EXTERNAL", out)

    def test_init_create_manifest_rejects_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "ext3"
            project.mkdir()
            (project / "AGENTS.md").write_text("# x\n", encoding="utf-8")
            code, out = support.run_cli(
                "init", "--dir", str(project), "--name", "Ext", "--owner", "o"
            )
            self.assertNotEqual(code, 0)
            self.assertIn("EXTERNAL", out)
            self.assertFalse((project / "PROJECT.json").exists())
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), "# x\n")

    def test_init_prints_target_and_works_on_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "fresh"
            code, out = support.run_cli("init", str(project), "--agents", "architect")
            self.assertEqual(code, 0, out)
            self.assertIn("TARGET:", out)
            self.assertTrue((project / "PROJECT.json").exists())

    def test_init_managed_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "m"
            code, _ = support.run_cli("init", str(project), "--agents", "architect")
            self.assertEqual(code, 0)
            before = (project / "AGENTS.md").read_bytes()
            code, out = support.run_cli("init", str(project))
            self.assertEqual(code, 0, out)
            self.assertEqual((project / "AGENTS.md").read_bytes(), before)


class DoctorCategoryTests(unittest.TestCase):
    def _fake_repo(self):
        root = Path(tempfile.mkdtemp())
        man = root / "PROJECTS" / "MAN"
        ext = root / "PROJECTS" / "EXT"
        man.mkdir(parents=True)
        ext.mkdir()
        support.write_json(man / "PROJECT.json", support.manifest())
        support.write_json(
            ext / "PROJECT.json", support.manifest(metadata={"category": "EXTERNAL"})
        )
        return root, man, ext

    def test_secrets_flags_managed_only(self):
        root, man, _ext = self._fake_repo()
        (man / ".env").write_text("SECRET=1\n", encoding="utf-8")
        status, detail = check_secrets(root)
        self.assertEqual(status, "FAIL", detail)

    def test_secrets_skips_external(self):
        root, _man, ext = self._fake_repo()
        (ext / ".env").write_text("SECRET=1\n", encoding="utf-8")
        status, detail = check_secrets(root)
        self.assertEqual(status, "PASS", detail)

    def test_secrets_skips_independent_manifestless(self):
        root, _man, ext = self._fake_repo()
        (ext / ".env").write_text("SECRET=1\n", encoding="utf-8")
        (ext / "PROJECT.json").unlink()
        status, detail = check_secrets(root)
        self.assertEqual(status, "PASS", detail)

    def test_self_containment_flags_managed_only(self):
        root, man, _ext = self._fake_repo()
        (man / "notes.md").write_text("servidor-ia\n", encoding="utf-8")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "WARN", detail)

    def test_self_containment_skips_external(self):
        root, _man, ext = self._fake_repo()
        (ext / "notes.md").write_text("servidor-ia\n", encoding="utf-8")
        status, detail = check_self_containment(root)
        self.assertEqual(status, "PASS", detail)

    def test_project_skip_roots(self):
        root, man, ext = self._fake_repo()
        skips = {p.name for p in project_skip_roots(root)}
        self.assertEqual(skips, {"EXT"})


class ValidateCompatibilityTests(unittest.TestCase):
    def test_validate_external_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "ext"
            project.mkdir()
            (project / ".opencode").mkdir()
            (project / "AGENTS.md").write_text("# x\n", encoding="utf-8")
            code, out = support.run_cli("validate", "--project", str(project))
            self.assertEqual(code, 0, out)
            self.assertIn("EXTERNAL", out)

    def test_validate_managed_missing_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "m"
            project.mkdir()
            code, out = support.run_cli("validate", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("no PROJECT.json", out)


if __name__ == "__main__":
    unittest.main()