"""LLM Provider Factory for SYSTEM-ENGINEERING.

Creates LLM providers from agent configuration.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Type

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
