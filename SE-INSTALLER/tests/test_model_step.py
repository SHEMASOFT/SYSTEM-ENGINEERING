"""Hermetic tests for the installer's optional MODEL SELECTION step.

These tests never install anything, never touch the network and never write
outside ``tmp_path``. They cover the guarantees the step has to keep:

* argv/flag parsing (including the flags that must be rejected);
* "skip leaves nothing": no ``model`` key, no ``agents`` entry, no new file;
* the installer never invents a model (no default, no "first free model");
* the selection is written through the same store ``se shema-ai model`` reads;
* the step never fails the install.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# The installer package is importable through PYTHONPATH=SE-INSTALLER (the way
# CI runs this suite). SE Core lives next to it in the checkout.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SCRIPTS"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import se_installer.cli as cli_module  # noqa: E402
import se_installer.model_step as model_step  # noqa: E402
from se_installer.cli import create_parser  # noqa: E402
from se_installer.models import InstallationPlan  # noqa: E402

ROSTER = model_step.list_agents(REPO_ROOT)


def _config_module():
    return importlib.import_module("se_core.model_tui.config")


def _project(tmp_path, body='{\n  "theme": "dark"\n}\n'):
    root = tmp_path / "project"
    root.mkdir()
    (root / "opencode.jsonc").write_text(body, encoding="utf-8")
    return root


def _read_config(root):
    return _config_module().load_model_config(root)


class _Answers:
    """Scripted answers for the interactive prompt (EOF once exhausted)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeOrchestrator:
    """Just enough orchestrator for ``cmd_install`` without an install."""

    def __init__(self, plan=None, dry_run=False, progress_callback=None):
        self.plan = plan or InstallationPlan()
        self.dry_run = dry_run
        self.progress_callback = progress_callback

    def prepare_plan(self, selected_ids, target_runtimes=None):
        self.plan.target_runtimes = list(target_runtimes or ["opencode"])

    def run_installation(self):
        return True

    def get_summary(self):
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "shortcut": None,
            "components": [],
        }


def _install_args(**overrides):
    values = dict(
        all=False,
        components=["se_core"],
        recommended=False,
        dry_run=True,
        runtimes=["opencode"],
        force=False,
        skip_verification=False,
        json=False,
        model=None,
        model_agent=None,
        no_model_step=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_install(monkeypatch, project_root):
    """Point the installer at a temp project and use the fake orchestrator."""
    monkeypatch.setattr(cli_module, "_repo_root", lambda: project_root)
    monkeypatch.setattr(
        "se_installer.orchestrator.InstallerOrchestrator", _FakeOrchestrator
    )


# --------------------------------------------------------------------------- #
# argv / flag parsing
# --------------------------------------------------------------------------- #


def test_install_parser_accepts_the_model_flags():
    args = create_parser().parse_args(
        [
            "install",
            "--dry-run",
            "--model",
            "openai/gpt-4o",
            "--model-agent",
            "reviewer=anthropic/claude-haiku",
            "--model-agent",
            "planner=openai/o1",
        ]
    )

    assert args.model == "openai/gpt-4o"
    assert args.model_agent == [
        "reviewer=anthropic/claude-haiku",
        "planner=openai/o1",
    ]
    assert args.no_model_step is False


def test_install_parser_accepts_no_model_step():
    args = create_parser().parse_args(["install", "--no-model-step"])

    assert args.no_model_step is True


def test_tui_parser_accepts_no_model_step():
    args = create_parser().parse_args(["tui", "--no-model-step"])

    assert args.no_model_step is True


def test_request_is_absent_without_model_flags():
    request = model_step.request_from_args(_install_args(), ROSTER)

    assert request.ask is True
    assert request.selection is None
    assert request.explicit_skip is False


def test_request_reads_the_global_model():
    request = model_step.request_from_args(
        _install_args(model="openai/gpt-4o"), ROSTER
    )

    assert request.selection.mode == model_step.MODE_GLOBAL
    assert request.selection.global_model == "openai/gpt-4o"


def test_request_reads_per_agent_models():
    request = model_step.request_from_args(
        _install_args(model_agent=["reviewer=anthropic/claude-haiku"]), ROSTER
    )

    assert request.selection.mode == model_step.MODE_PER_AGENT
    assert request.selection.agent_overrides == {
        "reviewer": "anthropic/claude-haiku"
    }


def test_no_model_step_rejects_a_combined_model_flag():
    with pytest.raises(model_step.ModelSelectionError):
        model_step.request_from_args(
            _install_args(no_model_step=True, model="openai/gpt-4o"), ROSTER
        )


@pytest.mark.parametrize(
    "value",
    ["", "gpt-4o", "/gpt-4o", "openai/", "open ai/gpt-4o", "openai/gpt 4o"],
)
def test_parse_model_spec_rejects_anything_but_provider_model(value):
    with pytest.raises(model_step.ModelSelectionError):
        model_step.parse_model_spec(value)


def test_parse_model_spec_keeps_variants_and_nested_model_ids():
    assert str(model_step.parse_model_spec("anthropic/claude-haiku[high]")) == (
        "anthropic/claude-haiku[high]"
    )
    assert str(model_step.parse_model_spec("openrouter/qwen/qwen2.5-coder:free")) == (
        "openrouter/qwen/qwen2.5-coder:free"
    )


def test_unknown_agent_is_rejected():
    with pytest.raises(model_step.ModelSelectionError):
        model_step.request_from_args(
            _install_args(model_agent=["reviewr=openai/gpt-4o"]), ROSTER
        )


def test_cmd_install_rejects_an_invalid_spec_before_installing(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    constructed = []

    class _Recording(_FakeOrchestrator):
        def __init__(self, *args, **kwargs):
            constructed.append(True)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(cli_module, "_repo_root", lambda: root)
    monkeypatch.setattr(
        "se_installer.orchestrator.InstallerOrchestrator", _Recording
    )

    exit_code = cli_module.cmd_install(_install_args(model="gpt-4o"))

    assert exit_code == 2
    assert constructed == []
    assert "not provider/model" in capsys.readouterr().err


def test_cmd_install_rejects_no_model_step_with_a_model(monkeypatch, tmp_path, capsys):
    root = _project(tmp_path)
    _patch_install(monkeypatch, root)

    exit_code = cli_module.cmd_install(
        _install_args(no_model_step=True, model="openai/gpt-4o")
    )

    assert exit_code == 2
    assert "cannot be combined" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# the selection uses the system's own store
# --------------------------------------------------------------------------- #


def test_installer_uses_the_same_save_model_config_as_the_rest_of_the_system():
    direct = _config_module().save_model_config

    assert model_step.load_save_model_config(REPO_ROOT) is direct


def test_global_selection_is_written_to_opencode_jsonc(tmp_path):
    root = _project(tmp_path)
    saver = _config_module().save_model_config

    report = model_step.apply_selection(
        root,
        model_step.selection_for_all("openai/gpt-4o"),
        runtimes=[],
        save=saver,
    )

    assert report["status"] == "configured"
    assert report["written"] is True
    assert _read_config(root).global_model == "openai/gpt-4o"
    assert _read_config(root).agent_overrides == {}


def test_per_agent_selection_writes_overrides_and_keeps_the_global(tmp_path):
    root = _project(
        tmp_path,
        '{\n  "model": "openai/gpt-4o",\n'
        '  "agents": {"planner": {"model": {"providerID": "openai", "model": "o1"}}}\n}\n',
    )
    saver = _config_module().save_model_config

    report = model_step.apply_selection(
        root,
        model_step.selection_from_cli(
            None, ["reviewer=anthropic/claude-haiku"], ROSTER
        ),
        runtimes=[],
        save=saver,
        existing=lambda _root: ("openai/gpt-4o", {"planner": "openai/o1"}),
    )

    assert report["status"] == "configured"
    config = _read_config(root)
    assert config.global_model == "openai/gpt-4o"
    assert {name: (o.provider, o.model) for name, o in config.agent_overrides.items()} == {
        "planner": ("openai", "o1"),
        "reviewer": ("anthropic", "claude-haiku"),
    }


# --------------------------------------------------------------------------- #
# skip leaves nothing
# --------------------------------------------------------------------------- #


def test_skipped_selection_writes_nothing_and_never_calls_the_store(tmp_path):
    root = _project(tmp_path)
    before = (root / "opencode.jsonc").read_bytes()
    calls = []

    def _saver(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    report = model_step.apply_selection(
        root,
        model_step.skipped_selection(reason="test"),
        runtimes=["opencode", "codex"],
        save=_saver,
    )

    assert report["status"] == "skipped"
    assert report["written"] is False
    assert report["adapters"] == []
    assert calls == []
    assert (root / "opencode.jsonc").read_bytes() == before


def test_absent_selection_writes_nothing_and_never_calls_the_store(tmp_path):
    root = _project(tmp_path)
    before = (root / "opencode.jsonc").read_bytes()
    calls = []

    report = model_step.apply_selection(
        root, None, runtimes=["opencode"], save=lambda *a, **k: calls.append(a)
    )

    assert report["status"] == "skipped"
    assert calls == []
    assert (root / "opencode.jsonc").read_bytes() == before


def test_skip_does_not_create_a_config_file(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()

    report = model_step.apply_selection(
        root, model_step.skipped_selection(), runtimes=["opencode"]
    )

    assert report["status"] == "skipped"
    assert not (root / "opencode.jsonc").exists()


def test_prompt_skip_is_a_first_class_answer(tmp_path):
    root = _project(tmp_path)
    answers = _Answers("3")

    selection = model_step.prompt_for_selection(ROSTER, ask=answers)

    assert selection.skipped
    assert selection.reason == "skipped in the prompt"
    report = model_step.apply_selection(
        root, selection, runtimes=[], save=lambda *a, **k: pytest.fail("wrote")
    )
    assert report["status"] == "skipped"
    assert _read_config(root).global_model is None


def test_prompt_ending_without_an_answer_skips(tmp_path):
    root = _project(tmp_path)

    selection = model_step.prompt_for_selection(ROSTER, ask=_Answers())

    assert selection.skipped
    assert report_is_untouched(root, selection)


def report_is_untouched(root, selection):
    before = (root / "opencode.jsonc").read_bytes()
    report = model_step.apply_selection(
        root, selection, runtimes=[], save=lambda *a, **k: pytest.fail("wrote")
    )
    return report["status"] == "skipped" and (root / "opencode.jsonc").read_bytes() == before


def test_empty_per_agent_answers_skip(tmp_path):
    root = _project(tmp_path)
    answers = _Answers("2", "", "", "")

    selection = model_step.prompt_for_selection(["planner", "reviewer"], ask=answers)

    assert selection.skipped
    assert report_is_untouched(root, selection)


def test_per_agent_prompt_lists_every_agent_and_keeps_blank_ones_unset():
    answers = _Answers("2", "openai/gpt-4o", "", "anthropic/claude-haiku")

    selection = model_step.prompt_for_selection(
        ["planner", "reviewer", "tester"], ask=answers
    )

    assert selection.agent_overrides == {
        "planner": "openai/gpt-4o",
        "tester": "anthropic/claude-haiku",
    }
    prompts = "\n".join(answers.prompts)
    assert "planner" in prompts and "reviewer" in prompts and "tester" in prompts


def test_global_prompt_offers_both_modes_and_skip():
    answers = _Answers("1", "openai/gpt-4o")

    selection = model_step.prompt_for_selection(ROSTER, ask=answers)

    menu = answers.prompts[0]
    assert "Un mismo modelo para todos" in menu
    assert "Un modelo por subagente" in menu
    assert "Saltar" in menu
    assert selection.mode == model_step.MODE_GLOBAL
    assert selection.global_model == "openai/gpt-4o"


# --------------------------------------------------------------------------- #
# the installer never invents a model
# --------------------------------------------------------------------------- #


def test_no_selection_and_no_terminal_reports_nothing(tmp_path):
    root = _project(tmp_path)
    before = (root / "opencode.jsonc").read_bytes()

    report = model_step.run_model_step(
        model_step.request_from_args(_install_args(), ROSTER),
        project_root=root,
        runtimes=["opencode"],
        interactive=False,
        save=lambda *a, **k: pytest.fail("wrote a model nobody chose"),
    )

    assert report is None
    assert (root / "opencode.jsonc").read_bytes() == before
    assert _read_config(root).global_model is None
    assert _read_config(root).agent_overrides == {}


def test_selection_from_cli_invents_nothing_when_no_flag_is_given():
    assert model_step.selection_from_cli(None, None, ROSTER) is None
    assert model_step.selection_from_cli("", [], ROSTER) is None


def test_apply_selection_never_adds_a_default_model(tmp_path):
    root = _project(tmp_path)

    report = model_step.apply_selection(
        root,
        model_step.skipped_selection(),
        runtimes=["opencode"],
    )

    assert report["global_model"] is None
    assert report["agent_overrides"] == {}
    parsed = json.loads((root / "opencode.jsonc").read_text(encoding="utf-8"))
    assert "model" not in parsed
    assert "agents" not in parsed


def test_report_lines_for_a_skip_are_not_a_plan(tmp_path):
    report = model_step.apply_selection(
        tmp_path, model_step.skipped_selection(reason="skipped"), runtimes=[]
    )

    lines = model_step.report_lines(report)

    assert len(lines) == 1
    assert "Omitido" in lines[0]
    assert not any("PLAN" in line for line in lines)


# --------------------------------------------------------------------------- #
# dry run, adapter refresh, error collection
# --------------------------------------------------------------------------- #


def test_dry_run_reports_the_plan_and_writes_nothing(tmp_path):
    root = _project(tmp_path)
    before = (root / "opencode.jsonc").read_bytes()
    calls = []

    report = model_step.apply_selection(
        root,
        model_step.selection_for_all("openai/gpt-4o"),
        runtimes=["codex"],
        dry_run=True,
        save=lambda *a, **k: calls.append(a),
        runner=lambda *a, **k: calls.append(a),
    )

    assert report["status"] == "planned"
    assert report["written"] is False
    assert report["global_model"] == "openai/gpt-4o"
    assert [entry["status"] for entry in report["adapters"]] == ["planned"]
    assert calls == []
    assert (root / "opencode.jsonc").read_bytes() == before


def test_configured_selection_refreshes_the_selected_runtimes(tmp_path):
    root = _project(tmp_path)
    (root / "SCRIPTS").mkdir()
    (root / "SCRIPTS" / "se.py").write_text("", encoding="utf-8")
    seen = []

    def runner(command, **kwargs):
        seen.append((command, kwargs))
        return _Completed(returncode=0)

    report = model_step.apply_selection(
        root,
        model_step.selection_for_all("openai/gpt-4o"),
        runtimes=["codex", "claude_code", "deepseek"],
        save=_config_module().save_model_config,
        runner=runner,
    )

    assert report["status"] == "configured"
    assert [command[3] for command, _ in seen] == [
        "codex",
        "claude-code",
        "deepseek",
    ]
    for command, kwargs in seen:
        assert command[1].endswith(str(Path("SCRIPTS") / "se.py"))
        assert command[2] == "adapter"
        assert kwargs["cwd"] == str(root)
    assert [entry["status"] for entry in report["adapters"]] == [
        "PASS",
        "PASS",
        "PASS",
    ]


def test_an_adapter_failure_is_collected_and_does_not_raise(tmp_path):
    root = _project(tmp_path)
    (root / "SCRIPTS").mkdir()
    (root / "SCRIPTS" / "se.py").write_text("", encoding="utf-8")

    report = model_step.apply_selection(
        root,
        model_step.selection_for_all("openai/gpt-4o"),
        runtimes=["codex"],
        save=_config_module().save_model_config,
        runner=lambda *a, **k: _Completed(returncode=3, stderr="boom"),
    )

    assert report["status"] == "configured"
    assert report["adapters"][0]["status"] == "FAIL"
    assert "boom" in report["adapters"][0]["error"]
    assert any("codex adapter failed" in error for error in report["errors"])


def test_a_save_failure_is_collected_and_does_not_raise(tmp_path):
    root = _project(tmp_path)

    report = model_step.apply_selection(
        root,
        model_step.selection_for_all("openai/gpt-4o"),
        runtimes=["opencode"],
        save=lambda *a, **k: (_ for _ in ()).throw(OSError("disk on fire")),
    )

    assert report["status"] == "failed"
    assert report["written"] is False
    assert any("disk on fire" in error for error in report["errors"])


def test_unknown_runtime_is_reported_but_does_not_abort(tmp_path):
    root = _project(tmp_path)

    report = model_step.apply_selection(
        root,
        model_step.selection_for_all("openai/gpt-4o"),
        runtimes=["vim"],
        save=_config_module().save_model_config,
    )

    assert report["status"] == "configured"
    assert report["adapters"] == []
    assert any("unknown runtime 'vim'" in error for error in report["errors"])


# --------------------------------------------------------------------------- #
# CLI wiring: installed first, model second, never fails the install
# --------------------------------------------------------------------------- #


def test_cmd_install_dry_run_reports_the_model_plan_and_writes_nothing(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    before = (root / "opencode.jsonc").read_bytes()
    _patch_install(monkeypatch, root)

    exit_code = cli_module.cmd_install(
        _install_args(dry_run=True, model="openai/gpt-4o")
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[MODELO]" in out
    assert "openai/gpt-4o" in out
    assert "Dry run" in out
    assert (root / "opencode.jsonc").read_bytes() == before


def test_cmd_install_no_model_step_prints_no_plan_and_writes_nothing(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    before = (root / "opencode.jsonc").read_bytes()
    _patch_install(monkeypatch, root)

    exit_code = cli_module.cmd_install(
        _install_args(dry_run=True, no_model_step=True)
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[MODELO]" not in out
    assert (root / "opencode.jsonc").read_bytes() == before


def test_cmd_install_writes_the_selection_after_the_install(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    order = []

    class _Orchestrator(_FakeOrchestrator):
        def run_installation(self):
            order.append("install")
            return True

    monkeypatch.setattr(cli_module, "_repo_root", lambda: root)
    monkeypatch.setattr(
        "se_installer.orchestrator.InstallerOrchestrator", _Orchestrator
    )
    # The temp project has no SCRIPTS/ of its own: hand the real store to the
    # step, which is the seam the installer uses for the repository checkout.
    monkeypatch.setattr(
        model_step, "load_save_model_config", lambda _root: _config_module().save_model_config
    )
    original = model_step.apply_selection

    def _spy(*args, **kwargs):
        order.append("model")
        return original(*args, **kwargs)

    monkeypatch.setattr(model_step, "apply_selection", _spy)

    exit_code = cli_module.cmd_install(
        _install_args(dry_run=False, model="openai/gpt-4o", runtimes=[])
    )

    assert exit_code == 0
    assert order == ["install", "model"]
    assert _read_config(root).global_model == "openai/gpt-4o"


def test_cmd_install_does_not_run_the_model_step_when_the_install_failed(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    before = (root / "opencode.jsonc").read_bytes()

    class _Orchestrator(_FakeOrchestrator):
        def run_installation(self):
            return False

    monkeypatch.setattr(cli_module, "_repo_root", lambda: root)
    monkeypatch.setattr(
        "se_installer.orchestrator.InstallerOrchestrator", _Orchestrator
    )

    exit_code = cli_module.cmd_install(
        _install_args(dry_run=False, model="openai/gpt-4o", runtimes=[])
    )

    assert exit_code == 1
    assert "No ejecutado" in capsys.readouterr().out
    assert (root / "opencode.jsonc").read_bytes() == before


def test_cmd_install_json_envelope_keeps_the_model_report(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    _patch_install(monkeypatch, root)

    exit_code = cli_module.cmd_install(
        _install_args(dry_run=True, json=True, model="openai/gpt-4o")
    )

    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"] == 0
    assert data["model"]["status"] == "planned"
    assert data["model"]["global_model"] == "openai/gpt-4o"


def test_cmd_install_json_without_the_step_keeps_the_old_envelope(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    _patch_install(monkeypatch, root)

    exit_code = cli_module.cmd_install(_install_args(dry_run=True, json=True))

    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert "model" not in data


def test_a_model_failure_never_changes_the_install_exit_code(
    monkeypatch, tmp_path, capsys
):
    root = _project(tmp_path)
    _patch_install(monkeypatch, root)

    def _boom(*args, **kwargs):
        raise OSError("cannot write the selection")

    monkeypatch.setattr(model_step, "apply_selection", _boom)

    exit_code = cli_module.cmd_install(
        _install_args(dry_run=False, model="openai/gpt-4o", runtimes=[])
    )

    assert exit_code == 0
    assert "cannot write the selection" in capsys.readouterr().out
