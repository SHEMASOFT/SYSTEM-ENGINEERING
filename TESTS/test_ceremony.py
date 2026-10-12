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


if __name__ == "__main__":
    unittest.main()
