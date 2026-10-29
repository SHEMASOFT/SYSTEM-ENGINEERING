"""Ceremony enforcement: execution is fail-closed and only valid documents count.

The contract asserted here (P0 of the work-modes enforcement):

1. `se execute` and `OrchestrationEngine.execute` refuse to run when the declared
   ceremony floor is not met, *before* any task/node mutation (dry-run included).
2. A project that declares no `profiles.work` keeps the current behavior: nothing
   is required and execution proceeds.
3. An SDD satisfies `spec_required` only when it is schema-valid, its status is
   accepted and its `requirements_coverage` resolves; an RDD satisfies
   `receipt_required` only when its candidate is real (not a placeholder), its
   `evidence[].id` entries resolve to existing EVD records and an internal
   `linked_change` resolves.
4. Decisional SDD/RDD states cannot be born in `se new` (creation cannot attest)
   nor changed through `se update` without `--by` (the actor goes to the mutation
   log). ODD is not governed by analogy.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.commands import _master_version  # noqa: E402

EVD_ID = "EVD-0001"
WORKFLOW_ID = "WF-0001"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def profiled_project(root: Path, *, scale="large", risk="high", criticality="high", state="DRAFT"):
    """A managed project that declares a work profile requiring an SDD and a receipt."""
    project = support.make_project(root, state=state)
    support.write_json(
        project / "PROJECT.json",
        support.manifest(
            lifecycle_state=state,
            criticality=criticality,
            master_system_version=_master_version(),
            profiles={"work": {"type": "brownfield", "scale": scale, "risk": risk}},
        ),
    )
    return project


def satisfying_documents(project: Path, *, coverage=None):
    """Write the documents a `scale=large` / `risk=high` profile requires."""
    support.write_json(project / "evidence" / f"{EVD_ID}.json", support.evidence())
    support.write_json(project / "rdds" / "RDD-0001.json", support.rdd())
    support.write_json(
        project / "sdds" / "SDD-0001.json",
        support.sdd(requirements_coverage=coverage or []),
    )


def executable_task(**over):
    """A task `se execute` would really run (authorizes IMPLEMENT)."""
    task = support.task(status="READY", authorized_actions=["READ", "ANALYZE", "IMPLEMENT"])
    task.update(over)
    return task


def snapshot(project: Path) -> dict:
    """Content hash of every file in the project, to prove a command mutated nothing."""
    return {
        str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


def workflow(nodes, edges=None):
    return {
        "schema_version": "1",
        "workflow_id": WORKFLOW_ID,
        "project_id": "PRJ-TEST-001",
        "name": "Ceremony flow",
        "version": "1.0.0",
        "status": "DRAFT",
        "nodes": nodes,
        "edges": edges or [],
        "gates": [],
    }


def node(node_id, action):
    return {"node_id": node_id, "agent": "analyst", "action": action, "inputs": {}, "outputs": {}}


def completed(outputs=None):
    return {"status": "COMPLETED", "output": outputs or {}, "outputs": outputs or {}}


def failed(error="node failed"):
    return {"status": "FAILED", "error": error}


def write_workflow(project: Path, nodes, edges=None):
    support.write_json(project / "workflows" / f"{WORKFLOW_ID}.json", workflow(nodes, edges))


def engine_for(project: Path):
    """An engine whose project lookup resolves to the temporary project."""
    from se_core.orchestration.engine import OrchestrationEngine

    engine = OrchestrationEngine(root=project.parent)
    engine._find_project_dir = mock.MagicMock(return_value=project)
    return engine


def execute_with(engine, script, calls, *args, **kwargs):
    """Run engine.execute with AgentRunner.run replaced by a scripted stub."""
    from se_core.agents.runner import AgentRunner

    def fake_run(runner_self, action, inputs, context, max_tokens=None):
        calls.append(action)
        queue = script[action]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    with mock.patch.object(AgentRunner, "run", fake_run):
        return engine.execute(WORKFLOW_ID, "PRJ-TEST-001", *args, **kwargs)


# --------------------------------------------------------------------------- #
# 1. `se execute` is fail-closed
# --------------------------------------------------------------------------- #


class ExecuteCeremonyGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_execute_refuses_before_any_mutation(self):
        project = profiled_project(self.root / "p")
        support.write_json(project / "tasks" / "TASK-0001.json", executable_task())
        before = snapshot(project)

        code, out = support.run_cli("execute", "--project", str(project), "--json")

        self.assertEqual(code, 1, out)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("ceremony not satisfied", " ".join(payload["conflicts"]))
        # No mutation at all: not the task file, not evidence, not a receipt.
        self.assertEqual(snapshot(project), before)
        self.assertEqual(list((project / "evidence").glob("*.json")), [])
        self.assertEqual(list((project / "execution_receipts").glob("*.json")), [])
        task = json.loads((project / "tasks" / "TASK-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "READY")

    def test_execute_dry_run_is_blocked_too(self):
        project = profiled_project(self.root / "p")
        support.write_json(project / "tasks" / "TASK-0001.json", executable_task())
        before = snapshot(project)

        code, out = support.run_cli("execute", "--project", str(project), "--dry-run", "--json")

        self.assertEqual(code, 1, out)
        self.assertIn("ceremony not satisfied", out)
        self.assertEqual(snapshot(project), before)

    def test_unprofiled_project_keeps_current_behavior(self):
        project = support.make_project(self.root / "p")
        support.write_json(project / "tasks" / "TASK-0001.json", executable_task())

        code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")

        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["executed"], 1)
        self.assertEqual(len(payload["execution_receipts"]), 1)
        task = json.loads((project / "tasks" / "TASK-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(task["status"], "DONE")

    def test_profile_without_scale_or_risk_keeps_the_defaults(self):
        project = support.make_project(self.root / "p")
        support.write_json(
            project / "PROJECT.json",
            support.manifest(profiles={"work": {"type": "brownfield"}}),
        )
        support.write_json(project / "tasks" / "TASK-0001.json", executable_task())

        code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")

        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["status"], "PASS")

    def test_execute_passes_when_the_ceremony_is_met(self):
        project = profiled_project(self.root / "p")
        satisfying_documents(project)
        support.write_json(project / "tasks" / "TASK-0001.json", executable_task())

        code, out = support.run_cli("execute", "--project", str(project), "--task", "TASK-0001", "--json")

        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["status"], "PASS")


# --------------------------------------------------------------------------- #
# 2. `se orchestrate execute` starts no node when the ceremony fails
# --------------------------------------------------------------------------- #


class OrchestrateCeremonyGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _checkpoint_dir(self, project):
        return project / ".workflows" / "checkpoints"

    def test_engine_fails_before_starting_a_node(self):
        project = profiled_project(self.root / "p")
        write_workflow(project, [node("n1", "step1")])
        calls = []

        result = execute_with(engine_for(project), {"step1": [completed()]}, calls)

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("ceremony not satisfied", result["error"])
        self.assertTrue(result["ceremony"]["failures"])
        self.assertEqual(calls, [], "no node may start when the ceremony fails")
        self.assertEqual(self._checkpoint_dir(project).exists(), False)

    def test_engine_dry_run_is_blocked(self):
        project = profiled_project(self.root / "p")
        write_workflow(project, [node("n1", "step1")])
        calls = []

        result = execute_with(engine_for(project), {"step1": [completed()]}, calls, dry_run=True)

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["execution_order"], [])
        self.assertEqual(calls, [])
        self.assertEqual(self._checkpoint_dir(project).exists(), False)

    def test_resume_is_blocked_when_the_ceremony_no_longer_holds(self):
        project = profiled_project(self.root / "p")
        write_workflow(project, [node("n1", "step1")])
        checkpoint = self._checkpoint_dir(project)
        checkpoint.mkdir(parents=True)
        support.write_json(
            checkpoint / "CP-0001.json",
            {
                "schema_version": "1",
                "checkpoint_id": "CP-0001",
                "workflow_id": WORKFLOW_ID,
                "execution_id": "WEX-0001",
                "status": "FAILED",
                "completed_nodes": [],
                "node_results": {},
                "gate_results": {},
                "context": {},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            },
        )
        before = snapshot(project)
        calls = []

        result = execute_with(
            engine_for(project), {"step1": [completed()]}, calls,
            resume_from_checkpoint="CP-0001",
        )

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(calls, [])
        self.assertEqual(snapshot(project), before)

    def test_cli_reports_the_failure_and_starts_no_node(self):
        project = profiled_project(self.root / "p")
        write_workflow(project, [node("n1", "step1")])
        engine = engine_for(project)

        with mock.patch("se_core.orchestration.engine.OrchestrationEngine", return_value=engine):
            code, out = support.run_cli(
                "orchestrate", "execute", "--workflow", WORKFLOW_ID,
                "--project", str(project), "--json",
            )

        self.assertEqual(code, 1, out)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "FAILED")
        self.assertIn("ceremony not satisfied", payload["error"])
        self.assertFalse(self._checkpoint_dir(project).exists())

    def test_ceremony_satisfied_project_executes_and_checkpoints(self):
        project = profiled_project(self.root / "p")
        satisfying_documents(project)
        write_workflow(project, [node("n1", "step1")])
        calls = []

        result = execute_with(engine_for(project), {"step1": [completed({"a": 1})]}, calls)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(calls, ["step1"])
        self.assertTrue(any(self._checkpoint_dir(project).glob("CP-*.json")))

    def test_resume_still_works_once_the_ceremony_is_met(self):
        project = profiled_project(self.root / "p")
        satisfying_documents(project)
        write_workflow(project, [node("n1", "step1"), node("n2", "step2")], [{"from": "n1", "to": "n2"}])
        engine = engine_for(project)
        script = {"step1": [completed({"a": 1})], "step2": [failed(), completed({"b": 2})]}
        calls = []

        first = execute_with(engine, script, calls)
        self.assertEqual(first["status"], "FAILED")
        resume_id = sorted(self._checkpoint_dir(project).glob("CP-*.json"))[-1].stem
        second = execute_with(engine, script, calls, resume_from_checkpoint=resume_id)

        self.assertEqual(second["status"], "COMPLETED")
        self.assertEqual(calls.count("step1"), 1)
        self.assertEqual(calls.count("step2"), 2)

    def test_unprofiled_project_still_runs_and_checkpoints(self):
        project = support.make_project(self.root / "p")
        write_workflow(project, [node("n1", "step1")])
        calls = []

        result = execute_with(engine_for(project), {"step1": [completed()]}, calls)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(calls, ["step1"])


# --------------------------------------------------------------------------- #
# 3. Only valid, self-consistent receipts/SDDs satisfy the floor
# --------------------------------------------------------------------------- #


class DocumentValidityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = profiled_project(
            Path(self._tmp.name) / "p", scale="medium", risk="medium", criticality="low"
        )

    def _ceremony(self, *argv):
        return support.run_cli("ceremony", "--project", str(self.project), *argv)

    def test_placeholder_candidate_hash_is_not_a_receipt(self):
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(
            self.project / "rdds" / "RDD-0001.json",
            support.rdd(candidate={"kind": "commit", "ref": "0000000", "hash": "0" * 40}),
        )

        code, out = self._ceremony()

        self.assertEqual(code, 1, out)
        self.assertIn("placeholder", out)

    def test_receipt_with_dangling_evidence_is_not_a_receipt(self):
        support.write_json(
            self.project / "rdds" / "RDD-0001.json",
            support.rdd(evidence=[{"id": "EVD-9999", "claim": "Reviewed", "result": "PASS"}]),
        )

        code, out = self._ceremony()

        self.assertEqual(code, 1, out)
        self.assertIn("EVD-9999", out)

    def test_receipt_with_invalid_evidence_record_is_not_a_receipt(self):
        # The EVD exists but is not a valid EVD record.
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", {"id": EVD_ID})
        support.write_json(self.project / "rdds" / "RDD-0001.json", support.rdd())

        code, out = self._ceremony()

        self.assertEqual(code, 1, out)
        self.assertIn(EVD_ID, out)

    def test_internal_linked_change_must_resolve(self):
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(
            self.project / "rdds" / "RDD-0001.json", support.rdd(linked_change="TASK-9999")
        )

        code, out = self._ceremony()

        self.assertEqual(code, 1, out)
        self.assertIn("TASK-9999", out)

    def test_external_linked_change_is_not_an_internal_reference(self):
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(
            self.project / "rdds" / "RDD-0001.json",
            support.rdd(linked_change="34a906c6694b405f948dc5f1010cd2e29ba0bddf"),
        )

        code, out = support.run_cli(
            "validate", "--project", str(self.project)
        )

        self.assertEqual(code, 0, out)

    def test_internal_linked_change_resolves(self):
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(self.project / "tasks" / "TASK-0001.json", support.task())
        support.write_json(
            self.project / "rdds" / "RDD-0001.json", support.rdd(linked_change="TASK-0001")
        )

        code, out = support.run_cli(
            "validate", "--project", str(self.project)
        )

        self.assertEqual(code, 0, out)

    def test_sdd_coverage_must_resolve(self):
        project = profiled_project(Path(self._tmp.name) / "large")
        support.write_json(project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(project / "rdds" / "RDD-0001.json", support.rdd())
        support.write_json(
            project / "sdds" / "SDD-0001.json",
            support.sdd(requirements_coverage=["REQ-9999"]),
        )

        code, out = support.run_cli("ceremony", "--project", str(project))

        self.assertEqual(code, 1, out)
        self.assertIn("REQ-9999", out)

    # R2b: Cross-check EVD.result with RDD.evidence[].result
    def test_receipt_evidence_result_mismatch_is_rejected(self):
        # EVD says FAIL, but RDD claims PASS for the same evidence
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", support.evidence(result="FAIL"))
        support.write_json(
            self.project / "rdds" / "RDD-0001.json",
            support.rdd(evidence=[{"id": EVD_ID, "claim": "Reviewed", "result": "PASS"}]),
        )

        code, out = self._ceremony()

        self.assertEqual(code, 1, out)
        self.assertIn("result mismatch", out)
        self.assertIn("EVD has 'FAIL'", out)
        self.assertIn("receipt claims 'PASS'", out)

    # R3: RDD with terminal status (SUPERSEDED, ARCHIVED) cannot satisfy receipt_required
    def test_receipt_with_superseded_status_is_rejected(self):
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(
            self.project / "rdds" / "RDD-0001.json",
            support.rdd(status="SUPERSEDED", verdict="PASS"),
        )

        code, out = self._ceremony()

        self.assertEqual(code, 1, out)
        self.assertIn("SUPERSEDED", out)
        self.assertIn("terminal", out)

    def test_receipt_with_archived_status_is_rejected(self):
        support.write_json(self.project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(
            self.project / "rdds" / "RDD-0001.json",
            support.rdd(status="ARCHIVED", verdict="PASS"),
        )

        code, out = self._ceremony()

        self.assertEqual(code, 1, out)
        self.assertIn("ARCHIVED", out)
        self.assertIn("terminal", out)


# --------------------------------------------------------------------------- #
# 4. Attestation cannot be bypassed by creation or direct update
# --------------------------------------------------------------------------- #


class CreationAttestationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = support.make_project(Path(self._tmp.name) / "p")

    def new(self, kind, *extra):
        return support.run_cli("new", kind, "--project", str(self.project), *extra)

    def update(self, kind, record_id, *extra):
        return support.run_cli("update", kind, record_id, "--project", str(self.project), *extra)

    def test_sdd_cannot_be_created_approved(self):
        code, out = self.new("sdd", "--title", "Design", "--status", "APPROVED")

        self.assertEqual(code, 1, out)
        self.assertIn("cannot be created as APPROVED", out)
        self.assertEqual(list((self.project / "sdds").glob("*.json")), [])

    def test_sdd_cannot_be_created_implemented(self):
        code, out = self.new("sdd", "--title", "Design", "--status", "IMPLEMENTED")

        self.assertEqual(code, 1, out)
        self.assertEqual(list((self.project / "sdds").glob("*.json")), [])

    def test_rdd_cannot_be_created_approved(self):
        code, out = self.new("rdd", "--title", "Receipt", "--status", "APPROVED")

        self.assertEqual(code, 1, out)
        self.assertEqual(list((self.project / "rdds").glob("*.json")), [])

    def test_sdd_status_change_requires_a_human_and_is_logged(self):
        self.assertEqual(self.new("sdd", "--title", "Design")[0], 0)

        code, out = self.update("sdd", "SDD-0001", "--set", "status=APPROVED")
        self.assertEqual(code, 1, out)
        self.assertIn("controlled", out)

        code, out = self.update("sdd", "SDD-0001", "--set", "status=APPROVED", "--by", "owner")
        self.assertEqual(code, 0, out)
        record = json.loads((self.project / "sdds" / "SDD-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "APPROVED")
        entries = [
            json.loads(line)
            for line in (self.project / "mutation-log.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(any(e.get("by") == "owner" and e.get("record_type") == "sdd" for e in entries))

    def test_rdd_verdict_cannot_change_without_a_human(self):
        self.assertEqual(self.new("rdd", "--title", "Receipt")[0], 0)

        code, out = self.update("rdd", "RDD-0001", "--set", "verdict=FAIL")
        self.assertEqual(code, 1, out)
        self.assertIn("controlled", out)

    def test_rdd_verdict_change_with_a_human_is_logged(self):
        self.assertEqual(self.new("rdd", "--title", "Receipt")[0], 0)

        code, out = self.update("rdd", "RDD-0001", "--set", "verdict=FAIL", "--by", "reviewer")
        self.assertEqual(code, 0, out)
        record = json.loads((self.project / "rdds" / "RDD-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(record["verdict"], "FAIL")
        log = (self.project / "mutation-log.jsonl").read_text(encoding="utf-8")
        self.assertIn('"by": "reviewer"', log)

    def test_odd_status_is_not_governed_by_analogy(self):
        from se_core.commands import CONTROLLED_FIELDS

        self.assertNotIn(("odd", "status"), CONTROLLED_FIELDS)
        self.assertEqual(self.new("odd", "--title", "Design", "--problem", "Problem")[0], 0)
        code, out = self.update("odd", "ODD-0001", "--set", "status=APPROVED")
        self.assertEqual(code, 0, out)


# --------------------------------------------------------------------------- #
# 5. `se validate --project` and `se review` see the invalid cases
# --------------------------------------------------------------------------- #


class ValidateAndReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_validate_and_review_report_a_dangling_coverage_reference(self):
        project = profiled_project(self.root / "p")
        support.write_json(project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(project / "rdds" / "RDD-0001.json", support.rdd())
        support.write_json(
            project / "sdds" / "SDD-0001.json",
            support.sdd(requirements_coverage=["REQ-9999"]),
        )

        code, out = support.run_cli("validate", "--project", str(project))
        self.assertEqual(code, 1, out)
        self.assertIn("REQ-9999", out)

        code, out = support.run_cli("review", "--project", str(project))
        self.assertEqual(code, 1, out)
        self.assertIn("unresolved reference REQ-9999", out)

    def test_review_reports_a_dangling_receipt_evidence(self):
        project = support.make_project(self.root / "p")
        support.write_json(project / "rdds" / "RDD-0001.json", support.rdd())

        code, out = support.run_cli("review", "--project", str(project))

        self.assertEqual(code, 1, out)
        self.assertIn("unresolved reference EVD-0001", out)

    def test_validate_rejects_placeholder_receipt(self):
        project = profiled_project(self.root / "p", scale="medium", criticality="low")
        support.write_json(project / "evidence" / f"{EVD_ID}.json", support.evidence())
        support.write_json(
            project / "rdds" / "RDD-0001.json",
            support.rdd(candidate={"kind": "commit", "ref": "0000000", "hash": "0" * 40}),
        )

        code, out = support.run_cli("validate", "--project", str(project))

        self.assertEqual(code, 1, out)
        self.assertIn("placeholder", out)


if __name__ == "__main__":
    unittest.main()
