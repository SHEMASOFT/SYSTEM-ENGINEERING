"""Cross-platform MCP launcher tests.

The tracked OpenCode config and the generated MCP templates must not pin a
host-specific Python spelling. They invoke the Node launcher, which resolves
``python3``/``python`` at startup; the same entry then works on Windows, WSL,
Linux and macOS.
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import install, mcpconfig  # noqa: E402

ROOT = Path(support.REPO_ROOT)
SERVER_SCRIPTS = {
    "se-memory-server": "memory_server.py",
    "se-skill-server": "skill_server.py",
}
LAUNCHER = "SCRIPTS/se_core/mcp/launch.mjs"


class LauncherConfigurationTests(unittest.TestCase):
    def test_tracked_opencode_config_uses_the_launcher(self):
        config = mcpconfig.read_config(ROOT / "opencode.jsonc")
        servers = config["mcp"]["servers"]
        for name, script in SERVER_SCRIPTS.items():
            command = servers[name]["command"]
            self.assertEqual(command[0], "node", name)
            self.assertEqual(command[1], LAUNCHER, name)
            self.assertEqual(command[2], f"SCRIPTS/se_core/mcp/{script}", name)
            self.assertEqual(servers[name].get("cwd"), ".", name)

    def test_templates_use_the_launcher_and_keep_root_placeholders(self):
        for key, script in (
            ("memory-server", "memory_server.py"),
            ("skill-server", "skill_server.py"),
        ):
            path = ROOT / "TEMPLATES" / "mcp" / f"{key}.json.tmpl"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["command"], "node", key)
            self.assertEqual(
                data["args"],
                [
                    "${SE_ROOT}/" + LAUNCHER,
                    f"${{SE_ROOT}}/SCRIPTS/se_core/mcp/{script}",
                ],
                key,
            )

    def test_deployed_adapter_copies_use_the_launcher(self):
        for key in ("memory-server", "skill-server"):
            path = ROOT / ".opencode" / "mcp" / f"{key}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["command"], "node", key)
            self.assertIn("${SE_ROOT}/" + LAUNCHER, data["args"], key)


class LauncherRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not available")
    def test_launcher_starts_the_skill_server(self):
        spec = {
            "name": "se-skill-server",
            "command": [
                "node",
                LAUNCHER,
                "SCRIPTS/se_core/mcp/skill_server.py",
            ],
        }
        ok, detail = install.probe_mcp_server(
            spec, timeout=20, cwd=str(ROOT)
        )
        self.assertTrue(ok, detail)

    @unittest.skipUnless(shutil.which("node"), "node is not available")
    def test_se_python_override_is_honoured(self):
        spec = {
            "name": "se-skill-server",
            "command": [
                "node",
                LAUNCHER,
                "SCRIPTS/se_core/mcp/skill_server.py",
            ],
        }
        ok, detail = install.probe_mcp_server(
            spec,
            timeout=20,
            cwd=str(ROOT),
            env={"SE_PYTHON": sys.executable},
        )
        self.assertTrue(ok, detail)


if __name__ == "__main__":
    unittest.main()
