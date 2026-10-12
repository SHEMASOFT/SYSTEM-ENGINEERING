"""Project bootstrap tests (CHECKPOINT-005): `se init <project>`.

Hermetic: every target project lives in a temporary directory; the Master System
repository is only read. Real projects (PROJECTS/*) are never touched.
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.doctor import run_doctor  # noqa: E402
from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

GENERATED_ROOT = {"AGENTS.md", "adapter-manifest.json", "MASTER-SYSTEM-MANIFEST.json"}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProjectBootstrapTests(unittest.TestCase):
    def schemas(self):
        return support.schemas()

    def _bootstrap(self, root, *extra):
        return support.run_cli("init", str(root), *extra)

    def test_empty_project_can_be_initialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "fresh"
            code, out = self._bootstrap(project, "--agents", "architect")
            self.assertEqual(code, 0, out)
            self.assertIn("Status: PASS", out)
            self.assertTrue((project / "PROJECT.json").exists())
            self.assertTrue((project / "AGENTS.md").exists())
            self.assertTrue((project / "adapter-manifest.json").exists())
            self.assertTrue((project / "MASTER-SYSTEM-MANIFEST.json").exists())
            self.assertTrue((project / ".opencode" / "agents" / "architect.md").exists())
            self.assertTrue((project / ".opencode" / "commands" / "doctor.md").exists())
            proj = load_json(project / "PROJECT.json")
            self.assertEqual(validate(proj, self.schemas()["project"]), [])
            self.assertEqual(validate(proj, self.schemas()["project_context"]), [])

    def test_existing_project_not_destroyed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "existing"
            code, _ = support.run_cli(
                "init", "--dir", str(project), "--name", "Existing", "--owner", "alice"
            )
            self.assertEqual(code, 0)
            (project / "notes").mkdir(exist_ok=True)
            stray = project / "notes" / "keep.txt"
            stray.write_text("user file\n", encoding="utf-8")
            (project / "custom.md").write_text("# Custom\n", encoding="utf-8")
            manifest = load_json(project / "PROJECT.json")
            manifest.setdefault("required_agents", []).append("architect")
            manifest.setdefault("inherited_skills", [])
            support.write_json(project / "PROJECT.json", manifest)
            project_json_before = (project / "PROJECT.json").read_bytes()

            code, out = self._bootstrap(project)
            self.assertEqual(code, 0, out)
            self.assertEqual((project / "PROJECT.json").read_bytes(), project_json_before)
            self.assertEqual(stray.read_text(encoding="utf-8"), "user file\n")
            self.assertEqual((project / "custom.md").read_text(encoding="utf-8"), "# Custom\n")
            self.assertTrue((project / "discovery.json").exists())
            self.assertTrue((project / ".gitignore").exists())

    def test_generates_correct_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = self._bootstrap(project, "--agents", "architect,reviewer,security")
            self.assertEqual(code, 0, out)
            for role in ("architect", "reviewer", "security"):
                self.assertTrue((project / ".opencode" / "agents" / f"{role}.md").exists())
            agents_doc = (project / "AGENTS.md").read_text(encoding="utf-8")
            for role in ("architect", "reviewer", "security"):
                self.assertIn(f"**{role}**", agents_doc)
            opencode = load_json(project / "adapter-manifest.json")
            agent_paths = [
                a["path"] for a in opencode["output"]["artifacts"] if a["type"] == "agent"
            ]
            self.assertEqual(
                sorted(agent_paths),
                sorted([
                    ".opencode/agents/architect.md",
                    ".opencode/agents/reviewer.md",
                    ".opencode/agents/security.md",
                ]),
            )

    def test_does_not_copy_unrequested_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = self._bootstrap(project, "--agents", "architect")
            self.assertEqual(code, 0, out)
            agent_files = sorted(p.name for p in (project / ".opencode" / "agents").glob("*.md"))
            self.assertEqual(agent_files, ["architect.md"])
            install = load_json(project / "MASTER-SYSTEM-MANIFEST.json")
            self.assertEqual(install["installed"]["agents"], ["architect"])
            self.assertEqual(install["metadata"]["counts"]["agents"], 1)

    def test_hashes_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = self._bootstrap(project, "--agents", "architect,security")
            self.assertEqual(code, 0, out)
            opencode = load_json(project / "adapter-manifest.json")
            for rel, declared in opencode["metadata"]["content_hashes"].items():
                self.assertEqual(file_sha256(project / ".opencode" / rel), declared, rel)
            install = load_json(project / "MASTER-SYSTEM-MANIFEST.json")
            for rel, declared in install["files"].items():
                self.assertEqual(file_sha256(project / rel), declared, rel)
            self.assertEqual(validate(install, self.schemas()["installation_manifest"]), [])

    def test_doctor_after_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = self._bootstrap(project, "--agents", "architect")
            self.assertEqual(code, 0, out)
            code, out = support.run_cli("validate", "--project", str(project))
            self.assertEqual(code, 0, out)
            report = run_doctor(support.REPO_ROOT)
            by_id = {r["id"]: r for r in report["results"]}
            for check in ("contracts", "adapter", "manifests"):
                self.assertEqual(by_id[check]["status"], "PASS", check)
            self.assertEqual(by_id["configuration"]["status"], "PASS")

    def test_bootstrap_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, first = self._bootstrap(project, "--agents", "architect")
            self.assertEqual(code, 0, first)
            before = {
                p.relative_to(project).as_posix(): p.read_bytes()
                for p in project.rglob("*")
                if p.is_file()
            }
            code, second = self._bootstrap(project)
            self.assertEqual(code, 0, second)
            self.assertIn("Wrote 0 file(s)", second)
            after = {
                p.relative_to(project).as_posix(): p.read_bytes()
                for p in project.rglob("*")
                if p.is_file()
            }
            self.assertEqual(before, after)

    def test_distributed_at_version_reflects_current_master(self):
        from se_core.paths import load_json as _load_json

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, _ = self._bootstrap(project, "--agents", "architect")
            self.assertEqual(code, 0)
            master = _load_json(support.REPO_ROOT / "SYSTEM.json")["master_system_version"]
            install = load_json(project / "MASTER-SYSTEM-MANIFEST.json")
            self.assertEqual(install["metadata"]["distributed_at_version"], master)
            self.assertEqual(install["master_system_version"], master)
            self.assertEqual(install["project_context"]["master_system_version"], master)

    def test_bootstrap_reconciles_stale_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, _ = support.run_cli(
                "init", "--dir", str(project), "--name", "P", "--owner", "o"
            )
            self.assertEqual(code, 0)
            manifest = load_json(project / "PROJECT.json")
            manifest["master_system_version"] = "0.1.0"
            support.write_json(project / "PROJECT.json", manifest)

            code, out = self._bootstrap(project)
            self.assertEqual(code, 0, out)
            self.assertIn("VERSION ALIGNMENT", out)

            master = load_json(support.REPO_ROOT / "SYSTEM.json")["master_system_version"]
            aligned = load_json(project / "PROJECT.json")
            self.assertEqual(aligned["master_system_version"], master)
            migrations = aligned["metadata"]["migrations"]
            latest = migrations[-1]
            self.assertEqual(latest["from_master_system_version"], "0.1.0")
            self.assertEqual(latest["to_master_system_version"], master)
            self.assertEqual(latest["by"], "o")

            install = load_json(project / "MASTER-SYSTEM-MANIFEST.json")
            self.assertEqual(install["metadata"]["distributed_at_version"], master)
            self.assertEqual(install["project_context"]["master_system_version"], master)

            before = (project / "PROJECT.json").read_bytes()
            code, again = self._bootstrap(project)
            self.assertEqual(code, 0, again)
            self.assertIn("Wrote 0 file(s)", again)
            self.assertEqual((project / "PROJECT.json").read_bytes(), before)

    def test_validate_reports_stale_floor_without_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, _ = support.run_cli(
                "init", "--dir", str(project), "--name", "P", "--owner", "o"
            )
            self.assertEqual(code, 0)
            manifest = load_json(project / "PROJECT.json")
            manifest["master_system_version"] = "0.1.0"
            support.write_json(project / "PROJECT.json", manifest)
            before = (project / "PROJECT.json").read_bytes()

            code, out = support.run_cli("validate", "--project", str(project))
            self.assertEqual(code, 1, out)
            self.assertIn("VERSION OUT OF DATE", out)
            self.assertEqual((project / "PROJECT.json").read_bytes(), before)

    def test_validate_passes_again_after_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, _ = support.run_cli(
                "init", "--dir", str(project), "--name", "P", "--owner", "o"
            )
            self.assertEqual(code, 0)
            manifest = load_json(project / "PROJECT.json")
            manifest["master_system_version"] = "0.1.0"
            support.write_json(project / "PROJECT.json", manifest)
            code, _ = self._bootstrap(project)
            self.assertEqual(code, 0)
            code, out = support.run_cli("validate", "--project", str(project))
            self.assertEqual(code, 0, out)

    def test_unknown_agent_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = self._bootstrap(project, "--agents", "bogus")
            self.assertEqual(code, 1, out)
            self.assertIn("unknown agent", out.lower())
            self.assertFalse((project / "PROJECT.json").exists())
            self.assertFalse(list(project.rglob("*.md")))

    def test_unknown_skill_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, out = self._bootstrap(project, "--agents", "architect", "--skills", "bogus")
            self.assertEqual(code, 1, out)
            self.assertIn("unknown skill", out.lower())

    def test_invalid_project_context_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            project.mkdir(exist_ok=True)
            support.write_json(project / "PROJECT.json", {
                "schema_version": "1",
                "project_id": "nope",
                "name": "Broken",
                "owner": "o",
                "domains": ["security"],
                "criticality": "unknown",
                "lifecycle_state": "DRAFT",
                "version": "0.1.0",
                "created_at": support.TS,
                "updated_at": support.TS,
                "master_system_version": "0.7.0",
            })
            code, out = self._bootstrap(project)
            self.assertEqual(code, 1, out)
            self.assertIn("does not conform", out)

    def test_no_agents_installed_without_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            code, _ = support.run_cli(
                "init", "--dir", str(project), "--name", "NoAgents", "--owner", "o"
            )
            self.assertEqual(code, 0)
            code, out = self._bootstrap(project)
            self.assertEqual(code, 0, out)
            install = load_json(project / "MASTER-SYSTEM-MANIFEST.json")
            self.assertEqual(install["installed"]["agents"], [])
            self.assertIn("capabilities", install["installed"]["commands"])
            self.assertEqual(
                list((project / ".opencode" / "agents").glob("*.md")), []
            )


if __name__ == "__main__":
    unittest.main()