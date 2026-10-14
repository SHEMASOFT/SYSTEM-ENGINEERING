"""Every human summary table of the command contract must list exactly its commands.

`COMMANDS/commands.json` is the machine-readable contract, and two documents
summarise it by hand: `COMMANDS/README.md` ("Human summary: COMMANDS/README.md",
per the reference documentation) and the Commands table in
`DOCS/reference/commands.md`. A hand-maintained table falls behind silently --
the README had frozen at 14 rows and the reference table at 17 -- so both are
pinned to the contract here, in both directions.

The CLI-to-contract relationship is not a summary table: it is asserted
separately, in `TESTS/test_cli_contract_boundary.py`.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402

# A documentation row: the first cell is a backticked command name.
_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|")

SUMMARY_TABLES = {
    "COMMANDS/README.md": support.REPO_ROOT / "COMMANDS" / "README.md",
    "DOCS/reference/commands.md": support.REPO_ROOT / "DOCS" / "reference" / "commands.md",
}
CONTRACT = support.REPO_ROOT / "COMMANDS" / "commands.json"


def table_commands(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [m.group(1) for m in (_ROW.match(line) for line in text.splitlines()) if m]


def contract_commands() -> list[str]:
    return [c["name"] for c in load_json(CONTRACT)["commands"]]


class CommandSummaryTableParityTests(unittest.TestCase):
    def test_every_contract_command_is_documented(self):
        declared = contract_commands()
        for name, path in SUMMARY_TABLES.items():
            with self.subTest(table=name):
                listed = table_commands(path)
                missing = [command for command in declared if command not in listed]
                self.assertEqual(
                    missing, [], f"in commands.json but not in {name}: {missing}"
                )

    def test_no_table_documents_a_command_the_contract_does_not_declare(self):
        declared = set(contract_commands())
        for name, path in SUMMARY_TABLES.items():
            with self.subTest(table=name):
                extra = [c for c in table_commands(path) if c not in declared]
                self.assertEqual(
                    extra, [], f"in {name} but not in commands.json: {extra}"
                )
