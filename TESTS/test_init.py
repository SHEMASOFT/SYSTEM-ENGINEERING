"""`se init` tests: seeding and idempotency."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402


def init(root, name="Demo"):
    return support.run_cli("init", "--dir", str(root), "--name", name, "--owner", "owner")


class InitTests(unittest.TestCase):
    def test_new_project_seeds_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = init(project)
            self.assertEqual(code, 0, out)
            self.assertTrue((project / "PROJECT.json").exists())
            self.assertTrue((project / ".gitignore").exists())
            self.assertTrue((project / "discovery.json").exists())
            discovery = load_json(project / "discovery.json")
            self.assertEqual(validate(discovery, support.schemas()["discovery"]), [])

    def test_existing_manifest_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init(project)
            manifest = load_json(project / "PROJECT.json")
            manifest["name"] = "Renamed"
            support.write_json(project / "PROJECT.json", manifest)

            code, out = init(project)
            self.assertEqual(code, 0, out)
            self.assertIn("already exists; keeping it", out)
            self.assertEqual(load_json(project / "PROJECT.json")["name"], "Renamed")

    def test_existing_seed_files_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            init(project)
            (project / ".gitignore").write_text("# custom\n", encoding="utf-8")
            support.write_json(project / "discovery.json", {
                "schema_version": "1",
                "summary": "Custom discovery.",
                "findings": [], "unknowns": [], "assumptions": [], "constraints": [], "risks": [],
                "reviewed_by": "", "reviewed_at": None,
            })

            code, out = init(project)
            self.assertEqual(code, 0, out)
            self.assertEqual((project / ".gitignore").read_text(encoding="utf-8"), "# custom\n")
            self.assertEqual(load_json(project / "discovery.json")["summary"], "Custom discovery.")

    def test_repeated_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            first_code, _ = init(project)
            second_code, out = init(project)
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0, out)
            self.assertEqual(load_json(project / "PROJECT.json")["lifecycle_state"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
