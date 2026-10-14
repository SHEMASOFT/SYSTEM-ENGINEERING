"""SE-CONSOLE :: Windows child-process visibility policy (guards).

Why this file exists
--------------------
On Windows, a process that has NO console hands every child console process its
own NEW console window. ``se`` is invoked through ``sys.executable`` -- a console
application -- so a console started detached used to pop one ``python.exe``
window per invocation: two for ``/api/system`` (``se doctor`` + ``se
capabilities``) and nine for ``/api/gates``. The operator saw "multiple console
windows opening" while simply using the UI.

The fix arms ``CREATE_NO_WINDOW`` in two places:

* ``console/se_cli.py`` -- for the ``se`` child itself (the root fix: the console
  never flashes a window, however it was launched);
* ``scripts/dev_console.py`` -- for the server process, so its children inherit a
  hidden console instead of allocating visible ones, and for ``taskkill``.

These tests fail on Windows if either flag is ever dropped. They are skipped
elsewhere, where the constant does not exist and ``creationflags`` must stay 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

CONSOLE_ROOT = Path(__file__).resolve().parent.parent
if str(CONSOLE_ROOT) not in sys.path:
    sys.path.insert(0, str(CONSOLE_ROOT))
if str(CONSOLE_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(CONSOLE_ROOT / "scripts"))

import dev_console  # noqa: E402  (import after sys.path is prepared)
from console import se_cli  # noqa: E402


@unittest.skipUnless(os.name == "nt", "CREATE_NO_WINDOW is Windows-only")
class ChildVisibilityFlags(unittest.TestCase):
    def test_se_cli_arms_create_no_window(self):
        """Any non-zero value keeps child consoles hidden; assert it is the real flag."""
        self.assertEqual(se_cli._NO_WINDOW, subprocess.CREATE_NO_WINDOW)

    def test_launcher_arms_create_no_window(self):
        self.assertEqual(dev_console.NO_WINDOW, subprocess.CREATE_NO_WINDOW)

    def test_run_se_forwards_the_flag_to_subprocess(self):
        """The `se` call itself must carry the flag, not just define it."""
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(cmd, 0, '{"report":"se.report/1"}', "")

        with mock.patch.object(se_cli.subprocess, "run", fake_run):
            se_cli.run_se(["doctor"], timeout=5)

        self.assertEqual(captured.get("creationflags"), se_cli._NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
