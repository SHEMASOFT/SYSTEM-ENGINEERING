"""SE-CONSOLE :: bounded TTL cache for expensive project reads.

`/api/projects` runs a deep `se context` per managed project and
`/api/project?rel_path=...` repeats that for one project, so the Attention view
(fan-out over every project) cost 10-30 s per project and blocked the page.

This module holds each read for a short TTL and refreshes it in the background,
so repeating a read is instant. It is deliberately narrow:

* it caches canonical *file and `se` output*, never a governance verdict;
* a cold read always runs the real producer -- no caller ever sees an empty
  snapshot and nothing is invented;
* the age travels with the payload so the console can show how fresh it is;
* `invalidate()` is called on the one mutating surface (`POST /api/action`) so a
  write is never followed by a stale cached read.

Env: SE_CONSOLE_CACHE_TTL (seconds, default 20; 0 disables the cache).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

DEFAULT_TTL_SECONDS = 20.0

_lock = threading.RLock()
_entries: dict[str, dict[str, Any]] = {}


def ttl_seconds() -> float:
    try:
        return float(os.environ.get("SE_CONSOLE_CACHE_TTL", DEFAULT_TTL_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS


def invalidate(prefix: str | None = None) -> None:
    """Drop cached reads. With a prefix, only that family (e.g. ``project``)."""
    with _lock:
        if prefix is None:
            _entries.clear()
        else:
            for k in [k for k in _entries if k.startswith(prefix)]:
                _entries.pop(k, None)


def _refresh_locked(key: str, producer: Callable[[], Any]) -> None:
    """Mark an entry as refreshing; the producer runs off the request thread."""
    entry = _entries[key]
    entry["refreshing"] = True
    t = threading.Thread(target=_bg, args=(key, producer), daemon=True)
    t.start()


def _bg(key: str, producer: Callable[[], Any]) -> None:
    try:
        value = producer()
    except Exception:  # keep the previous value; the next read retries
        with _lock:
            entry = _entries.get(key)
            if entry is not None:
                entry["refreshing"] = False
        return
    with _lock:
        entry = _entries.setdefault(key, {})
        entry["value"] = value
        entry["at"] = time.time()
        entry["refreshing"] = False


def get(key: str, producer: Callable[[], Any]) -> Any:
    """Return the cached value when fresh, otherwise run the producer.

    A stale-but-present value is served immediately while a background
    refresh replaces it, so a slow read is paid once instead of on every
    request.
    """
    ttl = ttl_seconds()
    with _lock:
        entry = _entries.get(key)
        now = time.time()
        if entry is not None and "value" in entry:
            age = now - entry.get("at", 0.0)
            if ttl <= 0 or age < ttl:
                entry["last_hit"] = now
                return entry["value"]
            if not entry.get("refreshing"):
                _refresh_locked(key, producer)
            entry["last_hit"] = now
            return entry["value"]
    value = producer()
    with _lock:
        entry = _entries.setdefault(key, {})
        entry["value"] = value
        entry["at"] = time.time()
        entry["refreshing"] = False
        entry["last_hit"] = time.time()
    return value


def age_of(key: str) -> float | None:
    """Age in seconds of the cached entry, or None when nothing is cached."""
    with _lock:
        entry = _entries.get(key)
        if entry is None or "at" not in entry:
            return None
        return max(0.0, time.time() - entry["at"])


def stats() -> dict[str, Any]:
    """Counts only: how many reads are cached and refreshing (diagnostics)."""
    with _lock:
        return {
            "entries": len(_entries),
            "refreshing": sum(1 for e in _entries.values() if e.get("refreshing")),
            "ttl_seconds": ttl_seconds(),
        }