"""Hermetic test runner for the Master System.

Usage:
    python TESTS/run_tests.py
    python -m unittest discover -s TESTS -p "test_*.py"

The canonical command runs the core suite (``TESTS/``) plus every integration
suite shipped in the checkout (``INTEGRATIONS/<name>/tests``). CI calls this one
command, so an integration cannot silently lose its coverage: adding a suite
under ``INTEGRATIONS/`` is enough for it to run everywhere ``run_tests.py`` runs.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(ROOT / "SCRIPTS") not in sys.path:
    sys.path.insert(0, str(ROOT / "SCRIPTS"))

CORE_SUITE_DIR = HERE
INTEGRATION_SUITE_GLOB = "INTEGRATIONS/*/tests"


def discover_suites(root: Path = ROOT) -> list[unittest.TestSuite]:
    """Discover the core suite and one suite per integration tests directory."""
    loader = unittest.TestLoader()
    suites = [
        loader.discover(
            start_dir=str(CORE_SUITE_DIR),
            pattern="test_*.py",
            top_level_dir=str(CORE_SUITE_DIR),
        )
    ]
    for tests_dir in sorted(root.glob(INTEGRATION_SUITE_GLOB)):
        if not tests_dir.is_dir():
            continue
        suites.append(
            loader.discover(
                start_dir=str(tests_dir),
                pattern="test_*.py",
                top_level_dir=str(tests_dir),
            )
        )
    return suites


def main() -> int:
    combined = unittest.TestSuite(discover_suites())
    if combined.countTestCases() == 0:
        print("No tests discovered", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(combined)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
