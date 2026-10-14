#!/usr/bin/env python3
"""SE-CONSOLE :: local dev lifecycle helper (start / stop / status / restart / logs).

Purpose
-------
The operator wants the console UP while they work and DOWN with one click. This
helper gives exactly that, at the OS level, with no service, no daemon and no
privileges:

* it is spawned by the operator (a shortcut is just a double-click) and the
  process it starts is a normal child of the OS, not a boot-persistent service;
* state lives under ``SE-CONSOLE/.runtime/`` (gitignored) -- one PID file and one
  log per run;
* nothing is written into the SE tree, so the console's read-only contract and
  ``se doctor``'s fingerprints are untouched;
* when it spawns the console it also ARMS the server's idle timeout (15 minutes
  by default, ``--idle-timeout``), so closing the browser is by itself enough to
  bring the console down. A console started by hand keeps the server's default
  of *no* timeout and never stops on its own.

Design rules (why the code looks like this)
-------------------------------------------
1. **One rooting decision.** ``SE_ROOT`` is taken from the console's own resolver
   (``console.se_reader.SE_ROOT``) and passed to the child EXPLICITLY. A server
   started by this tool can therefore never observe a different SE root than the
   one the tool reports.
2. **Liveness is a probe, never a PID.** A running server is recognised by
   ``GET /api/health`` answering with the console's own signature
   (``console == "se-console"`` and ``mode == "read-only"``). A recycled PID on
   the recorded port is therefore never mistaken for our server.
3. **Never kill a stranger.** ``stop`` kills only after the signature check. If
   the PID is alive but the health probe does not answer, it refuses unless
   ``--force`` is given -- a PID alone is not proof of identity.
4. **Stop cleanly where the platform allows it.** POSIX gets SIGINT, which is the
   path ``console/server.py`` already handles (``KeyboardInterrupt`` -> tidy
   shutdown). Windows has no reliable cross-process SIGINT, and the console is
   stateless (no DB, no cache, no manifest -- DESIGN), so a hard terminate is
   acceptable there.

Output is English and ASCII-safe on purpose: the console's own logs are English
(``console/server.py`` writes ``[se-console] ...``), and an ASCII surface cannot
turn into mojibake on a legacy Windows code page.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

CONSOLE_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = CONSOLE_ROOT / ".runtime"
LOGS_DIR = RUNTIME_DIR / "logs"
PID_FILE = RUNTIME_DIR / "se-console.json"

DEFAULT_HOST = os.environ.get("SE_CONSOLE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("SE_CONSOLE_PORT", "8777"))

#: How long a console started by this tool may sit with nobody asking it for
#: anything. The SERVER defaults to 0 (off) because a console started by hand in
#: a terminal must not vanish on its own; the LAUNCHER switches it on, because a
#: console started from here is the one a browser gets pointed at, and the
#: operator wants it gone once they close the tab (DESIGN-5C, decision D2).
DEFAULT_IDLE_TIMEOUT = int(os.environ.get("SE_CONSOLE_IDLE_TIMEOUT", str(15 * 60)))

START_TIMEOUT = 45.0          # seconds to wait for /api/health after spawn
STOP_TIMEOUT = 20.0           # seconds to wait for the process to disappear
POLL = 0.25

SIGNATURE_CONSOLE = "se-console"
SIGNATURE_MODE = "read-only"

#: Windows-only: 0 on other platforms, where the flag does not exist and
#: ``creationflags`` must stay 0. Keeps an auxiliary console child (``taskkill``,
#: which is itself a console app) from flashing a window when the helper runs
#: without a console of its own.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# ---------------------------------------------------------------------------
# rooting
# ---------------------------------------------------------------------------


def se_root() -> str:
    """Resolve the canonical SE root through the console's own module."""
    sys.path.insert(0, str(CONSOLE_ROOT))
    try:
        from console import se_reader  # noqa: PLC0415 (deliberate late import)

        return se_reader.SE_ROOT
    except Exception:
        # Fall back to the vendored convention so the helper still works when
        # the console package itself is broken (it must be startable enough to
        # diagnose). SE-CONSOLE/<root> => SE_ROOT is the console's parent.
        return os.environ.get("SE_ROOT") or str(CONSOLE_ROOT.parent)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _say(msg: str) -> None:
    print(f"[se-console-dev] {msg}")


def _fail(msg: str, code: int = 1) -> int:
    print(f"[se-console-dev][ERROR] {msg}", file=sys.stderr)
    return code


def _human_seconds(seconds: int) -> str:
    """900 -> '15 min'. Whole minutes only; anything else is shown as seconds."""
    if seconds and seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds}s"


def _is_windows() -> bool:
    return os.name == "nt"


def _pid_alive(pid: int) -> bool:
    """True when the PID exists. Never uses os.kill(pid, 0) on Windows, whose
    os.kill would TERMINATE the target for any signal."""
    if pid <= 0:
        return False
    if not _is_windows():
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, owned by someone else
    import ctypes  # noqa: PLC0415

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(handle)


def probe_health(host: str, port: int, timeout: float = 2.5) -> dict[str, Any] | None:
    """Return the /api/health payload, or None when nothing answers there."""
    url = f"http://{host}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (local)
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def is_our_console(payload: dict[str, Any] | None) -> bool:
    """The console's identity: a signature no other local service answers with."""
    return bool(payload) and payload.get("console") == SIGNATURE_CONSOLE and (
        payload.get("mode") == SIGNATURE_MODE
    )


# ---------------------------------------------------------------------------
# PID file
# ---------------------------------------------------------------------------


def read_pidfile() -> dict[str, Any] | None:
    if not PID_FILE.is_file():
        return None
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_pidfile(data: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_pidfile() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        _say(f"warning: could not remove {PID_FILE}: {exc}")


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def _spawn_env(host: str, port: int) -> dict[str, str]:
    env = dict(os.environ)
    env["SE_ROOT"] = se_root()                 # explicit: no inherited ambiguity
    env["SE_CONSOLE_HOST"] = host
    env["SE_CONSOLE_PORT"] = str(port)
    # Make sure the interpreter running this helper is the one reachable by the
    # console's `se` subprocess calls, even when PATH is minimal (shortcut case).
    py_dir = str(Path(sys.executable).parent)
    if py_dir not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = py_dir + os.pathsep + env.get("PATH", "")
    return env


def cmd_start(args: argparse.Namespace) -> int:
    host, port = args.host, args.port
    idle = int(args.idle_timeout)
    if idle < 0:
        return _fail("--idle-timeout must be 0 (never stop) or a positive number of seconds")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # already running?
    existing = read_pidfile()
    payload = probe_health(host, port)
    if existing and _pid_alive(int(existing.get("pid", 0))):
        if is_our_console(payload):
            _say(f"already running (pid={existing['pid']}) -> http://{host}:{port}")
            return 0
        _say(
            f"pid file exists (pid={existing.get('pid')}) but /api/health did not "
            f"answer -- refusing to start a second console; run 'stop' first"
        )
        return 1
    if existing:
        _say("clearing stale pid file")
        clear_pidfile()

    # is the port taken by something that is not ours?
    if payload is not None and not is_our_console(payload):
        return _fail(f"port {port} is in use by another service (not se-console)")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOGS_DIR / f"se-console-{stamp}.log"
    env = _spawn_env(host, port)

    kwargs: dict[str, Any] = {}
    if _is_windows():
        # CREATE_NO_WINDOW, NOT DETACHED_PROCESS. A detached server has no
        # console at all, and Windows then gives EVERY child console process its
        # own new console window -- `se` is a console app, so `/api/system` (2
        # calls) and `/api/gates` (9 calls) would each pop a window on the
        # operator's desktop. A hidden console keeps the server and all of its
        # children invisible. CREATE_NEW_PROCESS_GROUP detaches it from Ctrl+C.
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True

    _say(f"starting console (se_root={se_root()}, port={port})")
    if idle > 0:
        _say(f"idle timeout: {_human_seconds(idle)} with no client, then it stops on its own")
    else:
        _say("idle timeout: disabled (it stops only on an explicit 'stop')")
    _say(f"log -> {log_path}")
    # Passed EXPLICITLY, never inherited from the environment: the child's own
    # log line then states the value actually in force, so 'status' and the
    # console's log cannot disagree.
    argv = [sys.executable, "-m", "console.server", "--idle-timeout", str(idle)]
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(  # noqa: S603 (fixed argv, own interpreter)
            argv,
            cwd=str(CONSOLE_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            **kwargs,
        )

    write_pidfile(
        {
            "pid": proc.pid,
            "host": host,
            "port": port,
            "se_root": se_root(),
            "console_root": str(CONSOLE_ROOT),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "idle_timeout": idle,
            "log": str(log_path),
        }
    )

    # wait for liveness
    deadline = time.time() + (args.timeout if args.timeout else START_TIMEOUT)
    while time.time() < deadline:
        if proc.poll() is not None:
            _fail(f"console exited immediately (code {proc.returncode})")
            _tail(log_path, 20)
            clear_pidfile()
            return 1
        if is_our_console(probe_health(host, port)):
            _say(f"console is UP -> http://{host}:{port}  (pid={proc.pid})")
            return 0
        time.sleep(POLL)

    _fail(f"console did not become healthy within {deadline - (time.time() - START_TIMEOUT):.0f}s")
    _tail(log_path, 20)
    _terminate(proc.pid)
    clear_pidfile()
    return 1


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def _terminate(pid: int) -> None:
    """Best-effort stop. SIGINT on POSIX (the server handles it); taskkill on
    Windows (the console is stateless, so a hard stop loses nothing)."""
    if not _pid_alive(pid):
        return
    if _is_windows():
        subprocess.run(  # noqa: S603, S607
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=NO_WINDOW,
        )
        return
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    except OSError as exc:
        _say(f"warning: SIGINT failed ({exc}); sending SIGTERM")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return


def cmd_stop(args: argparse.Namespace) -> int:
    data = read_pidfile()
    if not data:
        return _fail("not running (no pid file); if you started it by hand, stop it in its own terminal")

    pid = int(data.get("pid", 0))
    host = data.get("host", DEFAULT_HOST)
    port = int(data.get("port", DEFAULT_PORT))
    payload = probe_health(host, port)

    if not _pid_alive(pid):
        _say(f"pid {pid} is gone -- clearing stale pid file")
        clear_pidfile()
        return 0

    if not is_our_console(payload) and not args.force:
        _say(
            f"pid {pid} is alive but /api/health on {host}:{port} did not answer "
            f"with the se-console signature."
        )
        return _fail(
            "refusing to kill a process that was not proven to be this console "
            "(use --force only if you know it is the console)"
        )

    _say(f"stopping pid {pid} ...")
    _terminate(pid)

    deadline = time.time() + STOP_TIMEOUT
    while time.time() < deadline:
        if not _pid_alive(pid) and not is_our_console(probe_health(host, port)):
            clear_pidfile()
            _say("console is DOWN")
            return 0
        time.sleep(POLL)

    if not is_our_console(probe_health(host, port)):
        clear_pidfile()
        _say("console is DOWN (port no longer answers)")
        return 0
    return _fail(f"console still answering on {host}:{port} after {STOP_TIMEOUT:.0f}s")


# ---------------------------------------------------------------------------
# status / restart / logs
# ---------------------------------------------------------------------------


def _status_data() -> dict[str, Any]:
    data = read_pidfile()
    host = data.get("host", DEFAULT_HOST) if data else DEFAULT_HOST
    port = int(data.get("port", DEFAULT_PORT)) if data else DEFAULT_PORT
    payload = probe_health(host, port)
    alive = bool(data) and _pid_alive(int(data.get("pid", 0)))
    if is_our_console(payload):
        state = "running"
    elif data and alive:
        state = "stale"          # pid alive, not proven to be the console
    elif data:
        state = "stopped"        # pid file left behind, process gone
    else:
        state = "stopped"
    return {
        "state": state,
        "pid": data.get("pid") if data else None,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "se_root": (payload or {}).get("se_root") or (data or {}).get("se_root"),
        "health": (payload or {}).get("status"),
        "version": (payload or {}).get("version"),
        # Configured by THIS tool at start, read back from its own PID file. It
        # is deliberately not read from the server: /api/health carries no idle
        # timeout, and adding a field there would change a frozen response shape
        # (DESIGN-5B). None means "we did not start this one", so we do not claim
        # to know its value.
        "idle_timeout": (data or {}).get("idle_timeout"),
        "log": (data or {}).get("log"),
    }


def cmd_status(args: argparse.Namespace) -> int:
    info = _status_data()
    if args.json:
        print(json.dumps(info, indent=2))
        return 0
    if info["state"] == "running":
        _say(f"RUNNING  {info['url']}  pid={info['pid']}  health={info['health']}")
        _say(f"se_root={info['se_root']}  version={info['version']}")
        idle = info.get("idle_timeout")
        if isinstance(idle, int) and idle > 0:
            _say(f"idle_timeout={_human_seconds(idle)}  (stops after that long with no client)")
        elif isinstance(idle, int):
            _say("idle_timeout=off  (it will not stop on its own)")
        elif info.get("pid") is None:
            _say("idle_timeout=unknown  (not started by this tool)")
        else:
            # A PID file with no idle_timeout field was written before the option
            # existed. Say that, rather than guess a value never recorded.
            _say("idle_timeout=unknown  (started before this option existed)")
        if info["log"]:
            _say(f"log -> {info['log']}")
    elif info["state"] == "stale":
        _say(f"STALE    pid={info['pid']} is alive but {info['url']} is not answering as se-console")
    else:
        _say("STOPPED  (no console running)")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    rc = cmd_stop(argparse.Namespace(force=args.force))
    if rc != 0:
        return rc
    return cmd_start(args)


def _tail(path: Path, n: int) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"[se-console-dev] no log at {path}: {exc}", file=sys.stderr)
        return
    print(f"--- last {min(n, len(lines))} lines of {path.name} ---")
    for line in lines[-n:]:
        print(line)


def cmd_logs(args: argparse.Namespace) -> int:
    data = read_pidfile()
    path = Path(data["log"]) if data and data.get("log") else None
    if path is None or not path.is_file():
        if not LOGS_DIR.is_dir():
            return _fail("no logs yet (nothing has been started)")
        candidates = sorted(LOGS_DIR.glob("se-console-*.log"))
        if not candidates:
            return _fail("no logs yet")
        path = candidates[-1]
    _tail(path, args.lines)
    if args.follow:
        _say("following (Ctrl+C to stop) ...")
        pos = path.stat().st_size
        try:
            while True:
                time.sleep(0.5)
                size = path.stat().st_size
                if size < pos:      # rotated/truncated
                    pos = 0
                if size > pos:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        sys.stdout.write(fh.read())
                        sys.stdout.flush()
                        pos = fh.tell()
        except KeyboardInterrupt:
            return 0
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_idle_argument(parser: argparse.ArgumentParser) -> None:
    """The same flag on ``start`` and ``restart``, so they cannot drift apart."""
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT,
        metavar="SECONDS",
        help=(
            "stop the console once no client has asked it for anything for "
            f"SECONDS (default {DEFAULT_IDLE_TIMEOUT}s = "
            f"{_human_seconds(DEFAULT_IDLE_TIMEOUT)}); use 0 to disable. The "
            "count only starts after the first client connects, so a console "
            "nobody opens never stops on its own."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dev_console.py",
        description="Start/stop the local SE-CONSOLE without a service or privileges.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start", help="start the console in the background")
    s.add_argument("--host", default=DEFAULT_HOST)
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--timeout", type=float, default=START_TIMEOUT)
    _add_idle_argument(s)
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("stop", help="stop the console started by this tool")
    s.add_argument("--force", action="store_true", help="stop even if identity is unproven")
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("status", help="show whether the console is running")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("restart", help="stop then start")
    s.add_argument("--host", default=DEFAULT_HOST)
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--timeout", type=float, default=START_TIMEOUT)
    s.add_argument("--force", action="store_true")
    _add_idle_argument(s)
    s.set_defaults(func=cmd_restart)

    s = sub.add_parser("logs", help="tail the console log")
    s.add_argument("-n", "--lines", type=int, default=40)
    s.add_argument("--follow", action="store_true")
    s.set_defaults(func=cmd_logs)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
