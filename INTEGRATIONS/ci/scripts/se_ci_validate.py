#!/usr/bin/env python3
"""Run the canonical ``se validate`` and translate it into a CI verdict.

Exit codes (adapter contract):
    0 PASS          validation passed
    1 FAIL          validation failed (the engine/contracts or the project)
    2 usage error   invalid arguments (argparse)
    3 OPERATIONAL   verification was impossible (missing project, engine or dependency)

A ``WARN`` from ``se validate`` is informational in SE and stays non-blocking
here: the adapter does not reinterpret engine warnings as failures.
"""

from __future__ import annotations

import argparse
import sys

from se_ci_common import (
    STATUS_FAIL,
    STATUS_PASS,
    OperationalError,
    check_python_version,
    emit,
    finding,
    make_report,
    operational_report,
    parse_envelope,
    read_project,
    require_module,
    resolve_project,
    resolve_se_root,
    run_se,
)

STEP = "validate"


def classify(envelope: dict) -> tuple:
    status = envelope.get("status")
    conflicts = [str(item) for item in envelope.get("conflicts") or []]
    warnings = [str(item) for item in envelope.get("warnings") or []]
    findings = [finding("FAIL", "VALIDATE", message) for message in conflicts]
    findings.extend(finding("WARN", "VALIDATE", message) for message in warnings)

    if status == "FAIL":
        summary = f"se validate reported {len(conflicts)} failure(s)"
        return STATUS_FAIL, summary, findings
    if status in ("PASS", "WARN"):
        if status == "WARN":
            summary = (
                f"se validate passed with {len(warnings)} informational warning(s) "
                "(non-blocking in SE)"
            )
        else:
            summary = "se validate passed"
        return STATUS_PASS, summary, findings
    raise OperationalError(
        f"se validate returned an unexpected status: {status!r}",
        code="UNEXPECTED_STATUS",
    )


def run(args) -> dict:
    project = None
    details = {}
    try:
        check_python_version()
        se_root = resolve_se_root(args.se_root)
        project = resolve_project(args.project)
        manifest = read_project(project)
        require_module("jsonschema", "Install it with: python -m pip install jsonschema")

        result = run_se(
            se_root,
            ["validate", "--project", str(project), "--json"],
            timeout=args.timeout,
        )
        envelope = parse_envelope(result, "validate")
        status, summary, findings = classify(envelope)

        # The envelope is authoritative, but an inconsistent exit code means the
        # CLI and the adapter disagree: do not report a verdict we cannot trust.
        if status == STATUS_PASS and result["exit_code"] != 0:
            raise OperationalError(
                "se validate reported PASS but exited with "
                f"{result['exit_code']}; refusing to trust the envelope",
                code="INCONSISTENT_EXIT",
            )
        if status == STATUS_FAIL and result["exit_code"] == 0:
            raise OperationalError(
                "se validate reported FAIL but exited with 0; refusing to trust the envelope",
                code="INCONSISTENT_EXIT",
            )

        details = {
            "project_id": manifest.get("project_id"),
            "lifecycle_state": manifest.get("lifecycle_state"),
            "master_system_version": manifest.get("master_system_version"),
            "project_status": (envelope.get("details") or {}).get("project_status"),
            "envelope_status": envelope.get("status"),
        }
        report = make_report(
            STEP,
            status,
            project=project,
            summary=summary,
            findings=findings,
            evidence={
                "command": ["se", "validate", "--project", str(project), "--json"],
                "exit_code": result["exit_code"],
                "envelope_status": envelope.get("status"),
                "stderr": result["stderr"].strip()[-2000:],
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
        description="Translate canonical 'se validate' into a CI verdict."
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
    parser.add_argument("--timeout", type=int, default=300, help="Command timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Emit se-ci.report/1 JSON.")
    parser.add_argument("--output", default=None, help="Write the JSON report to this path.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return emit(run(args), as_json=args.json, output=args.output)


if __name__ == "__main__":
    sys.exit(main())
