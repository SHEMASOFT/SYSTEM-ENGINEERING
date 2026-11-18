"""Surgical model-config tests (opencode.jsonc).

The write path must edit only the model keys: comments, blank lines, key order,
indentation and trailing commas of every other region survive byte for byte.
"""

from __future__ import annotations

import difflib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401

from se_core.model_tui.config import (  # noqa: E402
    AgentModelOverride,
    load_model_config,
    save_model_config,
)

GLOBAL = "openai/gpt-4o"
NEW_GLOBAL = "anthropic/claude-sonnet-5-5"

CONFIG = """{
  // runtime settings
  "$schema": "https://opencode.ai/config.json",
  "default_agent": "shema-ai-coordinador", // the coordinator
  "mcp": {
    "servers": {
      "context7": {
        "type": "local",
        "command": ["npx", "-y", "@upstash/context7-mcp@4.4.0"]
      }
    }
  },
  "model": "openai/gpt-4o"
}
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _changed_lines(before: str, after: str) -> list[str]:
    """Return the added/removed lines of a unified diff (no hunk headers)."""
    return [
        line
        for line in difflib.unified_diff(
            before.splitlines(), after.splitlines(), lineterm="", n=0
        )
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


class SurgicalSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / "opencode.jsonc"

    # 1. Comments and formatting survive a global model change.
    def test_global_model_change_preserves_comments_and_formatting(self) -> None:
        _write(self.path, CONFIG)

        save_model_config(self.root, NEW_GLOBAL, {})

        after = self.path.read_text(encoding="utf-8")
        self.assertIn("// runtime settings", after)
        self.assertIn("// the coordinator", after)
        self.assertEqual(after, CONFIG.replace(GLOBAL, NEW_GLOBAL))
        self.assertEqual(_changed_lines(CONFIG, after), [
            '-  "model": "openai/gpt-4o"',
            '+  "model": "anthropic/claude-sonnet-5-5"',
        ])

    def test_trailing_comma_survives_global_change(self) -> None:
        original = '{\n  // settings\n  "model": "openai/gpt-4o",\n}\n'
        _write(self.path, original)

        save_model_config(self.root, NEW_GLOBAL, {})

        self.assertEqual(
            self.path.read_text(encoding="utf-8"),
            original.replace(GLOBAL, NEW_GLOBAL),
        )

    # 2. Comments survive adding an override.
    def test_adding_override_preserves_comments(self) -> None:
        _write(self.path, CONFIG)

        save_model_config(
            self.root,
            GLOBAL,
            {
                "reviewer": AgentModelOverride(
                    provider="anthropic", model="claude-sonnet-5-5", variant="high"
                )
            },
        )

        after = self.path.read_text(encoding="utf-8")
        self.assertIn("// runtime settings", after)
        self.assertIn("// the coordinator", after)
        for line in CONFIG.splitlines():
            if line.strip() == "}":
                continue
            self.assertIn(line, after)
        loaded = load_model_config(self.root)
        self.assertEqual(loaded.global_model, GLOBAL)
        override = loaded.agent_overrides["reviewer"]
        self.assertEqual(override.provider, "anthropic")
        self.assertEqual(override.model, "claude-sonnet-5-5")
        self.assertEqual(override.variant, "high")

    # 3. Removing an override restores inheritance and restores every byte.
    def test_removing_override_restores_inheritance_and_bytes(self) -> None:
        _write(self.path, CONFIG)
        original = self.path.read_bytes()

        save_model_config(
            self.root,
            GLOBAL,
            {"reviewer": AgentModelOverride(provider="anthropic", model="claude-x")},
        )
        self.assertIn("anthropic", self.path.read_text(encoding="utf-8"))

        save_model_config(self.root, GLOBAL, {})

        self.assertEqual(load_model_config(self.root).agent_overrides, {})
        self.assertEqual(load_model_config(self.root).global_model, GLOBAL)
        self.assertEqual(self.path.read_bytes(), original)

    def test_clearing_override_keeps_other_agent_settings(self) -> None:
        original = """{
  "model": "openai/gpt-4o",
  "agents": {
    "reviewer": {
      "description": "Reviews changes", // keep this note
      "temperature": 0.2,
      "model": {
        "providerID": "anthropic",
        "model": "claude-x"
      }
    }
  }
}
"""
        _write(self.path, original)

        save_model_config(self.root, GLOBAL, {"reviewer": None})

        after = self.path.read_text(encoding="utf-8")
        self.assertIn('"description": "Reviews changes", // keep this note', after)
        self.assertIn('"temperature": 0.2', after)
        self.assertNotIn("claude-x", after)
        self.assertEqual(load_model_config(self.root).agent_overrides, {})

    def test_setting_override_keeps_unrelated_agent_keys(self) -> None:
        original = """{
  "model": "openai/gpt-4o",
  "agents": {
    "reviewer": {
      "description": "Reviews changes",
      "temperature": 0.2
    }
  }
}
"""
        _write(self.path, original)

        save_model_config(
            self.root,
            GLOBAL,
            {"reviewer": AgentModelOverride(provider="anthropic", model="claude-x")},
        )

        after = self.path.read_text(encoding="utf-8")
        self.assertIn('"description": "Reviews changes"', after)
        self.assertIn('"temperature": 0.2', after)
        loaded = load_model_config(self.root)
        self.assertEqual(loaded.agent_overrides["reviewer"].model, "claude-x")

    # 4. A file with no top-level "model" gets one added.
    def test_missing_top_level_model_is_added(self) -> None:
        original = '{\n  // no model yet\n  "default_agent": "shema-ai-coordinador"\n}\n'
        _write(self.path, original)

        save_model_config(self.root, NEW_GLOBAL, {})

        after = self.path.read_text(encoding="utf-8")
        self.assertIn("// no model yet", after)
        self.assertIn('"default_agent": "shema-ai-coordinador"', after)
        self.assertEqual(load_model_config(self.root).global_model, NEW_GLOBAL)
        self.assertIn(NEW_GLOBAL, after)

    # 5. Malformed JSONC does not raise and does not lose the original content.
    def test_malformed_jsonc_does_not_raise_or_lose_content(self) -> None:
        malformed = '{\n  "model": "openai/gpt-4o",\n  "broken": [1, 2,\n}\n'
        _write(self.path, malformed)

        save_model_config(self.root, NEW_GLOBAL, {})  # must not raise

        self.assertEqual(self.path.read_bytes(), malformed.encode("utf-8"))

    # 6. Loading still reports the global model and the overrides.
    def test_load_reports_global_model_and_overrides(self) -> None:
        config = """{
  // models
  "model": "openai/gpt-4o",
  "agents": {
    "reviewer": {
      "model": {"providerID": "anthropic", "model": "claude-x", "variant": "high"}
    },
    "planner": {
      "model": "openai/gpt-4o"
    }
  }
}
"""
        _write(self.path, config)

        loaded = load_model_config(self.root)

        self.assertEqual(loaded.global_model, GLOBAL)
        self.assertEqual(set(loaded.agent_overrides), {"reviewer", "planner"})
        self.assertEqual(loaded.agent_overrides["reviewer"].provider, "anthropic")
        self.assertEqual(loaded.agent_overrides["reviewer"].model, "claude-x")
        self.assertEqual(loaded.agent_overrides["reviewer"].variant, "high")
        self.assertEqual(loaded.agent_overrides["planner"].provider, "openai")
        self.assertEqual(loaded.agent_overrides["planner"].model, "gpt-4o")

    def test_empty_object_gets_model_and_agent(self) -> None:
        _write(self.path, "{}\n")

        save_model_config(
            self.root,
            NEW_GLOBAL,
            {"reviewer": AgentModelOverride(provider="openai", model="gpt-4o")},
        )

        loaded = load_model_config(self.root)
        self.assertEqual(loaded.global_model, NEW_GLOBAL)
        self.assertEqual(loaded.agent_overrides["reviewer"].model, "gpt-4o")
        self.assertTrue(self.path.read_text(encoding="utf-8").endswith("}\n"))

    def test_missing_model_with_existing_agents(self) -> None:
        original = """{
  // agents only
  "agents": {
    "planner": {
      "model": {"providerID": "openai", "model": "gpt-4o"}
    }
  }
}
"""
        _write(self.path, original)

        save_model_config(
            self.root,
            NEW_GLOBAL,
            {
                "planner": AgentModelOverride(provider="anthropic", model="claude-x"),
                "reviewer": AgentModelOverride(provider="openai", model="gpt-4o"),
            },
        )

        after = self.path.read_text(encoding="utf-8")
        self.assertIn("// agents only", after)
        loaded = load_model_config(self.root)
        self.assertEqual(loaded.global_model, NEW_GLOBAL)
        self.assertEqual(loaded.agent_overrides["planner"].model, "claude-x")
        self.assertEqual(loaded.agent_overrides["reviewer"].model, "gpt-4o")

    def test_missing_file_is_created_in_the_legacy_shape(self) -> None:
        save_model_config(
            self.root,
            NEW_GLOBAL,
            {"reviewer": AgentModelOverride(provider="openai", model="gpt-4o")},
        )

        self.assertTrue(self.path.exists())
        self.assertEqual(load_model_config(self.root).global_model, NEW_GLOBAL)
        self.assertEqual(
            load_model_config(self.root).agent_overrides["reviewer"].model, "gpt-4o"
        )
        raw = self.path.read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("{\n  \"model\":"), raw)
        self.assertTrue(raw.endswith("}\n"), raw)


if __name__ == "__main__":
    unittest.main()
