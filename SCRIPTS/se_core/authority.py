"""Operator authority for MANUAL attestation (C1).

A MANUAL gate is a decision only a human may take. A string passed on the
command line is not evidence of *who* took it: ``--by`` is audit metadata that
the caller types, so on its own it cannot distinguish the responsible operator
from a script that copied the owner's name. The proof of authority is therefore
possession of the SE-CONSOLE operator token, the same secret the console
already uses to authorise its action surface (``SE-CONSOLE/console/auth.py``).

This module MIRRORS that reference implementation instead of importing it:
``se_core`` is the engine and must not depend on ``SE-CONSOLE/``. The literal
path, the creation mode (0600, ``secrets.token_urlsafe(32)``) and the
constant-time comparison are deliberately identical, so one token authorises
both surfaces. ``TESTS/test_attest_authority.py`` pins that agreement.

FAIL CLOSED. A missing, empty or unreadable token is a REFUSAL, never an
allow. The token VALUE is never printed, logged or recorded: only its path is
ever mentioned, and audit records carry a truncated SHA-256 fingerprint.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
from pathlib import Path

from .paths import now_utc


def token_path() -> Path:
    """Where the operator token lives: outside the repository, by design."""
    return Path.home() / ".config" / "se-console" / "token"


def load_token() -> str | None:
    """Return the stored operator token, creating it on first use.

    Mirrors ``SE-CONSOLE/console/auth.py:load_token``: created 0600 with
    ``secrets.token_urlsafe(32)``, a lost creation race re-reads the winner's
    token, and any OSError -- or an empty file -- yields ``None`` so the caller
    refuses. Only the path is printed, never the value.
    """
    path = token_path()
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if not value:
                sys.stderr.write(f"[se] operator token file is empty: {path}\n")
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
        sys.stderr.write(f"[se] operator token created at {path}\n")
        return value
    except OSError as exc:
        sys.stderr.write(f"[se] cannot read operator token at {path}: {exc}\n")
        return None


def fingerprint(token: str) -> str:
    """A non-reversible, truncated identifier for the audit record."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def verify(presented: str, *, source: str) -> tuple[bool, dict]:
    """Constant-time check of a presented token against the stored one.

    Returns ``(ok, proof)``. ``proof`` is the audit evidence -- the METHOD the
    token arrived by, WHEN it was verified and a FINGERPRINT of the stored
    token -- and is empty when verification fails. The token itself is never
    echoed or recorded. Fail closed when no stored token is readable.
    """
    if not presented:
        return False, {}
    stored = load_token()
    if stored is None:
        return False, {}
    try:
        matches = hmac.compare_digest(presented.strip(), stored)
    except TypeError:  # non-str input is not a token; refuse rather than raise
        return False, {}
    if not matches:
        return False, {}
    return True, {
        "method": source,
        "verified_at": now_utc(),
        "token_fingerprint": fingerprint(stored),
    }


def resolve_presented_token(args, env=None) -> tuple[str | None, str | None]:
    """Find the token the caller presented, and say HOW.

    Precedence: ``--console-token`` (``"flag"``) > ``SE_CONSOLE_TOKEN``
    (``"env"``) > ``--console-token-file PATH`` (``"file"``). An unreadable or
    empty token file resolves to ``(None, None)`` so the caller refuses.
    """
    env = os.environ if env is None else env

    flag_value = getattr(args, "console_token", None)
    if flag_value:
        return str(flag_value).strip(), "flag"

    env_value = env.get("SE_CONSOLE_TOKEN")
    if env_value:
        return str(env_value).strip(), "env"

    token_file = getattr(args, "console_token_file", None)
    if token_file:
        try:
            value = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return None, None
        if value:
            return value, "file"
    return None, None
