"""Agent Runner for SYSTEM-ENGINEERING.

Executes agent actions using configured LLM providers.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..llm.factory import create_provider_from_config
from ..llm.providers import DummyProvider, LLMMessage, LLMProvider
from ..paths import repo_root, load_json
from ..schemas import load_schemas, validate

logger = logging.getLogger(__name__)


class AgentRunner:
    """Executes agent actions using configured LLM provider."""
    
    def __init__(
        self,
        agent_name: str,
        project_dir: Path,
        root: Optional[Path] = None,
        override_llm_config: Optional[Dict] = None,
    ):
        self.agent_name = agent_name
        self.project_dir = Path(project_dir)
        self.root = Path(root) if root else repo_root()
        self.override_llm_config = override_llm_config
        
        # Load agent configuration
        self.agent_config = self._load_agent_config()
        self.llm_provider = self._create_llm_provider()

        # A simulated provider is never presented as a real execution. The
        # `se subagent` command refuses to run it unless the user passes
        # --simulate explicitly.
        self.simulated = isinstance(self.llm_provider, DummyProvider)

        # Load available tools
        self.tools = self._load_tools()
        
        # Load schemas for validation
        self._schemas = None
    
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
        """Create LLM provider from agent config."""
        llm_config = self.override_llm_config or self.agent_config.get("llm_config", {})
        
        if not llm_config:
            # Backward-compatible fallback for tests and the internal
            # orchestration route. It is NOT a real execution: `self.simulated`
            # exposes it and `se subagent` refuses to run it unless --simulate
            # was requested explicitly.
            from ..llm.factory import create_provider
            return create_provider("dummy", "dummy")
        
        from ..llm.factory import create_provider_from_config
        return create_provider_from_config(llm_config)

    def _load_tools(self) -> List[Dict]:
        """Load available tools for this agent."""
        tools = self.agent_config.get("tools", [])
        
        # Load tool definitions from SKILLS or built-in
        tool_defs = []
        for tool_name in tools:
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
        }
        
        system_prompt = self._get_system_prompt()
        
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
        
        # Static parts that are always included
        static_suffix = """Execute this action and return results. Use available tools as needed.
Return results as JSON with the following structure:
{
  "status": "COMPLETED|FAILED",
  "output": {...},
  "evidence": [...],
  "artifacts": [...]
}"""
        
        # Estimate tokens: rough heuristic 4 chars ≈ 1 token
        def estimate_tokens(text: str) -> int:
            return len(text) // 4
        
        # Base tokens (system prompt + action + inputs + static suffix)
        base_tokens = estimate_tokens(system_prompt) + estimate_tokens(action_part) + estimate_tokens(inputs_part) + estimate_tokens(static_suffix)
        
        # Budget for context: 70% of max_tokens minus base
        context_budget = int(max_tokens * 0.7) - base_tokens
        telemetry["context_budget_tokens"] = max(0, context_budget)
        
        # Serialize context
        context_json = json.dumps(context, indent=2, ensure_ascii=False)
        context_part = f"Context:\n{context_json}\n\n"
        context_tokens = estimate_tokens(context_part)
        
        # If within budget, use as-is
        if context_tokens <= context_budget or context_budget <= 0:
            user_content = action_part + inputs_part + context_part + static_suffix
            telemetry["estimated_prompt_tokens"] = base_tokens + context_tokens
            return [
                LLMMessage(role="system", content=system_prompt),
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
        
        user_content = action_part + inputs_part + context_part + static_suffix
        telemetry["estimated_prompt_tokens"] = base_tokens + context_tokens
        return [
            LLMMessage(role="system", content=system_prompt),
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
                tools=self.tools,
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

        finish_reason = getattr(response, "finish_reason", None)
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

        # Providers report transport/API failures through finish_reason
        # instead of raising; that must not become a successful result.
        if finish_reason == "error":
            raw = getattr(response, "raw_response", None) or {}
            detail = raw.get("error") if isinstance(raw, dict) else None
            return {
                "status": "FAILED",
                "error": f"LLM provider error: {detail or 'unknown provider error'}",
                "output": {},
                "usage": usage,
                "finish_reason": finish_reason,
                "telemetry": full_telemetry,
            }

        # Process tool calls if any
        if response.tool_calls:
            result = self._execute_tool_calls(response.tool_calls, context)
            result.setdefault("usage", usage)
            result.setdefault("finish_reason", finish_reason)
            result.setdefault("telemetry", full_telemetry)
            if result.get("status") == "COMPLETED" and self.simulated:
                result["status"] = "SIMULATED"
            return result

        content = response.content or ""
        if not content.strip():
            return {
                "status": "FAILED",
                "error": "LLM provider returned an empty response",
                "output": {},
                "usage": usage,
                "finish_reason": finish_reason,
                "telemetry": full_telemetry,
            }

        # Parse response content as JSON. The prompt requires a JSON object
        # with a status field, so a malformed response is a failure even
        # though no exception was raised.
        try:
            output = json.loads(content)
        except json.JSONDecodeError as e:
            excerpt = content.strip()[:200]
            return {
                "status": "FAILED",
                "error": f"LLM provider returned non-JSON output: {e}: {excerpt!r}",
                "output": {},
                "usage": usage,
                "finish_reason": finish_reason,
                "telemetry": full_telemetry,
            }

        if not isinstance(output, dict):
            return {
                "status": "FAILED",
                "error": "LLM provider returned JSON that is not an object",
                "output": {},
                "usage": usage,
                "finish_reason": finish_reason,
                "telemetry": full_telemetry,
            }

        provider_status = output.get("status")
        if provider_status not in ("COMPLETED", "FAILED"):
            return {
                "status": "FAILED",
                "error": (
                    "LLM provider returned JSON without a valid status "
                    f"(expected COMPLETED|FAILED, got {provider_status!r})"
                ),
                "output": {},
                "usage": usage,
                "finish_reason": finish_reason,
                "telemetry": full_telemetry,
            }

        if provider_status == "FAILED":
            return {
                "status": "FAILED",
                "error": output.get("error") or "LLM provider reported FAILED",
                "output": output,
                "usage": usage,
                "finish_reason": finish_reason,
                "telemetry": full_telemetry,
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

        # The DummyProvider payload is synthetic. Its nested status must not
        # claim a real COMPLETED result, so keep the top-level and nested
        # statuses consistent without discarding the rest of the payload.
        if self.simulated:
            output = dict(output)
            output["status"] = "SIMULATED"

        return {
            "status": "SIMULATED" if self.simulated else "COMPLETED",
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
        
        # A failed tool must not be reported as a completed operation.
        failures = []
        for item in results:
            inner = item.get("result")
            if isinstance(inner, dict) and inner.get("status") == "ERROR":
                failures.append(
                    f"{item.get('name')}: {inner.get('error', 'tool failed')}"
                )

        payload = {
            "status": "FAILED" if failures else "COMPLETED",
            "output": {"tool_results": results},
            "tool_results": results,
        }
        if failures:
            payload["error"] = "Tool execution failed: " + "; ".join(failures)
        return payload

    def _invoke_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        """Invoke a tool by name.

        The internal AgentRunner route has no real tool dispatch wired (tools are
        a placeholder). Returning a fabricated ``executed`` status would report
        success without doing anything, so this route fails loudly instead.
        """
        return {
            "tool": tool_name,
            "args": args,
            "status": "ERROR",
            "error": (
                f"Tool '{tool_name}' is not available in the internal AgentRunner "
                "route: no tool dispatch is wired. Use the native OpenCode `subagent` "
                "tool instead, or implement dispatch here."
            ),
        }

    def validate_output(self, output: Dict, expected_schema: str) -> Tuple[bool, List[str]]:
        """Validate output against schema."""
        if expected_schema not in self.schemas:
            return True, []
        
        errors = validate(output, self.schemas[expected_schema])
        return len(errors) == 0, errors
