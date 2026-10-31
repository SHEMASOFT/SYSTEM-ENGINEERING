"""Agent Runner for SYSTEM-ENGINEERING.

Executes agent actions using configured LLM providers.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..llm.factory import create_provider_from_config, llm_config_from_env
from ..llm.providers import DummyProvider, LLMMessage, LLMProvider
from ..paths import repo_root, load_json
from ..schemas import load_schemas, validate

logger = logging.getLogger(__name__)

# Tools that `_invoke_tool` knows how to dispatch. `bash` is intentionally
# included so that a request for it fails with an explicit, actionable error
# instead of an "unknown tool" message.
_SUPPORTED_TOOLS = ("read", "list", "search", "write", "bash")

# Directory names never traversed by `search`.
_SEARCH_SKIP_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules"})

# Maximum number of characters returned by a single `read`.
_READ_MAX_CHARS = 1_000_000

# Maximum number of matches returned by a single `search`.
_SEARCH_MAX_MATCHES = 200


class _ToolPathError(ValueError):
    """Raised when a tool path is missing or escapes the sandbox."""


class AgentRunner:
    """Executes agent actions using configured LLM provider."""
    
    def __init__(
        self,
        agent_name: str,
        project_dir: Path,
        root: Optional[Path] = None,
        override_llm_config: Optional[Dict] = None,
        memory_engine: Optional["MemoryEngine"] = None,
    ):
        self.agent_name = agent_name
        self.project_dir = Path(project_dir)
        self.root = Path(root) if root else repo_root()
        self.override_llm_config = override_llm_config
        
        # Load agent configuration
        self.agent_config = self._load_agent_config()
        self.llm_provider = self._create_llm_provider()
        
        # Load available tools
        self.tools = self._load_tools()
        
        # Load schemas for validation
        self._schemas = None
        
        # Memory engine for reference resolution (P3-B.1)
        if memory_engine is not None:
            self.memory_engine = memory_engine
        else:
            from ..memory.engine import MemoryEngine
            self.memory_engine = MemoryEngine(root=self.root)
        
        # Prompt prefix cache (P1 token economy): system prompt + static suffix
        # These are constant per agent instance and don't change between calls
        self._cached_system_prompt = self._get_system_prompt()
        self._static_suffix = """Execute this action and return results. Use available tools as needed.
Return results as JSON with the following structure:
{
  "status": "COMPLETED|FAILED",
  "output": {...},
  "evidence": [...],
  "artifacts": [...]
}"""
        # Pre-compute token estimates for cached parts (4 chars ≈ 1 token)
        self._cached_system_prompt_tokens = len(self._cached_system_prompt) // 4
        self._cached_static_suffix_tokens = len(self._static_suffix) // 4
    
    @property
    def schemas(self):
        if self._schemas is None:
            from ..schemas import load_schemas
            from ..paths import repo_root
            self._schemas = load_schemas(repo_root())
        return self._schemas

    def _load_agent_config(self) -> Dict:
        """Load agent configuration from AGENTS/<name>/agent.json"""
        agent_path = self.root / "AGENTS" / self.agent_name / "agent.json"
        if not agent_path.exists():
            raise ValueError(f"Agent config not found: {agent_path}")
        
        from ..paths import load_json
        return load_json(agent_path)

    def _create_llm_provider(self):
        """Create LLM provider from agent config with env fallback."""
        # Precedence: override > agent config > env > dummy
        llm_config = self.override_llm_config or self.agent_config.get("llm_config", {})
        
        if not llm_config:
            # Try to get config from environment
            from ..llm.factory import llm_config_from_env
            import os
            llm_config = llm_config_from_env(os.environ)

        if not llm_config:
            # Fallback to dummy provider for testing
            from ..llm.factory import create_provider
            return create_provider("dummy", "dummy")
        
        from ..llm.factory import create_provider_from_config
        return create_provider_from_config(llm_config)

    @property
    def simulated(self) -> bool:
        """Return True if agent is running in simulated mode (DummyProvider)."""
        # Check the actual provider instance, not just config (config might come from env)
        from ..llm.providers import DummyProvider
        return isinstance(self.llm_provider, DummyProvider)

    def _load_tools(self) -> List[Dict]:
        """Load available tools for this agent."""
        tools = self.agent_config.get("tools", [])

        # Load tool definitions from SKILLS or built-in
        tool_defs = []
        for tool_name in tools:
            tool_def = self._get_tool_definition(tool_name)
            if tool_def:
                tool_defs.append(tool_def)

        # If agent declares no tools, provide default built-in tools
        if not tools:
            # Default tools for all agents
            default_tools = ["read", "list", "search"]

            # Add write tool only if agent has IMPLEMENT or WRITE_DOCS permission
            permissions = self.agent_config.get("permissions", [])
            if "IMPLEMENT" in permissions or "WRITE_DOCS" in permissions:
                default_tools.append("write")

            for tool_name in default_tools:
                tool_def = self._get_tool_definition(tool_name)
                if tool_def:
                    tool_defs.append(tool_def)

        return tool_defs

    def _get_tool_definition(self, tool_name: str) -> Optional[Dict]:
        """Get tool definition from SKILLS or built-in registry."""
        # Try to load from SKILLS
        from ..paths import repo_root
        skill_path = repo_root() / "SKILLS" / tool_name / "SKILL.json"
        if skill_path.exists():
            from ..paths import load_json
            skill = load_json(skill_path)
            return {
                "type": "function",
                "function": {
                    "name": skill.get("skill_id", tool_name),
                    "description": skill.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": skill.get("inputs", {}),
                        "required": skill.get("required_inputs", [])
                    }
                }
            }
        
        # Built-in tools
        builtin_tools = {
            "read": {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to read"}
                        },
                        "required": ["path"]
                    }
                }
            },
            "write": {
                "type": "function",
                "function": {
                    "name": "write",
                    "description": "Write a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to write"},
                            "content": {"type": "string", "description": "Content to write"}
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            "list": {
                "type": "function",
                "function": {
                    "name": "list",
                    "description": "List directory contents",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path to list"}
                        },
                        "required": ["path"]
                    }
                }
            },
            "bash": {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute a bash command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Command to execute"},
                            "cwd": {"type": "string", "description": "Working directory"}
                        },
                        "required": ["command"]
                    }
                }
            },
            "search": {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search files for pattern",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Regex pattern"},
                            "path": {"type": "string", "description": "Directory to search"},
                            "include": {"type": "string", "description": "File pattern"}
                        },
                        "required": ["pattern"]
                    }
                }
            },
            "memory": {
                "type": "function",
                "function": {
                    "name": "memory",
                    "description": "Retrieve or search project memories. Use 'get' to retrieve content by memory ID, 'search' for lexical search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["get", "search"], "description": "Operation to perform: 'get' retrieves a memory by ID, 'search' performs lexical search"},
                            "memory_id": {"type": "string", "description": "Memory ID for 'get' action"},
                            "query": {"type": "string", "description": "Search query text for 'search' action"},
                            "project_id": {"type": "string", "description": "Project ID (optional, defaults to agent's project)"},
                            "limit": {"type": "integer", "default": 10, "description": "Maximum results for search"}
                        },
                        "required": ["action"]
                    }
                }
            },
        }
        
        return builtin_tools.get(tool_name)

    def _build_messages(
        self,
        action: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        max_tokens: int = 4096,
    ) -> Tuple[List, Dict[str, Any]]:
        """Build messages for LLM from action, inputs, and context.
        
        If estimated prompt tokens exceed 70% of max_tokens, truncate context values
        to fit within budget. Priority: inputs > context keys > long values.
        
        Opt-in summarization: values exceeding agent's context_max_inline (default 2000)
        are replaced with a summary reference.
        
        Returns:
            Tuple of (messages_list, telemetry_dict)
        """
        from ..llm.providers import LLMMessage
        
        # Telemetry tracking
        telemetry = {
            "context_original_keys": list(context.keys()),
            "context_original_count": len(context),
            "keys_summarized": [],
            "keys_truncated": [],
            "keys_dropped": [],
            "estimated_prompt_tokens": 0,
            "context_budget_tokens": 0,
            "max_tokens": max_tokens,
            # Breakdown (P2 token economy)
            "system_prompt_tokens": 0,
            "static_suffix_tokens": 0,
            "action_tokens": 0,
            "inputs_tokens": 0,
            "context_tokens": 0,
        }
        
        # Opt-in summarization threshold (chars) - configurable per agent
        context_max_inline = self.agent_config.get("context_max_inline", 2000)
        
        # Summarize large context values before token budget check
        original_context_keys = set(context.keys())
        context = self._summarize_large_context_values(context, context_max_inline, telemetry)
        telemetry["keys_summarized"] = [k for k in context.keys() if k in original_context_keys and isinstance(context.get(k), dict) and "_summary" in context[k]]
        
        # Build base message parts
        action_part = f"Action: {action}\n\n"
        inputs_json = json.dumps(inputs, indent=2, ensure_ascii=False)
        inputs_part = f"Inputs:\n{inputs_json}\n\n"
        
        # Estimate tokens: rough heuristic 4 chars ≈ 1 token
        def estimate_tokens(text: str) -> int:
            return len(text) // 4
        
        # Token breakdown for telemetry (P2)
        system_prompt_tokens = self._cached_system_prompt_tokens
        static_suffix_tokens = self._cached_static_suffix_tokens
        action_tokens = estimate_tokens(action_part)
        inputs_tokens = estimate_tokens(inputs_part)
        
        # Use cached system prompt and static suffix tokens (P1 token economy)
        base_tokens = system_prompt_tokens + action_tokens + inputs_tokens + static_suffix_tokens
        
        # Budget for context: 70% of max_tokens minus base
        context_budget = int(max_tokens * 0.7) - base_tokens
        telemetry["context_budget_tokens"] = max(0, context_budget)
        
        # Serialize context
        context_json = json.dumps(context, indent=2, ensure_ascii=False)
        context_part = f"Context:\n{context_json}\n\n"
        context_tokens = estimate_tokens(context_part)
        
        # Record breakdown in telemetry (P2)
        telemetry["system_prompt_tokens"] = system_prompt_tokens
        telemetry["static_suffix_tokens"] = static_suffix_tokens
        telemetry["action_tokens"] = action_tokens
        telemetry["inputs_tokens"] = inputs_tokens
        telemetry["context_tokens"] = context_tokens
        
        # If within budget, use as-is
        if context_tokens <= context_budget or context_budget <= 0:
            user_content = action_part + inputs_part + context_part + self._static_suffix
            telemetry["estimated_prompt_tokens"] = base_tokens + context_tokens
            return [
                LLMMessage(role="system", content=self._cached_system_prompt),
                LLMMessage(role="user", content=user_content),
            ], telemetry
        
        # Need to truncate context: prioritize keeping keys, truncate long values
        # Strategy: truncate string values > 500 chars, then if still over budget, drop keys
        truncated_context = {}
        for k, v in context.items():
            if isinstance(v, str) and len(v) > 500:
                # Truncate long strings with indicator
                truncated_context[k] = v[:500] + f"... [truncated {len(v) - 500} chars]"
                telemetry["keys_truncated"].append(k)
            else:
                truncated_context[k] = v
        
        # Re-estimate
        context_json = json.dumps(truncated_context, indent=2, ensure_ascii=False)
        context_part = f"Context:\n{context_json}\n\n"
        context_tokens = estimate_tokens(context_part)
        telemetry["context_tokens"] = context_tokens
        
        # If still over budget, drop least important keys (keep first N that fit)
        if context_tokens > context_budget and context_budget > 0:
            # Keep keys in order, drop from end until fits
            keys = list(truncated_context.keys())
            while keys and context_tokens > context_budget:
                dropped_key = keys.pop()  # Remove last key
                telemetry["keys_dropped"].append(dropped_key)
                test_context = {k: truncated_context[k] for k in keys}
                context_json = json.dumps(test_context, indent=2, ensure_ascii=False)
                context_part = f"Context:\n{context_json}\n\n"
                context_tokens = estimate_tokens(context_part)
            truncated_context = {k: truncated_context[k] for k in keys}
            telemetry["context_tokens"] = context_tokens
        
        user_content = action_part + inputs_part + context_part + self._static_suffix
        telemetry["estimated_prompt_tokens"] = base_tokens + context_tokens
        return [
            LLMMessage(role="system", content=self._cached_system_prompt),
            LLMMessage(role="user", content=user_content),
        ], telemetry

    def _summarize_large_context_values(
        self,
        context: Dict[str, Any],
        max_inline: int,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Replace context values exceeding max_inline chars with a summary reference.
        
        The summary includes:
        - _summary: human-readable description
        - _full_key: the original context key for potential retrieval
        - _type: original value type
        - _size: original size in chars
        
        Agents can use tools to retrieve full content if needed.
        """
        if max_inline <= 0:
            return context  # Disabled
        
        summarized = {}
        for k, v in context.items():
            # Serialize to estimate size
            if isinstance(v, (str, dict, list)):
                serialized = json.dumps(v, ensure_ascii=False)
                size = len(serialized)
            else:
                serialized = str(v)
                size = len(serialized)
            
            if size > max_inline:
                # Create summary
                if isinstance(v, dict):
                    type_desc = f"dict with {len(v)} keys: {list(v.keys())[:5]}"
                    if len(v) > 5:
                        type_desc += f" ... (+{len(v) - 5} more)"
                elif isinstance(v, list):
                    type_desc = f"list of {len(v)} items"
                    if len(v) > 0:
                        type_desc += f", first: {str(v[0])[:50]}"
                else:
                    type_desc = f"str ({size} chars)"
                
                summarized[k] = {
                    "_summary": f"Large {type_desc}, {size} chars",
                    "_full_key": k,
                    "_type": type(v).__name__,
                    "_size": size,
                }
                if telemetry is not None:
                    telemetry.setdefault("keys_summarized", []).append(k)
            else:
                summarized[k] = v
        
        return summarized

    def _get_system_prompt(self) -> str:
        """Get system prompt for this agent."""
        # Try to load from prompts directory
        prompt_path = self.root / "TEMPLATES" / "prompts" / "personas" / f"{self.agent_name}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        
        # Fallback to agent config
        system_prompt = self.agent_config.get("system_prompt", "")
        if system_prompt:
            return system_prompt
        
        # Default based on agent name
        defaults = {
            "analyst": "You are a senior systems analyst. Analyze requirements, identify risks, and propose solutions.",
            "architect": "You are a senior software architect. Design systems, create technical specifications, and make architectural decisions.",
            "implementer": "You are a senior software engineer. Implement features, write clean code, and follow best practices.",
            "tester": "You are a senior QA engineer. Design tests, verify implementations, and ensure quality.",
            "reviewer": "You are a senior code reviewer. Review code for correctness, security, and maintainability.",
            "planner": "You are a technical planner. Create execution plans, estimate effort, and identify dependencies.",
            "coordinator": "You are a technical coordinator. Coordinate tasks, manage dependencies, and track progress.",
            "explorer": "You are a code explorer. Analyze codebases, find patterns, and document findings.",
            "security": "You are a security engineer. Identify vulnerabilities, assess risks, and enforce security policies.",
            "documentation": "You are a technical writer. Create clear, accurate documentation.",
        }
        return defaults.get(self.agent_name, f"You are a {self.agent_name}. Execute tasks professionally.")

    def run(
        self,
        action: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        tools: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute an agent action.
        
        Args:
            action: Action name to execute
            inputs: Input parameters for the action
            context: Execution context (memory, project state, etc.)
            tools: Additional tools to make available
            temperature: Override temperature
            max_tokens: Override max tokens
            
        Returns:
            Result dict with status, output, evidence, artifacts, and telemetry
        """
        # Get LLM config overrides
        llm_config = self.agent_config.get("llm_config", {})
        temperature = temperature if temperature is not None else llm_config.get("temperature", 0.3)
        max_tokens = max_tokens or llm_config.get("max_tokens", 4096)
        
        # Build messages with token budget awareness
        messages, telemetry = self._build_messages(action, inputs, context, max_tokens)
        
        # Log telemetry (context processing)
        logger.debug(
            "AgentRunner telemetry: agent=%s action=%s "
            "original_keys=%d summarized=%d truncated=%d dropped=%d "
            "est_prompt_tokens=%d budget=%d",
            self.agent_name, action,
            telemetry.get("context_original_count", 0),
            len(telemetry.get("keys_summarized", [])),
            len(telemetry.get("keys_truncated", [])),
            len(telemetry.get("keys_dropped", [])),
            telemetry.get("estimated_prompt_tokens", 0),
            telemetry.get("context_budget_tokens", 0),
        )
        
        # Merge tools
        all_tools = self.tools.copy()
        if tools:
            all_tools.extend(tools)
        
        # Call LLM
        try:
            response = self.llm_provider.chat(
                messages=messages,
                tools=all_tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            return {
                "status": "FAILED",
                "error": f"LLM call failed: {e}",
                "output": {},
                "telemetry": telemetry,
            }
        
        # Process tool calls if any
        if response.tool_calls:
            return self._execute_tool_calls(response.tool_calls, context)
        
        # Handle provider finish_reason errors
        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason == "error":
            error_msg = "Provider error"
            raw = getattr(response, "raw_response", {})
            if isinstance(raw, dict) and "error" in raw:
                error_msg = raw["error"]
            return {
                "status": "FAILED",
                "error": error_msg,
                "output": {},
                "telemetry": telemetry,
            }
        
        # Handle content_filter and length truncation finish reasons
        if finish_reason == "content_filter":
            return {
                "status": "FAILED",
                "error": "content_filter",
                "output": {},
                "telemetry": telemetry,
            }
        
        # For length truncation, check if content is empty or truncated
        if finish_reason == "length":
            content = response.content or ""
            content = content.strip()
            if not content:
                return {
                    "status": "FAILED",
                    "error": "Empty response from provider (length truncation)",
                    "output": {},
                    "telemetry": telemetry,
                }
            # Try to parse truncated JSON
            try:
                output = json.loads(content)
            except json.JSONDecodeError:
                return {
                    "status": "FAILED",
                    "error": "non-JSON response from provider (length truncation)",
                    "output": {},
                    "telemetry": telemetry,
                }
        
        # Parse response content as JSON
        content = response.content or ""
        content = content.strip()
        if not content:
            return {
                "status": "FAILED",
                "error": "Empty response from provider",
                "output": {},
                "telemetry": telemetry,
            }
        
        try:
            output = json.loads(content)
        except json.JSONDecodeError:
            return {
                "status": "FAILED",
                "error": "non-JSON response from provider",
                "output": {},
                "telemetry": telemetry,
            }
        
        # Validate output structure
        if not isinstance(output, dict):
            return {
                "status": "FAILED",
                "error": "Response is not a JSON object",
                "output": {},
                "telemetry": telemetry,
            }
        
        if "status" not in output:
            return {
                "status": "FAILED",
                "error": "Missing 'status' field in response",
                "output": {},
                "telemetry": telemetry,
            }
        
        # If provider explicitly reports FAILED, propagate it
        if output.get("status") == "FAILED":
            return {
                "status": "FAILED",
                "error": output.get("error", "Provider reported failure"),
                "output": output.get("output", {}),
                "telemetry": telemetry,
            }
        
        # Combine telemetry with provider usage
        usage = getattr(response, "usage", {}) or {}
        full_telemetry = {
            "context_processing": telemetry,
            "provider_usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "finish_reason": finish_reason,
        }
        
        # Log provider usage
        logger.info(
            "AgentRunner usage: agent=%s action=%s "
            "prompt_tokens=%d completion_tokens=%d total_tokens=%d",
            self.agent_name, action,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("total_tokens", 0),
        )
        
        # If using dummy provider, mark as SIMULATED
        from ..llm.providers import DummyProvider
        if isinstance(self.llm_provider, DummyProvider):
            return {
                "status": "SIMULATED",
                "output": {"status": "SIMULATED", "output": output.get("output", {"echo": output})},
                "usage": usage,
                "finish_reason": finish_reason,
                "telemetry": full_telemetry,
            }
        
        return {
            "status": "COMPLETED",
            "output": output,
            "usage": usage,
            "finish_reason": finish_reason,
            "telemetry": full_telemetry,
        }

    def _execute_tool_calls(
        self,
        tool_calls: List[Dict],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute tool calls from LLM response."""
        results = []
        
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name", "")
            tool_args = tc.get("function", {}).get("arguments", {})
            
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}
            
            # Execute tool (dispatch to appropriate handler)
            result = self._invoke_tool(tool_name, tool_args, context)
            results.append({
                "tool_call_id": tc.get("id"),
                "name": tool_name,
                "result": result,
            })
        
        # Check if any tool failed
        for r in results:
            tool_result = r.get("result", {})
            if tool_result.get("status") in ("ERROR", "FAILED", "failed", "error", "FAILURE", "failure"):
                error_msg = tool_result.get("error", "Tool execution failed")
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "output": {"tool_results": results},
                    "tool_results": results,
                }
            # Also check for error field even with ok status
            if tool_result.get("status") == "ok" and tool_result.get("error"):
                return {
                    "status": "FAILED",
                    "error": tool_result.get("error"),
                    "output": {"tool_results": results},
                    "tool_results": results,
                }
        
        # All tools succeeded
        return {
            "status": "COMPLETED",
            "output": {"tool_results": results},
            "tool_results": results,
        }

    def _invoke_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        """Invoke a tool by name with path sandboxing and permission checks."""
        if tool_name == "memory":
            return self._invoke_memory_tool(args)

        if tool_name == "read":
            return self._tool_read(args)
        if tool_name == "list":
            return self._tool_list(args)
        if tool_name == "search":
            return self._tool_search(args)
        if tool_name == "write":
            return self._tool_write(args)
        if tool_name == "bash":
            return {
                "tool": tool_name,
                "args": args,
                "status": "ERROR",
                "error": (
                    f"Tool '{tool_name}' is not available in the internal AgentRunner "
                    "route: no tool dispatch is wired. Use the native OpenCode `subagent` "
                    "tool instead, or implement dispatch here. Tool execution failed."
                ),
            }

        return {
            "tool": tool_name,
            "args": args,
            "status": "ERROR",
            "error": f"Unknown tool '{tool_name}'",
        }

    def _can_write(self) -> bool:
        """Check if agent has permission to write."""
        permissions = self.agent_config.get("permissions", [])
        return "IMPLEMENT" in permissions or "WRITE_DOCS" in permissions

    def _tool_read(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read a file with path sandboxing."""
        path_str = args.get("path")
        if not path_str or not isinstance(path_str, str):
            return {
                "tool": "read",
                "args": args,
                "status": "ERROR",
                "error": "path is required and must be a string",
            }

        try:
            # Resolve path within project_dir or root
            path = Path(path_str)
            if path.is_absolute():
                # Absolute path - must be within project_dir or root
                if self._is_path_allowed(path):
                    target = path
                else:
                    return {
                        "tool": "read",
                        "args": args,
                        "status": "ERROR",
                        "error": f"path escapes sandbox: {path}. Tool execution failed.",
                    }
            else:
                # Relative path - resolve from project_dir
                target = (self.project_dir / path).resolve()

            # Check containment
            if not self._is_path_allowed(target):
                return {
                    "tool": "read",
                    "args": args,
                    "status": "ERROR",
                    "error": f"path escapes sandbox: {target}. Tool execution failed.",
                }

            if not target.exists():
                return {
                    "tool": "read",
                    "args": args,
                    "status": "ERROR",
                    "error": f"file not found: {target}",
                }

            if not target.is_file():
                return {
                    "tool": "read",
                    "args": args,
                    "status": "ERROR",
                    "error": f"not a file: {target}",
                }

            content = target.read_text(encoding="utf-8")
            if len(content) > _READ_MAX_CHARS:
                content = content[:_READ_MAX_CHARS] + f"\n... [truncated {len(content) - _READ_MAX_CHARS} chars]"

            return {
                "tool": "read",
                "args": args,
                "status": "COMPLETED",
                "output": content,
                "path": str(target),
            }
        except _ToolPathError as e:
            return {
                "tool": "read",
                "args": args,
                "status": "ERROR",
                "error": str(e),
            }
        except Exception as e:
            return {
                "tool": "read",
                "args": args,
                "status": "ERROR",
                "error": f"read failed: {e}",
            }

    def _tool_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List directory contents with path sandboxing."""
        path_str = args.get("path")
        if not path_str or not isinstance(path_str, str):
            return {
                "tool": "list",
                "args": args,
                "status": "ERROR",
                "error": "path is required and must be a string",
            }

        try:
            path = Path(path_str)
            if path.is_absolute():
                if self._is_path_allowed(path):
                    target = path
                else:
                    return {
                        "tool": "list",
                        "args": args,
                        "status": "ERROR",
                        "error": f"path escapes sandbox: {path}. Tool execution failed.",
                    }
            else:
                target = (self.project_dir / path).resolve()

            if not self._is_path_allowed(target):
                return {
                    "tool": "list",
                    "args": args,
                    "status": "ERROR",
                    "error": f"path escapes sandbox: {target}. Tool execution failed.",
                }

            if not target.exists():
                return {
                    "tool": "list",
                    "args": args,
                    "status": "ERROR",
                    "error": f"path not found: {target}",
                }

            if not target.is_dir():
                return {
                    "tool": "list",
                    "args": args,
                    "status": "ERROR",
                    "error": f"not a directory: {target}",
                }

            entries = []
            for child in sorted(target.iterdir(), key=lambda p: p.name):
                entries.append({
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                })

            return {
                "tool": "list",
                "args": args,
                "status": "COMPLETED",
                "output": entries,
            }
        except _ToolPathError as e:
            return {
                "tool": "list",
                "args": args,
                "status": "ERROR",
                "error": str(e),
            }
        except Exception as e:
            return {
                "tool": "list",
                "args": args,
                "status": "ERROR",
                "error": f"list failed: {e}",
            }

    def _tool_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search files for pattern with path sandboxing."""
        pattern = args.get("pattern")
        if not pattern or not isinstance(pattern, str):
            return {
                "tool": "search",
                "args": args,
                "status": "ERROR",
                "error": "pattern is required and must be a string",
            }

        path_str = args.get("path")
        include = args.get("include")

        try:
            # Compile regex
            try:
                regex = re.compile(pattern)
            except re.error as e:
                return {
                    "tool": "search",
                    "args": args,
                    "status": "ERROR",
                    "error": f"Invalid regex: {e}",
                }

            # Determine search root
            if path_str:
                path = Path(path_str)
                if path.is_absolute():
                    if self._is_path_allowed(path):
                        search_root = path
                    else:
                        return {
                            "tool": "search",
                            "args": args,
                            "status": "ERROR",
                            "error": f"path escapes sandbox: {path}. Tool execution failed.",
                        }
                else:
                    search_root = (self.project_dir / path).resolve()
            else:
                search_root = self.project_dir

            if not self._is_path_allowed(search_root):
                return {
                    "tool": "search",
                    "args": args,
                    "status": "ERROR",
                    "error": f"path escapes sandbox: {search_root}. Tool execution failed.",
                }

            if not search_root.exists():
                return {
                    "tool": "search",
                    "args": args,
                    "status": "ERROR",
                    "error": f"path not found: {search_root}",
                }

            if not search_root.is_dir():
                return {
                    "tool": "search",
                    "args": args,
                    "status": "ERROR",
                    "error": f"not a directory: {search_root}",
                }

            matches = []
            for root, dirs, files in os.walk(search_root):
                # Skip excluded directories
                dirs[:] = [d for d in dirs if d not in _SEARCH_SKIP_DIRS]

                for fname in files:
                    if include and not fnmatch.fnmatch(fname, include):
                        continue

                    fpath = Path(root) / fname
                    try:
                        # Check path is allowed
                        if not self._is_path_allowed(fpath):
                            continue

                        # Read and search
                        text = fpath.read_text(encoding="utf-8")
                        for i, line in enumerate(text.splitlines(), 1):
                            if regex.search(line):
                                # Return relative path from project_dir
                                try:
                                    rel_path = fpath.relative_to(self.project_dir)
                                except ValueError:
                                    rel_path = fpath.relative_to(self.root)
                                # Normalize to forward slashes for cross-platform consistency
                                matches.append({
                                    "path": str(rel_path).replace("\\", "/"),
                                    "line": i,
                                    "text": line.rstrip(),
                                })
                                if len(matches) >= _SEARCH_MAX_MATCHES:
                                    break
                        if len(matches) >= _SEARCH_MAX_MATCHES:
                            break
                    except Exception:
                        # Skip unreadable files
                        continue
                if len(matches) >= _SEARCH_MAX_MATCHES:
                    break

            truncated = len(matches) >= _SEARCH_MAX_MATCHES

            return {
                "tool": "search",
                "args": args,
                "status": "COMPLETED",
                "output": matches,
                "truncated": truncated,
            }
        except _ToolPathError as e:
            return {
                "tool": "search",
                "args": args,
                "status": "ERROR",
                "error": str(e),
            }
        except Exception as e:
            return {
                "tool": "search",
                "args": args,
                "status": "ERROR",
                "error": f"search failed: {e}",
            }

    def _tool_write(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Write a file with path sandboxing and permission check."""
        if not self._can_write():
            return {
                "tool": "write",
                "args": args,
                "status": "ERROR",
                "error": "Agent lacks IMPLEMENT or WRITE_DOCS permission for write operations",
            }

        path_str = args.get("path")
        content = args.get("content")
        if not path_str or not isinstance(path_str, str):
            return {
                "tool": "write",
                "args": args,
                "status": "ERROR",
                "error": "path is required and must be a string",
            }
        if content is None:
            return {
                "tool": "write",
                "args": args,
                "status": "ERROR",
                "error": "content is required",
            }

        try:
            path = Path(path_str)
            if path.is_absolute():
                if self._is_path_allowed(path):
                    target = path
                else:
                    return {
                        "tool": "write",
                        "args": args,
                        "status": "ERROR",
                        "error": f"path escapes sandbox: {path}. Tool execution failed.",
                    }
            else:
                target = (self.project_dir / path).resolve()

            if not self._is_path_allowed(target):
                return {
                    "tool": "write",
                    "args": args,
                    "status": "ERROR",
                    "error": f"path escapes sandbox: {target}. Tool execution failed.",
                }

            # Write file
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                data = content.encode("utf-8")
            else:
                data = json.dumps(content, indent=2, sort_keys=True).encode("utf-8")

            target.write_bytes(data)

            return {
                "tool": "write",
                "args": args,
                "status": "COMPLETED",
                "path": str(target),
                "bytes": len(data),
            }
        except _ToolPathError as e:
            return {
                "tool": "write",
                "args": args,
                "status": "ERROR",
                "error": str(e),
            }
        except Exception as e:
            return {
                "tool": "write",
                "args": args,
                "status": "ERROR",
                "error": f"write failed: {e}",
            }

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is within project_dir or root."""
        try:
            resolved = path.resolve()
            project_resolved = self.project_dir.resolve()
            root_resolved = self.root.resolve()
            # Allow if within project_dir or within root (repo root)
            return (resolved == project_resolved or project_resolved in resolved.parents) or \
                   (resolved == root_resolved or root_resolved in resolved.parents)
        except Exception:
            return False

    def _invoke_memory_tool(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke the memory tool for get/search operations.
        
        Args:
            args: Tool arguments with action, memory_id, query, project_id, limit
            
        Returns:
            Tool result dict with status and content/error
        """
        action = args.get("action")
        
        # Validate action
        if action not in ("get", "search"):
            return {
                "tool": "memory",
                "args": args,
                "status": "ERROR",
                "error": f"Invalid action '{action}'. Supported actions: get, search"
            }
        
        # Get project_id from args or derive from agent's project_dir
        project_id = args.get("project_id")
        if not project_id:
            # Derive project_id from project_dir name or manifest
            if self.project_dir and self.project_dir.name:
                # Try to read PROJECT.json to get project_id
                try:
                    from ..artifacts import read_manifest
                    manifest = read_manifest(self.project_dir)
                    project_id = manifest.get("project_id")
                except Exception:
                    pass
        
        if not project_id:
            return {
                "tool": "memory",
                "args": args,
                "status": "ERROR",
                "error": "Project context required for memory operations"
            }
        
        # Check agent permissions for memory operations
        permissions = self.agent_config.get("permissions", [])
        if "READ" not in permissions:
            return {
                "tool": "memory",
                "args": args,
                "status": "ERROR",
                "error": "Agent lacks READ permission for memory operations"
            }
        
        if action == "get":
            memory_id = args.get("memory_id")
            if not memory_id:
                return {
                    "tool": "memory",
                    "args": args,
                    "status": "ERROR",
                    "error": "memory_id required for get action"
                }
            
            # Retrieve memory from engine
            try:
                mem_record = self.memory_engine.get(memory_id, project_id)
            except Exception as e:
                return {
                    "tool": "memory",
                    "args": args,
                    "status": "ERROR",
                    "error": f"Memory engine error: {e}"
                }
            
            if mem_record is None:
                return {
                    "tool": "memory",
                    "args": args,
                    "status": "ERROR",
                    "error": f"Memory not found: {memory_id} (project: {project_id})"
                }
            
            # Return the memory content
            return {
                "tool": "memory",
                "args": args,
                "status": "OK",
                "content": mem_record.get("content", {})
            }
        
        elif action == "search":
            query = args.get("query")
            if not query:
                return {
                    "tool": "memory",
                    "args": args,
                    "status": "ERROR",
                    "error": "query required for search action"
                }
            
            limit = args.get("limit", 10)
            
            try:
                search_result = self.memory_engine.search(
                    text=query,
                    project_id=project_id,
                    limit=limit
                )
            except Exception as e:
                return {
                    "tool": "memory",
                    "args": args,
                    "status": "ERROR",
                    "error": f"Memory search error: {e}"
                }
            
            # Return compact hits
            hits = search_result.get("hits", [])
            compact_hits = []
            for hit in hits:
                # Create a compact summary
                snippet = hit.get("snippet", "")
                if not snippet:
                    # Try to build a summary from available fields
                    hit_type = hit.get("type", "")
                    if isinstance(hit.get("content"), dict):
                        summary = f"dict with {len(hit['content'])} keys"
                    elif isinstance(hit.get("content"), list):
                        summary = f"list of {len(hit['content'])} items"
                    else:
                        summary = hit_type
                    if snippet:
                        summary = snippet + " | " + summary
                else:
                    summary = snippet
                
                compact_hits.append({
                    "memory_id": hit.get("memory_id"),
                    "type": hit.get("type"),
                    "summary": summary,
                    "score": hit.get("score"),
                })
            
            return {
                "tool": "memory",
                "args": args,
                "status": "OK",
                "hits": compact_hits,
                "total": search_result.get("summary", {}).get("total", len(compact_hits))
            }

    def validate_output(self, output: Dict, expected_schema: str) -> Tuple[bool, List[str]]:
        """Validate output against schema."""
        if expected_schema not in self.schemas:
            return True, []
        
        errors = validate(output, self.schemas[expected_schema])
        return len(errors) == 0, errors
