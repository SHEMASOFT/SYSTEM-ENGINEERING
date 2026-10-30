# ADR-004: P3 Complete — Token Economy & Reference Resolution

## Status
Accepted

## Summary
Implemented the complete P3 token economy and reference resolution pipeline across three phases:

### P3-B.1: On-Demand Memory Reference Resolution (Internal Route)
- **AgentRunner**: `memory` tool (get/search) with project isolation, READ permission checks
- **Engine**: `_resolve_node_outputs` for `memory:new:`, `memory:`, `literal:` prefixes
- **Dispatcher**: Automatic resolution of `{"memory_id": "..."}` refs in inputs/context (P3-A)
- **Context pruning**: `_compute_live_context_keys`, `_prune_context` for resume
- **Telemetry**: Workflow-level token aggregation (P1/P2)
- **Benchmark**: 99.9% context size reduction (100KB → 84 bytes reference)

### P3-A: Dispatcher — Auto-Resolution
- **ReferenceDispatcher**: Resolves `{"memory_id": "..."}` refs in inputs/context before LLM call
- **Config**: `auto_resolve_refs: true/false` per node (default: true)
- **Schema**: Added `auto_resolve_refs` to node definition
- **Backward compatible**: Internal route still works with explicit `memory.get()`

### P3-B.1 TTL/GC: Memory Retention
- **Schema**: `ttl_days`, `expires_at`, `gc_protected` fields
- **Engine.add()**: Accepts `ttl_days`, computes `expires_at`
- **Engine.gc()**: Filters by `older_than_days`, `tag_filter`, `state_filter`, `dry_run`
- **CLI**: `se memory gc` command
- **Protection**: `gc_protected` flag prevents accidental deletion

### P3-C: Native Route Economy
- **Schema**: `execution_mode: "internal" | "native"` (default: internal)
- **Engine**: Returns `NATIVE` status with coordinator prompt for OpenCode `subagent` tool
- **Prompt**: Includes nodes, gates, context filtering, gate commands, background delegation
- **Helper**: `build_native_subagent_input()` for FASE 1 token economy (context filtering)
- **CLI**: `--native` flag generates prompt regardless of workflow config

## Test Results
| Phase | Tests | Status |
|-------|-------|--------|
| Core (P3-B.1) | 209 | ✅ |
| P3-A Dispatcher | +8 = 217 | ✅ |
| TTL/GC | +6 = 223 | ✅ |
| P3-C Native | +3 = 226 | ✅ |
| **Total** | **226** | **✅ All Pass** |

## Architecture Impact
| Aspect | Before | After |
|--------|--------|-------|
| Large output handling | Inline (100KB+) | Reference (84 bytes) |
| Reference resolution | Manual `memory.get()` | Auto (Dispatcher) or Manual |
| Memory lifecycle | Permanent | TTL + GC |
| Execution routes | Internal only | Internal + Native (subagent) |
| Token accounting | Heuristic (4 chars/token) | Real provider tokens (native) |

## Files Modified
- `SCRIPTS/se_core/agents/runner.py` — memory tool, SIMULATED, dispatcher integration
- `SCRIPTS/se_core/orchestration/engine.py` — dispatcher, context pruning, native mode, telemetry
- `SCRIPTS/se_core/orchestration/dispatcher.py` — NEW: ReferenceDispatcher
- `SCRIPTS/se_core/memory/engine.py` — TTL/GC, schema fields
- `SCRIPTS/se_core/llm/providers.py` — cached_tokens extraction
- `SCRIPTS/se_core/commands.py` — CLI subagent SIMULATED, memory gc
- `SCRIPTS/se_core/cli.py` — memory gc, orchestrate --native
- `SCHEMAS/workflow/workflow.schema.json` — execution_mode, auto_resolve_refs
- `SCHEMAS/memory/record.schema.json` — ttl_days, expires_at, gc_protected
- `TESTS/test_orchestrate.py` — 21 new tests
- `TESTS/test_memory.py` — 6 new TTL/GC tests
- `DOCS/adr/P3_B1_ADR.md` — Architecture decision record