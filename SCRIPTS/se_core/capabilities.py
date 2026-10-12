"""Capability governance: registry, policy validation and capability resolution.

CP-020. This module is the single engine for capability governance:

* loads the canonical registry (CORE/capabilities/capabilities.json) which
  declares providers (tools/MCP servers) and the capabilities they enable;
* validates capability policies declared in skills, agents, tasks and project
  profiles against the registry;
* resolves a deterministic capability plan for a given context
  (project / agent / skill / task), applying the resolution order
  SYSTEM -> Project -> Agent -> Skill -> Task (more specific prevails) and
  reporting conflicts (required-but-denied, required-but-unavailable).

Nothing here is provider-specific by name: the registry owns the mapping
from logical capabilities (e.g. ``documentation.lookup``) to concrete
providers (e.g. ``context7``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9-]*([.][a-z][a-z0-9-]*)*$")
PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")

OPERATION_WRITE = "write"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def registry_path(root=None) -> Path:
    base = Path(root) if root else repo_root()
    return base / "CORE" / "capabilities" / "capabilities.json"


def load_registry(root=None) -> dict:
    path = registry_path(root)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def capability_meta(root=None) -> dict:
    """Map capability id -> {operation, provider, availability, description}."""
    registry = load_registry(root)
    providers = {
        p.get("id"): p.get("availability", "available")
        for p in registry.get("providers", [])
    }
    meta = {}
    for cap in registry.get("capabilities", []):
        provider = cap.get("provider")
        provider_available = providers.get(provider, "available") == "available"
        cap_available = cap.get("availability", "available") == "available"
        meta[cap["id"]] = {
            "operation": cap.get("operation", "read"),
            "provider": provider,
            "availability": "available" if (provider_available and cap_available) else "unavailable",
            "description": cap.get("description", ""),
        }
    return meta


def known_capabilities(root=None) -> set:
    return set(capability_meta(root))


def known_providers(root=None) -> dict:
    registry = load_registry(root)
    return {p.get("id"): p.get("availability", "available") for p in registry.get("providers", [])}


def operation_map(root=None) -> dict:
    return {cid: meta["operation"] for cid, meta in capability_meta(root).items()}


def available_capabilities(root=None) -> set:
    return {cid for cid, meta in capability_meta(root).items() if meta["availability"] == "available"}


def provider_capabilities(root=None) -> dict:
    """Map provider id -> sorted list of capability ids it enables."""
    meta = capability_meta(root)
    mapping = {}
    for cap in load_registry(root).get("capabilities", []):
        mapping.setdefault(cap.get("provider"), []).append(cap["id"])
    for provider in mapping:
        mapping[provider] = sorted(mapping[provider])
    return dict(sorted(mapping.items()))


def capability_plan_view(root=None) -> dict:
    """Adapter-facing view of the registry (providers + available capabilities)."""
    meta = capability_meta(root)
    available = sorted(c for c, m in meta.items() if m["availability"] == "available")
    mapping = []
    for provider, caps in provider_capabilities(root).items():
        mapping.append(
            {
                "provider": provider,
                "capabilities": caps,
                "availability": known_providers(root).get(provider, "unknown"),
            }
        )
    return {
        "registry": "CORE/capabilities/capabilities.json",
        "available": available,
        "mapping": mapping,
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def validate_registry(root=None, schemas=None) -> list:
    """Return a list of error strings for the canonical registry."""
    errors = []
    path = registry_path(root)
    if not path.exists():
        return [f"{path}: missing canonical capability registry"]
    registry = load_registry(root)
    metadata = capability_meta(root)
    known = set(metadata)
    providers = known_providers(root)
    if schemas is not None and "capability" in schemas:
        schema = schemas["capability"]
        try:
            import jsonschema

            validator = jsonschema.Draft202012Validator(schema)
            for error in sorted(validator.iter_errors(registry), key=lambda e: list(e.path)):
                errors.append(f"{path}: {error.message}")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{path}: registry schema validation failed: {exc}")
    seen_ids = []
    for cap in registry.get("capabilities", []):
        cid = cap.get("id")
        if cid in seen_ids:
            errors.append(f"{path}: duplicate capability id '{cid}'")
        seen_ids.append(cid)
        if not CAPABILITY_ID_RE.match(cid or ""):
            errors.append(f"{path}: invalid capability id '{cid}'")
        provider = cap.get("provider")
        if provider not in providers:
            errors.append(f"{path}: capability '{cid}' references unknown provider '{provider}'")
    seen_providers = []
    for prov in registry.get("providers", []):
        pid = prov.get("id")
        if pid in seen_providers:
            errors.append(f"{path}: duplicate provider id '{pid}'")
        seen_providers.append(pid)
        if not PROVIDER_ID_RE.match(pid or ""):
            errors.append(f"{path}: invalid provider id '{pid}'")
    return errors


def validate_skill_policy(data: dict, known: set, ops: dict) -> list:
    """Validate a skill sidecar capability policy.

    * ``capabilities.required`` / ``capabilities.optional`` must be known.
    * ``constraints.write`` must be one of allowed|forbidden (schema covers it,
      this is a belt-and-braces check).
    """
    errors = []
    caps = (data or {}).get("capabilities") or {}
    for kind in ("required", "optional"):
        for cid in caps.get(kind) or []:
            if not CAPABILITY_ID_RE.match(cid):
                errors.append(f"skill '{data.get('skill_id', '?')}': invalid capability id '{cid}'")
            elif cid not in known:
                errors.append(
                    f"skill '{data.get('skill_id', '?')}' ({kind}): unknown capability '{cid}'"
                )
    constraints = (data or {}).get("constraints") or {}
    write = constraints.get("write")
    if write is not None and write not in ("allowed", "forbidden"):
        errors.append(
            f"skill '{data.get('skill_id', '?')}': constraints.write must be 'allowed' or 'forbidden'"
        )
    return errors


def validate_task_policy(data: dict, known: set, ops: dict) -> list:
    """Validate a task capability policy.

    * unknown capability ids are rejected;
    * ``requires`` and ``denies`` must not overlap;
    * READ_ONLY mode cannot require or allow write-operation capabilities.
    """
    errors = []
    policy = (data or {}).get("capability_policy")
    if not policy:
        return errors
    task = data.get("task_id") or data.get("id") or data.get("title") or "?"
    label = f"task '{task}'"

    def _unknown(cid):
        if not CAPABILITY_ID_RE.match(cid):
            errors.append(f"{label}: invalid capability id '{cid}'")
            return True
        if cid not in known:
            errors.append(f"{label}: unknown capability '{cid}'")
            return True
        return False

    requires = policy.get("requires") or []
    allows = policy.get("allows") or []
    denies = policy.get("denies") or []
    mode = policy.get("mode")

    for cid in requires + allows + denies:
        _unknown(cid)

    overlap = set(requires) & set(denies)
    if overlap:
        errors.append(f"{label}: capability in both requires and denies: {', '.join(sorted(overlap))}")

    if mode == "READ_ONLY":
        for cid in requires + allows:
            if cid in known and ops.get(cid) == OPERATION_WRITE:
                errors.append(
                    f"{label}: READ_ONLY mode conflicts with {OPERATION_WRITE} capability '{cid}'"
                )
    return errors


def validate_agent_policy(data: dict, known: set, ops: dict) -> list:
    """Validate an agent contract capability declaration."""
    errors = []
    requires = (data or {}).get("capability_requires") or []
    label = f"agent '{data.get('agent_id', '?')}'"
    for cid in requires:
        if not CAPABILITY_ID_RE.match(cid):
            errors.append(f"{label}: invalid capability id '{cid}'")
        elif cid not in known:
            errors.append(f"{label}: unknown capability '{cid}'")
    return errors


def _profile_errors(root, project):
    """Validate a project manifest profiles.capability / profiles.toolchain.providers."""
    errors = []
    known = known_capabilities(root)
    providers = known_providers(root)
    profiles = (project or {}).get("profiles") or {}
    for cid in profiles.get("capability") or []:
        if not CAPABILITY_ID_RE.match(cid):
            errors.append(f"{project.get('project_id', '?')} profiles.capability: invalid capability id '{cid}'")
        elif cid not in known:
            errors.append(f"{project.get('project_id', '?')} profiles.capability: unknown capability '{cid}'")
    for pid in (profiles.get("toolchain") or {}).get("providers") or []:
        if pid not in providers:
            errors.append(f"{project.get('project_id', '?')} profiles.toolchain.providers: unknown provider '{pid}'")
    return errors


def check_policies(root=None, project=None, tasks=None) -> list:
    """Validate all declared capability policies (canonical + optional project).

    Canonical: every skill sidecar (SKILLS/*/SKILL.json) and every agent contract
    (AGENTS/*/agent.json). Project: profiles and task policies.
    """
    base = Path(root) if root else repo_root()
    schema_meta = capability_meta(base)
    known = set(schema_meta)
    ops = {cid: m["operation"] for cid, m in schema_meta.items()}
    errors = []

    skills_dir = base / "SKILLS"
    if skills_dir.exists():
        for sidecar in sorted(skills_dir.glob("*/SKILL.json")):
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"{sidecar}: unreadable: {exc}")
                continue
            errors.extend(validate_skill_policy(data, known, ops))

    agents_dir = base / "AGENTS"
    if agents_dir.exists():
        for contract in sorted(agents_dir.glob("*/agent.json")):
            try:
                data = json.loads(contract.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"{contract}: unreadable: {exc}")
                continue
            errors.extend(validate_agent_policy(data, known, ops))

    if project is not None:
        errors.extend(_profile_errors(base, project))

    if tasks:
        for task in tasks:
            errors.extend(validate_task_policy(task, known, ops))

    return errors


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

_MAP_NAME = {
    "project": "project profile",
    "agent": "agent",
    "skill": "skill",
    "task": "task",
}


def resolve_plan(root=None, project=None, agent=None, skill=None, task=None) -> dict:
    """Resolve a deterministic capability plan for the given context.

    Resolution order (more specific prevails):
    SYSTEM (available) -> Project profile -> Agent -> Skill -> Task.

    Statuses: ALLOW, DENY, OPTIONAL, REQUIRED. A capability that is REQUIRED by
    any layer but ends DENIED (task deny, READ_ONLY, skill write-forbidden) or
    that is REQUIRED but not available is reported as a conflict.
    """
    base = Path(root) if root else repo_root()
    meta = capability_meta(base)
    known = set(meta)
    ops = {cid: m["operation"] for cid, m in meta.items()}
    available = available_capabilities(base)

    entries = {}
    for cid in sorted(known):
        entries[cid] = {
            "status": "ALLOW",
            "operation": ops[cid],
            "provider": meta[cid]["provider"],
            "available": cid in available,
            "sources": [],
            "conflicts": [],
        }

    def _set(cid, status, source):
        if cid in entries:
            entries[cid]["status"] = status
            if source not in entries[cid]["sources"]:
                entries[cid]["sources"].append(source)

    for cid in sorted(available):
        _set(cid, "ALLOW", "system")

    # Layer: project profile
    if project is not None:
        for cid in (project.get("profiles") or {}).get("capability") or []:
            if cid in known:
                _set(cid, "REQUIRED", "project")

    # Layer: agent
    if agent is not None:
        for cid in agent.get("capability_requires") or []:
            if cid in known:
                _set(cid, "REQUIRED", "agent")

    # Layer: skill
    skill_forbids_write = False
    if skill is not None:
        caps = skill.get("capabilities") or {}
        for cid in caps.get("required") or []:
            if cid in known:
                _set(cid, "REQUIRED", "skill")
        for cid in caps.get("optional") or []:
            if cid in known and entries[cid]["status"] in ("ALLOW", "OPTIONAL"):
                _set(cid, "OPTIONAL", "skill")
        skill_forbids_write = (skill.get("constraints") or {}).get("write") == "forbidden"
        if skill_forbids_write:
            for cid in known:
                if ops[cid] == OPERATION_WRITE:
                    _set(cid, "DENY", "skill")

    # Layer: task
    task_denies = set()
    task_read_only = False
    if task is not None:
        policy = task.get("capability_policy") or {}
        for cid in policy.get("allows") or []:
            if cid in known:
                _set(cid, "ALLOW", "task")
        for cid in policy.get("requires") or []:
            if cid in known:
                _set(cid, "REQUIRED", "task")
        for cid in policy.get("denies") or []:
            if cid in known:
                _set(cid, "DENY", "task")
                task_denies.add(cid)
        task_read_only = policy.get("mode") == "READ_ONLY"
        if task_read_only:
            for cid in known:
                if ops[cid] == OPERATION_WRITE:
                    _set(cid, "DENY", "task")
                elif entries[cid]["status"] == "ALLOW":
                    _set(cid, "ALLOW", "task")

    # Conflict detection over REQUIRED wins.
    required_sources = []
    seen = set()
    for layer, value in (
        ("project", ((project.get("profiles") or {}).get("capability") or []) if project else []),
        ("agent", (agent.get("capability_requires") or []) if agent else []),
        ("skill", ((skill.get("capabilities") or {}).get("required") or []) if skill else []),
        ("task", ((task.get("capability_policy") or {}).get("requires") or []) if task else []),
    ):
        for cid in value:
            if cid in known and cid not in seen:
                seen.add(cid)
                required_sources.append((cid, layer))

    conflicts = []
    for cid, layer in required_sources:
        entry = entries[cid]
        if not entry["available"]:
            msg = f"required by {_MAP_NAME[layer]} but capability '{cid}' is not available"
            conflicts.append(msg)
            entry["conflicts"].append(msg)
        if entry["status"] == "DENY":
            reason = []
            if cid in task_denies:
                reason.append("denied by task policy")
            elif task_read_only and ops[cid] == OPERATION_WRITE:
                reason.append("denied by READ_ONLY mode")
            elif skill_forbids_write and ops[cid] == OPERATION_WRITE:
                reason.append("denied by skill write-forbidden constraint")
            else:
                reason.append("denied by a more specific layer")
            msg = f"required by {_MAP_NAME[layer]} but {reason[0]}: '{cid}'"
            conflicts.append(msg)
            entry["conflicts"].append(msg)

    # Skill vs task write conflict (explicit re-grant of a forbidden write).
    if skill_forbids_write and task is not None:
        policy = task.get("capability_policy") or {}
        for cid in known:
            if ops[cid] != OPERATION_WRITE:
                continue
            if cid in (policy.get("requires") or []) or cid in (policy.get("allows") or []):
                msg = (
                    f"task grants write capability '{cid}' but skill '{skill.get('skill_id', '?')}'"
                    " forbids writes"
                )
                if msg not in conflicts:
                    conflicts.append(msg)
                    entries[cid]["conflicts"].append(msg)

    plan = {
        "root": str(base),
        "status": "CONFLICT" if conflicts else "PASS",
        "context": {
            "project": (project or {}).get("project_id") if project else None,
            "agent": (agent or {}).get("agent_id") if agent else None,
            "skill": (skill or {}).get("skill_id") if skill else None,
            "task": (task or {}).get("task_id") if task else None,
        },
        "capabilities": {
            cid: {
                "status": entries[cid]["status"],
                "operation": entries[cid]["operation"],
                "provider": entries[cid]["provider"],
                "available": entries[cid]["available"],
                "sources": entries[cid]["sources"],
                "conflicts": entries[cid]["conflicts"],
            }
            for cid in sorted(entries)
        },
        "conflicts": sorted(conflicts),
    }
    return plan