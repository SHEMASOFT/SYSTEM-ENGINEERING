"""Runtime adapters beyond OpenCode: Claude Code and Codex generation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import runtimes  # noqa: E402

ROOT = support.REPO_ROOT


class ClaudeCodeAdapterTests(unittest.TestCase):
    def render(self, tmp):
        return runtimes.generate_claude_code(ROOT, Path(tmp))

    def test_tree_matches_the_runtime_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.render(tmp)
            self.assertEqual(result["status"], "PASS")
            paths = {f["path"] for f in result["files"]}
            self.assertIn(".mcp.json", paths)
            self.assertIn("CLAUDE.md", paths)
            for role in ("coordinator", "planner", "implementer"):
                self.assertIn(f".claude/agents/{role}.md", paths)
            self.assertIn(".claude/commands/plan.md", paths)
            self.assertIn(".claude/skills/impl-tdd/SKILL.md", paths)

    def test_agent_frontmatter_has_name_and_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.render(tmp)
            text = (Path(tmp) / ".claude/agents/coordinator.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\nname: coordinator\n"))
            self.assertIn("description:", text)

    def test_skills_are_byte_identical_to_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.render(tmp)
            for name in ("impl-tdd", "rev-adversarial", "visual-frontend-engineering"):
                generated = (Path(tmp) / ".claude" / "skills" / name / "SKILL.md").read_bytes()
                canonical = (ROOT / "SKILLS" / name / "SKILL.md").read_bytes()
                self.assertEqual(generated, canonical, name)

    def test_mcp_json_is_portable_and_lists_the_se_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.render(tmp)
            data = json.loads((Path(tmp) / ".mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(data["mcpServers"]),
                ["context7", "engram", "filesystem", "se-skill-server"],
            )
            text = json.dumps(data)
            # Portable by construction: no absolute host paths in the config.
            self.assertNotIn(":\\\\", text)
            self.assertNotIn("/mnt/", text)


class CodexAdapterTests(unittest.TestCase):
    def test_tree_matches_the_runtime_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = runtimes.generate_codex(ROOT, Path(tmp))
            self.assertEqual(result["status"], "PASS")
            paths = {f["path"] for f in result["files"]}
            self.assertIn("AGENTS.md", paths)
            self.assertIn(".codex/config.toml", paths)
            self.assertIn(".codex/prompts/plan.md", paths)
            self.assertIn(".codex/agents/coordinator.toml", paths)

    def test_config_toml_declares_mcp_servers_and_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtimes.generate_codex(ROOT, Path(tmp))
            config = (Path(tmp) / ".codex" / "config.toml").read_text(encoding="utf-8")
            for name in ("context7", "engram", "filesystem", "se-skill-server"):
                self.assertIn(f"[mcp_servers.{name}]", config)
            self.assertIn("[agents.coordinator]", config)
            self.assertIn("config_file = \"agents/coordinator.toml\"", config)

    def test_role_file_carries_developer_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtimes.generate_codex(ROOT, Path(tmp))
            role = (Path(tmp) / ".codex" / "agents" / "coordinator.toml").read_text(encoding="utf-8")
            self.assertIn('developer_instructions = """', role)
            self.assertIn("Orchestrate", role)  # the coordinator purpose


class AdapterInvariantsTests(unittest.TestCase):
    def test_generation_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtimes.generate_all(ROOT, Path(tmp))
            second = runtimes.generate_all(ROOT, Path(tmp))
            self.assertEqual({f["action"] for f in second["files"]}, {"unchanged"})

    def test_cli_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = support.run_cli("adapter", "claude-code", "--output", tmp, "--dry-run")
            self.assertEqual(code, 0, out)
            self.assertIn("Status: PASS", out)
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def test_cli_generates_every_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = support.run_cli("adapter", "all", "--output", tmp)
            self.assertEqual(code, 0, out)
            self.assertTrue((Path(tmp) / ".mcp.json").exists())
            self.assertTrue((Path(tmp) / ".codex" / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
