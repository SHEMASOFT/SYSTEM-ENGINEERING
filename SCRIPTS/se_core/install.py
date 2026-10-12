"""``se install`` — operator setup for a runtime (OpenCode first).

This module implements the setup pipeline behind the ``se install`` command:

1. detect the host OS (``windows`` | ``linux`` | ``macos``);
2. preflight external tools (python interpreter, the ``opencode`` CLI,
   ``engram``) with per-OS guidance — no automatic installation in v1.
   ``node``/``npx`` is only required when MCP servers that depend on it
   (``context7``, ``filesystem``) are selected;
3. optionally run the unified SE installer (``se-installer``) via ``--bootstrap``
   to install SE Core, Console, MCPs, runtimes, and generate runtime configs;
4. optionally generate the OpenCode adapter for the target project;
5. translate ``TEMPLATES/mcp/*.json.tmpl`` into ``opencode mcp add`` registrations,
   resolving ``${SE_ROOT}`` / ``${SE_PROJECT_ROOT}`` placeholders and the
   ``python3`` -> ``python`` interpreter name at registration time;
6. summarize registered / skipped / missing pieces plus the environment variables
   the user must provide (``SE_ROOT``, ``SE_PROJECT_ROOT``, ``CONTEXT7_API_KEY``, ...).

Every boundary that touches the outside world (subprocess execution, executable
lookup, the current platform) is injectable so the unit tests never spawn the real
``opencode`` CLI and never mutate a real configuration.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import load_json, repo_root
from .mcpconfig import add_server_text

SUPPORTED_OS = ("windows", "linux", "macos")

#: Template directory (relative to the SE repository root).
MCP_TEMPLATE_DIR = "TEMPLATES/mcp"

#: Placeholders resolved at registration time.
SE_ROOT_PLACEHOLDER = "${SE_ROOT}"
SE_PROJECT_ROOT_PLACEHOLDER = "${SE_PROJECT_ROOT}"

#: ``${NAME}`` references left to the user's environment at runtime.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: Environment variables every registered runtime needs.
ALWAYS_REPORTED_ENV_VARS = ("SE_ROOT", "SE_PROJECT_ROOT")

#: External tools probed by preflight, in report order. Each entry declares the
#: candidate executable names to probe and per-OS install guidance. v1 never
#: installs anything automatically; it reports and guides.
#:
#: ``node`` is special: it is only required when MCP servers that depend on it
#: (``context7``, ``filesystem``) are selected. The preflight logic handles this
#: conditionally based on the selected servers.
DEPENDENCIES = (
    {
        "name": "python",
        "commands": ("python3", "python"),
        "purpose": "Runs the SE reference CLI and the SE skill-server MCP.",
        "guidance": {
            "windows": "Install Python 3 from https://www.python.org/downloads/ "
                       "(winget install Python.Python.3.12) and ensure it is on PATH.",
            "linux": "Install Python 3 with your package manager "
                     "(apt install python3 / dnf install python3).",
            "macos": "Install Python 3 (brew install python@3.12 or python.org).",
        },
    },
    {
        "name": "node",
        "commands": ("npx", "node"),
        "purpose": "Runs the npx-based MCP servers (context7, filesystem). Only required when those servers are selected.",
        "guidance": {
            "windows": "Install Node.js LTS: winget install OpenJS.NodeJS.LTS "
                       "(provides node and npx).",
            "linux": "Install Node.js with your package manager (apt install nodejs npm).",
            "macos": "Install Node.js (brew install node).",
        },
    },
    {
        "name": "opencode",
        "commands": ("opencode",),
        "purpose": "The runtime that loads the registered MCP servers.",
        "guidance": {
            "windows": "Install the OpenCode CLI: npm install -g opencode-ai.",
            "linux": "Install the OpenCode CLI: curl -fsSL https://opencode.ai/install | bash.",
            "macos": "Install the OpenCode CLI: brew install sst/tap/opencode.",
        },
    },
    {
        "name": "engram",
        "commands": ("engram",),
        "purpose": "Persistent memory MCP.",
        "guidance": {
            "windows": "Install the Engram binary from "
                       "https://github.com/Gentleman-Programming/engram (prebuilt release) "
                       "and run: engram setup opencode.",
            "linux": "brew install gentleman-programming/tap/engram (or "
                     "go install github.com/Gentleman-Programming/engram/v3/cmd/engram@latest).",
            "macos": "brew install gentleman-programming/tap/engram and run: engram setup opencode.",
        },
    },
)

#: MCP server key -> dependency name required to launch it (see :data:`DEPENDENCIES`).
SERVER_DEPENDENCY = {
    "context7": "node",
    "engram": "engram",
    "filesystem": "node",
    "skill-server": "python",
}


def run_bootstrap_installer(
    *,
    components: str | None = None,
    runtimes: str | None = None,
    dry_run: bool = False,
    project: Path | str,
    json_output: bool = False,
) -> tuple[int, dict | None]:
    """Run the ``se-installer`` CLI as a subprocess for the bootstrap phase.

    Returns ``(exit_code, summary_dict)``. ``summary_dict`` is the parsed JSON
    output when the command succeeds. Always runs with --json internally to
    capture the summary reliably.
    """
    project = Path(project)
    se_installer_cmd = [sys.executable, "-m", "se_installer.cli", "install"]

    # Map bootstrap components to se-installer components
    if components:
        comp_list = [c.strip() for c in components.split(",") if c.strip()]
        se_installer_cmd.extend(["--components"] + comp_list)
    else:
        se_installer_cmd.append("--recommended")

    if runtimes:
        rt_list = [r.strip() for r in runtimes.split(",") if r.strip()]
        se_installer_cmd.extend(["--runtimes"] + rt_list)

    if dry_run:
        se_installer_cmd.append("--dry-run")

    # Always use --json internally to get parseable summary
    se_installer_cmd.append("--json")

    # Run from the project directory so se-installer state is local to project
    try:
        result = subprocess.run(
            se_installer_cmd,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return 1, {"error": "se-installer bootstrap timed out (300s)"}
    except FileNotFoundError:
        return 1, {"error": "se-installer not found; ensure it is installed (pip install -e SE-INSTALLER)"}

    summary = None
    if result.stdout:
        try:
            import json
            # The JSON is the last line(s) of stdout
            lines = result.stdout.strip().split('\n')
            json_start = None
            for i, line in enumerate(lines):
                if line.strip().startswith('{'):
                    json_start = i
                    break
            if json_start is not None:
                json_text = '\n'.join(lines[json_start:])
                summary = json.loads(json_text)
        except Exception:
            pass

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or f"se-installer exited with {result.returncode}"
        return result.returncode, {"error": error_msg}

    return 0, summary


def detect_os(platform_name: str | None = None) -> str:
    """Return ``windows`` | ``linux`` | ``macos`` for a platform string.

    ``platform_name`` is injectable for tests; it defaults to ``sys.platform``.
    Unknown platforms raise :class:`ValueError`.
    """
    value = (platform_name or __import__("sys").platform).lower()
    if value.startswith("win"):
        return "windows"
    if value.startswith("darwin"):
        return "macos"
    if value.startswith("linux"):
        return "linux"
    raise ValueError(f"unsupported platform: {platform_name or value}")


#: Runtime environments the installer can target. ``auto`` resolves to the host
#: environment at run time; ``wsl`` is the Linux distribution while the OpenCode
#: the user actually runs may live on either side of the boundary.
ENV_TARGETS = ("auto", "windows", "wsl", "linux", "macos")


def detect_env_target(
    platform_name: str | None = None, *, wsl_distro: str | None = None
) -> str:
    """Return ``windows`` | ``wsl`` | ``linux`` | ``macos`` for this process.

    ``sys.platform`` reads ``linux`` inside WSL, so the host environment is
    refined with ``WSL_DISTRO_NAME`` (set by WSL itself). ``wsl_distro`` is
    injectable for tests.
    """
    os_name = detect_os(platform_name)
    if os_name == "linux":
        probe = wsl_distro if wsl_distro is not None else __import__("os").environ.get("WSL_DISTRO_NAME")
        if probe:
            return "wsl"
    return os_name


def translate_host_path(path: str | Path, source: str, target: str) -> str:
    """Translate an absolute path between Windows and WSL/Unix spellings.

    A Windows drive path becomes the WSL mount of that drive, and vice versa.
    Only paths that match the source spelling are translated; anything else is
    returned unchanged, so the call is safe to apply defensively. Same
    source/target pairs are a no-op.
    """
    text = str(path)
    if source == target:
        return text
    normalized = text.replace("\\", "/")
    if source == "windows" and target in ("wsl", "linux"):
        match = re.match(r"^([A-Za-z]):(?:/(.*))?$", normalized)
        if not match:
            return normalized
        drive = match.group(1).lower()
        rest = (match.group(2) or "").strip("/")
        return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"
    if source in ("wsl", "linux") and target == "windows":
        match = re.match(r"^/mnt/([A-Za-z])(?:/(.*))?$", normalized)
        if match:
            drive = match.group(1).upper()
            rest = (match.group(2) or "").strip("/").replace("/", "\\")
            return f"{drive}:\\{rest}" if rest else f"{drive}:\\"
        return normalized.replace("/", "\\")
    return normalized if source == "windows" else text


def path_mapper_for(host_env: str, env_target: str):
    """Return a ``str -> str`` mapper or ``None`` when no translation is needed."""
    if not env_target or env_target == "auto" or env_target == host_env:
        return None
    return lambda value: translate_host_path(value, host_env, env_target)


def default_probe_runner(command, timeout=20):
    """Run a probe command capturing output (production seam; tests inject fakes)."""
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def probe_command_version(command: str, *, runner=None, timeout: int = 20):
    """Execute ``command --version`` and report whether it really runs.

    Returns ``(ok, version, detail)``: ``version`` is the first non-empty output
    line when the command exits 0; ``detail`` carries truncated failure output
    otherwise. A stub whose postinstall never ran exits non-zero, which is how a
    broken ``opencode`` npm install is detected before anything depends on it.
    """
    runner = runner or default_probe_runner
    # Resolve first: on Windows the shims are ``.cmd``/``.ps1`` and CreateProcess
    # does not append those extensions to a bare name from PATH.
    resolved = shutil.which(command) or command
    try:
        result = runner([resolved, "--version"], timeout=timeout)
    except FileNotFoundError:
        return False, None, "executable not found"
    except Exception as exc:  # noqa: BLE001 - reported as a probe failure
        return False, None, str(exc)[:300]
    output = ((getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")).strip()
    if getattr(result, "returncode", None) == 0:
        first = next((line.strip() for line in output.splitlines() if line.strip()), "")
        return True, (first or None), None
    return False, None, output[:300] or f"exit {getattr(result, 'returncode', 'unknown')}"


_OPENCODE_BROKEN_HINTS = ("postinstall", "not a valid application", "is not recognized", "no such file")
_OPENCODE_VERSION_RE = re.compile(r"(\d+)\.(\d+)")


def classify_opencode(*, ok: bool, version: str | None, detail: str | None, os_name: str) -> tuple[str, str, str | None]:
    """Classify the opencode preflight probe into ``(status, note, remedy)``.

    * broken binary (stub, failed postinstall, wrong platform build) -> WARN with
      the exact remedy;
    * v1 running -> WARN: this project targets v2;
    * v2 running -> PASS;
    * anything else runnable -> PASS (version reported verbatim).
    """
    if not ok:
        lowered = (detail or "").lower()
        platform_mismatch = any(
            hint in lowered
            for hint in ("not a valid application", "aplicación válida", "not compatible", "no es compatible")
        )
        postinstall_missed = any(hint in lowered for hint in _OPENCODE_BROKEN_HINTS) or "postinstall" in lowered
        if platform_mismatch:
            remedy = (
                "The installed opencode binary cannot run on this platform (a partially "
                "installed or wrong-platform npm package). Reinstall with scripts enabled: "
                "npm install -g @opencode/cli (with pnpm, run pnpm approve-builds first)."
            )
        elif postinstall_missed:
            remedy = (
                "The npm package's postinstall did not run. Fix it with: "
                "npm rebuild -g @opencode/cli. With pnpm, approve build scripts first: "
                "pnpm approve-builds, then reinstall."
            )
        else:
            remedy = (
                "The opencode CLI did not run. Repair or reinstall it: "
                "npm rebuild -g @opencode/cli (with pnpm: pnpm approve-builds first), or use the "
                "official installer at https://opencode.ai/install."
            )
        return "WARN", f"does not run: {(detail or '').strip()[:160]}", remedy
    match = _OPENCODE_VERSION_RE.search(version or "")
    if match and match.group(1) == "1":
        return (
            "WARN",
            f"v1 detected ({version}); this project targets OpenCode v2",
            "Upgrade the CLI: npm install -g @opencode/cli, or re-run the official installer "
            "(https://opencode.ai/install).",
        )
    return "PASS", version or "runs", None


def load_mcp_templates(root: Path | str) -> list[dict]:
    """Load ``TEMPLATES/mcp/*.json.tmpl`` as portable registration specs.

    Each record keeps the template stem as ``key`` (the user-facing selector), the
    template's own ``name`` (the registered MCP server name — it can differ, e.g.
    ``skill-server`` -> ``se-skill-server``), plus ``command`` / ``args`` / ``env``
    with the original placeholders intact. Records are sorted by ``key`` for
    deterministic output.
    """
    root = Path(root)
    templates = []
    for path in sorted((root / MCP_TEMPLATE_DIR).glob("*.json.tmpl")):
        data = load_json(path)
        templates.append(
            {
                "key": path.name[: -len(".json.tmpl")],
                "name": data["name"],
                "command": data["command"],
                "args": list(data.get("args") or []),
                "env": dict(data.get("env") or {}),
                "template": f"{MCP_TEMPLATE_DIR}/{path.name}",
            }
        )
    return templates


def select_servers(
    templates: list[dict], with_list: str | None = None
) -> list[str]:
    """Return the server keys to register.

    ``with_list`` is a comma-separated selection; ``None`` selects every server
    (``--all`` default). Unknown keys raise :class:`ValueError` so a typo never
    silently registers nothing.
    """
    by_key = {t["key"]: t for t in templates}
    if with_list is None:
        return [t["key"] for t in templates]
    selected = []
    for raw in with_list.split(","):
        key = raw.strip()
        if not key:
            continue
        if key not in by_key:
            raise ValueError(f"unknown MCP server: {key!r}; available: {', '.join(sorted(by_key))}")
        selected.append(key)
    return sorted(set(selected))


def resolve_python_interpreter(which=None, env_target: str | None = None) -> str | None:
    """Return the python command to register, honouring the target environment.

    Windows teaches ``python``; POSIX (Linux/WSL/macOS) teaches ``python3``. Each
    order falls back to the other name, so a machine that only provides one still
    resolves. ``which`` is injectable for tests; returns ``None`` when neither
    candidate resolves.
    """
    which = which or shutil.which
    candidates = ("python", "python3") if env_target == "windows" else ("python3", "python")
    for candidate in candidates:
        if which(candidate):
            return candidate
    return None


def preflight_dependencies(
    os_name: str, which=None, interpreter: str | None = None, selected_servers: list[str] | None = None,
    probe=None,
) -> list[dict]:
    """Probe external tools and return per-dependency preflight items.

    Each item is ``{"name", "status" ("PASS" | "WARN"), "detail", "guidance",
    "purpose"}``. ``which`` (executable lookup) and ``interpreter`` (pre-resolved
    python name) are injectable for tests. Nothing is ever installed.

    ``selected_servers`` controls conditional dependencies: ``node`` is only
    probed when ``context7`` or ``filesystem`` are in the selected servers.

    ``probe`` is an optional ``command -> (ok, version, detail)`` callable
    (see :func:`probe_command_version`). When provided, node/opencode/engram are
    *executed* instead of only looked up, so a broken npm install (a stub whose
    postinstall never ran) or an OpenCode v1 binary is reported with a remedy
    instead of a false PASS. Tests leave it ``None`` to stay hermetic.
    """
    which = which or shutil.which
    items = []

    # Determine if node is needed (context7 or filesystem selected)
    node_needed = False
    if selected_servers:
        node_needed = any(s in selected_servers for s in ("context7", "filesystem"))

    for dep in DEPENDENCIES:
        # Skip node if not needed
        if dep["name"] == "node" and not node_needed:
            continue

        if dep["name"] == "python":
            found_command = (
                interpreter
                if interpreter is not None
                else resolve_python_interpreter(which)
            )
        else:
            found_command = next((c for c in dep["commands"] if which(c)), None)

        status = "PASS" if found_command else "WARN"
        detail = found_command or f"not found (tried: {', '.join(dep['commands'])})"
        guidance = dep["guidance"][os_name]

        if found_command and probe is not None and dep["name"] in ("node", "opencode", "engram"):
            ok, version, probe_detail = probe(found_command)
            if dep["name"] == "opencode":
                status, note, remedy = classify_opencode(
                    ok=ok, version=version, detail=probe_detail, os_name=os_name
                )
                detail = f"{found_command}: {note}"
                if remedy:
                    guidance = guidance + " Remedy: " + remedy
            elif ok:
                detail = f"{found_command} ({version})" if version else found_command
            else:
                status = "WARN"
                detail = f"{found_command} does not run: {(probe_detail or '').strip()[:160]}"

        items.append(
            {
                "name": dep["name"],
                "status": status,
                "detail": detail,
                "guidance": guidance,
                "purpose": dep["purpose"],
            }
        )
    return items


def resolve_placeholders(value: str, context: dict, *, env_mode: bool = False) -> str:
    """Resolve ``${SE_ROOT}`` / ``${SE_PROJECT_ROOT}`` / ``{{project_id}}`` in ``value``.

    In ``env_mode`` any *other* ``${NAME}`` becomes the OpenCode runtime reference
    ``{env:NAME}`` so a secret value (``CONTEXT7_API_KEY``) is resolved by the runtime
    instead of being embedded literally. In argument mode unknown references are left
    untouched.
    """
    value = value.replace(SE_ROOT_PLACEHOLDER, context["se_root"])
    value = value.replace(SE_PROJECT_ROOT_PLACEHOLDER, context["se_project_root"])
    value = value.replace("{{project_id}}", context["project_id"])
    if env_mode:
        value = _ENV_REF.sub(lambda match: "{env:" + match.group(1) + "}", value)
    return value


def read_project_id(project: Path | str) -> str:
    """Return the target project id (from ``PROJECT.json``) or its directory name."""
    project = Path(project)
    manifest = project / "PROJECT.json"
    if manifest.exists():
        try:
            return str(load_json(manifest).get("project_id") or project.name)
        except Exception:
            return project.name
    return project.name


def build_registrations(
    templates: list[dict],
    *,
    se_root: Path | str,
    project: Path | str,
    project_id: str,
    interpreter: str | None,
    scope: str = "project",
    register: bool = True,
    preflight: list[dict] | None = None,
) -> list[dict]:
    """Build the ``opencode mcp add`` registration records for the selected servers.

    Each record carries the exact ``command`` argv, ``status`` (``planned`` /
    ``skipped`` / ``registered``) and a ``reason`` when skipped. A server whose
    declared dependency is missing, or all servers when ``--no-register`` is used,
    are ``skipped``. The python interpreter name is substituted into the command.
    """
    context = {
        "se_root": str(se_root),
        "se_project_root": str(project),
        "project_id": project_id,
    }
    state_by_dependency = {item["name"]: item for item in (preflight or [])}
    registrations = []
    for template in templates:
        key = template["key"]
        dependency = SERVER_DEPENDENCY.get(key)
        registration = {
            "server": key,
            "name": template["name"],
            "status": "planned",
            "reason": None,
            "requires": [dependency] if dependency else [],
            "command": [],
        }
        if not register:
            registration["status"] = "skipped"
            registration["reason"] = "registration disabled (--no-register)"
            registrations.append(registration)
            continue
        if dependency and state_by_dependency.get(dependency, {}).get("status") != "PASS":
            registration["status"] = "skipped"
            registration["reason"] = f"missing dependency: {dependency}"
            registrations.append(registration)
            continue

        command_name = template["command"]
        if command_name.startswith("python"):
            command_name = interpreter or "python3"
        args = [resolve_placeholders(a, context) for a in template["args"]]
        env_flags = []
        for env_name in sorted(template["env"]):
            env_flags += [
                "--env",
                f"{env_name}={resolve_placeholders(template['env'][env_name], context, env_mode=True)}",
            ]
        argv = ["opencode", "mcp", "add"]
        if scope == "global":
            argv.append("--global")
        argv += env_flags
        argv += [template["name"], "--", command_name, *args]
        registration["command"] = argv
        registrations.append(registration)
    return registrations


def resolved_server_spec(
    template: dict,
    *,
    se_root: Path | str,
    project: Path | str,
    project_id: str,
    interpreter: str | None,
    path_mapper=None,
) -> dict:
    """Resolve a template into the config-entry spec it registers at ``project``.

    Returns a plain dict ``{"name", "command": [...], "environment": {...}}`` with
    placeholders resolved exactly like :func:`build_registrations` (paths and
    ``{{project_id}}`` resolved; ``${OTHER}`` env values turned into the runtime
    reference ``{env:OTHER}``). This is the canonical DECLARED shape that
    ``se sync`` / ``se update`` compare against the runtime config and that
    lifecycle state hashes.

    ``path_mapper`` optionally translates the resolved host paths (for example a
    Windows drive path to its WSL mount when the runtime lives in WSL); install,
    sync and the recorded state must use the same mapper or their hashes diverge.
    """
    se_root_value = str(se_root)
    project_value = str(project)
    if path_mapper is not None:
        se_root_value = path_mapper(se_root_value)
        project_value = path_mapper(project_value)
    context = {
        "se_root": se_root_value,
        "se_project_root": project_value,
        "project_id": project_id,
    }
    command_name = template["command"]
    if command_name.startswith("python"):
        command_name = interpreter or "python3"
    args = [resolve_placeholders(a, context) for a in template["args"]]
    environment = {
        env_name: resolve_placeholders(
            template["env"][env_name], context, env_mode=True
        )
        for env_name in sorted(template["env"])
    }
    return {
        "name": template["name"],
        "command": [command_name, *args],
        "environment": environment,
    }


def probe_global_support(runner, command=None) -> bool:
    """Probe whether the installed ``opencode`` CLI supports ``mcp add --global``.

    Runs ``opencode mcp add --help`` ONCE through ``runner`` and scans stdout and
    stderr for ``--global``. ``command`` is injectable for tests. The probe is
    read-only; the runner is the same injectable seam used for registrations, so
    tests never spawn the real CLI.
    """
    result = runner(list(command) if command else ["opencode", "mcp", "add", "--help"])
    output = (getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")
    return "--global" in output


def execute_registrations(registrations: list[dict], runner) -> None:
    """Run the planned registration commands through ``runner``.

    ``runner(command)`` returns an object with ``returncode`` (and optionally
    ``stderr``). Only ``planned`` records execute; the result mutates their status to
    ``registered`` or ``skipped``.
    """
    for registration in registrations:
        if registration["status"] != "planned":
            continue
        result = runner(registration["command"])
        if getattr(result, "returncode", None) == 0:
            registration["status"] = "registered"
        else:
            registration["status"] = "skipped"
            stderr = (getattr(result, "stderr", "") or "").strip()
            registration["reason"] = (
                f"registration failed (exit {getattr(result, 'returncode', 'unknown')})"
                + (f": {stderr[:160]}" if stderr else "")
            )


def write_server_configs_direct(
    selected_templates: list[dict],
    *,
    se_root: Path | str,
    project: Path | str,
    project_id: str,
    interpreter: str | None,
    target: Path | str,
    scope: str = "project",
    path_mapper=None,
) -> list[dict]:
    """Write server configs directly to opencode.jsonc using surgical editing.

    Returns list of results for each server. ``path_mapper`` (see
    :func:`resolved_server_spec`) keeps the written spec identical to the one
    :func:`record_lifecycle_state` hashes.
    """
    from .mcpconfig import add_server_text, config_path

    target = Path(target)
    config_file = config_path(target)
    results = []
    for template in selected_templates:
        spec = resolved_server_spec(
            template,
            se_root=se_root,
            project=project,
            project_id=project_id,
            interpreter=interpreter,
            path_mapper=path_mapper,
        )
        server_config = {
            "type": "local",
            "command": spec["command"],
            "environment": spec["environment"],
        }
        result = add_server_text(config_file, spec["name"], server_config, target=target)
        results.append({
            "server": template["key"],
            "name": spec["name"],
            "status": "registered" if not result["errors"] else "skipped",
            "reason": result["errors"][0] if result["errors"] else None,
            "added": result["added"],
            "updated": result["updated"],
        })
    return results


def default_runner(command):
    """Run ``command`` in a real subprocess (production seam; tests inject a fake)."""
    import subprocess

    return subprocess.run(command, capture_output=True, text=True)


def record_lifecycle_state(
    *,
    target: Path | str,
    se_root: Path | str,
    os_name: str,
    scope: str,
    project_id: str,
    interpreter: str | None,
    templates: list[dict],
    registrations: list[dict],
    adapter: dict,
    env_target: str | None = None,
    path_mapper=None,
) -> dict:
    """Persist the SE-owned lifecycle state after real registrations.

    Merges with an existing state (the ``uninstalled`` audit trail is preserved),
    records every ``registered`` server with its declared spec hash, and refreshes
    ``se_version`` / ``os`` / ``target``. Returns the saved state. Reuses the
    lifecycle-state module so install, sync, update and uninstall share one format.

    ``env_target`` records which runtime environment the declared specs were
    resolved for (``windows`` | ``wsl`` | ...), so ``se sync`` can rebuild the same
    spec — and its hash — with :func:`resolved_server_spec`'s ``path_mapper``.
    """
    import hashlib

    from . import lifecycle_state as lc

    target = Path(target)
    state = lc.load_state(target) or lc.new_state(
        se_version=lc.read_se_version(se_root),
        os_name=os_name,
        target=str(target),
        scope=scope,
    )
    state["se_version"] = lc.read_se_version(se_root)
    state["os"] = os_name
    state["target"] = str(target)
    state["scope"] = scope
    state["runtime"] = "opencode"
    if env_target:
        state["env_target"] = env_target

    by_key = {t["key"]: t for t in templates}
    for registration in registrations:
        if registration["status"] != "registered":
            continue
        template = by_key.get(registration["server"])
        if template is None:
            continue
        spec = resolved_server_spec(
            template,
            se_root=se_root,
            project=target,
            project_id=project_id,
            interpreter=interpreter,
            path_mapper=path_mapper,
        )
        lc.record_server(
            state,
            spec["name"],
            declared=lc.spec_hash(spec),
            source=template["template"],
            scope=scope,
        )
    if adapter and adapter.get("status") == "generated":
        manifest = target / "adapter-manifest.json"
        digest = ""
        if manifest.exists():
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        state["adapter"] = {"generated": True, "hash": digest}
    lc.save_state(state, target)
    return state


def plan_adapter_selection(se_root: Path | str, project: Path | str, *, generate: bool) -> dict:
    """Plan the optional adapter generation step.

    Refuses to regenerate the SE repository's own ``.opencode`` (out of scope for v1);
    consumer projects are planned.
    """
    entry = {"generate": bool(generate), "output": str(project), "status": "skipped", "reason": None}
    if not generate:
        entry["reason"] = "--generate-adapter not set"
        return entry
    if Path(project).resolve() == Path(se_root).resolve():
        entry["status"] = "BLOCKED"
        entry["reason"] = (
            "refusing to regenerate the SE repository's own .opencode; "
            "run --generate-adapter from a consumer project"
        )
        return entry
    entry["status"] = "planned"
    return entry


def generate_adapter_files(se_root: Path | str, project: Path | str) -> dict:
    """Generate the OpenCode adapter for a consumer project via the existing generator."""
    from .opencode.generator import generate_project

    project = Path(project)
    manifest = project / "PROJECT.json"
    if manifest.exists():
        try:
            project_data = load_json(manifest)
        except Exception as exc:  # noqa: BLE001 - report, never crash the installer
            return {"status": "FAIL", "errors": [f"cannot read PROJECT.json: {exc}"]}
    else:
        project_data = {"project_id": project.name, "name": project.name}
    try:
        return generate_project(se_root, project, project_data)
    except (ValueError, OSError) as exc:
        return {"status": "FAIL", "errors": [str(exc)]}


def collect_env_vars(templates: list[dict]) -> list[str]:
    """Return the sorted set of ``${NAME}`` references found in the templates.

    Every referenced variable is reported so the operator can set it before the
    registered servers start (``CONTEXT7_API_KEY``, ``SE_ROOT``, ...).
    """
    found = set()
    for template in templates:
        for value in [template["command"], *template["args"], *template["env"].values()]:
            found.update(_ENV_REF.findall(value))
    for guaranteed in ALWAYS_REPORTED_ENV_VARS:
        found.add(guaranteed)
    return sorted(found)


def build_plan(
    *,
    os_name: str,
    se_root: Path | str,
    project: Path | str,
    scope: str = "project",
    register: bool = True,
    generate_adapter: bool = False,
    dry_run: bool = True,
    selected: list[str] | None = None,
    templates: list[dict] | None = None,
    preflight: list[dict] | None = None,
    registrations: list[dict] | None = None,
    adapter: dict | None = None,
) -> dict:
    """Build the deterministic install plan (a plain JSON-serializable dict).

    ``preflight``, ``registrations`` and ``adapter`` are produced by earlier pipeline
    stages; the envelope and renderer stay stable regardless of their presence.
    """
    templates = templates if templates is not None else load_mcp_templates(se_root)
    servers = selected if selected is not None else [t["key"] for t in templates]
    preflight = list(preflight or [])
    plan_adapter = (
        adapter
        if adapter is not None
        else {
            "generate": bool(generate_adapter),
            "output": str(project),
            "status": "skipped",
            "reason": None,
        }
    )
    return {
        "os": os_name,
        "scope": scope,
        "se_root": str(se_root),
        "project": str(project),
        "register": register,
        "generate_adapter": plan_adapter["generate"],
        "adapter": plan_adapter,
        "servers": servers,
        "preflight": preflight,
        "registrations": list(registrations or []),
        "missing_dependencies": sorted(
            {item["name"] for item in preflight if item["status"] != "PASS"}
        ),
        "env_vars": collect_env_vars(templates),
        "dry_run": dry_run,
        "blockers": [],
        "status": "PASS",
    }


def render_plan(plan: dict) -> str:
    """Render the plan as deterministic human-readable text (no ANSI)."""
    lines = []
    mode = " (dry-run)" if plan["dry_run"] else ""
    lines.append("se install plan" + mode)
    lines.append(f"OS: {plan['os']}")
    env_target = plan.get("env_target")
    if env_target and env_target != plan["os"]:
        lines.append(f"Env target: {env_target} (host paths translated from {plan['os']})")
    lines.append(f"Scope: {plan['scope']}")
    lines.append(f"SE root: {plan['se_root']}")
    lines.append(f"Project: {plan['project']}")
    if plan["generate_adapter"]:
        lines.append(f"Adapter: generate into {plan['adapter']['output']}")
    else:
        lines.append("Adapter: skipped (use --generate-adapter)")
    if plan["adapter"].get("status") == "BLOCKED":
        lines.append(f"  -> {plan['adapter'].get('reason')}")
    if not plan["register"]:
        lines.append("Registration: disabled (--no-register)")
    servers = plan["servers"]
    lines.append(
        f"Servers to register ({len(servers)}): "
        + (", ".join(servers) if servers else "none")
    )
    if plan.get("preflight"):
        lines.append("Preflight:")
        for item in plan["preflight"]:
            lines.append(f"  [{item['status']}] {item['name']}: {item['detail']}")
            if item["status"] != "PASS" and item.get("guidance"):
                lines.append(f"    -> {item['guidance']}")
    if plan.get("registrations"):
        lines.append("Registrations:")
        for item in plan["registrations"]:
            command = " ".join(item.get("command") or [])
            suffix = f" -> {command}" if command else ""
            reason = f" ({item['reason']})" if item.get("reason") else ""
            lines.append(f"  [{item['status']}] {item['server']}{suffix}{reason}")
        counts = {}
        for item in plan["registrations"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        parts = [f"{name} {counts[name]}" for name in ("registered", "skipped", "planned") if counts.get(name)]
        if plan.get("missing_dependencies"):
            parts.append(f"missing dependencies {len(plan['missing_dependencies'])}")
        if parts:
            lines.append("Summary: " + ", ".join(parts))
    for blocker in plan.get("blockers") or []:
        lines.append(f"Blocked: {blocker}")
    if plan["env_vars"]:
        lines.append("Environment variables to set: " + ", ".join(plan["env_vars"]))
    lines.append(f"Status: {plan['status']}")
    return "\n".join(lines)


def run(args, *, platform_name: str | None = None, runner=None, which=None, probe=None) -> int:
    """Execute the ``se install`` pipeline.

    ``platform_name``, ``runner``, ``which`` and ``probe`` are injectable test
    seams; production callers pass nothing and get the current platform, the real
    subprocess runner, the real executable lookup and the real ``--version``
    probe. Exit codes: 0 success, 1 failure/BLOCKED report, 2 usage.
    """
    se_root = repo_root()
    project = Path(getattr(args, "project", None) or ".").resolve()
    os_name = detect_os(platform_name)
    host_env = detect_env_target(platform_name)
    requested_target = str(getattr(args, "env_target", "auto") or "auto")
    if requested_target not in ENV_TARGETS:
        print(f"FAIL: unknown --env-target {requested_target!r}; expected one of {', '.join(ENV_TARGETS)}")
        return 2
    env_target = host_env if requested_target == "auto" else requested_target
    path_mapper = path_mapper_for(host_env, env_target)
    which = which or shutil.which

    # Handle --bootstrap: run se-installer first to install SE Core, Console, MCPs, runtimes
    bootstrap = bool(getattr(args, "bootstrap", False))
    if bootstrap:
        dry_run = bool(getattr(args, "dry_run", False))
        json_output = bool(getattr(args, "json", False))
        components = getattr(args, "bootstrap_components", None)
        runtimes = getattr(args, "bootstrap_runtimes", None)

        # Run se-installer bootstrap
        exit_code, summary = run_bootstrap_installer(
            components=components,
            runtimes=runtimes,
            dry_run=dry_run,
            project=project,
            json_output=json_output,
        )
        if exit_code != 0:
            if json_output:
                from .reporting import build_envelope, render_json
                envelope = build_envelope(
                    "install",
                    "FAIL",
                    scope="identity",
                    source_root=str(se_root),
                    details={"bootstrap": summary or {"error": "bootstrap failed"}},
                )
                print(render_json(envelope))
            else:
                print(f"FAIL: bootstrap failed: {summary.get('error') if summary else 'unknown error'}")
            return 1

        if json_output:
            # Include bootstrap summary in the final envelope
            plan = {
                "os": os_name,
                "scope": "project",
                "se_root": str(se_root),
                "project": str(project),
                "bootstrap": summary,
                "status": "PASS",
                "blockers": [],
            }
            from .reporting import build_envelope, render_json
            envelope = build_envelope(
                "install",
                "PASS",
                scope="identity",
                source_root=str(se_root),
                details=plan,
            )
            print(render_json(envelope))
            return 0

        # Print bootstrap summary and continue to MCP registration
        if summary:
            total = summary.get("total", 0)
            success = summary.get("success", 0)
            failed = summary.get("failed", 0)
            skipped = summary.get("skipped", 0)
            print(f"\n[BOOTSTRAP] Total: {total} | [OK] {success} | [FAIL] {failed} | [SKIP] {skipped}")

    templates = load_mcp_templates(se_root)
    selected_keys = select_servers(templates, with_list=getattr(args, "with_", None))
    selected_templates = [t for t in templates if t["key"] in selected_keys]
    interpreter = resolve_python_interpreter(which, env_target=env_target)
    preflight = preflight_dependencies(
        os_name, which=which, interpreter=interpreter,
        selected_servers=selected_keys, probe=probe,
    )
    scope = "global" if getattr(args, "global", False) else "project"
    register = not getattr(args, "no_register", False)
    generate_adapter = bool(getattr(args, "generate_adapter", False))
    dry_run = bool(getattr(args, "dry_run", False))
    project_id = read_project_id(project)

    registrations = build_registrations(
        selected_templates,
        se_root=se_root,
        project=project,
        project_id=project_id,
        interpreter=interpreter,
        scope=scope,
        register=register,
        preflight=preflight,
    )
    adapter = plan_adapter_selection(se_root, project, generate=generate_adapter)
    plan = build_plan(
        os_name=os_name,
        se_root=se_root,
        project=project,
        scope=scope,
        register=register,
        generate_adapter=generate_adapter,
        dry_run=dry_run,
        selected=selected_keys,
        templates=templates,
        preflight=preflight,
        registrations=registrations,
        adapter=adapter,
    )
    plan["env_target"] = env_target

    if scope == "global" and register:
        probe_runner = runner or default_runner
        if not probe_global_support(probe_runner):
            plan["status"] = "BLOCKED"
            plan["blockers"].append(
                "the installed opencode CLI does not support --global "
                "(probed `opencode mcp add --help`); re-run without --global "
                "or upgrade opencode"
            )

    if adapter["status"] == "BLOCKED":
        plan["status"] = "BLOCKED"
        plan["blockers"].append(adapter["reason"])
    elif adapter["status"] == "planned" and not dry_run:
        result = generate_adapter_files(se_root, project)
        if result.get("status") == "PASS":
            adapter["status"] = "generated"
            adapter["files"] = len(result.get("files", []))
        else:
            adapter["status"] = "FAIL"
            adapter["errors"] = list(result.get("errors", []))[:5]
            plan["status"] = "FAIL"
            plan["blockers"].append(f"adapter generation failed: {'; '.join(adapter['errors'])}")

    if plan["status"] == "PASS" and not dry_run and register:
        # MCP servers are written straight into the runtime config (surgical,
        # portable), so the opencode CLI is not required for registration. A
        # broken or missing CLI was already reported by the preflight probe.
        # Only servers whose dependency passed the preflight are written: the
        # installer never registers a server it cannot launch.
        planned_keys = {r["server"] for r in registrations if r["status"] == "planned"}
        planned_templates = [t for t in selected_templates if t["key"] in planned_keys]
        config_results = write_server_configs_direct(
            planned_templates,
            se_root=se_root,
            project=project,
            project_id=project_id,
            interpreter=interpreter,
            target=project,
            scope=scope,
            path_mapper=path_mapper,
        )
        results_by_key = {r["server"]: r for r in config_results}
        for reg in registrations:
            if reg["status"] != "planned":
                continue
            outcome = results_by_key.get(reg["server"])
            if outcome is not None:
                reg["status"] = outcome["status"]
                reg["reason"] = outcome["reason"]
        if any(r["status"] == "registered" for r in registrations):
            try:
                record_lifecycle_state(
                    target=project,
                    se_root=se_root,
                    os_name=os_name,
                    scope=scope,
                    project_id=project_id,
                    interpreter=interpreter,
                    templates=selected_templates,
                    registrations=registrations,
                    adapter=adapter,
                    env_target=env_target,
                    path_mapper=path_mapper,
                )
            except Exception as exc:  # noqa: BLE001 - state write is part of a successful install
                plan["status"] = "FAIL"
                plan["blockers"].append(f"failed to record lifecycle state: {exc}")

    if getattr(args, "json", False):
        from .reporting import build_envelope, render_json

        envelope = build_envelope(
            "install",
            plan["status"],
            scope="identity",
            source_root=str(se_root),
            details=plan,
        )
        print(render_json(envelope))
    else:
        print(render_plan(plan))
    return 0 if plan["status"] == "PASS" else 1