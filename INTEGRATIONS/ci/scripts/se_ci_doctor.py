#!/usr/bin/env python3
"""Publish ``se doctor`` findings as INFORMATION for CI; never as a gate.

SE's doctor audits the engine installation, not the product. Its verdict is
published separately and does not change the governance result. The only
non-zero exit is operational (3): the adapter could not run or parse the doctor.

Exit codes:
    0 INFO/PASS   doctor executed; findings (if any) are advisory
    3 OPERATIONAL doctor could not be executed or parsed

Blocking security or environment conditions are intentionally NOT invented
here. If an adopter needs one, it must be declared and tested as an explicit
adapter policy (see INTEGRATIONS/ci/README.md).
"""

from __future__ import annotations

import argparse
import sys

from se_ci_common import (
    STATUS_INFO,
    STATUS_PASS,
    OperationalError,
    check_python_version,
    emit,
    finding,
    make_report,
    operational_report,
    parse_envelope,
    resolve_se_root,
    run_se,
)

STEP = "doctor"


def summarize(envelope: dict) -> tuple:
    details = envelope.get("details") or {}
    checks = details.get("checks") or []
    warnings = []
    failures = []
    for check in checks:
        item = finding(
            str(check.get("status") or "INFO"),
            str(check.get("id") or "CHECK"),
            str(check.get("detail") or check.get("description") or ""),
        )
        if check.get("status") == "FAIL":
            failures.append(item)
        elif check.get("status") == "WARN":
            warnings.append(item)
    summary_data = details.get("summary") or {}
    findings = warnings + failures
    if findings:
        summary = (
            "se doctor reported {} warning(s) and {} failure(s); "
            "informational only, it does not block this workflow".format(
                len(warnings), len(failures)
            )
        )
        status = STATUS_INFO
    else:
        summary = "se doctor reported no findings"
        status = STATUS_PASS
    return status, summary, findings, {
        "summary": summary_data,
        "warnings": len(warnings),
        "failures": len(failures),
        "blocking": False,
    }


def run(args) -> dict:
    try:
        check_python_version()
        se_root = resolve_se_root(args.se_root)
        result = run_se(se_root, ["doctor", "--json"], timeout=args.timeout)
        envelope = parse_envelope(result, "doctor")
        status, summary, findings, details = summarize(envelope)
        return make_report(
            STEP,
            status,
            project=se_root,
            summary=summary,
            findings=findings,
            evidence={
                "command": ["se", "doctor", "--json"],
                "exit_code": result["exit_code"],
                "envelope_status": envelope.get("status"),
                "stderr": result["stderr"].strip()[-2000:],
            },
            details=details,
        )
    except OperationalError as exc:
        return operational_report(STEP, exc)
    except Exception as exc:  # noqa: BLE001 - never let an adapter bug look like a PASS
        return operational_report(
            STEP,
            OperationalError(f"unexpected adapter error: {exc}", code="ADAPTER_ERROR"),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish se doctor findings as non-blocking CI information."
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
