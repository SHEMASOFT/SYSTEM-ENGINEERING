# `se orchestrate` — Workflow orchestration

Manage and execute deterministic, gate-driven workflows inside managed projects.

---

## Synopsis

```bash
se orchestrate <command> [options]
```

| Subcommand | Description |
|---|---|
| `create` | Create a new workflow definition from JSON files |
| `execute` | Execute a workflow (or dry-run) |
| `list` | List workflows in a project |

---

## `se orchestrate create`

Create a workflow definition from JSON files.

```bash
se orchestrate create --project <dir> --name <str> \
  --nodes <file> [--edges <file>] [--gates <file>] [--json]
```

### Options

| Option | Required | Description |
|---|---|---|
| `--project <dir>` | ✅ | Managed project workspace (must have `PROJECT.json`) |
| `--name <str>` | ✅ | Human-readable workflow name |
| `--description <str>` | | Workflow description |
| `--nodes <file>` | ✅ | JSON file with array of node definitions |
| `--edges <file>` | | JSON file with array of edge definitions |
| `--gates <file>` | | JSON file with array of gate assignments |
| `--json` | | Emit `se.report/1` envelope instead of text |

### Node definition (required fields)

```json
{
  "node_id": "unique_id",
  "agent": "analyst",
  "action": "analyze_requirements",
  "inputs": { "param": "context:key" },
  "outputs": { "out_key": "memory:mem_id" },
  "depends_on": ["other_node"],
  "gate": "G0"
}
```

### Edge definition

```json
{ "from": "node_a", "to": "node_b" }
```

### Gate definition

```json
{ "gate_id": "G2", "description": "Verification done", "criteria": "Tests pass" }
```

### Example

```bash
se orchestrate create --project PROJECTS/MyApp \
  --name "Feature Development" \
  --nodes nodes.json --edges edges.json --gates gates.json
```

Output (text):
```
Created workflow WF-0001 at PROJECTS/MyApp/workflows/WF-0001.json
```

Output (`--json`):
```json
{
  "status": "COMPLETED",
  "workflow_id": "WF-0001",
  "path": "PROJECTS/MyApp/workflows/WF-0001.json"
}
```

---

## `se orchestrate execute`

Execute a workflow (or dry-run to validate).

```bash
se orchestrate execute --workflow <WF-XXXX> --project <dir> \
  [--execution-id <str>] [--start-node <node_id>] [--dry-run] [--json]
```

### Options

| Option | Required | Description |
|---|---|---|
| `--workflow <WF-XXXX>` | ✅ | Workflow ID to execute |
| `--project <dir>` | ✅ | Managed project workspace |
| `--execution-id <str>` | | Custom execution ID (auto-generated if omitted) |
| `--start-node <node_id>` | | Resume from this node (computes forward reachable subgraph) |
| `--dry-run` | | Validate and plan only; no agents run, no gates evaluated |
| `--json` | | Emit `se.report/1` envelope |

### Dry-run example

```bash
se orchestrate execute --workflow WF-0001 --project PROJECTS/MyApp --dry-run
```

Output:
```json
{
  "execution_id": "WEX-1234",
  "workflow_id": "WF-0001",
  "status": "DRY_RUN",
  "execution_order": ["analyze", "design", "implement", "verify"],
  "nodes": ["analyze", "design", "implement", "verify"],
  "gates": [{"gate_id": "G2", "description": "..."}]
}
```

### Execute example

```bash
se orchestrate execute --workflow WF-0001 --project PROJECTS/MyApp
```

Output (success):
```json
{
  "execution_id": "WEX-5678",
  "workflow_id": "WF-0001",
  "project_id": "PRJ-MYAPP",
  "status": "COMPLETED",
  "completed_at": "2026-10-10T12:34:56Z",
  "node_states": {
    "analyze": {"status": "COMPLETED", "outputs": {"analysis": "..."}},
    "design": {"status": "COMPLETED", "outputs": {"design": "..."}},
    "implement": {"status": "COMPLETED", "outputs": {"code": "..."}},
    "verify": {"status": "COMPLETED", "outputs": {"verification": "..."}}
  },
  "gate_results": {
    "G2": {"status": "PASS", "detail": "All tests pass"}
  },
  "context": { "analysis": "...", "design": "...", "code": "...", "verification": "..." }
}
```

Output (failure):
```json
{
  "execution_id": "WEX-9999",
  "workflow_id": "WF-0001",
  "status": "FAILED",
  "error": "Gate G2 failed: Tests failed"
}
```

### Resume from node

```bash
se orchestrate execute --workflow WF-0001 --project PROJECTS/MyApp --start-node implement
```

- Computes all nodes reachable from `implement` (forward)
- Re-executes only that subgraph
- Requires previous outputs in memory/context

---

## `se orchestrate list`

List all workflows in a project.

```bash
se orchestrate list --project <dir> [--json]
```

### Example

```bash
se orchestrate list --project PROJECTS/MyApp
```

Output:
```
WF-0001  Feature Development          DRAFT    4 nodes  3 edges  1 gates
WF-0002  Bugfix Workflow              ACTIVE   2 nodes  1 edges  0 gates
```

With `--json`:
```json
{
  "workflows": [
    {
      "workflow_id": "WF-0001",
      "name": "Feature Development",
      "status": "DRAFT",
      "nodes": 4,
      "edges": 3,
      "gates": 1,
      "created_at": "2026-10-10T12:00:00Z"
    }
  ]
}
```

---

## Workflow file locations

Created workflows are saved to:

```
PROJECTS/<project_name>/workflows/WF-XXXX.json
```

The `WF-XXXX` ID is auto-assigned (sequential per project).

---

## JSON input files format

### nodes.json (array)

```json
[
  {
    "node_id": "analyze",
    "agent": "analyst",
    "action": "analyze_requirements",
    "inputs": { "requirements": "context:requirements" },
    "outputs": { "analysis": "memory:analysis_result" },
    "depends_on": [],
    "gate": "G0"
  }
]
```

### edges.json (array, optional)

```json
[ {"from": "analyze", "to": "design"} ]
```

### gates.json (array, optional)

```json
[ { "gate_id": "G2", "description": "Implementation verified", "criteria": "Tests pass" } ]
```

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Failure (validation error, execution failure, missing args) |

---

## See also

- `DOCS/reference/workflows.md` — Complete workflow reference (nodes, edges, gates, memory, context, agents)
- `SCHEMAS/workflow/workflow.schema.json` — Authoritative schema
- `se gate --help` — Gate evaluation
- `se memory --help` — Memory operations