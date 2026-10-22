"""The CLI version comes from the repository's single source: ``VERSION``."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.lifecycle_state import read_se_version  # noqa: E402


class CliVersionTests(unittest.TestCase):
    def test_help_reports_the_version_file(self):
        version = read_se_version(support.REPO_ROOT)

        code, out = support.run_cli("--help")

        self.assertEqual(code, 0, out)
        self.assertIn(f"(v{version})", out)

    def test_version_flag_reports_the_version_file(self):
        version = read_se_version(support.REPO_ROOT)

        code, out = support.run_cli("--version")

        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), f"se {version}")


if __name__ == "__main__":
    unittest.main()
