"""The CLI may expose more than the contract declares, but only what is declared.

`COMMANDS/commands.json` is the *conceptual* command interface -- "Exposable via
CLI, OpenCode, other agents or automation" -- so the CLI is allowed to carry
subcommands that are not contract commands. `adapter` is the documented case:
the reference documentation calls it a "CLI infrastructure group (not a contract
command)", and `install`/`sync`/`uninstall` manage the tool's own installation.

What must not happen is silent growth. A new top-level subcommand would otherwise
reach the CLI surface without anyone deciding whether it belongs to the contract:
that is how the summary tables fell behind, and the CLI surface is larger. This
test pins the boundary in both directions, so adding a subcommand is a deliberate
choice between two reviewed places -- the contract (which per ADR-0020 means an
ADR and a `VERSION` bump) or the declared support list below.

The declared list mirrors the boundary documented in `COMMANDS/README.md`
("Conventions"). Adding a name here is the cheap, reviewed way to widen the CLI;
widening the contract is the governed way.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.cli import build_parser  # noqa: E402
from se_core.paths import load_json  # noqa: E402

CONTRACT = support.REPO_ROOT / "COMMANDS" / "commands.json"

# Top-level subcommands the CLI exposes outside the contract. This list is the
# boundary decision, so changing it is meant to be reviewed -- see the module
# docstring.
DECLARED_SUPPORT = frozenset(
    {
        "adapter",  # generates tool artifacts from the contracts
        "adopt",  # adopts an existing project into the managed layout
        "ceremony",  # reports the ceremony floor for a project profile
        "coverage",  # rebases the document coverage baseline (governed)
        "har",  # handoff/archive/restore helpers for a project
        "install",  # installs the tool itself
        "intelligence",  # inspects the intelligence/observability surface
        "memory",  # reads and writes persistent memory
        "resume",  # resumes work from a stored session
        "run",  # runs a declared pipeline step
        "skill",  # lists and inspects available skills
        "status",  # reports session/tool status
        "subagent",  # executes a subagent with full token economy (reuses AgentRunner)
        "sync",  # synchronises installed tool artifacts
        "uninstall",  # removes the tool's installed artifacts
    }
)


def top_level_commands() -> set[str]:
    """The CLI's top-level subcommands, read from the parser the CLI builds.

    `argparse` exposes no public accessor for a parser's subparsers, so this
    walks `_actions` for the subparsers action. Nested subcommands (`adapter
    opencode`, `har show`) belong to child parsers and are therefore not
    collected, which is what makes the set comparable with the contract.
    """
    parser = build_parser()
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if len(subparsers) != 1:
        raise AssertionError(
            f"expected exactly one top-level subparsers action, got {len(subparsers)}"
        )
    return set(subparsers[0].choices)


def contract_commands() -> set[str]:
    return {command["name"] for command in load_json(CONTRACT)["commands"]}


class CliContractBoundaryTests(unittest.TestCase):
    def test_the_cli_exposes_every_contract_command(self):
        missing = sorted(contract_commands() - top_level_commands())
        self.assertEqual(
            missing,
            [],
            f"declared in commands.json but not exposed by the CLI: {missing}",
        )

    def test_the_cli_exposes_nothing_beyond_the_contract_and_the_declared_support(self):
        undeclared = sorted(
            top_level_commands() - contract_commands() - DECLARED_SUPPORT
        )
        self.assertEqual(
            undeclared,
            [],
            "new top-level CLI subcommand(s) with no boundary decision: "
            f"{undeclared}. Either declare them in commands.json (a governed change: "
            "ADR + VERSION bump, ADR-0020) or add them to DECLARED_SUPPORT here and to "
            "the Conventions section of COMMANDS/README.md.",
        )

    def test_declared_support_commands_all_exist(self):
        stale = sorted(DECLARED_SUPPORT - top_level_commands())
        self.assertEqual(
            stale,
            [],
            f"declared as support but no longer exposed by the CLI: {stale}",
        )

    def test_declared_support_and_the_contract_do_not_overlap(self):
        overlap = sorted(DECLARED_SUPPORT & contract_commands())
        self.assertEqual(
            overlap,
            [],
            f"both declared as support and in the contract: {overlap}",
        )

    def test_the_readme_documents_every_declared_support_command(self):
        readme = (support.REPO_ROOT / "COMMANDS" / "README.md").read_text(
            encoding="utf-8"
        )
        parts = readme.split("Conventions:", 1)
        self.assertEqual(
            len(parts), 2, "COMMANDS/README.md no longer has a Conventions section"
        )
        section = parts[1].split("\n## ", 1)[0]
        undocumented = sorted(
            name for name in DECLARED_SUPPORT if f"`{name}`" not in section
        )
        self.assertEqual(
            undocumented,
            [],
            "declared as support but not documented in the Conventions section of "
            f"COMMANDS/README.md: {undocumented}",
        )


if __name__ == "__main__":
    unittest.main()
