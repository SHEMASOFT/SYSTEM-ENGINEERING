"""OpenCode adapter package.

Transforms canonical SYSTEM-ENGINEERING contracts (agents, commands, skills,
policies) into OpenCode-compatible generated artifacts (`.opencode/`).
Source of truth stays in `AGENTS/`, `COMMANDS/`, `SKILLS/` and `POLICIES/`;
everything under the output directory is generated output only.

Public API (see :mod:`se_core.opencode.generator`):

- ``generate(root, output, dry_run=False)`` -> generation result dict.
"""

from __future__ import annotations

from .generator import generate, generate_default_output

__all__ = ["generate", "generate_default_output"]
__version__ = "0.1.0"