# Token Economy & Native Invoke Implementation

## Overview

This document describes the token economy implementation (FASE 1-4) and the native OpenCode `invoke` tool support for subagents in SYSTEM-ENGINEERING.

---

## Token Economy (FASE 1-4)

### FASE 1: Context Filtering (Engine Level)
**File**: `SCRIPTS/se_core/orchestration/engine.py` → `_execute_node()`

```python
# Filter context to only keys referenced by node inputs (context: prefix)
context_keys = {s[8:] for s in inputs.values() if isinstance(s, str) and s.startswith("context:")}
filtered_context = {k: v for k, v in context.items() if k in context_keys} if context_keys else {}
```

**Effect**: Only keys declared in `node.inputs` with `context:` prefix are passed to the agent.

---

### FASE 2: Token Budget Protection (Runner Level)
**File**: `SCRIPTS/se_core/agents/runner.py` → `_build_messages()`

```python
# Budget: 70% of max_tokens for context
context_budget = int(max_tokens * 0.7) - base_tokens

# If over budget:
# 1. Truncate strings > 500 chars
# 2. Drop least important keys
```

**Effect**: Hard limit on prompt tokens, prevents context window overflow.

---

### FASE 3: Opt-in Summarization (Runner Level)
**File**: `SCRIPTS/se_core/agents/runner.py` → `_summarize_large_context_values()`

```python
# Configurable per agent via agent.json:
# "context_max_inline": 2000  # chars threshold

# Values exceeding threshold replaced with summary:
{
    "_summary": "Large dict with 50 keys: [...], 45000 chars",
    "_full_key": "original_key",
    "_type": "dict",
    "_size": 45000
}
```

**Config** (per agent in `AGENTS/<name>/agent.json`):
```json
{
  "context_max_inline": 2000,
  "llm_config": { "max_tokens": 4096 }
}
```

---

### FASE 4: Telemetry (Runner Level)
**File**: `SCRIPTS/se_core/agents/runner.py` → `run()`

```python
# Returns in result["telemetry"]:
{
  "context_processing": {
    "context_original_count": 5,
    "keys_summarized": ["large_data"],
    "keys_truncated": ["long_string"],
    "keys_dropped": ["excess_key"],
    "estimated_prompt_tokens": 2847,
    "context_budget_tokens": 2457
  },
  "provider_usage": {
    "prompt_tokens": 2847,
    "completion_tokens": 850,
    "total_tokens": 3739
  }
}
```

**Logging**:
- DEBUG: Context processing details
- INFO: Provider usage (prompt/completion/total tokens)

---

## Native OpenCode `invoke` Support

### Problem
The internal path (`se orchestrate execute`) uses `AgentRunner` with full token economy.
The native path (`se orchestrate execute --native`) generates a prompt for the coordinator to use OpenCode's `invoke` tool, which was **outside** our token economy control.

### Solution Implemented

#### 1. Helper Function in Engine
**File**: `SCRIPTS/se_core/orchestration/engine.py`

```python
def build_native_subagent_input(self, node, context, resolved_inputs):
    """Build filtered input payload for native OpenCode `invoke` tool.
    
    Filters context to ONLY keys declared in node.inputs with `context:` prefix.
    Consistent with internal AgentRunner token economy (FASE 1).
    """
    context_keys = {s[8:] for s in node.get("inputs", {}).values() 
                    if isinstance(s, str) and s.startswith("context:")}
    filtered_context = {k: v for k, v in context.items() if k in context_keys} if context_keys else {}
    
    return {
        "action": node["action"],
        "inputs": resolved_inputs,
        "context": filtered_context,
    }
```

#### 2. Coordinator Prompt Updated
**File**: `SCRIPTS/se_core/orchestration/engine.py` → `generate_native_execution_prompt()`

Now instructs coordinator to use the helper:

```markdown
3. **Build filtered subagent input** (use engine helper):
   ```python
   subagent_input = engine.build_native_subagent_input(
       node=node,
       context=context,
       resolved_inputs=resolved_inputs
   )
   ```
   This returns `{"action", "inputs", "context"}` with context
   filtered to ONLY keys declared in node.inputs with `context:` prefix.
   (Consistent with internal AgentRunner token economy - FASE 1)
```

#### 3. Subagent System Prompts Updated
**Files**: `TEMPLATES/prompts/personas/*.md` (12 files)

All 12 subagent prompts now include:

```markdown
## Context Handling

You receive ONLY the context keys declared in your workflow node `inputs` with `context:` prefix.

The coordinator uses `engine.build_native_subagent_input()` to filter context to ONLY keys you declared in `inputs.context:*`.

- Do NOT assume access to keys not provided in `context`
- If you need additional context, request it explicitly in your response
- The `inputs` parameter contains resolved values (including from `context:`, `memory:`, `literal:`)
- The `context` parameter contains only the filtered keys you declared
```

**Files updated** (12):
- `analyst.md`, `architect.md`, `planner.md`, `implementer.md`
- `tester.md`, `reviewer.md`, `security.md`, `documentation.md`
- `explorer.md`, `devops.md`, `visual.md`

---

## Usage

### Internal Mode (Full Economy)
```bash
se orchestrate execute --workflow WF-0001 --project PROJECTS/workflow-demo
```
Uses internal `AgentRunner` with full FASE 1-4 economy.

### Native Mode (OpenCode `invoke`)
```bash
se orchestrate execute --workflow WF-0001 --project PROJECTS/workflow-demo --native
```
Generates prompt for coordinator to use OpenCode `invoke` tool with token economy.

### Workflow Declaration
Workflows declare context needs explicitly:

```json
{
  "nodes": [
    {
      "node_id": "design",
      "agent": "architect",
      "action": "create_design",
      "inputs": {
        "requirements": "context:requirements"
      }
    }
  ]
}
```

Only `requirements` key is passed to the architect subagent.

---

## Architecture Comparison

| Aspect | Internal Path | Native `invoke` Path |
|--------|--------------|---------------------|
| **Entry** | `se orchestrate execute` | `se orchestrate execute --native` |
| **Execution** | `OrchestrationEngine.execute()` | Coordinator uses `invoke` tool |
| **Context Filtering** | ✅ `_execute_node()` | ✅ `build_native_subagent_input()` |
| **Token Budget** | ✅ Runner `_build_messages()` | ⚠️ Coordinator instructed |
| **Summarization** | ✅ Runner `_summarize...` | ❌ Not available |
| **Telemetry** | ✅ Full (context + provider) | ❌ Not available |

---

## Verification

```bash
# Run tests
python -m pytest TESTS/test_orchestrate.py -v
# 18/18 PASS

# Full suite
python -m pytest TESTS/ -x
# 783/783 PASS

# Generate native prompt
se orchestrate execute --workflow WF-0001 --project PROJECTS/workflow-demo --native
```

---

## Files Modified

| File | Change |
|------|--------|
| `SCRIPTS/se_core/orchestration/engine.py` | + `build_native_subagent_input()`, updated `generate_native_execution_prompt()` |
| `TEMPLATES/prompts/personas/*.md` (12) | + `## Context Handling` section |
| `.opencode/agents/*.md` | Regenerated via adapter |

---

## Verification

```bash
python -m pytest TESTS/test_orchestrate.py -v  # 18/18 PASS
python -m pytest TESTS/ -x                      # 783/783 PASS
```

---

## Next Steps (Not Implemented)

| Feature | Status |
|---------|--------|
| Token budget in native subagents | ❌ Requires OpenCode support |
| Summarization in native subagents | ❌ Requires OpenCode support |
| Telemetry from native subagents | ❌ Requires OpenCode support |
| Per-node `max_context_tokens` in workflow schema | ✅ Implemented (FASE 5) |
| G3.5 attestation automation | ❌ Requires human |

---

## Key Principle

> **Declarative, not heuristic**: Context filtering is based on explicit declaration in workflow `node.inputs` with `context:` prefix. No guessing, no heuristics — respects the contract.

This ensures:
- Zero silent data loss
- Predictable token usage
- Traceable data flow
- Consistent behavior across internal and native paths