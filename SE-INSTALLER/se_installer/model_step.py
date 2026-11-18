"""Optional MODEL SELECTION step of the unified installer.

The installer runs this step after a successful install. It records the
operator's choice with ``save_model_config`` — the same ``opencode.jsonc`` store
``se shema-ai model`` reads and writes — and then refreshes the generated runtime
layers with ``se adapter <runtime>``, so the Codex, Claude Code and DeepSeek
adapters pick the selection up through ``_model_for_agent``.

Three invariants shape the implementation:

* **Skipping writes nothing.** No ``model`` key, no fallback model, no file
  created: ``save_model_config`` is not even imported when nobody selected a
  model. An install that skips the step leaves an unconfigured checkout exactly
  as unconfigured as it found it.
* **The selection is never invented.** This module only ever writes what the
  operator typed (``--model``, ``--model-agent`` or the prompt). There is no
  default provider, no default model and no "first free model" fallback.
* **The step never fails the install.** Every failure — an unreadable config, a
  missing ``se.py``, a failing adapter — is collected into the report the
  caller prints. The caller keeps the install's own exit status.

Every side effect is injectable (``save``, ``runner``, ``ask``), so the tests
never touch a real install, a network or the operator's configuration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

#: How long one ``se adapter`` refresh may take before it is reported as failed.
ADAPTER_TIMEOUT = 300

#: Agent contracts live one directory per agent under this repository folder.
AGENTS_SUBDIR = "AGENTS"

#: The agent roster the prompt lists, and the same one the adapters render.
MODE_GLOBAL = "global"
MODE_PER_AGENT = "per_agent"
MODE_SKIP = "skip"

#: Runtime names accepted by the installer mapped to the adapter sub-command.
_RUNTIME_ALIASES = {
    "opencode": "opencode",
    "codex": "codex",
    "claude_code": "claude-code",
    "claude": "claude-code",
    "deepseek": "deepseek",
    "deepseek_harness": "deepseek",
}

#: What a ``--runtimes`` value may say, for the error message.
_RUNTIME_EXPECTATION = "expected opencode, codex, claude_code or deepseek"


class ModelSelectionError(ValueError):
    """A model spec, agent assignment or request the installer must not accept."""


@dataclass(frozen=True)
class ModelSpec:
    """One ``provider/model[variant]`` selection, parsed and canonical."""

    provider: str
    model: str
    variant: Optional[str] = None

    def __str__(self) -> str:
        text = f"{self.provider}/{self.model}"
        if self.variant:
            text += f"[{self.variant}]"
        return text


def parse_model_spec(value) -> ModelSpec:
    """Parse ``provider/model`` (optionally ``provider/model[variant]``).

    Raises :class:`ModelSelectionError` for anything that is not a concrete
    selection. An empty string is rejected on purpose: silently turning it into
    a default model is exactly the behaviour this step must never have.
    """
    text = str(value or "").strip()
    if not text:
        raise ModelSelectionError("a model spec cannot be empty; use provider/model")
    if any(ch.isspace() for ch in text):
        raise ModelSelectionError(
            f"{text!r} contains whitespace; use provider/model"
        )

    variant: Optional[str] = None
    if text.endswith("]") and "[" in text:
        base, _, raw_variant = text.rpartition("[")
        variant = raw_variant[:-1].strip()
        if not base or not variant:
            raise ModelSelectionError(
                f"{text!r} is not provider/model[variant]"
            )
        text = base

    provider, separator, model = text.partition("/")
    provider = provider.strip()
    model = model.strip()
    if not separator or not provider or not model:
        raise ModelSelectionError(f"{text!r} is not provider/model")
    return ModelSpec(provider=provider, model=model, variant=variant or None)


def parse_agent_assignment(value) -> tuple[str, ModelSpec]:
    """Parse one ``NAME=provider/model`` assignment."""
    text = str(value or "").strip()
    name, separator, spec = text.partition("=")
    name = name.strip()
    if not separator or not name or not spec.strip():
        raise ModelSelectionError(
            f"{text!r} is not NAME=provider/model"
        )
    return name, parse_model_spec(spec)


def list_agents(project_root) -> list[str]:
    """The agent names declared by ``AGENTS/*/agent.json``, sorted by directory.

    The contract's ``name`` wins; the directory name is the fallback for a
    contract that cannot be read, so the prompt still lists the role. Private
    (``_``) folders are not agents.
    """
    agents_dir = Path(project_root) / AGENTS_SUBDIR
    names: list[str] = []
    for path in sorted(agents_dir.glob("*/agent.json")):
        name: Optional[str] = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            value = data.get("name")
            if isinstance(value, str) and value.strip():
                name = value.strip()
        name = name or path.parent.name
        if name and not name.startswith("_") and name not in names:
            names.append(name)
    return names


@dataclass
class ModelSelection:
    """What the operator chose for the model step.

    ``MODE_SKIP`` (the default) is a first-class answer: it means "configure no
    model at all", never "pick a default".
    """

    mode: str = MODE_SKIP
    global_model: Optional[str] = None
    agent_overrides: dict[str, str] = field(default_factory=dict)
    source: str = "cli"
    reason: str = ""

    @property
    def skipped(self) -> bool:
        return self.mode == MODE_SKIP


def _canonical(spec) -> str:
    return str(parse_model_spec(spec))


def selection_for_all(spec, source: str = "cli") -> ModelSelection:
    """One model every agent inherits (the global ``model`` key)."""
    return ModelSelection(
        mode=MODE_GLOBAL,
        global_model=_canonical(spec),
        source=source,
    )


def selection_per_agent(overrides: dict, source: str = "cli") -> ModelSelection:
    """One model per agent (``agents.<name>.model`` overrides)."""
    canonical = {}
    for name, spec in (overrides or {}).items():
        agent = str(name or "").strip()
        if not agent:
            raise ModelSelectionError("an agent override needs an agent name")
        canonical[agent] = _canonical(spec)
    if not canonical:
        raise ModelSelectionError("a per-agent selection needs at least one agent")
    return ModelSelection(
        mode=MODE_PER_AGENT,
        global_model=None,
        agent_overrides=canonical,
        source=source,
    )


def skipped_selection(reason: str = "", source: str = "cli") -> ModelSelection:
    """An explicit skip: nothing is written, nothing is configured."""
    return ModelSelection(mode=MODE_SKIP, source=source, reason=reason)


def selection_from_cli(
    model: Optional[str] = None,
    assignments: Optional[Sequence[str]] = None,
    agents: Optional[Iterable[str]] = None,
) -> Optional[ModelSelection]:
    """Build the selection from ``--model`` and ``--model-agent`` values.

    Returns ``None`` when neither flag was used: that absence is what tells the
    caller to ask (interactive) or to skip (non-interactive). Unknown agent
    names are rejected when the roster is known, so a typo cannot create a
    silent override nobody reads.
    """
    overrides: dict[str, str] = {}
    roster = list(agents) if agents is not None else None
    for raw in assignments or ():
        name, spec = parse_agent_assignment(raw)
        if roster is not None and name not in roster:
            expected = ", ".join(roster) if roster else "none"
            raise ModelSelectionError(
                f"unknown agent {name!r}; the roster is: {expected}"
            )
        overrides[name] = str(spec)

    global_model = _canonical(model) if model else None
    if global_model is None and not overrides:
        return None
    return ModelSelection(
        mode=MODE_PER_AGENT if overrides else MODE_GLOBAL,
        global_model=global_model,
        agent_overrides=overrides,
        source="cli",
    )


@dataclass
class ModelStepRequest:
    """The CLI/TUI request parsed from flags, before anything is installed."""

    selection: Optional[ModelSelection] = None
    ask: bool = False
    explicit_skip: bool = False

    @property
    def enabled(self) -> bool:
        """False only when nobody asked for the step at all."""
        return self.ask or self.selection is not None or self.explicit_skip


def request_from_args(args, agents: Optional[Iterable[str]] = None) -> ModelStepRequest:
    """Read ``--model`` / ``--model-agent`` / ``--no-model-step`` from parsed argv.

    Values are type-checked instead of truth-tested: argparse always supplies a
    real ``str``/``list``, and a test double must not be able to look like an
    explicit selection by accident.
    """
    model = getattr(args, "model", None)
    if not isinstance(model, str) or not model.strip():
        model = None
    raw_assignments = getattr(args, "model_agent", None)
    assignments: list[str] = []
    if isinstance(raw_assignments, (list, tuple)):
        assignments = [value for value in raw_assignments if isinstance(value, str)]
    no_step = getattr(args, "no_model_step", False) is True

    if no_step:
        if model or assignments:
            raise ModelSelectionError(
                "--no-model-step cannot be combined with --model or --model-agent"
            )
        return ModelStepRequest(explicit_skip=True)
    if model or assignments:
        return ModelStepRequest(
            selection=selection_from_cli(model, assignments, agents)
        )
    return ModelStepRequest(ask=True)


# --------------------------------------------------------------------------- #
# Interactive prompt
# --------------------------------------------------------------------------- #


def _ask_text(ask: Callable[[str], str], prompt: str) -> Optional[str]:
    """Read one answer; ``None`` when the input stream ended or was cancelled."""
    try:
        return str(ask(prompt))
    except (EOFError, KeyboardInterrupt):
        return None


def _ask_model_spec(
    ask: Callable[[str], str], prompt: str
) -> Optional[ModelSpec]:
    """Ask for one ``provider/model``; an empty answer means "skip"."""
    while True:
        raw = _ask_text(ask, prompt)
        if raw is None:
            return None
        if not raw.strip():
            return None
        try:
            return parse_model_spec(raw)
        except ModelSelectionError as exc:
            print(f"  {exc}")


def _ask_mode(ask: Callable[[str], str]) -> tuple[str, bool]:
    """Ask same-model / per-agent / skip. Returns ``(mode, stream_ended)``."""
    prompt = (
        "  1) Un mismo modelo para todos los agentes\n"
        "  2) Un modelo por subagente\n"
        "  3) Saltar (no configurar ningun modelo)\n"
        "  Elige [1/2/3]: "
    )
    while True:
        raw = _ask_text(ask, prompt)
        if raw is None:
            return MODE_SKIP, True
        choice = raw.strip() or "3"
        if choice == "1":
            return MODE_GLOBAL, False
        if choice == "2":
            return MODE_PER_AGENT, False
        if choice == "3":
            return MODE_SKIP, False
        print("  Opcion no valida; elige 1, 2 o 3.")


def prompt_for_selection(
    agents: Iterable[str],
    ask: Callable[[str], str] = input,
) -> ModelSelection:
    """Ask how the agents should be routed. Skipping is a first-class answer."""
    roster = list(agents)
    print("\n[MODELO] Seleccion de modelo (opcional)")
    print("  Elige un modelo para los agentes o salta el paso: no se")
    print("  configura ningun modelo si eliges 3.")

    mode, stream_ended = _ask_mode(ask)
    if stream_ended or mode == MODE_SKIP:
        reason = "the prompt ended" if stream_ended else "skipped in the prompt"
        return skipped_selection(reason=reason, source="prompt")

    if mode == MODE_GLOBAL:
        spec = _ask_model_spec(
            ask, "  Modelo para todos (provider/model, vacio = saltar): "
        )
        if spec is None:
            return skipped_selection(reason="no model entered", source="prompt")
        return selection_for_all(spec, source="prompt")

    if not roster:
        print("  No hay contratos de agente en AGENTS/; no hay nada que asignar.")
        return skipped_selection(reason="no agents found", source="prompt")

    print("\n  Un modelo por subagente. Vacio deja ese agente como estaba.\n")
    overrides: dict[str, str] = {}
    for name in roster:
        spec = _ask_model_spec(
            ask, f"  {name} (provider/model, vacio = sin cambio): "
        )
        if spec is not None:
            overrides[name] = str(spec)
    if not overrides:
        return skipped_selection(reason="no agent model entered", source="prompt")
    return selection_per_agent(overrides, source="prompt")


# --------------------------------------------------------------------------- #
# Persistence: the system's own store, then the generated layers
# --------------------------------------------------------------------------- #


def _load_se_core_module(project_root, dotted_name: str):
    """Import a module from the repository's ``SCRIPTS/`` package.

    The installer ships next to SE Core but does not depend on it being
    importable at start-up; the lockstep is created on demand here.
    """
    scripts = Path(project_root) / "SCRIPTS"
    if not scripts.is_dir():
        raise ModelSelectionError(
            f"SCRIPTS/ was not found under {project_root}; cannot reach the "
            "model selection store"
        )
    path = str(scripts)
    if path not in sys.path:
        sys.path.insert(0, path)
    import importlib

    return importlib.import_module(dotted_name)


def load_save_model_config(project_root) -> Callable:
    """Return the exact ``save_model_config`` the rest of the system uses."""
    module = _load_se_core_module(project_root, "se_core.model_tui.config")
    return module.save_model_config


def read_existing_selection(project_root) -> tuple[Optional[str], dict[str, str]]:
    """Read the selection already on disk through the system's own loader.

    Used only to *preserve* a global model when the operator sets per-agent
    overrides, so the installer never deletes a choice it was not asked about.
    """
    module = _load_se_core_module(project_root, "se_core.model_tui.config")
    config = module.load_model_config(Path(project_root))
    overrides: dict[str, str] = {}
    for name, override in config.agent_overrides.items():
        spec = _spec_from_override(override)
        if spec:
            overrides[str(name)] = spec
    global_model = config.global_model if isinstance(config.global_model, str) else None
    return global_model or None, overrides


def _spec_from_override(override) -> Optional[str]:
    provider = getattr(override, "provider", None)
    model = getattr(override, "model", None)
    variant = getattr(override, "variant", None)
    if provider and model:
        return str(ModelSpec(str(provider), str(model), str(variant) if variant else None))
    if model:
        return str(model)
    return None


def _override_dict(spec: ModelSpec) -> dict:
    """The ``agents.<name>.model`` object ``save_model_config`` writes."""
    value = {"providerID": spec.provider, "model": spec.model}
    if spec.variant:
        value["variant"] = spec.variant
    return value


def adapter_names_for(runtimes: Optional[Iterable[str]]) -> tuple[list[str], list[str]]:
    """Map the installer's runtime names to ``se adapter`` sub-commands."""
    names: list[str] = []
    errors: list[str] = []
    for runtime in runtimes or ():
        key = str(runtime or "").strip().lower().replace("-", "_")
        adapter = _RUNTIME_ALIASES.get(key)
        if adapter is None:
            errors.append(
                f"unknown runtime {runtime!r}; {_RUNTIME_EXPECTATION}"
            )
        elif adapter not in names:
            names.append(adapter)
    return names, errors


def adapter_command(project_root, adapter: str, python=None) -> list[str]:
    """The exact command that refreshes one generated layer."""
    return [
        str(python or sys.executable),
        str(Path(project_root) / "SCRIPTS" / "se.py"),
        "adapter",
        adapter,
    ]


def _tail(text: str, limit: int = 400) -> str:
    value = " ".join(str(text or "").split())
    return value[-limit:]


def _run_adapter(project_root, adapter: str, runner, python=None) -> dict:
    """Run one adapter refresh, converting every failure into a report entry."""
    command = adapter_command(project_root, adapter, python=python)
    entry = {
        "runtime": adapter,
        "command": command,
        "status": "FAIL",
        "returncode": None,
        "error": None,
    }
    se_cli = Path(command[1])
    if not se_cli.is_file():
        entry["error"] = f"se.py was not found: {se_cli}"
        return entry
    try:
        completed = runner(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=ADAPTER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        entry["error"] = f"timed out after {ADAPTER_TIMEOUT}s"
        return entry
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        entry["error"] = str(exc)
        return entry

    returncode = getattr(completed, "returncode", 1)
    entry["returncode"] = returncode
    if returncode == 0:
        entry["status"] = "PASS"
    else:
        entry["error"] = _tail(getattr(completed, "stderr", "")) or (
            f"adapter exited {returncode}"
        )
    return entry


def _report(selection: Optional[ModelSelection], roster: list[str], dry_run: bool) -> dict:
    return {
        "status": "skipped",
        "mode": getattr(selection, "mode", MODE_SKIP),
        "source": getattr(selection, "source", "cli"),
        "dry_run": bool(dry_run),
        "written": False,
        "global_model": None,
        "global_model_source": None,
        "agent_overrides": {},
        "agents": list(roster),
        "adapters": [],
        "errors": [],
        "reason": getattr(selection, "reason", ""),
    }


def _resolve_target(
    project_root, selection: ModelSelection, existing: Optional[Callable] = None
) -> tuple[Optional[str], dict[str, str], Optional[str]]:
    """The final state this selection asks for.

    Returns ``(global_model, overrides, source)`` where ``source`` says whether
    the global model was chosen now (``"selection"``) or preserved from the
    existing configuration (``"existing"``), so the report can be honest.
    """
    if selection.mode == MODE_GLOBAL:
        if not selection.global_model:
            raise ModelSelectionError("a same-model selection needs a model")
        # "One model for every agent" means every agent inherits it, so any
        # previous override would contradict the answer.
        return selection.global_model, dict(selection.agent_overrides), "selection"
    if selection.mode != MODE_PER_AGENT:
        raise ModelSelectionError(f"unknown selection mode {selection.mode!r}")

    # Per-agent overrides are an edit, not a reset: keep the global model the
    # operator already had and keep overrides for agents left blank.
    reader = existing or read_existing_selection
    existing_global, existing_overrides = reader(project_root)
    if selection.global_model is not None:
        target_global, source = selection.global_model, "selection"
    else:
        target_global, source = existing_global, "existing"
    merged = dict(existing_overrides)
    merged.update(selection.agent_overrides)
    return target_global, merged, source


def apply_selection(
    project_root,
    selection: Optional[ModelSelection],
    *,
    runtimes: Optional[Iterable[str]] = ("opencode",),
    dry_run: bool = False,
    save: Optional[Callable] = None,
    existing: Optional[Callable] = None,
    runner: Optional[Callable] = None,
    python=None,
) -> dict:
    """Write the selection (unless dry-run) and refresh the generated layers.

    Never raises: the returned report carries ``status``, what was written and
    every error that was collected. ``selection`` may be ``None`` or a skipped
    selection, in which case nothing is read and nothing is written.
    """
    project_root = Path(project_root)
    roster = list_agents(project_root)
    report = _report(selection, roster, dry_run)

    if selection is None or selection.skipped:
        report["reason"] = (
            (selection.reason if selection else "") or "no model configured"
        )
        return report

    adapter_names, adapter_errors = adapter_names_for(runtimes)
    report["errors"].extend(adapter_errors)

    try:
        target_global, target_overrides, global_source = _resolve_target(
            project_root, selection, existing
        )
    except Exception as exc:  # noqa: BLE001 - collected into the report
        report["status"] = "failed"
        report["errors"].append(f"cannot resolve the model selection: {exc}")
        return report

    report["global_model"] = target_global
    report["global_model_source"] = global_source
    report["agent_overrides"] = dict(target_overrides)
    report["adapters"] = [
        {
            "runtime": name,
            "command": adapter_command(project_root, name, python=python),
            "status": "planned",
            "returncode": None,
            "error": None,
        }
        for name in adapter_names
    ]

    if dry_run:
        report["status"] = "planned"
        return report

    if target_global is None and not target_overrides:
        # An empty answer must not create an empty configuration file.
        report["status"] = "skipped"
        report["reason"] = "no model was selected"
        report["adapters"] = []
        return report

    try:
        saver = save or load_save_model_config(project_root)
        overrides = {
            name: _override_dict(parse_model_spec(spec))
            for name, spec in target_overrides.items()
        }
        report["written"] = bool(saver(project_root, target_global, overrides))
    except Exception as exc:  # noqa: BLE001 - collected into the report
        report["status"] = "failed"
        report["errors"].append(f"could not save the model selection: {exc}")
        return report

    report["status"] = "configured"

    # Refresh the generated layers only once the selection is on disk.
    run = runner or subprocess.run
    adapters = [
        _run_adapter(project_root, name, run, python=python) for name in adapter_names
    ]
    report["adapters"] = adapters
    for entry in adapters:
        if entry["status"] != "PASS":
            report["errors"].append(
                f"{entry['runtime']} adapter failed: "
                f"{entry['error'] or entry['returncode']}"
            )
    return report


def run_model_step(
    request: ModelStepRequest,
    *,
    project_root,
    runtimes: Optional[Iterable[str]] = ("opencode",),
    dry_run: bool = False,
    interactive: bool = False,
    save: Optional[Callable] = None,
    existing: Optional[Callable] = None,
    runner: Optional[Callable] = None,
    ask: Callable[[str], str] = input,
    python=None,
) -> Optional[dict]:
    """Execute (or plan) the step for one request.

    Returns ``None`` when there is nothing to report: ``--no-model-step`` and a
    non-interactive run without model flags both leave the output untouched, so
    an automated install keeps its previous shape.
    """
    if request.explicit_skip:
        return None
    selection = request.selection
    if selection is None:
        if not interactive:
            return None
        try:
            selection = prompt_for_selection(list_agents(project_root), ask=ask)
        except Exception as exc:  # noqa: BLE001 - the install result stands
            return failure_report(
                None, f"the model prompt failed: {exc}"
            )
    try:
        return apply_selection(
            project_root,
            selection,
            runtimes=runtimes,
            dry_run=dry_run,
            save=save,
            existing=existing,
            runner=runner,
            python=python,
        )
    except Exception as exc:  # noqa: BLE001 - the install result stands
        return failure_report(selection, f"the model step failed: {exc}")


def not_run_report(
    selection: Optional[ModelSelection] = None,
    reason: str = "the installation did not succeed",
) -> dict:
    """Report a step that was requested but must not run (install failed)."""
    report = _report(selection, [], dry_run=False)
    report["status"] = "not-run"
    report["reason"] = reason
    return report


def failure_report(
    selection: Optional[ModelSelection] = None,
    reason: str = "the model step failed",
) -> dict:
    """Report a step that raised unexpectedly; nothing was written."""
    report = _report(selection, [], dry_run=False)
    report["status"] = "failed"
    report["reason"] = reason
    report["errors"].append(reason)
    return report


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _described_agents(report: dict) -> str:
    names = report.get("agent_overrides") or {}
    return ", ".join(f"{name}={spec}" for name, spec in sorted(names.items()))


def report_lines(report: dict) -> list[str]:
    """Human-readable lines for one report, in the installer's ``[TAG]`` style."""
    status = report.get("status")
    lines: list[str] = []
    if status == "skipped":
        lines.append(
            "[MODELO] Omitido: no se configura ningun modelo"
            + (f" ({report['reason']})" if report.get("reason") else "")
        )
        return lines
    if status == "not-run":
        lines.append(
            "[MODELO] No ejecutado: "
            + (report.get("reason") or "the installation did not succeed")
        )
        return lines

    prefix = {"planned": "[PLAN]", "failed": "[FAIL]"}.get(status, "[OK]")
    lines.append("[MODELO] Seleccion de modelo")
    if report.get("global_model"):
        if report.get("global_model_source") == "existing":
            note = "sin cambios; los agentes sin override lo heredan"
        else:
            note = "lo heredan todos los agentes"
        lines.append(
            f"  {prefix} Modelo global: {report['global_model']} ({note})"
        )
    overrides = _described_agents(report)
    if overrides:
        lines.append(f"  {prefix} Overrides: {overrides}")
    for entry in report.get("adapters") or []:
        if entry["status"] == "planned":
            lines.append(f"  {prefix} Capa a refrescar: {entry['runtime']}")
        elif entry["status"] == "PASS":
            lines.append(f"  [OK] Capa {entry['runtime']} refrescada")
        else:
            lines.append(
                f"  [FAIL] Capa {entry['runtime']}: "
                f"{entry.get('error') or entry.get('returncode')}"
            )
    if status == "planned":
        lines.append("  [SKIP] Dry run: no se escribe nada ni se ejecuta ningun adapter")
    elif status == "configured" and not report.get("written"):
        lines.append("  [OK] La seleccion ya estaba en ese estado; no hubo cambios")
    for error in report.get("errors") or []:
        lines.append(f"  [FAIL] {error}")
    return lines
