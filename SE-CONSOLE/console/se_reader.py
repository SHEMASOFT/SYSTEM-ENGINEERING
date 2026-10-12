"""SE-CONSOLE :: transcription-only reader for canonical SE state.

SCOPE / NON-GOVERNANCE RULE
---------------------------
This module may PARSE, VALIDATE, INDEX and COUNT. It may NOT decide.

Specifically it never answers: does a gate pass, is coverage sufficient, is
this reference valid, is the project healthy, is an acceptance satisfied.
Those are governance verdicts and they belong to `se` (``se_cli``). This
module stores nothing; every call re-reads the canonical files.

The ONE derived computation it performs is an inverted link index, because
canonical records store links as forward ID arrays and a reverse query
("which requirements does EVD-0008 support?") would otherwise require a full
scan. The index is rebuilt on every call and is never persisted.

It also exposes a `source_fingerprint` so the UI can show canonical provenance
and prove, at any moment, which bytes it is reporting on.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

_CONSOLE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Canonical SE root. When vendored, this console lives at <repo>/SE-CONSOLE and
#: the repository root is its parent (`SE-CONSOLE/..`); SE_ROOT may still be
#: overridden via the environment (the old hardcoded Windows path and the
#: sibling-checkout assumption both broke rooting off Windows / when vendored).
SE_ROOT = os.environ.get("SE_ROOT") or os.path.dirname(_CONSOLE_ROOT)
PROJECTS_DIR = os.path.join(SE_ROOT, "PROJECTS")

#: record type -> (directory, id field, schema path)
RECORD_LAYOUT: dict[str, tuple[str, str, str]] = {
    "OBJECTIVE": ("objectives", "objective_id", "SCHEMAS/objective/objective.schema.json"),
    "REQUIREMENT": ("requirements", "id", "SCHEMAS/requirement/requirement.schema.json"),
    "TASK": ("tasks", "id", "SCHEMAS/task/task.schema.json"),
    "ARTIFACT": ("artifacts", "artifact_id", "SCHEMAS/artifact/artifact.schema.json"),
    "EVIDENCE": ("evidence", "id", "SCHEMAS/evidence/evidence.schema.json"),
    "ACCEPTANCE": ("acceptances", "acceptance_id", "SCHEMAS/acceptance/acceptance.schema.json"),
    "DECISION": ("decisions", "decision_id", "SCHEMAS/decision/decision.schema.json"),
    "RELEASE": ("releases", "id", "SCHEMAS/release/release.schema.json"),
    # RUN records one episode of work (intent, execution, runtime/harness/model,
    # checkpoint, recovery). Registered here so the console reads it through the
    # same transcription path as every other canonical record type.
    "RUN": ("runs", "run_id", "SCHEMAS/run/run.schema.json"),
}

#: Link fields that carry record ids, used only to build the inverted index.
LINK_FIELDS = (
    "related_requirements",
    "related_tasks",
    "related_artifacts",
    "related_evidence",
    "related_decisions",
    "related_releases",
    "evidence",
    "produced_by",
    "dependencies",
    "subtasks",
)

_SECRET_DIR_NAMES = {"node_modules", ".git", "__pycache__", "backups", "db_backups", "uploads"}
_SECRET_FILE_RE = re.compile(
    r"(^\.env($|\.)|\.pem$|\.key$|^id_(rsa|dsa|ecdsa|ed25519)$|_rsa$|secrets?|credentials?|\.npmrc$)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Low-level, read-only IO
# --------------------------------------------------------------------------


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:  # read mode only, never "w"/"a"
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def read_json(path: str) -> tuple[Any, str | None]:
    """Return ``(parsed, error)``. Never raises."""
    text = _read_text(path)
    if text is None:
        return None, "unreadable"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc.msg} (line {exc.lineno})"


def sha256_of(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def is_sensitive(relpath: str) -> bool:
    """Deny-by-default exclusion of secret-bearing and bulk paths."""
    parts = relpath.replace("\\", "/").split("/")
    if any(p in _SECRET_DIR_NAMES for p in parts):
        return True
    return bool(_SECRET_FILE_RE.search(parts[-1] if parts else ""))


# --------------------------------------------------------------------------
# Framework reference (static, versioned SE definitions)
# --------------------------------------------------------------------------


def read_framework() -> dict[str, Any]:
    """Read CORE/*, SCHEMAS/index.json, COMMANDS/commands.json, capabilities.

    These are static versioned JSON documents: reading them gives the console
    the *same* definitions the engine enforces, with no subprocess cost.
    """
    out: dict[str, Any] = {"errors": []}

    for key, rel in (
        ("system", "SYSTEM.json"),
        ("lifecycle", "CORE/lifecycle/lifecycle.json"),
        ("gates", "CORE/gates/gates.json"),
        ("task_states", "CORE/tasks/task-states.json"),
        ("permissions", "CORE/policies/permissions.json"),
        ("artifact_types", "CORE/artifacts/artifact-types.json"),
        ("capabilities", "CORE/capabilities/capabilities.json"),
        ("commands", "COMMANDS/commands.json"),
        ("schema_index", "SCHEMAS/index.json"),
        ("manifest", "MASTER SYSTEM/MANIFEST.json"),
    ):
        data, err = read_json(os.path.join(SE_ROOT, rel))
        if err:
            out["errors"].append({"source": rel, "error": err})
            out[key] = None
        else:
            out[key] = data

    version, _ = read_text_value(os.path.join(SE_ROOT, "VERSION"))
    out["version_file"] = version.strip() if version else None

    changelog = _read_text(os.path.join(SE_ROOT, "MASTER SYSTEM", "CHANGELOG.md"))
    out["changelog_head"] = changelog[:2000] if changelog else None

    out["agents"] = _read_agents()
    out["skills"] = _read_skills()
    out["policies"] = _read_named("POLICIES", ".md")
    out["domains"] = _read_domains()
    return out


def read_text_value(path: str) -> tuple[str | None, str | None]:
    text = _read_text(path)
    return text, None if text is not None else "unreadable"


def _read_agents() -> list[dict[str, Any]]:
    """Agent contracts from AGENTS/*/agent.json (canonical)."""
    base = os.path.join(SE_ROOT, "AGENTS")
    found: list[dict[str, Any]] = []
    if not os.path.isdir(base):
        return found
    for name in sorted(os.listdir(base)):
        agent_json = os.path.join(base, name, "agent.json")
        if not os.path.isfile(agent_json):
            continue
        data, err = read_json(agent_json)
        if err:
            found.append({"id": name, "error": err})
            continue
        entry = {"id": data.get("id", name)}
        for field in ("name", "role", "description", "version", "status", "model"):
            if field in data:
                entry[field] = data[field]
        entry["source"] = f"AGENTS/{name}/agent.json"
        found.append(entry)
    return found


def _read_skills() -> list[dict[str, Any]]:
    base = os.path.join(SE_ROOT, "SKILLS")
    found: list[dict[str, Any]] = []
    if not os.path.isdir(base):
        return found
    for name in sorted(os.listdir(base)):
        skill_md = os.path.join(base, name, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        text = _read_text(skill_md) or ""
        description = ""
        for line in text.splitlines():
            if line.lower().startswith("description:"):
                description = line.split(":", 1)[1].strip()
                break
        found.append(
            {"id": name, "description": description, "source": f"SKILLS/{name}/SKILL.md"}
        )
    return found


def _read_named(subdir: str, suffix: str) -> list[dict[str, Any]]:
    base = os.path.join(SE_ROOT, subdir)
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if name.endswith(suffix):
            out.append({"id": name[: -len(suffix)], "source": f"{subdir}/{name}"})
    return out


def _read_domains() -> list[dict[str, Any]]:
    base = os.path.join(SE_ROOT, "DOMAINS")
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if os.path.isdir(p) and not name.startswith("_") and not name.startswith("."):
            out.append({"id": name, "source": f"DOMAINS/{name}"})
    return out


# --------------------------------------------------------------------------
# Project discovery (transcription)
# --------------------------------------------------------------------------


def discover_projects() -> list[dict[str, Any]]:
    """Scan PROJECTS/ and classify each candidate.

    A candidate is only a MANAGED project if it has a schema-valid
    PROJECT.json. Everything else is reported as UNMANAGED with the reason,
    so the console can be honest about SHEMA rather than inventing its state.
    """
    if not os.path.isdir(PROJECTS_DIR):
        return []

    out: list[dict[str, Any]] = []
    for name in sorted(os.listdir(PROJECTS_DIR)):
        path = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(path) or name.startswith("."):
            continue
        manifest_path = os.path.join(path, "PROJECT.json")
        entry: dict[str, Any] = {
            "dir_name": name,
            "path": path,
            "rel_path": f"PROJECTS/{name}",
            "has_project_json": os.path.isfile(manifest_path),
        }
        if not entry["has_project_json"]:
            entry["management"] = "UNMANAGED"
            entry["reason"] = "no PROJECT.json — not a SYSTEM-ENGINEERING managed project"
            entry["project_id"] = None
            entry["name"] = name
            out.append(entry)
            continue

        data, err = read_json(manifest_path)
        if err:
            entry["management"] = "INVALID"
            entry["reason"] = f"PROJECT.json {err}"
            entry["project_id"] = None
            entry["name"] = name
            out.append(entry)
            continue

        validation = validate_record(
            data, "SCHEMAS/project/project.schema.json", "PROJECT"
        )
        entry["management"] = "MANAGED" if validation["ok"] else "INVALID"
        entry["reason"] = (
            None
            if validation["ok"]
            else f"PROJECT.json fails schema: {validation['errors'][:3]}"
        )
        entry["project_id"] = data.get("project_id")
        entry["name"] = data.get("name")
        entry["owner"] = data.get("owner")
        entry["lifecycle_state"] = data.get("lifecycle_state")
        entry["criticality"] = data.get("criticality")
        entry["blocked"] = data.get("blocked", False)
        entry["version"] = data.get("version")
        entry["master_system_version"] = data.get("master_system_version")
        entry["domains"] = data.get("domains")
        entry["updated_at"] = data.get("updated_at")
        entry["schema_valid"] = validation["ok"]
        entry["schema_errors"] = validation["errors"]
        entry["manifest_sha256"] = sha256_of(manifest_path)
        out.append(entry)
    return out


# --------------------------------------------------------------------------
# Schema validation (delegates to SE's own schemas; no redefinition)
# --------------------------------------------------------------------------


_schema_cache: dict[str, Any] = {}


def _load_schema(rel: str) -> Any | None:
    if rel not in _schema_cache:
        data, err = read_json(os.path.join(SE_ROOT, rel))
        _schema_cache[rel] = None if err else data
    return _schema_cache[rel]


def validate_record(data: Any, schema_rel: str, label: str) -> dict[str, Any]:
    """Validate against SE's canonical schema. Reports, never repairs."""
    schema = _load_schema(schema_rel)
    if schema is None:
        return {
            "ok": False,
            "errors": [f"schema unavailable: {schema_rel}"],
            "label": label,
        }
    try:
        import jsonschema
    except ImportError:
        return {
            "ok": False,
            "errors": ["jsonschema not installed; validation UNKNOWN"],
            "label": label,
        }
    validator = jsonschema.Draft202012Validator(schema)
    problems = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        problems.append(f"{loc}: {err.message}")
    return {"ok": not problems, "errors": problems, "label": label}


# --------------------------------------------------------------------------
# Record loading (transcription)
# --------------------------------------------------------------------------


def load_records(project_path: str, rtype: str) -> dict[str, Any]:
    """Load one record type from a project workspace.

    Returns records plus per-record schema validation. Validation failures are
    SURFACED as findings, never dropped: hiding them would make the console
    less honest than ``se validate``.
    """
    if rtype not in RECORD_LAYOUT:
        return {"type": rtype, "error": f"unknown record type {rtype}", "records": []}

    subdir, id_field, schema_rel = RECORD_LAYOUT[rtype]
    dirpath = os.path.join(project_path, subdir)
    out: dict[str, Any] = {
        "type": rtype,
        "schema": schema_rel,
        "dir": f"{os.path.basename(project_path)}/{subdir}",
        "records": [],
        "invalid": [],
        "error": None,
    }
    if not os.path.isdir(dirpath):
        out["error"] = f"directory absent: {subdir}/"
        out["absent"] = True
        return out

    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(dirpath, fname)
        data, err = read_json(fpath)
        if err:
            out["invalid"].append(
                {"file": fname, "errors": [f"unreadable or invalid JSON: {err}"]}
            )
            continue
        rid = data.get(id_field) or fname[: -len(".json")]
        v = validate_record(data, schema_rel, rid)
        entry = {
            "id": rid,
            "file": fname,
            "rel_path": os.path.relpath(fpath, SE_ROOT).replace("\\", "/"),
            "sha256": sha256_of(fpath),
            "schema_valid": v["ok"],
            "schema_errors": v["errors"],
            "data": data,
        }
        out["records"].append(entry)
        if not v["ok"]:
            out["invalid"].append({"file": fname, "id": rid, "errors": v["errors"]})
    return out


def load_discovery(project_path: str) -> dict[str, Any]:
    data, err = read_json(os.path.join(project_path, "discovery.json"))
    if err:
        return {"present": False, "error": err, "data": None, "schema_valid": None}
    v = validate_record(data, "SCHEMAS/discovery/discovery.schema.json", "DISCOVERY")
    return {
        "present": True,
        "error": None,
        "data": data,
        "schema_valid": v["ok"],
        "schema_errors": v["errors"],
    }


def load_mutation_log(project_path: str) -> dict[str, Any]:
    """Parse mutation-log.jsonl.

    Observed data-quality fact: several `add` mutations store comma-joined
    strings where a list is structurally correct (e.g. "EVD-0006,EVD-0007").
    We normalise for interpretation and keep the raw value visible so the
    normalisation is auditable rather than silent.
    """
    path = os.path.join(project_path, "mutation-log.jsonl")
    result: dict[str, Any] = {"present": False, "entries": [], "malformed": 0}
    text = _read_text(path)
    if text is None:
        return result
    result["present"] = True

    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            result["malformed"] += 1
            continue
        changes = []
        for ch in raw.get("changes", []) or []:
            value = ch.get("value")
            normalised = value
            split_flag = False
            if isinstance(value, str) and "," in value:
                parts = [p.strip() for p in value.split(",") if p.strip()]
                if parts and all(re.fullmatch(r"[A-Z]{3,4}-\d{4}", p) for p in parts):
                    normalised = parts
                    split_flag = True
            changes.append(
                {
                    "field": ch.get("field"),
                    "action": ch.get("action"),
                    "value_raw": value,
                    "value_normalized": normalised,
                    "was_split": split_flag,
                }
            )
        result["entries"].append(
            {
                "seq": lineno,
                "at": raw.get("at"),
                "record_type": raw.get("record_type"),
                "record_id": raw.get("record_id"),
                "by": raw.get("by"),
                "changes": changes,
            }
        )
    return result


def load_project_docs(project_path: str) -> dict[str, Any]:
    """SUPPORTING narrative. Explicitly not authoritative for gates."""
    docs = os.path.join(project_path, "docs")
    if not os.path.isdir(docs):
        return {"present": False, "documents": []}
    out = []
    for root, _dirs, files in os.walk(docs):
        for f in sorted(files):
            if f.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(root, f), project_path).replace("\\", "/")
            if is_sensitive(rel):
                continue
            out.append({"name": f, "rel_path": f"docs/{os.path.relpath(os.path.join(root, f), project_path).replace(chr(92), '/')}"})
    return {"present": True, "documents": out}


def load_transitions(project_path: str) -> dict[str, Any]:
    """Lifecycle transitions + version migrations from PROJECT.json metadata."""
    data, err = read_json(os.path.join(project_path, "PROJECT.json"))
    if err:
        return {"present": False, "error": err, "transitions": [], "migrations": []}
    meta = data.get("metadata") or {}
    return {
        "present": True,
        "transitions": meta.get("transitions") or [],
        "migrations": meta.get("migrations") or [],
    }


# --------------------------------------------------------------------------
# Derived inverted link index (rebuilt per call, never persisted)
# --------------------------------------------------------------------------


def build_link_index(project_path: str) -> dict[str, Any]:
    """Invert the forward ``related_*`` arrays into a queryable adjacency map.

    This is the only derived computation in the reader. It answers "what
    points at X" without a full scan. It is NOT a verdict: an index entry
    records that an id was *declared*, not that the relationship is correct.
    ``se review``'s ``link_notes`` remain the authority on link integrity.
    """
    index: dict[str, list[dict[str, str]]] = {}
    counts: dict[str, int] = {}

    for rtype, (subdir, id_field, _schema) in RECORD_LAYOUT.items():
        loaded = load_records(project_path, rtype)
        counts[rtype] = len(loaded["records"])
        for rec in loaded["records"]:
            src = rec["id"]
            data = rec["data"]
            for field in LINK_FIELDS:
                value = data.get(field)
                if not isinstance(value, list):
                    continue
                for dst in value:
                    if not isinstance(dst, str):
                        continue
                    index.setdefault(dst, []).append(
                        {"from_type": rtype, "from_id": src, "via": field}
                    )
    return {"inbound": index, "counts": counts}


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def source_fingerprint(paths: list[str]) -> dict[str, Any]:
    """Hash the canonical files the console is reporting on."""
    entries = []
    for rel in paths:
        full = os.path.join(SE_ROOT, rel)
        entries.append({"path": rel, "sha256": sha256_of(full), "bytes": _size(full)})
    return {
        "se_root": SE_ROOT,
        "files": entries,
        "fingerprint": hashlib.sha256(
            "|".join(f"{e['path']}:{e['sha256']}" for e in entries).encode()
        ).hexdigest(),
    }


def _size(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None
