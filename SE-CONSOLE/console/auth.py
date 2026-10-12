"""SE-CONSOLE :: operator authentication for the action surface (DESIGN-5B §5).

The console is GET-only by default; `POST /api/action` is the single named
exception. Without controls, any page the operator happens to have open could
drive that route (CSRF) or a rebound DNS name could reach it (DNS rebinding).
This module is the gate in front of it:

  * a bearer token, generated once with `secrets.token_urlsafe(32)` and stored
    at ``~/.config/se-console/token`` with mode 0600 -- OUTSIDE the repository,
    so it can never be committed;
  * the token is compared in constant time (`hmac.compare_digest`);
  * a mandatory CUSTOM header (`X-SE-Console-Token`): a cross-origin page
    cannot set a custom header without a CORS preflight, and the console never
    grants one (it emits no CORS headers at all);
  * `Origin`, when present, must be same-origin (127.0.0.1/localhost on this
    port). Absent is allowed for non-browser clients;
  * `Host` must be 127.0.0.1/localhost on this port (DNS-rebinding).

FAIL CLOSED. Any error reading or creating the token -- missing directory that
cannot be created, unreadable file, empty file -- is a REFUSAL, never an
allow. A security check that fails open is worse than no check at all.

The token VALUE is never logged. Only its path is ever printed.
"""

from __future__ import annotations

import hmac
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Mapping

#: The mandatory custom header. Deliberately not `Authorization: Bearer`:
#: setting an arbitrary custom header forces a CORS preflight, which this
#: console never answers.
TOKEN_HEADER = "X-SE-Console-Token"

#: The only route this guard exists for.
ACTION_PATH = "/api/action"


def token_path() -> Path:
    """Where the operator token lives: outside the repository, by design."""
    return Path.home() / ".config" / "se-console" / "token"


def load_token() -> str | None:
    """Return the stored token, creating it on first use.

    Returns ``None`` when the token cannot be read or created -- callers must
    treat that as a refusal.
    """
    path = token_path()
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if not value:
                sys.stderr.write(f"[se-console] action token file is empty: {path}\n")
                return None
            return value

        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Lost a creation race: the winner's token is authoritative.
            value = path.read_text(encoding="utf-8").strip()
            return value or None
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        # Log the path, never the value.
        sys.stderr.write(f"[se-console] action token created at {path}\n")
        return value
    except OSError as exc:
        sys.stderr.write(f"[se-console] cannot read action token at {path}: {exc}\n")
        return None


def _header(headers: Any, name: str) -> str | None:
    """Case-insensitive header lookup for both `email.message.Message` (what
    the stdlib server hands us) and plain mappings (what tests hand us)."""
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is None:
            value = getter(name.lower())
        if value is not None:
            return str(value)
    items = getattr(headers, "items", None)
    if callable(items):
        lowered = name.lower()
        for key, value in items():
            if str(key).lower() == lowered:
                return str(value)
    return None


def guard(
    headers: Mapping[str, Any] | Any,
    *,
    method: str,
    path: str,
    port: int,
) -> str | None:
    """Authorise an action request. ``None`` = allowed, string = refusal.

    The refusal reason is prefixed with the failed control (``method:``,
    ``path:``, ``host:``, ``origin:``, ``token:``) so the caller can map it to
    the right HTTP status without re-deriving the verdict.
    """
    if method != "POST":
        return f"method:{method} is not accepted on the action surface"
    if path != ACTION_PATH:
        return f"path:{path} is not the action route"

    # Host first: a rebound name never gets as far as reading the token.
    host = _header(headers, "Host")
    if host is None:
        return "host:missing Host header"
    host = host.strip().lower()
    if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return f"host:{host!r} is not 127.0.0.1/localhost on port {port}"

    # Origin: absent is fine (curl, tests, non-browser clients); anything
    # present must be same-origin.
    origin = _header(headers, "Origin")
    if origin is not None:
        origin = origin.strip()
        if origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return f"origin:{origin!r} is not same-origin"

    token = _header(headers, TOKEN_HEADER)
    if token is None:
        return f"token:missing {TOKEN_HEADER} header"
    stored = load_token()
    if stored is None:
        return "token:action token unavailable (fail closed)"
    if not hmac.compare_digest(token.strip(), stored):
        return "token:incorrect action token"
    return None


def status_for(reason: str) -> int:
    """Map a refusal reason to its HTTP status.

    403 for a request that reached us with the wrong provenance (Origin/Host),
    401 for failed authentication, 405 for a method/path the surface does not
    accept (defence in depth; the router normally rejects those first).
    """
    if reason.startswith(("origin:", "host:")):
        return 403
    if reason.startswith(("method:", "path:")):
        return 405
    return 401
