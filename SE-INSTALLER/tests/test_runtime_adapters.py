"""--runtimes must render real adapter layers, not just store plan state."""

from __future__ import annotations

import json
from pathlib import Path

from se_installer import cli, runtime_adapters
from se_installer import orchestrator as orchestrator_module

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_root_prefers_a_tree_with_scripts(tmp_path):
    scripts = tmp_path / "SCRIPTS"
    scripts.mkdir()
    (scripts / "se.py").write_text("", encoding="utf-8")
    assert runtime_adapters.resolve_root(tmp_path) == tmp_path


def test_resolve_root_falls_back_to_the_installer_package(tmp_path):
    resolved = runtime_adapters.resolve_root(tmp_path / "missing")
    assert (resolved / "SCRIPTS" / "se.py").exists()


def test_dry_run_reports_files_without_writing(tmp_path):
    results = runtime_adapters.generate(REPO_ROOT, ["deepseek"], dry_run=True)
    assert results[0]["runtime"] == "deepseek"
    assert results[0]["status"] == "PASS"
    assert results[0]["files"] >= 9
    assert not (REPO_ROOT / ".dsh").exists()


def test_unknown_runtime_is_reported_not_silently_dropped():
    results = runtime_adapters.generate(REPO_ROOT, ["not-a-runtime"], dry_run=True)
    assert results[0]["status"] == "FAILED"
    assert "unknown runtime" in results[0]["error"]


def test_cli_includes_adapters_in_the_json_summary(monkeypatch, capsys):
    class FakeOrchestrator:
        def __init__(self, *args, **kwargs):
            pass

        def prepare_plan(self, *args, **kwargs):
            pass

        def run_installation(self):
            return True

        def get_summary(self):
            return {
                "total": 1,
                "success": 1,
                "failed": 0,
                "skipped": 0,
                "shortcut": None,
                "components": [],
            }

    monkeypatch.setattr(orchestrator_module, "InstallerOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        runtime_adapters,
        "generate",
        lambda root, runtimes, dry_run=False: [
            {"runtime": name, "status": "PASS", "files": 9, "output": str(root)}
            for name in runtimes
        ],
    )

    args = cli.create_parser().parse_args(
        ["install", "--components", "se_core", "--runtimes", "deepseek", "--json", "--dry-run"]
    )
    code = cli.cmd_install(args)
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["adapters"][0]["runtime"] == "deepseek"
    assert payload["adapters"][0]["status"] == "PASS"
