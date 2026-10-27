#!/usr/bin/env python3
"""Evaluate the gates that the canonical lifecycle assigns to the current state.

Gate applicability is not guessed: it is read from
``CORE/lifecycle/lifecycle.json`` (``transitions[].gates``), which is the same
contract ``se transition`` enforces. Every declared gate is evaluated with
``se gate --json``; the adapter never evaluates a condition itself.

Outcomes:
    0 PASS                   every declared gate is PASS
    1 FAIL                   at least one gate has FAIL/WARN conditions
    3 OPERATIONAL            the gate set cannot be determined, or evaluation failed
    4 HUMAN APPROVAL REQUIRED at least one gate is MANUAL and none is FAIL/WARN

A pending MANUAL condition is never reported as PASS and is never attested here.
"""

from __future__ import annotations

import argparse
import sys

from se_ci_common import (
    STATUS_FAIL,
    STATUS_MANUAL_PENDING,
    STATUS_PASS,
    OperationalError,
    check_python_version,
    emit,
    finding,
    load_json,
    make_report,
    operational_report,
    parse_envelope,
    read_project,
    require_module,
    resolve_project,
    resolve_se_root,
    run_se,
)

STEP = "gate"


def load_lifecycle(se_root) -> dict:
    return load_json(se_root / "CORE" / "lifecycle" / "lifecycle.json")


def load_gate_ids(se_root) -> set:
    model = load_json(se_root / "CORE" / "gates" / "gates.json")
    return {gate.get("id") for gate in model.get("gates") or [] if gate.get("id")}


def resolve_transition(lifecycle: dict, state: str, target=None) -> tuple:
    """Return ``(to_state, gate_ids)`` for the outgoing transition of ``state``.

    Raises ``OperationalError`` when the state is invalid, the transition is
    ambiguous, the requested target does not exist, or the transition declares
    no gate (the ``OPERATING -> ARCHIVED`` gap): an unverified transition is an
    operational failure, never a PASS.
    """
    states = {entry.get("id") for entry in lifecycle.get("states") or [] if entry.get("id")}
    if not states:
        raise OperationalError(
            "lifecycle model declares no states", code="LIFECYCLE_MODEL"
        )
    if not state:
        raise OperationalError(
            "PROJECT.json has no lifecycle_state; the applicable gate cannot be determined",
            code="STATE_MISSING",
        )
    if state not in states:
        raise OperationalError(
            f"lifecycle_state {state!r} is not a valid lifecycle state; "
            f"valid states: {', '.join(sorted(states))}",
            code="STATE_INVALID",
        )

    outgoing = [
        transition
        for transition in lifecycle.get("transitions") or []
        if transition.get("from") == state
    ]
    if not outgoing:
        raise OperationalError(
            f"no lifecycle transition is declared from {state}; unable to determine the gate",
            code="TRANSITION_MISSING",
        )
    if target is not None:
        outgoing = [item for item in outgoing if item.get("to") == target]
        if not outgoing:
            allowed = [
                str(item.get("to"))
                for item in lifecycle.get("transitions") or []
                if item.get("from") == state
            ]
            raise OperationalError(
                f"transition {state} -> {target} is not declared; "
                f"allowed targets: {', '.join(allowed) or '(none)'}",
                code="TRANSITION_MISSING",
            )
    if len(outgoing) > 1:
        targets = ", ".join(sorted(str(item.get("to")) for item in outgoing))
        raise OperationalError(
            f"gate resolution is ambiguous from {state}: {len(outgoing)} transitions "
            f"({targets}); pass --to <target state> to select one",
            code="AMBIGUOUS_TRANSITION",
        )

    transition = outgoing[0]
    to_state = transition.get("to")
    gate_ids = [str(item) for item in transition.get("gates") or [] if item]
    if not gate_ids:
        raise OperationalError(
            f"transition {state} -> {to_state} declares no gate; governance for this "
            "transition cannot be verified in this increment",
            code="NO_APPLICABLE_GATE",
        )
    return to_state, gate_ids


def evaluate_gates(se_root, project, gate_ids: list) -> list:
    known = load_gate_ids(se_root)
    unknown = [gate for gate in gate_ids if gate not in known]
    if unknown:
        raise OperationalError(
            "lifecycle references gate(s) absent from CORE/gates/gates.json: "
            + ", ".join(unknown),
            code="GATE_MODEL_MISMATCH",
        )

    evaluations = []
    for gate_id in gate_ids:
        result = run_se(
            se_root,
            ["gate", "--project", str(project), "--gate", gate_id, "--json"],
        )
        envelope = parse_envelope(result, "gate")
        gate = envelope.get("gate") or {}
        if gate.get("id") != gate_id:
            raise OperationalError(
                f"se gate returned gate {gate.get('id')!r} while {gate_id!r} was requested",
                code="BAD_ENVELOPE",
            )
        gate_status = gate.get("status") or envelope.get("status")
        if result["exit_code"] not in (0, 1):
            raise OperationalError(
                f"se gate {gate_id} exited with {result['exit_code']}; "
                f"stderr: {result['stderr'].strip()[-800:]}",
                code="SE_EXECUTION",
            )
        if (result["exit_code"] == 0) != (gate_status == "PASS"):
            raise OperationalError(
                f"se gate {gate_id} reported {gate_status!r} with exit "
                f"{result['exit_code']}; refusing to trust the envelope",
                code="INCONSISTENT_EXIT",
            )
        if gate_status not in ("PASS", "WARN", "MANUAL", "FAIL"):
            raise OperationalError(
                f"se gate {gate_id} returned an unexpected status: {gate_status!r}",
                code="UNEXPECTED_STATUS",
            )
        evaluations.append(
            {
                "id": gate_id,
                "to_state": gate.get("to_state"),
                "status": gate_status,
                "exit_code": result["exit_code"],
                "conditions": [
                    {
                        "id": condition.get("id"),
                        "status": condition.get("status"),
                        "automated": condition.get("automated"),
                        "description": condition.get("description"),
                        "detail": condition.get("detail"),
                    }
                    for condition in gate.get("conditions") or []
                ],
                "command": ["se", "gate", "--project", str(project), "--gate", gate_id, "--json"],
            }
        )
    return evaluations


def classify(evaluations: list) -> tuple:
    findings = []
    manual = []
    for evaluation in evaluations:
        gate_id = evaluation["id"]
        for condition in evaluation["conditions"]:
            status = condition.get("status")
            code = f"{gate_id}.{condition.get('id')}"
            if status in ("FAIL", "WARN"):
                findings.append(
                    finding(
                        str(status),
                        code,
                        str(condition.get("detail") or condition.get("description") or ""),
                    )
                )
            elif status == "MANUAL":
                manual.append(
                    {
                        "id": condition.get("id"),
                        "gate": gate_id,
                        "description": condition.get("description"),
                        "detail": condition.get("detail"),
                    }
                )
        if evaluation["status"] in ("FAIL", "WARN") and not any(
            item["code"].startswith(gate_id + ".") for item in findings
        ):
            findings.append(
                finding(
                    str(evaluation["status"]),
                    gate_id,
                    f"gate {gate_id} status is {evaluation['status']}",
                )
            )

    if findings:
        return (
            STATUS_FAIL,
            f"{len(findings)} blocking gate condition(s) did not pass; see findings",
            findings,
            manual,
        )
    if manual:
        ids = ", ".join(str(item.get("id")) for item in manual)
        return (
            STATUS_MANUAL_PENDING,
            "human attestation required: " + ids,
            findings,
            manual,
        )
    return STATUS_PASS, "all declared gates are PASS", findings, manual


def run(args) -> dict:
    project = None
    details = {}
    try:
        check_python_version()
        se_root = resolve_se_root(args.se_root, require_gate_model=True)
        project = resolve_project(args.project)
        manifest = read_project(project)
        require_module("jsonschema", "Install it with: python -m pip install jsonschema")

        state = manifest.get("lifecycle_state")
        lifecycle = load_lifecycle(se_root)
        to_state, gate_ids = resolve_transition(lifecycle, state, args.to)
        details = {
            "project_id": manifest.get("project_id"),
            "lifecycle_state": state,
            "transition": {"from": state, "to": to_state, "gates": gate_ids},
        }

        evaluations = evaluate_gates(se_root, project, gate_ids)
        status, summary, findings, manual = classify(evaluations)
        report = make_report(
            STEP,
            status,
            project=project,
            summary=summary,
            findings=findings,
            manual_conditions=manual,
            gates=evaluations,
            evidence={
                "commands": [item["command"] for item in evaluations],
                "envelope_status": [item["status"] for item in evaluations],
            },
            details=details,
        )
        return report
    except OperationalError as exc:
        return operational_report(STEP, exc, project=project, details=details)
    except Exception as exc:  # noqa: BLE001 - never let an adapter bug look like a PASS
        return operational_report(
            STEP,
            OperationalError(f"unexpected adapter error: {exc}", code="ADAPTER_ERROR"),
            project=project,
            details=details,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate every gate the lifecycle declares for the current state."
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Product checkout containing PROJECT.json (default: current directory).",
    )
    parser.add_argument(
        "--se-root",
        default=None,
        help="SYSTEM-ENGINEERING checkout (default: the checkout containing this script).",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Target lifecycle state (required only if the state has several transitions).",
    )
    parser.add_argument("--json", action="store_true", help="Emit se-ci.report/1 JSON.")
    parser.add_argument("--output", default=None, help="Write the JSON report to this path.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return emit(run(args), as_json=args.json, output=args.output)


if __name__ == "__main__":
    sys.exit(main())
