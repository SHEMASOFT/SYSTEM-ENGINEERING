"""RDD (review receipt) plus the SDD/ODD creation regression.

The SDD and ODD record types were advertised by the skill server but their
templates were never registered in ``NEW_TEMPLATES``, so ``create_record``
raised ``KeyError`` for both. These tests pin the three record types end to end:
creation through the same path the CLI and the MCP tools use, and validation
against their schemas.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import commands  # noqa: E402
from se_core.paths import load_json  # noqa: E402
from se_core.schemas import load_schemas, validate  # noqa: E402


class RecordCreationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "Demo"
        support.make_project(self.project)
        self.addCleanup(self._tmp.cleanup)

    def _create(self, kind, **overrides):
        path, identifier, errors = commands.create_record(self.project, kind, overrides)
        self.assertEqual(errors, [], f"{kind}: {errors}")
        self.assertTrue(path.exists(), kind)
        return path, identifier

    def test_sdd_creation_matches_its_schema(self):
        path, identifier = self._create("sdd", title="SDD one")
        self.assertTrue(identifier.startswith("SDD-"))
        self.assertEqual(validate(load_json(path), load_schemas()["sdd"]), [])

    def test_odd_creation_matches_its_schema(self):
        path, identifier = self._create("odd", title="ODD one")
        self.assertTrue(identifier.startswith("ODD-"))
        self.assertEqual(validate(load_json(path), load_schemas()["odd"]), [])

    def test_rdd_creation_matches_its_schema(self):
        path, identifier = self._create("rdd", title="RDD one")
        self.assertTrue(identifier.startswith("RDD-"))
        record = load_json(path)
        self.assertEqual(validate(record, load_schemas()["rdd"]), [])
        # A receipt always names its candidate and carries at least one evidence
        # entry: a verdict with no candidate is not a receipt.
        self.assertIn("hash", record["candidate"])
        self.assertTrue(record["evidence"])
        self.assertIn(record["verdict"], ("PASS", "PARTIAL", "BLOCKED", "FAIL"))

    def test_rdd_accepts_an_explicit_candidate_and_verdict(self):
        candidate = {"kind": "commit", "ref": "abc1234", "hash": "a" * 40}
        evidence = [{"id": "EVD-0001", "claim": "tests pass", "result": "PASS"}]
        path, _ = self._create(
            "rdd", title="Review", candidate=candidate, verdict="PASS", evidence=evidence
        )
        record = load_json(path)
        self.assertEqual(record["candidate"], candidate)
        self.assertEqual(record["evidence"], evidence)
        self.assertEqual(validate(record, load_schemas()["rdd"]), [])

    def test_ids_increment_per_collection(self):
        _, first = self._create("rdd", title="One")
        _, second = self._create("rdd", title="Two")
        self.assertNotEqual(first, second)
        self.assertEqual(second, "RDD-0002")


if __name__ == "__main__":
    unittest.main()
