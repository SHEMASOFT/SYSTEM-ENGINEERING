#!/usr/bin/env python3
"""SYSTEM ENGINEERING reference CLI entry point.

Usage:
    python SCRIPTS/se.py <command> [options]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from se_core.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
