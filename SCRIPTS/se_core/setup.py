"""One command from a fresh clone to a usable SE install (roadmap T12-T15).

This module only sequences existing commands. It does not reimplement the
installer, the adapters or the doctor. The console is a separate web app: we
point at it instead of starting a second server behind the operator's back.
"""

from __future__ import annotations

from pathlib import Path

#: A harness is detected by the artifacts it leaves in the project root.
HARNESS_DIRS = {
    "opencode": (".opencode",),
    "codex": (".codex",),
    "claude-code": (".claude",),
    "deepseek": (".dsh",),
    "pi": (".pi",),
    "hermes": (".hermes",),
}
CONSOLE_URL = "http://127.0.0.1:8777"

#: `--explain` says what each step does and which surface it touches.
STEP_INFO = {
    "install": "Instala componentes y registra MCPs (toca ~/.se-installer y la config del runtime)",
    "adapter": "Genera los artefactos del harness (toca .opencode/, .dsh/, .codex/, ...)",
    "doctor": "Solo lectura: verifica estructura, contratos, adapters y configuración",
}


def detect_harness(root: Path | str = ".") -> str:
    """Return the harness already present in ``root``; default to OpenCode."""
    base = Path(root)
    for name, dirs in HARNESS_DIRS.items():
        if any((base / directory).exists() for directory in dirs):
            return name
    return "opencode"


def build_steps(root: str, harness: str, dry_run: bool) -> list[tuple[str, list[str]]]:
    """Return the ordered ``(step, argv)`` pairs for ``se setup``."""
    steps = [
        ("install", ["install", "--project", root, "--bootstrap"]),
        ("adapter", ["adapter", harness]),
        ("doctor", ["doctor"]),
    ]
    if dry_run:
        steps[0] = ("install", steps[0][1] + ["--dry-run"])
        steps[1] = ("adapter", steps[1][1] + ["--dry-run"])
    return steps


def _default_runner(argv: list[str]) -> int:
    from .cli import main

    return main(argv)


def _open_browser(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def run_setup(args, *, runner=None, browser=None) -> int:
    """Install, adapt, verify, then point at the console.

    ``runner`` receives an argv list and returns an exit code; tests inject a
    recorder. Any failing step stops the sequence, so an adapter is never
    generated on top of a broken install. ``--explain`` prints the plan without
    running it; ``--check`` runs only the read-only diagnosis. Neither mode
    starts the console server.
    """
    root = str(getattr(args, "project", ".") or ".")
    requested = getattr(args, "harness", "auto") or "auto"
    harness = detect_harness(root) if requested == "auto" else requested
    dry_run = bool(getattr(args, "dry_run", False))
    explain = bool(getattr(args, "explain", False))
    check = bool(getattr(args, "check", False))
    runner = runner or _default_runner

    suffix = " (auto)" if requested == "auto" else ""
    print(f"[setup] harness: {harness}{suffix}")
    steps = [("doctor", ["doctor"])] if check else build_steps(root, harness, dry_run)
    for step, argv in steps:
        print(f"[setup] {step}: {' '.join(argv)}")
        if explain:
            print(f"[setup]   {STEP_INFO[step]}")
            continue
        try:
            code = runner(argv)
        except Exception as exc:  # a broken step is reportable, never silent
            print(f"[setup] FAIL {step}: {exc}")
            return 1
        if code:
            print(f"[setup] FAIL {step} (exit {code}); remaining steps skipped")
            return 1

    if explain:
        print("[setup] explain: ningún paso se ejecutó")
        return 0

    print(f"[setup] console: {CONSOLE_URL}")
    print("[setup] start it with: cd SE-CONSOLE && python -m console.server --port 8777")
    if getattr(args, "open", False) and not dry_run and not check:
        (browser or _open_browser)(CONSOLE_URL)
    return 0
