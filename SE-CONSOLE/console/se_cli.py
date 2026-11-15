"""SE-CONSOLE :: read-only bridge to the SYSTEM-ENGINEERING `se` CLI.

The console NEVER re-implements SE governance. Every verdict (gate status,
review findings, validation, capability resolution, context reconstruction)
is obtained by invoking the existing `se` CLI and parsing its
``se.report/1`` envelope verbatim.

HARD RULES enforced here:
  * READ-ONLY command allow-list. Mutating commands (new, update, transition,
    release, init, explore, plan) are refused, not merely unused.
  * ACTION allow-list, separate from the read-only one: only the two argv
    shapes of DESIGN-5B §2.1 (`run checkpoint`, `run close`) may be delegated
    a write, and each shape is re-parsed here so a caller cannot smuggle an
    extra subcommand or flag past `console/actions.py`.
  * The SE root is opened read-only by the console itself and is never
    written directly: state changes happen only inside `se`, through the
    action allow-list below.
  * Envelopes are relayed verbatim: no reshaping, no key addition/removal.
  * A failure or timeout degrades to an explicit UNKNOWN observation; it is
    never silently swallowed and never faked.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

_CONSOLE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Canonical SE root. When vendored, this console lives at <repo>/SE-CONSOLE and
#: the repository root is its parent (`SE-CONSOLE/..`); SE_ROOT may still be
#: overridden via the environment (the old hardcoded Windows path and the
#: sibling-checkout assumption both broke rooting off Windows / when vendored).
SE_ROOT = os.environ.get("SE_ROOT") or os.path.dirname(_CONSOLE_ROOT)
SE_ENTRY = os.path.join(SE_ROOT, "SCRIPTS", "se.py")

#: Windows-only. A process with NO console makes every child console process
#: allocate a NEW console window -- and `se` is invoked through
#: ``sys.executable``, i.e. a console application. A console started detached
#: (e.g. by ``scripts/dev_console.py``) would therefore pop one window per
#: invocation: two for ``/api/system`` (``se doctor`` + ``se capabilities``) and
#: nine for ``/api/gates``. ``CREATE_NO_WINDOW`` keeps the child consoles
#: invisible, with no console at all being created. It is 0 on other platforms,
#: where the flag does not exist and ``creationflags`` must stay 0.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

#: The only `se` subcommands this console may ever invoke.
#: Every entry here is declared ``mutates: false`` in COMMANDS/commands.json.
READ_ONLY_COMMANDS = frozenset(
    {
        "doctor",
        "validate",
        "review",
        "gate",
        "capabilities",
        "context",
        "implement",  # execution_intent REPORT, mutates=false
        # CMD-0016 `health`: added in SE-AUTOMATION-001C. Admitted only after
        # reading its declaration in COMMANDS/commands.json:
        #   "mutates": false, "execution_intent": "READ",
        #   "permissions": ["READ","ANALYZE"], "implemented": true
        # It aggregates doctor/validate/capabilities/review. The console relays
        # its envelope; it does not re-derive health from it.
        "health",
        # P3-B.1: memory read-only subcommands (get, query, search, gc dry-run)
        "memory",
    }
)

#: Explicitly refused, so a future caller cannot widen the surface by accident.
FORBIDDEN_COMMANDS = frozenset(
    {"init", "explore", "new", "update", "transition", "plan", "release"}
)

#: ACTION allow-list (DESIGN-5B §2.1). Deliberately SEPARATE from
#: READ_ONLY_COMMANDS: a read-only verb and an approved write are different
#: promises, and neither list can be widened by editing the other. Checked by
#: `run_se` itself against the fully parsed argv -- not just `args[0]` -- so a
#: caller cannot pass `run checkpoint ... --some-other-flag` through.
#:
#: Required flags are mandatory, allowed flags are optional; unknown flags,
#: repeated flags, flag-looking values and odd trailing tokens all refuse.
ACTION_ALLOWLIST: dict[str, dict[str, Any]] = {
    "run.checkpoint": {
        "prefix": ("run", "checkpoint"),
        "required": frozenset({"--project", "--run"}),
        "allowed": frozenset(
            {
                "--project",
                "--run",
                "--next-step",
                "--completed",
                "--pending",
                "--blocked",
                "--idempotency-key",
                "--expected-revision",
            }
        ),
    },
    "run.close": {
        "prefix": ("run", "close"),
        "required": frozenset({"--project", "--run", "--state"}),
        "allowed": frozenset(
            {
                "--project",
                "--run",
                "--state",
                "--summary",
                "--by",
                "--idempotency-key",
                "--expected-revision",
            }
        ),
    },
    "transition.attest": {
        "prefix": ("transition",),
        "required": frozenset({"--project", "--to", "--attest", "--condition"}),
        "allowed": frozenset(
            {
                "--project",
                "--to",
                "--attest",
                "--by",
                "--condition",
                "--idempotency-key",
                "--expected-revision",
            }
        ),
        # `--condition` names ONE condition per occurrence, so it must be
        # repeatable while every other flag stays single-valued.
        "repeatable": frozenset({"--condition"}),
    },
    # P3-B.1 TTL/GC: garbage collect expired memories (mutating when not dry-run)
    "memory.gc": {
        "prefix": ("memory", "gc"),
        "required": frozenset({"--project"}),
        "allowed": frozenset(
            {
                "--project",
                "--older-than-days",
                "--tags",
                "--state",
                "--dry-run",
                "--json",
            }
        ),
    },
}

DEFAULT_TIMEOUT = 60

#: TTL for the engine liveness probe. Liveness is not governance, so a short
#: cache is acceptable; it exists only to avoid a subprocess per /api/health.
PROBE_TTL_SECONDS = 15
_PROBE_CACHE: dict[str, Any] = {"value": None, "at": 0.0}


class SeError(RuntimeError):
    """Raised when the SE CLI cannot be invoked or its output is unusable."""


def _unknown(operation: str, reason: str) -> dict[str, Any]:
    """Build an UNKNOWN observation in the shape of an se.report/1 envelope.

    The console must be able to render a degraded state honestly, so failure is
    modelled as data (status UNKNOWN + the reason in `warnings`) rather than
    swallowed. Root keys are NOT fabricated: we only report what we know.
    """
    return {
        "report": "se.report/1",
        "operation": operation,
        "status": "UNKNOWN",
        "scope": "identity",
        "warnings": [reason],
        "observation": {
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": "se-console",
            "source_root": SE_ROOT,
        },
    }


def se_available() -> bool:
    """Deprecated by `probe_se`: file existence is NOT engine availability.

    Kept only so nothing that imported it silently changes meaning; it now
    delegates to the real probe.
    """
    return probe_se()["operational"]


def probe_se(*, timeout: int = 20) -> dict[str, Any]:
    """Determine whether the `se` engine is actually *operational*.

    POC-001 judged availability by `os.path.isfile(SCRIPTS/se.py)`. That is a
    statement about the filesystem, not about the engine: during the
    SE-AUTOMATION-001C refactor `se.py` still existed while its import target
    `se_core/cli.py` had been truncated to 0 bytes, so the console reported
    `se_available: true` and a green `OK` while every command failed.

    This probes execution instead. It is cached for a short TTL because it
    spawns a subprocess, and the answer is a liveness fact, not governance.
    """
    now = time.monotonic()
    cached = _PROBE_CACHE.get("value")
    if cached and now - _PROBE_CACHE["at"] < PROBE_TTL_SECONDS:
        return cached

    result: dict[str, Any] = {
        "operational": False,
        "entry_present": os.path.isfile(SE_ENTRY),
        "reason": None,
        "detail": None,
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if not result["entry_present"]:
        result["reason"] = "se entrypoint not found"
        result["detail"] = SE_ENTRY
    else:
        try:
            proc = subprocess.run(
                [sys.executable, SE_ENTRY, "capabilities", "--json"],
                cwd=SE_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            result["reason"] = "se probe timed out"
        except OSError as exc:
            result["reason"] = "cannot invoke se"
            result["detail"] = str(exc)
        else:
            out = (proc.stdout or "").strip()
            if proc.returncode == 0 and out.startswith("{"):
                try:
                    env = json.loads(out)
                except json.JSONDecodeError:
                    result["reason"] = "se probe returned unparsable JSON"
                else:
                    if env.get("report") == "se.report/1":
                        result["operational"] = True
                    else:
                        result["reason"] = "unexpected report id from se probe"
                        result["detail"] = repr(env.get("report"))
            else:
                err = (proc.stderr or "").strip()
                result["reason"] = "se exited %d without JSON" % proc.returncode
                # Keep the tail: this is the single most useful line when the
                # engine itself is broken.
                result["detail"] = err[-300:] if err else "no stdout"

    _PROBE_CACHE["value"] = result
    _PROBE_CACHE["at"] = now
    return result


def _action_allows(args: list[str]) -> str | None:
    """Return the catalog id when ``args`` matches an approved action argv.

    This is the second, independent gate: `console/actions.py` validated the
    REQUEST, this validates the ARGV that request produced. Anything that does
    not parse as exactly one of the approved shapes falls through to the
    read-only allow-list (where `run ...` is refused, since it is not on it).
    """
    for action_id, spec in ACTION_ALLOWLIST.items():
        prefix = tuple(spec["prefix"])
        # Each entry declares its own prefix length ("transition" is ONE token,
        # "run checkpoint" is two). A window sized for one entry matches only
        # the entries it happens to fit and refuses every other one: comparing
        # two tokens against ("transition",) never matches, so the attest
        # delegation fell through to the read-only gate and was refused.
        if len(args) < len(prefix) + 2 or tuple(args[: len(prefix)]) != prefix:
            continue
        required = set(spec["required"])
        allowed = spec["allowed"]
        # `repeatable` names the flags that MAY occur more than once. Ignoring
        # it refuses any multi-valued delegation: `transition.attest` takes one
        # `--condition` per condition, so a list of conditions never matched.
        repeatable = set(spec.get("repeatable", ()))
        seen: set[str] = set()
        index = len(prefix)
        while index < len(args):
            flag = args[index]
            value = args[index + 1] if index + 1 < len(args) else None
            if (
                not flag.startswith("--")
                or "=" in flag
                or flag not in allowed
                or (flag in seen and flag not in repeatable)
                or value is None
                or value.startswith("--")
            ):
                break
            seen.add(flag)
            index += 2
        else:
            if required <= seen and index == len(args):
                return action_id
        break
    return None


def _action_envelope(action_id: str, proc: "subprocess.CompletedProcess[str]") -> dict[str, Any]:
    """Build the result envelope for a delegated action.

    `se run checkpoint|close` has no `--json` mode: it prints plain
    ``PASS:``/``FAIL:`` text and returns an exit code. The console therefore
    derives ``status`` FROM THE EXIT CODE and preserves stdout verbatim in
    ``result.output`` -- the raw evidence travels with the verdict, so a PASS
    is never asserted without the process evidence behind it. Transport-level
    problems (timeout, no JSON at all) are handled by the caller's `_unknown`
    path, not here.
    """
    output = (proc.stdout or "").strip()
    detail = (proc.stderr or "").strip()
    exit_code = proc.returncode
    if exit_code == 0:
        status = "PASS"
    elif exit_code in (1, 2):  # 1 = refusal/validation, 2 = usage
        status = "FAIL"
    else:
        status = "UNKNOWN"
    warnings = []
    if detail:
        warnings.append(detail[-400:])
    return {
        "report": "se.report/1",
        "operation": "se " + action_id.replace(".", " "),
        "status": status,
        "scope": "project",
        "warnings": warnings,
        "result": {"exit_code": exit_code, "output": output[:2000]},
        "observation": {
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": "se-console",
            "source_root": SE_ROOT,
        },
    }


def run_se(
    args: list[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    check_exit: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Invoke `se <args> --json` and return ``(envelope, meta)``.

    ``envelope`` is the parsed ``se.report/1`` envelope exactly as emitted by
    ``SCRIPTS/se_core/reporting.py``. ``meta`` carries console-side observations
    (exit code, duration, transport errors) that are NOT part of the envelope.
    """
    if not args:
        raise SeError("empty argv")
    verb = args[0]

    # Two independent gates: an approved ACTION argv shape is allowed through
    # (without `--json`, which the `run` subcommands do not accept);
    # everything else must be on the read-only allow-list.
    action_id = _action_allows(list(args))
    if action_id is None:
        if verb in FORBIDDEN_COMMANDS:
            raise SeError(
                f"refused: '{verb}' is a mutating SE command; SE-CONSOLE is read-only"
            )
        if verb not in READ_ONLY_COMMANDS:
            raise SeError(f"refused: '{verb}' is not on the console read-only allow-list")
        json_flag = ["--json"]
    else:
        json_flag = []

    # An approved ACTION may need to prove operator authority (`transition.attest`
    # requires the SE-CONSOLE operator token). Inject it through the child's
    # ENVIRONMENT -- never argv, never `meta`, never the envelope -- and only for
    # an approved action. If the token cannot be read, inject nothing and let the
    # CLI refuse: fail closed here too.
    child_env = None
    if action_id is not None:
        from .auth import load_token

        token = load_token()
        if token:
            child_env = {**os.environ, "SE_CONSOLE_TOKEN": token}

    started = time.perf_counter()
    meta: dict[str, Any] = {
        "argv": ["se", *args, *json_flag],
        "exit_code": None,
        "duration_ms": None,
        "transport": "ok",
    }

    try:
        proc = subprocess.run(
            [sys.executable, SE_ENTRY, *args, *json_flag],
            cwd=SE_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        meta["transport"] = "timeout"
        meta["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return _unknown(f"se {verb}", f"timeout after {timeout}s"), meta
    except OSError as exc:  # python missing, permissions, ...
        meta["transport"] = "oserror"
        meta["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return _unknown(f"se {verb}", f"cannot invoke se: {exc}"), meta

    meta["exit_code"] = proc.returncode
    meta["duration_ms"] = int((time.perf_counter() - started) * 1000)

    if action_id is not None:
        # Actions emit plain text, not an se.report/1 envelope; see
        # `_action_envelope` for how the verdict is derived from the exit code.
        return _action_envelope(action_id, proc), meta

    raw = (proc.stdout or "").strip()
    if not raw:
        detail = (proc.stderr or "").strip()[:400] or f"exit {proc.returncode}, no stdout"
        meta["transport"] = "empty"
        return _unknown(f"se {verb}", f"se produced no JSON: {detail}"), meta

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        meta["transport"] = "unparsable"
        head = raw[:200]
        return _unknown(f"se {verb}", f"unparsable JSON ({exc}) at: {head}"), meta

    if not isinstance(envelope, dict):
        meta["transport"] = "unexpected_shape"
        return _unknown(f"se {verb}", "envelope is not a JSON object"), meta

    if envelope.get("report") != "se.report/1":
        # Do not guess: an unknown contract id is a hard compatibility signal.
        meta["transport"] = "unknown_contract"
        envelope.setdefault(
            "warnings", []
        ).append(
            "unexpected report id: "
            f"{envelope.get('report')!r} (console pins 'se.report/1')"
        )

    if check_exit and proc.returncode not in (0,):
        meta["transport"] = "nonzero_exit"
        envelope.setdefault("warnings", []).append(
            f"se exited {proc.returncode} (0=ok, 1=validation/gate failure, 2=usage)"
        )

    return envelope, meta
