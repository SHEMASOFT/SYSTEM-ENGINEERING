"""Install-time desktop shortcut for the SE Console (DESIGN-5C phase 4).

DESIGN-5C §7.4 (decision D3) asks for exactly ONE shortcut, "SE Console". It
starts the console; the console then serves its own URL. There is deliberately no
Stop shortcut -- the console stops itself once nothing is watching it.

The work is split so that the *decision* can be tested without ever touching a
real Desktop:

    plan_shortcut(...)      pure: what would be created, including the file body
    create_shortcut(...)    performs it, once, and reports what it did

The caller always supplies the Desktop directory. Nothing here runs on import,
and the module imports nothing outside the standard library, so this code is
reachable from CI (which does not install the TUI's dependencies).

Per platform the shortcut points at the entry point the console already ships:

    Windows   <desktop>/SE Console.lnk       -> SE-CONSOLE/scripts/Start SE Console.cmd
    macOS     <desktop>/SE Console.command   -> SE-CONSOLE/scripts/Start SE Console.command
    Linux     <desktop>/SE Console.desktop   -> SE-CONSOLE/scripts/dev_console.py start

The Linux case carries the launch recipe itself. The console ships a
double-clickable start script for Windows and for macOS but none for Linux, and
phase 4 is confined to ``se_installer/`` -- no console files are added to make a
shortcut possible.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import OSType

SHORTCUT_NAME = "SE Console"
DESCRIPTION = "Inicia la consola web local (read-only) sobre SYSTEM-ENGINEERING"
CONSOLE_URL = "http://127.0.0.1:8777"

CONSOLE_DIR_NAME = "SE-CONSOLE"
CONSOLE_SCRIPTS_SUBDIR = "scripts"

KIND_WINDOWS_LNK = "windows-lnk"
KIND_MACOS_COMMAND = "macos-command"
KIND_LINUX_DESKTOP = "linux-desktop"

WINDOWS_SHORTCUT_FILE = "SE Console.lnk"
MACOS_SHORTCUT_FILE = "SE Console.command"
LINUX_SHORTCUT_FILE = "SE Console.desktop"

WINDOWS_ENTRY_POINT = "Start SE Console.cmd"
MACOS_ENTRY_POINT = "Start SE Console.command"
LINUX_ENTRY_POINT = "dev_console.py"


class ShortcutError(RuntimeError):
    """The shortcut could not be created. The message is written for the operator."""


@dataclass(frozen=True)
class Shortcut:
    """What to create, decided before anything is written."""

    os_type: OSType
    kind: str
    path: Path
    target: Path
    description: str = DESCRIPTION
    #: Body of the generated file, for the kinds that are a file we author.
    #: ``None`` for the Windows shortcut, which the system creates for us.
    contents: Optional[str] = None
    #: Mode of a generated file. Executable, because a shortcut that cannot be
    #: launched is not a shortcut.
    mode: int = 0o755

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "target": str(self.target),
        }


@dataclass(frozen=True)
class ShortcutResult:
    """What actually happened."""

    created: bool
    path: Path
    kind: str
    target: Path
    error: Optional[str] = None

    def as_dict(self) -> dict:
        data = {
            "created": self.created,
            "path": str(self.path),
            "kind": self.kind,
            "target": str(self.target),
        }
        if self.error:
            data["error"] = self.error
        return data


def se_root() -> Path:
    """The repository root.

    This file is ``<root>/SE-INSTALLER/se_installer/shortcuts.py``. ``SE_ROOT``
    wins when it is set, mirroring how the console resolves itself.
    """
    configured = os.environ.get("SE_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2]


def console_scripts_dir(root: Optional[Path] = None) -> Path:
    """``<root>/SE-CONSOLE/scripts`` -- where the console's entry points live."""
    return (root or se_root()) / CONSOLE_DIR_NAME / CONSOLE_SCRIPTS_SUBDIR


def desktop_dir(os_type: OSType) -> Path:
    """The operator's actual Desktop.

    On Windows the Desktop is not always ``%USERPROFILE%\\Desktop`` -- OneDrive
    relocates it -- so Windows is asked rather than guessed at.
    """
    if os_type is OSType.WINDOWS:
        return _windows_desktop()
    return Path.home() / "Desktop"


def plan_shortcut(
    os_type: OSType,
    root: Optional[Path] = None,
    desktop: Optional[Path] = None,
) -> Shortcut:
    """Decide what to create. Writes nothing and runs nothing."""
    scripts = console_scripts_dir(root)
    if desktop is None:
        desktop = desktop_dir(os_type)

    if os_type is OSType.WINDOWS:
        return Shortcut(
            os_type=os_type,
            kind=KIND_WINDOWS_LNK,
            path=desktop / WINDOWS_SHORTCUT_FILE,
            target=scripts / WINDOWS_ENTRY_POINT,
        )

    if os_type is OSType.MACOS:
        target = scripts / MACOS_ENTRY_POINT
        return Shortcut(
            os_type=os_type,
            kind=KIND_MACOS_COMMAND,
            path=desktop / MACOS_SHORTCUT_FILE,
            target=target,
            contents=_macos_wrapper(target),
        )

    target = scripts / LINUX_ENTRY_POINT
    return Shortcut(
        os_type=os_type,
        kind=KIND_LINUX_DESKTOP,
        path=desktop / LINUX_SHORTCUT_FILE,
        target=target,
        contents=_linux_desktop_entry(target),
    )


def create_shortcut(shortcut: Shortcut) -> ShortcutResult:
    """Create the shortcut described by ``shortcut``.

    Refuses before writing anything if the console entry point is not there: a
    shortcut to nothing is worse than no shortcut, because it fails silently on
    the Desktop weeks later.
    """
    if not shortcut.target.exists():
        raise ShortcutError(
            f"the console entry point does not exist: {shortcut.target} "
            f"(is the installer running from the repository?)"
        )

    try:
        shortcut.path.parent.mkdir(parents=True, exist_ok=True)
        if shortcut.kind == KIND_WINDOWS_LNK:
            _write_windows_lnk(shortcut)
        else:
            # newline="\n": a generated launcher is a shell file even when the
            # installer is run on Windows against a shared output directory.
            shortcut.path.write_text(shortcut.contents or "", encoding="utf-8", newline="\n")
            os.chmod(shortcut.path, shortcut.mode)
            if shortcut.kind == KIND_LINUX_DESKTOP:
                _mark_trusted(shortcut.path)
    except ShortcutError:
        raise
    except OSError as exc:
        raise ShortcutError(f"could not create {shortcut.path}: {exc}") from exc

    return ShortcutResult(
        created=True, path=shortcut.path, kind=shortcut.kind, target=shortcut.target
    )


def install_console_shortcut(
    os_type: OSType,
    root: Optional[Path] = None,
    desktop: Optional[Path] = None,
) -> ShortcutResult:
    """Plan and create in one step. The side-effecting entry point."""
    return create_shortcut(plan_shortcut(os_type=os_type, root=root, desktop=desktop))


def _macos_wrapper(target: Path) -> str:
    """A .command on the Desktop that hands over to the console's own script.

    A symlink would be wrong: the console's launcher begins with
    ``cd "$(dirname "$0")"``, which on a Desktop symlink points at the Desktop,
    not at the scripts directory, and the console would not be found.
    """
    return (
        "#!/bin/sh\n"
        "# Generated by se-installer -- re-run the installer to regenerate.\n"
        "# Runs the console's own launcher, by absolute path (see above).\n"
        f'exec "{target}"\n'
    )


def _linux_desktop_entry(target: Path) -> str:
    """The freedesktop shortcut.

    ``Exec`` is a single double-quoted argument, so only ``"`` and ``\\`` would
    need escaping inside it -- and the recipe below contains neither. The shell
    metacharacters it does use (``;`` ``&`` ``|`` ``$`` ``>`` ``(`` ``)``) are
    literal inside the quotes, and are the shell's to interpret, not the
    Desktop Entry parser's.

    ``Terminal=true`` mirrors the Windows .cmd: a double-clicked start must be
    readable when it fails, so failures wait for a key instead of vanishing.
    """
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={SHORTCUT_NAME}\n"
        f"Comment={DESCRIPTION}\n"
        # python3 first, then python: the console's own scripts do the same.
        # xdg-open is best effort -- without it the console still starts and the
        # operator can type the URL.
        'Exec=sh -c "'
        "PY=python3; command -v python3 >/dev/null 2>&1 || PY=python; "
        f"if $PY '{target}' start; then "
        f"{{ xdg-open {CONSOLE_URL} || true; }}; "
        f"echo; echo SE Console is running: {CONSOLE_URL}; sleep 2; "
        "else "
        "echo; echo SE Console did not start. See the messages above.; "
        "read -r _; exit 1; "
        'fi"'
        "\n"
        "Icon=utilities-terminal\n"
        "Terminal=true\n"
        "Categories=Development;\n"
        "StartupNotify=false\n"
    )


def _windows_desktop() -> Path:
    """Ask Windows where the Desktop is; fall back to the usual place."""
    script = "[Environment]::GetFolderPath('Desktop')"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return Path.home() / "Desktop"
    answer = (proc.stdout or "").strip()
    if proc.returncode == 0 and answer:
        return Path(answer)
    return Path.home() / "Desktop"


def _write_windows_lnk(shortcut: Shortcut) -> None:
    """Create the .lnk through WScript.Shell, the only way Windows offers."""
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$link = $shell.CreateShortcut({_powershell_literal(str(shortcut.path))}); "
        f"$link.TargetPath = {_powershell_literal(str(shortcut.target))}; "
        f"$link.WorkingDirectory = {_powershell_literal(str(shortcut.target.parent))}; "
        f"$link.Description = {_powershell_literal(shortcut.description)}; "
        "$link.Save()"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShortcutError(
            f"could not run powershell to create the shortcut: {exc}"
        ) from exc

    if proc.returncode != 0:
        lines = [line for line in (proc.stderr or proc.stdout or "").splitlines() if line.strip()]
        detail = f": {lines[-1].strip()}" if lines else ""
        raise ShortcutError(f"powershell could not create {shortcut.path}{detail}")


def _powershell_literal(value: str) -> str:
    """A single-quoted PowerShell string literal (the only escape is '')."""
    return "'" + value.replace("'", "''") + "'"


def _mark_trusted(path: Path) -> None:
    """Best effort: GNOME will not launch a .desktop it has not been told to trust.

    Failure is not an error. Desktops without ``gio`` still run the shortcut, and
    otherwise the operator can right-click and choose "Allow launching".
    """
    try:
        subprocess.run(
            ["gio", "set", str(path), "metadata::trusted", "true"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass
