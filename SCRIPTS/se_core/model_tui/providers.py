"""Provider discovery from OpenCode runtime."""

from __future__ import annotations

import asyncio
import json
import subprocess
import httpx
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ModelInfo:
    """Model information from OpenCode."""
    id: str
    name: str
    family: str = ""
    input_cost: float = 0.0
    output_cost: float = 0.0
    tool_call: bool = False
    reasoning: bool = False
    vision: bool = False
    effort_levels: list[str] = field(default_factory=list)


@dataclass
class ProviderInfo:
    """Provider information from OpenCode."""
    id: str
    name: str
    models: list[ModelInfo] = field(default_factory=list)
    connected: bool = False


async def discover_providers(project_root: Path) -> list[ProviderInfo]:
    """Discover providers and models from OpenCode runtime.

    Tries multiple methods in order:
    1. HTTP API (if OpenCode server is running)
    2. CLI `opencode api get /api/providers`
    3. CLI `opencode model list` (fallback)
    """
    # Try HTTP API first
    providers = await _discover_via_api(project_root)
    if providers:
        return providers

    # Fallback to CLI
    return await _discover_via_cli(project_root)


async def _discover_via_api(project_root: Path) -> list[ProviderInfo]:
    """Discover via OpenCode HTTP API."""
    try:
        # Try to find running OpenCode server
        # Default port is 49374 but can vary
        ports = [49374, 49375, 49376, 49377, 49378]
        for port in ports:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"http://localhost:{port}/api/providers")
                    if resp.status_code == 200:
                        return _parse_providers_api(resp.json())
            except Exception:
                continue
    except Exception:
        pass
    return []


async def _discover_via_cli(project_root: Path) -> list[ProviderInfo]:
    """Discover via `opencode models` CLI."""
    try:
        # On Windows, opencode is a .ps1 script, so run via cmd /c
        import sys
        if sys.platform == "win32":
            cmd = ["cmd", "/c", "opencode", "models"]
        else:
            cmd = ["opencode", "models"]

        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _parse_model_list_text(result.stdout)
    except Exception:
        pass

    return []


def _parse_providers_api(data: dict) -> list[ProviderInfo]:
    """Parse providers from OpenCode API response."""
    providers = []
    for provider_id, provider_data in data.items():
        models = []
        for model_data in provider_data.get("models", []):
            models.append(ModelInfo(
                id=model_data.get("id", ""),
                name=model_data.get("name", model_data.get("id", "")),
                family=model_data.get("family", ""),
                input_cost=model_data.get("cost", {}).get("input", 0.0),
                output_cost=model_data.get("cost", {}).get("output", 0.0),
                tool_call=model_data.get("tool_call", False),
                reasoning=model_data.get("reasoning", False),
                vision=model_data.get("vision", False),
                effort_levels=model_data.get("effort_levels", []),
            ))
        providers.append(ProviderInfo(
            id=provider_id,
            name=provider_data.get("name", provider_id),
            models=models,
            connected=provider_data.get("connected", False),
        ))
    return providers


def _parse_model_list_text(output: str) -> list[ProviderInfo]:
    """Parse `opencode models` text output (one model per line)."""
    try:
        lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
        if not lines:
            return []

        # Group by provider prefix (e.g., "nvidia/", "opencode/")
        by_provider: dict[str, list[str]] = {}
        for line in lines:
            if "/" in line:
                provider = line.split("/")[0]
                if provider not in by_provider:
                    by_provider[provider] = []
                by_provider[provider].append(line)

        providers = []
        for provider_id, models in by_provider.items():
            model_infos = []
            for model in models:
                model_infos.append(ModelInfo(
                    id=model,
                    name=model,
                ))
            providers.append(ProviderInfo(
                id=provider_id,
                name=provider_id,
                models=model_infos,
                connected=True,
            ))
        return providers
    except Exception:
        pass
    return []


def _parse_model_list(output: str) -> list[ProviderInfo]:
    """Parse `opencode model list --json` output (legacy)."""
    try:
        data = json.loads(output)
        if isinstance(data, list):
            # Group by provider
            by_provider: dict[str, list] = {}
            for item in data:
                provider = item.get("provider", "unknown")
                if provider not in by_provider:
                    by_provider[provider] = []
                by_provider[provider].append(item)

            providers = []
            for provider_id, models in by_provider.items():
                model_infos = []
                for m in models:
                    model_infos.append(ModelInfo(
                        id=m.get("model", ""),
                        name=m.get("model", ""),
                        effort_levels=m.get("variants", []),
                    ))
                providers.append(ProviderInfo(
                    id=provider_id,
                    name=provider_id,
                    models=model_infos,
                    connected=True,
                ))
            return providers
    except Exception:
        pass
    return []


# Default providers when OpenCode is not available
DEFAULT_PROVIDERS = [
    ProviderInfo(
        id="anthropic",
        name="Anthropic",
        connected=False,
        models=[
            ModelInfo(id="claude-sonnet-5-5", name="Claude Sonnet 5.5", effort_levels=["high", "medium", "low"]),
            ModelInfo(id="claude-sonnet-5-5#high", name="Claude Sonnet 5.5 (high)", effort_levels=[]),
            ModelInfo(id="claude-sonnet-5-5#medium", name="Claude Sonnet 5.5 (medium)", effort_levels=[]),
            ModelInfo(id="claude-sonnet-5-5#low", name="Claude Sonnet 5.5 (low)", effort_levels=[]),
            ModelInfo(id="claude-haiku-3.5", name="Claude Haiku 3.5", effort_levels=[]),
            ModelInfo(id="claude-opus-4", name="Claude Opus 4", effort_levels=[]),
        ],
    ),
    ProviderInfo(
        id="openai",
        name="OpenAI",
        connected=False,
        models=[
            ModelInfo(id="gpt-4o", name="GPT-4o", effort_levels=[]),
            ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", effort_levels=[]),
            ModelInfo(id="gpt-4.1", name="GPT-4.1", effort_levels=[]),
            ModelInfo(id="gpt-4.1-mini", name="GPT-4.1 Mini", effort_levels=[]),
            ModelInfo(id="o1-preview", name="o1 Preview", effort_levels=["high", "medium", "low"]),
            ModelInfo(id="o1-mini", name="o1 Mini", effort_levels=[]),
        ],
    ),
    ProviderInfo(
        id="google",
        name="Google",
        connected=False,
        models=[
            ModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash", effort_levels=[]),
            ModelInfo(id="gemini-2.0-pro", name="Gemini 2.0 Pro", effort_levels=[]),
            ModelInfo(id="gemini-1.5-pro", name="Gemini 1.5 Pro", effort_levels=[]),
        ],
    ),
]


def get_default_providers() -> list[ProviderInfo]:
    """Get default provider list when OpenCode is not available."""
    return DEFAULT_PROVIDERS