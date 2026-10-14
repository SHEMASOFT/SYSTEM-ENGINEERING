"""The COMMANDS README must list every command the contract declares.

`COMMANDS/README.md` presents itself as the human view of `commands.json`
("The conceptual command interface. Machine-readable source: commands.json"), so
a command that exists in the contract but is missing from the table is a
documentation defect, not a style choice: the table stopped describing its own
source. This pins the two together so the table cannot fall behind silently again.

The CLI-to-contract relationship is deliberately NOT asserted here. The contract
is the canonical command interface while the CLI carries auxiliary subcommands
that are not part of it; whether the contract should grow to cover them is an open
question, not a settled parity rule, so it must not be frozen by a test.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402

README = support.REPO_ROOT / "COMMANDS" / "README.md"
CONTRACT = support.REPO_ROOT / "COMMANDS" / "commands.json"

# A documentation row: the first cell is a backticked command name.
_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|")


def readme_commands() -> list[str]:
    text = README.read_text(encoding="utf-8")
    return [m.group(1) for m in (_ROW.match(line) for line in text.splitlines()) if m]


def contract_commands() -> list[str]:
    return [c["name"] for c in load_json(CONTRACT)["commands"]]


class CommandsReadmeParityTests(unittest.TestCase):
    def test_every_contract_command_is_documented(self):
        listed = readme_commands()
        missing = [name for name in contract_commands() if name not in listed]
        self.assertEqual(
            missing, [], f"in commands.json but not in the README table: {missing}"
        )

    def test_the_table_documents_nothing_the_contract_does_not_declare(self):
        declared = set(contract_commands())
        extra = [name for name in readme_commands() if name not in declared]
        self.assertEqual(
            extra, [], f"in the README table but not in commands.json: {extra}"
        )
