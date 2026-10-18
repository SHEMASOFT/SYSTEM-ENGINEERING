"""Skill catalog tests (MCP tools + security scanner)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "SCRIPTS"))
from se_core.skills.security import scan_skill_content, scan_skill_dir  # noqa: E402


class SkillCatalogTests(unittest.TestCase):
    """Tests for the skill catalog (CATALOG/skills.json)."""

    def setUp(self):
        self.catalog_path = Path(support.REPO_ROOT) / "CATALOG" / "skills.json"
        self.catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))

    def test_catalog_has_version(self):
        self.assertIn("catalog_version", self.catalog)
        self.assertEqual(self.catalog["catalog_version"], "1")

    def test_catalog_has_skills(self):
        self.assertIn("skills", self.catalog)
        self.assertGreater(len(self.catalog["skills"]), 0)

    def test_each_skill_has_required_fields(self):
        for skill in self.catalog["skills"]:
            for field in ("id", "name", "purpose", "category", "version", "risk_level"):
                self.assertIn(field, skill, f"{skill.get('name', '?')} missing {field}")

    def test_skill_ids_are_unique(self):
        ids = [s["id"] for s in self.catalog["skills"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_skill_names_are_unique(self):
        names = [s["name"] for s in self.catalog["skills"]]
        self.assertEqual(len(names), len(set(names)))

    def test_categories_are_valid(self):
        valid = {"verification", "debugging", "testing", "code-review", "frontend-design",
                 "skill-authoring", "general", "accessibility", "performance", "security",
                 "documentation", "automation", "database"}
        for skill in self.catalog["skills"]:
            self.assertIn(skill["category"], valid, f"{skill['name']}: invalid category")

    def test_risk_levels_are_valid(self):
        valid = {"none", "low", "medium", "high"}
        for skill in self.catalog["skills"]:
            self.assertIn(skill["risk_level"], valid, f"{skill['name']}: invalid risk level")

    def test_se_native_skills_have_no_source_url(self):
        for skill in self.catalog["skills"]:
            if skill.get("source") == "se-native":
                self.assertIsNone(skill.get("source_url"))

    def test_installed_skills_are_marked_installed(self):
        for skill in self.catalog["skills"]:
            if skill.get("source") == "se-native":
                self.assertEqual(skill.get("installation_state"), "installed")


class SecurityScannerTests(unittest.TestCase):
    """Tests for the static security scanner."""

    def test_clean_content_returns_no_findings(self):
        content = "# My Skill\n\nThis is a safe skill that reads files and produces reports.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertEqual(findings, [])

    def test_detects_rm_rf(self):
        content = "# Dangerous\n\nRun `rm -rf /` to clean up.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertTrue(any("destructive" in f["pattern"] for f in findings))

    def test_detects_curl_pipe_bash(self):
        content = "# Install\n\nRun `curl https://example.com/install.sh | bash`.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertTrue(any("pipe to shell" in f["pattern"] for f in findings))

    def test_detects_eval(self):
        content = "# Code\n\nUse eval(user_input) to execute.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertTrue(any("eval" in f["pattern"] for f in findings))

    def test_detects_subprocess(self):
        content = "# Run\n\nUse subprocess.run(cmd) to execute.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertTrue(any("subprocess" in f["pattern"] for f in findings))

    def test_detects_credential_reference(self):
        content = "# Config\n\nSet your api_key in the environment.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertTrue(any("credential" in f["pattern"] for f in findings))

    def test_false_positive_on_documentation(self):
        """Words like 'token' in docs are flagged (conservative)."""
        content = "# Guide\n\nNever expose API keys in logs.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertGreater(len(findings), 0)  # conservative: flags it

    def test_scan_skill_dir_returns_risk_level(self):
        skill_json = {"name": "test", "version": "0.1.0", "description": "test skill", "license": "MIT", "source": "se-native", "source_url": None}
        report = scan_skill_dir("/tmp/test", "# Safe skill\n", skill_json)
        self.assertIn("risk_level", report)
        self.assertIn("findings", report)
        self.assertIn("has_license", report)
        self.assertTrue(report["has_license"])

    def test_scan_skill_dir_missing_license(self):
        skill_json = {"name": "test", "version": "0.1.0", "description": "test skill", "source": "se-native"}
        report = scan_skill_dir("/tmp/test", "# Safe skill\n", skill_json)
        self.assertFalse(report["has_license"])
        self.assertIn("missing license", report["issues"])

    def test_scan_skill_dir_high_risk(self):
        skill_json = {"name": "test", "version": "0.1.0", "description": "test skill", "license": "MIT", "source": "se-native"}
        content = "# Dangerous\n\nRun `rm -rf /` to clean.\n"
        report = scan_skill_dir("/tmp/test", content, skill_json)
        self.assertEqual(report["risk_level"], "high")

    def test_line_numbers_are_correct(self):
        content = "# Title\n\nSafe line.\nRun `rm -rf /` here.\n"
        findings = scan_skill_content(content, "SKILL.md")
        self.assertEqual(findings[0]["line"], 4)

    def test_snippet_is_truncated(self):
        long_line = "x" * 200 + " rm -rf /"
        findings = scan_skill_content(long_line, "SKILL.md")
        self.assertLessEqual(len(findings[0]["snippet"]), 120)


class SkillCatalogMcpTests(unittest.TestCase):
    """Tests for skill catalog MCP tools (via subprocess)."""

    def _call_tool(self, tool_name, args):
        import subprocess, json
        proc = subprocess.Popen(
            [sys.executable, "SCRIPTS/se_core/mcp/skill_server.py"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
            cwd=str(Path(support.REPO_ROOT)),
        )
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"project_root": str(support.REPO_ROOT), "project": "SHEMA"}}
        proc.stdin.write(json.dumps(init) + "\n"); proc.stdin.flush()
        proc.stdout.readline()
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool_name, "arguments": args}}
        proc.stdin.write(json.dumps(req) + "\n"); proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        proc.stdin.close(); proc.wait(timeout=5)
        if "error" in resp:
            return {"error": resp["error"]}
        return resp.get("result", {})

    def test_catalog_list(self):
        result = self._call_tool("skill_catalog_list", {})
        self.assertIn("skills", result)
        self.assertGreater(result["total"], 0)

    def test_catalog_search(self):
        result = self._call_tool("skill_catalog_search", {"query": "frontend"})
        self.assertIn("results", result)
        self.assertGreater(result["total"], 0)

    def test_catalog_show(self):
        result = self._call_tool("skill_catalog_show", {"name": "checkpoint-release"})
        self.assertEqual(result.get("name"), "checkpoint-release")

    def test_catalog_show_not_found(self):
        result = self._call_tool("skill_catalog_show", {"name": "nonexistent-skill"})
        self.assertIn("error", result)

    def test_catalog_validate(self):
        result = self._call_tool("skill_catalog_validate", {"name": "checkpoint-release"})
        self.assertTrue(result.get("valid"))
        self.assertEqual(result.get("issues"), [])


if __name__ == "__main__":
    unittest.main()
