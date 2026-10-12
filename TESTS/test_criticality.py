"""CRITICALITY handling tests: no silent factual default."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


class CriticalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def test_unknown_is_valid(self):
        self.assertEqual(validate(support.manifest(criticality="unknown"), self.schemas["project"]), [])

    def test_invalid_value_rejected(self):
        self.assertNotEqual(validate(support.manifest(criticality="bogus"), self.schemas["project"]), [])

    def test_missing_criticality_rejected(self):
        data = support.manifest()
        del data["criticality"]
        self.assertNotEqual(validate(data, self.schemas["project"]), [])

    def test_init_default_is_unknown_not_medium(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "demo"
            code, out = support.run_cli("init", "--dir", str(project), "--name", "Demo", "--owner", "o")
            self.assertEqual(code, 0, out)
            manifest = json.loads((project / "PROJECT.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["criticality"], "unknown")
            self.assertNotEqual(manifest["criticality"], "medium")


if __name__ == "__main__":
    unittest.main()
