"""Hermetic test runner for the Master System.

Usage:
    python TESTS/run_tests.py
    python -m unittest discover -s TESTS -p "test_*.py"
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parent / "SCRIPTS") not in sys.path:
    sys.path.insert(0, str(HERE.parent / "SCRIPTS"))


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(HERE), pattern="test_*.py", top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
