"""AUTO-04 EXECUTE -> OBSERVE tests (SE-AUTOMATION-001F).

Hermetic: no network, temporary directories only, READ-ONLY semantics verified for observe.
Covers:
  - ``se execute`` (CMD-0022) executes tasks in topological order with authorization,
    creates evidence on completion, creates artifacts for deliverable tasks,
    fail-closed on first failure, produces execution receipts.
  - ``se observe`` (CMD-0023) READ-ONLY view of execution state.
  - Contract validation of both envelopes.
  - G3 gate enforcement before execution.
  - Dry-run mode (no mutations).
  - Skip already DONE tasks, reject BLOCKED tasks.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


def _load(out):
    return json.loads(out)


class ExecuteCommandTests(unittest.TestCase):
    def test_execute_dry_run_emits_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("execute", "--project", str(project), "--dry-run", "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["contract"], "se.execute/1")
            self.assertEqual(data["operation"], "execute")
            self.assertEqual(data["status"], "PASS")
            self.assertIn("results", data)
            self.assertIn("execution_receipts", data)
            self.assertNotIn("\x1b", out)

    def test_execute_envelope_validates_against_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            _, out = support.run_cli("execute", "--project", str(project), "--dry-run", "--json")
            data = _load(out)
            errors = validate(data, support.schemas()["execute"])
            self.assertEqual(errors, [], errors)

    def test_execute_requires_g3_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, out = support.run_cli("execute", "--project", str(project), "--dry-run", "--json")
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["report"], "se.report/1")
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(any("G3 gate not passed" in c for c in data["conflicts"]))

    def test_execute_skips_done_tasks_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("execute", "--project", str(project), "--dry-run", "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            for r in data["results"]:
                self.assertTrue(r.get("skipped") or r.get("status") == "DONE")

    def test_execute_force_reruns_done_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("execute", "--project", str(project), "--force", "--dry-run", "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            # With --force, tasks should be executed (dry-run) not skipped
            self.assertTrue(len(data["results"]) > 0)

    def test_execute_single_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--dry-run", "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(len(data["results"]), 1)
            self.assertEqual(data["results"][0]["task_id"], "TASK-0001")

    def test_execute_invalid_task_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-9999", "--dry-run", "--json")
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["status"], "FAIL")

    def test_execute_rejects_cyclic_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            support.write_json(
                project / "tasks" / "TASK-0001.json",
                support.task(id="TASK-0001", dependencies=["TASK-0002"]),
            )
            support.write_json(
                project / "tasks" / "TASK-0002.json",
                support.task(id="TASK-0002", dependencies=["TASK-0001"]),
            )
            support.write_json(project / "objectives" / "OBJ-0001.json", support.objective())
            support.write_json(project / "requirements" / "REQ-0001.json", support.requirement())
            code, out = support.run_cli("execute", "--project", str(project), "--dry-run", "--json")
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["report"], "se.report/1")
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(any("cycles" in c.lower() for c in data["conflicts"]))

    def test_execute_actual_creates_evidence_and_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            # Need a task that's not DONE - modify one to PENDING
            task_path = project / "tasks" / "TASK-0001.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["status"] = "READY"
            support.write_json(task_path, task)
            
            before = _snapshot(project)
            code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(data["executed"], 1)
            self.assertEqual(len(data["execution_receipts"]), 1)
            
            # Verify evidence and artifact were created
            receipt = data["execution_receipts"][0]
            self.assertIn("evidence_ids", receipt)
            self.assertIn("artifact_ids", receipt)
            
            # Verify files created
            after = _snapshot(project)
            new_files = [f for f in after if f not in before]
            self.assertTrue(any("evidence" in f for f in new_files))
            self.assertTrue(any("artifact" in f or "execution_receipts" in f for f in new_files))

    def test_execute_rejected_action_blocks_task_with_reason(self):
        """Regression for DEF-6.

        A refused action must leave the task BLOCKED with a schema-valid
        blocked_reason and resolution_path. Before the fix the BLOCKED write was
        rejected by validation, so the task silently stayed IN_PROGRESS and
        `observe` reported a refused task as still running.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            task_path = project / "tasks" / "TASK-0001.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["status"] = "READY"
            task["metadata"] = {"action": {
                "kind": "write_file",
                "path": "../escaped.txt",
                "content": "nope",
            }}
            support.write_json(task_path, task)

            before = _snapshot(project)
            code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")
            self.assertNotEqual(code, 0, "a refused action must not report success")

            blocked = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertTrue(blocked.get("blocked_reason"), "BLOCKED requires a reason")
            self.assertTrue(blocked.get("resolution_path"), "BLOCKED requires a resolution path")
            self.assertEqual(validate(blocked, support.load_schemas()["task"]), [])

            # Fail-closed: nothing escaped the project root, and no record was
            # invented for an action that never ran.
            self.assertFalse((project.parent / "escaped.txt").exists())
            after = _snapshot(project)
            for name in before:
                self.assertIn(name, after)
            self.assertEqual(
                [n for n in after if "execution_receipts" in n and n not in before], []
            )

    def test_execute_actual_updates_task_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            task_path = project / "tasks" / "TASK-0001.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["status"] = "READY"
            support.write_json(task_path, task)
            
            _, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")
            data = _load(out)
            self.assertEqual(data["status"], "PASS")
            
            # Verify task status updated to DONE
            updated_task = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(updated_task["status"], "DONE")

    def test_execute_fail_closed_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            # Create task without authorized_actions IMPLEMENT
            support.write_json(
                project / "tasks" / "TASK-0001.json",
                support.task(id="TASK-0001", authorized_actions=["READ", "ANALYZE"]),
            )
            support.write_json(
                project / "tasks" / "TASK-0002.json",
                support.task(id="TASK-0002", authorized_actions=["READ", "ANALYZE", "IMPLEMENT"]),
            )
            support.write_json(project / "objectives" / "OBJ-0001.json", support.objective())
            support.write_json(project / "requirements" / "REQ-0001.json", support.requirement())
            
            code, out = support.run_cli("execute", "--project", str(project), "--json")
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["status"], "FAIL")
            # Only first task should have been attempted (fail-closed)
            self.assertEqual(len(data["results"]), 1)
            self.assertFalse(data["results"][0]["success"])

    def test_execute_continue_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            support.write_json(
                project / "tasks" / "TASK-0001.json",
                support.task(id="TASK-0001", authorized_actions=["READ", "ANALYZE"]),
            )
            support.write_json(
                project / "tasks" / "TASK-0002.json",
                support.task(id="TASK-0002", authorized_actions=["READ", "ANALYZE", "IMPLEMENT"]),
            )
            support.write_json(project / "objectives" / "OBJ-0001.json", support.objective())
            support.write_json(project / "requirements" / "REQ-0001.json", support.requirement())
            
            code, out = support.run_cli("execute", "--project", str(project), "--continue-on-error", "--json")
            data = _load(out)
            self.assertEqual(data["status"], "FAIL")
            # Both tasks should have been attempted
            self.assertEqual(len(data["results"]), 2)

    def test_execute_respects_authorized_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Use a full project that satisfies all gates (including G3)
            project = support.make_full_project(Path(tmp) / "p")
            # Add a task that is READY but lacks IMPLEMENT in authorized_actions
            support.write_json(
                project / "tasks" / "TASK-0002.json",
                support.task(
                    id="TASK-0002",
                    status="READY",
                    authorized_actions=["READ", "ANALYZE"],
                    related_requirements=["REQ-0001"],
                ),
            )
            # Ensure the task is not DONE
            task_path = project / "tasks" / "TASK-0002.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(task["status"], "READY")
            self.assertNotIn("IMPLEMENT", task.get("authorized_actions", []))
            
            code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0002", "--dry-run", "--json")
            data = _load(out)
            self.assertFalse(data["results"][0]["success"])
            self.assertIn("IMPLEMENT", data["results"][0].get("error", ""))


class ObserveCommandTests(unittest.TestCase):
    def test_observe_emits_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli("observe", "--project", str(project), "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["contract"], "se.observe/1")
            self.assertEqual(data["operation"], "observe")
            self.assertEqual(data["status"], "PASS")
            self.assertIn("tasks", data)
            self.assertIn("evidence", data)
            self.assertIn("artifacts", data)
            self.assertIn("execution_receipts", data)
            self.assertNotIn("\x1b", out)

    def test_observe_envelope_validates_against_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            _, out = support.run_cli("observe", "--project", str(project), "--json")
            data = _load(out)
            errors = validate(data, support.schemas()["observe"])
            self.assertEqual(errors, [], errors)

    def test_observe_reports_task_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            _, out = support.run_cli("observe", "--project", str(project), "--json")
            data = _load(out)
            self.assertEqual(len(data["tasks"]["done"]), 1)
            self.assertEqual(len(data["tasks"]["in_progress"]), 0)
            self.assertEqual(len(data["tasks"]["blocked"]), 0)

    def test_observe_reports_execution_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            task_path = project / "tasks" / "TASK-0001.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["status"] = "READY"
            support.write_json(task_path, task)
            
            _, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")
            
            _, out2 = support.run_cli("observe", "--project", str(project), "--json")
            data = _load(out2)
            self.assertTrue(len(data["evidence"]) > 0)
            # TASK-0001 declares no metadata.action, so the executor performs no real
            # effect and must not claim a verification-grade result. PASS is reserved
            # for executions that actually produced a hash-verified effect.
            self.assertEqual(data["evidence"][0]["result"], "INFO")

    def test_observe_reports_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            _, out = support.run_cli("observe", "--project", str(project), "--json")
            data = _load(out)
            self.assertTrue(len(data["artifacts"]) > 0)
            # Verify artifact id field contains the canonical artifact_id
            for art in data["artifacts"]:
                self.assertIsNotNone(art["id"])
                self.assertTrue(art["id"].startswith("ART-"))

    def test_observe_reports_execution_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            task_path = project / "tasks" / "TASK-0001.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["status"] = "READY"
            support.write_json(task_path, task)
            
            _, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")
            
            _, out2 = support.run_cli("observe", "--project", str(project), "--json")
            data = _load(out2)
            self.assertTrue(len(data["execution_receipts"]) > 0)
            receipt = data["execution_receipts"][0]
            self.assertIn("receipt_id", receipt)
            self.assertIn("task_id", receipt)
            self.assertIn("evidence_ids", receipt)

    def test_observe_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            before = _snapshot(project)
            _, out = support.run_cli("observe", "--project", str(project), "--json")
            after = _snapshot(project)
            self.assertEqual(before, after)

    def test_observe_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            _, first = support.run_cli("observe", "--project", str(project), "--json")
            _, second = support.run_cli("observe", "--project", str(project), "--json")
            a = _load(first)
            b = _load(second)
            a["observation"].pop("observed_at")
            b["observation"].pop("observed_at")
            self.assertEqual(a, b)


def _snapshot(project: Path) -> dict:
    return {
        str(p.relative_to(project)): p.read_bytes()
        for p in sorted(project.rglob("*"))
        if p.is_file()
    }


if __name__ == "__main__":
    unittest.main()