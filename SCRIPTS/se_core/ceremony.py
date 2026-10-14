"""Ceremony policy: the declared work profile drives enforceable requirements.

The work modes (organic / spec / receipt) are the vocabulary; this module is what
makes them real. ``se validate --project`` refuses a project whose declared scale,
risk or criticality demands a document it does not have (an approved SDD, a review
receipt). A project that declares no work profile keeps the defaults — nothing is
required — so adoption and existing projects stay valid by construction.

Policy lives in ``CORE/policies/ceremony.json`` (data, not code); this module only
resolves and applies it.
"""

from __future__ import annotations

from pathlib import Path

from .paths import load_json, repo_root

POLICY_RELPATH = ("CORE", "policies", "ceremony.json")

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

    if requirements.get("spec_required"):
        acceptable = set(policy.get("spec_status_acceptable") or [])
        sdds = _read_records(project, "sdds")
        if not any(str(sdd.get("status")) in acceptable for sdd in sdds):
            failures.append(
                "ceremony: the declared work profile requires an approved SDD "
                f"(no sdds/*.json with status in {sorted(acceptable)})"
            )

    if requirements.get("receipt_required"):
        verdicts = set(policy.get("receipt_verdicts_acceptable") or [])
        rdds = _read_records(project, "rdds")
        if not rdds:
            failures.append(
                "ceremony: the declared work profile requires a review receipt (RDD); none found in rdds/"
            )
        elif not any(str(rdd.get("verdict")) in verdicts for rdd in rdds):
            failures.append(
                "ceremony: the declared work profile requires an RDD with verdict in "
                f"{sorted(verdicts)}"
            )

    return {
        "project": str(project),
        "requirements": requirements,
        "failures": failures,
        "notes": notes,
    }
