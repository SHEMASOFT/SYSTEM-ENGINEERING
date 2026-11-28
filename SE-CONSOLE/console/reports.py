"""SE-CONSOLE :: allow-listed read-only report requests.

`actions.py` is the catalog for the one authenticated write surface. This
module is its read-only counterpart: it names the exact `se` argv shapes the
console may ask for, and refuses everything else before a subprocess exists.

`explore` is deliberately NOT here: it writes `discovery.json` and advances the
lifecycle from DRAFT to DISCOVERY, so it is a mutation despite its READ
execution intent. `plan` is here ONLY in its derivation form (`--project` plus
the `--json` that `se_cli.run_se` appends); `--create-tasks` and `--intent`
can never be supplied through this surface.
"""

from __future__ import annotations

import re
from typing import Any

_PROJECT_RE = re.compile(r"^PROJECTS/[A-Za-z0-9._\-/]+$")
_GATE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SCOPES = frozenset(
    {"identity", "work", "authority", "trace", "deep", "consistency", "conformance"}
)

#: report id -> (se verb, request param -> flag, required params, choices).
#: Order matters: it fixes the argv order so `se_cli` can re-parse it exactly.
REPORTS: dict[str, dict[str, Any]] = {
    "health": {
        "verb": "health",
        "params": {"project": "--project", "scope": "--scope"},
        "required": ("project",),
        "choices": {"scope": _SCOPES},
    },
    "verify": {
        "verb": "verify",
        "params": {"project": "--project"},
        "required": ("project",),
        "choices": {},
    },
    "gate": {
        "verb": "gate",
        "params": {"project": "--project", "gate": "--gate"},
        "required": ("project", "gate"),
        "choices": {},
    },
    "plan": {
        "verb": "plan",
        "params": {"project": "--project"},
        "required": ("project",),
        "choices": {},
    },
}

#: Verbs that look like reports but mutate canonical state. Kept explicit so a
#: future maintainer cannot add them by editing only the CLI allow-list.
REFUSED_VERBS = {
    "explore": "explore writes discovery.json and may advance the lifecycle",
}


class Refused(Exception):
    """The report request is malformed. Nothing is executed."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        raise Refused(f"{field} must be a short non-empty string")
    if value.startswith("--"):
        raise Refused(f"{field} cannot look like a flag")
    return value


def build_argv(report: str, params: Any) -> list[str]:
    """Validate a report request and return its exact `se` argv."""
    spec = REPORTS.get(report)
    if spec is None:
        raise Refused(f"report not in catalog: {report!r} (allowed: {sorted(REPORTS)})")
    if not isinstance(params, dict):
        raise Refused("params must be an object")

    unknown = sorted(set(params) - set(spec["params"]))
    if unknown:
        raise Refused(f"unknown params for {report}: {unknown}")
    missing = [key for key in spec["required"] if not params.get(key)]
    if missing:
        raise Refused(f"missing params for {report}: {missing}")

    argv = [spec["verb"]]
    for key, flag in spec["params"].items():
        if key not in params:
            continue
        value = _text(params[key], f"params.{key}")
        if key == "project":
            if not _PROJECT_RE.match(value) or ".." in value:
                raise Refused("project must be PROJECTS/... without '..'")
        elif key == "gate" and not _GATE_RE.match(value):
            raise Refused("gate must be a short alphanumeric id")
        choices = spec["choices"].get(key)
        if choices is not None and value not in choices:
            raise Refused(f"params.{key} must be one of {sorted(choices)}")
        argv += [flag, value]
    return argv


def _parse_pairs(args: list[str], spec: dict[str, Any]) -> dict[str, str]:
    """Re-parse an argv built by `build_argv`, refusing anything extra."""
    flag_to_key = {flag: key for key, flag in spec["params"].items()}
    out: dict[str, str] = {}
    index = 0
    while index < len(args):
        flag = args[index]
        key = flag_to_key.get(flag)
        if key is None or key in out or index + 1 >= len(args):
            raise Refused("unknown, repeated or dangling report flag")
        out[key] = args[index + 1]
        index += 2
    return out


def is_allowed_readonly(args: list[str]) -> bool:
    """True only for an argv that `build_argv` itself would have produced."""
    if not args or args[0] not in {s["verb"] for s in REPORTS.values()}:
        return False
    report = next(name for name, s in REPORTS.items() if s["verb"] == args[0])
    try:
        params = _parse_pairs(list(args[1:]), REPORTS[report])
        return build_argv(report, params) == list(args)
    except Refused:
        return False
