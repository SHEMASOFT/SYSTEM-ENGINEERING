"""SE-CONSOLE :: the v1 action catalog (DESIGN-5B §2.1).

The console owns no state and writes no canonical artifact: it **delegates**
to `se` and **records that it delegated**. `se` remains the only writer of SE
state. There is deliberately no generic "run any command" surface -- an action
must be in this catalog before anything is executed, and every input is
validated HARD before a subprocess exists.

Catalog (v1, exactly two):

    run.checkpoint   se run checkpoint --project <p> --run <RUN-id>
                     [--next-step ...] [--completed ...] [--pending ...]
                     [--blocked ...]
    run.close        se run close --project <p> --run <RUN-id> --state <STATE>
                     [--summary ...] [--by ...]

Validation is duplicated (not shared) with `se_cli` on purpose: this module
decides whether the REQUEST is well formed, `se_cli` refuses any ARGV shape
that is not one of the two approved shapes. Two independent checks, so a
mistake in one does not widen the surface.

Audit: every delegated action appends one JSON line to
``artifacts/actions.jsonl`` (actor, target, key, revision, argv, exit code,
result). `se` writes its own mutation log next to the project; neither log is
a source of truth for the other (DESIGN-5B §7).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any

CONSOLE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTIONS_LOG = os.path.join(CONSOLE_ROOT, "artifacts", "actions.jsonl")

#: §3: v1 is ONE local operator, declared explicitly -- never inferred from
#: the OS user. Real identities are step 6.
ACTOR = "se-console-local-operator"

#: Same notion of a safe project rel path that `console/api.py` uses: must
#: stay inside PROJECTS/ and must not traverse.
_PROJECT_RE = re.compile(r"^PROJECTS/[A-Za-z0-9._\-/]+$")
_RUN_RE = re.compile(r"^RUN-[0-9]{4,}$")
#: Idempotency keys and revisions travel on the argv, so their alphabet is
#: restricted to something that can never look like another flag (must start
#: with an alphanumeric character).
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")

_VALUE_MAX = 4096
CLOSE_STATES = ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED")

#: catalog id -> (se subcommand argv prefix, param -> flag, required params).
#: Order matters: it fixes the argv order, matching DESIGN-5B §2.1.
CATALOG: dict[str, dict[str, Any]] = {
    "run.checkpoint": {
        "argv": ("run", "checkpoint"),
        "params": {
            "next_step": "--next-step",
            "completed": "--completed",
            "pending": "--pending",
            "blocked": "--blocked",
        },
        "required": (),
    },
    "run.close": {
        "argv": ("run", "close"),
        "params": {
            "state": "--state",
            "summary": "--summary",
            "by": "--by",
        },
        "required": ("state",),
    },
    # The SAME engine contract the CLI drives -- the console implements no
    # transition of its own. It transcribes the MANUAL conditions the engine
    # reported (read_model's attention `action_params`) and delegates
    # `se transition`. `to` and the condition ids are deliberately NOT validated
    # for meaning here: that is the engine's job. Validating them here would make
    # the console a second, diverging implementation of SE semantics.
    "transition.attest": {
        "argv": ("transition",),
        "needs_run": False,
        "params": {
            "to": "--to",
            "attest": "--attest",
            "by": "--by",
        },
        "list_params": {"conditions": "--condition"},
        "required": ("to", "attest", "conditions"),
    },
}


class Refused(Exception):
    """The request is malformed or not in the catalog. Nothing is executed."""


class Plan:
    """A validated request, ready to be delegated.

    ``argv`` is exactly the argument list handed to `se` (without ``--json``,
    which the `run` subcommands do not accept).
    """

    __slots__ = ("action", "project", "run", "params", "idempotency_key",
                 "expected_revision", "argv")

    def __init__(
        self,
        action: str,
        project: str,
        run: str | None,
        params: dict[str, str],
        idempotency_key: str | None,
        expected_revision: str | None,
        argv: list[str],
    ) -> None:
        self.action = action
        self.project = project
        self.run = run
        self.params = params
        self.idempotency_key = idempotency_key
        self.expected_revision = expected_revision
        self.argv = argv


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise Refused(f"{field} must be a non-empty string")
    if len(value) > _VALUE_MAX:
        raise Refused(f"{field} is too long")
    if "\x00" in value:
        raise Refused(f"{field} contains a NUL byte")
    return value


def plan(payload: Any) -> Plan:
    """Validate a request body and build the `se` argv. Raises `Refused`."""
    if not isinstance(payload, dict):
        raise Refused("request body must be a JSON object")

    action = payload.get("action")
    spec = CATALOG.get(action) if isinstance(action, str) else None
    if spec is None:
        raise Refused(
            f"action not in catalog: {action!r} (allowed: {sorted(CATALOG)})"
        )

    project = payload.get("project")
    if not isinstance(project, str) or not _PROJECT_RE.match(project) or ".." in project:
        raise Refused("invalid project path: must match PROJECTS/... without '..'")
    run = payload.get("run")
    if spec.get("needs_run", True):
        if not isinstance(run, str) or not _RUN_RE.match(run):
            raise Refused("invalid run id: expected RUN-<4+ digits>")
    else:
        run = None

    raw_params = payload.get("params") or {}
    if not isinstance(raw_params, dict):
        raise Refused("params must be a JSON object")

    params: dict[str, str] = {}
    list_params: dict[str, list[str]] = {}
    spec_lists = spec.get("list_params", {})
    for key, value in raw_params.items():
        if not isinstance(key, str):
            raise Refused("param names must be strings")
        normalized = key.replace("-", "_")
        if normalized in spec_lists:
            if not isinstance(value, list) or not value:
                raise Refused(f"params.{key} must be a non-empty list")
            items = []
            for item in value:
                text = _text(item, f"params.{key}[]")
                if text.startswith("-"):
                    raise Refused(f"params.{key} must not look like a flag")
                items.append(text)
            list_params[normalized] = items
            continue
        flag = spec["params"].get(normalized)
        if flag is None:
            raise Refused(f"unknown param {key!r} for {action}")
        text = _text(value, f"params.{key}")
        if text.startswith("-"):
            raise Refused(f"params.{key} must not look like a flag")
        params[normalized] = text

    for required in spec["required"]:
        if required not in params and required not in list_params:
            raise Refused(f"{action} requires params.{required}")
    if action == "run.close" and params.get("state") not in CLOSE_STATES:
        raise Refused(
            f"invalid state {params.get('state')!r} for run.close "
            f"(expected {'|'.join(CLOSE_STATES)})"
        )

    idempotency_key = payload.get("idempotency_key")
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not _KEY_RE.match(idempotency_key):
            raise Refused("invalid idempotency_key: expected 1-128 chars of [A-Za-z0-9._:-]")
    expected_revision = payload.get("expected_revision")
    if expected_revision is not None:
        if not isinstance(expected_revision, str) or not _REVISION_RE.match(expected_revision):
            raise Refused("invalid expected_revision: expected a 64-char lowercase sha256 hex")

    argv: list[str] = [*spec["argv"], "--project", project]
    if spec.get("needs_run", True):
        argv.extend(["--run", run])
    for normalized, flag in spec["params"].items():
        if normalized in params:
            argv.extend([flag, params[normalized]])
    for normalized, flag in spec_lists.items():
        for item in list_params.get(normalized, []):
            argv.extend([flag, item])
    if idempotency_key is not None:
        argv.extend(["--idempotency-key", idempotency_key])
    if expected_revision is not None:
        argv.extend(["--expected-revision", expected_revision])

    return Plan(action, project, run, params, idempotency_key,
                expected_revision, argv)


def write_audit(plan: Plan, meta: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Append the delegation record for this action (create the file if new).

    The console records that it delegated; `se` remains the only writer of SE
    state. Any OSError propagates: the caller decides how to surface it, but
    the delegation itself has already happened and must not be hidden.
    """
    record = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "actor": ACTOR,
        "action": plan.action,
        "project": plan.project,
        "run": plan.run,
        "idempotency_key": plan.idempotency_key,
        "expected_revision": plan.expected_revision,
        "argv": ["se", *plan.argv],
        "exit_code": meta.get("exit_code"),
        "result": result,
    }
    os.makedirs(os.path.dirname(ACTIONS_LOG), exist_ok=True)
    with open(ACTIONS_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def audit_failure(exc: OSError) -> None:
    """Surface a failed audit write without inventing a second truth."""
    sys.stderr.write(f"[se-console] audit write failed: {exc}\n")
