"""AUTO-02 deterministic context reconstruction tests (SE-AUTOMATION-001B-B2).

Hermetic: read-only commands only; no network; temporary projects for --project.
Verifies the context levels, focus semantics, bounded closure, determinism,
minimum-context behavior, JSON contract usage and authority preservation.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.reporting import REPORT_ID, ROOT_KEYS  # noqa: E402


def run_context(project, *extra):
    return support.run_cli("context", "--project", str(project), "--json", *extra)


def load(out):
    return json.loads(out)


def write_active_project(root: Path):
    """A small project with one PENDING task linked to a requirement/objective."""
    support.make_project(root, state="ACTIVE")
    support.write_json(root / "objectives" / "OBJ-0001.json", support.objective())
    support.write_json(root / "requirements" / "REQ-0001.json", support.requirement())
    support.write_json(
        root / "tasks" / "TASK-0001.json",
        support.task(
            status="PENDING",
            related_requirements=["REQ-0001"],
            authorized_actions=["READ", "ANALYZE", "IMPLEMENT"],
            restrictions=["No production access."],
        ),
    )
    support.write_json(
        root / "evidence" / "EVD-0001.json",
        support.evidence(related_tasks=["TASK-0001"], related_requirements=["REQ-0001"]),
    )
    return root


def snapshot_tree(root: Path):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ContextReconstructionTests(unittest.TestCase):
    # 1. default = LEVEL 0 -------------------------------------------------
    def test_default_scope_is_identity_level_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = write_active_project(Path(tmp) / "p")
            code, out = run_context(project)
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["operation"], "context reconstruction")
            self.assertEqual(data["scope"], "identity")
            self.assertEqual(data["details"]["level"], 0)
            self.assertEqual(data["tasks"], [])
            self.assertEqual(data["requirements"], [])
            self.assertEqual(data["evidence"], [])
            self.assertEqual(data["artifacts"], [])
            self.assertEqual(data["details"]["selection"]["id"], None)
            self.assertEqual(data["project"]["project_id"], "PRJ-TEST-001")
            self.assertEqual(data["lifecycle"]["state"], "ACTIVE")

    # 2. explicit LEVEL 1 --------------------------------------------------
    def test_explicit_work_scope_selects_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = write_active_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "work")
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertEqual(data["details"]["level"], 1)
            self.assertEqual(data["details"]["selection"]["id"], "TASK-0001")
            self.assertEqual(data["details"]["selection"]["basis"], "active-task")
            self.assertEqual([t["id"] for t in data["tasks"]], ["TASK-0001"])
            self.assertEqual([o["id"] for o in data["objectives"]], ["OBJ-0001"])
            self.assertEqual(data["blockers"], [])

    # 3. explicit LEVEL 2 --------------------------------------------------
    def test_explicit_authority_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = write_active_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "authority")
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertEqual(data["details"]["level"], 2)
            authority = data["authority"]
            self.assertIsInstance(authority, dict)
            self.assertEqual(authority["authorized_actions"], ["READ", "ANALYZE", "IMPLEMENT"])
            self.assertEqual(authority["restrictions"], ["No production access."])
            self.assertIsInstance(data["capabilities"], dict)
            self.assertIn(data["capabilities"]["plan_status"], {"PASS", "CONFLICT"})
            self.assertIn("summary", data["capabilities"])

    # 4. explicit LEVEL 3 --------------------------------------------------
    def test_explicit_trace_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "trace", "--focus", "TASK-0001")
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertEqual(data["details"]["level"], 3)
            self.assertEqual(data["details"]["closure"]["depth"], 2)
            self.assertIn("REQ-0001", [r["id"] for r in data["requirements"]])
            self.assertTrue(data["evidence"])
            self.assertIn("ACC-0001", [a["id"] for a in data["acceptance"]])
            self.assertFalse(data["details"]["closure"]["capped"])

    # 5. explicit LEVEL 4 --------------------------------------------------
    def test_explicit_deep_scope_adds_bounded_bodies(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "deep", "--focus", "TASK-0001")
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertEqual(data["details"]["level"], 4)
            bodies = data["details"]["bodies"]
            self.assertIn("TASK-0001", bodies)
            self.assertEqual(bodies["TASK-0001"]["id"], "TASK-0001")
            # bodies are bounded to the closure, never the whole project
            self.assertIn("REQ-0001", bodies)
            self.assertNotIn("REQ-0002", bodies)

    # 6. focus=TASK-0001 ---------------------------------------------------
    def test_focus_is_explicit_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "work", "--focus", "TASK-0001")
            self.assertEqual(code, 0, out)
            selection = load(out)["details"]["selection"]
            self.assertEqual(selection["kind"], "task")
            self.assertEqual(selection["id"], "TASK-0001")
            self.assertEqual(selection["basis"], "explicit")

    def test_project_focus_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = write_active_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "work", "--focus", "PRJ-TEST-001")
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertTrue(data["details"]["selection"]["project_focus"])
            self.assertEqual(data["details"]["selection"]["id"], "TASK-0001")

    # 7. bounded closure ---------------------------------------------------
    def test_closure_does_not_include_unrelated_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = write_active_project(Path(tmp) / "p")
            support.write_json(
                project / "tasks" / "TASK-0099.json",
                support.task(id="TASK-0099", title="Unrelated", related_requirements=["REQ-0099"]),
            )
            support.write_json(
                project / "requirements" / "REQ-0099.json",
                support.requirement(id="REQ-0099", title="Unrelated requirement"),
            )
            code, out = run_context(project, "--scope", "trace", "--focus", "TASK-0001")
            self.assertEqual(code, 0, out)
            self.assertNotIn("TASK-0099", out)
            self.assertNotIn("REQ-0099", out)
            self.assertFalse(load(out)["details"]["closure"]["capped"])

    def test_work_scope_reports_dependencies_and_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p", state="ACTIVE")
            support.write_json(
                project / "tasks" / "TASK-0001.json",
                support.task(status="PENDING", dependencies=["TASK-0002"]),
            )
            support.write_json(
                project / "tasks" / "TASK-0002.json",
                support.task(id="TASK-0002", status="BLOCKED", blocked_reason="Waiting on inputs."),
            )
            code, out = run_context(project, "--scope", "work", "--focus", "TASK-0001")
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertEqual(data["dependencies"], [{"from": "TASK-0001", "to": "TASK-0002"}])
            self.assertTrue(data["details"]["dependencies"]["acyclic"])
            self.assertEqual([b["task_id"] for b in data["blockers"]], ["TASK-0002"])
            self.assertEqual(data["blockers"][0]["reason"], "Waiting on inputs.")

    # 8. deterministic output ----------------------------------------------
    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            _, first = run_context(project, "--scope", "deep", "--focus", "TASK-0001")
            _, second = run_context(project, "--scope", "deep", "--focus", "TASK-0001")
            a, b = load(first), load(second)
            a.pop("observation")
            b.pop("observation")
            self.assertEqual(a, b)

    # 9. only observed_at varies -------------------------------------------
    def test_only_observed_at_varies(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            _, first = run_context(project, "--scope", "trace", "--focus", "TASK-0001")
            _, second = run_context(project, "--scope", "trace", "--focus", "TASK-0001")
            a, b = load(first), load(second)
            self.assertEqual(a["observation"]["tool"], "se")
            self.assertEqual(a["observation"]["source_root"], b["observation"]["source_root"])
            for data in (a, b):
                data["observation"]["observed_at"] = "<observed_at>"
            self.assertEqual(a, b)

    # 10. no unrelated project data ----------------------------------------
    def test_no_data_from_another_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_a = support.make_full_project(Path(tmp) / "a")
            project_b = support.make_full_project(Path(tmp) / "b")
            support.write_json(
                project_b / "PROJECT.json",
                support.manifest(project_id="PRJ-OTHER-999", name="Other Project"),
            )
            code, out = run_context(project_a, "--scope", "deep", "--focus", "TASK-0001")
            self.assertEqual(code, 0, out)
            self.assertNotIn("PRJ-OTHER-999", out)
            self.assertNotIn("Other Project", out)

    # 11. no full mutation-log dump ----------------------------------------
    def test_no_mutation_log_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            sentinel = "MUTATION-SENTINEL-42"
            (project / "mutation-log.jsonl").write_text(
                json.dumps({"at": support.TS, "record_id": sentinel, "changes": [sentinel]}) + "\n",
                encoding="utf-8",
            )
            for scope in ("identity", "work", "authority", "trace", "deep"):
                code, out = run_context(project, "--scope", scope, "--focus", "TASK-0001")
                self.assertEqual(code, 0, out)
                self.assertNotIn(sentinel, out, scope)
                self.assertNotIn("mutation-log", out, scope)

    # 12. no complete document dump by default -----------------------------
    def test_no_document_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            sentinel = "DOC-SENTINEL-7"
            (project / "docs" / "sentinel.md").write_text(
                "# Sentinel\n\n" + sentinel + "\n", encoding="utf-8"
            )
            for scope in ("identity", "work", "authority", "trace", "deep"):
                code, out = run_context(project, "--scope", scope, "--focus", "TASK-0001")
                self.assertEqual(code, 0, out)
                self.assertNotIn(sentinel, out, scope)

    # 13. no authority mutation --------------------------------------------
    def test_reconstruction_does_not_mutate_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            before = snapshot_tree(project)
            for scope in ("identity", "work", "authority", "trace", "deep"):
                code, out = run_context(project, "--scope", scope, "--focus", "TASK-0001")
                self.assertEqual(code, 0, out)
            self.assertEqual(snapshot_tree(project), before)

    # 14. malformed/unknown focus handled cleanly --------------------------
    def test_unknown_and_malformed_focus_handled_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            for focus in ("TASK-9999", "not-a-focus", "REQ-"):
                code, out = run_context(project, "--scope", "trace", "--focus", focus)
                self.assertEqual(code, 2, out)
                data = load(out)
                self.assertEqual(data["report"], REPORT_ID)
                self.assertEqual(data["status"], "FAIL")
                self.assertTrue(data["conflicts"], focus)

    # 15. invalid scope handled cleanly ------------------------------------
    def test_invalid_scope_handled_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "everything")
            self.assertEqual(code, 2, out)
            data = load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(data["conflicts"])

    def test_missing_project_handled_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run_context(Path(tmp) / "nope")
            self.assertEqual(code, 1, out)
            data = load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(data["conflicts"])

    # 16. JSON remains valid se.report/1 -----------------------------------
    def test_json_envelope_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = run_context(project, "--scope", "trace", "--focus", "TASK-0001")
            self.assertEqual(code, 0, out)
            data = load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["operation"], "context reconstruction")
            self.assertTrue(set(ROOT_KEYS).issubset(data.keys()))
            self.assertNotIn("\x1b", out)
            self.assertIn("observed_at", data["observation"])

    # 17. existing B1 behavior remains unchanged ---------------------------
    def test_existing_json_commands_still_emit_se_report_1(self):
        code, out = support.run_cli("doctor", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(load(out)["report"], REPORT_ID)
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, out = support.run_cli("review", "--project", str(project), "--json")
            self.assertEqual(code, 0, out)
            self.assertEqual(load(out)["report"], REPORT_ID)

    # 18. normal CLI behavior remains unchanged ----------------------------
    def test_human_output_is_not_json(self):
        code, out = support.run_cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("Doctor summary:", out)
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("context", "--project", str(project), "--scope", "work")
            self.assertEqual(code, 0, out)
            self.assertTrue(out.startswith("CONTEXT:"))
            self.assertFalse(out.lstrip().startswith("{"))


if __name__ == "__main__":
    unittest.main()
