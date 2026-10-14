"""Writers must emit LF on every platform, because bytes are identified by hash.

`.gitattributes` (`* text=auto eol=lf`) is not cosmetic: the repository states that
content hashes are part of the contract, and several comparisons read the **raw bytes**
of a file from the working tree:

* `_file_revision` -> `opencode.validators._sha256_file` feeds `--expected-revision`
  (the CLI documents it as "sha256 of the run file's raw bytes"), so a revision must be
  a function of the content, not of the platform that wrote it;
* `_compute_file_hash` decides whether the coverage baseline still matches the tree;
* `se archive` hashes every project file and `se restore` verifies those hashes;
* `install` records `sha256(adapter-manifest.json)` in the lifecycle state.

If a writer lets the platform translate ``\\n`` into ``\\r\\n``, the same logical content
hashes differently on Windows than on a fresh clone, and those comparisons fail or
spuriously report drift. `opencode/generator.py` and `runtimes.py` already pin
``newline="\\n"``; these tests pin the same contract for the writers that did not:
`write_json_atomic` (every JSON record), the ADR-0013 `mutation-log.jsonl` append, and
the coverage-baseline ledger append.

Platform note: the pre-fix failure is only reachable where ``os.linesep`` is ``\\r\\n``
(Windows). The assertions compare exact bytes, so they are not weakened on POSIX — they
simply cannot fail there.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (puts SCRIPTS on sys.path)

from se_core import commands  # noqa: E402
from se_core.paths import write_json_atomic  # noqa: E402


class WriteJsonAtomicLineEndingsTests(unittest.TestCase):
    def test_writes_exactly_the_canonical_lf_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "record.json"
            write_json_atomic(target, {"a": 1, "nested": {"b": [1, 2]}, "text": "ñ"})
            expected = (
                '{\n'
                '  "a": 1,\n'
                '  "nested": {\n'
                '    "b": [\n'
                '      1,\n'
                '      2\n'
                '    ]\n'
                '  },\n'
                '  "text": "ñ"\n'
                '}\n'
            )
            self.assertEqual(target.read_bytes(), expected.encode("utf-8"))

    def test_revision_is_the_digest_of_the_canonical_bytes(self):
        """The revision of given content must not depend on who wrote it."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "record.json"
            write_json_atomic(target, {"a": 1})
            canonical = b'{\n  "a": 1\n}\n'
            self.assertEqual(commands._file_revision(str(target)), hashlib.sha256(canonical).hexdigest())


class MutationLogLineEndingsTests(unittest.TestCase):
    def test_appended_entries_are_lf_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            commands._append_mutation_log(tmp, "task", "TASK-1", "tester", {"status": "DONE"})
            commands._append_mutation_log(tmp, "task", "TASK-2", "tester", {"status": "DONE"})
            raw = (Path(tmp) / "mutation-log.jsonl").read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertTrue(raw.endswith(b"\n"))
            entries = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
            self.assertEqual([entry["record_id"] for entry in entries], ["TASK-1", "TASK-2"])


class CoverageLedgerLineEndingsTests(unittest.TestCase):
    def test_rebase_appends_lf_only_and_rewrites_the_baseline_as_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "DOCS").mkdir(parents=True)
            stale = {
                "version": 1,
                "created_at": "2026-01-01T00:00:00Z",
                "description": "fixture",
                "minimums": {"reference": 0},
                "documents": {
                    "reference": [{"path": "DOCS/reference/commands.md", "hash": "0000000000000000"}]
                },
            }
            (root / "DOCS" / "coverage-baseline.json").write_text(
                json.dumps(stale), encoding="utf-8"
            )

            result = commands._record_coverage_baseline_rebase(root, "tester", "lf line-ending test")
            self.assertTrue(result.get("written"), result)

            ledger = (root / "DOCS" / "coverage-baseline.log.jsonl").read_bytes()
            self.assertNotIn(b"\r", ledger)
            self.assertTrue(ledger.endswith(b"\n"))
            entry = json.loads(ledger.decode("utf-8").splitlines()[0])
            self.assertEqual(entry["by"], "tester")
            self.assertEqual(entry["reason"], "lf line-ending test")

            self.assertNotIn(b"\r", (root / "DOCS" / "coverage-baseline.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
