"""Generate runtime adapter layers after a successful CLI install.

The installer venv is isolated and does not ship ``se_core``, so the
repository's ``SCRIPTS/`` directory is added to ``sys.path`` before importing
the generators. This helper is used by the CLI only: the TUI and the web
installer drive the orchestrator directly and are deliberately untouched.

Adapter generation is best-effort. The components are already installed at
this point, so a broken adapter is reported as an outcome instead of turning
a successful install into a crash.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resolve_root(project_root) -> Path:
    """Return the tree that holds ``SCRIPTS/se.py``.

    The caller normally passes the repository root. Fall back to the location
    of this package so an install started from a subdirectory still works.
    """
    candidate = Path(project_root)
    if (candidate / "SCRIPTS" / "se.py").exists():
        return candidate
    return Path(__file__).resolve().parents[2]


def _load_generators(root: Path):
    scripts = root / "SCRIPTS"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from se_core import runtimes
    from se_core.opencode import generator

    return runtimes, generator


def generate(project_root, runtimes: list[str], dry_run: bool = False) -> list[dict]:
    """Render the requested adapters and return one outcome per runtime.

    ``opencode`` writes under ``.opencode/``; every other runtime writes its
    files at the project root (that is what their generators expect). Nothing
    here invents a runtime: an unknown id is reported, not ignored.
    """
    root = resolve_root(project_root)
    results: list[dict] = []

    try:
        rt, opencode = _load_generators(root)
    except Exception as exc:  # se_core not reachable from this venv
        return [
            {"runtime": name, "status": "FAILED", "error": f"se_core unavailable: {exc}"}
            for name in runtimes
        ]

    for name in runtimes:
        key = str(name).strip()
        try:
            if key == "opencode":
                result = opencode.generate(root, root / ".opencode", dry_run=dry_run)
            else:
                fn_name = "claude_code" if key in {"claude-code", "claude_code"} else key
                fn = getattr(rt, f"generate_{fn_name}", None)
                if fn is None:
                    raise ValueError(f"unknown runtime '{name}'")
                result = fn(root, root, dry_run=dry_run)

            results.append({
                "runtime": name,
                "status": result.get("status", "PASS"),
                "files": len(result.get("files", [])),
                "output": str(result.get("output", root)),
            })
        except Exception as exc:
            results.append({"runtime": name, "status": "FAILED", "error": str(exc)})

    return results
