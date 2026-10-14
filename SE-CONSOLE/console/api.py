"""SE-CONSOLE :: HTTP API.

Read-only is enforced in three independent layers, so no single mistake can
turn the console into a writer (DESIGN-5B §6 revises exactly layer 1):
  1. The route table contains GET handlers only. The single exception is the
     explicitly named `POST_ROUTES` surface (`/api/action`), which is
     authenticated, catalog-allowlisted, and validated before any subprocess.
  2. Any other non-GET/HEAD/OPTIONS method is rejected with 405 + Allow.
  3. Static file serving is confined to WEB_ROOT and refuses traversal.

No database, no ledger. Every request re-reads the canonical SE tree; the one
shared exception is the audit *engine output* (`se doctor` + `se capabilities`),
which is held as a single refreshed pass in `console/audit.py` so `/api/system`
does not re-run the full audit on every page load. It caches `se`'s own
envelope verbatim, carries its age, and computes no verdict of its own.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import sys
import urllib.parse
from typing import Any, Callable

from . import actions, auth, read_model, se_cli, se_reader

WEB_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}

#: Project rel paths must stay inside PROJECTS/ and contain no traversal.
_SAFE_RELPATH = re.compile(r"^PROJECTS/[A-Za-z0-9._\-/]+$")
_VALID_TYPES = frozenset(se_reader.RECORD_LAYOUT)
_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


def _error(status: int, message: str, **extra: Any) -> tuple[int, dict[str, Any]]:
    return status, {"status": "ERROR", "http_status": status, "message": message, **extra}


# --------------------------------------------------------------------------
# API handlers
# --------------------------------------------------------------------------


def api_health(_m: dict) -> tuple[int, dict[str, Any]]:
    """Liveness of the console process and its ability to reach `se`.

    `status` describes the CONSOLE, not SYSTEM-ENGINEERING. It is `OK` only when
    the engine is actually operational; when the engine cannot be invoked the
    endpoint answers `DEGRADED` and carries the reason. It must never report a
    green console while every governance read is failing -- that would let an
    outage look like a healthy system.
    """
    probe = se_cli.probe_se()
    operational = bool(probe["operational"])
    return 200, {
        "status": "OK" if operational else "DEGRADED",
        "console": "se-console",
        "version": read_model.CONSOLE_VERSION,
        "mode": "read-only",
        "se_available": operational,
        "se_probe": {
            "epistemic": "OBSERVED",
            "operational": operational,
            "entry_present": probe["entry_present"],
            "reason": probe["reason"],
            "detail": probe["detail"],
            "probed_at": probe["probed_at"],
        },
        "se_root": se_reader.SE_ROOT,
        "generated_at": read_model._now(),
    }


def api_system(_m: dict) -> tuple[int, dict[str, Any]]:
    return 200, read_model.build_system_overview()


def api_projects(_m: dict) -> tuple[int, dict[str, Any]]:
    return 200, read_model.build_project_list()


def api_project_detail(m: dict) -> tuple[int, dict[str, Any]]:
    rel = (m.get("rel_path") or "").strip("/")
    if not _SAFE_RELPATH.match(rel) or ".." in rel:
        return _error(400, "invalid project path", rel_path=rel)
    return 200, read_model.build_project_detail(rel)


def api_record_detail(m: dict) -> tuple[int, dict[str, Any]]:
    rel = (m.get("rel_path") or "").strip("/")
    rtype = (m.get("type") or "").upper()
    rid = (m.get("id") or "").strip()
    if not _SAFE_RELPATH.match(rel) or ".." in rel:
        return _error(400, "invalid project path", rel_path=rel)
    if rtype not in _VALID_TYPES:
        return _error(400, f"unknown record type {rtype!r}", allowed=sorted(_VALID_TYPES))
    if not _ID_RE.match(rid):
        return _error(400, "invalid record id", id=rid)
    return 200, read_model.build_record_detail(rel, rtype, rid)


def api_provenance(_m: dict) -> tuple[int, dict[str, Any]]:
    return 200, read_model.build_provenance()


def api_heartbeat(_m: dict) -> tuple[int, dict[str, Any]]:
    """Liveness ping for the console's LIFECYCLE, not a governance read.

    Added for DESIGN-5C (option A). The front end says "a client is still here"
    on a timer, and the server stops itself when nobody has said so for a while
    (`--idle-timeout`, off by default). The trigger is the ABSENCE of this call —
    which is exactly why it survives a browser crash or a kill, where
    `pagehide`/`sendBeacon` never fire at all.

    It reads no SE state and spawns no subprocess, so it cannot become a second
    cache of canonical data: there is nothing here to cache. And it is a GET,
    like every other route — no exception to the read-only surface is added or
    needed (DESIGN-5C §6).
    """
    return 200, {
        "status": "OK",
        "console": "se-console",
        "version": read_model.CONSOLE_VERSION,
        "purpose": "lifecycle heartbeat",
        "generated_at": read_model._now(),
    }


ROUTES: dict[str, Callable[[dict], tuple[int, dict]]] = {
    "/api/health": api_health,
    "/api/heartbeat": api_heartbeat,
    "/api/system": api_system,
    "/api/projects": api_projects,
    "/api/project": api_project_detail,
    "/api/record": api_record_detail,
    "/api/provenance": api_provenance,
}


# --------------------------------------------------------------------------
# POST surface (DESIGN-5B): the single, named exception to GET-only
# --------------------------------------------------------------------------


def api_action(
    *,
    body: bytes,
    headers: Any,
    method: str,
    path: str,
    port: int,
) -> tuple[int, dict[str, Any]]:
    """Handle `POST /api/action`: delegate one catalog action to `se`.

    The order below is mandatory, not stylistic:

      (a) parse the body           -- malformed JSON is a 400, nothing runs;
      (b) auth guard               -- a refusal here means `se` is NEVER
                                      invoked (no token, bad Origin, bad Host);
      (c) action validation        -- catalog / project / run / params are
                                      validated hard BEFORE any subprocess;
      (d) extract the `se` result  -- the delegation itself;
      (e) audit line               -- the console records that it delegated.

    The response is the `se` result envelope plus the action id and the
    idempotency key, so a client can correlate a replay with its original.
    An `se`-side refusal (e.g. stale expected revision) is relayed as the
    envelope's own status -- the console does not translate engine verdicts
    into different HTTP codes and pretend to a verdict it did not make.
    """
    # (a) parse body
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _error(400, f"malformed JSON body: {exc}")
    if not isinstance(payload, dict):
        return _error(400, "JSON body must be an object")

    # (b) auth guard -- before validation, before any `se` invocation.
    reason = auth.guard(headers, method=method, path=path, port=port)
    if reason is not None:
        return _error(auth.status_for(reason), f"refused: {reason}")

    # (c) action validation
    try:
        action_plan = actions.plan(payload)
    except actions.Refused as exc:
        return _error(400, str(exc))

    # (d) extract the se result
    try:
        result, meta = se_cli.run_se(action_plan.argv)
    except se_cli.SeError as exc:
        # Defence in depth: validation should have caught this already.
        return _error(500, f"console refused to delegate: {exc}")

    # (e) audit line -- after the delegation, for every attempt, pass or fail.
    try:
        actions.write_audit(action_plan, meta, result)
    except OSError as exc:
        actions.audit_failure(exc)
        result.setdefault("warnings", []).append(
            f"console audit write failed: {exc} (se still applied the action)"
        )

    return 200, {
        **result,
        "action": action_plan.action,
        "idempotency_key": action_plan.idempotency_key,
    }


#: Routes that accept POST. Everything else stays GET-only; `server.py`
#: dispatches POST to these and nothing more.
POST_ROUTES: dict[str, Callable[..., tuple[int, dict]]] = {
    "/api/action": api_action,
}


# --------------------------------------------------------------------------
# Static files (read-only, traversal-safe)
# --------------------------------------------------------------------------


def resolve_static(url_path: str) -> tuple[str | None, str]:
    """Map a URL to a file inside WEB_ROOT, or refuse."""
    if url_path in ("/", ""):
        url_path = "/index.html"
    # normalise then reject anything that tried to escape
    clean = posixpath.normpath(urllib.parse.unquote(url_path))
    if clean.startswith("..") or clean.startswith("/") is False and ".." in clean:
        return None, "text/plain; charset=utf-8"
    rel = clean.lstrip("/")
    if rel.startswith("../") or "..\\" in rel:
        return None, "text/plain; charset=utf-8"

    full = os.path.normpath(os.path.join(WEB_ROOT, rel))
    root = os.path.abspath(WEB_ROOT)
    if not os.path.abspath(full).startswith(root):
        return None, "text/plain; charset=utf-8"
    if not os.path.isfile(full):
        return None, "text/plain; charset=utf-8"
    ext = os.path.splitext(full)[1].lower()
    return full, CONTENT_TYPES.get(ext, "application/octet-stream")


def parse(path: str) -> tuple[str, dict[str, str]]:
    p = urllib.parse.urlsplit(path)
    query = {
        k: v[0] for k, v in urllib.parse.parse_qs(p.query, keep_blank_values=True).items()
    }
    return p.path, query
