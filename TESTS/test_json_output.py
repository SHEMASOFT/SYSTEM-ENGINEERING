"""AUTO-16 JSON output tests (SE-AUTOMATION-001B-B1).

Hermetic: read-only commands only; no network; temporary projects for --project.
Verifies the ``se.report/1`` envelope, backward compatibility of the human output,
determinism, JSON error semantics, and the absence of context reconstruction.
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


def _load(out):
    return json.loads(out)


class JsonOutputTests(unittest.TestCase):
    def test_doctor_human_output_unchanged(self):
        code, out = support.run_cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("Doctor summary:", out)
        self.assertFalse(out.lstrip().startswith("{"))

    def test_validate_human_output_unchanged(self):
        code, out = support.run_cli("validate")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("VALIDATE:"))
        self.assertFalse(out.lstrip().startswith("{"))

    def test_doctor_json_envelope(self):
        code, out = support.run_cli("doctor", "--json")
        self.assertEqual(code, 0, out)
        data = _load(out)
        self.assertEqual(data["report"], REPORT_ID)
        self.assertEqual(data["operation"], "doctor")
        self.assertIn(data["status"], {"PASS", "WARN", "FAIL"})
        self.assertTrue(set(ROOT_KEYS).issubset(data.keys()))
        self.assertIn("observed_at", data["observation"])
        self.assertNotIn("\x1b", out)

    def test_validate_json_envelope(self):
        code, out = support.run_cli("validate", "--json")
        self.assertEqual(code, 0, out)
        data = _load(out)
        self.assertEqual(data["report"], REPORT_ID)
        self.assertEqual(data["operation"], "validate")
        self.assertTrue(set(ROOT_KEYS).issubset(data.keys()))
        self.assertNotIn("\x1b", out)

    def test_review_json_clean_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, out = support.run_cli("review", "--project", str(project), "--json")
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["operation"], "review")
            self.assertEqual(data["status"], "PASS")
            self.assertIn("counts", data["details"])

    def test_gate_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, out = support.run_cli(
                "gate", "--project", str(project), "--gate", "G0", "--json"
            )
            self.assertEqual(code, 0, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["gate"]["id"], "G0")
            self.assertEqual(data["gate"]["status"], "PASS")
            self.assertIsInstance(data["gate"]["conditions"], list)

    def test_capabilities_json(self):
        code, out = support.run_cli("capabilities", "--json")
        self.assertEqual(code, 0, out)
        data = _load(out)
        self.assertEqual(data["report"], REPORT_ID)
        self.assertEqual(data["operation"], "capabilities")
        self.assertIn("registry", data["capabilities"])

    def test_error_in_json_mode_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope"
            code, out = support.run_cli("review", "--project", str(missing), "--json")
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")
            self.assertTrue(data["conflicts"])

            code, out = support.run_cli(
                "gate", "--project", str(missing), "--gate", "G0", "--json"
            )
            self.assertEqual(code, 1, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")

    def test_gate_unknown_gate_json_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            code, out = support.run_cli(
                "gate", "--project", str(project), "--gate", "G42", "--json"
            )
            self.assertEqual(code, 2, out)
            data = _load(out)
            self.assertEqual(data["report"], REPORT_ID)
            self.assertEqual(data["status"], "FAIL")

    def test_json_is_deterministic_except_observation(self):
        _, a = support.run_cli("doctor", "--json")
        _, b = support.run_cli("doctor", "--json")
        da, db = _load(a), _load(b)
        da.pop("observation")
        db.pop("observation")
        self.assertEqual(da, db)

    def test_no_context_reconstruction_for_doctor(self):
        _, out = support.run_cli("doctor", "--json")
        data = _load(out)
        self.assertEqual(data["requirements"], [])
        self.assertEqual(data["tasks"], [])
        self.assertEqual(data["evidence"], [])
        self.assertEqual(data["artifacts"], [])

    def test_gate_json_does_not_dump_project_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_full_project(Path(tmp) / "p")
            code, out = support.run_cli(
                "gate", "--project", str(project), "--gate", "G6", "--json"
            )
            data = _load(out)
            self.assertEqual(data["requirements"], [])
            self.assertEqual(data["tasks"], [])
            self.assertEqual(data["evidence"], [])
            self.assertEqual(data["artifacts"], [])

    def test_human_default_not_json_for_all_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = support.make_project(Path(tmp) / "p")
            for argv in (
                ("doctor",),
                ("validate",),
                ("review", "--project", str(project)),
                ("gate", "--project", str(project), "--gate", "G0"),
                ("capabilities",),
            ):
                code, out = support.run_cli(*argv)
                self.assertFalse(out.lstrip().startswith("{"), argv)
                self.assertNotIn('"report": "se.report/1"', out, argv)


if __name__ == "__main__":
    unittest.main()
