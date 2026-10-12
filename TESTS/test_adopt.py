"""`se adopt`: the additive integration path for existing/advanced projects.

`se init` refuses directories that already carry independent-project artifacts.
Adoption is the dedicated path for those; these tests pin its safety contract:
it writes a MANAGED manifest and the empty workspace directories, and never
touches what the project already had.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.artifacts import WORKSPACE_DIRS  # noqa: E402
from se_core.paths import load_json  # noqa: E402
from se_core.projects import project_category  # noqa: E402
from se_core.schemas import validate  # noqa: E402


def make_advanced_project(root: Path) -> Path:
    """An 'advanced' project: independent artifacts present, no PROJECT.json."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# Existing agents\n", encoding="utf-8")
    (root / ".opencode").mkdir()
    (root / ".opencode" / "config.json").write_text('{"keep": true}\n', encoding="utf-8")
    (root / "opencode.json").write_text('{"mcp": {}}\n', encoding="utf-8")
    (root / "SDD").mkdir()
    (root / "SDD" / "design.md").write_text("# design\n", encoding="utf-8")
    return root


class AdoptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_adopts_an_independent_project_additively(self):
        project = make_advanced_project(self.tmp / "Legacy")
        agents_before = (project / "AGENTS.md").read_bytes()
        opencode_before = {
            p.relative_to(project).as_posix(): p.read_bytes()
            for p in (project / ".opencode").rglob("*")
            if p.is_file()
        }

        code, out = support.run_cli(
            "adopt", str(project), "--owner", "alice", "--scale", "large", "--risk", "high"
        )
        self.assertEqual(code, 0, out)

        manifest = load_json(project / "PROJECT.json")
        self.assertEqual(validate(manifest, support.schemas()["project"]), [])
        self.assertEqual(manifest["source"], "se adopt")
        self.assertEqual(manifest["lifecycle_state"], "DISCOVERY")
        self.assertEqual(manifest["owner"], "alice")
        self.assertEqual(manifest["metadata"]["category"], "MANAGED")
        self.assertEqual(manifest["metadata"]["adoption"]["adopted_from"], "EXTERNAL")
        self.assertEqual(manifest["profiles"]["work"], {"type": "brownfield", "scale": "large", "risk": "high"})
        self.assertEqual(project_category(project), "MANAGED")

        for directory in WORKSPACE_DIRS:
            self.assertTrue((project / directory).is_dir(), directory)

        # Nothing the project already had was rewritten.
        self.assertEqual((project / "AGENTS.md").read_bytes(), agents_before)
        self.assertEqual(
            {
                p.relative_to(project).as_posix(): p.read_bytes()
                for p in (project / ".opencode").rglob("*")
                if p.is_file()
            },
            opencode_before,
        )

    def test_dry_run_writes_nothing(self):
        project = make_advanced_project(self.tmp / "Legacy")
        code, out = support.run_cli("adopt", str(project), "--owner", "alice", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertFalse((project / "PROJECT.json").exists())
        self.assertEqual(
            sorted(p.name for p in project.iterdir()),
            sorted([".opencode", "AGENTS.md", "opencode.json", "SDD"]),
        )
        self.assertEqual(project_category(project), "EXTERNAL")

    def test_refuses_a_managed_project(self):
        project = self.tmp / "Managed"
        project.mkdir()
        (project / "PROJECT.json").write_text("{}", encoding="utf-8")
        code, out = support.run_cli("adopt", str(project), "--owner", "alice")
        self.assertEqual(code, 1)
        self.assertIn("already has PROJECT.json", out)

    def test_refuses_the_master_repo(self):
        code, out = support.run_cli("adopt", str(support.REPO_ROOT), "--owner", "alice")
        self.assertEqual(code, 1)
        self.assertIn("refusing to initialize SYSTEM-ENGINEERING infrastructure", out)

    def test_requires_owner(self):
        project = make_advanced_project(self.tmp / "Legacy")
        code, out = support.run_cli("adopt", str(project))
        self.assertEqual(code, 1)
        self.assertIn("--owner is required", out)
        self.assertFalse((project / "PROJECT.json").exists())

    def test_refuses_a_missing_directory(self):
        code, out = support.run_cli("adopt", str(self.tmp / "nope"), "--owner", "alice")
        self.assertEqual(code, 1)
        self.assertIn("not an existing directory", out)

    def test_json_envelope(self):
        project = make_advanced_project(self.tmp / "Legacy")
        code, out = support.run_cli("adopt", str(project), "--owner", "alice", "--json")
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        self.assertEqual(data["report"], "se.report/1")
        self.assertEqual(data["operation"], "adopt")
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(data["provenance"]["category"], "MANAGED")
        self.assertEqual(data["provenance"]["adopted_from"], "EXTERNAL")
        self.assertTrue(data["details"]["preserved"])

    def test_adopted_project_passes_validate(self):
        project = make_advanced_project(self.tmp / "Legacy")
        self.assertEqual(support.run_cli("adopt", str(project), "--owner", "alice")[0], 0)
        code, out = support.run_cli("validate", "--project", str(project))
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
