# Workflows — SYSTEM ENGINEERING

**Deterministic, gate-driven workflow execution** — define multi-agent processes as DAGs, execute them with automatic topological ordering, gate enforcement, and context passing between nodes.

Workflows live inside **managed projects** (`PROJECTS/<name>/workflows/`) and are versioned alongside the project artifacts.

---

## Quick path

```bash
# 1. Create a workflow definition (JSON)
python SCRIPTS/se.py orchestrate create --project PROJECTS/MyApp \
  --name "Feature Development" \
  --nodes nodes.json --edges edges.json --gates gates.json

# 2. Dry-run to validate + see execution order
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp \
  --workflow WF-0001 --dry-run

# 3. Execute for real
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp \
  --workflow WF-0001

# 4. List workflows in a project
python SCRIPTS/se.py orchestrate list --project PROJECTS/MyApp
```

---

## What is a workflow?

A **workflow** is a directed acyclic graph (DAG) of **nodes** executed by **agents**, with optional **gates** that must pass before a node runs. The engine:

1. **Validates** the definition against schema
2. **Topologically sorts** nodes (Kahn's algorithm, deterministic)
3. **Executes** in order, evaluating gates before each node
4. **Passes context** between nodes (outputs → inputs)
5. **Records** execution state, gate results, and final context

---

## Workflow definition (schema v1)

Saved as `WF-XXXX.json` in `PROJECTS/<name>/workflows/`.

```json
{
  "schema_version": "1",
  "workflow_id": "WF-0001",
  "project_id": "PRJ-MYAPP",
  "name": "Feature Development",
  "version": "0.1.0",
  "status": "DRAFT",
  "description": "End-to-end feature development",
  "nodes": [ ... ],
  "edges": [ ... ],
  "gates": [ ... ],
  "created_at": "2026-10-10T12:00:00Z",
  "updated_at": "2026-10-10T12:00:00Z",
  "author": "cli",
  "metadata": {}
}
```

### Nodes

Each node declares **what agent**, **what action**, **inputs**, and **outputs**.

```json
{
  "node_id": "analyze",
  "agent": "analyst",
  "action": "analyze_requirements",
  "inputs": {
    "requirements": "context:requirements",
    "scope": "literal:backend"
  },
  "outputs": {
    "analysis": "memory:analysis_result"
  },
  "depends_on": [],
  "gate": "G0"
}
```

| Field | Required | Description |
|---|---|---|
| `node_id` | ✅ | Unique within workflow |
| `agent` | ✅ | Agent name (must exist in `AGENTS/`) |
| `action` | ✅ | Action name the agent exposes |
| `inputs` | | Map: param → source (see **Input sources**) |
| `outputs` | | Map: output_key → destination (see **Output destinations**) |
| `depends_on` | | Array of node_ids (alternative to `edges`) |
| `gate` | | Gate ID to evaluate before this node |

### Edges

Explicit dependencies (alternative to `depends_on`):

```json
{ "from": "analyze", "to": "design" }
```

The engine uses **both** `depends_on` and `edges` to build the DAG.

### Gates

Gates that must PASS before a node executes. Referenced by node's `gate` field.

```json
{
  "gate_id": "G2",
  "description": "Implementation verified",
  "criteria": "All tests pass and review approved"
}
```

Gates are evaluated by the **coordinator** agent via `se gate`. See `DOCS/reference/gates.md`.

---

## Input sources (how nodes get data)

| Prefix | Example | Resolved from |
|---|---|---|
| `context:` | `context:requirements` | Previous node outputs (merged into execution context) |
| `memory:` | `memory:analysis_result` | Engram memory (project-scoped) |
| `literal:` | `literal:backend` | Static value (string after `literal:`) |
| *(none)* | `requirements` | Treated as `context:requirements` |

### Resolution order

1. `context:` — execution context (outputs from completed nodes)
2. `memory:` — Engram persistent memory (`se memory get`)
3. `literal:` — static string
4. bare key — falls back to `context:`

---

## Output destinations (where node results go)

| Prefix | Example | Stored in |
|---|---|---|
| `memory:` | `memory:analysis_result` | Engram (persistent, project-scoped) |
| `artifact:` | `artifact:implementation` | Project artifact store (`PROJECTS/<name>/artifacts/`) |
| `evidence:` | `evidence:verification_result` | Evidence log (`PROJECTS/<name>/evidence/`) |
| `context:` | `context:analysis` | Execution context only (ephemeral, next nodes) |
| *(none)* | `analysis` | `context:` (ephemeral) |

---

## Context passing (how data flows)

```
Node A (outputs: {analysis: "memory:result"})
    │
    ▼ execution context updated with Node A outputs
Node B (inputs: {analysis: "context:analysis"})
    │
    ▼ uses Node A's result
```

The engine merges each node's `outputs` into a shared `context` dict. Subsequent nodes read via `context:key` or `memory:key`.

---

## Agents & actions

Nodes reference agents by name (must exist in `AGENTS/<name>/agent.json`). Each agent exposes **actions** defined in its contract.

| Agent | Typical actions |
|---|---|
| `analyst` | `analyze_requirements`, `discover`, `formalize` |
| `architect` | `create_design`, `review_architecture` |
| `implementer` | `implement_feature`, `refactor` |
| `tester` | `verify_implementation`, `design_tests` |
| `reviewer` | `review_code`, `review_design` |
| `planner` | `create_plan`, `estimate_effort` |
| `coordinator` | `gate_evaluation`, `transition`, `orchestrate` |
| `security` | `assess_risk`, `audit` |
| `documentation` | `write_docs`, `update_changelog` |

Actions are arbitrary strings — the agent's LLM prompt receives the action name and decides what to do.

---

## Execution lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│  orchestrate execute --workflow WF-0001 --project PRJ-APP   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Load workflow + validate against schema                 │
│  2. Topological sort (Kahn) → execution_order               │
│  3. For each node in order:                                 │
│       a) If node.gate → evaluate_gate() → must PASS         │
│       b) Resolve inputs (context/memory/literal)            │
│       c) Instantiate AgentRunner(agent)                     │
│       c) runner.run(action, inputs, context)                │
│       d) On FAIL → stop, return error                       │
│       e) On COMPLETED → merge outputs into context          │
│  4. Return {execution_id, status, node_states, context}     │
└─────────────────────────────────────────────────────────────┘
```

---

## Resume from node

```bash
python SCRIPTS/se.py orchestrate execute \
  --workflow WF-0001 --project PROJECTS/MyApp \
  --start-node implement
```

- Computes reachable nodes from `start_node` (forward reachability)
- Re-executes only that subgraph
- Previous node outputs must exist in memory/context

---

## Dry-run (validate + plan only)

```bash
python SCRIPTS/se.py orchestrate execute \
  --workflow WF-0001 --project PROJECTS/MyApp \
  --dry-run
```

Returns: `{execution_order, nodes, gates, status: "DRY_RUN"}` — no agents run, no gates evaluated.

---

## Machine-readable output

Add `--json` to any subcommand for `se.report/1` envelope:

```bash
python SCRIPTS/se.py orchestrate execute --workflow WF-0001 --project PRJ-APP --json
```

---

## Complete example

### 1. Project exists

```bash
python SCRIPTS/se.py init --dir PROJECTS/MyApp --name "MyApp" --owner "me" --domains software
```

### 2. Create workflow files

**nodes.json**
```json
[
  {
    "node_id": "analyze",
    "agent": "analyst",
    "action": "analyze_requirements",
    "inputs": { "requirements": "context:requirements" },
    "outputs": { "analysis": "memory:analysis_result" },
    "depends_on": []
  },
  {
    "node_id": "design",
    "agent": "architect",
    "action": "create_design",
    "inputs": { "analysis": "memory:analysis_result" },
    "outputs": { "design": "memory:design_result" },
    "depends_on": ["analyze"]
  },
  {
    "node_id": "implement",
    "agent": "implementer",
    "action": "implement_feature",
    "inputs": { "design": "memory:design_result" },
    "outputs": { "code": "artifact:implementation" },
    "depends_on": ["design"]
  },
  {
    "node_id": "verify",
    "agent": "tester",
    "action": "verify_implementation",
    "inputs": { "code": "artifact:implementation", "design": "memory:design_result" },
    "outputs": { "verification": "evidence:verification_result" },
    "depends_on": ["implement"],
    "gate": "G2"
  }
]
```

**edges.json** (optional; `depends_on` suffices)
```json
[
  {"from": "analyze", "to": "design"},
  {"from": "design", "to": "implement"},
  {"from": "implement", "to": "verify"}
]
```

**gates.json**
```json
[
  { "gate_id": "G2", "description": "Implementation verified", "criteria": "Tests pass + review approved" }
]
```

### 3. Create workflow

```bash
python SCRIPTS/se.py orchestrate create --project PROJECTS/MyApp \
  --name "Feature Development" \
  --nodes nodes.json --edges edges.json --gates gates.json
```

Output: `Created workflow WF-0001 at PROJECTS/MyApp/workflows/WF-0001.json`

### 4. Dry-run

```bash
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp --workflow WF-0001 --dry-run
```

Output:
```json
{
  "execution_order": ["analyze", "design", "implement", "verify"],
  "nodes": ["analyze", "design", "implement", "verify"],
  "gates": [{"gate_id": "G2", ...}],
  "status": "DRY_RUN"
}
```

### 5. Execute

```bash
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp --workflow WF-0001
```

---

## Error handling

| Failure mode | Behavior |
|---|---|
| Gate FAIL | Execution stops immediately, returns error |
| Node FAIL | Execution stops, returns error + partial context |
| Cycle detected | Validation fails before execution |
| Missing dependency | Validation fails (node not reachable) |
| Agent not found | Node FAIL with descriptive error |
| Schema validation error | Create/execute fails with details |

---

## File locations

| Artifact | Path |
|---|---|
| Workflow definitions | `PROJECTS/<name>/workflows/WF-XXXX.json` |
| Workflow schema | `SCHEMAS/workflow/workflow.schema.json` |
| Execution schema | `SCHEMAS/workflow/execution.schema.json` |
| Engine code | `SCRIPTS/se_core/orchestration/engine.py` |
| Agent runner | `SCRIPTS/se_core/agents/runner.py` |
| Gate evaluator | `SCRIPTS/se_core/gates.py` |
| Memory engine | `SCRIPTS/se_core/memory/engine.py` |

---

## See also

- `se orchestrate --help` — CLI reference
- `DOCS/reference/gates.md` — Gate definitions and evaluation
- `DOCS/reference/memory.md` — Engram memory model
- `SCHEMAS/workflow/workflow.schema.json` — Authoritative schema