"""LLM Provider Abstraction for SYSTEM-ENGINEERING.

Abstract base class and concrete implementations for LLM providers.
Supports OpenAI, Anthropic, and local models (Ollama, vLLM, llama.cpp).
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


@dataclass
class LLMMessage:
    """A single message in a conversation."""
    role: str  # system, user, assistant, tool
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    tool_calls: Optional[List[Dict]] = None
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    raw_response: Optional[Any] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, model: str, **kwargs):
        self.model = model
        self.config = kwargs

    @abstractmethod
    def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **kwargs
    ) -> LLMResponse:
        """Send messages and get a complete response."""
        raise NotImplementedError

    @abstractmethod
    def stream_chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **kwargs
    ) -> Iterator[LLMResponse]:
        """Stream chat responses."""
        raise NotImplementedError

    def _format_messages(self, messages: List[LLMMessage]) -> List[Dict]:
        formatted = []
        for m in messages:
            entry: Dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            if m.name:
                entry["name"] = m.name
            formatted.append(entry)
        return formatted


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (also works with OpenAI-compatible endpoints)."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        **kwargs
    ):
        if not HAS_OPENAI:
            raise ImportError("openai package required: pip install openai")
        super().__init__(model)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url
        self.organization = organization
        if not self.api_key:
            raise ValueError("OpenAI API key required (OPENAI_API_KEY env var or api_key param)")
        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if organization:
            client_kwargs["organization"] = organization
        self.client = openai.OpenAI(**client_kwargs)

    @staticmethod
    def _to_oai_tools(tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        out = []
        for tool in tools:
            func = tool.get("function", tool)
            out.append({
                "type": "function",
                "function": {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                },
            })
        return out

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._format_messages(messages),
                tools=self._to_oai_tools(tools),
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as exc:
            return LLMResponse(content="", finish_reason="error", raw_response={"error": str(exc)})

        choice = response.choices[0]
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.message.tool_calls
            ]
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            # Extract cached tokens (OpenAI: prompt_tokens_details.cached_tokens)
            prompt_tokens_details = getattr(response.usage, "prompt_tokens_details", None)
            if prompt_tokens_details and hasattr(prompt_tokens_details, "cached_tokens"):
                usage["cached_tokens"] = prompt_tokens_details.cached_tokens
        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason,
            raw_response=response,
        )

    def stream_chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self._format_messages(messages),
            tools=self._to_oai_tools(tools),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield LLMResponse(
                    content=chunk.choices[0].delta.content,
                    finish_reason=chunk.choices[0].finish_reason,
                )


class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) API provider."""

    def __init__(self, model, api_key=None, base_url=None, **kwargs):
        if not HAS_ANTHROPIC:
            raise ImportError("anthropic package required: pip install anthropic")
        super().__init__(model)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url
        if not self.api_key:
            raise ValueError("Anthropic API key required (ANTHROPIC_API_KEY env var or api_key param)")
        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)

    @staticmethod
    def _split_system(messages: List[LLMMessage]):
        system = ""
        out = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                out.append({"role": m.role, "content": m.content})
        return system, out

    @staticmethod
    def _to_anthropic_tools(tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        out = []
        for tool in tools:
            func = tool.get("function", tool)
            out.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return out

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        system, msgs = self._split_system(messages)
        try:
            response = self.client.messages.create(
                model=self.model,
                system=system,
                messages=msgs,
                tools=self._to_anthropic_tools(tools),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            return LLMResponse(content="", finish_reason="error", raw_response={"error": str(exc)})

        content_parts: List[str] = []
        tool_calls: List[Dict] = []
        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {"name": block.name, "arguments": json.dumps(block.input)},
                })
        return LLMResponse(
            content="\n".join(content_parts),
            tool_calls=tool_calls or None,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                "cached_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) + getattr(response.usage, "cache_read_input_tokens", 0),
            },
            finish_reason=response.stop_reason,
            raw_response=response,
        )

    def stream_chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        system, msgs = self._split_system(messages)
        with self.client.messages.stream(
            model=self.model,
            system=system,
            messages=msgs,
            tools=self._to_anthropic_tools(tools),
            temperature=temperature,
            max_tokens=max_tokens,
        ) as stream:
            for chunk in stream:
                if chunk.type == "content_block_delta" and chunk.delta.type == "text_delta":
                    yield LLMResponse(content=chunk.delta.text, finish_reason=None)
                elif chunk.type == "message_stop":
                    yield LLMResponse(content="", finish_reason="stop")


class LocalProvider(LLMProvider):
    """Local model provider (Ollama, vLLM, llama.cpp server, OpenAI-compatible)."""

    def __init__(self, model, base_url="http://localhost:11434", **kwargs):
        if not HAS_REQUESTS:
            raise ImportError("requests package required: pip install requests")
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    @staticmethod
    def _to_local_tools(tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        out = []
        for tool in tools:
            func = tool.get("function", tool)
            out.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return out

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        payload = {
            "model": self.model,
            "messages": self._format_messages(messages),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = self._to_local_tools(tools)
        try:
            resp = self.session.post(f"{self.base_url}/api/chat", json=payload, timeout=300)
            if resp.status_code == 404:
                return self._chat_openai_compatible(messages, tools, temperature, max_tokens)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return LLMResponse(content="", finish_reason="error", raw_response={"error": str(exc)})

        message = data.get("message", {})
        return LLMResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            finish_reason="stop",
            raw_response=data,
        )

    def _chat_openai_compatible(self, messages, tools, temperature, max_tokens):
        payload = {
            "model": self.model,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": t}
                for t in self._to_local_tools(tools)
            ]
        try:
            resp = self.session.post(f"{self.base_url}/v1/chat/completions", json=payload, timeout=300)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return LLMResponse(content="", finish_reason="error", raw_response={"error": str(exc)})

        choice = data["choices"][0]
        usage = None
        if "usage" in data:
            u = data["usage"]
            usage = {
                "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "total_tokens": u.get("total_tokens", 0),
            }
            # Extract cached tokens (OpenAI-compatible: prompt_tokens_details.cached_tokens)
            prompt_tokens_details = u.get("prompt_tokens_details")
            if prompt_tokens_details and "cached_tokens" in prompt_tokens_details:
                usage["cached_tokens"] = prompt_tokens_details["cached_tokens"]
        return LLMResponse(
            content=choice["message"].get("content", ""),
            tool_calls=choice["message"].get("tool_calls"),
            finish_reason=choice.get("finish_reason", "stop"),
            usage=usage,
            raw_response=data,
        )

    def stream_chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        payload = {
            "model": self.model,
            "messages": self._format_messages(messages),
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = self._to_local_tools(tools)
        try:
            resp = self.session.post(f"{self.base_url}/api/chat", json=payload, stream=True, timeout=300)
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = data.get("message", {})
                if message.get("content"):
                    yield LLMResponse(content=message["content"], finish_reason=None)
                if data.get("done"):
                    yield LLMResponse(content="", finish_reason="stop")
                    break
        except Exception as exc:
            yield LLMResponse(content="", finish_reason="error", raw_response={"error": str(exc)})


class DummyProvider(LLMProvider):
    """Deterministic provider for tests that need no API keys."""

    def __init__(self, model="dummy", **kwargs):
        super().__init__(model)

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        last = messages[-1].content if messages else ""
        return LLMResponse(
            content=json.dumps({"status": "COMPLETED", "output": {"echo": last}}),
            finish_reason="stop",
        )

    def stream_chat(self, messages, tools=None, temperature=0.3, max_tokens=4096, **kwargs):
        yield LLMResponse(content="[DUMMY] ", finish_reason=None)
        yield LLMResponse(content="streaming ", finish_reason=None)
        yield LLMResponse(content="response", finish_reason="stop")
