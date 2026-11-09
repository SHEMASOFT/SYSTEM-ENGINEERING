"""Model configuration persistence for opencode.jsonc."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import httpx


@dataclass
class AgentModelOverride:
    """Override for a specific agent's model."""
    provider: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None

    def to_dict(self) -> dict:
        result = {}
        if self.provider:
            result["providerID"] = self.provider
        if self.model:
            result["model"] = self.model
        if self.variant:
            result["variant"] = self.variant
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "AgentModelOverride":
        return cls(
            provider=data.get("providerID"),
            model=data.get("model"),
            variant=data.get("variant"),
        )


@dataclass
class ModelConfig:
    """Model configuration from opencode.jsonc."""
    global_model: str = "anthropic/claude-sonnet-5-5"
    agent_overrides: dict[str, AgentModelOverride] = field(default_factory=dict)

    @classmethod
    def from_opencode_config(cls, config: dict) -> "ModelConfig":
        """Parse model config from opencode.jsonc."""
        global_model = config.get("model", "anthropic/claude-sonnet-5-5")
        agent_overrides = {}

        agents = config.get("agents", {})
        for agent_name, agent_config in agents.items():
            if isinstance(agent_config, dict) and "model" in agent_config:
                model_config = agent_config["model"]
                if isinstance(model_config, dict):
                    agent_overrides[agent_name] = AgentModelOverride(
                        provider=model_config.get("providerID"),
                        model=model_config.get("model"),
                        variant=model_config.get("variant"),
                    )
                elif isinstance(model_config, str):
                    # Simple string format "provider/model"
                    parts = model_config.split("/", 1)
                    agent_overrides[agent_name] = AgentModelOverride(
                        provider=parts[0] if len(parts) > 1 else None,
                        model=parts[1] if len(parts) > 1 else model_config,
                    )

        return cls(global_model=global_model, agent_overrides=agent_overrides)

    def to_opencode_config(self) -> dict:
        """Convert to opencode.jsonc format."""
        config = {"model": self.global_model}
        if self.agent_overrides:
            config["agents"] = {}
            for agent_name, override in self.agent_overrides.items():
                if override.provider or override.model:
                    model_dict = override.to_dict()
                    if model_dict:
                        config["agents"][agent_name] = {"model": model_dict}
        return config


def _parse_jsonc(content: str) -> dict:
    """Parse JSONC content (strip comments properly - not inside strings)."""
    lines = []
    in_string = False
    escape_next = False
    for line in content.splitlines():
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"' and not escape_next:
                in_string = not in_string
            elif ch == '\\' and not escape_next:
                escape_next = True
                i += 1
                continue
            elif ch == '/' and i + 1 < len(line) and line[i + 1] == '/' and not in_string:
                line = line[:i]
                break
            escape_next = False
            i += 1
        stripped = line.strip()
        if stripped and not stripped.startswith("//"):
            lines.append(line)
    cleaned = "\n".join(lines)
    return json.loads(cleaned)


def load_model_config(project_root: Path) -> ModelConfig:
    """Load model configuration from opencode.jsonc."""
    config_path = project_root / "opencode.jsonc"
    if not config_path.exists():
        # Try .opencode/opencode.jsonc
        config_path = project_root / ".opencode" / "opencode.jsonc"
        if not config_path.exists():
            return ModelConfig()

    try:
        content = config_path.read_text(encoding="utf-8")
        config = _parse_jsonc(content)
        return ModelConfig.from_opencode_config(config)
    except Exception:
        return ModelConfig()


def save_model_config(
    project_root: Path,
    global_model: str,
    agent_overrides: dict,
) -> None:
    """Save model configuration to opencode.jsonc."""
    config_path = project_root / "opencode.jsonc"
    if not config_path.exists():
        config_path = project_root / ".opencode" / "opencode.jsonc"
        if not config_path.exists():
            # Create new config
            config_path = project_root / "opencode.jsonc"
            config = {"model": global_model}
        else:
            config = _parse_jsonc(config_path.read_text(encoding="utf-8"))
    else:
        config = _parse_jsonc(config_path.read_text(encoding="utf-8"))

    # Update config
    config["model"] = global_model
    if agent_overrides:
        config.setdefault("agents", {})
        for agent_name, override in agent_overrides.items():
            model_dict = override.to_dict()
            if model_dict:
                config["agents"][agent_name] = {"model": model_dict}
        # Remove agents not in agent_overrides
        existing_agents = list(config["agents"].keys())
        for agent_name in existing_agents:
            if agent_name not in agent_overrides:
                del config["agents"][agent_name]
    else:
        # No overrides provided - remove all agents
        config.pop("agents", None)

    # Write back preserving formatting as much as possible
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


async def reload_opencode_config(project_root: Path) -> bool:
    """Trigger OpenCode hot reload via API."""
    # Try HTTP API
    ports = [49374, 49375, 49376, 49377, 49378]
    for port in ports:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"http://localhost:{port}/api/config/reload")
                if resp.status_code == 200:
                    return True
        except Exception:
            continue

    # Try CLI
    try:
        result = subprocess.run(
            ["opencode", "config", "reload"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        pass

    return False


import subprocess  # noqa: E402