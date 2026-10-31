"""LLM Provider Factory for SYSTEM-ENGINEERING.

Creates LLM providers from agent configuration.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Type

from .providers import (
    LLMProvider,
    OpenAIProvider,
    AnthropicProvider,
    LocalProvider,
    DummyProvider,
)


# Provider registry: name -> provider class
PROVIDER_REGISTRY: Dict[str, Type] = {
    "openai": None,  # Will be set after import
    "anthropic": None,
    "local": None,
    "ollama": None,
    "vllm": None,
    "dummy": None,
}

# Lazy import to avoid circular imports
def _get_provider_classes() -> Dict[str, Type]:
    """Lazy load provider classes to avoid circular imports."""
    global PROVIDER_REGISTRY
    if PROVIDER_REGISTRY.get("openai") is None:
        from .providers import (
            OpenAIProvider,
            AnthropicProvider,
            LocalProvider,
            DummyProvider,
        )
        PROVIDER_REGISTRY = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "local": LocalProvider,
            "ollama": LocalProvider,  # alias
            "vllm": LocalProvider,
            "dummy": DummyProvider,
        }
    return PROVIDER_REGISTRY


def create_provider(
    provider: str,
    model: str,
    **kwargs
) -> "LLMProvider":
    """Create an LLM provider instance.
    
    Args:
        provider: Provider name (openai, anthropic, local, ollama, vllm, dummy)
        model: Model name
        **kwargs: Additional provider-specific arguments
            - api_key: API key (or from env)
            - base_url: Base URL for local/custom endpoints
            - organization: Organization ID (OpenAI)
            - **kwargs: Passed to provider constructor
    
    Returns:
        LLMProvider instance
    
    Raises:
        ValueError: If provider is unknown
        ImportError: If required package not installed
    """
    provider = provider.lower().strip()
    registry = _get_provider_classes()
    
    if provider not in registry:
        available = ", ".join(sorted(_get_provider_classes().keys()))
        raise ValueError(
            f"Unknown provider: '{provider}'. Available: {available}"
        )
    
    provider_cls = _get_provider_classes()[provider]
    return provider_cls(model=model, **kwargs)


def llm_config_from_env(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Build an LLM configuration dict from environment variables.

    This is the single, process-level default that lets a real provider be
    reachable without declaring ``llm_config`` in every ``agent.json``. It
    returns the same shape ``create_provider_from_config`` consumes:

    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.3,           # optional
        "max_tokens": 4096,           # optional
        "provider_options": {         # optional
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
        },
    }

    ``SE_LLM_PROVIDER`` and ``SE_LLM_MODEL`` are all-or-nothing: setting only
    one of them raises ``ValueError`` instead of silently degrading to the
    dummy provider. An entirely unset environment returns ``None`` so the
    caller can apply its own fallback.

    Args:
        env: Mapping to read from. Defaults to ``os.environ``. This function
            never reads the process environment when ``env`` is provided.

    Returns:
        The configuration dict, or ``None`` when no LLM variable is set.

    Raises:
        ValueError: If exactly one of provider/model is set, or if an optional
            numeric variable cannot be parsed.
    """
    source: Mapping[str, str] = os.environ if env is None else env

    def _read(name: str) -> str:
        value = source.get(name)
        if value is None:
            return ""
        return str(value).strip()

    provider = _read("SE_LLM_PROVIDER")
    model = _read("SE_LLM_MODEL")

    if not provider and not model:
        return None
    if not provider:
        raise ValueError(
            "SE_LLM_MODEL is set but SE_LLM_PROVIDER is not; "
            "set both or neither."
        )
    if not model:
        raise ValueError(
            "SE_LLM_PROVIDER is set but SE_LLM_MODEL is not; "
            "set both or neither."
        )

    config: Dict[str, Any] = {"provider": provider.lower(), "model": model}

    temperature_raw = _read("SE_LLM_TEMPERATURE")
    if temperature_raw:
        try:
            config["temperature"] = float(temperature_raw)
        except ValueError:
            raise ValueError(
                "SE_LLM_TEMPERATURE must be a number, "
                f"got {temperature_raw!r}"
            ) from None

    max_tokens_raw = _read("SE_LLM_MAX_TOKENS")
    if max_tokens_raw:
        try:
            config["max_tokens"] = int(max_tokens_raw)
        except ValueError:
            raise ValueError(
                "SE_LLM_MAX_TOKENS must be an integer, "
                f"got {max_tokens_raw!r}"
            ) from None

    provider_options: Dict[str, str] = {}
    api_key_env = _read("SE_LLM_API_KEY_ENV")
    if api_key_env:
        provider_options["api_key_env"] = api_key_env
    base_url = _read("SE_LLM_BASE_URL")
    if base_url:
        provider_options["base_url"] = base_url
    if provider_options:
        config["provider_options"] = provider_options

    return config


def create_provider_from_config(config: Dict[str, Any]) -> "LLMProvider":
    """Create provider from agent configuration dict.
    
    Expected config format:
    {
        "provider": "openai|anthropic|local|ollama|vllm|dummy",
        "model": "model-name",
        "temperature": 0.3,
        "max_tokens": 4096,
        "provider_options": {
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "organization": "org-id"
        }
    }
    
    Args:
        config: Agent LLM configuration dict
        
    Returns:
        LLMProvider instance
    """
    provider = config.get("provider", "").lower()
    model = config.get("model", "")
    
    if not provider or not model:
        raise ValueError("Provider and model required in LLM config")
    
    # Build kwargs from config
    kwargs = {
        "temperature": config.get("temperature", 0.3),
        "max_tokens": config.get("max_tokens", 4096),
    }
    
    # Add provider options
    provider_options = config.get("provider_options", {})
    
    # Handle API key from env var
    api_key_env = provider_options.get("api_key_env")
    if api_key_env:
        import os
        api_key = os.environ.get(api_key_env)
        if api_key:
            kwargs["api_key"] = api_key
    
    # Base URL for local/custom endpoints
    base_url = provider_options.get("base_url")
    if base_url:
        kwargs["base_url"] = base_url
    
    # Organization (OpenAI)
    org = provider_options.get("organization")
    if org:
        kwargs["organization"] = org
    
    # API key directly
    api_key = provider_options.get("api_key")
    if api_key:
        kwargs["api_key"] = api_key
    
    return create_provider(provider=provider, model=config["model"], **kwargs)


def register_provider(name: str, provider_cls: type) -> None:
    """Register a custom provider class.
    
    Args:
        name: Provider name (lowercase)
        provider_cls: Provider class (must inherit from LLMProvider)
    """
    global PROVIDER_REGISTRY
    if not issubclass(provider_cls, LLMProvider):
        raise ValueError("Provider class must inherit from LLMProvider")
    _get_provider_classes()[name.lower()] = provider_cls


def list_providers() -> Dict[str, Dict[str, Any]]:
    """List available providers with metadata."""
    registry = _get_provider_classes()
    return {
        name: {
            "class": cls.__name__,
            "module": cls.__module__,
        }
        for name, cls in registry.items()
    }


def get_provider_for_model(model: str) -> str:
    """Guess provider from model name (heuristic)."""
    model_lower = model.lower()
    
    if model_lower.startswith(("gpt-", "o1", "o3")):
        return "openai"
    elif model_lower.startswith(("claude-", "claude_")):
        return "anthropic"
    elif model_lower.startswith(("llama", "mistral", "codellama", "phi", "gemma", "qwen")):
        return "local"
    elif model_lower.startswith("gpt"):
        return "openai"
    elif model_lower.startswith("claude"):
        return "anthropic"
    
    # Default to local for unknown models
    return "local"
