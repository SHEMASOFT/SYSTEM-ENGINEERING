"""Ceremony policy: the declared work profile drives enforceable requirements.

The work modes (organic / spec / receipt) are the vocabulary; this module is what
makes them real. ``se validate --project`` refuses a project whose declared scale,
risk or criticality demands a document it does not have (an approved SDD, a review
receipt). A project that declares no work profile keeps the defaults — nothing is
required — so adoption and existing projects stay valid by construction.

A document only counts when it is a document: an SDD satisfies ``spec_required``
only if it validates against its schema, its status is accepted and every
``requirements_coverage`` reference resolves to an existing REQUIREMENT. An RDD
satisfies ``receipt_required`` only if it validates against its schema, its verdict
is accepted, ``candidate.hash`` names a real candidate (not a placeholder), its
``evidence[].id`` entries resolve to existing EVD records, and an internal
``linked_change`` reference resolves. The file's existence is never enough.

Policy lives in ``CORE/policies/ceremony.json`` (data, not code); this module only
resolves and applies it.
"""

from __future__ import annotations

import re
from pathlib import Path

from .artifacts import COLLECTIONS, ID_FIELD
from .paths import load_json, repo_root
from .schemas import load_schemas, validate

POLICY_RELPATH = ("CORE", "policies", "ceremony.json")

# A reference shaped like an SE record id. `linked_change` is a free string in the
# schema, so a value that is *not* shaped like a record id (a commit sha, a branch,
# a patch name) is an external change reference: there is no index that could
# resolve it and pretending otherwise would reject valid receipts.
INTERNAL_REF_PATTERN = re.compile(r"^[A-Z]{2,5}-\d{4}$")

_DEFAULT_POLICY = {
    "defaults": {"spec_required": False, "receipt_required": False},
    "by_scale": {},
    "by_risk": {},
    "by_criticality": {},
    "spec_status_acceptable": ["APPROVED", "IMPLEMENTED"],
    "receipt_verdicts_acceptable": ["PASS", "PARTIAL"],
}


def load_policy(root=None) -> dict:
    """Load the ceremony policy; fall back to the built-in defaults when absent."""
    root = Path(root) if root else repo_root()
    policy = {key: value for key, value in _DEFAULT_POLICY.items()}
    path = root.joinpath(*POLICY_RELPATH)
    if path.exists():
        policy.update(load_json(path))
    return policy


def effective_requirements(manifest: dict, policy: dict | None = None) -> dict:
    """Resolve the effective requirements for a project manifest.

    Starts from the defaults and applies, in order, the scale, risk and criticality
    tiers that the manifest actually declares. ``profile_declared`` records whether
    ``profiles.work`` exists at all: without it nothing is enforced.
    """
    policy = policy or load_policy()
    work = (manifest.get("profiles") or {}).get("work") or {}
    scale = work.get("scale")
    risk = work.get("risk")
    criticality = manifest.get("criticality")

    requirements = dict(policy.get("defaults") or {})
    for source in (
        (policy.get("by_scale") or {}).get(scale),
        (policy.get("by_risk") or {}).get(risk),
        (policy.get("by_criticality") or {}).get(criticality),
    ):
        if source:
            requirements.update(source)

    requirements["declared"] = {
        "type": work.get("type"),
        "scale": scale,
        "risk": risk,
        "criticality": criticality,
    }
    requirements["profile_declared"] = bool(work)
    return requirements


def _read_records(project: Path, directory: str) -> list:
    folder = Path(project) / directory
    records = []
    if not folder.is_dir():
        return records
    for path in sorted(folder.glob("*.json")):
        try:
            records.append(load_json(path))
        except Exception:  # noqa: BLE001 - unreadable records are a different check's concern
            continue
    return records


def _record_ids(project: Path, kind: str) -> set:
    field = ID_FIELD[kind]
    return {
        record.get(field)
        for record in _read_records(project, COLLECTIONS[kind]["dir"])
        if record.get(field)
    }


def _known_reference_ids(project: Path) -> set:
    known = set()
    for kind in COLLECTIONS:
        known.update(_record_ids(project, kind))
    return known


def _record_label(kind: str, record: dict) -> str:
    return str(record.get(ID_FIELD[kind]) or "(unidentified record)")


def _schema_reason(record: dict, kind: str, schemas: dict) -> str | None:
    """Why `record` is not a valid record of `kind` (None when it is valid)."""
    schema = schemas.get(kind)
    if schema is None:  # pragma: no cover - every collection has a schema
        return None
    errors = validate(record, schema)
    if not errors:
        return None
    return f"does not validate against the {kind.upper()} schema ({errors[0]})"


def _is_placeholder_hash(value) -> bool:
    """True for the hashes a template leaves behind (empty, all zeros, all same char)."""
    value = str(value or "").strip()
    return not value or len(set(value)) == 1


def _valid_evidence_ids(project: Path, schemas: dict) -> set:
    """Ids of EVD records that exist *and* validate; an external path is not an EVD."""
    ids = set()
    for record in _read_records(project, COLLECTIONS["evidence"]["dir"]):
        identifier = record.get(ID_FIELD["evidence"])
        if identifier and not validate(record, schemas["evidence"]):
            ids.add(identifier)
    return ids


def _sdd_reason(
    sdd: dict, schemas: dict, acceptable: set, requirement_ids: set
) -> str | None:
    reason = _schema_reason(sdd, "sdd", schemas)
    if reason:
        return reason
    status = str(sdd.get("status"))
    if status not in acceptable:
        return (
            f"status {status} is not acceptable "
            f"(expected {'/'.join(sorted(acceptable))})"
        )
    missing = sorted(
        {
            str(ref)
            for ref in (sdd.get("requirements_coverage") or [])
            if ref not in requirement_ids
        }
    )
    if missing:
        return "requirements_coverage references unknown requirement(s): " + ", ".join(missing)
    return None


def _rdd_reason(
    rdd: dict,
    schemas: dict,
    acceptable: set,
    evidence_ids: set,
    known_ids: set,
    project: Path,
) -> str | None:
    reason = _schema_reason(rdd, "rdd", schemas)
    if reason:
        return reason
    verdict = str(rdd.get("verdict"))
    if verdict not in acceptable:
        return (
            f"verdict {verdict} is not acceptable "
            f"(expected {'/'.join(sorted(acceptable))})"
        )
    # R3: Reject terminal statuses (SUPERSEDED, ARCHIVED) even if verdict is acceptable
    status = str(rdd.get("status"))
    if status in {"SUPERSEDED", "ARCHIVED"}:
        return f"status {status} is terminal and cannot satisfy receipt_required"
    candidate_hash = (rdd.get("candidate") or {}).get("hash")
    if _is_placeholder_hash(candidate_hash):
        return (
            f"candidate.hash {str(candidate_hash or '')!r} is a placeholder: "
            "the receipt does not name the change it reviewed"
        )
    # R2: Cross-check EVD.result with RDD.evidence[].result
    for entry in (rdd.get("evidence") or []):
        if not isinstance(entry, dict):
            continue
        evd_id = str(entry.get("id") or "")
        if not evd_id:
            continue
        # Find the actual EVD record
        evd_record = None
        for record in _read_records(project, COLLECTIONS["evidence"]["dir"]):
            if record.get(ID_FIELD["evidence"]) == evd_id:
                evd_record = record
                break
        if evd_record is not None:
            evd_result = str(evd_record.get("result") or "")
            rdd_result = str(entry.get("result") or "")
            if evd_result and rdd_result and evd_result != rdd_result:
                return (
                    f"evidence {evd_id} result mismatch: EVD has {evd_result!r}, "
                    f"receipt claims {rdd_result!r}"
                )
    unresolved = sorted(
        {
            str((entry or {}).get("id") or "(missing id)")
            for entry in (rdd.get("evidence") or [])
            if not isinstance(entry, dict)
            or str(entry.get("id") or "") not in evidence_ids
        }
    )
    if unresolved:
        return "evidence does not resolve to a valid EVD record: " + ", ".join(unresolved)
    linked = str(rdd.get("linked_change") or "").strip()
    if linked and INTERNAL_REF_PATTERN.match(linked) and linked not in known_ids:
        return f"linked_change {linked} does not resolve to an existing record"
    return None


def check_project_ceremony(project, policy: dict | None = None) -> dict:
    """Evaluate the ceremony floor for a project.

    Returns a dict: ``requirements`` (the resolved set), ``failures`` (each one a
    reason ``se validate`` should refuse) and ``notes`` (informational). Raises
    ``FileNotFoundError`` when the project has no manifest — the caller owns that
    failure.
    """
    project = Path(project)
    manifest_file = project / "PROJECT.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"no PROJECT.json in {project}")

    manifest = load_json(manifest_file)
    policy = policy or load_policy()
    requirements = effective_requirements(manifest, policy)
    failures: list = []
    notes: list = []

    if not requirements["profile_declared"]:
        notes.append(
            "no work profile declared (profiles.work); ceremony defaults apply and nothing is required"
        )
        return {
            "project": str(project),
            "requirements": requirements,
            "failures": failures,
            "notes": notes,
        }

    schemas = load_schemas(repo_root())

    if requirements.get("spec_required"):
        acceptable = set(policy.get("spec_status_acceptable") or [])
        requirement_ids = _record_ids(project, "requirement")
        sdds = _read_records(project, COLLECTIONS["sdd"]["dir"])
        reasons = []
        eligible = False
        for sdd in sdds:
            reason = _sdd_reason(sdd, schemas, acceptable, requirement_ids)
            if reason is None:
                eligible = True
                break
            reasons.append(f"{_record_label('sdd', sdd)}: {reason}")
        if not eligible:
            detail = (
                f"no sdds/*.json with status in {sorted(acceptable)}"
                if not sdds
                else "none eligible (" + "; ".join(reasons) + ")"
            )
            failures.append(
                "ceremony: the declared work profile requires an approved SDD "
                f"({detail})"
            )

    if requirements.get("receipt_required"):
        verdicts = set(policy.get("receipt_verdicts_acceptable") or [])
        rdds = _read_records(project, COLLECTIONS["rdd"]["dir"])
        if not rdds:
            failures.append(
                "ceremony: the declared work profile requires a review receipt (RDD); none found in rdds/"
            )
        else:
            evidence_ids = _valid_evidence_ids(project, schemas)
            needs_index = any(
                INTERNAL_REF_PATTERN.match(str(rdd.get("linked_change") or ""))
                for rdd in rdds
            )
            known_ids = _known_reference_ids(project) if needs_index else set()
            reasons = []
            eligible = False
            for rdd in rdds:
                reason = _rdd_reason(rdd, schemas, verdicts, evidence_ids, known_ids, project)
                if reason is None:
                    eligible = True
                    break
                reasons.append(f"{_record_label('rdd', rdd)}: {reason}")
            if not eligible:
                failures.append(
                    "ceremony: the declared work profile requires an RDD with verdict in "
                    f"{sorted(verdicts)} that is a valid receipt "
                    f"(none eligible ({'; '.join(reasons)}))"
                )

    return {
        "project": str(project),
        "requirements": requirements,
        "failures": failures,
        "notes": notes,
    }
