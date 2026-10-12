"""Command-line interface for the Master System reference implementation."""

from __future__ import annotations

import argparse

from . import commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="se",
        description="SYSTEM ENGINEERING reference CLI (v0.8.0)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a managed project workspace / bootstrap an OpenCode layer")
    p_init.add_argument("project", nargs="?", default=None,
                        help="Existing or new project directory to bootstrap (.opencode layer from PROJECT.json)")
    p_init.add_argument("--dir", default=None, help="Target project directory (create-manifest mode)")
    p_init.add_argument("--name", default=None, help="Project name (used when creating PROJECT.json)")
    p_init.add_argument("--owner", default=None, help="Project owner (used when creating PROJECT.json)")
    p_init.add_argument("--domains", default="software", help="Comma-separated domain ids")
    p_init.add_argument("--agents", default=None, help="Comma-separated agent roles to install (bootstrap)")
    p_init.add_argument("--skills", default=None, help="Comma-separated skill ids to install (bootstrap)")
    p_init.add_argument("--criticality", default="unknown", choices=["low", "medium", "high", "critical", "unknown"], help="Declared criticality; defaults to 'unknown' (never a silent factual default)")
    p_init.add_argument("--id", default=None, help="Explicit project_id (PRJ-...)")
    p_init.add_argument("--description", default="", help="Short project description")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing PROJECT.json")
    p_init.set_defaults(func=commands.cmd_init)

    p_explore = sub.add_parser("explore", help="Produce a discovery report")
    p_explore.add_argument("--project", required=True)
    p_explore.add_argument("--force", action="store_true")
    p_explore.set_defaults(func=commands.cmd_explore)

    p_plan = sub.add_parser("plan", help="Check coverage / scaffold tasks")
    p_plan.add_argument("--project", required=True)
    p_plan.add_argument("--create-tasks", action="store_true")
    p_plan.set_defaults(func=commands.cmd_plan)

    p_implement = sub.add_parser("implement", help="Report actionable tasks")
    p_implement.add_argument("--project", required=True)
    p_implement.set_defaults(func=commands.cmd_implement)

    p_verify = sub.add_parser("verify", help="Report verification readiness")
    p_verify.add_argument("--project", required=True)
    p_verify.set_defaults(func=commands.cmd_verify)

    p_review = sub.add_parser("review", help="Static review of artifacts")
    p_review.add_argument("--project", required=True)
    p_review.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_review.set_defaults(func=commands.cmd_review)

    p_release = sub.add_parser("release", help="Create a release artifact")
    p_release.add_argument("--project", required=True)
    p_release.add_argument("--version", required=True)
    p_release.add_argument("--scope", default="")
    p_release.add_argument("--approve", action="store_true")
    p_release.add_argument("--by", default="")
    p_release.set_defaults(func=commands.cmd_release)

    p_gate = sub.add_parser("gate", help="Evaluate a single gate")
    p_gate.add_argument("--project", required=True)
    p_gate.add_argument("--gate", required=True)
    p_gate.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_gate.set_defaults(func=commands.cmd_gate)

    p_transition = sub.add_parser("transition", help="Advance the project lifecycle through its gates")
    p_transition.add_argument("--project", required=True)
    p_transition.add_argument("--to", required=True, help="Target lifecycle state")
    p_transition.add_argument("--attest", default=None, help="Human attestation required for MANUAL gate conditions")
    p_transition.add_argument("--by", default=None, help="Who is performing the transition")
    p_transition.set_defaults(func=commands.cmd_transition)

    p_new = sub.add_parser("new", help="Create a record from its template")
    p_new.add_argument("record", choices=["objective", "requirement", "task", "artifact", "evidence", "acceptance", "decision"])
    p_new.add_argument("--project", required=True)
    p_new.add_argument("--title", default=None)
    p_new.add_argument("--description", default=None)
    p_new.add_argument("--status", default=None)
    p_new.add_argument("--type", default=None)
    p_new.add_argument("--priority", default=None)
    p_new.add_argument("--epistemic-status", dest="epistemic_status", default=None)
    p_new.add_argument("--rationale", default=None)
    p_new.add_argument("--objective", default=None)
    p_new.add_argument("--scope", default=None)
    p_new.add_argument("--kind", default=None)
    p_new.add_argument("--location", default=None)
    p_new.add_argument("--command", default=None)
    p_new.add_argument("--result", default=None)
    p_new.add_argument("--decided-by", dest="decided_by", default=None)
    p_new.add_argument("--authority", default=None)
    p_new.add_argument("--acceptance-criteria", dest="acceptance_criteria", default=None)
    p_new.add_argument("--produced-by", dest="produced_by", default=None)
    p_new.add_argument("--evidence", default=None)
    p_new.add_argument("--related-requirements", dest="related_requirements", default=None)
    p_new.add_argument("--related-tasks", dest="related_tasks", default=None)
    p_new.add_argument("--related-artifacts", dest="related_artifacts", default=None)
    p_new.add_argument("--related-decisions", dest="related_decisions", default=None)
    p_new.add_argument("--dependencies", default=None)
    p_new.add_argument("--category", default=None)
    p_new.add_argument("--context", default=None)
    p_new.add_argument("--problem", default=None)
    p_new.add_argument("--decision", default=None)
    p_new.add_argument("--reason", default=None)
    p_new.add_argument("--consequences", default=None)
    p_new.add_argument("--options", default=None)
    p_new.add_argument("--affected-components", dest="affected_components", default=None)
    p_new.set_defaults(func=commands.cmd_new)

    p_update = sub.add_parser("update", help="Apply a controlled mutation to an existing record")
    p_update.add_argument("record", choices=commands.RECORD_TYPES)
    p_update.add_argument("record_id")
    p_update.add_argument("--project", required=True)
    p_update.add_argument("--set", action="append", default=[], help="FIELD=VALUE (repeatable)")
    p_update.add_argument("--add", action="append", default=[], help="FIELD=VALUE append to a list (repeatable)")
    p_update.add_argument("--remove", action="append", default=[], help="FIELD=VALUE remove from a list (repeatable)")
    p_update.add_argument("--by", default=None, help="Human actor; required for controlled fields")
    p_update.set_defaults(func=commands.cmd_update)

    p_adapter = sub.add_parser("adapter", help="Distribution adapters")
    p_adapter_sub = p_adapter.add_subparsers(dest="adapter_command", required=True)
    p_opencode = p_adapter_sub.add_parser("opencode", help="Generate OpenCode assets from contracts")
    p_opencode.add_argument("--output", default=None, help="Output directory (default: <repo>/.opencode)")
    p_opencode.add_argument("--dry-run", action="store_true", help="Show the generation plan without writing files")
    p_opencode.set_defaults(func=commands.cmd_adapter_opencode)

    p_doctor = sub.add_parser("doctor", help="Validate the Master System")
    p_doctor.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_doctor.set_defaults(func=commands.cmd_doctor)

    p_validate = sub.add_parser("validate", help="Validate schemas/agents/domains and a project")
    p_validate.add_argument("--project", default=None)
    p_validate.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_validate.set_defaults(func=commands.cmd_validate)

p_capabilities = sub.add_parser("capabilities", help="Capability governance: registry, policy check and resolution")
    p_capabilities.add_argument("--check", action="store_true", help="Validate declared capability policies (canonical skills/agents + optional project/task)")
    p_capabilities.add_argument("--project", default=None, help="Project directory for policy check / resolved plan")
    p_capabilities.add_argument("--task", default=None, help="Task artifact id (TASK-xxxx) within --project for plan / check")
    p_capabilities.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope instead of human-readable output.")
    p_capabilities.set_defaults(func=commands.cmd_capabilities)

    p_health = sub.add_parser("health", help="Aggregate health status from existing checks (doctor, validate, capabilities, review)")
    p_health.add_argument("--project", required=True, help="Managed project workspace")
    p_health.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope instead of human-readable output")
    p_health.set_defaults(func=commands.cmd_health)

    p_context = sub.add_parser("context", help="Reconstruct the minimum relevant context (AUTO-02)")
    p_context.add_argument("--project", required=True, help="Managed project workspace")
    p_context.add_argument("--scope", default="identity", help="Context level: identity|work|authority|trace|deep (default: identity)")
    p_context.add_argument("--focus", default=None, help="Optional focus id (TASK-xxxx/REQ-xxxx/OBJ-xxxx/... or the project id)")
    p_context.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_context.set_defaults(func=commands.cmd_context)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        if getattr(args, "json", False):
            from .reporting import error_envelope, render_json

            print(render_json(error_envelope(getattr(args, "command", "unknown"), str(exc), status="BLOCKED")))
        else:
            print(f"FAIL: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        if getattr(args, "json", False):
            from .reporting import error_envelope, render_json

            print(render_json(error_envelope(getattr(args, "command", "unknown"), f"unexpected error: {exc}", status="FAIL")))
        else:
            print(f"FAIL: unexpected error: {exc}")
        return 1
