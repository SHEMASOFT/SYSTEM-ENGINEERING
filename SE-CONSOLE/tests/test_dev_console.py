"""SE-CONSOLE :: tests for the local dev lifecycle helper (``scripts/dev_console.py``).

These are unit tests of the *decision* logic -- PID file handling, process
liveness, and the health signature that proves identity. They deliberately do
NOT start a server: spawning a background console and killing it would be flaky,
would fight over the very port under test, and is already covered end-to-end by
``tests/validate_poc.py``. Keeping this suite hermetic is the proportionate
check for dev tooling (organic-mode proportionality).

The idle-timeout wiring is checked the same way: ``Popen`` is stubbed, so the
assertion is about the exact argv the helper would hand to the OS, with no
server ever spawned.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dev_console  # noqa: E402  (import after sys.path is prepared)


class HealthSignature(unittest.TestCase):
    """Identity must come from the /api/health payload, never from a PID."""

    def test_accepts_the_console_signature(self):
        self.assertTrue(
            dev_console.is_our_console({"console": "se-console", "mode": "read-only"})
        )

    def test_rejects_anything_else(self):
        self.assertFalse(dev_console.is_our_console(None))
        self.assertFalse(dev_console.is_our_console({}))
        self.assertFalse(dev_console.is_our_console({"status": "OK"}))
        # console name right, but not proven read-only -> not our console
        self.assertFalse(dev_console.is_our_console({"console": "se-console"}))
        # read-only, but a different service
        self.assertFalse(
            dev_console.is_our_console({"console": "other", "mode": "read-only"})
        )


class PidFile(unittest.TestCase):
    """Read/write/clear round trips, and malformed files fail closed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = dev_console.RUNTIME_DIR
        self._orig_file = dev_console.PID_FILE
        dev_console.RUNTIME_DIR = Path(self._tmp.name)
        dev_console.PID_FILE = Path(self._tmp.name) / "se-console.json"

    def tearDown(self):
        dev_console.RUNTIME_DIR = self._orig_dir
        dev_console.PID_FILE = self._orig_file
        self._tmp.cleanup()

    def test_absent_file_reads_as_none(self):
        self.assertIsNone(dev_console.read_pidfile())

    def test_round_trip(self):
        dev_console.write_pidfile({"pid": 1234, "host": "127.0.0.1", "port": 8777})
        data = dev_console.read_pidfile()
        self.assertIsNotNone(data)
        self.assertEqual(data["pid"], 1234)
        dev_console.clear_pidfile()
        self.assertIsNone(dev_console.read_pidfile())

    def test_clear_is_idempotent(self):
        dev_console.clear_pidfile()
        dev_console.clear_pidfile()
        self.assertIsNone(dev_console.read_pidfile())

    def test_malformed_file_reads_as_none(self):
        dev_console.PID_FILE.write_text("{not json", encoding="utf-8")
        self.assertIsNone(dev_console.read_pidfile())


class Liveness(unittest.TestCase):
    """os.getpid() is alive; impossible PIDs are not. On Windows this must use
    OpenProcess, never os.kill(pid, 0) -- which would terminate the target."""

    def test_own_process_is_alive(self):
        self.assertTrue(dev_console._pid_alive(os.getpid()))

    def test_invalid_pids_are_not_alive(self):
        self.assertFalse(dev_console._pid_alive(0))
        self.assertFalse(dev_console._pid_alive(-1))
        self.assertFalse(dev_console._pid_alive(999_999_999))


class IdleTimeoutWiring(unittest.TestCase):
    """The launcher must ARM the server's idle timeout, and say so.

    Stubs ``Popen`` instead of spawning: the thing under test is the argv and the
    PID file, and asserting them directly is both stronger and hermetic.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (dev_console.RUNTIME_DIR, dev_console.LOGS_DIR, dev_console.PID_FILE)
        dev_console.RUNTIME_DIR = Path(self._tmp.name)
        dev_console.LOGS_DIR = Path(self._tmp.name) / "logs"
        dev_console.PID_FILE = Path(self._tmp.name) / "se-console.json"

        self.calls = []

        class FakeProc:
            pid = 4242
            returncode = None

            def poll(self):
                return None

        self._orig_popen = dev_console.subprocess.Popen
        dev_console.subprocess.Popen = lambda argv, **kw: (self.calls.append(argv), FakeProc())[1]

        # Nothing answers before the spawn; our console answers after it -- the
        # real sequence, so the start path is exercised, not short-circuited.
        self._orig_probe = dev_console.probe_health
        dev_console.probe_health = lambda host, port, timeout=2.5: (
            None if not self.calls else {"console": "se-console", "mode": "read-only",
                                         "status": "OK", "version": "t", "se_root": "/x"}
        )

    def tearDown(self):
        dev_console.subprocess.Popen = self._orig_popen
        dev_console.probe_health = self._orig_probe
        (dev_console.RUNTIME_DIR, dev_console.LOGS_DIR, dev_console.PID_FILE) = self._orig
        self._tmp.cleanup()

    def _start(self, idle_timeout):
        return dev_console.cmd_start(
            argparse.Namespace(host="127.0.0.1", port=8777, timeout=5.0,
                               idle_timeout=idle_timeout)
        )

    def test_start_passes_the_timeout_to_the_server(self):
        rc = self._start(900)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            self.calls[0],
            [sys.executable, "-m", "console.server", "--idle-timeout", "900"],
        )

    def test_start_records_the_timeout_for_status(self):
        self._start(900)
        self.assertEqual(dev_console.read_pidfile()["idle_timeout"], 900)

    def test_zero_is_passed_through_as_disabled(self):
        self._start(0)
        self.assertEqual(self.calls[0][-1], "0")
        self.assertEqual(dev_console.read_pidfile()["idle_timeout"], 0)

    def test_negative_timeout_is_refused_without_spawning(self):
        rc = self._start(-5)
        self.assertEqual(rc, 1)
        self.assertEqual(self.calls, [])
        self.assertIsNone(dev_console.read_pidfile())

    def test_the_default_is_fifteen_minutes(self):
        self.assertEqual(dev_console.DEFAULT_IDLE_TIMEOUT, 15 * 60)


class IdleTimeoutCli(unittest.TestCase):
    """The flag exists on both spawning subcommands and defaults to 15 min."""

    def setUp(self):
        self.parser = dev_console.build_parser()

    def test_start_defaults_to_the_launcher_default(self):
        self.assertEqual(
            self.parser.parse_args(["start"]).idle_timeout,
            dev_console.DEFAULT_IDLE_TIMEOUT,
        )

    def test_start_accepts_an_explicit_value(self):
        self.assertEqual(self.parser.parse_args(["start", "--idle-timeout", "0"]).idle_timeout, 0)

    def test_restart_carries_the_flag_too(self):
        args = self.parser.parse_args(["restart", "--idle-timeout", "60"])
        self.assertEqual(args.idle_timeout, 60)
        self.assertIs(args.func, dev_console.cmd_restart)

    def test_status_does_not_grow_the_flag(self):
        # `status` only reports; it must not accept a value it would ignore.
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["status", "--idle-timeout", "60"])

    def test_human_seconds(self):
        self.assertEqual(dev_console._human_seconds(900), "15 min")
        self.assertEqual(dev_console._human_seconds(60), "1 min")
        self.assertEqual(dev_console._human_seconds(90), "90s")
        self.assertEqual(dev_console._human_seconds(0), "0s")


class StatusReportsTheTimeout(unittest.TestCase):
    """status reports what the launcher configured, and admits ignorance."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (dev_console.RUNTIME_DIR, dev_console.PID_FILE, dev_console.probe_health)
        dev_console.RUNTIME_DIR = Path(self._tmp.name)
        dev_console.PID_FILE = Path(self._tmp.name) / "se-console.json"
        # No live console, and no network calls from a unit test.
        dev_console.probe_health = lambda *a, **k: None

    def tearDown(self):
        (dev_console.RUNTIME_DIR, dev_console.PID_FILE, dev_console.probe_health) = self._orig
        self._tmp.cleanup()

    def test_reports_the_value_it_started_with(self):
        dev_console.write_pidfile({"pid": 1234, "host": "127.0.0.1", "port": 8777,
                                   "idle_timeout": 900})
        self.assertEqual(dev_console._status_data()["idle_timeout"], 900)

    def test_unknown_when_the_pidfile_predates_the_feature(self):
        dev_console.write_pidfile({"pid": 1234, "host": "127.0.0.1", "port": 8777})
        self.assertIsNone(dev_console._status_data()["idle_timeout"])


if __name__ == "__main__":
    unittest.main()
