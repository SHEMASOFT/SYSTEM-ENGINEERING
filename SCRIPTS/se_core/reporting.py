"""Stable machine-readable reporting envelope (``se.report/1``) — AUTO-16.

This module is a READ-ONLY serialization surface for existing read-only commands.
It is a serializer, not a context loader: it never traverses a project, never reads
record bodies, and never mutates anything. It only shapes data that a command has
already computed from canonical state.

Contract: ``DOCS/adr/ADR-0022-readonly-aggregation-minimum-context.json`` and
``DOCS/reference/policies/MINIMUM_CONTEXT_POLICY.md``.

Envelope rules (see B0):
* root keys are stable and additive-only (never repurposed, never removed);
* ``details`` is the documented additive key that carries the operation-specific
  payload (the B0 project-state sections stay available but empty when not relevant);
* ``observation.observed_at`` is the ONLY intentionally non-deterministic field;
* output is deterministic for the same observed state (sorted object keys);
* no ANSI/control characters, no human UI decoration.
"""

from __future__ import annotations

import json

from .paths import now_utc

REPORT_ID = "se.report/1"

# Order is documentation only; rendering sorts keys for determinism.
ROOT_KEYS = (
    "report",
    "operation",
    "status",
    "scope",
    "project",
    "lifecycle",
    "gate",
    "objectives",
    "requirements",
    "tasks",
    "blockers",
    "dependencies",
    "authority",
    "capabilities",
    "artifacts",
    "evidence",
    "decisions",
    "acceptance",
    "runs",
    "next_action",
    "provenance",
    "epistemic",
    "warnings",
    "conflicts",
    "observation",
    "details",
)

# Sections that are arrays (default ``[]``); every other root key defaults to ``None``.
_ARRAY_KEYS = frozenset(
    {
        "objectives",
        "requirements",
        "tasks",
        "blockers",
        "dependencies",
        "artifacts",
        "evidence",
        "decisions",
        "acceptance",
        "runs",
        "warnings",
        "conflicts",
    }
)

# Documented status vocabulary. MANUAL is an existing gate status and is passed
# through unchanged rather than forced into this set.
STATUSES = ("PASS", "WARN", "FAIL", "BLOCKED", "UNKNOWN", "CONFLICT", "INFO", "MANUAL")


def wants_json(args) -> bool:
    """True when the caller explicitly requested JSON output."""
    return bool(getattr(args, "json", False))


def build_envelope(
    operation: str,
    status: str,
    *,
    scope: str = "identity",
    project=None,
    lifecycle=None,
    gate=None,
    objectives=None,
    requirements=None,
    tasks=None,
    blockers=None,
    dependencies=None,
    authority=None,
    capabilities=None,
    artifacts=None,
    evidence=None,
    decisions=None,
    acceptance=None,
    runs=None,
    next_action=None,
    provenance=None,
    epistemic=None,
    warnings=None,
    conflicts=None,
    details=None,
    observed_at=None,
    source_root=None,
    tool: str = "se",
) -> dict:
    """Build the ``se.report/1`` envelope with every stable root key present.

    Unused sections default to an empty array (array sections) or ``None``. No
    project traversal happens here; callers pass only what they already computed.
    """
    provided = {
        "project": project,
        "lifecycle": lifecycle,
        "gate": gate,
        "objectives": objectives,
        "requirements": requirements,
        "tasks": tasks,
        "blockers": blockers,
        "dependencies": dependencies,
        "authority": authority,
        "capabilities": capabilities,
        "artifacts": artifacts,
        "evidence": evidence,
        "decisions": decisions,
        "acceptance": acceptance,
        "runs": runs,
        "next_action": next_action,
        "provenance": provenance,
        "epistemic": epistemic,
        "warnings": warnings,
        "conflicts": conflicts,
        "details": details,
    }

    envelope = {
        "report": REPORT_ID,
        "operation": operation,
        "status": status,
        "scope": scope,
    }
    for key in ROOT_KEYS:
        if key in envelope:
            continue
        if key == "observation":
            envelope[key] = {
                "observed_at": observed_at or now_utc(),
                "tool": tool,
                "source_root": source_root,
            }
        elif key in _ARRAY_KEYS:
            envelope[key] = list(provided.get(key) or [])
        else:
            envelope[key] = provided.get(key)
    return envelope


def error_envelope(operation: str, message: str, *, status: str = "FAIL", scope: str = "identity", source_root=None) -> dict:
    """An envelope representing a command error (always valid, machine-readable)."""
    return build_envelope(
        operation,
        status,
        scope=scope,
        conflicts=[message],
        source_root=source_root,
    )


def render_json(envelope: dict) -> str:
    """Serialize an envelope to deterministic, ASCII-safe JSON (valid UTF-8)."""
    return json.dumps(envelope, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
