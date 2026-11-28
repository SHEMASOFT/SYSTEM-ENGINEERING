"""T12: `se setup` sequences existing commands without reimplementing them."""

from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import setup  # noqa: E402


class DetectHarnessTests(unittest.TestCase):
    def test_detects_each_declared_artifact(self):
        for harness, dirs in setup.HARNESS_DIRS.items():
            with self.subTest(harness=harness), __import__("tempfile").TemporaryDirectory() as tmp:
                for directory in dirs:
                    (Path(tmp) / directory).mkdir()
                self.assertEqual(setup.detect_harness(tmp), harness)

    def test_empty_tree_defaults_to_opencode(self):
        with __import__("tempfile").TemporaryDirectory() as tmp:
            self.assertEqual(setup.detect_harness(tmp), "opencode")


class BuildStepsTests(unittest.TestCase):
    def test_dry_run_reaches_install_and_adapter(self):
        steps = dict(setup.build_steps("/proj", "deepseek", True))
        self.assertIn("--dry-run", steps["install"])
        self.assertIn("--dry-run", steps["adapter"])
        self.assertEqual(steps["adapter"], ["adapter", "deepseek", "--dry-run"])
        self.assertEqual(steps["doctor"], ["doctor"])

    def test_apply_does_not_pass_dry_run(self):
        steps = dict(setup.build_steps("/proj", "opencode", False))
        self.assertNotIn("--dry-run", steps["install"])
        self.assertNotIn("--dry-run", steps["adapter"])


class RunSetupTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.browser = []

    def runner(self, argv):
        self.calls.append(argv)
        return 0

    def test_order_and_console_url(self):
        args = Namespace(project="/proj", harness="codex", dry_run=False, open=False)
        self.assertEqual(setup.run_setup(args, runner=self.runner), 0)
        self.assertEqual(
            self.calls,
            [
                ["install", "--project", "/proj", "--bootstrap"],
                ["adapter", "codex"],
                ["doctor"],
            ],
        )
        self.assertEqual(self.browser, [])

    def test_dry_run_never_opens_the_browser(self):
        args = Namespace(project="/proj", harness="pi", dry_run=True, open=True)
        self.assertEqual(
            setup.run_setup(args, runner=self.runner, browser=self.browser.append), 0
        )
        self.assertTrue(all("--dry-run" in call for call in self.calls[:2]))
        self.assertEqual(self.browser, [])

    def test_open_only_after_a_successful_run(self):
        args = Namespace(project="/proj", harness="opencode", dry_run=False, open=True)
        self.assertEqual(
            setup.run_setup(args, runner=self.runner, browser=self.browser.append), 0
        )
        self.assertEqual(self.browser, [setup.CONSOLE_URL])

    def test_a_failing_step_stops_the_sequence(self):
        def failing(argv):
            self.calls.append(argv)
            return 1 if argv[0] == "install" else 0

        args = Namespace(project="/proj", harness="opencode", dry_run=False, open=False)
        self.assertEqual(setup.run_setup(args, runner=failing), 1)
        self.assertEqual(len(self.calls), 1)

    def test_explain_describes_without_running(self):
        args = Namespace(
            project="/proj", harness="auto", dry_run=False, open=True,
            explain=True, check=False,
        )
        self.assertEqual(
            setup.run_setup(args, runner=self.runner, browser=self.browser.append), 0
        )
        self.assertEqual(self.calls, [])
        self.assertEqual(self.browser, [])

    def test_check_runs_only_the_doctor(self):
        args = Namespace(
            project="/proj", harness="auto", dry_run=False, open=True,
            explain=False, check=True,
        )
        self.assertEqual(
            setup.run_setup(args, runner=self.runner, browser=self.browser.append), 0
        )
        self.assertEqual(self.calls, [["doctor"]])
        self.assertEqual(self.browser, [])

    def test_two_runs_produce_the_same_plan(self):
        args = Namespace(
            project="/proj", harness="opencode", dry_run=True, open=False,
            explain=False, check=False,
        )
        first_code = setup.run_setup(args, runner=self.runner)
        first_calls = list(self.calls)
        self.calls.clear()
        second_code = setup.run_setup(args, runner=self.runner)
        self.assertEqual((first_code, first_calls), (second_code, self.calls))


if __name__ == "__main__":
    unittest.main()
