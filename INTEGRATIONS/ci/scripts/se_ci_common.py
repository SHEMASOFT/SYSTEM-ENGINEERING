"""Shared plumbing for the SYSTEM-ENGINEERING CI governance adapter.

The adapter is deliberately thin: it invokes the canonical ``se`` CLI, parses the
``se.report/1`` envelope and translates it into a CI verdict. It never evaluates a
gate condition, attests a manual condition or mutates project state.

Platform-neutral: Python 3.10+ standard library only. Commands are always passed
as an argv list through a shell-free subprocess call.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPORT_SCHEMA = "se-ci.report/1"
INTERFACE_VERSION = "1.0.0"

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_USAGE = 2
EXIT_OPERATIONAL = 3
EXIT_MANUAL_PENDING = 4

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_MANUAL_PENDING = "MANUAL_PENDING"
STATUS_OPERATIONAL_ERROR = "OPERATIONAL_ERROR"
STATUS_INFO = "INFO"

EXIT_FOR_STATUS = {
    STATUS_PASS: EXIT_OK,
    STATUS_INFO: EXIT_OK,
    STATUS_FAIL: EXIT_VALIDATION,
    STATUS_OPERATIONAL_ERROR: EXIT_OPERATIONAL,
    STATUS_MANUAL_PENDING: EXIT_MANUAL_PENDING,
}

BLOCKING_STATUSES = frozenset({STATUS_FAIL, STATUS_MANUAL_PENDING, STATUS_OPERATIONAL_ERROR})

MIN_PYTHON = (3, 10)


class OperationalError(RuntimeError):
    """A failure that prevents verification ("I could not check"), not a verdict."""

    def __init__(self, message: str, *, code: str = "OPERATIONAL"):
        super().__init__(message)
        self.code = code


def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        raise OperationalError(
            "Python {}.{} or newer is required (running {})".format(
                MIN_PYTHON[0], MIN_PYTHON[1], sys.version.split()[0]
            ),
            code="PYTHON_VERSION",
        )


def default_se_root() -> Path:
    """Return the SYSTEM-ENGINEERING checkout that contains this adapter."""
    return Path(__file__).resolve().parents[3]


def resolve_se_root(value=None, *, require_gate_model: bool = False) -> Path:
    root = Path(value).expanduser().resolve() if value else default_se_root()
    if not root.is_dir():
        raise OperationalError(f"SE root does not exist: {root}", code="SE_ROOT")
    if not (root / "SCRIPTS" / "se.py").is_file():
        raise OperationalError(
            f"SE root has no SCRIPTS/se.py: {root}", code="SE_ROOT"
        )
    if not (root / "VERSION").is_file():
        raise OperationalError(f"SE root has no VERSION file: {root}", code="SE_ROOT")
    if require_gate_model:
        for relative in ("CORE/lifecycle/lifecycle.json", "CORE/gates/gates.json"):
            if not (root / relative).is_file():
                raise OperationalError(
                    f"SE root has no {relative}: {root}", code="SE_CONTRACT"
                )
    return root


def resolve_project(value=None) -> Path:
    """Resolve the product project directory (default: current checkout root).

    ``--project`` accepts a directory or the ``PROJECT.json`` file itself. The
    directory must contain ``PROJECT.json``; nothing is inferred or created.
    """
    raw = Path(value) if value else Path.cwd()
    if raw.is_file():
        if raw.name != "PROJECT.json":
            raise OperationalError(
                f"--project file must be named PROJECT.json (got {raw.name})",
                code="PROJECT_PATH",
            )
        raw = raw.parent
    path = raw.expanduser().resolve()
    if not path.is_dir():
        raise OperationalError(f"project directory does not exist: {path}", code="PROJECT_PATH")
    if not (path / "PROJECT.json").is_file():
        raise OperationalError(
            f"no PROJECT.json in {path}; pass --project <product checkout>",
            code="PROJECT_PATH",
        )
    return path


def load_json(path: Path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_project(project: Path) -> dict:
    try:
        data = load_json(project / "PROJECT.json")
    except (OSError, json.JSONDecodeError) as exc:
        raise OperationalError(
            f"cannot read PROJECT.json in {project}: {exc}", code="PROJECT_MANIFEST"
        ) from exc
    if not isinstance(data, dict):
        raise OperationalError(
            f"PROJECT.json in {project} is not a JSON object", code="PROJECT_MANIFEST"
        )
    return data


def require_module(module: str, hint: str) -> None:
    """Fail operationally when a runtime dependency needed for verification is absent."""
    try:
        __import__(module)
    except Exception as exc:  # noqa: BLE001 - reported as an operational failure
        raise OperationalError(
            f"cannot verify: required dependency '{module}' is not importable ({exc}). {hint}",
            code="MISSING_DEPENDENCY",
        ) from exc


def run_se(se_root: Path, arguments: list, *, timeout: int = 300) -> dict:
    """Run the canonical ``se`` CLI. Returns argv, exit code and captured output."""
    argv = [sys.executable, str(se_root / "SCRIPTS" / "se.py"), *arguments]
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        completed = subprocess.run(
            argv,
            cwd=str(se_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise OperationalError(
            f"cannot execute the SE CLI ({argv[0]}): {exc}", code="SE_EXECUTION"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OperationalError(
            f"SE command timed out after {timeout}s: {' '.join(argv)}",
            code="SE_EXECUTION",
        ) from exc
    return {
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def parse_envelope(result: dict, operation: str) -> dict:
    """Parse a canonical ``se.report/1`` envelope from command output."""
    text = (result.get("stdout") or "").strip()
    if not text:
        raise OperationalError(
            f"'{operation}' produced no output (exit {result.get('exit_code')})",
            code="NO_ENVELOPE",
        )
    candidates = [text]
    first = text.find("{")
    if first > 0:
        candidates.append(text[first:])
    payload = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            break
        payload = None
    if not isinstance(payload, dict):
        raise OperationalError(
            f"'{operation}' output is not a JSON envelope (exit {result.get('exit_code')})",
            code="BAD_ENVELOPE",
        )
    if payload.get("report") != "se.report/1":
        raise OperationalError(
            f"'{operation}' did not return a se.report/1 envelope "
            f"(report={payload.get('report')!r})",
            code="BAD_ENVELOPE",
        )
    if operation and payload.get("operation") not in (operation, None):
        raise OperationalError(
            f"'{operation}' returned an envelope for operation {payload.get('operation')!r}",
            code="BAD_ENVELOPE",
        )
    return payload


def finding(severity: str, code: str, message: str) -> dict:
    return {"severity": severity, "code": code, "message": message}


def make_report(
    step: str,
    status: str,
    *,
    project=None,
    summary: str = "",
    findings=None,
    manual_conditions=None,
    gates=None,
    evidence=None,
    details=None,
) -> dict:
    exit_code = EXIT_FOR_STATUS.get(status)
    if exit_code is None:
        raise ValueError(f"unknown adapter status: {status}")
    return {
        "schema": REPORT_SCHEMA,
        "interface_version": INTERFACE_VERSION,
        "step": step,
        "status": status,
        "exit_code": exit_code,
        "blocking": status in BLOCKING_STATUSES,
        "project": str(project) if project is not None else None,
        "summary": summary,
        "findings": list(findings or []),
        "manual_conditions": list(manual_conditions or []),
        "gates": list(gates or []),
        "evidence": dict(evidence or {}),
        "details": dict(details or {}),
    }


def operational_report(
    step: str,
    error: OperationalError | str,
    *,
    project=None,
    details=None,
) -> dict:
    if isinstance(error, OperationalError):
        message, code = str(error), error.code
    else:
        message, code = str(error), "OPERATIONAL"
    return make_report(
        step,
        STATUS_OPERATIONAL_ERROR,
        project=project,
        summary=message,
        findings=[finding("FAIL", code, message)],
        details=details,
    )


def emit(report: dict, *, as_json: bool = False, output=None) -> int:
    """Write the report (optionally) and return its canonical exit code."""
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output:
        path = Path(output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    if as_json:
        sys.stdout.write(payload)
    else:
        sys.stdout.write(render_text(report))
    sys.stdout.flush()
    return int(report.get("exit_code", EXIT_OPERATIONAL))


def render_text(report: dict) -> str:
    lines = [
        f"[{report.get('status')}] se-ci {report.get('step')}: {report.get('summary')}"
    ]
    for item in report.get("findings") or []:
        lines.append(f"  {item.get('severity')} {item.get('code')}: {item.get('message')}")
    for condition in report.get("manual_conditions") or []:
        lines.append(
            "  MANUAL {} ({}): {}".format(
                condition.get("id"), condition.get("gate"), condition.get("description")
            )
        )
    return "\n".join(lines) + "\n"


def markdown_step(report: dict, heading: str = "###") -> str:
    icon = {
        STATUS_PASS: "PASS",
        STATUS_INFO: "INFO",
        STATUS_FAIL: "FAIL",
        STATUS_MANUAL_PENDING: "HUMAN APPROVAL REQUIRED",
        STATUS_OPERATIONAL_ERROR: "OPERATIONAL ERROR",
    }.get(report.get("status"), str(report.get("status")))
    lines = [
        f"{heading} {report.get('step')}: {icon}",
        "",
        report.get("summary") or "",
    ]
    findings = report.get("findings") or []
    if findings:
        lines.extend(["", "| Severity | Code | Detail |", "|---|---|---|"])
        for item in findings:
            detail = str(item.get("message") or "").replace("|", "\\|")
            lines.append(
                f"| {item.get('severity')} | `{item.get('code')}` | {detail} |"
            )
    manual = report.get("manual_conditions") or []
    if manual:
        lines.extend(
            [
                "",
                "Pending human attestation (CI never satisfies it):",
                "",
                "| Condition | Gate | Description |",
                "|---|---|---|",
            ]
        )
        for condition in manual:
            lines.append(
                "| `{}` | `{}` | {} |".format(
                    condition.get("id"),
                    condition.get("gate"),
                    str(condition.get("description") or "").replace("|", "\\|"),
                )
            )
    return "\n".join(lines).rstrip() + "\n"
