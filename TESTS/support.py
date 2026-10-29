"""Shared helpers for the Master System test-suite.

Hermetic: no network, no production infrastructure, temporary directories only.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "SCRIPTS"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from se_core.artifacts import WORKSPACE_DIRS  # noqa: E402
from se_core.schemas import load_schemas  # noqa: E402

TS = "2024-01-01T00:00:00Z"


def schemas():
    return load_schemas(REPO_ROOT)


def run_cli(*argv):
    """Invoke the reference CLI, capturing stdout. Returns (exit_code, output)."""
    from se_core.cli import main

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = main(list(argv))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    return code, buffer.getvalue()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def manifest(**over):
    data = {
        "schema_version": "1",
        "project_id": "PRJ-TEST-001",
        "name": "Test Project",
        "description": "Test project",
        "owner": "tester",
        "domains": ["software"],
        "criticality": "medium",
        "lifecycle_state": "DRAFT",
        "blocked": False,
        "version": "0.1.0",
        "created_at": TS,
        "updated_at": TS,
        "master_system_version": "0.1.0",
        "source": "test",
        "metadata": {},
    }
    data.update(over)
    return data


def requirement(**over):
    data = {
        "schema_version": "1",
        "id": "REQ-0001",
        "project_id": "PRJ-TEST-001",
        "type": "REQUIREMENT",
        "title": "Requirement title",
        "description": "Requirement description",
        "priority": "high",
        "acceptance_criteria": ["Observable criterion."],
        "status": "APPROVED",
        "created_at": TS,
        "updated_at": TS,
    }
    data.update(over)
    return data


def task(**over):
    data = {
        "schema_version": "1",
        "id": "TASK-0001",
        "project_id": "PRJ-TEST-001",
        "title": "Task title",
        "objective": "Task objective",
        "type": "implementation",
        "authorized_actions": ["READ", "ANALYZE", "IMPLEMENT"],
        "status": "PENDING",
        "created_at": TS,
        "updated_at": TS,
    }
    data.update(over)
    return data


def evidence(**over):
    data = {
        "schema_version": "1",
        "id": "EVD-0001",
        "project_id": "PRJ-TEST-001",
        "type": "test",
        "title": "Evidence title",
        "result": "PASS",
        "collected_at": TS,
        "collected_by": "tester",
    }
    data.update(over)
    return data


def decision(**over):
    data = {
        "schema_version": "1",
        "decision_id": "ADR-0001",
        "project_id": "PRJ-TEST-001",
        "date": "2024-01-01",
        "context": "Context",
        "problem": "Problem",
        "options_considered": [{"option": "A"}, {"option": "B"}],
        "decision": "A",
        "reason": "Because",
        "consequences": "Trade-offs",
        "affected_components": ["component"],
        "status": "ACCEPTED",
    }
    data.update(over)
    return data


def release(**over):
    data = {
        "schema_version": "1",
        "id": "REL-0001",
        "project_id": "PRJ-TEST-001",
        "version": "0.1.0",
        "scope": "Initial release",
        "status": "PLANNED",
        "created_at": TS,
        "updated_at": TS,
    }
    data.update(over)
    return data


def objective(**over):
    data = {
        "schema_version": "1",
        "objective_id": "OBJ-0001",
        "project_id": "PRJ-TEST-001",
        "title": "Objective title",
        "description": "Objective description",
        "status": "ACTIVE",
        "epistemic_status": "OBJECTIVE",
        "priority": "high",
        "success_criteria": ["Observable success criterion."],
        "related_requirements": ["REQ-0001"],
        "created_at": TS,
        "updated_at": TS,
    }
    data.update(over)
    return data


def artifact(**over):
    data = {
        "schema_version": "1",
        "artifact_id": "ART-0001",
        "project_id": "PRJ-TEST-001",
        "title": "Deliverable title",
        "description": "Deliverable description",
        "kind": "code",
        "status": "COMPLETE",
        "produced_by": ["TASK-0001"],
        "related_requirements": ["REQ-0001"],
        "related_evidence": ["EVD-0001"],
        "created_at": TS,
        "updated_at": TS,
    }
    data.update(over)
    return data


REAL_HASH = "34a906c6694b405f948dc5f1010cd2e29ba0bddf"


def template(kind):
    """Load a record template from the repository (the same file `se new` copies)."""
    with (REPO_ROOT / "TEMPLATES" / f"{kind}.template.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def sdd(**over):
    """A schema-valid SDD that references nothing outside the project by default."""
    data = template("sdd")
    data.update({
        "sdd_id": "SDD-0001",
        "project_id": "PRJ-TEST-001",
        "status": "APPROVED",
        "requirements_coverage": [],
        "related_decisions": [],
        "related_tasks": [],
    })
    data.update(over)
    return data


def rdd(**over):
    """A schema-valid receipt whose candidate and evidence are real (not placeholders)."""
    data = template("rdd")
    data.update({
        "rdd_id": "RDD-0001",
        "project_id": "PRJ-TEST-001",
        "verdict": "PASS",
        "candidate": {"kind": "commit", "ref": "abc1234", "hash": REAL_HASH},
        "evidence": [{"id": "EVD-0001", "claim": "Tests pass", "result": "PASS"}],
        "linked_change": "",
    })
    data.update(over)
    return data


def acceptance(**over):
    data = {
        "schema_version": "1",
        "acceptance_id": "ACC-0001",
        "project_id": "PRJ-TEST-001",
        "scope": "Acceptance of the verified result.",
        "criteria_refs": ["REQ-0001"],
        "related_requirements": ["REQ-0001"],
        "evidence": ["EVD-0001", "EVD-0002"],
        "result": "ACCEPTED",
        "decided_by": "tester",
        "authority": "owner",
        "decided_at": TS,
        "gate": "G6",
        "created_at": TS,
        "updated_at": TS,
    }
    data.update(over)
    return data


def make_project(root: Path, state="DRAFT"):
    root.mkdir(parents=True, exist_ok=True)
    for directory in WORKSPACE_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    write_json(root / "PROJECT.json", manifest(lifecycle_state=state))
    return root


def make_full_project(root: Path):
    """A project that satisfies the automated conditions of G0-G8."""
    make_project(root, state="ACCEPTANCE")
    write_json(
        root / "discovery.json",
        {
            "schema_version": "1",
            "summary": "Discovery complete.",
            "findings": [],
            "unknowns": [],
            "assumptions": [],
            "constraints": [],
            "risks": [],
            "reviewed_by": "tester",
            "reviewed_at": TS,
        },
    )
    write_json(root / "objectives" / "OBJ-0001.json", objective())
    write_json(root / "requirements" / "REQ-0001.json", requirement())
    write_json(
        root / "requirements" / "REQ-0002.json",
        requirement(id="REQ-0002", type="RISK", title="Risk", status="APPROVED",
                    acceptance_criteria=[], priority="medium"),
    )
    write_json(
        root / "tasks" / "TASK-0001.json",
        task(
            status="DONE",
            related_requirements=["REQ-0001"],
            evidence=["EVD-0001", "EVD-0002"],
            acceptance_criteria=["Done."],
            verification="Tests pass.",
        ),
    )
    write_json(root / "artifacts" / "ART-0001.json", artifact())
    write_json(
        root / "evidence" / "EVD-0001.json",
        evidence(
            related_requirements=["REQ-0001"],
            related_tasks=["TASK-0001"],
            related_artifacts=["ART-0001"],
        ),
    )
    write_json(
        root / "evidence" / "EVD-0002.json",
        evidence(id="EVD-0002", type="uat", title="UAT", related_requirements=["REQ-0001"]),
    )
    write_json(root / "acceptances" / "ACC-0001.json", acceptance())
    write_json(
        root / "releases" / "REL-0001.json",
        release(
            status="APPROVED",
            rollback="Redeploy previous version.",
            deployment_method="Blue/green deployment.",
            evidence=["EVD-0001"],
            acceptances=["ACC-0001"],
            known_issues=[],
            approval={"approved_by": "tester", "approved_at": TS, "status": "APPROVED"},
        ),
    )
    (root / "docs" / "operations.md").write_text("# Operations\n\nRunbook.\n", encoding="utf-8")
    return root
