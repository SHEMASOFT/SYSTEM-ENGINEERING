"""T16: the TUI's model / runtime / adapter step is wired and testable."""

from __future__ import annotations

from pathlib import Path

import pytest

from se_installer import tui


def test_selected_runtimes_follows_checkbox_order():
    flags = {"chk-rt-pi": True, "chk-rt-opencode": True, "chk-rt-codex": False}
    assert tui.selected_runtimes(flags) == ["opencode", "pi"]
    assert tui.selected_runtimes({}) == []


def test_hermes_is_not_a_bulk_adapter_choice():
    assert "hermes" not in tui.CONFIG_RUNTIMES


def test_finish_config_applies_model_then_generates_adapters(tmp_path: Path):
    events = []

    def save_model(root, spec, overrides):
        events.append(("model", root, spec, overrides))
        return True

    def generate(root, runtimes, dry_run=False):
        events.append(("adapters", root, runtimes, dry_run))
        return [{"runtime": r, "status": "OK"} for r in runtimes]

    result = tui.finish_config(
        tmp_path,
        runtimes=["opencode", "pi"],
        model_spec="deepseek/deepseek-chat",
        generate=generate,
        save_model=save_model,
    )

    assert result["model"] == "written"
    assert len(result["adapters"]) == 2
    assert events[0][:2] == ("model", tmp_path)
    assert events[0][2] == "deepseek/deepseek-chat"
    assert events[1][2:] == (["opencode", "pi"], False)


def test_finish_config_dry_run_writes_nothing(tmp_path: Path):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not write the model config")

    calls = []

    def plan_adapters(root, runtimes, dry_run=False):
        calls.append((runtimes, dry_run))
        return [{"runtime": r, "status": "PLANNED"} for r in runtimes]

    result = tui.finish_config(
        tmp_path,
        runtimes=["codex"],
        model_spec="openai/gpt-5",
        dry_run=True,
        generate=plan_adapters,
        save_model=forbidden,
    )
    assert result["model"] == "planned"
    assert result["adapters"] == [{"runtime": "codex", "status": "PLANNED"}]
    assert calls == [(["codex"], True)]


def test_model_spec_must_be_provider_slash_model(tmp_path: Path):
    with pytest.raises(ValueError, match="provider/model"):
        tui.finish_config(tmp_path, runtimes=[], model_spec="deepseek-chat")


def test_config_tab_mounts_with_the_three_steps():
    import asyncio

    async def scenario():
        app = tui.InstallerApp()
        async with app.run_test():
            assert app.query_one("#tab-config") is not None
            assert app.query_one("#inp-model") is not None
            ids = {str(w.id) for w in app.query("Checkbox")}
            assert {f"chk-rt-{r}" for r in tui.CONFIG_RUNTIMES} <= ids
            assert app.query_one("#config-summary") is not None

    asyncio.run(scenario())


def test_tui_wires_config_step_into_install_plan():
    source = Path(tui.__file__).read_text(encoding="utf-8")
    assert 'TabPane("Configurar", id="tab-config")' in source
    assert "selected_runtimes(flags)" in source
    assert "target_runtimes=self.config_runtimes" in source
    assert "finish_config(" in source
