"""Model Registry - Registro de modelos disponibles para agentes."""

from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path
import json


class ModelProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"  # Ollama, vLLM, LM Studio
    OPENROUTER = "openrouter"
    FREE = "free"  # Modelos gratuitos via OpenRouter u otros


class ModelCapability(str, Enum):
    CHAT = "chat"
    CODE = "code"
    REASONING = "reasoning"
    TOOLS = "tools"  # Function calling
    VISION = "vision"
    LONG_CONTEXT = "long_context"


@dataclass
class Model:
    """Definición de un modelo disponible."""
    id: str
    name: str
    provider: ModelProvider
    capabilities: list[ModelCapability] = field(default_factory=list)
    context_window: int = 4096
    max_output: int = 4096
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    is_free: bool = False
    description: str = ""
    # Para OpenCode: modelo ID exacto que usa el provider
    provider_model_id: str = ""
    # Configuración de parámetros por defecto
    default_temperature: float = 0.3
    default_max_tokens: int = 4096
    # Metadatos
    tags: list[str] = field(default_factory=list)
    
    def supports(self, capability: ModelCapability) -> bool:
        return capability in self.capabilities
    
    def to_opencode_config(self) -> dict:
        """Genera configuración para OpenCode."""
        return {
            "provider": self.provider.value,
            "model": self.provider_model_id or self.id,
            "temperature": self.default_temperature,
            "max_tokens": self.default_max_tokens,
        }


# Modelos predefinidos (extensibles por usuario)
BUILTIN_MODELS = {
    # Modelos gratuitos (OpenRouter free tier)
    "deepseek-r1-free": Model(
        id="deepseek-r1-free",
        name="DeepSeek R1 (Free)",
        provider=ModelProvider.FREE,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.REASONING, ModelCapability.TOOLS],
        context_window=16384,
        max_output=4096,
        is_free=True,
        description="DeepSeek R1 razonamiento avanzado, gratis via OpenRouter",
        provider_model_id="deepseek/deepseek-r1:free",
        tags=["reasoning", "free", "openrouter"],
    ),
    "llama-3.1-8b-free": Model(
        id="llama-3.1-8b-free",
        name="Llama 3.1 8B (Free)",
        provider=ModelProvider.FREE,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.TOOLS],
        context_window=8192,
        max_output=4096,
        is_free=True,
        description="Meta Llama 3.1 8B, rápido y eficiente",
        provider_model_id="meta-llama/llama-3.1-8b-instruct:free",
        tags=["fast", "free", "openrouter"],
    ),
    "qwen-2.5-coder-free": Model(
        id="qwen-2.5-coder-free",
        name="Qwen 2.5 Coder (Free)",
        provider=ModelProvider.FREE,
        capabilities=[ModelCapability.CODE, ModelCapability.TOOLS],
        context_window=32768,
        max_output=8192,
        is_free=True,
        description="Especializado en código, contexto largo",
        provider_model_id="qwen/qwen-2.5-coder-32b-instruct:free",
        tags=["coding", "free", "long-context", "openrouter"],
    ),
    "gemini-flash-free": Model(
        id="gemini-flash-free",
        name="Gemini 1.5 Flash (Free)",
        provider=ModelProvider.FREE,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.TOOLS, ModelCapability.VISION],
        context_window=1000000,
        max_output=8192,
        is_free=True,
        description="Google Gemini Flash, contexto masivo gratis",
        provider_model_id="google/gemini-flash-1.5:free",
        tags=["vision", "long-context", "free", "openrouter"],
    ),
    
    # OpenAI
    "gpt-4o": Model(
        id="gpt-4o",
        name="GPT-4o",
        provider=ModelProvider.OPENAI,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.REASONING, ModelCapability.TOOLS, ModelCapability.VISION],
        context_window=128000,
        max_output=16384,
        cost_per_1k_input=0.005,
        cost_per_1k_output=0.015,
        description="Modelo flagship multimodal de OpenAI",
        provider_model_id="gpt-4o",
        tags=["flagship", "vision", "reasoning"],
    ),
    "gpt-4o-mini": Model(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        provider=ModelProvider.OPENAI,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.TOOLS, ModelCapability.VISION],
        context_window=128000,
        max_output=16384,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        description="Versión económica y rápida de GPT-4o",
        provider_model_id="gpt-4o-mini",
        tags=["cheap", "fast", "vision"],
    ),
    "o1-preview": Model(
        id="o1-preview",
        name="o1 Preview",
        provider=ModelProvider.OPENAI,
        capabilities=[ModelCapability.REASONING, ModelCapability.CODE, ModelCapability.TOOLS],
        context_window=128000,
        max_output=32768,
        cost_per_1k_input=0.015,
        cost_per_1k_output=0.06,
        description="Modelo de razonamiento avanzado",
        provider_model_id="o1-preview",
        tags=["reasoning", "advanced"],
    ),
    
    # Anthropic
    "claude-3.5-sonnet": Model(
        id="claude-3.5-sonnet",
        name="Claude 3.5 Sonnet",
        provider=ModelProvider.ANTHROPIC,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.REASONING, ModelCapability.TOOLS, ModelCapability.VISION],
        context_window=200000,
        max_output=8192,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        description="Mejor modelo para coding y razonamiento",
        provider_model_id="claude-3-5-sonnet-20241022",
        tags=["coding", "reasoning", "vision"],
    ),
    "claude-3.5-haiku": Model(
        id="claude-3.5-haiku",
        name="Claude 3.5 Haiku",
        provider=ModelProvider.ANTHROPIC,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.TOOLS],
        context_window=200000,
        max_output=8192,
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.005,
        description="Rápido y económico",
        provider_model_id="claude-3-5-haiku-20241022",
        tags=["fast", "cheap"],
    ),
    
    # Local (Ollama/vLLM)
    "llama-3.1-8b-local": Model(
        id="llama-3.1-8b-local",
        name="Llama 3.1 8B (Local)",
        provider=ModelProvider.LOCAL,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.TOOLS],
        context_window=131072,
        max_output=4096,
        is_free=True,
        description="Ejecuta localmente via Ollama/vLLM",
        provider_model_id="llama3.1:8b",
        tags=["local", "privacy", "free"],
    ),
    "qwen2.5-coder-local": Model(
        id="qwen2.5-coder-local",
        name="Qwen 2.5 Coder (Local)",
        provider=ModelProvider.LOCAL,
        capabilities=[ModelCapability.CODE, ModelCapability.TOOLS],
        context_window=32768,
        max_output=8192,
        is_free=True,
        description="Especializado en código, local",
        provider_model_id="qwen2.5-coder:32b",
        tags=["coding", "local", "free"],
    ),
    "deepseek-r1-local": Model(
        id="deepseek-r1-local",
        name="DeepSeek R1 (Local)",
        provider=ModelProvider.LOCAL,
        capabilities=[ModelCapability.REASONING, ModelCapability.CODE, ModelCapability.TOOLS],
        context_window=131072,
        max_output=8192,
        is_free=True,
        description="Razonamiento avanzado local",
        provider_model_id="deepseek-r1:32b",
        tags=["reasoning", "local", "free"],
    ),
    
    # NVIDIA Nemotron (via OpenRouter free tier / OpenCode Zen)
    "nemotron-3-ultra-free": Model(
        id="nemotron-3-ultra-free",
        name="Nemotron 3 Ultra (Free)",
        provider=ModelProvider.FREE,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.REASONING, ModelCapability.TOOLS],
        context_window=128000,
        max_output=8192,
        is_free=True,
        description="NVIDIA Nemotron 3 Ultra 550B A55B - razonamiento avanzado, gratis via OpenRouter/OpenCode Zen",
        provider_model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
        tags=["reasoning", "nvidia", "free", "openrouter", "opencode-zen"],
        default_temperature=0.3,
        default_max_tokens=8192,
    ),
    "nemotron-4-340b-free": Model(
        id="nemotron-4-340b-free",
        name="Nemotron 4 340B (Free)",
        provider=ModelProvider.FREE,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.REASONING, ModelCapability.TOOLS],
        context_window=128000,
        max_output=8192,
        is_free=True,
        description="NVIDIA Nemotron 4 340B - modelo flagship de NVIDIA, gratis via OpenRouter",
        provider_model_id="nvidia/nemotron-4-340b-instruct:free",
        tags=["flagship", "nvidia", "free", "openrouter"],
    ),
}


class ModelRegistry:
    """Registro de modelos disponibles con selección por usuario."""
    
    def __init__(self, custom_models_path: Optional[Path] = None):
        self.models = dict(BUILTIN_MODELS)
        self.custom_models_path = custom_models_path
        self.user_selections: dict[str, str] = {}  # agent_id -> model_id
        self._load_custom_models()
    
    def _load_custom_models(self) -> None:
        if self.custom_models_path and self.custom_models_path.exists():
            try:
                data = json.loads(self.custom_models_path.read_text(encoding="utf-8"))
                for m in data.get("models", []):
                    model = Model(**m)
                    self.models[model.id] = model
            except Exception:
                pass
    
    def get_model(self, model_id: str) -> Optional[Model]:
        return self.models.get(model_id)
    
    def get_models_by_provider(self, provider: ModelProvider) -> list[Model]:
        return [m for m in self.models.values() if m.provider == provider]
    
    def get_models_by_capability(self, capability: ModelCapability) -> list[Model]:
        return [m for m in self.models.values() if m.supports(capability)]
    
    def get_free_models(self) -> list[Model]:
        return [m for m in self.models.values() if m.is_free]
    
    def get_recommended_for_agent(self, agent_id: str, required_caps: list[ModelCapability]) -> list[Model]:
        """Sugiere modelos para un agente basado en capacidades requeridas."""
        candidates = [m for m in self.models.values() if all(m.supports(c) for c in required_caps)]
        # Priorizar: gratis -> barato -> capability match
        candidates.sort(key=lambda m: (
            not m.is_free,
            m.cost_per_1k_input + m.cost_per_1k_output,
            -len(m.capabilities)
        ))
        return candidates[:5]
    
    def select_model_for_agent(self, agent_id: str, model_id: str) -> bool:
        """Usuario selecciona modelo para un agente."""
        if model_id in self.models:
            self.user_selections[agent_id] = model_id
            return True
        return False
    
    def get_selected_model(self, agent_id: str) -> Optional[Model]:
        model_id = self.user_selections.get(agent_id)
        if model_id:
            return self.models.get(model_id)
        # Fallback: primer modelo gratuito con capacidades básicas
        free = self.get_free_models()
        return free[0] if free else None
    
    def save_selections(self, path: Path) -> None:
        data = {"selections": self.user_selections}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    def load_selections(self, path: Path) -> None:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.user_selections = data.get("selections", {})


# Instancia global
MODEL_REGISTRY = ModelRegistry()


def get_model_registry() -> ModelRegistry:
    return MODEL_REGISTRY