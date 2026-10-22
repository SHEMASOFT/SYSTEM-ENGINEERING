"""`se update` tests: controlled record mutation (positive and adversarial)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import install  # noqa: E402
from se_core import lifecycle_state as lc  # noqa: E402
from se_core import update as update_lifecycle  # noqa: E402
from se_core.commands import _is_stale  # noqa: E402
from se_core.paths import load_json  # noqa: E402

DIR = {
    "objective": "objectives",
    "requirement": "requirements",
    "task": "tasks",
    "artifact": "artifacts",
    "evidence": "evidence",
    "acceptance": "acceptances",
    "decision": "decisions",
    "release": "releases",
}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, kind, data):
        ident = data.get("id") or data.get("objective_id") or data.get("artifact_id") \
            or data.get("acceptance_id") or data.get("decision_id")
        support.write_json(self.project / DIR[kind] / f"{ident}.json", data)

    def update(self, kind, ident, *ops, by=None):
        argv = ["update", kind, ident, "--project", str(self.project), *ops]
        if by:
            argv += ["--by", by]
        return support.run_cli(*argv)

    def read(self, kind, ident):
        return load_json(self.project / DIR[kind] / f"{ident}.json")

    # --- positive ---
    def test_p1_update_simple_field(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--set", "title=New title")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read("task", "TASK-0001")["title"], "New title")

    def test_p2_update_multiple_fields(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--set", "title=T", "--set", "objective=O")
        self.assertEqual(code, 0, out)
        data = self.read("task", "TASK-0001")
        self.assertEqual(data["title"], "T")
        self.assertEqual(data["objective"], "O")

    def test_p7_relationship_update(self):
        self.write("requirement", support.requirement())
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--add", "related_requirements=REQ-0001")
        self.assertEqual(code, 0, out)
        self.assertIn("REQ-0001", self.read("task", "TASK-0001")["related_requirements"])

    def test_p11_task_dependencies_valid(self):
        self.write("task", support.task(id="TASK-0001"))
        self.write("task", support.task(id="TASK-0002"))
        code, out = self.update("task", "TASK-0001", "--set", "dependencies=TASK-0002")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read("task", "TASK-0001")["dependencies"], ["TASK-0002"])

    def test_p12_related_decisions_valid(self):
        self.write("requirement", support.requirement())
        self.write("decision", support.decision())
        code, out = self.update("requirement", "REQ-0001", "--add", "related_decisions=ADR-0001")
        self.assertEqual(code, 0, out)
        self.assertIn("ADR-0001", self.read("requirement", "REQ-0001")["related_decisions"])

    def test_p14_epistemic_fact_requires_evidence(self):
        self.write("objective", support.objective(epistemic_status="UNKNOWN", rationale="unknown"))
        code, out = self.update("objective", "OBJ-0001", "--set", "epistemic_status=FACT", by="owner")
        self.assertEqual(code, 1, out)
        self.assertIn("evidence", out)
        self.write("evidence", support.evidence())
        code, out = self.update(
            "objective", "OBJ-0001", "--add", "evidence=EVD-0001", "--set", "epistemic_status=FACT", by="owner"
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read("objective", "OBJ-0001")["epistemic_status"], "FACT")

    def test_p15_atomic_failure_preserves_original(self):
        self.write("task", support.task())
        path = self.project / DIR["task"] / "TASK-0001.json"
        before = path.read_text(encoding="utf-8")
        code, out = self.update("task", "TASK-0001", "--set", "status=BOGUS")
        self.assertEqual(code, 1, out)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_p16_repeated_update(self):
        self.write("task", support.task())
        self.assertEqual(self.update("task", "TASK-0001", "--set", "title=A")[0], 0)
        self.assertEqual(self.update("task", "TASK-0001", "--set", "title=B")[0], 0)
        self.assertEqual(self.read("task", "TASK-0001")["title"], "B")

    def test_p17_review_after_mutation(self):
        project = support.make_full_project(Path(self._tmp.name) / "full")
        code, out = support.run_cli(
            "update", "task", "TASK-0001", "--project", str(project), "--set", "title=Updated task"
        )
        self.assertEqual(code, 0, out)
        code, out = support.run_cli("review", "--project", str(project))
        self.assertEqual(code, 0, out)

    def test_mutation_log_written(self):
        self.write("task", support.task())
        self.update("task", "TASK-0001", "--set", "title=X", by="owner")
        log = self.project / "mutation-log.jsonl"
        self.assertTrue(log.exists())
        self.assertIn("TASK-0001", log.read_text(encoding="utf-8"))

    # --- adversarial ---
    def test_n1_unknown_record_type(self):
        code, out = self.update("bogus", "X-0001", "--set", "title=X")
        self.assertEqual(code, 2, out)

    def test_n2_unknown_record_id(self):
        code, out = self.update("requirement", "REQ-9999", "--set", "title=X")
        self.assertEqual(code, 1, out)
        self.assertIn("not found", out)

    def test_n3_unknown_field(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--set", "bogus=1")
        self.assertEqual(code, 1, out)
        self.assertIn("unknown field", out)

    def test_n4_change_id_rejected(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--set", "id=TASK-9999")
        self.assertEqual(code, 1, out)
        self.assertIn("immutable", out)

    def test_n5_change_project_id_rejected(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--set", "project_id=PRJ-OTHER-001")
        self.assertEqual(code, 1, out)
        self.assertIn("immutable", out)

    def test_n6_invalid_enum(self):
        self.write("requirement", support.requirement())
        code, out = self.update("requirement", "REQ-0001", "--set", "priority=urgent")
        self.assertEqual(code, 1, out)
        self.assertIn("invalid", out)

    def test_n7_invalid_data_type(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--set", "title=")
        self.assertEqual(code, 1, out)

    def test_n8_broken_relationship(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--add", "related_requirements=REQ-9999")
        self.assertEqual(code, 1, out)
        self.assertIn("does not exist", out)

    def test_n9_cross_project_reference(self):
        other = support.make_project(Path(self._tmp.name) / "other")
        support.write_json(other / "requirements" / "REQ-0001.json", support.requirement())
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--add", "related_requirements=REQ-0001")
        self.assertEqual(code, 1, out)
        self.assertIn("does not exist", out)

    def test_n10_malformed_update_input(self):
        self.write("task", support.task())
        code, out = self.update("task", "TASK-0001", "--set", "noequals")
        self.assertEqual(code, 1, out)
        self.assertIn("invalid assignment", out)

    def test_n11_breaks_required_field(self):
        self.write("artifact", support.artifact())
        code, out = self.update("artifact", "ART-0001", "--remove", "produced_by=TASK-0001")
        self.assertEqual(code, 1, out)

    def test_n12_epistemic_violation(self):
        self.write("objective", support.objective(epistemic_status="UNKNOWN", rationale="unknown"))
        code, out = self.update("objective", "OBJ-0001", "--set", "epistemic_status=FACT", by="owner")
        self.assertEqual(code, 1, out)

    def test_n13_acceptance_without_evidence(self):
        self.write("acceptance", support.acceptance())
        code, out = self.update(
            "acceptance", "ACC-0001", "--remove", "evidence=EVD-0001,EVD-0002", by="owner"
        )
        self.assertEqual(code, 1, out)

    def test_n14_release_controlled_without_by(self):
        self.write("release", support.release())
        code, out = self.update("release", "REL-0001", "--set", "status=RELEASED")
        self.assertEqual(code, 1, out)
        self.assertIn("controlled", out)

    def test_n15_stale_detection_helper(self):
        self.write("task", support.task())
        path = self.project / DIR["task"] / "TASK-0001.json"
        raw = path.read_text(encoding="utf-8")
        self.assertFalse(_is_stale(path, raw))
        path.write_text(raw + " ", encoding="utf-8")
        self.assertTrue(_is_stale(path, raw))

    def test_n16_corrupt_record_no_partial_write(self):
        path = self.project / DIR["requirement"] / "REQ-0001.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        code, out = self.update("requirement", "REQ-0001", "--set", "title=X")
        self.assertEqual(code, 1, out)
        self.assertEqual(path.read_text(encoding="utf-8"), "{ this is not json")


# --------------------------------------------------------------------------- #
# SE lifecycle `se update` (declared-vs-registered diff, backup, verify, rollback)
# --------------------------------------------------------------------------- #


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or FakeResult(0)

    def __call__(self, command):
        self.calls.append(list(command))
        return self.result


def make_lifecycle_args(project, dry_run=False, json=False):
    return types.SimpleNamespace(project=str(project), dry_run=dry_run, json=json)


def declared_view_for(project, interpreter="python"):
    # Mirror production: ``cmd_update`` resolves the project path, and the
    # ``${SE_PROJECT_ROOT}`` substitution is part of the declared hash. On Windows
    # a temp directory can carry a short (8.3) name that ``resolve()`` expands, so
    # an unresolved path here would compute a different spec than production.
    project = Path(project).resolve()
    templates = install.load_mcp_templates(support.REPO_ROOT)
    view = update_lifecycle.declared_view(
        templates,
        se_root=support.REPO_ROOT,
        project=project,
        project_id=install.read_project_id(project),
        interpreter=interpreter,
    )
    return view, templates


def seed_state(project, view, *, se_version=None, only=None):
    state = lc.new_state(
        se_version=se_version or lc.read_se_version(support.REPO_ROOT),
        os_name="windows",
        target=str(Path(project).resolve()),
    )
    for name, entry in view.items():
        if only is not None and name not in only:
            continue
        lc.record_server(state, name, declared=entry["hash"], source=entry["template"]["template"])
    lc.save_state(state, project)
    return state


class PlanDiffTests(unittest.TestCase):
    def test_classifies_changed_orphaned_unmanaged(self):
        declared = {"a": {"hash": "h2"}, "c": {"hash": "hc"}}
        state = {"servers": {"a": {"declared": "h1"}, "b": {"declared": "hb"}}}
        diff = update_lifecycle.plan_diff(declared, state)
        self.assertEqual(diff["changed"], [{"name": "a", "old": "h1", "new": "h2"}])
        self.assertEqual(diff["orphaned"], ["b"])
        self.assertEqual(diff["unmanaged"], ["c"])

    def test_no_state_means_everything_unmanaged(self):
        diff = update_lifecycle.plan_diff({"a": {"hash": "h"}}, {"servers": {}})
        self.assertEqual(diff["changed"], [])
        self.assertEqual(diff["unmanaged"], ["a"])


class LifecycleUpdateCmdTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.runner = FakeRunner()
        self.which = lambda name: name in ("python", "node", "npx", "opencode")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, dry_run=False, json=False, runner=None):
        return update_lifecycle.cmd_update(
            make_lifecycle_args(self.project, dry_run=dry_run, json=json),
            platform_name="windows",
            runner=runner if runner is not None else self.runner,
            which=self.which,
        )

    def _capture(self, func):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = func()
        return code, buffer.getvalue()

    def _write_config(self, servers=None):
        (self.project / "opencode.jsonc").write_text(
            json.dumps({"mcp": {"servers": servers or {}}}), encoding="utf-8"
        )
        return self.project / "opencode.jsonc"

    def test_cli_dry_run_nothing_installed_is_blocked(self):
        code, out = support.run_cli("update", "--dry-run", "--project", str(self.project))
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED", out)

    def test_dry_run_reports_changes_without_running_runner(self):
        view, _ = declared_view_for(self.project)
        seed_state(self.project, view, only={"se-skill-server"}, se_version="0.0.1")
        state = lc.load_state(self.project)
        state["servers"]["se-skill-server"]["declared"] = "0" * 64
        lc.save_state(state, self.project)

        code, out = self._capture(lambda: self._run(dry_run=True))
        self.assertEqual(code, 0, out)
        self.assertIn("Would update", out)
        self.assertIn("se-skill-server", out)
        self.assertEqual(self.runner.calls, [])

    def test_dry_run_reports_version_mismatch_warning(self):
        view, _ = declared_view_for(self.project)
        seed_state(self.project, view, se_version="0.0.1")
        code, out = self._capture(lambda: self._run(dry_run=True, json=True))
        self.assertEqual(code, 0, out)
        details = json.loads(out)["details"]
        self.assertTrue(any("SE version changed" in w for w in details["warnings"]))

    def test_no_changes_is_noop(self):
        view, _ = declared_view_for(self.project)
        seed_state(self.project, view)
        self._write_config()
        code, out = self._capture(lambda: self._run(dry_run=True, json=True))
        self.assertEqual(code, 0, out)
        details = json.loads(out)["details"]
        self.assertEqual(details["changed"], [])
        self.assertEqual(details["status"], "PASS")

    def test_apply_success_records_state_and_verifies(self):
        view, _ = declared_view_for(self.project)
        seed_state(self.project, view, only={"se-skill-server"})
        state = lc.load_state(self.project)
        state["servers"]["se-skill-server"]["declared"] = "0" * 64
        lc.save_state(state, self.project)
        self._write_config()

        code, out = self._capture(lambda: self._run(json=True))
        self.assertEqual(code, 0, out)
        details = json.loads(out)["details"]
        self.assertEqual(details["applied"], ["se-skill-server"])
        self.assertEqual(details["verify"]["status"], "PASS")
        self.assertTrue(self.runner.calls)

        reloaded = lc.load_state(self.project)
        self.assertEqual(
            reloaded["servers"]["se-skill-server"]["declared"],
            view["se-skill-server"]["hash"],
        )

    def test_apply_failure_rolls_back_config_and_state(self):
        view, _ = declared_view_for(self.project)
        seed_state(self.project, view, only={"se-skill-server"})
        state = lc.load_state(self.project)
        state["servers"]["se-skill-server"]["declared"] = "0" * 64
        lc.save_state(state, self.project)
        config = self._write_config()
        config_before = config.read_bytes()
        state_before = lc.state_path(self.project).read_bytes()

        failing = FakeRunner(FakeResult(1, stderr="boom"))
        code, out = self._capture(lambda: self._run(json=True, runner=failing))
        self.assertEqual(code, 1, out)
        details = json.loads(out)["details"]
        self.assertEqual(details["status"], "BLOCKED")
        self.assertTrue(details["rollback"]["config_restored"])
        self.assertTrue(details["rollback"]["state_restored"])
        self.assertEqual(config.read_bytes(), config_before)
        self.assertEqual(lc.state_path(self.project).read_bytes(), state_before)

    def test_apply_missing_config_is_blocked(self):
        view, _ = declared_view_for(self.project)
        seed_state(self.project, view, only={"se-skill-server"})
        state = lc.load_state(self.project)
        state["servers"]["se-skill-server"]["declared"] = "0" * 64
        lc.save_state(state, self.project)

        code, out = self._capture(lambda: self._run())
        self.assertEqual(code, 1, out)
        self.assertIn("runtime config not found", out)


if __name__ == "__main__":
    unittest.main()
