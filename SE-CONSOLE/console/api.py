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

from . import actions, auth, read_cache, read_model, project_memory, se_cli, se_reader

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
#: Canonical SE root (re-exported from se_cli)
SE_ROOT = se_cli.SE_ROOT


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
    return 200, read_cache.get("projects", read_model.build_project_list)


def api_project_detail(m: dict) -> tuple[int, dict[str, Any]]:
    rel = (m.get("rel_path") or "").strip("/")
    if not _SAFE_RELPATH.match(rel) or ".." in rel:
        return _error(400, "invalid project path", rel_path=rel)
    key = "project:" + rel
    detail = read_cache.get(key, lambda: read_model.build_project_detail(rel))
    # The list carries no per-project depth; mark freshness so the UI can tell
    # a served-from-cache read from a fresh one without inventing an age.
    detail = dict(detail)
    detail["_cache"] = {
        "key": key,
        "age_seconds": read_cache.age_of(key),
        "ttl_seconds": read_cache.ttl_seconds(),
    }
    return 200, detail


def warm_attention() -> None:
    """Pre-fill the attention cache off the request path.

    The first cold read costs ~45 s because it runs one deep read per managed
    project. Doing that once at startup (same shape as `audit.start_background`)
    means the first person to open the tab does not pay for it, and the next
    refresh replaces the value in place.
    """
    import threading

    def _bg() -> None:
        try:
            api_attention({})
        except Exception:  # a failed warm only costs a slow first read
            pass

    threading.Thread(target=_bg, daemon=True).start()


def api_attention(_m: dict) -> tuple[int, dict[str, Any]]:
    """Aggregate every managed project's attention items in ONE request.

    The Attention view used to fan out `/api/project` per project from the
    browser (one deep read each, in series), which is what made the tab slow.
    Here the same canonical reads are done server-side and reuse the bounded
    TTL cache, so the first load pays the cost and the rest are instant.
    """
    projects = read_cache.get("projects", read_model.build_project_list) or {}
    out_items: list[dict[str, Any]] = []
    for p in projects.get("projects", []) or []:
        if p.get("management") != "MANAGED":
            continue
        rel = p.get("rel_path")
        if not rel:
            continue
        key = "project:" + rel
        detail = read_cache.get(key, lambda r=rel: read_model.build_project_detail(r)) or {}
        for item in ((detail.get("attention") or {}).get("items") or []):
            it = dict(item)
            it["_project"] = rel
            it["_project_name"] = p.get("dir_name") or p.get("name") or rel
            out_items.append(it)
    order = {"BLOCKED": 0, "WARNING": 1, "UNKNOWN": 2, "INFO": 3}
    out_items.sort(key=lambda i: (order.get(str(i.get("severity", "")).upper(), 9),
                                  str(i.get("_project", "")), str(i.get("id", ""))))
    counts = {
        "total": len(out_items),
        "BLOCKED": sum(1 for i in out_items if i.get("severity") == "BLOCKED"),
        "WARNING": sum(1 for i in out_items if i.get("severity") == "WARNING"),
    }
    return 200, {
        "counts": counts,
        "items": out_items,
        "projects": [p.get("rel_path") for p in (projects.get("projects", []) or [])
                     if p.get("management") == "MANAGED"],
        "note": "Aggregated per project from the same canonical reads as /api/project; "
                "severity orders attention, it is not a governance verdict.",
        "generated_at": read_model._now(),
    }


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


# --------------------------------------------------------------------------
# P3-B.1: Memory endpoints (read-only)
# --------------------------------------------------------------------------


def api_memory_get(m: dict) -> tuple[int, dict[str, Any]]:
    """Get a single memory by ID: GET /api/memory/get?project=...&memory_id=..."""
    project_rel = (m.get("project") or "").strip("/")
    memory_id = (m.get("memory_id") or "").strip()

    if not project_rel or not _SAFE_RELPATH.match(project_rel):
        return _error(400, "valid --project required (PROJECTS/...)", project=project_rel)
    if not memory_id:
        return _error(400, "--memory_id required")

    # Resolve project path
    project_path = os.path.join(_SE_ROOT, project_rel)
    if not os.path.isdir(project_path):
        return _error(404, "project not found", project=project_rel)

    try:
        result, _ = se_cli.run_se(["memory", "get", "--project", project_path, "--memory-id", memory_id, "--json"])
    except se_cli.SeError as exc:
        return _error(500, f"memory get failed: {exc}")

    return 200, result


def api_memory_query(m: dict) -> tuple[int, dict[str, Any]]:
    """Query memories with filters: GET /api/memory/query?project=...&type=...&tags=..."""
    project_rel = (m.get("project") or "").strip("/")
    if not project_rel or not _SAFE_RELPATH.match(project_rel):
        return _error(400, "valid --project required (PROJECTS/...)", project=project_rel)

    project_path = os.path.join(_SE_ROOT, project_rel)
    if not os.path.isdir(project_path):
        return _error(404, "project not found", project=project_rel)

    args = ["memory", "query", "--project", project_path, "--json"]
    for key, flag in [
        ("type", "--type"),
        ("tags", "--tags"),
        ("by", "--by"),
        ("since", "--since"),
        ("until", "--until"),
        ("tags_mode", "--tags-mode"),
        ("state", "--state"),
        ("limit", "--limit"),
        ("offset", "--offset"),
    ]:
        val = m.get(key)
        if val:
            args.extend([flag, val])

    try:
        result, _ = se_cli.run_se(args)
    except se_cli.SeError as exc:
        return _error(500, f"memory query failed: {exc}")

    return 200, result


def api_memory_search(m: dict) -> tuple[int, dict[str, Any]]:
    """Lexical search: GET /api/memory/search?project=...&query=..."""
    project_rel = (m.get("project") or "").strip("/")
    query = (m.get("query") or "").strip()

    if not project_rel or not _SAFE_RELPATH.match(project_rel):
        return _error(400, "valid --project required (PROJECTS/...)", project=project_rel)
    if not query:
        return _error(400, "--query required")

    project_path = os.path.join(_SE_ROOT, project_rel)
    if not os.path.isdir(project_path):
        return _error(404, "project not found", project=project_rel)

    args = ["memory", "search", "--project", project_path, "--query", query, "--json"]
    for key, flag in [
        ("type", "--type"),
        ("limit", "--limit"),
        ("offset", "--offset"),
    ]:
        val = m.get(key)
        if val:
            args.extend([flag, val])

    try:
        result, _ = se_cli.run_se(args)
    except se_cli.SeError as exc:
        return _error(500, f"memory search failed: {exc}")

    return 200, result


def api_memory_gc(m: dict) -> tuple[int, dict[str, Any]]:
    """Garbage collect (dry-run by default): GET /api/memory/gc?project=...&older_than_days=...&dry_run=true"""
    project_rel = (m.get("project") or "").strip("/")
    if not project_rel or not _SAFE_RELPATH.match(project_rel):
        return _error(400, "valid --project required (PROJECTS/...)", project=project_rel)

    project_path = os.path.join(_SE_ROOT, project_rel)
    if not os.path.isdir(project_path):
        return _error(404, "project not found", project=project_rel)

    args = ["memory", "gc", "--project", project_path, "--json"]

    # Optional filters
    for key, flag in [
        ("older_than_days", "--older-than-days"),
        ("tags", "--tags"),
        ("state", "--state"),
    ]:
        val = m.get(key)
        if val:
            args.extend([flag, val])

    # Default to dry-run for safety
    dry_run = (m.get("dry_run") or "true").lower() == "true"
    if dry_run:
        args.append("--dry-run")

    try:
        result, _ = se_cli.run_se(args)
    except se_cli.SeError as exc:
        return _error(500, f"memory gc failed: {exc}")

    return 200, result


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


def api_memory_project_get(m: dict) -> tuple[int, dict[str, Any]]:
    """GET /api/memory/project?rel_path=PROJECTS/...

    Return the persistent project memory (focus, next steps, notes, context).
    Returns an empty skeleton when nothing has been saved yet.
    """
    rel = (m.get("rel_path") or "").strip("/")
    if not _SAFE_RELPATH.match(rel) or ".." in rel:
        return _error(400, "invalid project path", rel_path=rel)
    mem = project_memory.load_memory(rel, se_reader.SE_ROOT)
    return 200, mem


def api_memory_project_set(m: dict) -> tuple[int, dict[str, Any]]:
    """POST-equivalent via GET (local console, no SE state touched).

    Query params:
      rel_path  -- PROJECTS/...
      field     -- current_focus | context | next_step | note | done_step | delete_step | delete_note
      value     -- text value (for focus/context/next_step/note)
      step_id   -- step id (for done_step/delete_step)
      note_id   -- note id (for delete_note/update_note)
      done      -- "true"/"false" (for done_step)
    """
    rel = (m.get("rel_path") or "").strip("/")
    if not _SAFE_RELPATH.match(rel) or ".." in rel:
        return _error(400, "invalid project path", rel_path=rel)
    field = (m.get("field") or "").strip()
    value = m.get("value") or ""
    step_id = m.get("step_id") or ""
    note_id = m.get("note_id") or ""
    done_str = (m.get("done") or "").lower()

    try:
        if field == "current_focus":
            result = project_memory.set_focus(rel, se_reader.SE_ROOT, value)
        elif field == "context":
            result = project_memory.set_context(rel, se_reader.SE_ROOT, value)
        elif field == "next_step":
            result = project_memory.upsert_next_step(rel, se_reader.SE_ROOT, value, step_id or None)
        elif field == "done_step":
            result = project_memory.mark_step_done(rel, se_reader.SE_ROOT, step_id, done_str == "true")
            if result is None:
                return _error(404, "step not found", step_id=step_id)
        elif field == "delete_step":
            result = project_memory.delete_step(rel, se_reader.SE_ROOT, step_id)
            if result is None:
                return _error(404, "step not found", step_id=step_id)
        elif field == "add_note":
            result = project_memory.add_note(rel, se_reader.SE_ROOT, value, note_id or None)
        elif field == "update_note":
            result = project_memory.update_note(rel, se_reader.SE_ROOT, note_id, value)
            if result is None:
                return _error(404, "note not found", note_id=note_id)
        elif field == "delete_note":
            result = project_memory.delete_note(rel, se_reader.SE_ROOT, note_id)
            if result is None:
                return _error(404, "note not found", note_id=note_id)
        else:
            return _error(400, "unknown field", field=field)
    except OSError as exc:
        return _error(500, f"memory write failed: {exc}")
    return 200, result


def api_memory_project_auto(m: dict) -> tuple[int, dict[str, Any]]:
    """GET /api/memory/project/auto?rel_path=PROJECTS/...

    Auto-generated memory for a project: what's blocked, what's next,
    what's pending - all derived from canonical SE data. No manual input required.
    """
    rel = (m.get("rel_path") or "").strip("/")
    if not _SAFE_RELPATH.match(rel) or ".." in rel:
        return _error(400, "invalid project path", rel_path=rel)

    memory = {
        "project": rel,
        "generated_at": read_model._now(),
        "current_focus": "Estado no disponible",
        "next_steps": [],
        "notes": [],
        "context": "",
        "auto_generated": True,
    }

    try:
        pj = read_cache.get("projects", read_model.build_project_list) or {}
    except Exception:
        pj = {"projects": []}

    proj = None
    for p in (pj.get("projects") or []):
        if p.get("rel_path") == rel:
            proj = p
            break

    if not proj:
        return _error(404, "project not found", rel_path=rel)

    # Current lifecycle state
    lifecycle = proj.get("lifecycle", {}) if isinstance(proj.get("lifecycle"), dict) else {}
    current_state = (lifecycle.get("value") or "UNKNOWN") if isinstance(lifecycle.get("value"), str) else "UNKNOWN"
    state_descriptions = {
        "DRAFT": "Proyecto registrado, pendiente de iniciar descubrimiento",
        "DISCOVERY": "Identificando contexto, restricciones y desconocidos",
        "PLANNING": "Definiendo requisitos y plan de trabajo",
        "ACTIVE": "Implementando lo planificado",
        "VERIFICATION": "Verificando implementación contra requisitos",
        "ACCEPTANCE": "Esperando aceptación del propietario",
        "RELEASED": "Versión publicada",
        "OPERATING": "Sistema en operación",
        "ARCHIVED": "Proyecto cerrado y preservado",
    }
    memory["current_focus"] = state_descriptions.get(current_state, f"Estado: {current_state}")

    # Next step from next_transition
    nt = lifecycle.get("next_transition", {}) if isinstance(lifecycle.get("next_transition"), dict) else {}
    nt_value = nt.get("value", {}) if isinstance(nt.get("value"), dict) else {}
    nt_to = nt_value.get("to")
    nt_gates = nt_value.get("gates", []) if isinstance(nt_value.get("gates"), list) else []
    if nt_to:
        memory["next_steps"].insert(0, {
            "id": f"next-transition-{nt_to}",
            "text": f"Avanzar a {nt_to}" + (f" resolviendo gates: {', '.join(nt_gates)}" if nt_gates else ""),
            "done": False,
            "type": "next_transition",
        })

    # Gate health from project list
    gate = proj.get("gate", {}) if isinstance(proj.get("gate"), dict) else {}
    gate_value = gate.get("value", {}) if isinstance(gate.get("value"), dict) else {}
    gate_status = gate_value.get("status") if isinstance(gate_value, dict) else None
    gate_id = gate_value.get("id") if isinstance(gate_value, dict) else None
    if gate_status == "FAIL":
        memory["next_steps"].append({
            "id": f"gate-fail-{gate_id or proj.get('project_id', rel)}",
            "text": f"Gate {gate_id} en FAIL: bloquea el avance del proyecto",
            "done": False,
            "type": "gate_fail",
        })
    elif gate_status == "MANUAL":
        memory["next_steps"].append({
            "id": f"gate-manual-{gate_id or proj.get('project_id', rel)}",
            "text": f"Gate {gate_id} en MANUAL: decisión humana requerida",
            "done": False,
            "type": "gate_manual",
        })

    # Context / context deep counts
    context = proj.get("context_status", {}) if isinstance(proj.get("context_status"), dict) else {}
    context_value = context.get("value", {}) if isinstance(context.get("value"), dict) else {}
    deep_scope = context_value.get("deep_scope") or {}
    counts = deep_scope.get("counts") or {}
    if counts:
        total_records = sum(counts.get(k, 0) for k in ("objectives", "requirements", "tasks", "artifacts", "evidence", "decisions", "acceptances"))
        if total_records > 0:
            memory["notes"].append({
                "id": "note-records-count",
                "text": f"Registros del proyecto: {total_records} elementos registrados",
                "type": "info",
            })

    order = {"BLOCKED": 0, "WARNING": 1, "UNKNOWN": 2, "INFO": 3}
    memory["next_steps"].sort(key=lambda s: order.get(s.get("type", "INFO").upper(), 9))

    return 200, memory


ROUTES: dict[str, Callable[[dict], tuple[int, dict]]] = {
    "/api/health": api_health,
    "/api/heartbeat": api_heartbeat,
    "/api/system": api_system,
    "/api/projects": api_projects,
    "/api/project": api_project_detail,
    "/api/attention": api_attention,
    "/api/record": api_record_detail,
    "/api/provenance": api_provenance,
    # P3-B.1: Memory endpoints
    "/api/memory/get": api_memory_get,
    "/api/memory/query": api_memory_query,
    "/api/memory/search": api_memory_search,
    "/api/memory/gc": api_memory_gc,
    # P3-C.1: Project memory (persistent workspace aid, read-only for se)
    "/api/memory/project/get": api_memory_project_get,
    "/api/memory/project/set": api_memory_project_set,
    "/api/memory/project/auto": api_memory_project_auto,
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

    # A write is never followed by a stale cached read: drop every cached read
    # so the next GET re-reads the canonical tree the action just changed.
    read_cache.invalidate()

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
