"""Agent Runner for SYSTEM-ENGINEERING.

Executes agent actions using configured LLM providers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..llm.factory import create_provider_from_config
from ..llm.providers import LLMMessage, LLMProvider
from ..paths import repo_root, load_json
from ..schemas import load_schemas, validate


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
            # Fallback to dummy provider for testing
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
    ) -> List:
        """Build messages for LLM from action, inputs, and context."""
        from ..llm.providers import LLMMessage
        
        system_prompt = self._get_system_prompt()
        
        # Build user message with action, inputs, and context
        user_content = f"""Action: {action}

Inputs:
{json.dumps(inputs, indent=2, ensure_ascii=False)}

Context:
{json.dumps(context, indent=2, ensure_ascii=False)}

Execute this action and return results. Use available tools as needed.
Return results as JSON with the following structure:
{{
  "status": "COMPLETED|FAILED",
  "output": {{...}},
  "evidence": [...],
  "artifacts": [...]
}}"""
        
        return [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

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
            Result dict with status, output, evidence, artifacts
        """
        # Build messages
        messages = self._build_messages(action, inputs, context)
        
        # Merge tools
        all_tools = self.tools.copy()
        if tools:
            all_tools.extend(tools)
        
        # Get LLM config overrides
        llm_config = self.agent_config.get("llm_config", {})
        temperature = temperature if temperature is not None else llm_config.get("temperature", 0.3)
        max_tokens = max_tokens or llm_config.get("max_tokens", 4096)
        
        # Call LLM
        try:
            response = self.llm_provider.chat(
                messages=self._build_messages(action, inputs, context),
                tools=self.tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            return {
                "status": "FAILED",
                "error": f"LLM call failed: {e}",
                "output": {},
            }
        
        # Process tool calls if any
        if response.tool_calls:
            return self._execute_tool_calls(response.tool_calls, context)
        
        # Parse response content as JSON
        try:
            output = json.loads(response.content)
        except json.JSONDecodeError:
            output = {"raw_output": response.content}
        
        return {
            "status": "COMPLETED",
            "output": output,
            "usage": response.usage,
            "finish_reason": response.finish_reason,
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
        
        # For now, return the tool results as output
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
        """Invoke a tool by name."""
        # This would integrate with the actual tool execution system
        # For now, return a placeholder
        return {
            "tool": tool_name,
            "args": args,
            "status": "executed",
            "note": f"Tool {tool_name} executed with args: {args}"
        }

    def validate_output(self, output: Dict, expected_schema: str) -> Tuple[bool, List[str]]:
        """Validate output against schema."""
        if expected_schema not in self.schemas:
            return True, []
        
        errors = validate(output, self.schemas[expected_schema])
        return len(errors) == 0, errors
