# ADR-003: P3-B.1 On-Demand Memory Reference Resolution via Tool

## Status
Accepted

## Context
Large agent outputs (100KB+) were being passed inline through workflow context, causing token bloat and context window pressure. The P3-B.1 implementation introduces a `memory` tool that allows agents to store large outputs as memory references and retrieve them on-demand.

## Decision
Implement a tool-based on-demand reference resolution mechanism where:
1. Producer nodes declare outputs with `memory:new:topic_key` → engine creates memory, stores reference in context
2. Consumer nodes receive reference dict `{"memory_id": "...", "topic_key": "...", "param": "..."}` via `context:` inputs
3. Consumer agents explicitly call `memory.get({"action": "get", "memory_id": "..."})` to retrieve content
4. No automatic resolution — LLM decides when to fetch (token economy)

## Implementation Details

### Files Modified
| File | Changes |
|------|---------|
| `SCRIPTS/se_core/agents/runner.py` | +499/-10: memory_engine injection, memory tool definition, _invoke_memory_tool, SIMULATED handling |
| `SCRIPTS/se_core/orchestration/engine.py` | +329/-5: _execute_node passes memory_engine, _resolve_node_outputs, _extract_output_refs, context pruning, workflow telemetry |
| `SCRIPTS/se_core/llm/providers.py` | +18: cached_tokens extraction for OpenAI/Anthropic/Local |
| `SCRIPTS/se_core/commands.py` | +8/-1: CLI subagent checks actual provider type for SIMULATED detection |
| `TESTS/test_orchestrate.py` | +349/-2: 9 new tests (7 unit + 2 integration) |

### Memory Tool Schema
```json
{
  "name": "memory",
  "description": "Retrieve or search project memories",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["get", "search"]},
      "memory_id": {"type": "string"},
      "query": {"type": "string"},
      "project_id": {"type": "string"},
      "limit": {"type": "integer", "default": 10}
    },
    "required": ["action"]
  }
}
```

### Output Destination Prefixes
| Prefix | Behavior |
|--------|----------|
| `memory:new:topic_key` | Create new memory with topic_key (upsert), store reference |
| `memory:mem_id` | Reference existing memory by ID |
| `literal:value` | Inline literal value |
| (none) | Direct value from agent output |

### Reference Flow
```
Producer: outputs={"result": "memory:new:shared_data"}
  → Engine creates memory MEM-123
  → Context["result"] = {"memory_id": "MEM-123", "topic_key": "shared_data", "param": "result"}

Consumer: inputs={"data": "context:result"}
  → Receives: inputs["data"] = {"memory_id": "MEM-123", "topic_key": "shared_data", "param": "result"}

Consumer calls: memory.get({"action": "get", "memory_id": "MEM-123"})
  → Returns: {"status": "OK", "content": {"result": "large_content_here"}}
```

## Security
- Project isolation: `project_id` required, validated against memory_engine
- Agent permissions: `READ` permission required for memory operations
- Explicit errors for missing/invalid references, cross-project access

## Performance
| Scenario | Context Size | Reduction |
|----------|--------------|-----------|
| Inline (100KB) | 100,014 bytes | baseline |
| Reference | 84 bytes | **99.9%** |

*Note: Measures Python context size (proxy). Actual token savings depend on LLM provider and whether downstream resolves.*

## Testing
- 209/209 tests pass
- 7 unit tests for memory tool (get, search, errors, cross-project)
- 2 integration tests for end-to-end reference resolution
- SIMULATED status propagation for checkpoint/resume

## Limitations
1. **Internal route requires explicit `memory.get()`** — No auto-resolution (P3-A Dispatcher will address)
2. **No TTL/GC for transient outputs** — Documented; future issue for retention policy
3. **Benchmark measures context size, not actual tokens** — Requires real LLM provider for accurate measurement

## Related
- P3-A: Dispatcher for automatic reference resolution
- P3-C: Native path economy (subagent tool)
- TTL/GC for transient memory outputs