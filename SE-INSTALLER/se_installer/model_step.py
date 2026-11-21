"""MODEL SELECTION step for the SE Installer (shared by CLI and Web UI).

This module handles the MODEL SELECTION step that runs after a successful
installation. It writes the model selection to opencode.jsonc using the same
storage that `se shema-ai model` uses.

The selection is made at the harness level (opencode.jsonc), not in agent.json,
so it applies to all agents unless overridden per-agent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from se_core.model_tui.config import (
    load_model_config,
    save_model_config,
    resolve_agent_model,
    ModelSelectionError,
    ModelConfig,
    AgentModelOverride,
)


def list_agents(repo_root: Path) -> list[str]:
    """Return the list of agent names from AGENTS/ directory."""
    agents_dir = Path(repo_root) / "AGENTS"
    if not agents_dir.exists():
        return []
    return sorted([d.name for d in agents_dir.iterdir() if d.is_dir()])


def describe_selection(repo_root: Path, prefill: Optional[str] = None, model_step_disabled: bool = False, runtimes: Optional[list[str]] = None) -> dict:
    """Return the current model selection state for the UI."""
    config = load_model_config(Path(repo_root))
    roster = list_agents(Path("."))
    
    overrides = {}
    for name, override in config.agent_overrides.items():
        if override.provider or override.model:
            provider = override.provider or ""
            model = override.model or ""
            overrides[name] = f"{provider}/{model}" if provider and "/" not in model else model
    
    global_model = config.global_model
    if prefill:
        global_model = prefill
    
    return {
        "global_model": global_model,
        "agent_overrides": overrides,
        "apply_to_all": getattr(config, "apply_to_all", True),
        "roster": roster,
        "prefill": prefill,
        "model_step_disabled": model_step_disabled,
        "runtimes": runtimes or ["opencode"],
    }


def apply_selection(
    project_root: Path,
    global_spec: Optional[str] = None,
    agents: Optional[dict[str, str]] = None,
    skip: bool = False,
    save: bool = True,
    runtimes: Optional[list[str]] = None,
    python: Optional[str] = None,
    runner = None,
) -> dict:
    """Apply a model selection from the web UI.
    
    Args:
        project_root: Path to the project root
        global_spec: Global model spec (provider/model)
        agents: Dict of agent_name -> model_spec
        skip: If True, write nothing (skip the step)
        save: If False, only report what would be written
        runtimes: List of runtimes to refresh (opencode, claude-code, codex, etc.)
        python: Python interpreter to use for adapter generation
        runner: Optional subprocess runner for dry-run
    
    Returns:
        Dict with status, written flag, errors, adapters, etc.
    """
    from se_core.runtimes import generate_all
    from se_core.model_tui.config import save_model_config, load_model_config
    
    root = Path(project_root)
    
    if skip:
        return {
            "status": "skipped",
            "written": False,
            "errors": [],
            "adapters": [],
            "runtimes_refreshed": [],
            "message": "Model step skipped by user",
        }
    
    if global_spec is None and not agents:
        # Empty body = clear selection
        load_func, _, save_func = _load_store()
        written = save_func(root, None, {})
        adapters, errors = refresh_layers(root, runtimes, python=python)
        return {
            "status": "cleared",
            "written": written,
            "errors": errors,
            "adapters": adapters,
            "runtimes_refreshed": runtimes or [],
        }
    
    # Validate roster
    roster = list_agents(root)
    for agent_name in (agents or {}).keys():
        if agent_name not in roster:
            raise HTTPException(status_code=400, detail=f"Unknown agent: {agent_name}")
        spec = (agents or {})[agent_name]
        if spec and "/" not in spec:
            raise HTTPException(status_code=400, detail=f"Agent model for {agent_name} must be provider/model format")
    
    # Apply via save_model_config
    from se_core.model_tui.config import save_model_config, AgentModelOverride
    
    # Convert string specs to AgentModelOverride objects
    agent_objs = {}
    if agents:
        for agent_name, spec in agents.items():
            if spec:
                if "/" in spec:
                    provider, model = spec.split("/", 1)
                else:
                    provider, model = "", spec
                agent_objs[agent_name] = AgentModelOverride(
                    provider=provider if provider else None,
                    model=model,
                )
    
    written = save_model_config(root, global_spec, agent_objs)
    
    # Refresh adapter layers
    adapters, errors = refresh_layers(root, runtimes or ["opencode"])
    
    return _response(root, "configured", written, errors, adapters, runtimes or ["opencode"])


def _load_store():
    """Lazy import to avoid circular imports."""
    from se_core.model_tui.config import load_model_config, resolve_agent_model, save_model_config
    return load_model_config, resolve_agent_model, save_model_config


def selection_from(global_spec: Optional[str], agents: Optional[dict[str, str]], roster: list[str]) -> dict:
    """Build a selection dict from the provided specs."""
    from se_installer.model_step import apply_selection as _apply_selection
    from se_core.model_tui.config import ModelConfig
    
    selection = ModelConfig()
    if global_spec:
        provider, _, model_id = global_spec.partition("/")
        if not model_id:
            provider, model_id = "", provider
        selection.global_model = f"{provider}/{model_id}" if provider and "/" not in model_id else model_id
    
    if agents:
        for agent_name, spec in agents.items():
            if spec:
                if "/" in spec:
                    provider, model = spec.split("/", 1)
                else:
                    provider, model = "", spec
                from se_core.model_tui.config import AgentModelOverride
                # We'll let apply_selection handle the override creation
                pass
    
    # For now, return a simple dict that apply_selection can use
    # The actual implementation will use model_step.apply_selection
    return {}


def refresh_layers(project_root: Path, runtimes: Optional[list[str]], python: Optional[str] = None, runner=None) -> tuple[list[dict], list[str]]:
    """Refresh the generated adapter layers for the given runtimes."""
    from se_core import runtimes as rt
    
    runtimes = runtimes or ["opencode"]
    adapter_map = {
        "opencode": "opencode",
        "codex": "codex", 
        "claude-code": "claude_code",
        "deepseek": "deepseek",
        "pi": "pi",
        "hermes": "hermes",
    }
    
    selected = [r for r in runtimes if r in adapter_map]
    
    adapter_errors = []
    refreshed = []
    
    for rt in selected:
        try:
            gen_func = getattr(rt, f"generate_{adapter_map[rt]}")
            result = gen_func(Path("."), Path("."), dry_run=False)
            refreshed.append(rt)
        except Exception as e:
            adapter_errors.append(f"{rt}: {e}")
    
    return [{"adapter": rt, "status": "ok"} for rt in refreshed], adapter_errors


def _response(root: Path, status: str, written: bool, errors: list[str], adapters: list, runtimes: list[str]) -> dict:
    """Build the standard response for the model step."""
    from se_core.model_tui.config import load_model_config
    
    config = load_model_config(Path("."))
    return {
        "status": status,
        "written": written,
        "errors": errors,
        "adapters": adapters,
        "runtimes_refreshed": runtimes,
        "selection": {
            "global": config.global_model,
            "agents": {k: v.to_dict() for k, v in config.agent_overrides.items()},
        }
    }


class ModelSelectionError(Exception):
    """Raised when the model selection is invalid."""
    pass


def _load_store():
    from se_core.model_tui.config import load_model_config, save_model_config
    return load_model_config, None, save_model_config


def list_agents(repo_root: Path) -> list[str]:
    """Return the list of agent names from AGENTS/ directory."""
    agents_dir = Path(repo_root) / "AGENTS"
    if not agents_dir.exists():
        return []
    return sorted([d.name for d in agents_dir.iterdir() if d.is_dir()])


def resolve_agent_model(project_root: Path, agent_name: str) -> Optional[str]:
    """Resolve the model for a specific agent from the project's opencode.jsonc."""
    from se_core.model_tui.config import resolve_agent_model as _resolve
    return _resolve(project_root, agent_name)


def save_model_config(project_root: Path, global_model: Optional[str], agent_overrides: dict) -> bool:
    """Save model configuration to opencode.jsonc."""
    from se_core.model_tui.config import save_model_config as _save
    return _save(Path(project_root), global_model, agent_overrides)


def load_model_config(project_root: Path):
    """Load model configuration from opencode.jsonc."""
    from se_core.model_tui.config import load_model_config as _load
    return _load(Path(project_root))




