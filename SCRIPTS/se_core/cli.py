"""Command-line interface for the Master System reference implementation."""

from __future__ import annotations

import argparse

from . import commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="se",
        description="SYSTEM ENGINEERING reference CLI (v0.10.0)",
        epilog="There is no `se console` command: the console is a separate, read-only web app "
               "in SE-CONSOLE/ (run `python -m console.server` from that directory).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
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

    # adopt
    p_adopt = sub.add_parser(
        "adopt",
        help="Adopt an existing/advanced project into the SE lifecycle (additive: writes PROJECT.json + workspace dirs, never overwrites project artifacts)",
    )
    p_adopt.add_argument("project", help="Existing project directory (absolute, or a name under PROJECTS/)")
    p_adopt.add_argument("--name", default=None, help="Project name (default: the directory name)")
    p_adopt.add_argument("--owner", default=None, help="Project owner (required)")
    p_adopt.add_argument("--domains", default="software", help="Comma-separated domain ids")
    p_adopt.add_argument("--criticality", default="unknown", choices=["low", "medium", "high", "critical", "unknown"], help="Declared criticality; defaults to 'unknown' (never a silent factual default)")
    p_adopt.add_argument("--type", default=None, choices=["greenfield", "brownfield"], help="Work type profile (default: brownfield, since the project already exists)")
    p_adopt.add_argument("--scale", default=None, choices=["small", "medium", "large"], help="Work scale profile; drives ceremony requirements")
    p_adopt.add_argument("--risk", default=None, choices=["low", "medium", "high"], help="Work risk profile; drives ceremony requirements")
    p_adopt.add_argument("--id", default=None, help="Explicit project_id (PRJ-...)")
    p_adopt.add_argument("--description", default="", help="Short project description")
    p_adopt.add_argument("--dry-run", dest="dry_run", action="store_true", help="Plan only; write nothing")
    p_adopt.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_adopt.set_defaults(func=commands.cmd_adopt)

    # explore
    p_explore = sub.add_parser("explore", help="Produce a discovery report")
    p_explore.add_argument("--project", required=True)
    p_explore.add_argument("--force", action="store_true")
    p_explore.set_defaults(func=commands.cmd_explore)

    # plan
    p_plan = sub.add_parser("plan", help="Check coverage / scaffold tasks; with --json derive an ordered se.plan/1 envelope (READ-ONLY)")
    p_plan.add_argument("--project", required=True)
    p_plan.add_argument("--create-tasks", action="store_true")
    p_plan.add_argument("--intent", default=None,
                        help="Explicit intent file (se.intent/1 intent payload) used to derive the plan")
    p_plan.add_argument("--json", action="store_true",
                        help="Emit a machine-readable se.plan/1 envelope (READ-ONLY derivation)")
    p_plan.set_defaults(func=commands.cmd_plan)

    # intent (AUTO-03)
    p_intent = sub.add_parser("intent", help="Normalize an explicit structured intent into a se.intent/1 envelope (READ-ONLY)")
    p_intent.add_argument("--project", required=True)
    p_intent.add_argument("--file", default=None,
                          help="Explicit intent JSON file (objective, context, scope, restrictions, success_criteria)")
    p_intent.add_argument("--objective", default=None,
                          help="Derive the intent from an existing OBJECTIVE artifact (OBJ-xxxx)")
    p_intent.add_argument("--json", action="store_true",
                          help="Emit a machine-readable se.intent/1 envelope")
    p_intent.set_defaults(func=commands.cmd_intent)

    # execute (AUTO-04)
    p_execute = sub.add_parser("execute", help="Execute tasks in topological order with authorization, evidence, fail-closed")
    p_execute.add_argument("--project", required=True)
    p_execute.add_argument("--task", default=None, help="Execute a single task by ID (default: all actionable tasks in topological order)")
    p_execute.add_argument("--dry-run", action="store_true", help="Simulate execution without mutating state")
    p_execute.add_argument("--force", action="store_true", help="Re-execute already DONE tasks")
    p_execute.add_argument("--continue-on-error", action="store_true", help="Continue executing remaining tasks after a failure (default: fail-closed)")
    p_execute.add_argument("--json", action="store_true", help="Emit a machine-readable se.execute/1 envelope")
    p_execute.set_defaults(func=commands.cmd_execute)

    # observe (AUTO-04)
    p_observe = sub.add_parser("observe", help="Observe execution state: IN_PROGRESS tasks, evidence, artifacts, receipts (READ-ONLY)")
    p_observe.add_argument("--project", required=True)
    p_observe.add_argument("--json", action="store_true", help="Emit a machine-readable se.observe/1 envelope")
    p_observe.set_defaults(func=commands.cmd_observe)

    # implement
    p_implement = sub.add_parser("implement", help="Report actionable tasks")
    p_implement.add_argument("--project", required=True)
    p_implement.set_defaults(func=commands.cmd_implement)

    # verify
    p_verify = sub.add_parser("verify", help="Report verification readiness")
    p_verify.add_argument("--project", required=True)
    p_verify.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_verify.set_defaults(func=commands.cmd_verify)

    # review
    p_review = sub.add_parser("review", help="Static review of artifacts")
    p_review.add_argument("--project", required=True)
    p_review.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_review.set_defaults(func=commands.cmd_review)

    # release
    p_release = sub.add_parser("release", help="Create a release artifact")
    p_release.add_argument("--project", required=True)
    p_release.add_argument("--version", required=True)
    p_release.add_argument("--scope", default="")
    p_release.add_argument("--approve", action="store_true")
    p_release.add_argument("--by", default="")
    p_release.set_defaults(func=commands.cmd_release)

    # gate
    p_gate = sub.add_parser("gate", help="Evaluate a single gate against a project")
    p_gate.add_argument("--project", required=True)
    p_gate.add_argument("--gate", required=True)
    p_gate.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_gate.set_defaults(func=commands.cmd_gate)

    # transition
    p_transition = sub.add_parser("transition", help="Advance the project lifecycle through its gates")
    p_transition.add_argument("--project", required=True)
    p_transition.add_argument("--to", required=True, help="Target lifecycle state")
    p_transition.add_argument("--attest", default=None, help="Human attestation required for MANUAL gate conditions")
    p_transition.add_argument("--by", default=None, help="Who is performing the transition")
    p_transition.add_argument("--condition", action="append", default=None,
                              help="MANUAL condition id being attested (repeatable, comma-separated accepted); "
                                   "omit to attest the whole set")
    p_transition.add_argument("--idempotency-key", dest="idempotency_key", default=None,
                              help="Replaying the same key returns the prior result instead of re-applying")
    p_transition.add_argument("--expected-revision", dest="expected_revision", default=None,
                              help="sha256 of PROJECT.json the caller saw; refuses before writing if it changed")
    p_transition.set_defaults(func=commands.cmd_transition)

    # har
    p_har = sub.add_parser("har", help="Human Action Request lifecycle: create, list, show, answer, cancel, expire")
    p_har_sub = p_har.add_subparsers(dest="har_subcommand", required=True)

    p_har_create = p_har_sub.add_parser("create", help="Create a HAR awaiting a human decision")
    p_har_create.add_argument("--project", required=True, help="Managed project workspace")
    p_har_create.add_argument("--requested-action", dest="requested_action", default=None,
                              help="What action is being requested of the human")
    p_har_create.add_argument("--condition", action="append", default=None,
                              help="MANUAL condition id being requested (repeatable, comma-separated accepted)")
    p_har_create.add_argument("--by", default=None, help="Who is creating the HAR")
    p_har_create.add_argument("--expires-at", dest="expires_at", default=None,
                              help="ISO 8601 timestamp after which an OPEN HAR becomes STALE")
    p_har_create.set_defaults(func=commands.cmd_har)

    p_har_list = p_har_sub.add_parser("list", help="List HARs for a project")
    p_har_list.add_argument("--project", required=True)
    p_har_list.add_argument("--state", default=None,
                            help="Filter by state: OPEN|ANSWERED|CANCELLED|EXPIRED|STALE")
    p_har_list.set_defaults(func=commands.cmd_har)

    p_har_show = p_har_sub.add_parser("show", help="Show a single HAR as JSON")
    p_har_show.add_argument("har_id")
    p_har_show.add_argument("--project", required=True)
    p_har_show.set_defaults(func=commands.cmd_har)

    p_har_answer = p_har_sub.add_parser("answer", help="Answer an OPEN HAR")
    p_har_answer.add_argument("har_id")
    p_har_answer.add_argument("--project", required=True)
    p_har_answer.add_argument("--answer", required=True, help="The human decision")
    p_har_answer.add_argument("--by", default=None, help="Who is answering")
    p_har_answer.set_defaults(func=commands.cmd_har)

    p_har_cancel = p_har_sub.add_parser("cancel", help="Cancel an OPEN HAR")
    p_har_cancel.add_argument("har_id")
    p_har_cancel.add_argument("--project", required=True)
    p_har_cancel.set_defaults(func=commands.cmd_har)

    p_har_expire = p_har_sub.add_parser("expire", help="Expire an OPEN HAR")
    p_har_expire.add_argument("har_id")
    p_har_expire.add_argument("--project", required=True)
    p_har_expire.set_defaults(func=commands.cmd_har)

    # resume
    p_resume = sub.add_parser("resume", help="Resume work from an ANSWERED HAR (dry-run)")
    p_resume.add_argument("har_id")
    p_resume.add_argument("--project", required=True)
    p_resume.add_argument("--by", default=None, help="Who is resuming the work")
    p_resume.set_defaults(func=commands.cmd_resume)

    # new
    p_new = sub.add_parser("new", help="Create a record from its template")
    p_new.add_argument("record", choices=["objective", "requirement", "task", "artifact", "evidence", "acceptance", "decision", "sdd", "odd", "rdd", "run"])
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

    # update
    p_update = sub.add_parser(
        "update",
        help="Apply a controlled mutation to an existing record, or update SE-owned MCP servers (omit the record)",
    )
    p_update.add_argument("record", nargs="?", choices=commands.RECORD_TYPES, default=None,
                          help="Record type to mutate; omit to run the SE lifecycle update")
    p_update.add_argument("record_id", nargs="?", default=None)
    p_update.add_argument("--project", default=None,
                          help="Target project (record mutation) or directory (lifecycle update; default: current directory)")
    p_update.add_argument("--set", action="append", default=[], help="FIELD=VALUE (repeatable)")
    p_update.add_argument("--add", action="append", default=[], help="FIELD=VALUE append to a list (repeatable)")
    p_update.add_argument("--remove", action="append", default=[], help="FIELD=VALUE remove from a list (repeatable)")
    p_update.add_argument("--by", default=None, help="Human actor; required for controlled fields")
    p_update.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="Lifecycle update: report changes without applying")
    p_update.add_argument("--json", action="store_true",
                          help="Lifecycle update: emit a machine-readable se.report/1 envelope")
    p_update.set_defaults(func=commands.cmd_update)

    # run
    p_run = sub.add_parser("run", help="RUN artifact lifecycle: start, checkpoint, close")
    p_run_sub = p_run.add_subparsers(dest="run_command", required=True)

    p_run_start = p_run_sub.add_parser("start", help="Start a RUN: capture the runtime identity and record the intent")
    p_run_start.add_argument("--project", required=True, help="Managed project workspace")
    p_run_start.add_argument("--objective", default=None, help="Objective of this run")
    p_run_start.add_argument("--scope", default=None, help="Scope of this run")
    p_run_start.add_argument("--agent", default=None, help="Agent name whose contract contributes to the runtime capture")
    p_run_start.add_argument("--author", default=None, help="Who is starting the run (default: project owner)")
    p_run_start.add_argument("--task", default=None, help="TASK-id[,..] to record in execution.tasks")
    p_run_start.add_argument("--idempotency-key", dest="idempotency_key", default=None, help="Replay-safe key: if already applied, the command is a no-op returning 0")
    p_run_start.set_defaults(func=commands.cmd_run_start)

    p_run_checkpoint = p_run_sub.add_parser("checkpoint", help="Record a progress checkpoint on an existing RUN")
    p_run_checkpoint.add_argument("--project", required=True, help="Managed project workspace")
    p_run_checkpoint.add_argument("--run", required=True, help="RUN id (RUN-xxxx)")
    p_run_checkpoint.add_argument("--next-step", dest="next_step", default=None, help="Next step after this checkpoint")
    p_run_checkpoint.add_argument("--completed", default=None, help="Comma-separated ids completed so far")
    p_run_checkpoint.add_argument("--pending", default=None, help="Comma-separated ids still pending")
    p_run_checkpoint.add_argument("--blocked", default=None, help="Comma-separated ids blocked")
    p_run_checkpoint.add_argument("--state", default=None, help="State to record on the checkpoint")
    p_run_checkpoint.add_argument("--idempotency-key", dest="idempotency_key", default=None, help="Replay-safe key: if already applied, the checkpoint is a no-op returning 0")
    p_run_checkpoint.add_argument("--expected-revision", dest="expected_revision", default=None, help="sha256 of the run file's raw bytes; refuse to write when it differs")
    p_run_checkpoint.set_defaults(func=commands.cmd_run_checkpoint)

    p_run_close = p_run_sub.add_parser("close", help="Close a RUN with a final state")
    p_run_close.add_argument("--project", required=True, help="Managed project workspace")
    p_run_close.add_argument("--run", required=True, help="RUN id (RUN-xxxx)")
    p_run_close.add_argument("--state", required=True, help="Final state: COMPLETED|FAILED|BLOCKED|CANCELLED")
    p_run_close.add_argument("--summary", default=None, help="Closing summary (recorded in recovery.notes)")
    p_run_close.add_argument("--by", default=None, help="Human actor closing the run")
    p_run_close.add_argument("--idempotency-key", dest="idempotency_key", default=None, help="Replay-safe key: if already applied, the close is a no-op returning 0")
    p_run_close.add_argument("--expected-revision", dest="expected_revision", default=None, help="sha256 of the run file's raw bytes; refuse to write when it differs")
    p_run_close.set_defaults(func=commands.cmd_run_close)

    # adapter
    p_adapter = sub.add_parser("adapter", help="Distribution adapters")
    p_adapter_sub = p_adapter.add_subparsers(dest="adapter_command", required=True)
    p_opencode = p_adapter_sub.add_parser("opencode", help="Generate OpenCode assets from contracts")
    p_opencode.add_argument("--output", default=None, help="Output directory (default: <repo>/.opencode)")
    p_opencode.add_argument("--dry-run", action="store_true", help="Show the generation plan without writing files")
    p_opencode.set_defaults(func=commands.cmd_adapter_opencode)

    p_claude = p_adapter_sub.add_parser(
        "claude-code", help="Generate Claude Code assets (.claude/ + .mcp.json + CLAUDE.md)"
    )
    p_claude.add_argument("--output", default=None, help="Output directory (default: repo root)")
    p_claude.add_argument("--dry-run", action="store_true", help="Show the generation plan without writing files")
    p_claude.set_defaults(func=commands.cmd_adapter_claude_code)

    p_codex = p_adapter_sub.add_parser(
        "codex", help="Generate Codex assets (.codex/ + AGENTS.md)"
    )
    p_codex.add_argument("--output", default=None, help="Output directory (default: repo root)")
    p_codex.add_argument("--dry-run", action="store_true", help="Show the generation plan without writing files")
    p_codex.set_defaults(func=commands.cmd_adapter_codex)

    p_adapter_all = p_adapter_sub.add_parser("all", help="Generate every runtime adapter")
    p_adapter_all.add_argument("--output", default=None, help="Output directory (default: repo root)")
    p_adapter_all.add_argument("--dry-run", action="store_true", help="Show the generation plan without writing files")
    p_adapter_all.set_defaults(func=commands.cmd_adapter_all)

    # coverage
    p_coverage = sub.add_parser("coverage", help="Document coverage baseline (governed)")
    p_coverage_sub = p_coverage.add_subparsers(dest="coverage_command", required=True)
    p_rebase = p_coverage_sub.add_parser(
        "rebase",
        help="Rebase the coverage baseline after published docs change (journalled)",
    )
    p_rebase.add_argument(
        "--reason", required=True,
        help="Why the baseline changes; recorded in the ledger (a rebase is never anonymous)",
    )
    p_rebase.add_argument(
        "--by", default="operator", help="Actor recorded in the ledger (default: operator)",
    )
    p_rebase.set_defaults(func=commands.cmd_coverage_rebase)

    # install
    p_install = sub.add_parser(
        "install",
        help="Operator setup: detect the OS, preflight dependencies, register MCP servers in the runtime",
    )
    p_install.add_argument("--project", default=".", help="Target project directory (default: current directory)")
    p_install.add_argument("--global", action="store_true",
                           help="Register into the user config instead of the project config")
    install_group = p_install.add_mutually_exclusive_group()
    install_group.add_argument("--all", action="store_true", help="Register every MCP server (default)")
    install_group.add_argument("--with", dest="with_", default=None,
                               help="Comma-separated list of MCP servers to register (e.g. engram,context7)")
    p_install.add_argument("--no-register", dest="no_register", action="store_true",
                           help="Preflight and plan only; perform no registration")
    p_install.add_argument("--generate-adapter", dest="generate_adapter", action="store_true",
                           help="Optionally generate the OpenCode adapter for the target project")
    p_install.add_argument("--env-target", dest="env_target", default="auto",
                           choices=["auto", "windows", "wsl", "linux", "macos"],
                           help="Runtime environment to target when resolving paths "
                                "(default: auto = this host; wsl translates Windows paths to /mnt/<drive>)")
    p_install.add_argument("--bootstrap", action="store_true",
                           help="Run the unified SE installer (se-installer) to install SE Core, Console, MCPs, runtimes, and generate runtime configs before MCP registration")
    p_install.add_argument("--bootstrap-components", dest="bootstrap_components", default=None,
                           help="Comma-separated component IDs for --bootstrap (default: recommended)")
    p_install.add_argument("--bootstrap-runtimes", dest="bootstrap_runtimes", default=None,
                           help="Comma-separated runtimes for --bootstrap (default: opencode)")
    p_install.add_argument("--dry-run", dest="dry_run", action="store_true",
                           help="Plan only; write nothing")
    p_install.add_argument("--json", action="store_true",
                           help="Emit a machine-readable se.report/1 envelope")
    p_install.set_defaults(func=commands.cmd_install)

    # sync
    p_sync = sub.add_parser(
        "sync",
        help="Reconcile declared MCP servers with the runtime config (register missing, never touch foreign entries)",
    )
    p_sync.add_argument("--project", default=".", help="Target project directory (default: current directory)")
    p_sync.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Report the reconciliation without registering anything")
    p_sync.add_argument("--json", action="store_true",
                        help="Emit a machine-readable se.report/1 envelope")
    p_sync.set_defaults(func=commands.cmd_sync)

    # uninstall
    p_uninstall = sub.add_parser(
        "uninstall",
        help="Remove only SE-managed MCP servers (plan by default; use --apply to perform)",
    )
    p_uninstall.add_argument("--project", default=".", help="Target project directory (default: current directory)")
    p_uninstall.add_argument("--apply", action="store_true",
                             help="Perform the removal (default is a plan-only dry-run)")
    p_uninstall.add_argument("--dry-run", dest="dry_run", action="store_true",
                             help="Force a plan-only run (the default)")
    p_uninstall.add_argument("--json", action="store_true",
                             help="Emit a machine-readable se.report/1 envelope")
    p_uninstall.set_defaults(func=commands.cmd_uninstall)

    # doctor
    p_doctor = sub.add_parser("doctor", help="Validate the Master System")
    p_doctor.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_doctor.set_defaults(func=commands.cmd_doctor)

    # ceremony
    p_ceremony = sub.add_parser(
        "ceremony",
        help="Show the effective ceremony requirements for a project's declared work profile, and whether they are met",
    )
    p_ceremony.add_argument("--project", required=True, help="Managed project workspace")
    p_ceremony.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_ceremony.set_defaults(func=commands.cmd_ceremony)

# validate
    p_validate = sub.add_parser("validate", help="Validate schemas/agents/domains and a project")
    p_validate.add_argument("--project", default=None)
    p_validate.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_validate.set_defaults(func=commands.cmd_validate)


    # capabilities
    p_capabilities = sub.add_parser("capabilities", help="Capability governance: registry, policy check and resolution")
    p_capabilities.add_argument("--check", action="store_true", help="Validate declared capability policies (canonical skills/agents + optional project/task)")
    p_capabilities.add_argument("--project", default=None, help="Project directory for policy check / resolved plan")
    p_capabilities.add_argument("--task", default=None, help="Task artifact id (TASK-xxxx) within --project for plan / check")
    p_capabilities.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope instead of human-readable output.")
    p_capabilities.set_defaults(func=commands.cmd_capabilities)



    # skill

    p_skill = sub.add_parser("skill", help="Skill discovery and management")

    p_skill_sub = p_skill.add_subparsers(dest="skill_command", required=True)



    p_discover = p_skill_sub.add_parser("discover", help="Discover skills matching project capabilities")

    p_discover.add_argument("--project", required=True, help="Managed project workspace")

    p_discover.add_argument("--capability", action="append", help="Capability to match (repeatable)")

    p_discover.add_argument("--profile", default=None, help="Project profile JSON for capability inference")

    p_discover.add_argument("--max-candidates", type=int, default=10, help="Max candidates to return")

    p_discover.add_argument("--include-experimental", action="store_true", help="Include experimental skills")

    p_discover.add_argument("--require-approval", action="store_true", help="Only show skills requiring approval")

    p_discover.add_argument("--by", default=None, help="Requesting actor")

    p_discover.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")

    p_discover.set_defaults(func=commands.cmd_skill)



    # memory

    p_memory = sub.add_parser("memory", help="Memory operations: add, query, get, link, update, supersede")

    p_memory_sub = p_memory.add_subparsers(dest="memory_command", required=True)



    p_mem_add = p_memory_sub.add_parser("add", help="Add a new memory record")

    p_mem_add.add_argument("--project", required=True, help="Managed project workspace")

    p_mem_add.add_argument("--type", required=True, help="Memory type (decision, architecture, discovery, constraint, capability, verification, checkpoint, relationship)")

    p_mem_add.add_argument("--content", required=True, help="Memory content as JSON")

    p_mem_add.add_argument("--scope", default="project", choices=["project", "global", "architecture"], help="Memory scope")

    p_mem_add.add_argument("--tags", default=None, help="Comma-separated tags")

    p_mem_add.add_argument("--confidence", type=float, default=1.0, help="Confidence score (0-1)")

    p_mem_add.add_argument("--related", default=None, help="Comma-separated related memory IDs")

    p_mem_add.add_argument("--supersedes", default=None, help="Memory ID this supersedes")

    p_mem_add.add_argument("--by", default=None, help="Author")

    p_mem_add.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")

    p_mem_add.set_defaults(func=commands.cmd_memory)



    p_mem_query = p_memory_sub.add_parser("query", help="Query memories with filters")

    p_mem_query.add_argument("--project", default=None, help="Managed project workspace (optional for cross-project)")

    p_mem_query.add_argument("--type", default=None, help="Comma-separated memory types to filter")

    p_mem_query.add_argument("--tags", default=None, help="Comma-separated tags to filter")

    p_mem_query.add_argument("--by", default=None, help="Filter by author")

    p_mem_query.add_argument("--since", default=None, help="Filter by created after (ISO date)")

    p_mem_query.add_argument("--until", default=None, help="Filter by created before (ISO date)")

    p_mem_query.add_argument("--tags-mode", choices=["any", "all"], default="any", help="Tag match mode")

    p_mem_query.add_argument("--limit", type=int, default=50, help="Max results")

    p_mem_query.add_argument("--offset", type=int, default=0, help="Offset for pagination")

    p_mem_query.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")

    p_mem_query.set_defaults(func=commands.cmd_memory)



    p_mem_get = p_memory_sub.add_parser("get", help="Get a single memory by ID")

    p_mem_get.add_argument("--memory-id", required=True, help="Memory ID (MEM-XXXX)")

    p_mem_get.add_argument("--project", default=None, help="Managed project workspace (optional)")

    p_mem_get.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")

    p_mem_get.set_defaults(func=commands.cmd_memory)



    p_mem_link = p_memory_sub.add_parser("link", help="Link two memories")

    p_mem_link.add_argument("--memory-id", required=True, help="Source memory ID")

    p_mem_link.add_argument("--related-id", required=True, help="Related memory ID")

    p_mem_link.add_argument("--relation", default="related", choices=["related", "supersedes", "superseded_by"], help="Relation type")

    p_mem_link.set_defaults(func=commands.cmd_memory)



    p_mem_update = p_memory_sub.add_parser("update", help="Update a memory record")

    p_mem_update.add_argument("--memory-id", required=True, help="Memory ID to update")

    p_mem_update.add_argument("--project", default=None, help="Managed project workspace")

    p_mem_update.add_argument("--updates", required=True, help="Updates as JSON")

    p_mem_update.set_defaults(func=commands.cmd_memory)



    p_mem_supersede = p_memory_sub.add_parser("supersede", help="Mark a memory as superseded by another")

    p_mem_supersede.add_argument("--memory-id", required=True, help="Old memory ID to supersede")

    p_mem_supersede.add_argument("--new-id", required=True, help="New memory ID that supersedes")

    p_mem_supersede.add_argument("--project", required=True, help="Managed project workspace")

    p_mem_supersede.set_defaults(func=commands.cmd_memory)



    # context

    # context
    p_context = sub.add_parser("context", help="Reconstruct the minimum relevant context (AUTO-02)")
    p_context.add_argument("--project", required=True, help="Managed project workspace")
    p_context.add_argument("--scope", default="identity", help="Context level: identity|work|authority|trace|deep (default: identity)")
    p_context.add_argument("--focus", default=None, help="Optional focus id (TASK-xxxx/REQ-xxxx/OBJ-xxxx/... or the project id)")
    p_context.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_context.set_defaults(func=commands.cmd_context)

    # handoff
    p_handoff = sub.add_parser("handoff", help="Create or load a HANDOFF.json artifact for project continuity")
    p_handoff_sub = p_handoff.add_subparsers(dest="subcommand", required=True)
    p_handoff_create = p_handoff_sub.add_parser("create", help="Generate HANDOFF.json from current project state")
    p_handoff_create.add_argument("--project", required=True, help="Managed project workspace")
    p_handoff_create.add_argument("--scope", default="trace", help="Context level: identity|work|authority|trace|deep (default: trace)")
    p_handoff_create.add_argument("--focus", default=None, help="Optional focus id for context snapshot")
    p_handoff_create.add_argument("--by", default=None, help="Author of handoff")
    p_handoff_create.add_argument("--force", action="store_true", help="Overwrite existing HANDOFF.json")
    p_handoff_create.add_argument("--json", action="store_true", help="Emit machine-readable se.report/1 envelope")
    p_handoff_create.set_defaults(func=commands.cmd_handoff)
    p_handoff_load = p_handoff_sub.add_parser("load", help="Load and validate a HANDOFF.json artifact")
    p_handoff_load.add_argument("--project", required=True, help="Managed project workspace")
    p_handoff_load.add_argument("--file", default=None, help="Path to HANDOFF.json (default: <project>/HANDOFF.json)")
    p_handoff_load.add_argument("--json", action="store_true", help="Emit machine-readable se.report/1 envelope")
    p_handoff_load.set_defaults(func=commands.cmd_handoff)

    # archive
    p_archive = sub.add_parser("archive", help="Create a verified archive bundle of the project")
    p_archive.add_argument("--project", required=True, help="Managed project workspace")
    p_archive.add_argument("--output", default=None, help="Output archive path (default: <cwd>/<project_id>-<version>-<date>.tar.gz)")
    p_archive.add_argument("--by", default=None, help="Author of archive")
    p_archive.add_argument("--force", action="store_true", help="Archive even if validation fails")
    p_archive.add_argument("--json", action="store_true", help="Emit machine-readable se.report/1 envelope")
    p_archive.set_defaults(func=commands.cmd_archive)

    # restore
    p_restore = sub.add_parser("restore", help="Restore a project from an archive bundle")
    p_restore.add_argument("archive", help="Path to archive .tar.gz file")
    p_restore.add_argument("--target", default=None, help="Target directory (default: <cwd>/restored)")
    p_restore.add_argument("--force", action="store_true", help="Overwrite existing target / ignore hash mismatches")
    p_restore.add_argument("--json", action="store_true", help="Emit machine-readable se.report/1 envelope")
    p_restore.set_defaults(func=commands.cmd_restore)



    # status

    p_status = sub.add_parser("status", help="Aggregate project status: validate, gates, capabilities, memory (--doctor for canonical, --deep for doc scans)")

    p_status.add_argument("--project", required=True, help="Managed project workspace")

    p_status.add_argument("--gate", default=None, help="Evaluate a specific gate (default: all)")

    p_status.add_argument("--doctor", action="store_true", help="Include full canonical doctor checks (slow on DrvFs)")

    p_status.add_argument("--deep", action="store_true", help="Include deep document scans (slow on DrvFs)")

    p_status.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")

    p_status.set_defaults(func=commands.cmd_status)





    # orchestrate

    p_orchestrate = sub.add_parser("orchestrate", help="Workflow orchestration: create, execute, list")

    p_orchestrate_sub = p_orchestrate.add_subparsers(dest="orchestrate_command", required=True)



    p_orch_create = p_orchestrate_sub.add_parser("create", help="Create a new workflow definition")

    p_orch_create.add_argument("--project", required=True, help="Managed project workspace")

    p_orch_create.add_argument("--name", required=True, help="Workflow name")

    p_orch_create.add_argument("--description", default="", help="Workflow description")

    p_orch_create.add_argument("--nodes", required=True, help="Nodes JSON file (array of node definitions)")

    p_orch_create.add_argument("--edges", default=None, help="Edges JSON file (array of edge definitions)")

    p_orch_create.add_argument("--gates", default=None, help="Gates JSON file (array of gate assignments)")

    p_orch_create.add_argument("--json", action="store_true", help="Emit machine-readable se.report/1 envelope")

    p_orch_create.set_defaults(func=commands.cmd_orchestrate)



    p_orch_execute = p_orchestrate_sub.add_parser("execute", help="Execute a workflow")

    p_orch_execute.add_argument("--workflow", required=True, help="Workflow ID (WF-XXXX)")

    p_orch_execute.add_argument("--project", required=True, help="Managed project workspace")

    p_orch_execute.add_argument("--execution-id", default=None, help="Explicit execution ID (auto-generated if omitted)")

    p_orch_execute.add_argument("--start-node", default=None, help="Node ID to start execution from (for resume)")

    p_orch_execute.add_argument("--dry-run", action="store_true", help="Validate and plan only, don't execute")

    p_orch_execute.add_argument("--json", action="store_true", help="Emit machine-readable se.report/1 envelope")

    p_orch_execute.set_defaults(func=commands.cmd_orchestrate)



    p_orch_list = p_orchestrate_sub.add_parser("list", help="List workflows in a project")

    p_orch_list.add_argument("--project", required=True, help="Managed project workspace")

    p_orch_list.add_argument("--json", action="store_true", help="Emit machine-readable se.report/1 envelope")

    p_orch_list.set_defaults(func=commands.cmd_orchestrate)

    # intelligence
    p_intel = sub.add_parser("intelligence", help="Integration layer: skill discovery + memory + orchestration plan + gates (READ-ONLY)")
    p_intel.add_argument("--project", required=True, help="Managed project workspace")
    p_intel.add_argument("--capability", action="append", help="Capability to match (repeatable; inferred if omitted)")
    p_intel.add_argument("--workflow", default=None, help="Workflow ID (WF-XXXX) to plan (dry-run)")
    p_intel.add_argument("--by", default=None, help="Requesting actor")
    p_intel.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope")
    p_intel.set_defaults(func=commands.cmd_intelligence)

    # health
    p_health = sub.add_parser("health", help="Aggregate health status from existing checks (doctor, validate, capabilities, review)")
    p_health.add_argument("--project", required=True, help="Managed project workspace")
    p_health.add_argument("--json", action="store_true", help="Emit a machine-readable se.report/1 envelope instead of human-readable output")
    p_health.set_defaults(func=commands.cmd_health)

    # auto
    p_auto = sub.add_parser("auto", help="Deterministic decision engine: consumes health and emits next-action decision (se.auto/1)")
    p_auto.add_argument("--project", required=True, help="Managed project workspace")
    p_auto.add_argument("--json", action="store_true", help="Emit a machine-readable se.auto/1 envelope instead of human-readable output")
    p_auto.set_defaults(func=commands.cmd_auto)

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


if __name__ == "__main__":
    raise SystemExit(main())