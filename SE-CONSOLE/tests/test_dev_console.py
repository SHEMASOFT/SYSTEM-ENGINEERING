"""SE-CONSOLE :: tests for the local dev lifecycle helper (``scripts/dev_console.py``).

These are unit tests of the *decision* logic -- PID file handling, process
liveness, and the health signature that proves identity. They deliberately do
NOT start a server: spawning a background console and killing it would be flaky,
would fight over the very port under test, and is already covered end-to-end by
``tests/validate_poc.py``. Keeping this suite hermetic is the proportionate
check for dev tooling (organic-mode proportionality).
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
