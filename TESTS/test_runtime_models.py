"""Model propagation from the harness selection into the generated adapters."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (puts SCRIPTS/ on sys.path)

from se_core.model_tui.config import resolve_agent_model  # noqa: E402
from se_core.runtimes import (  # noqa: E402
    _claude_code_model,
    _model_for_agent,
)


def write_harness(root: Path, text: str) -> Path:
    path = root / "opencode.jsonc"
    path.write_text(text, encoding="utf-8")
    return path


class ResolveAgentModelTests(unittest.TestCase):
    def test_absent_file_resolves_to_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(resolve_agent_model(Path(tmp), "planner"))

    def test_absent_model_key_does_not_invent_a_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_harness(Path(tmp), '{\n  "theme": "dark"\n}\n')
            self.assertIsNone(resolve_agent_model(Path(tmp), "planner"))

    def test_global_model_applies_to_every_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_harness(Path(tmp), '{\n  "model": "openai/gpt-4o"\n}\n')
            for agent in ("planner", "reviewer", "unknown-agent"):
                self.assertEqual(
                    resolve_agent_model(Path(tmp), agent), "openai/gpt-4o"
                )

    def test_per_agent_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_harness(
                Path(tmp),
                '{\n  "model": "openai/gpt-4o",\n  "agents": {\n'
                '    "reviewer": {"model": {"providerID": "anthropic", '
                '"model": "claude-haiku"}}\n  }\n}\n',
            )
            self.assertEqual(
                resolve_agent_model(Path(tmp), "reviewer"), "anthropic/claude-haiku"
            )
            self.assertEqual(
                resolve_agent_model(Path(tmp), "planner"), "openai/gpt-4o"
            )

    def test_string_override_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_harness(
                Path(tmp),
                '{\n  "model": "openai/gpt-4o",\n  "agents": {\n'
                '    "tester": {"model": "anthropic/claude-haiku"}\n  }\n}\n',
            )
            self.assertEqual(
                resolve_agent_model(Path(tmp), "tester"), "anthropic/claude-haiku"
            )

    def test_comments_do_not_break_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_harness(
                Path(tmp),
                '{\n  // the default model\n  "model": "openai/gpt-4o"\n}\n',
            )
            self.assertEqual(
                resolve_agent_model(Path(tmp), "planner"), "openai/gpt-4o"
            )


class ModelForAgentTests(unittest.TestCase):
    def test_contract_declaration_wins_over_the_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_harness(Path(tmp), '{\n  "model": "openai/gpt-4o"\n}\n')
            agent = {
                "name": "reviewer",
                "llm_config": {"provider": "anthropic", "model": "claude-haiku"},
            }
            self.assertEqual(
                _model_for_agent(Path(tmp), agent), "anthropic/claude-haiku"
            )

    def test_selection_applies_when_the_contract_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_harness(Path(tmp), '{\n  "model": "openai/gpt-4o"\n}\n')
            self.assertEqual(
                _model_for_agent(Path(tmp), {"name": "planner"}), "openai/gpt-4o"
            )

    def test_nothing_configured_means_nothing_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_model_for_agent(Path(tmp), {"name": "planner"}))


class ClaudeCodeMappingTests(unittest.TestCase):
    def test_anthropic_model_is_passed_as_the_id(self):
        self.assertEqual(
            _claude_code_model("anthropic/claude-sonnet-4-5"), "claude-sonnet-4-5"
        )

    def test_alias_form_without_provider_is_kept(self):
        self.assertEqual(_claude_code_model("sonnet"), "sonnet")

    def test_other_providers_are_not_claude_code_models(self):
        self.assertIsNone(_claude_code_model("openai/gpt-4o"))
        self.assertIsNone(_claude_code_model("ollama/llama3.1"))

    def test_empty_spec_maps_to_none(self):
        self.assertIsNone(_claude_code_model(""))
        self.assertIsNone(_claude_code_model(None))


if __name__ == "__main__":
    unittest.main()
