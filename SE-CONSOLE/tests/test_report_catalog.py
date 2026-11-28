"""T17: the console's report catalog is read-only and argv-restricted."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE_ROOT = os.path.dirname(HERE)
sys.path.insert(0, CONSOLE_ROOT)

from console import api, reports, se_cli  # noqa: E402

PROJECT = "PROJECTS/demo"


class ReportCatalogTests(unittest.TestCase):
    def test_every_declared_report_builds_an_exact_argv(self):
        cases = {
            "health": ({"project": PROJECT}, ["health", "--project", PROJECT]),
            "verify": ({"project": PROJECT}, ["verify", "--project", PROJECT]),
            "gate": (
                {"project": PROJECT, "gate": "G0"},
                ["gate", "--project", PROJECT, "--gate", "G0"],
            ),
            "plan": ({"project": PROJECT}, ["plan", "--project", PROJECT]),
        }
        for report, (params, expected) in cases.items():
            with self.subTest(report=report):
                self.assertEqual(reports.build_argv(report, params), expected)
                self.assertTrue(reports.is_allowed_readonly(expected))

    def test_unknown_and_mutating_reports_are_refused(self):
        for report in ("explore", "init", "nope"):
            with self.subTest(report=report), self.assertRaises(reports.Refused):
                reports.build_argv(report, {"project": PROJECT})

    def test_plan_cannot_request_task_creation(self):
        with self.assertRaises(reports.Refused):
            reports.build_argv("plan", {"project": PROJECT, "create_tasks": "true"})
        self.assertFalse(
            reports.is_allowed_readonly(["plan", "--project", PROJECT, "--create-tasks"])
        )

    def test_project_traversal_is_refused(self):
        with self.assertRaises(reports.Refused):
            reports.build_argv("verify", {"project": "PROJECTS/../secret"})

    def test_gate_and_scope_values_are_validated(self):
        with self.assertRaises(reports.Refused):
            reports.build_argv("gate", {"project": PROJECT, "gate": "--force"})
        with self.assertRaises(reports.Refused):
            reports.build_argv("health", {"project": PROJECT, "scope": "anything"})

    def test_extra_flags_cannot_be_smuggled_into_a_valid_argv(self):
        argv = reports.build_argv("verify", {"project": PROJECT})
        self.assertFalse(reports.is_allowed_readonly(argv + ["--force", "yes"]))
        self.assertFalse(reports.is_allowed_readonly(["verify", "--project"]))

    def test_api_report_relays_the_envelope_and_a_refusal(self):
        envelope = {"report": "se.report/1", "status": "PASS"}
        with mock.patch.object(
            se_cli, "run_se", return_value=(envelope, {"argv": ["se", "verify"]})
        ) as run:
            status, body = api.api_report({"report": "verify", "project": PROJECT})
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "PASS")
            self.assertEqual(body["report_request"], "verify")
            run.assert_called_once_with(["verify", "--project", PROJECT], timeout=120)

        status, body = api.api_report({"report": "explore", "project": PROJECT})
        self.assertEqual(status, 400)
        self.assertIn("not in catalog", body["message"])

    def test_run_se_accepts_only_the_exact_report_argv(self):
        import subprocess

        completed = subprocess.CompletedProcess(
            ["se"], 0, '{"report":"se.report/1","status":"PASS"}', ""
        )
        with mock.patch.object(se_cli.subprocess, "run", return_value=completed) as run:
            envelope, _ = se_cli.run_se(["plan", "--project", PROJECT])
            self.assertEqual(envelope["status"], "PASS")
            self.assertEqual(run.call_args[0][0][2:], ["plan", "--project", PROJECT, "--json"])
        with self.assertRaises(se_cli.SeError):
            se_cli.run_se(["plan", "--project", PROJECT, "--create-tasks"])


if __name__ == "__main__":
    unittest.main()
