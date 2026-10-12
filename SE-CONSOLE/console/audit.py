"""SE-CONSOLE :: the single shared `se` audit pass.

`/api/system` used to invoke `se doctor` (and `se capabilities`) synchronously
on every request, so each page load and each refresh re-ran the full audit and
waited for it -- the dominant cost of opening the console.

This module runs that audit as ONE single-flight pass and keeps the result, so
consecutive requests reuse it instead of spawning `se` again. The console still
computes nothing: the snapshot holds `se`'s own `se.report/1` envelopes
verbatim. The snapshot carries its own age so a reader can see how fresh the
audit is, and a cold read falls back to one synchronous pass -- no caller ever
sees an empty audit, and no two `se doctor` runs happen at the same time.

This is deliberately narrow: it caches the audit *engine output*, not a
governance verdict. Every other read in the console still re-reads the
canonical SE tree on each request.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from . import se_cli

#: How often the background refresher re-runs the audit. The audit is a
#: point-in-time observation; a bounded refresh keeps it from drifting stale
#: without re-running it on every request.
DEFAULT_REFRESH_SECONDS = 120

_cond = threading.Condition()
_running = False
_state: dict[str, Any] = {"doctor": None, "capabilities": None, "at": 0.0}
_bg_started = False


def _snapshot_locked() -> dict[str, Any] | None:
    if _state["doctor"] is None:
        return None
    return {
        "doctor": _state["doctor"],
        "capabilities": _state["capabilities"],
        "at": _state["at"],
        "age_seconds": max(0.0, time.time() - _state["at"]),
    }


def _run_pass() -> None:
    """Run one audit pass and publish it atomically."""
    doctor = se_cli.run_se(["doctor"])
    capabilities = se_cli.run_se(["capabilities"])
    with _cond:
        _state["doctor"] = doctor
        _state["capabilities"] = capabilities
        _state["at"] = time.time()


def snapshot() -> dict[str, Any] | None:
    """Return the latest audit pass, or None when none has completed yet."""
    with _cond:
        return _snapshot_locked()


def get_or_run() -> dict[str, Any]:
    """Return the shared audit pass, running one pass if it is cold.

    Single-flight: if a pass is already running (e.g. the boot warm-up), a cold
    caller waits for that same pass instead of starting a second `se doctor`.
    """
    global _running
    with _cond:
        snap = _snapshot_locked()
        if snap is not None:
            return snap
        if _running:
            _cond.wait_for(lambda: not _running)
            snap = _snapshot_locked()
            if snap is not None:
                return snap
        _running = True
    try:
        _run_pass()
    finally:
        with _cond:
            _running = False
            _cond.notify_all()
    with _cond:
        return _snapshot_locked() or _empty()


def refresh() -> None:
    """Run one pass unless one is already in flight (used by the refresher)."""
    global _running
    with _cond:
        if _running:
            return
        _running = True
    try:
        _run_pass()
    finally:
        with _cond:
            _running = False
            _cond.notify_all()


def _empty() -> dict[str, Any]:
    # Only reachable if `se_cli.run_se` raises inside `_run_pass`; degrade to an
    # explicit empty snapshot rather than fabricate a verdict.
    return {"doctor": None, "capabilities": None, "at": time.time(), "age_seconds": 0.0}


def reset() -> None:
    """Drop the snapshot (tests only)."""
    with _cond:
        _state["doctor"] = None
        _state["capabilities"] = None
        _state["at"] = 0.0


def start_background(interval: int = DEFAULT_REFRESH_SECONDS) -> None:
    """Warm the snapshot now and keep it refreshed in a daemon thread."""
    global _bg_started
    with _cond:
        if _bg_started:
            return
        _bg_started = True

    def loop() -> None:
        while True:
            try:
                refresh()
            except Exception:  # a failed pass must not kill the refresher
                pass
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="se-console-audit").start()
