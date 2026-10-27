#!/usr/bin/env python3
"""Aggregate se-ci step reports into one verdict and a GitHub Step Summary.

Precedence (highest first):
    OPERATIONAL_ERROR   verification was impossible (never treated as PASS)
    FAIL                governance validation failed
    MANUAL_PENDING      a human must attest; CI neither attests nor passes it
    PASS                every mandatory step verified

``doctor`` findings are rendered in their own informational section and never
change the verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from se_ci_common import (
    EXIT_FOR_STATUS,
    EXIT_OPERATIONAL,
    INTERFACE_VERSION,
    STATUS_FAIL,
    STATUS_INFO,
    STATUS_MANUAL_PENDING,
    STATUS_OPERATIONAL_ERROR,
    STATUS_PASS,
    finding,
    markdown_step,
)

SUMMARY_SCHEMA = "se-ci.summary/1"
DEFAULT_EXPECTED = ("version", "validate", "gate", "doctor")
STATUS_LABEL = {
    STATUS_PASS: "PASS",
    STATUS_FAIL: "FAIL",
    STATUS_MANUAL_PENDING: "HUMAN APPROVAL REQUIRED",
    STATUS_OPERATIONAL_ERROR: "OPERATIONAL ERROR",
    STATUS_INFO: "INFO",
}


def _synthetic_step(step: str, message: str) -> dict:
    return {
        "step": step,
        "status": STATUS_OPERATIONAL_ERROR,
        "exit_code": EXIT_OPERATIONAL,
        "summary": message,
        "findings": [],
        "manual_conditions": [],
        "gates": [],
        "details": {},
    }


def _report_problem(payload, step: str):
    if not isinstance(payload, dict):
        return f"{step} report is not a JSON object"
    if payload.get("schema") != "se-ci.report/1":
        return f"{step} report is not a se-ci.report/1 document"
    if payload.get("step") != step:
        return f"{step} report declares step {payload.get('step')!r}"
    status = payload.get("status")
    expected_exit = EXIT_FOR_STATUS.get(status)
    if expected_exit is None:
        return f"{step} report has an unknown status: {status!r}"
    if payload.get("exit_code") != expected_exit:
        return (
            f"{step} report reports status {status} with exit"
            f" {payload.get('exit_code')} (expected {expected_exit})"
        )
    return None


def read_steps(input_dir: Path, expected: list) -> tuple:
    steps = []
    operational = []
    for step in expected:
        path = input_dir / f"{step}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            message = f"missing step report: {path}"
            operational.append(finding("FAIL", "MISSING_STEP", message))
            steps.append(_synthetic_step(step, message))
            continue
        except (OSError, json.JSONDecodeError) as exc:
            message = f"cannot read step report {path}: {exc}"
            operational.append(finding("FAIL", "BAD_STEP_REPORT", message))
            steps.append(_synthetic_step(step, message))
            continue
        problem = _report_problem(payload, step)
        if problem:
            operational.append(finding("FAIL", "BAD_STEP_REPORT", problem))
            steps.append(_synthetic_step(step, problem))
            continue
        steps.append(payload)
    return steps, operational


def overall(steps: list, operational: list) -> tuple:
    statuses = [step.get("status") for step in steps]
    if operational or STATUS_OPERATIONAL_ERROR in statuses:
        failures = operational + [
            item
            for step in steps
            if step.get("status") == STATUS_OPERATIONAL_ERROR
            for item in step.get("findings") or []
        ]
        return (
            STATUS_OPERATIONAL_ERROR,
            "verification could not be completed; nothing is reported as compliant",
            failures,
        )
    if STATUS_FAIL in statuses:
        return STATUS_FAIL, "mandatory governance validation failed", []
    if STATUS_MANUAL_PENDING in statuses:
        return (
            STATUS_MANUAL_PENDING,
            "human attestation is required; CI did not attest and governance is not verified",
            [],
        )

    unexpected = [
        step
        for step in steps
        if (step.get("step") == "doctor" and step.get("status") not in (STATUS_PASS, STATUS_INFO))
        or (step.get("step") != "doctor" and step.get("status") != STATUS_PASS)
    ]
    if unexpected:
        findings = [
            finding(
                "FAIL",
                "UNEXPECTED_STATUS",
                f"{step.get('step')} returned {step.get('status')}",
            )
            for step in unexpected
        ]
        return (
            STATUS_OPERATIONAL_ERROR,
            "one or more steps returned a status that cannot be verified as compliant",
            findings,
        )
    return STATUS_PASS, "all mandatory governance steps verified", []


def build_summary(steps: list, operational: list) -> dict:
    status, summary, operational_findings = overall(steps, operational)
    manual = [
        {**condition, "step": step.get("step")}
        for step in steps
        for condition in step.get("manual_conditions") or []
    ]
    return {
        "schema": SUMMARY_SCHEMA,
        "interface_version": INTERFACE_VERSION,
        "status": status,
        "exit_code": EXIT_FOR_STATUS[status],
        "summary": summary,
        "operational_findings": operational_findings,
        "manual_conditions": manual,
        "steps": [
            {
                "step": step.get("step"),
                "status": step.get("status"),
                "exit_code": step.get("exit_code"),
                "summary": step.get("summary"),
            }
            for step in steps
        ],
    }


def render_markdown(summary: dict, steps: list) -> str:
    status = summary["status"]
    lines = [
        f"## SE governance - {STATUS_LABEL.get(status, status)}",
        "",
        summary.get("summary") or "",
        "",
        "| Step | Result | Exit | Summary |",
        "|---|---|---|---|",
    ]
    for step in steps:
        lines.append(
            "| `{}` | {} | {} | {} |".format(
                step.get("step"),
                STATUS_LABEL.get(step.get("status"), step.get("status")),
                step.get("exit_code"),
                str(step.get("summary") or "").replace("|", "\\|"),
            )
        )

    manual = summary.get("manual_conditions") or []
    if manual:
        lines.extend(
            [
                "",
                "### Pending human attestation",
                "",
                "These conditions are MANUAL. CI cannot satisfy, bypass or self-approve them,",
                "so governance is **not verified** while they remain pending.",
                "",
                "| Condition | Gate | Step | Description |",
                "|---|---|---|---|",
            ]
        )
        for condition in manual:
            lines.append(
                "| `{}` | `{}` | `{}` | {} |".format(
                    condition.get("id"),
                    condition.get("gate"),
                    condition.get("step"),
                    str(condition.get("description") or "").replace("|", "\\|"),
                )
            )

    operational = summary.get("operational_findings") or []
    if operational:
        lines.extend(
            [
                "",
                "### Operational findings",
                "",
                "The adapter could not verify these items. 'Could not check' is not 'compliant'.",
                "",
                "| Code | Detail |",
                "|---|---|",
            ]
        )
        for item in operational:
            lines.append(
                "| `{}` | {} |".format(
                    item.get("code"),
                    str(item.get("message") or "").replace("|", "\\|"),
                )
            )

    for step in steps:
        if step.get("step") == "doctor":
            lines.extend(
                [
                    "",
                    "### SE doctor (informational - never blocks)",
                    "",
                    markdown_step(step, heading="####"),
                ]
            )
            break

    lines.extend(
        [
            "",
            "---",
            "SE decides whether governance is satisfied; GitHub enforces it only through",
            "branch protection and required status checks. A green run with unprotected",
            "branches does not prevent a merge. See `INTEGRATIONS/ci/README.md`.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate se-ci step reports into one CI verdict."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing <step>.json reports written with --output.",
    )
    parser.add_argument(
        "--expect",
        default=",".join(DEFAULT_EXPECTED),
        help="Comma-separated step names that must be present (default: version,validate,gate,doctor).",
    )
    parser.add_argument(
        "--output", default=None, help="Write the Markdown summary to this path."
    )
    parser.add_argument("--json", action="store_true", help="Emit se-ci.summary/1 JSON.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    expected = [item.strip() for item in args.expect.split(",") if item.strip()]
    steps, operational = read_steps(Path(args.input_dir), expected)
    summary = build_summary(steps, operational)
    markdown = render_markdown(summary, steps)

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8", newline="\n")
    if args.json:
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(markdown)
    sys.stdout.flush()
    return int(summary["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
