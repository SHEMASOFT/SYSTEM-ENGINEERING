"""Path helpers and small IO utilities."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def repo_root() -> Path:
    """Return the Master System repository root."""
    return Path(__file__).resolve().parents[2]


def load_json(path: Path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data) -> None:
    """Write JSON atomically (delegates to :func:`write_json_atomic`)."""
    write_json_atomic(path, data)


def write_json_atomic(path: Path, data) -> None:
    """Write JSON via a unique temporary file and atomic replace (no half-written records).

    The temp name is unique per writer so concurrent writers of the same target do not
    clobber each other's staging file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tree_fingerprint(root: Path, rel_dirs) -> tuple:
    """Return a cheap change-detection fingerprint for files under ``rel_dirs``.

    Each entry is ``(relative_posix_path, st_mtime_ns, st_size)`` sorted by path. Any
    add, remove, content change, or touch of a covered file changes the fingerprint, so
    it can key a memoization cache without ever serving a stale result. ``st_mtime_ns``
    has nanosecond resolution, so a same-size rewrite is still detected.

    Uses ``os.scandir`` because on Windows (and DrvFs mounts) the directory enumeration
    already returns mtime and size, making ``DirEntry.stat()`` free. ``pathlib.rglob``
    plus ``Path.stat()`` issues one extra syscall per file, which costs ~10ms each on a
    DrvFs mount.
    """
    root = Path(root)
    entries = []
    for rel_dir in rel_dirs:
        base = root / rel_dir
        if not base.is_dir():
            continue
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as scan:
                    for entry in scan:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                                continue
                            stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        path = Path(entry.path)
                        entries.append(
                            (
                                path.relative_to(root).as_posix(),
                                stat.st_mtime_ns,
                                stat.st_size,
                            )
                        )
            except OSError:
                continue
    return tuple(sorted(entries))


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
