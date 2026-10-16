"""Orchestration Engine for SYSTEM-ENGINEERING.

Deterministic workflow execution engine with:
- DAG-based topological execution
- Gate evaluation integration
- Context passing between nodes
- Agent assignment and execution via AgentRunner
- Retry policies and error handling
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from collections import deque, defaultdict

from ..paths import repo_root, now_utc, load_json
from ..schemas import load_schemas, validate
from ..gates import evaluate_gate, load_gate_model
from ..artifacts import read_manifest
from ..memory.engine import MemoryEngine
from ..agents.runner import AgentRunner
from .schemas import load_workflow_schema, load_execution_schema


@dataclass
class NodeState:
    """Runtime state of a workflow node."""
    node_id: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED, SKIPPED
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    outputs: Dict[str, Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    gate_results: Dict[str, Any] = None

    def __post_init__(self):
        if self.outputs is None:
            self.outputs = {}
        if self.gate_results is None:
            self.gate_results = {}


class OrchestrationEngine:
    """Deterministic workflow orchestration engine."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else repo_root()
        self._schemas = None
        self._memory_engine = None
        self._gate_model = None

    @property
    def schemas(self) -> Dict[str, Any]:
        if self._schemas is None:
            self._schemas = load_schemas(repo_root())
        return self._schemas

    @property
    def memory_engine(self) -> "MemoryEngine":
        if self._memory_engine is None:
            self._memory_engine = MemoryEngine(root=repo_root())
        return self._memory_engine

    @property
    def gate_model(self) -> Dict[str, Any]:
        if self._gate_model is None:
            self._gate_model = load_gate_model()
        return self._gate_model

    def _find_project_dir(self, project_id: str) -> Optional[Path]:
        for p in (repo_root() / "PROJECTS").glob("*"):
            if (p / "PROJECT.json").exists():
                manifest = read_manifest(p)
                if manifest.get("project_id") == project_id:
                    return p
        return None

    def load_workflow(self, workflow_id: str, project_id: str) -> Dict[str, Any]:
        """Load workflow definition from project."""
        project_dir = self._find_project_dir(project_id)
        if not project_dir:
            raise ValueError(f"Project {project_id} not found")

        workflow_dir = project_dir / "workflows"
        workflow_path = workflow_dir / f"{workflow_id}.json"
        if not workflow_path.exists():
            raise ValueError(f"Workflow {workflow_id} not found in project {project_id}")

        workflow = load_json(workflow_path)
        
        # Validate against schema
        schemas = load_schemas(repo_root())
        errors = validate(workflow, self._get_schema("workflow"))
        if errors:
            raise ValueError(f"Workflow validation failed: {errors}")

        return workflow

    def execute(
        self,
        workflow_id: str,
        project_id: str,
        execution_id: Optional[str] = None,
        dry_run: bool = False,
        start_node: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a workflow deterministically.

        Args:
            workflow_id: Workflow to execute
            project_id: Target project
            execution_id: Optional execution ID (auto-generated if not provided)
            dry_run: If True, only validate and plan, don't execute
            start_node: Optional node to start from (for resume)

        Returns:
            Execution result with status and node states
        """
        # Load workflow
        workflow = self.load_workflow(workflow_id, project_id)

        # Generate execution ID
        if not execution_id:
            execution_id = f"WEX-{random.randint(1000, 9999):04d}"

        # Load project
        project_dir = self._find_project_dir(workflow["project_id"])
        project_data = read_manifest(project_dir)

        # Build execution context
        context = {
            "workflow_id": workflow["workflow_id"],
            "project_id": workflow["project_id"],
            "project_name": workflow.get("name", ""),
            "project_data": workflow,
        }

        # Generate execution ID
        if not execution_id:
            execution_id = f"WEX-{random.randint(1000, 9999):04d}"

        # Load project
        project_dir = self._find_project_dir(workflow["project_id"])
        project_data = read_manifest(project_dir)

        # Build execution context
        context = {
            "workflow_id": workflow["workflow_id"],
            "project_id": workflow["project_id"],
            "project_name": workflow.get("name", ""),
            "project_data": workflow,
        }

        # Build execution state
        execution_id_final = execution_id
        from ..paths import now_utc
        now = now_utc()

        # Initialize node states
        node_states = {}
        for node in workflow["nodes"]:
            node_states[node["node_id"]] = {
                "status": "PENDING",
                "started_at": None,
                "completed_at": None,
                "outputs": {},
                "error": None,
                "retry_count": 0,
                "gate_results": {},
            }

        # Build adjacency for topological sort
        adj = defaultdict(list)
        in_degree = defaultdict(int)
        node_map = {n["node_id"]: n for n in workflow["nodes"]}

        for edge in workflow.get("edges", []):
            adj[edge["from"]].append(edge["to"])
            in_degree[edge["to"]] += 1

        # Add nodes with no edges
        for node in workflow["nodes"]:
            if node["node_id"] not in in_degree:
                in_degree[node["node_id"]] = 0

        # Topological sort with gate integration
        execution_order = self._topological_sort_with_gates(
            workflow, node_map, adj, in_degree, start_node
        )

        if dry_run:
            return {
                "execution_id": execution_id_final,
                "workflow_id": workflow["workflow_id"],
                "status": "DRY_RUN",
                "execution_order": execution_order,
                "nodes": list(node_map.keys()),
                "gates": workflow.get("gates", []),
            }

        # Execute nodes in order
        context = {}
        gate_results = {}

        for node_id in execution_order:
            node = node_map[node_id]
            
            # Check gate if specified
            if node.get("gate"):
                gate_id = node["gate"]
                if gate_id not in gate_results:
                    gate_result = evaluate_gate(gate_id, project_dir)
                    gate_results[gate_id] = gate_result
                
                if gate_results[gate_id].get("status") != "PASS":
                    return self._fail_execution(
                        execution_id_final, workflow, node_states,
                        f"Gate {gate_id} failed: {gate_results[gate_id].get('detail', 'unknown')}"
                    )

            # Execute node using AgentRunner
            result = self._execute_node(node, project_dir, context, workflow)
            
            if result["status"] == "FAILED":
                return self._fail_execution(
                    execution_id_final, workflow, node_states,
                    f"Node {node_id} failed: {result.get('error', 'unknown error')}"
                )

            # Update context with node outputs
            context.update(result.get("outputs", {}))

        return {
            "execution_id": execution_id_final,
            "workflow_id": workflow["workflow_id"],
            "project_id": workflow["project_id"],
            "status": "COMPLETED",
            "completed_at": now_utc(),
            "node_states": node_states,
            "gate_results": gate_results,
            "context": context,
        }

    def _topological_sort_with_gates(
        self,
        workflow: Dict,
        node_map: Dict[str, Dict],
        adj: Dict[str, List[str]],
        in_degree: Dict[str, int],
        start_node: Optional[str],
    ) -> List[str]:
        """Topological sort respecting gates and start node."""
        # Filter nodes if start_node specified
        if start_node:
            # Find all nodes reachable from start_node
            reachable = set()
            queue = deque([start_node])
            while queue:
                node = queue.popleft()
                if node in reachable:
                    continue
                reachable.add(node)
                for neighbor in adj.get(node, []):
                    queue.append(neighbor)
            # Filter workflow nodes
            workflow["nodes"] = [n for n in workflow["nodes"] if n["node_id"] in reachable]
            node_map = {n["node_id"]: n for n in workflow["nodes"]}

        # Kahn's algorithm
        queue = deque([n for n in node_map if in_degree.get(n, 0) == 0])
        result = []

        while queue:
            # Deterministic: sort queue
            queue = deque(sorted(queue))
            node = queue.popleft()
            result.append(node)

            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(node_map):
            raise ValueError("Workflow has cycles")

        return result

    def _execute_node(
        self,
        node: Dict[str, Any],
        project_dir: Path,
        context: Dict[str, Any],
        workflow: Dict,
    ) -> Dict[str, Any]:
        """Execute a single workflow node using AgentRunner."""
        node_id = node["node_id"]
        agent = node["agent"]
        action = node["action"]
        inputs = node.get("inputs", {})
        outputs = node.get("outputs", {})

        # Resolve inputs from context
        resolved_inputs = {}
        for param, source in inputs.items():
            if source.startswith("memory:"):
                mem_id = source[7:]  # Remove "memory:"
                mem = self.memory_engine.get(source[7:], workflow.get("project_id"))
                if mem:
                    resolved_inputs[param] = mem.get("content", {})
                else:
                    return {"status": "FAILED", "error": f"Memory {source} not found"}
            elif source.startswith("context:"):
                key = source[8:]
                resolved_inputs[param] = context.get(key)
            elif source.startswith("literal:"):
                resolved_inputs[param] = source[8:]
            else:
                resolved_inputs[param] = source

        # Filter context to only keys referenced by node inputs (context: prefix).
        # This avoids sending the entire accumulated context to every LLM call.
        context_keys = set()
        for source in inputs.values():
            if isinstance(source, str) and source.startswith("context:"):
                context_keys.add(source[8:])  # Remove "context:" prefix

        filtered_context = {k: v for k, v in context.items() if k in context_keys} if context_keys else {}

        # Resolve max_tokens for this node: node.max_context_tokens > agent default > global default
        max_tokens = node.get("max_context_tokens")

        # Create AgentRunner for the assigned agent
        project_dir = self._find_project_dir(workflow["project_id"])
        try:
            runner = AgentRunner(
                agent_name=agent,
                project_dir=project_dir,
            )
        except Exception as e:
            return {"status": "FAILED", "error": f"Failed to create agent runner for {agent}: {e}"}

        # Execute agent action with filtered context and optional max_tokens override
        result = runner.run(
            action=action,
            inputs=resolved_inputs,
            context=filtered_context,
            max_tokens=max_tokens,
        )

        return result

    def build_native_subagent_input(
        self,
        node: Dict[str, Any],
        context: Dict[str, Any],
        resolved_inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build filtered input payload for native OpenCode `invoke` tool.
        
        This ensures the subagent receives only the context keys it declares
        in its node inputs (context: prefix), consistent with the internal
        AgentRunner path token economy (FASE 1).
        
        Args:
            node: Workflow node definition
            context: Accumulated execution context
            resolved_inputs: Already-resolved input values
            
        Returns:
            Dict with action, inputs, and filtered context for `invoke` tool
        """
        # Filter context to only keys referenced by node inputs (context: prefix)
        context_keys = set()
        for source in node.get("inputs", {}).values():
            if isinstance(source, str) and source.startswith("context:"):
                context_keys.add(source[8:])  # Remove "context:" prefix
        
        filtered_context = {k: v for k, v in context.items() if k in context_keys} if context_keys else {}
        
        return {
            "action": node["action"],
            "inputs": resolved_inputs,
            "context": filtered_context,
        }

    def _find_project_dir(self, project_id: str) -> Optional[Path]:
        for p in (repo_root() / "PROJECTS").glob("*"):
            if (p / "PROJECT.json").exists():
                manifest = read_manifest(p)
                if manifest.get("project_id") == project_id:
                    return p
        return None

    def _fail_execution(
        self,
        execution_id: str,
        workflow: Dict,
        node_states: Dict,
        error: str,
    ) -> Dict[str, Any]:
        from ..paths import now_utc
        return {
            "execution_id": execution_id,
            "workflow_id": workflow["workflow_id"],
            "project_id": workflow["project_id"],
            "status": "FAILED",
            "completed_at": now_utc(),
            "error": error,
        }

    def _get_schema(self, name: str) -> Dict[str, Any]:
        schemas = load_schemas(repo_root())
        return schemas.get(name, {})

    def generate_native_execution_prompt(
        self,
        workflow_id: str,
        project_id: str,
        execution_id: Optional[str] = None,
        start_node: Optional[str] = None,
    ) -> str:
        """Generate a prompt for the coordinator to execute workflow natively via OpenCode invoke.

        This prompt is designed to be used when the coordinator runs as an OpenCode primary agent
        and uses the `invoke` tool to launch subagents for each workflow node.

        Returns:
            Prompt string for the coordinator agent.
        """
        # Load workflow
        workflow = self.load_workflow(workflow_id, project_id)

        # Generate execution ID
        if not execution_id:
            execution_id = f"WEX-{random.randint(1000, 9999):04d}"

        # Load project
        project_dir = self._find_project_dir(workflow["project_id"])
        project_data = read_manifest(project_dir)

        # Build execution context
        context = {
            "workflow_id": workflow["workflow_id"],
            "project_id": workflow["project_id"],
            "project_name": workflow.get("name", ""),
            "project_data": workflow,
        }

        # Build execution state
        execution_id_final = execution_id
        from ..paths import now_utc
        now = now_utc()

        # Initialize node states
        node_states = {}
        for node in workflow["nodes"]:
            node_states[node["node_id"]] = {
                "status": "PENDING",
                "started_at": None,
                "completed_at": None,
                "outputs": {},
                "error": None,
                "retry_count": 0,
                "gate_results": {},
            }

        # Build adjacency for topological sort
        adj = defaultdict(list)
        in_degree = defaultdict(int)
        node_map = {n["node_id"]: n for n in workflow["nodes"]}

        for edge in workflow.get("edges", []):
            adj[edge["from"]].append(edge["to"])
            in_degree[edge["to"]] += 1

        # Add nodes with no edges
        for node in workflow["nodes"]:
            if node["node_id"] not in in_degree:
                in_degree[node["node_id"]] = 0

        # Topological sort with gate integration
        execution_order = self._topological_sort_with_gates(
            workflow, node_map, adj, in_degree, start_node
        )

        # Build the native execution prompt
        # Use minimal context - workflow already listed in "Nodes to Execute" above
        minimal_context = {
            "workflow_id": workflow["workflow_id"],
            "project_id": workflow["project_id"],
            "project_name": workflow.get("name", ""),
            # project_data intentionally omitted - workflow fully listed above
        }

        # Build the native execution prompt
        prompt_parts = [
            f"# Native Workflow Execution: {workflow_id}",
            f"",
            f"**Execution ID**: {execution_id_final}",
            f"**Workflow**: {workflow['workflow_id']} ({workflow.get('name', '')})",
            f"**Project**: {project_id}",
            f"**Started**: {now}",
            f"",
            f"## Execution Order",
            f"",
            f"{' -> '.join(execution_order)}",
            f"",
            f"## Nodes to Execute",
            f"",
        ]

        for node_id in execution_order:
            node = node_map[node_id]
            prompt_parts.append(f"### Node: {node_id}")
            prompt_parts.append(f"- **Agent**: {node['agent']}")
            prompt_parts.append(f"- **Action**: {node['action']}")
            prompt_parts.append(f"- **Inputs**: {json.dumps(node.get('inputs', {}), indent=2)}")
            prompt_parts.append(f"- **Outputs**: {json.dumps(node.get('outputs', {}), indent=2)}")
            if node.get('gate'):
                prompt_parts.append(f"- **Gate**: {node['gate']}")
            if node.get('max_context_tokens'):
                prompt_parts.append(f"- **Max Context Tokens**: {node['max_context_tokens']}")
            prompt_parts.append(f"")

        prompt_parts.extend([
            f"## Instructions for Native Execution",
            f"",
            f"You are the SHEMA-AI Coordinador. Execute this workflow by invoking subagents via the `invoke` tool.",
            f"",
            f"### For each node in execution order:",
            f"",
            f"1. **Check gate** (if specified):",
            f"   - If node has a `gate`, call `se gate --gate <GATE_ID> --project <project_dir>`",
            f"   - If gate status != PASS -> report BLOCKED, stop execution",
            f"",
            f"2. **Resolve inputs** (use the same logic as internal AgentRunner):",
            f"   - `context:key` -> from accumulated context below",
            f"   - `memory:id` -> call `se memory get <id> --project <project_id>`",
            f"   - `literal:value` -> use as-is",
            f"",
            f"3. **Build filtered subagent input** (use engine helper):",
            f"   ```python",
            f"   # Available in OrchestrationEngine:",
            f"   # subagent_input = engine.build_native_subagent_input(",
            f"   #     node=node,",
            f"   #     context=context,",
            f"   #     resolved_inputs=resolved_inputs",
            f"   # )",
            f"   ```",
            f"   This returns `{{\"action\", \"inputs\", \"context\"}}` with context",
            f"   filtered to ONLY keys declared in node.inputs with `context:` prefix.",
            f"   (Consistent with internal AgentRunner token economy - FASE 1)",
            f"",
            f"4. **Invoke subagent** via `invoke` tool:",
            f"   ```json",
            f"   {{",
            f"     \"tool\": \"invoke\",",
            f"     \"arguments\": {{",
            f"       \"agent\": \"{node['agent']}\",",
            f"       \"input\": subagent_input  # Use the helper result",
            f"     }}",
            f"   }}",
            f"   ```",
            f"",
            f"5. **Capture outputs**:",
            f"   - Subagent returns `outputs` dict -> merge into context",
            f"   - Update node status in your tracking",
            f"",
            f"6. **Continue to next node**",
            f"",
            f"### Context Management",
            f"",
            f"- Start with initial context: `{json.dumps(minimal_context, indent=2)}`",
            f"- After each node, update context with node outputs",
            f"- Filter context for each subagent: only keys referenced in `inputs` with `context:` prefix",
            f"",
            f"### Gate Commands",
            f"",
            f"```bash",
            f"se gate --gate G1 --project <project_dir>",
            f"se gate --gate G2 --project <project_dir>",
            f"# etc.",
            f"```",
            f"",
            f"### Final Output",
            f"",
            f"When workflow completes (or fails), return a structured summary:",
            f"```json",
            f"{{",
            f"  \"status\": \"COMPLETED|FAILED\",",
            f"  \"execution_id\": \"{execution_id_final}\",",
            f"  \"workflow_id\": \"{workflow_id}\",",
            f"  \"node_results\": {{",
            f"    \"node_id\": {{ \"status\": \"...\", \"outputs\": {{...}}, \"error\": \"...\" }}",
            f"  }},",
            f"  \"gate_results\": {{ \"G1\": \"PASS\", ... }},",
            f"  \"final_context\": {{...}}",
            f"  \"completed_at\": \"<ISO timestamp>\"",
            f"  \"error\": \"<error message if FAILED>\"",
            f"}}",
            f"```",
            f"",
        ])

        return "\n".join(prompt_parts)


def create_workflow(
    project_id: str,
    name: str,
    description: str,
    nodes: List[Dict],
    edges: List[Dict],
    gates: Optional[List[Dict]] = None,
    root: Optional[Path] = None,
) -> Path:
    """Create a new workflow definition."""
    from ..paths import repo_root, now_utc
    root = Path(root) if root else repo_root()

    project_dir = None
    for p in (repo_root() / "PROJECTS").glob("*"):
        if (p / "PROJECT.json").exists():
            manifest = read_manifest(p)
            if manifest.get("project_id") == project_id:
                project_dir = p
                break
    
    if not project_dir:
        raise ValueError(f"Project {project_id} not found")

    # Generate workflow ID
    workflows_dir = project_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    
    existing = list(workflows_dir.glob("WF-*.json"))
    highest = 0
    for f in existing:
        try:
            num = int(f.stem.split("-")[1])
            highest = max(highest, num)
        except (IndexError, ValueError):
            pass
    workflow_id = f"WF-{highest + 1:04d}"

    # Build workflow definition
    workflow = {
        "schema_version": "1",
        "workflow_id": f"WF-{highest + 1:04d}",
        "project_id": project_id,
        "name": name,
        "version": "0.1.0",
        "status": "DRAFT",
        "description": description,
        "nodes": nodes,
        "edges": edges,
        "gates": gates or [],
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "author": "cli",
        "metadata": {},
    }

    # Validate against schema
    from ..schemas import load_schemas, validate
    schemas = load_schemas(repo_root())
    errors = validate(workflow, schemas.get("workflow", {}))
    if errors:
        raise ValueError(f"Workflow validation failed: {errors}")

    # Write workflow file
    workflow_path = workflows_dir / f"{workflow_id}.json"
    workflow_path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")

    return workflow_path
