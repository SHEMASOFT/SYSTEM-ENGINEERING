"""SE-CONSOLE :: harness non-interference fingerprint (hermetic).

Why this file exists
--------------------
S12 proves the console changed nothing by comparing ``core_fingerprint()`` of the
canonical SE tree before and after a run. On 2026-10-14 that check produced a
false failure: the fingerprint walked all of ``DOCS``, including the gitignored
working records under ``DOCS/internal/``, so an unrelated write there during the
run was reported as "the console modified SYSTEM-ENGINEERING".

Only canonical content may be fingerprinted. These tests point the fingerprint at
a throwaway SE root (via SE_ROOT) and assert that gitignored working records are
invisible while real canonical changes are still caught.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from validate_poc import core_fingerprint  # noqa: E402


class CoreFingerprintTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.se = Path(self._tmp.name) / "se"
        (self.se / "CORE").mkdir(parents=True)
        (self.se / "DOCS" / "internal").mkdir(parents=True)
        (self.se / "CORE" / "canonical.txt").write_text("canonical\n", encoding="utf-8")
        (self.se / "DOCS" / "internal" / "notes.md").write_text("working notes\n", encoding="utf-8")
        self._prev = os.environ.get("SE_ROOT")
        os.environ["SE_ROOT"] = str(self.se)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SE_ROOT", None)
        else:
            os.environ["SE_ROOT"] = self._prev
        self._tmp.cleanup()

    def test_gitignored_working_records_do_not_perturb_the_fingerprint(self):
        """A write under DOCS/internal during a run must not move the fingerprint."""
        before = core_fingerprint()
        (self.se / "DOCS" / "internal" / "extra.md").write_text(
            "added during a run\n", encoding="utf-8"
        )
        (self.se / "DOCS" / "internal" / "notes.md").write_text(
            "edited during a run\n", encoding="utf-8"
        )
        after = core_fingerprint()
        self.assertEqual(before, after)

    def test_canonical_edit_is_still_detected(self):
        """Guard: the fix must not blind the check to real canonical writes."""
        before = core_fingerprint()
        (self.se / "CORE" / "canonical.txt").write_text("changed\n", encoding="utf-8")
        after = core_fingerprint()
        self.assertNotEqual(before["tree_sha256"], after["tree_sha256"])

    def test_canonical_addition_still_changes_the_count(self):
        """Guard: a new canonical file must still be noticed."""
        before = core_fingerprint()
        (self.se / "CORE" / "added.txt").write_text("new canonical file\n", encoding="utf-8")
        after = core_fingerprint()
        self.assertEqual(after["file_count"], before["file_count"] + 1)


if __name__ == "__main__":
    unittest.main()
