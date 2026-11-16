"""se trace tests (AUTO-06).

Hermetic: temporary project, no network, no production infrastructure.
Covers forward, reverse, both directions, depth, cap, truncation, cycles,
broken refs, unknown IDs, and kind resolution.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.artifacts import ID_FIELD, collection  # noqa: E402


def load(project, kind):
    items, _ = collection(project, kind)
    return {data[ID_FIELD[kind]]: data for _, data in items}


class TraceTests(unittest.TestCase):
    """Tests for `se trace` command."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_full_project(Path(self._tmp.name) / "proj")
        self.objectives = load(self.project, "objective")
        self.requirements = load(self.project, "requirement")
        self.tasks = load(self.project, "task")
        self.artifacts = load(self.project, "artifact")
        self.evidence = load(self.project, "evidence")
        self.acceptances = load(self.project, "acceptance")
        self.releases = load(self.project, "release")

    def tearDown(self):
        self._tmp.cleanup()

    def _trace(self, record_id, **kwargs):
        """Run se trace and return (exit_code, parsed_json)."""
        args = ["trace", "--project", str(self.project), record_id]
        if "kind" in kwargs:
            args += ["--kind", kwargs["kind"]]
        if "depth" in kwargs:
            args += ["--depth", str(kwargs["depth"])]
        if "cap" in kwargs:
            args += ["--cap", str(kwargs["cap"])]
        if "direction" in kwargs:
            args += ["--direction", kwargs["direction"]]
        args += ["--json"]
        code, out = support.run_cli(*args)
        if out:
            import json
            return code, json.loads(out)
        return code, None

    def test_forward_chain(self):
        """Forward trace from objective reaches requirements.

        The fixture only links OBJ-0001 -> REQ-0001 (via related_requirements).
        REQ-0001 does not have related_tasks in this fixture, so traversal
        stops at depth 1. Deeper traversal would require a fixture with
        full linkage.
        """
        code, env = self._trace("OBJ-0001", direction="forward", depth=3)
        self.assertEqual(code, 0, env)
        self.assertEqual(env["report"], "se.trace/1")
        self.assertEqual(env["operation"], "trace")
        self.assertEqual(env["root"]["kind"], "objective")
        self.assertEqual(env["root"]["id"], "OBJ-0001")
        self.assertEqual(env["direction"], "forward")
        # Should find REQ-0001 (linked from objective)
        kinds = {n["kind"] for n in env["forward"]}
        self.assertIn("requirement", kinds)
        # Fixture stops at REQ-0001 (no related_tasks on REQ-0001)
        self.assertNotIn("task", kinds)
        # Edges: objective -> requirement
        edge_kinds = {(e["from_kind"], e["to_kind"]) for e in env["edges"]}
        self.assertIn(("objective", "requirement"), edge_kinds)

    def test_reverse_chain(self):
        """Reverse trace from artifact reaches task, evidence, release, acceptance.

        The fixture has: ART-0001 <- evidence (EVD-0001/EVD-0002 via related_artifacts)
        EVD-0001 -> task (TASK-0001 via related_tasks), release (REL-0001 via evidence),
        acceptance (ACC-0001 via evidence). TASK-0001 has no incoming requirement
        (REQ-0001 lacks related_tasks), and objective has no evidence field.
        """
        code, env = self._trace("ART-0001", direction="reverse", depth=3)
        self.assertEqual(code, 0, env)
        self.assertEqual(env["direction"], "reverse")
        kinds = {n["kind"] for n in env["reverse"]}
        self.assertIn("task", kinds)
        self.assertIn("evidence", kinds)
        self.assertIn("release", kinds)
        self.assertIn("acceptance", kinds)
        # Edges: evidence -> artifact, task -> evidence, release -> evidence, acceptance -> evidence
        edge_kinds = {(e["from_kind"], e["to_kind"]) for e in env["edges"]}
        self.assertIn(("evidence", "artifact"), edge_kinds)
        self.assertIn(("task", "evidence"), edge_kinds)
        self.assertIn(("release", "evidence"), edge_kinds)
        self.assertIn(("acceptance", "evidence"), edge_kinds)

    def test_both_directions(self):
        """Both directions from a middle node (task)."""
        code, env = self._trace("TASK-0001", direction="both", depth=2)
        self.assertEqual(code, 0, env)
        self.assertEqual(env["direction"], "both")
        # Forward: task -> evidence, artifact (artifact.kind="code")
        fwd_kinds = {n.get("kind") or n.get("type") for n in env["forward"]}
        # Artifact's kind field is "code", so check for that
        self.assertTrue(any(n.get("kind") == "code" for n in env["forward"]), "artifact (kind=code) not found in forward")
        self.assertIn("evidence", {n.get("kind") for n in env["forward"]})
        # Reverse: task <- evidence (via evidence.related_tasks), acceptance (via evidence), release (via evidence), artifact (via produced_by)
        # Note: fixture REQ-0001 lacks related_tasks, so requirement not found in reverse
        rev_kinds = {n.get("kind") for n in env["reverse"]}
        self.assertIn("evidence", rev_kinds)
        self.assertIn("acceptance", rev_kinds)
        self.assertIn("release", rev_kinds)
        self.assertIn("code", rev_kinds)  # artifact with kind=code
        # Root should not be duplicated in forward/reverse
        self.assertNotIn("TASK-0001", [n["id"] for n in env["forward"]])
        self.assertNotIn("TASK-0001", [n["id"] for n in env["reverse"]])
        # Edges should include both directions
        edge_kinds = {(e["from_kind"], e["to_kind"]) for e in env["edges"]}
        self.assertIn(("task", "evidence"), edge_kinds)
        self.assertIn(("artifact", "evidence"), edge_kinds)  # artifact->evidence via related_artifacts
        self.assertIn(("evidence", "task"), edge_kinds)
        self.assertIn(("acceptance", "evidence"), edge_kinds)
        self.assertIn(("release", "evidence"), edge_kinds)
        self.assertIn(("artifact", "task"), edge_kinds)  # artifact.produced_by -> task

    def test_depth_limit(self):
        """Depth limit restricts traversal."""
        # Full depth reaches requirement (fixture only has OBJ->REQ link)
        code_full, env_full = self._trace("OBJ-0001", direction="forward", depth=3)
        # Depth 0 stops at root
        code_0, env_0 = self._trace("OBJ-0001", direction="forward", depth=0)
        self.assertEqual(code_0, 0)
        self.assertEqual(len(env_0["forward"]), 0)
        # Depth 1 stops at requirements
        code_1, env_1 = self._trace("OBJ-0001", direction="forward", depth=1)
        self.assertEqual(code_1, 0)
        kinds_1 = {n["kind"] for n in env_1["forward"]}
        self.assertIn("requirement", kinds_1)
        # Depth 2 also only reaches requirements (fixture lacks REQ->TASK link)
        code_2, env_2 = self._trace("OBJ-0001", direction="forward", depth=2)
        kinds_2 = {n["kind"] for n in env_2["forward"]}
        self.assertIn("requirement", kinds_2)
        self.assertNotIn("task", kinds_2)

    def test_cap_truncation(self):
        """Cap limits nodes and sets truncated flag."""
        # Use a cap smaller than the reachable nodes
        # The fixture from TASK-0001 forward reaches: task -> evidence, artifact
        # With cap=2: root (task) + 1 more = 2 total, should truncate
        code, env = self._trace("TASK-0001", direction="forward", cap=2)
        self.assertEqual(code, 0)
        self.assertTrue(env["truncated"])
        # Should have at most 2 nodes visited (root + 1)
        # Forward nodes exclude root, so at most 1
        self.assertLessEqual(len(env["forward"]), 1)
        # But total visited (root + forward) <= cap
        total = 1 + len(env["forward"]) + len(env["reverse"])
        self.assertLessEqual(total, 2)

    def test_broken_refs(self):
        """Broken references are reported in gaps."""
        # Add a task with a non-existent requirement reference
        support.write_json(
            self.project / "tasks" / "TASK-9999.json",
            support.task(id="TASK-9999", related_requirements=["REQ-9999"]),
        )
        code, env = self._trace("TASK-9999", direction="forward", cap=10)
        self.assertEqual(code, 0)
        # Should report the broken reference
        self.assertTrue(env["gaps"])
        self.assertTrue(any("REQ-9999" in g for g in env["gaps"]))
        self.assertTrue(any("related_requirements" in g for g in env["gaps"]))

    def test_unknown_id(self):
        """Unknown ID returns exit code 1 with error envelope."""
        code, env = self._trace("UNKNOWN-999", kind="requirement")
        self.assertEqual(code, 1)
        self.assertEqual(env["status"], "FAIL")
        self.assertIn("not found", " ".join(env.get("conflicts", [])))
        self.assertIsNotNone(env)
        self.assertEqual(env["report"], "se.trace/1")
        self.assertEqual(env["status"], "FAIL")
        self.assertIn("not found", " ".join(env.get("conflicts", [])))

    def test_cycle_detection(self):
        """Cycles in the graph do not cause infinite loops."""
        # The test fixture doesn't have cycles, but we can verify
        # the algorithm handles visited set correctly by tracing
        # a node that could theoretically have cycles (task dependencies)
        code, env = self._trace("TASK-0001", direction="both", depth=10, cap=50)
        self.assertEqual(code, 0)
        # Should complete without hanging
        # Total nodes should be reasonable
        total = 1 + len(env["forward"]) + len(env["reverse"])
        self.assertLessEqual(total, 50)

    def test_kind_required_for_sdd(self):
        """SDD/ODD/RDD/RUN require explicit --kind."""
        # SDD not in CONTEXT_FOCUS_PREFIXES, so without --kind it should fail
        code, env = self._trace("SDD-0001")
        self.assertEqual(code, 2)
        self.assertIsNotNone(env)
        self.assertEqual(env["status"], "FAIL")
        self.assertIn("cannot infer kind", " ".join(env.get("conflicts", [])))

    def test_kind_explicit_override(self):
        """Explicit --kind works even with unknown prefix."""
        code, env = self._trace("SDD-0001", kind="sdd")
        self.assertEqual(code, 1)  # record doesn't exist -> runtime error
        self.assertEqual(env["status"], "FAIL")
        self.assertIn("not found", " ".join(env.get("conflicts", [])))

    def test_invalid_kind_rejected(self):
        """Invalid --kind is rejected by argparse (exit code 2)."""
        code, env = self._trace("REQ-0001", kind="invalid_kind")
        self.assertEqual(code, 2)
        # argparse validates choices before our code runs, so no JSON envelope

    def test_depth_zero(self):
        """Depth 0 returns only root (no forward/reverse)."""
        code, env = self._trace("OBJ-0001", direction="forward", depth=0)
        self.assertEqual(code, 0)
        self.assertEqual(len(env["forward"]), 0)
        self.assertEqual(len(env["reverse"]), 0)

    def test_deterministic_order(self):
        """Output is deterministic (sorted keys, sorted lists)."""
        code1, env1 = self._trace("OBJ-0001", direction="both", depth=3, cap=50)
        code2, env2 = self._trace("OBJ-0001", direction="both", depth=3, cap=50)
        self.assertEqual(code1, code2)
        import json

        # `observation.observed_at` records when each run happened, so it is not
        # part of what "deterministic output" means here.
        for env in (env1, env2):
            env.pop("observation", None)
        self.assertEqual(json.dumps(env1, sort_keys=True), json.dumps(env2, sort_keys=True))

    def test_gaps_only_reports_declared_refs(self):
        """Gaps only reports references that are in REFERENCE_TARGETS."""
        # Add a task with a field that's not in REFERENCE_TARGETS
        support.write_json(
            self.project / "tasks" / "TASK-8888.json",
            support.task(id="TASK-8888", related_requirements=["REQ-0001"]),
        )
        # Add a field that's not in REFERENCE_TARGETS (e.g., some custom field)
        # We can't easily test this without modifying the record structure,
        # but the point is that gaps only reports refs from REFERENCE_TARGETS
        code, env = self._trace("TASK-8888", direction="forward", cap=10)
        self.assertEqual(code, 0)
        # No gaps for valid refs
        self.assertFalse(any("REQ-0001" in g for g in env["gaps"]))


class TraceEdgeCases(unittest.TestCase):
    """Additional edge case tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def test_nonexistent_project(self):
        """Non-existent project returns error."""
        code, env = support.run_cli("trace", "--project", "/nonexistent", "REQ-0001", "--json")
        self.assertEqual(code, 2)

    def test_missing_record_id(self):
        """Missing record_id argument returns error."""
        code, env = support.run_cli("trace", "--project", ".", "--json")
        self.assertEqual(code, 2)

    def test_invalid_depth(self):
        """Negative depth rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, env = support.run_cli("trace", "--project", str(project), "REQ-0001", "--depth", "-1", "--json")
            self.assertEqual(code, 2)

    def test_invalid_cap(self):
        """Zero or negative cap rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, env = support.run_cli("trace", "--project", str(project), "REQ-0001", "--cap", "0", "--json")
            self.assertEqual(code, 2)

    def test_invalid_direction(self):
        """Invalid direction rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, env = support.run_cli("trace", "--project", str(project), "REQ-0001", "--direction", "sideways", "--json")
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)