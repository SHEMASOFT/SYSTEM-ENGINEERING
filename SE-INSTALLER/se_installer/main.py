#!/usr/bin/env python3
"""SE Installer - Main entry point."""

import sys
from pathlib import Path

# Add parent directory to path so we can import se_installer
sys.path.insert(0, str(Path(__file__).parent.parent))

from se_installer.cli import main

if __name__ == "__main__":
    sys.exit(main())