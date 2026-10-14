"""Ceremony policy: the declared work profile turns work modes into enforceable requirements."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import ceremony  # noqa: E402
from se_core.artifacts import WORKSPACE_DIRS  # noqa: E402
from se_core.commands import _master_version  # noqa: E402


class RequirementsTests(unittest.TestCase):
    def test_unprofiled_project_requires_nothing(self):
        req = ceremony.effective_requirements(support.manifest())
        self.assertFalse(req["profile_declared"])
        self.assertFalse(req["spec_required"])
        self.assertFalse(req["receipt_required"])

    def test_profile_without_scale_or_risk_keeps_defaults(self):
        req = ceremony.effective_requirements(support.manifest(profiles={"work": {"type": "brownfield"}}))
        self.assertTrue(req["profile_declared"])
        self.assertFalse(req["spec_required"])
        self.assertFalse(req["receipt_required"])

    def test_medium_scale_requires_a_receipt_only(self):
        req = ceremony.effective_requirements(support.manifest(profiles={"work": {"scale": "medium"}}))
        self.assertTrue(req["receipt_required"])
        self.assertFalse(req["spec_required"])

    def test_large_scale_requires_spec_and_receipt(self):
        req = ceremony.effective_requirements(support.manifest(profiles={"work": {"scale": "large"}}))
        self.assertTrue(req["spec_required"])
        self.assertTrue(req["receipt_required"])

    def test_high_risk_requires_spec_and_receipt(self):
        req = ceremony.effective_requirements(support.manifest(profiles={"work": {"risk": "high"}}))
        self.assertTrue(req["spec_required"])
        self.assertTrue(req["receipt_required"])

    def test_medium_risk_requires_a_receipt_only(self):
        req = ceremony.effective_requirements(support.manifest(profiles={"work": {"risk": "medium"}}))
        self.assertTrue(req["receipt_required"])
        self.assertFalse(req["spec_required"])

    def test_high_criticality_requires_spec_and_receipt(self):
        req = ceremony.effective_requirements(
            support.manifest(criticality="high", profiles={"work": {"type": "greenfield"}})
        )
        self.assertTrue(req["spec_required"])
        self.assertTrue(req["receipt_required"])

    def test_critical_criticality_requires_spec_and_receipt(self):
        req = ceremony.effective_requirements(
            support.manifest(criticality="critical", profiles={"work": {"type": "greenfield"}})
        )
        self.assertTrue(req["spec_required"])
        self.assertTrue(req["receipt_required"])


class CheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)

    def write_manifest(self, **profile):
        manifest = support.manifest(profiles={"work": profile}) if profile else support.manifest()
        support.write_json(self.project / "PROJECT.json", manifest)

    def add_sdd(self, status="APPROVED"):
        support.write_json(self.project / "sdds" / "SDD-0001.json", {"sdd_id": "SDD-0001", "status": status})

    def add_rdd(self, verdict="PASS"):
        support.write_json(self.project / "rdds" / "RDD-0001.json", {"rdd_id": "RDD-0001", "verdict": verdict})

    def test_unprofiled_project_never_fails(self):
        self.write_manifest()
        result = ceremony.check_project_ceremony(self.project)
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["notes"])

    def test_large_profile_without_documents_fails(self):
        self.write_manifest(scale="large")
        self.assertEqual(len(ceremony.check_project_ceremony(self.project)["failures"]), 2)

    def test_large_profile_with_documents_passes(self):
        self.write_manifest(scale="large")
        self.add_sdd()
        self.add_rdd()
        self.assertEqual(ceremony.check_project_ceremony(self.project)["failures"], [])

    def test_draft_sdd_does_not_satisfy_spec_required(self):
        self.write_manifest(scale="large")
        self.add_sdd(status="DRAFT")
        self.add_rdd()
        failures = ceremony.check_project_ceremony(self.project)["failures"]
        self.assertEqual(len(failures), 1)
        self.assertIn("SDD", failures[0])

    def test_failing_receipt_verdict_is_reported(self):
        self.write_manifest(scale="medium")
        self.add_rdd(verdict="FAIL")
        failures = ceremony.check_project_ceremony(self.project)["failures"]
        self.assertEqual(len(failures), 1)
        self.assertIn("RDD", failures[0])

    def test_missing_manifest_raises(self):
        with self.assertRaises(FileNotFoundError):
            ceremony.check_project_ceremony(self.project)


class ValidationIntegrationTests(unittest.TestCase):
    """The policy drives `se validate --project`, not just a standalone report."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        for directory in WORKSPACE_DIRS:
            (self.project / directory).mkdir(parents=True, exist_ok=True)
        support.write_json(
            self.project / "PROJECT.json",
            support.manifest(
                master_system_version=_master_version(),
                profiles={"work": {"scale": "large", "risk": "high"}},
            ),
        )

    def test_validate_refuses_a_profile_without_its_documents(self):
        code, out = support.run_cli("validate", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("ceremony:", out)

    def test_validate_passes_once_the_documents_exist(self):
        self.assertEqual(
            support.run_cli("new", "sdd", "--project", str(self.project), "--title", "Design")[0], 0
        )
        sdd_path = self.project / "sdds" / "SDD-0001.json"
        sdd = json.loads(sdd_path.read_text(encoding="utf-8"))
        sdd["status"] = "APPROVED"
        sdd_path.write_text(json.dumps(sdd), encoding="utf-8")
        self.assertEqual(
            support.run_cli("new", "rdd", "--project", str(self.project), "--title", "Receipt")[0], 0
        )
        code, out = support.run_cli("validate", "--project", str(self.project))
        self.assertEqual(code, 0, out)


class CeremonyCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        support.write_json(
            self.project / "PROJECT.json",
            support.manifest(profiles={"work": {"scale": "large"}}),
        )

    def test_cli_reports_fail_and_its_json_envelope(self):
        code, out = support.run_cli("ceremony", "--project", str(self.project), "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["report"], "se.report/1")
        self.assertEqual(data["operation"], "ceremony")
        self.assertEqual(data["status"], "FAIL")
        self.assertTrue(data["conflicts"])

    def test_cli_is_pass_when_met(self):
        support.write_json(self.project / "sdds" / "SDD-0001.json", {"sdd_id": "SDD-0001", "status": "APPROVED"})
        support.write_json(self.project / "rdds" / "RDD-0001.json", {"rdd_id": "RDD-0001", "verdict": "PASS"})
        code, out = support.run_cli("ceremony", "--project", str(self.project))
        self.assertEqual(code, 0, out)
        self.assertIn("CEREMONY: PASS", out)


class PolicySchemaAlignmentTests(unittest.TestCase):
    """The ceremony policy must only accept statuses the schemas can actually hold.

    `spec_status_acceptable` listed `ACCEPTED` and `RELEASED`, which are not in the
    SDD status enum: no SDD record can ever carry them, so the policy advertised two
    dead paths (and printed them in the failure message). Nothing cross-checked the
    two, which is how the drift survived. These tests are that cross-check: every
    accepted value must exist in the schema it refers to, and the in-code default
    must agree with the policy file it shadows.
    """

    def sdd_status_enum(self):
        return support.schemas()["sdd"]["properties"]["status"]["enum"]

    def rdd_verdict_enum(self):
        return support.schemas()["rdd"]["properties"]["verdict"]["enum"]

    def policy_file(self):
        with (support.REPO_ROOT / "CORE" / "policies" / "ceremony.json").open(encoding="utf-8") as fh:
            return json.load(fh)

    def test_spec_statuses_are_reachable_in_the_sdd_schema(self):
        acceptable = ceremony.load_policy()["spec_status_acceptable"]
        self.assertTrue(acceptable, "the policy must accept at least one status")
        unreachable = sorted(set(acceptable) - set(self.sdd_status_enum()))
        self.assertEqual(
            unreachable, [],
            f"spec_status_acceptable declares statuses the SDD schema forbids: {unreachable}",
        )

    def test_receipt_verdicts_are_reachable_in_the_rdd_schema(self):
        acceptable = ceremony.load_policy()["receipt_verdicts_acceptable"]
        self.assertTrue(acceptable, "the policy must accept at least one verdict")
        unreachable = sorted(set(acceptable) - set(self.rdd_verdict_enum()))
        self.assertEqual(
            unreachable, [],
            f"receipt_verdicts_acceptable declares verdicts the RDD schema forbids: {unreachable}",
        )

    def test_policy_file_and_builtin_default_agree(self):
        policy = self.policy_file()
        for key in ("spec_status_acceptable", "receipt_verdicts_acceptable"):
            self.assertEqual(
                policy[key], ceremony._DEFAULT_POLICY[key],
                f"{key} drifted between CORE/policies/ceremony.json and ceremony._DEFAULT_POLICY",
            )

    def test_requirement_message_advertises_only_reachable_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            support.write_json(project / "PROJECT.json", support.manifest(profiles={"work": {"scale": "large"}}))
            support.write_json(project / "sdds" / "SDD-0001.json", {"sdd_id": "SDD-0001", "status": "DRAFT"})
            support.write_json(project / "rdds" / "RDD-0001.json", {"rdd_id": "RDD-0001", "verdict": "PASS"})

            result = ceremony.check_project_ceremony(project)

        self.assertTrue(result["failures"])
        message = " ".join(result["failures"])
        for forbidden in ("ACCEPTED", "RELEASED"):
            self.assertNotIn(
                forbidden, message,
                f"the failure message must not advertise the unreachable status {forbidden}",
            )


if __name__ == "__main__":
    unittest.main()
