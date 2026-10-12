"""Gate evaluation against a managed project workspace.

A gate passes only when every automated condition passes. Manual conditions are
reported as MANUAL and are never auto-passed.
"""

from __future__ import annotations

from pathlib import Path

from .artifacts import collection, read_discovery, read_manifest
from .paths import load_json, repo_root
from .schemas import load_schemas, validate

SETTLED_TASK_STATES = {"DONE", "CANCELLED"}
ACTIVE_TASK_STATES = {"PENDING", "READY", "IN_PROGRESS"}
EVIDENCE_REQUIRED_TYPES = {"implementation", "design", "test", "documentation", "deployment"}
ARTIFACT_REQUIRED_TYPES = {"implementation", "design", "documentation", "deployment"}
APPROVED_REQUIREMENT_STATES = {"APPROVED", "IMPLEMENTED", "VERIFIED"}
# ADR-0012: DEFERRED and REJECTED requirements are out of scope and are exempt from the
# "must be approved" and "must have evidence" gate rules. They must carry a rationale.
OUT_OF_SCOPE_REQUIREMENT_STATES = {"DEFERRED", "REJECTED"}
NON_FACTUAL_EPISTEMIC = {"UNKNOWN", "ASSUMPTION"}


def load_gate_model(root=None) -> dict:
    root = Path(root) if root else repo_root()
    return load_json(root / "CORE" / "gates" / "gates.json")


def get_gate(gate_id: str, root=None):
    for gate in load_gate_model(root)["gates"]:
        if gate["id"] == gate_id:
            return gate
    return None


def load_lifecycle_model(root=None) -> dict:
    root = Path(root) if root else repo_root()
    return load_json(root / "CORE" / "lifecycle" / "lifecycle.json")


def valid_states(model) -> set:
    return {state["id"] for state in model.get("states", [])}


def find_transition(model, from_state: str, to_state: str):
    for transition in model.get("transitions", []):
        if transition["from"] == from_state and transition["to"] == to_state:
            return transition
    return None


def allowed_targets(model, from_state: str):
    return [t["to"] for t in model.get("transitions", []) if t["from"] == from_state]


class ProjectContext:
    """Read-only view of a project workspace used by gate checks."""

    def __init__(self, project_dir):
        self.dir = Path(project_dir)
        self.manifest = None
        self.manifest_error = None
        try:
            self.manifest = read_manifest(self.dir)
        except Exception as exc:
            self.manifest_error = str(exc)
        self.requirements, self.requirement_errors = collection(self.dir, "requirement")
        self.tasks, self.task_errors = collection(self.dir, "task")
        self.decisions, self.decision_errors = collection(self.dir, "decision")
        self.evidence, self.evidence_errors = collection(self.dir, "evidence")
        self.releases, self.release_errors = collection(self.dir, "release")
        self.objectives, self.objective_errors = collection(self.dir, "objective")
        self.artifacts, self.artifact_errors = collection(self.dir, "artifact")
        self.acceptances, self.acceptance_errors = collection(self.dir, "acceptance")
        self.discovery = read_discovery(self.dir)

    def requirement_data(self):
        return [d for _, d in self.requirements]

    def task_data(self):
        return [d for _, d in self.tasks]

    def evidence_data(self):
        return [d for _, d in self.evidence]

    def release_data(self):
        return [d for _, d in self.releases]

    def objective_data(self):
        return [d for _, d in self.objectives]

    def artifact_data(self):
        return [d for _, d in self.artifacts]

    def acceptance_data(self):
        return [d for _, d in self.acceptances]


def _pass(detail):
    return "PASS", detail


def _fail(detail):
    return "FAIL", detail


def _warn(detail):
    return "WARN", detail


def c_manifest_valid(ctx):
    if ctx.manifest is None:
        return _fail(f"PROJECT.json missing or unreadable: {ctx.manifest_error}")
    errors = validate(ctx.manifest, load_schemas()["project"])
    if errors:
        return _fail("; ".join(errors[:5]))
    return _pass("PROJECT.json is valid")


def c_manifest_owner(ctx):
    if ctx.manifest and ctx.manifest.get("owner"):
        return _pass(f"owner={ctx.manifest['owner']}")
    return _fail("owner is missing")


def c_manifest_domains(ctx):
    if ctx.manifest and ctx.manifest.get("domains"):
        return _pass(f"domains={ctx.manifest['domains']}")
    return _fail("no domains declared")


def c_manifest_criticality(ctx):
    if ctx.manifest and ctx.manifest.get("criticality"):
        return _pass(f"criticality={ctx.manifest['criticality']}")
    return _fail("criticality is missing")


def c_discovery_exists(ctx):
    if ctx.discovery is None:
        return _fail("discovery.json not found")
    if not isinstance(ctx.discovery, dict):
        return _fail("discovery.json is not an object")
    return _pass("discovery.json present")


def c_discovery_unknowns(ctx):
    if ctx.discovery is None:
        return _fail("discovery.json not found")
    if isinstance(ctx.discovery.get("unknowns"), list):
        return _pass(f"{len(ctx.discovery['unknowns'])} unknown(s) enumerated")
    return _fail("discovery.json has no 'unknowns' list")


def c_discovery_scope(ctx):
    if ctx.discovery is None:
        return _fail("discovery.json not found")
    summary = ctx.discovery.get("summary")
    if isinstance(summary, str) and summary.strip():
        return _pass("scope summary present")
    return _fail("discovery.json has no non-empty 'summary'")


def c_discovery_valid(ctx):
    if ctx.discovery is None:
        return _fail("discovery.json not found")
    errors = validate(ctx.discovery, load_schemas()["discovery"])
    if errors:
        return _fail("; ".join(errors[:5]))
    return _pass("discovery.json is valid")


def c_objectives_present(ctx):
    objectives = ctx.objective_data()
    if objectives:
        return _pass(f"{len(objectives)} OBJECTIVE artifact(s)")
    return _fail("no OBJECTIVE artifacts")


def c_objectives_covered(ctx):
    uncovered = []
    for objective in ctx.objective_data():
        if objective.get("epistemic_status") in NON_FACTUAL_EPISTEMIC:
            continue
        if not objective.get("related_requirements"):
            uncovered.append(objective.get("objective_id"))
    if uncovered:
        return _fail(f"objectives without requirements: {', '.join(uncovered)}")
    return _pass("every factual objective is covered by a requirement")


def c_acceptance_record(ctx):
    accepted = [d for d in ctx.acceptance_data() if d.get("result") == "ACCEPTED"]
    if accepted:
        return _pass(f"{len(accepted)} accepted ACCEPTANCE record(s)")
    return _fail("no ACCEPTANCE record with result ACCEPTED")


def c_requirements_present(ctx):
    reqs = [d for d in ctx.requirement_data() if d.get("type") == "REQUIREMENT"]
    if reqs:
        return _pass(f"{len(reqs)} REQUIREMENT artifact(s)")
    return _fail("no REQUIREMENT artifacts")


def c_requirements_acceptance_criteria(ctx):
    missing = [
        d.get("id")
        for d in ctx.requirement_data()
        if d.get("type") == "REQUIREMENT" and not d.get("acceptance_criteria")
    ]
    if missing:
        return _fail(f"missing acceptance_criteria: {', '.join(missing)}")
    return _pass("all REQUIREMENTs have acceptance criteria")


def c_requirements_approved(ctx):
    bad = [
        d.get("id")
        for d in ctx.requirement_data()
        if d.get("type") == "REQUIREMENT"
        and d.get("status") not in APPROVED_REQUIREMENT_STATES
        and d.get("status") not in OUT_OF_SCOPE_REQUIREMENT_STATES
    ]
    if bad:
        return _fail(f"not approved: {', '.join(bad)}")
    return _pass("all in-scope REQUIREMENTs approved")


def c_requirements_risks_recorded(ctx):
    kinds = {"ASSUMPTION", "CONSTRAINT", "RISK", "UNKNOWN"}
    found = [d.get("id") for d in ctx.requirement_data() if d.get("type") in kinds]
    if found:
        return _pass(f"{len(found)} assumption/constraint/risk/unknown artifact(s)")
    return _warn("no assumption/constraint/risk/unknown artifacts; verify none apply")


def c_tasks_present(ctx):
    tasks = ctx.task_data()
    if tasks:
        return _pass(f"{len(tasks)} TASK artifact(s)")
    return _fail("no TASK artifacts")


def c_tasks_cover_requirements(ctx):
    approved = [
        d.get("id")
        for d in ctx.requirement_data()
        if d.get("type") == "REQUIREMENT" and d.get("status") in APPROVED_REQUIREMENT_STATES
    ]
    covered = set()
    for task in ctx.task_data():
        covered.update(task.get("related_requirements", []) or [])
    missing = [req for req in approved if req not in covered]
    if missing:
        return _fail(f"uncovered requirements: {', '.join(missing)}")
    return _pass("every approved requirement is covered by a task")


def c_tasks_acyclic(ctx):
    graph = {d.get("id"): list(d.get("dependencies") or []) for d in ctx.task_data()}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}

    def visit(node):
        color[node] = GRAY
        for dep in graph.get(node, []):
            if dep not in graph:
                continue
            if color[dep] == GRAY:
                return dep
            if color[dep] == WHITE:
                found = visit(dep)
                if found:
                    return found
        color[node] = BLACK
        return None

    for node in graph:
        if color[node] == WHITE:
            cycle = visit(node)
            if cycle:
                return _fail(f"dependency cycle involving {cycle}")
    return _pass("task dependencies are acyclic")


def c_tasks_authorized_actions(ctx):
    missing = [d.get("id") for d in ctx.task_data() if not d.get("authorized_actions")]
    if missing:
        return _fail(f"tasks without authorized_actions: {', '.join(missing)}")
    return _pass("every task declares authorized_actions")


def c_tasks_settled(ctx):
    active = [d.get("id") for d in ctx.task_data() if d.get("status") in ACTIVE_TASK_STATES]
    if active:
        return _fail(f"tasks not settled: {', '.join(active)}")
    return _pass("no pending/ready/in-progress tasks")


def c_tasks_not_blocked(ctx):
    blocked = [d.get("id") for d in ctx.task_data() if d.get("status") == "BLOCKED"]
    if blocked:
        return _fail(f"blocked tasks: {', '.join(blocked)}")
    return _pass("no blocked tasks")


def c_tasks_have_evidence(ctx):
    missing = []
    for task in ctx.task_data():
        if task.get("status") != "DONE":
            continue
        if task.get("type") not in EVIDENCE_REQUIRED_TYPES:
            continue
        if not task.get("evidence"):
            missing.append(task.get("id"))
    if missing:
        return _fail(f"DONE tasks without evidence: {', '.join(missing)}")
    return _pass("DONE deliverable tasks have evidence")


def c_tasks_have_artifacts(ctx):
    producers = set()
    for artifact in ctx.artifact_data():
        producers.update(artifact.get("produced_by", []) or [])
    missing = []
    for task in ctx.task_data():
        if task.get("status") != "DONE":
            continue
        if task.get("type") not in ARTIFACT_REQUIRED_TYPES:
            continue
        if task.get("id") not in producers:
            missing.append(task.get("id"))
    if missing:
        return _fail(f"DONE deliverable tasks without artifacts: {', '.join(missing)}")
    return _pass("DONE deliverable tasks produced artifacts")


def c_requirements_have_evidence(ctx):
    reqs = [
        d.get("id")
        for d in ctx.requirement_data()
        if d.get("type") == "REQUIREMENT"
        and d.get("status") not in OUT_OF_SCOPE_REQUIREMENT_STATES
    ]
    if not reqs:
        return _fail("no in-scope REQUIREMENT artifacts")
    with_evidence = set()
    for evd in ctx.evidence_data():
        with_evidence.update(evd.get("related_requirements", []) or [])
    missing = [req for req in reqs if req not in with_evidence]
    if missing:
        return _fail(f"requirements without evidence: {', '.join(missing)}")
    return _pass("every in-scope requirement is linked to evidence")


def c_evidence_no_fail(ctx):
    failed = [d.get("id") for d in ctx.evidence_data() if d.get("result") == "FAIL"]
    if failed:
        return _fail(f"failing evidence: {', '.join(failed)}")
    return _pass("no failing evidence")


def c_acceptance_uat(ctx):
    uat = [d for d in ctx.evidence_data() if d.get("type") == "uat" and d.get("result") == "PASS"]
    if uat:
        return _pass(f"{len(uat)} passing UAT evidence record(s)")
    return _fail("no passing UAT evidence")


def _latest_release(ctx):
    releases = ctx.release_data()
    if not releases:
        return None
    return sorted(releases, key=lambda d: str(d.get("id", "")))[-1]


def c_release_present(ctx):
    if ctx.release_data():
        return _pass(f"{len(ctx.release_data())} RELEASE artifact(s)")
    return _fail("no RELEASE artifact")


def c_release_approved(ctx):
    release = _latest_release(ctx)
    if release is None:
        return _fail("no RELEASE artifact")
    if release.get("status") == "APPROVED":
        return _pass("latest release is APPROVED")
    return _fail(f"latest release status={release.get('status')}")


def c_release_rollback(ctx):
    release = _latest_release(ctx)
    if release is None:
        return _fail("no RELEASE artifact")
    if release.get("rollback"):
        return _pass("rollback defined")
    return _fail("rollback not defined")


def c_release_deployment_method(ctx):
    release = _latest_release(ctx)
    if release is None:
        return _fail("no RELEASE artifact")
    if release.get("deployment_method"):
        return _pass("deployment method defined")
    return _fail("deployment_method not defined")


def c_release_evidence(ctx):
    release = _latest_release(ctx)
    if release is None:
        return _fail("no RELEASE artifact")
    if release.get("evidence"):
        return _pass(f"{len(release['evidence'])} evidence reference(s)")
    return _fail("release has no evidence references")


def c_operations_doc(ctx):
    if (ctx.dir / "docs" / "operations.md").exists():
        return _pass("docs/operations.md present")
    return _fail("docs/operations.md not found")


def c_release_known_issues(ctx):
    release = _latest_release(ctx)
    if release is None:
        return _fail("no RELEASE artifact")
    if isinstance(release.get("known_issues"), list):
        return _pass(f"{len(release['known_issues'])} known issue(s) tracked")
    return _fail("known_issues not tracked on release")


def c_manual_attestation(ctx):
    return "MANUAL", "requires human attestation; never auto-passed"


CHECKS = {
    "manifest_valid": c_manifest_valid,
    "manifest_owner": c_manifest_owner,
    "manifest_domains": c_manifest_domains,
    "manifest_criticality": c_manifest_criticality,
    "discovery_exists": c_discovery_exists,
    "discovery_valid": c_discovery_valid,
    "discovery_unknowns": c_discovery_unknowns,
    "discovery_scope": c_discovery_scope,
    "objectives_present": c_objectives_present,
    "objectives_covered": c_objectives_covered,
    "requirements_present": c_requirements_present,
    "requirements_acceptance_criteria": c_requirements_acceptance_criteria,
    "requirements_approved": c_requirements_approved,
    "requirements_risks_recorded": c_requirements_risks_recorded,
    "tasks_present": c_tasks_present,
    "tasks_cover_requirements": c_tasks_cover_requirements,
    "tasks_acyclic": c_tasks_acyclic,
    "tasks_authorized_actions": c_tasks_authorized_actions,
    "tasks_settled": c_tasks_settled,
    "tasks_not_blocked": c_tasks_not_blocked,
    "tasks_have_evidence": c_tasks_have_evidence,
    "tasks_have_artifacts": c_tasks_have_artifacts,
    "requirements_have_evidence": c_requirements_have_evidence,
    "evidence_no_fail": c_evidence_no_fail,
    "acceptance_uat": c_acceptance_uat,
    "acceptance_record": c_acceptance_record,
    "release_present": c_release_present,
    "release_approved": c_release_approved,
    "release_rollback": c_release_rollback,
    "release_deployment_method": c_release_deployment_method,
    "release_evidence": c_release_evidence,
    "operations_doc": c_operations_doc,
    "release_known_issues": c_release_known_issues,
    "manual_attestation": c_manual_attestation,
}


def evaluate_gate(project_dir, gate_id: str, root=None) -> dict:
    gate = get_gate(gate_id, root)
    if gate is None:
        raise ValueError(f"unknown gate: {gate_id}")
    ctx = ProjectContext(project_dir)
    results = []
    for condition in gate["conditions"]:
        check = CHECKS.get(condition["check"])
        if check is None:
            results.append({**condition, "status": "WARN", "detail": "no implementation for check"})
            continue
        try:
            status, detail = check(ctx)
        except Exception as exc:  # pragma: no cover - defensive
            status, detail = "WARN", f"check error: {exc}"
        results.append({**condition, "status": status, "detail": detail})

    statuses = [r["status"] for r in results]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "WARN" in statuses:
        overall = "WARN"
    elif "MANUAL" in statuses:
        overall = "MANUAL"
    else:
        overall = "PASS"
    return {"gate": gate, "conditions": results, "status": overall}
