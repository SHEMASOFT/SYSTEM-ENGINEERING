"""SE-CONSOLE :: read model.

Consolidates `se` envelopes (verdicts) and `se_reader` output (transcription)
into the small set of view models the frontend renders.

EPISTEMIC TAGGING — the central honesty mechanism of this console
-------------------------------------------------------------------
Every fact the UI shows is labelled with where it came from:

  OBSERVED  an `se` CLI verdict or a canonical field read verbatim
  DERIVED   computed by the console from observed facts (schema validity,
            link index, counts, rollups). Deterministic and re-computable.
  UNKNOWN   the console could not determine this; shown as UNKNOWN, never
            defaulted to a healthy-looking value.

The four health states are a PRESENTATION MAPPING of SE's own status values.
The console does not invent a parallel health model: it cannot report a gate
as passing unless `se gate` did.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import audit, se_cli, se_reader

# --------------------------------------------------------------------------
# Status mapping
# --------------------------------------------------------------------------

HEALTHY, WARNING, BLOCKED, UNKNOWN = "HEALTHY", "WARNING", "BLOCKED", "UNKNOWN"

#: Console's own version. Distinct from SYSTEM-ENGINEERING's VERSION, which is
#: read from the canonical file and reported under identity.version.
CONSOLE_VERSION = "0.2.0-002a"

#: SE status -> console health. Anything unmapped becomes UNKNOWN, never HEALTHY.
_STATUS_MAP = {
    "PASS": HEALTHY,
    "OK": HEALTHY,
    "WARN": WARNING,
    "WARNING": WARNING,
    "MANUAL": WARNING,  # human judgement pending: visible, not silently green
    "SKIP": WARNING,
    "FAIL": BLOCKED,
    "ERROR": BLOCKED,
    "CRITICAL": BLOCKED,
    "BLOCKED": BLOCKED,
    "UNKNOWN": UNKNOWN,
    "UNVERIFIED": UNKNOWN,
}


def health_of(se_status: str | None) -> str:
    """Map an SE status string to a console health state (fail closed)."""
    if not se_status:
        return UNKNOWN
    return _STATUS_MAP.get(str(se_status).upper(), UNKNOWN)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fact(value: Any, epistemic: str, source: str, note: str | None = None) -> dict:
    f = {"value": value, "epistemic": epistemic, "source": source}
    if note:
        f["note"] = note
    return f


def _is_degraded(env: dict[str, Any]) -> bool:
    """True when an `se` envelope is the console's own UNKNOWN fallback.

    `se_cli.run_se` models a failure as data: an `se.report/1`-shaped envelope
    with `status: UNKNOWN` and the reason in `warnings`, carrying no `details`.
    Any rollup over such an envelope must stay UNKNOWN.
    """
    return str(env.get("status") or "").upper() == "UNKNOWN"


def _degraded_reason(env: dict[str, Any]) -> str | None:
    warns = env.get("warnings") or []
    return "; ".join(str(w) for w in warns) if warns else None


def _rollup(checks: list[dict], env: dict[str, Any], source: str) -> dict:
    """Roll `se` checks up into a count summary, failing closed.

    POC-001 formatted `by_status` counters unconditionally, so an unreachable
    engine produced the string "0 PASS, 0 WARN, 0 FAIL of 0 checks" — text that
    reads as a flawless result and silently converts UNKNOWN into 0. When the
    envelope is degraded the summary now stays UNKNOWN and names the reason.
    """
    if _is_degraded(env) or not checks:
        reason = _degraded_reason(env) or "se returned no checks"
        return _fact(
            "UNKNOWN — engine did not return checks (" + reason + ")",
            "UNKNOWN",
            source,
        )
    by_status: dict[str, int] = {}
    for c in checks:
        by_status[c.get("status", "UNKNOWN")] = by_status.get(c.get("status", "UNKNOWN"), 0) + 1
    n_warn = by_status.get("WARN", 0) + by_status.get("WARNING", 0)
    return _fact(
        f"{by_status.get('PASS', 0)} PASS, {n_warn} WARN, "
        f"{by_status.get('FAIL', 0)} FAIL of {len(checks)} checks",
        "DERIVED",
        source,
    )


def se_health(rel_path: str, *, timeout: int = 90) -> dict:
    """Relay CMD-0016 `se health --project <rel> --json` as the official health.

    AUTO-01 / CMD-0016 is the engine's own aggregate health envelope. The
    console does NOT re-derive it and does NOT re-rank it: the envelope is
    attached verbatim under `envelope`, and the only thing the console computes
    is the presentation health via the pre-existing `_STATUS_MAP`, which is a
    declared display mapping rather than a judgement.

    `se health` requires `--project`, so this is inherently per-project. The
    system-wide health remains `se doctor`; neither replaces the other.
    """
    env, meta = se_cli.run_se(["health", "--project", rel_path], timeout=timeout)
    degraded = _is_degraded(env)
    return {
        "source": _fact("se health (CMD-0016)", "OBSERVED", "COMMANDS/commands.json"),
        "command_id": _fact("CMD-0016", "OBSERVED", "COMMANDS/commands.json"),
        "available": _fact(not degraded, "OBSERVED", "se health"),
        "status": _fact(env.get("status"), "OBSERVED", "se health"),
        "health": _fact(
            health_of(env.get("status")), "DERIVED", "presentation mapping of se health status"
        ),
        "reason": _fact(_degraded_reason(env), "OBSERVED" if degraded else "DERIVED", "se health"),
        "envelope": _fact(env, "OBSERVED", "se health (verbatim)"),
        "transport": _fact(meta.get("transport"), "OBSERVED", "console transport"),
        "exit_code": _fact(meta.get("exit_code"), "OBSERVED", "console transport"),
    }


def se_consistency(rel_path: str, *, timeout: int = 90) -> dict:
    """Relay AUTO-05 `se health --scope consistency --project <rel> --json`.

    The consistency scope (CON-01..CON-10) checks task-execution integrity,
    artifact/evidence integrity, checksums, execution states, cross-references,
    adapter/manifest conformance, version alignment, and gate ordering.
    """
    env, meta = se_cli.run_se(
        ["health", "--project", rel_path, "--scope", "consistency"],
        timeout=timeout
    )
    degraded = _is_degraded(env)
    return {
        "source": _fact("se health --scope consistency (AUTO-05)", "OBSERVED", "COMMANDS/commands.json"),
        "command_id": _fact("CMD-0016 (scope=consistency)", "OBSERVED", "COMMANDS/commands.json"),
        "available": _fact(not _is_degraded(env), "OBSERVED", "se health --scope consistency"),
        "status": _fact(env.get("status"), "OBSERVED", "se health --scope consistency"),
        "health": _fact(
            health_of(env.get("status")), "DERIVED", "presentation mapping of se consistency status"
        ),
        "reason": _fact(_degraded_reason(env), "OBSERVED" if _is_degraded(env) else "DERIVED", "se health --scope consistency"),
        "envelope": _fact(env, "OBSERVED", "se health --scope consistency (verbatim)"),
        "transport": _fact(meta.get("transport"), "OBSERVED", "console transport"),
        "exit_code": _fact(meta.get("exit_code"), "OBSERVED", "console transport"),
    }


def se_conformance(rel_path: str, *, timeout: int = 90) -> dict:
    """Relay B3/AUTO-07/08 `se health --scope conformance --project <rel> --json`.

    The conformance scope (CONF-01..CONF-06) checks skill frontmatter/schema,
    catalog/FS sync, adapter hashes, adapter counts, skill discovery paths,
    and capability plan coherence.
    """
    env, meta = se_cli.run_se(
        ["health", "--project", rel_path, "--scope", "conformance"],
        timeout=timeout
    )
    degraded = _is_degraded(env)
    return {
        "source": _fact("se health --scope conformance (B3/AUTO-07/08)", "OBSERVED", "COMMANDS/commands.json"),
        "command_id": _fact("CMD-0016 (scope=conformance)", "OBSERVED", "COMMANDS/commands.json"),
        "available": _fact(not _is_degraded(env), "OBSERVED", "se health --scope conformance"),
        "status": _fact(env.get("status"), "OBSERVED", "se health --scope conformance"),
        "health": _fact(
            health_of(env.get("status")), "DERIVED", "presentation mapping of se conformance status"
        ),
        "reason": _fact(_degraded_reason(env), "OBSERVED" if _is_degraded(env) else "DERIVED", "se health --scope conformance"),
        "envelope": _fact(env, "OBSERVED", "se health --scope conformance (verbatim)"),
        "transport": _fact(meta.get("transport"), "OBSERVED", "console transport"),
        "exit_code": _fact(meta.get("exit_code"), "OBSERVED", "console transport"),
    }


def _health_command_declaration(commands: dict) -> dict:
    """Report CMD-0016's *declared* status, separately from engine operability.

    `declared` and `implemented` come from COMMANDS/commands.json. `invocable`
    comes from a live probe. Keeping them apart is the whole point: a command
    can be declared and implemented while the engine is temporarily unable to
    run it, and the console must not collapse that into a single yes/no.
    """
    decl = next(
        (
            c
            for c in (commands.get("commands") or [])
            if str(c.get("id")) == "CMD-0016"
        ),
        None,
    )
    probe = se_cli.probe_se()
    if decl is None:
        available, note = False, "CMD-0016 is not present in COMMANDS/commands.json"
    elif not probe["operational"]:
        available, note = (
            False,
            "CMD-0016 is declared and implemented, but the se engine is not "
            "operational right now (%s)" % (probe["reason"] or "unknown reason"),
        )
    else:
        available, note = True, None
    return {
        "command_id": _fact("CMD-0016", "OBSERVED", "COMMANDS/commands.json"),
        "name": _fact((decl or {}).get("name"), "OBSERVED", "COMMANDS/commands.json"),
        "declared": _fact(decl is not None, "OBSERVED", "COMMANDS/commands.json"),
        "implemented": _fact(
            (decl or {}).get("implemented"), "OBSERVED", "COMMANDS/commands.json"
        ),
        "mutates": _fact((decl or {}).get("mutates"), "OBSERVED", "COMMANDS/commands.json"),
        "execution_intent": _fact(
            (decl or {}).get("execution_intent"), "OBSERVED", "COMMANDS/commands.json"
        ),
        "requires_project": _fact(
            any(a.get("name") == "--project" for a in ((decl or {}).get("arguments") or [])),
            "OBSERVED",
            "COMMANDS/commands.json",
        ),
        "invocable": _fact(available, "DERIVED", "CMD-0016 declaration + se probe"),
        "note": _fact(note, "DERIVED", "console (integration status, not a verdict)"),
    }


# --------------------------------------------------------------------------
# System overview
# --------------------------------------------------------------------------


def build_system_overview() -> dict[str, Any]:
    """What is SYSTEM-ENGINEERING, its version, its health, its components."""
    framework = se_reader.read_framework()
    system = framework.get("system") or {}
    lifecycle = framework.get("lifecycle") or {}
    capabilities = framework.get("capabilities") or {}
    commands = framework.get("commands") or {}

    # The audit is ONE shared pass (console/audit.py), not a fresh `se doctor`
    # per request: `/api/system` was paying the full audit on every page load.
    # A cold snapshot runs a single synchronous pass, so the shape below is the
    # same whether the snapshot is warm or not.
    audit_snap = audit.get_or_run()
    caps_env, caps_meta = audit_snap["capabilities"]
    doc_env, doc_meta = audit_snap["doctor"]

    # -- capabilities (from se, never recomputed) --------------------------
    caps_payload = caps_env.get("capabilities") or {}
    providers = caps_payload.get("mapping") or []
    cap_counts: dict[str, int] = {}
    for p in providers:
        avail = p.get("availability") or "unknown"
        cap_counts[avail] = cap_counts.get(avail, 0) + 1

    # -- doctor checks (from se) -------------------------------------------
    checks = (doc_env.get("details") or {}).get("checks") or []
    by_status: dict[str, int] = {}
    for c in checks:
        by_status[c.get("status", "UNKNOWN")] = by_status.get(c.get("status", "UNKNOWN"), 0) + 1
    failing = [c for c in checks if c.get("status") == "FAIL"]
    warning = [c for c in checks if c.get("status") in ("WARN", "WARNING")]

    # -- declared inventory: se doctor verifies the contract layer itself ---
    contracts_check = next((c for c in checks if c.get("id") == "contracts"), None)
    declared_counts, declared_raw = _parse_contracts_detail(
        (contracts_check or {}).get("detail")
    )

    observed = {
        "agents": len(framework.get("agents") or []),
        "skills": len(framework.get("skills") or []),
        "policies": len(framework.get("policies") or []),
        "commands": len((commands.get("commands") or [])),
        "domains": len(framework.get("domains") or []),
    }
    declared = {k: declared_counts.get(k) for k in ("agents", "skills", "policies", "commands")}
    inventory_alignment = _align(declared, observed)

    return {
        "generated_at": _now(),
        "se_root": se_reader.SE_ROOT,
        "identity": {
            "name": _fact(system.get("name"), "OBSERVED", "SYSTEM.json"),
            "version": _fact(
                framework.get("version_file") or system.get("master_system_version"),
                "OBSERVED",
                "VERSION",
            ),
            "master_system_version": _fact(
                system.get("master_system_version"), "OBSERVED", "SYSTEM.json"
            ),
            "status": _fact(system.get("status"), "OBSERVED", "SYSTEM.json"),
            "description": _fact(system.get("description"), "OBSERVED", "SYSTEM.json"),
            "schema_version": _fact(
                system.get("schema_version"), "OBSERVED", "SYSTEM.json"
            ),
            "models": _fact(
                {
                    k: v
                    for k, v in system.items()
                    if k.endswith("_model") or k.endswith("_index")
                },
                "OBSERVED",
                "SYSTEM.json",
                "canonical model pointers declared by the system",
            ),
        },
        "health": {
            "state": health_of(doc_env.get("status")),
            "se_status": _fact(doc_env.get("status"), "OBSERVED", "se doctor"),
            "summary": _rollup(checks, doc_env, "se doctor"),
            "by_status": (
                _fact("UNKNOWN", "UNKNOWN", "se doctor")
                if (_is_degraded(doc_env) or not checks)
                else _fact(by_status, "DERIVED", "se doctor")
            ),
            "failing_checks": _fact(failing, "OBSERVED", "se doctor"),
            "warning_checks": _fact(warning, "OBSERVED", "se doctor"),
            "epistemic": "OBSERVED",
            "engine": _fact(
                {
                    "operational": se_cli.probe_se()["operational"],
                    "reason": se_cli.probe_se()["reason"],
                },
                "OBSERVED",
                "se probe (se capabilities)",
            ),
        },
        # CMD-0016 `se health` (AUTO-01) is declared in the command contract.
        # Whether it can be *invoked right now* is a separate, honest question:
        # during the SE-AUTOMATION-001C refactor the command was declared and
        # implemented while the engine entrypoint was temporarily unrunnable.
        # Both facts are reported separately so neither implies the other.
        "health_command": _health_command_declaration(commands),
        "capabilities": {
            "health": _fact(caps_env.get("status"), "OBSERVED", "se capabilities"),
            # Same fail-closed rule as the doctor rollup: with the engine down
            # `caps_payload` is empty, and reporting "0 available" would read as
            # "this system has no capabilities" rather than "not determinable".
            "available_count": (
                _fact("UNKNOWN", "UNKNOWN", "se capabilities")
                if _is_degraded(caps_env)
                else _fact(
                    len(caps_payload.get("available") or []), "OBSERVED", "se capabilities"
                )
            ),
            "by_availability": (
                _fact("UNKNOWN", "UNKNOWN", "se capabilities")
                if _is_degraded(caps_env)
                else _fact(cap_counts, "DERIVED", "se capabilities")
            ),
            "providers": _fact(providers, "OBSERVED", "se capabilities"),
            "note": _fact(
                "capability is a provider-property, not a project field; the console "
                "deliberately does not attach it to project lifecycle",
                "DERIVED",
                "core-capabilities",
            ),
        },
        "lifecycle_framework": {
            "states": _fact(
                lifecycle.get("states") or lifecycle.get("lifecycle"), "OBSERVED", "CORE/lifecycle"
            ),
            "gates": _fact(
                [
                    {
                        "id": g.get("id"),
                        "name": g.get("name"),
                        "from_state": g.get("from_state"),
                        "to_state": g.get("to_state"),
                    }
                    for g in ((framework.get("gates") or {}).get("gates") or [])
                ],
                "OBSERVED",
                "CORE/gates/gates.json",
            ),
        },
        "inventory": {
            "declared_by_se": _fact(
                declared_counts, "OBSERVED", "se doctor (contracts check)"
            ),
            "declared_statement": _fact(
                declared_raw, "OBSERVED", "se doctor (contracts check)"
            ),
            "observed_by_console": _fact(observed, "OBSERVED", "AGENTS/SKILLS/POLICIES/COMMANDS/DOMAINS"),
            "alignment": inventory_alignment,
            "note": _fact(
                "declared counts come from `se doctor`, which verifies the contract layer. "
                "observed counts are what this console actually read. A mismatch means the "
                "console and the engine disagree about what exists.",
                "DERIVED",
                "console",
            ),
        },
        "command_surface": {
            "count": _fact(len((commands.get("commands") or [])), "OBSERVED", "commands.json"),
            "available": _fact(
                [c.get("id") for c in (commands.get("commands") or [])],
                "OBSERVED",
                "COMMANDS/commands.json",
            ),
        },
        "agents": _fact(framework.get("agents") or [], "OBSERVED", "AGENTS/*/agent.json"),
        "skills": _fact(framework.get("skills") or [], "OBSERVED", "SKILLS/*/SKILL.md"),
        "policies": _fact(framework.get("policies") or [], "OBSERVED", "POLICIES/*.md"),
        "domains": _fact(framework.get("domains") or [], "OBSERVED", "DOMAINS/"),
        "transport": {
            "doctor": doc_meta,
            "capabilities": caps_meta,
            # Freshness of the shared audit pass. The numbers above are as old
            # as this; the UI can show it rather than imply a live audit.
            "audit": {
                "single_pass": True,
                "age_seconds": round(audit_snap.get("age_seconds", 0.0), 1),
            },
        },
        "source_errors": _fact(framework.get("errors") or [], "DERIVED", "read_framework"),
    }


def _parse_contracts_detail(detail: str | None) -> tuple[dict[str, int], str | None]:
    """Read the contract-layer counts out of se doctor's own statement.

    `se doctor` reports e.g. "12 agents, 15 commands, 6 skills, 8 policies
    verified". This is transcription of an SE verdict, not an independent count,
    so it is tagged OBSERVED and surfaced verbatim alongside the parse.
    """
    if not detail:
        return {}, None
    counts: dict[str, int] = {}
    for kind, num in re.findall(r"(\d+)\s+(agents|commands|skills|policies)", detail):
        counts[num] = int(kind)
    for kind, num in re.findall(r"(agents|commands|skills|policies)\D{0,3}(\d+)", detail):
        counts.setdefault(kind, int(num))
    return counts, detail


def _align(declared: dict, observed: dict) -> dict:
    """Compare SE-declared contract counts against what the console read."""
    rows = []
    for key, obs in observed.items():
        dec = declared.get(key)
        if dec is None:
            rows.append(
                {"item": key, "declared": None, "observed": obs, "state": UNKNOWN,
                 "note": "se doctor did not declare this count; alignment unknown"}
            )
        else:
            rows.append(
                {"item": key, "declared": dec, "observed": obs,
                 "state": HEALTHY if dec == obs else WARNING,
                 "note": None if dec == obs else "se-declared vs console-observed mismatch"}
            )
    states = {r["state"] for r in rows}
    overall = BLOCKED if BLOCKED in states else (WARNING if WARNING in states else HEALTHY)
    return _fact(rows, "DERIVED", "se doctor vs console read", overall)


# --------------------------------------------------------------------------
# Project list
# --------------------------------------------------------------------------


def build_project_list() -> dict[str, Any]:
    projects = se_reader.discover_projects()

    for p in projects:
        if p["management"] != "MANAGED":
            p["lifecycle"] = _fact(None, "UNKNOWN", "no PROJECT.json", p.get("reason"))
            p["health"] = UNKNOWN
            continue
        # Context (AUTO-02)
        env, meta = se_cli.run_se(["context", "--project", p["rel_path"], "--json"])
        p["health"] = health_of(env.get("status"))
        p["context_status"] = _fact(env.get("status"), "OBSERVED", "se context")
        p["lifecycle"] = _fact(
            (env.get("lifecycle") or {}).get("state"), "OBSERVED", "se context"
        )
        p["next_transition"] = _fact(
            (env.get("lifecycle") or {}).get("next_transition"), "OBSERVED", "se context"
        )
        p["gate"] = _fact(
            {
                "id": (env.get("gate") or {}).get("id"),
                "status": (env.get("gate") or {}).get("status"),
            },
            "OBSERVED",
            "se context",
        )
        p["warnings"] = _fact(env.get("warnings") or [], "OBSERVED", "se context")

        # Consistency (AUTO-05)
        cons = se_consistency(p["rel_path"])
        p["consistency"] = cons["health"]
        p["consistency_envelope"] = _fact(cons.get("envelope"), "OBSERVED", "se health --scope consistency")
        p["consistency_status"] = _fact(cons.get("status"), "OBSERVED", "se health --scope consistency")

        # Conformance (B3/AUTO-07/08)
        conf = se_conformance(p["rel_path"])
        p["conformance"] = conf["health"]
        p["conformance_envelope"] = _fact(conf.get("envelope"), "OBSERVED", "se health --scope conformance")
        p["conformance_status"] = _fact(conf.get("status"), "OBSERVED", "se health --scope conformance")

    return {
        "generated_at": _now(),
        "total": len(projects),
        "managed": sum(1 for p in projects if p["management"] == "MANAGED"),
        "unmanaged": sum(1 for p in projects if p["management"] != "MANAGED"),
        "projects": projects,
    }


# --------------------------------------------------------------------------
# Project detail
# --------------------------------------------------------------------------


def build_project_detail(rel_path: str) -> dict[str, Any]:
    path = os.path.join(se_reader.SE_ROOT, rel_path.replace("/", os.sep))
    if not os.path.isdir(path) or not os.path.abspath(path).startswith(
        os.path.abspath(se_reader.SE_ROOT)
    ):
        return {"error": "unknown project", "rel_path": rel_path, "status": "UNKNOWN"}

    # --- gate matrix: every gate verdict comes from `se gate` -------------
    # The 9 gate evaluations are independent subprocess calls, so they run
    # concurrently. This is a latency optimisation only: results, ordering and
    # verdicts are identical to sequential execution. No caching is involved.
    definition = (se_reader.read_framework().get("gates") or {}).get("gates") or []
    gate_ids = [g["id"] for g in definition if g.get("id")]
    name_by_id = {g["id"]: g for g in definition if g.get("id")}

    def _gate(gid: str) -> tuple[dict[str, Any], dict[str, Any]]:
        env, _meta = se_cli.run_se(["gate", "--project", rel_path, "--gate", gid, "--json"])
        return env.get("gate") or {}, env

    with ThreadPoolExecutor(max_workers=min(9, (os.cpu_count() or 4))) as pool:
        gate_pairs = list(pool.map(_gate, gate_ids))

    gates: list[dict] = []
    envelope_conflicts: list[dict] = []
    envelope_statuses: set[str] = set()
    for gid, (g, env) in zip(gate_ids, gate_pairs):
        gdef = name_by_id.get(gid, {})
        env_status = env.get("status")
        envelope_statuses.add(str(env_status))
        for c in env.get("conflicts") or []:
            envelope_conflicts.append({"gate": gid, "conflict": c})
        gates.append(
            {
                "id": g.get("id") or gid,
                "name": g.get("name") or gdef.get("name"),
                "from_state": g.get("from_state") or gdef.get("from_state"),
                "to_state": g.get("to_state") or gdef.get("to_state"),
                "status": _fact(g.get("status"), "OBSERVED", f"se gate {gid}"),
                "health": health_of(g.get("status")),
                # When `se` could not evaluate the gate at all, the reason is in
                # the envelope, not in gate.status. Surface it, so an unevaluable
                # gate is not silently rendered as merely UNKNOWN.
                "envelope_status": _fact(env_status, "OBSERVED", f"se gate {gid}"),
                "envelope_health": health_of(env_status),
                "envelope_conflicts": _fact(
                    env.get("conflicts") or [], "OBSERVED", f"se gate {gid}"
                ),
                "conditions": _fact(g.get("conditions") or [], "OBSERVED", f"se gate {gid}"),
                "manual": [c for c in (g.get("conditions") or []) if c.get("status") == "MANUAL"],
                "failing": [c for c in (g.get("conditions") or []) if c.get("status") == "FAIL"],
            }
        )

    # --- context (AUTO-02) at identity scope: project + lifecycle + gate --
    ctx_env, ctx_meta = se_cli.run_se(["context", "--project", rel_path, "--json"])
    deep_env, deep_meta = se_cli.run_se(
        ["context", "--project", rel_path, "--scope", "deep", "--json"]
    )

    # Management status, recomputed the same way the project list does it, so a
    # detail page can state WHY a value is UNKNOWN instead of just showing it.
    managed = next(
        (
            p
            for p in se_reader.discover_projects()
            if p["rel_path"].replace("\\", "/") == rel_path.replace("\\", "/")
        ),
        None,
    )
    management = (managed or {}).get("management", "UNKNOWN")
    management_reason = (managed or {}).get("reason")

    # --- review: findings/gaps/links come from `se review` ----------------
    rev_env, rev_meta = se_cli.run_se(["review", "--project", rel_path, "--json"])
    review = rev_env.get("details") or {}

    # --- CMD-0016 `se health`: the engine's own aggregate health, relayed ---
    # Only for managed projects: the engine requires a PROJECT.json and
    # refuses otherwise, and we must not fabricate a health for an unmanaged
    # directory. For those the block is explicitly UNKNOWN with the reason.
    if management == "MANAGED":
        health_block = se_health(rel_path)
    else:
        health_block = {
            "source": _fact("se health (CMD-0016)", "OBSERVED", "COMMANDS/commands.json"),
            "command_id": _fact("CMD-0016", "OBSERVED", "COMMANDS/commands.json"),
            "available": _fact(False, "OBSERVED", "se health"),
            "status": _fact("UNKNOWN", "OBSERVED", "se health"),
            "health": _fact(UNKNOWN, "DERIVED", "presentation mapping of se health status"),
            "reason": _fact(
                "project is %s; `se health` requires a managed project with PROJECT.json"
                % management,
                "DERIVED",
                "console (classification only, not a health verdict)",
            ),
            "envelope": _fact(None, "UNKNOWN", "not invoked"),
            "transport": _fact(None, "OBSERVED", "console transport"),
            "exit_code": _fact(None, "OBSERVED", "console transport"),
        }

    # --- transcription: records ------------------------------------------
    records: dict[str, Any] = {}
    for rtype in se_reader.RECORD_LAYOUT:
        records[rtype] = se_reader.load_records(path, rtype)

    index = se_reader.build_link_index(path)
    discovery = se_reader.load_discovery(path)
    mutations = se_reader.load_mutation_log(path)
    transitions = se_reader.load_transitions(path)
    docs = se_reader.load_project_docs(path)
    manifest_path = os.path.join(path, "PROJECT.json")
    manifest, _ = se_reader.read_json(manifest_path)

    manifest_v = se_reader.validate_record(
        manifest, "SCHEMAS/project/project.schema.json", "PROJECT"
    ) if manifest else {"ok": False, "errors": ["unreadable"], "label": "PROJECT"}

    dsummary = discovery.get("data") or {}
    # discovery.json is a DISCOVERY *record* (summary/findings/unknowns/
    # assumptions/constraints/risks). It carries no gate status, and the console
    # does not invent one: anything absent is shown as UNKNOWN, not inferred.
    dschema = discovery.get("schema") or {}

    # --- traceability chain, built from review's own counts ---------------
    counts = review.get("counts") or {}
    chain = [
        {
            "type": t,
            "count": _fact(counts.get(t, 0), "OBSERVED", "se review"),
            "present": counts.get(t, 0) > 0,
        }
        for t in ("OBJECTIVE", "REQUIREMENT", "TASK", "ARTIFACT", "EVIDENCE", "ACCEPTANCE", "RELEASE")
    ]

    # --- attention queue -------------------------------------------------
    attention = build_attention(
        gates=gates,
        review=review,
        records=records,
        discovery=discovery,
        deep_env=deep_env,
        manifest_v=manifest_v,
        manifest_sha=(managed or {}).get("manifest_sha256"),
    )

    return {
        "generated_at": _now(),
        "rel_path": rel_path,
        "path": path,
        "management": _fact(management, "DERIVED", "PROJECT.json presence + schema"),
        "management_reason": _fact(
            management_reason, "DERIVED", "PROJECT.json presence + schema"
        ),
        "engine_conflicts": _fact(
            sorted(
                {
                    str(c)
                    for c in (ctx_env.get("conflicts") or [])
                    + list(deep_env.get("conflicts") or [])
                    + [c["conflict"] for c in envelope_conflicts]
                }
            ),
            "OBSERVED",
            "se gate / se context conflicts",
        ),
        "identity": _fact((ctx_env.get("project") or {}), "OBSERVED", "se context"),
        "manifest": {
            "data": _fact(manifest, "OBSERVED", "PROJECT.json"),
            "schema_valid": _fact(manifest_v["ok"], "DERIVED", "project.schema.json"),
            "schema_errors": _fact(manifest_v["errors"], "DERIVED", "project.schema.json"),
            "sha256": _fact(se_reader.sha256_of(manifest_path), "DERIVED", "sha256"),
        },
        "lifecycle": {
            "state": _fact(
                (ctx_env.get("lifecycle") or {}).get("state"), "OBSERVED", "se context"
            ),
            "health": health_of((ctx_env.get("lifecycle") or {}).get("state")),
            "next_transition": _fact(
                (ctx_env.get("lifecycle") or {}).get("next_transition"),
                "OBSERVED",
                "se context",
            ),
            "declared_transitions": _fact(
                transitions.get("transitions") or [], "OBSERVED", "PROJECT.json metadata"
            ),
            "migrations": _fact(
                transitions.get("migrations") or [], "OBSERVED", "PROJECT.json metadata"
            ),
        },
        # CMD-0016: the engine's own aggregate health envelope for this project.
        # Relayed verbatim; the console adds no ranking of its own.
        "se_health": health_block,
        "gates": {
            "matrix": _fact(gates, "OBSERVED", "se gate G0..G8"),
            "current": _fact((ctx_env.get("gate") or {}), "OBSERVED", "se context"),
            "passing": [g["id"] for g in gates if g["health"] == HEALTHY],
            "manual": [g["id"] for g in gates if g["health"] == WARNING],
            "failing": [g["id"] for g in gates if g["health"] == BLOCKED],
        },
        "discovery": {
            "present": _fact(discovery.get("present"), "OBSERVED", "discovery.json"),
            "schema_valid": _fact(
                discovery.get("schema_valid"), "DERIVED", "discovery.schema.json"
            ),
            "schema_errors": _fact(
                discovery.get("schema_errors") or [], "DERIVED", "discovery.schema.json"
            ),
            "summary": _fact(dschema.get("summary"), "OBSERVED", "discovery.json"),
            "findings": _fact(dschema.get("findings") or [], "OBSERVED", "discovery.json"),
            "unknowns": _fact(dschema.get("unknowns") or [], "OBSERVED", "discovery.json"),
            "assumptions": _fact(dschema.get("assumptions") or [], "OBSERVED", "discovery.json"),
            "constraints": _fact(dschema.get("constraints") or [], "OBSERVED", "discovery.json"),
            "risks": _fact(dschema.get("risks") or [], "OBSERVED", "discovery.json"),
            "reviewed_by": _fact(dschema.get("reviewed_by"), "OBSERVED", "discovery.json"),
            "reviewed_at": _fact(dschema.get("reviewed_at"), "OBSERVED", "discovery.json"),
            "status": _fact(
                None, "UNKNOWN", "discovery.json", "DISCOVERY carries no status field"
            ),
            "counts": _fact(
                {
                    k: len(dschema.get(k) or [])
                    for k in ("findings", "unknowns", "assumptions", "constraints", "risks")
                },
                "DERIVED",
                "discovery.json",
            ),
        },
        "records": _fact(
            {t: _record_summary(v) for t, v in records.items()},
            "OBSERVED",
            "PROJECTS/*/records",
        ),
        "records_detail": records,
        "traceability": {
            "chain": _fact(chain, "DERIVED", "se review counts"),
            "review_counts": _fact(counts, "OBSERVED", "se review"),
        },
        "integrity": {
            "review_status": _fact(rev_env.get("status"), "OBSERVED", "se review"),
            "findings": _fact(review.get("findings") or [], "OBSERVED", "se review"),
            "gaps": _fact(review.get("gaps") or [], "OBSERVED", "se review"),
            "link_notes": _fact(review.get("link_notes") or [], "OBSERVED", "se review"),
        },
        "link_index": {
            "counts": _fact(index["counts"], "DERIVED", "reverse link scan"),
            "inbound": _fact(index["inbound"], "DERIVED", "reverse link scan"),
            "note": _fact(
                "index records DECLARED links only; `se review` link_notes remain the "
                "authority on link integrity",
                "DERIVED",
                "console",
            ),
        },
        "mutation_log": {
            "present": _fact(mutations.get("present"), "OBSERVED", "mutation-log.jsonl"),
            "entries": _fact(mutations.get("entries") or [], "OBSERVED", "mutation-log.jsonl"),
            "malformed_lines": _fact(mutations.get("malformed", 0), "DERIVED", "jsonl parse"),
            "normalization_note": _fact(
                "comma-joined id strings are split for interpretation; raw values retained",
                "DERIVED",
                "console",
            ),
        },
        "documents": _fact(docs, "OBSERVED", "PROJECTS/*/docs"),
        "context": {
            "identity_scope": _fact(
                {
                    "status": ctx_env.get("status"),
                    "scope": ctx_env.get("scope"),
                    "epistemic": ctx_env.get("epistemic"),
                    "next_action": ctx_env.get("next_action"),
                    "warnings": ctx_env.get("warnings") or [],
                },
                "OBSERVED",
                "se context",
            ),
            "deep_scope": _fact(
                {
                    "status": deep_env.get("status"),
                    "scope": deep_env.get("scope"),
                    "warnings": deep_env.get("warnings") or [],
                    "counts": {
                        k: len(deep_env.get(k) or [])
                        for k in (
                            "objectives",
                            "requirements",
                            "tasks",
                            "artifacts",
                            "evidence",
                            "decisions",
                            "acceptances",
                        )
                    },
                },
                "OBSERVED",
                "se context --scope deep",
            ),
            "note": _fact(
                "AUTO-02 is focus-driven: without --focus, scope>=work legitimately "
                "returns an empty work set. That is a SE behaviour, not a data gap.",
                "DERIVED",
                "MINIMUM_CONTEXT_POLICY",
            ),
        },
        "attention": attention,
        "transport": {"gates": ctx_meta, "context": ctx_meta, "deep": deep_meta, "review": rev_meta},
    }


def _record_summary(loaded: dict) -> dict:
    return {
        "count": len(loaded.get("records") or []),
        "schema": loaded.get("schema"),
        "dir": loaded.get("dir"),
        "invalid_count": len(loaded.get("invalid") or []),
        "absent": loaded.get("absent", False),
        "error": loaded.get("error"),
        # IDs are already in memory (load_records returned them), so listing
        # them costs no extra file access. This is what lets the UI drill into
        # GET /api/record without adding a listing endpoint or a second read
        # path. Ids are transcribed, never interpreted.
        "ids": [r["id"] for r in (loaded.get("records") or [])],
    }


# --------------------------------------------------------------------------
# Attention queue
# --------------------------------------------------------------------------


def build_attention(
    *,
    gates: list[dict],
    review: dict,
    records: dict,
    discovery: dict,
    deep_env: dict,
    manifest_v: dict,
    manifest_sha: str | None = None,
) -> dict[str, Any]:
    """One prioritized queue. Priority is UI ordering, not a governance verdict."""
    items: list[dict] = []

    # A3 (DESIGN-5B §2.2): the enabled action ids for a RUN intervention.
    # Everything else is diagnosis, not actionable, and gets an empty list --
    # "no intervention point without a mapped action; no action without the
    # intervention point that originates it". Every item carries the key, so
    # callers never have to special-case a missing field.
    RUN_ACTIONS = ("run.checkpoint", "run.close")
    HANDOFF_ACTIONS = ("run.checkpoint",)
    MANUAL_ACTIONS = ("transition.attest",)

    def add(
        sev: str,
        area: str,
        title: str,
        detail: str,
        evidence: str,
        enabled_actions: tuple[str, ...] = (),
        expected_revision: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        item = {
            "severity": sev,
            "area": area,
            "title": title,
            "detail": detail,
            "evidence": evidence,
            "actions": list(enabled_actions),
        }
        if expected_revision is not None:
            item["expected_revision"] = expected_revision
        if params is not None:
            # The arguments the surface must send. They are derived from the
            # engine's own read model, so the UI never invents a target state or
            # a condition id -- it transcribes what the engine reported.
            item["action_params"] = params
        items.append(item)

    # BLOCKED: gates that actually fail
    for g in gates:
        for cond in g["failing"]:
            add(
                "BLOCKED",
                "gate",
                f"{g['id']} {g['name']}: {cond['id']} FAIL",
                f"se gate reports {cond['id']} as FAIL for {g['id']}.",
                f"se gate --gate {g['id']}",
            )

    # BLOCKED: schema-invalid canonical records
    for rtype, loaded in records.items():
        for bad in loaded.get("invalid") or []:
            add(
                "BLOCKED",
                "integrity",
                f"Schema-invalid {rtype}: {bad.get('id') or bad.get('file')}",
                "; ".join((bad.get("errors") or [])[:2]),
                f"SCHEMAS/{rtype}",
            )

    # Human intervention: RUNs that cannot progress without a person.
    # A RUN carries its own checkpoint, so "what is blocked" and "what is next"
    # are transcribed from the artifact rather than inferred here.
    for entry in (records.get("RUN") or {}).get("records") or []:
        run = entry.get("data") or {}
        rid = entry.get("id")
        state = str(run.get("state") or "UNKNOWN").upper()
        checkpoint = run.get("checkpoint") or {}
        recovery = run.get("recovery") or {}
        blocked_items = checkpoint.get("blocked") or []
        if state == "BLOCKED" or blocked_items:
            add(
                "BLOCKED",
                "run",
                f"RUN {rid} blocked",
                checkpoint.get("next_step")
                or "; ".join(blocked_items[:3])
                or "RUN is blocked; a human decision is required to continue.",
                f"runs/{rid}.json",
                RUN_ACTIONS,
                expected_revision=entry.get("sha256"),
            )
        elif state == "FAILED":
            add(
                "WARNING",
                "run",
                f"RUN {rid} failed",
                recovery.get("notes") or "Decide retry or abandon.",
                f"runs/{rid}.json",
                RUN_ACTIONS,
                expected_revision=entry.get("sha256"),
            )
        if recovery.get("handoff"):
            add(
                "WARNING",
                "run",
                f"RUN {rid} handoff pending",
                str(recovery.get("handoff")),
                f"runs/{rid}.json",
                HANDOFF_ACTIONS,
                expected_revision=entry.get("sha256"),
            )

    # WARNING: gates awaiting human judgement
    for g in gates:
        manual_conditions = [
            {
                "id": c.get("id"),
                "description": c.get("description"),
                "status": c.get("status"),
                "detail": c.get("detail"),
            }
            for c in (g.get("manual") or [])
        ]
        for cond in g["manual"]:
            add(
                "WARNING",
                "gate",
                f"{g['id']} {g['name']}: {cond['id']} MANUAL",
                "Condition requires an explicit human decision; not auto-derivable.",
                f"se gate --gate {g['id']}",
                MANUAL_ACTIONS,
                expected_revision=manifest_sha,
                params={
                    "to": g.get("to_state"),
                    "conditions": [c["id"] for c in manual_conditions if c.get("id")],
                    "context": manual_conditions,
                },
            )

    # WARNING: governance gaps from se review
    for gap in review.get("gaps") or []:
        add("WARNING", "integrity", "Review gap", gap, "se review")
    for note in review.get("link_notes") or []:
        add("WARNING", "integrity", "Asymmetric link", note, "se review")
    for f in review.get("findings") or []:
        sev = (f.get("severity") or "INFO").upper()
        add(
            "BLOCKED" if sev in ("ERROR", "CRITICAL") else "WARNING",
            "review",
            f"Review finding [{sev}]",
            f.get("message") or json_text(f),
            "se review",
        )

    # WARNING: discovery not done / unverified
    if not discovery.get("present"):
        add("WARNING", "discovery", "discovery.json absent",
            "No discovery artifact; gates derived from it cannot be evidenced.",
            "PROJECTS/*/discovery.json")
    elif discovery.get("schema_valid") is False:
        add("WARNING", "discovery", "discovery.json fails schema",
            "; ".join((discovery.get("schema_errors") or [])[:2]),
            "SCHEMAS/discovery/discovery.schema.json")

    # WARNING: PROJECT.json schema problem
    if not manifest_v["ok"]:
        add("WARNING", "integrity", "PROJECT.json schema problem",
            "; ".join(manifest_v["errors"][:2]), "project.schema.json")

    # WARNING: AUTO-02 deep scope empty (explains empty work set honestly)
    for w in deep_env.get("warnings") or []:
        add("WARNING", "context", "AUTO-02 context warning", w, "se context --scope deep")

    order = {"BLOCKED": 0, "WARNING": 1, "UNKNOWN": 2, "INFO": 3}
    items.sort(key=lambda i: order.get(i["severity"], 9))

    return {
        "counts": {
            "BLOCKED": sum(1 for i in items if i["severity"] == "BLOCKED"),
            "WARNING": sum(1 for i in items if i["severity"] == "WARNING"),
            "total": len(items),
        },
        "items": items,
        "note": "Priority orders attention; it is not a governance verdict.",
    }


def json_text(obj: Any) -> str:
    import json as _j

    return _j.dumps(obj, ensure_ascii=False)[:300]


# --------------------------------------------------------------------------
# Record detail (per-entity drill-down via AUTO-02 focus)
# --------------------------------------------------------------------------


def build_record_detail(rel_path: str, rtype: str, rid: str) -> dict[str, Any]:
    path = os.path.join(se_reader.SE_ROOT, rel_path.replace("/", os.sep))
    loaded = se_reader.load_records(path, rtype)
    record = next((r for r in loaded["records"] if r["id"] == rid), None)
    if record is None:
        return {"error": "record not found", "type": rtype, "id": rid, "status": "UNKNOWN"}

    index = se_reader.build_link_index(path)
    # AUTO-02 focus: the engine reconstructs the trace for this entity.
    ctx, meta = se_cli.run_se(
        ["context", "--project", rel_path, "--scope", "trace", "--focus", rid, "--json"]
    )
    return {
        "generated_at": _now(),
        "type": rtype,
        "id": rid,
        "record": _fact(record, "OBSERVED", record["rel_path"]),
        "inbound_links": _fact(
            index["inbound"].get(rid, []), "DERIVED", "reverse link scan"
        ),
        "context": _fact(
            {
                "status": ctx.get("status"),
                "scope": ctx.get("scope"),
                "epistemic": ctx.get("epistemic"),
                "next_action": ctx.get("next_action"),
                "counts": {
                    k: len(ctx.get(k) or [])
                    for k in (
                        "objectives",
                        "requirements",
                        "tasks",
                        "artifacts",
                        "evidence",
                        "decisions",
                        "acceptances",
                    )
                },
                "warnings": ctx.get("warnings") or [],
            },
            "OBSERVED",
            "se context --scope trace --focus",
        ),
        "transport": meta,
    }


# --------------------------------------------------------------------------
# Provenance endpoint
# --------------------------------------------------------------------------


def build_provenance() -> dict[str, Any]:
    watch = [
        "SYSTEM.json",
        "VERSION",
        "MASTER SYSTEM/MANIFEST.json",
        "CORE/lifecycle/lifecycle.json",
        "CORE/gates/gates.json",
        "CORE/capabilities/capabilities.json",
        "COMMANDS/commands.json",
        "SCHEMAS/index.json",
        "PROJECTS/SHEMASEG/PROJECT.json",
        "PROJECTS/SHEMASEG/discovery.json",
    ]
    fp = se_reader.source_fingerprint(watch)
    return {
        "generated_at": _now(),
        "se_root": se_reader.SE_ROOT,
        "fingerprint": fp["fingerprint"],
        "files": _fact(fp["files"], "DERIVED", "sha256"),
        "note": _fact(
            "SE-CONSOLE opens SYSTEM-ENGINEERING read-only. The fingerprint changes only "
            "when an external actor changes canonical files.",
            "DERIVED",
            "console",
        ),
    }
