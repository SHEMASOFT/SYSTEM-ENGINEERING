# Architecture

SYSTEM ENGINEERING is a reusable, domain-agnostic **Project Operating System**. It is the
smallest system capable of becoming the larger system: a set of contracts (schemas, models,
policies) plus a thin reference implementation, all tool-independent.

## Layers

```
SCHEMAS        machine-readable contracts for artifacts
CORE           lifecycle, gates, task states, artifact + permission models
DOMAINS        additive domain packs (software, security, cloud, ...)
AGENTS         agent contract + 12 agent definitions
TEMPLATES      fill-in artifact templates
COMMANDS       conceptual command interface
SCRIPTS        reference implementation (Python)
POLICIES       human-readable normative policies
DOCS           this documentation + ADRs
TESTS          hermetic tests for the system itself
INTEGRATIONS   tool adapters (e.g. OpenCode) — outside CORE
```

## Data flow

```
                 PROJECT.json (identity + lifecycle state)
                        |
   discovery.json --> REQUIREMENT --> TASK --> implementation
                        |             |          |
                        |             v          v
                        +---------> EVIDENCE <---+
                        |             |
                        v             v
                    DECISION       RELEASE
```

Traceability is bidirectional:

- forward: OBJECTIVE -> REQUIREMENT -> TASK -> IMPLEMENTATION -> TEST -> EVIDENCE ->
  ACCEPTANCE -> RELEASE
- reverse: RELEASE -> CHANGES -> TASKS -> REQUIREMENTS -> OBJECTIVES

## Principles

SIMPLE, MODULAR, TRACEABLE, VERIFIABLE, EXTENSIBLE, DOMAIN-AGNOSTIC,
HUMAN-CONTROLLED, AUTOMATION-FRIENDLY, TOOL-INDEPENDENT.

## Key design decisions

- **Tool independence.** CORE and SCHEMAS contain no OpenCode-specific concepts. Tool
  integration lives in `INTEGRATIONS/`.
- **Gates are additive and mostly automated.** Manual conditions are never auto-passed.
- **Evidence over trust.** Claims must be backed by evidence artifacts.
- **Additive extension.** Domain packs extend CORE; they never override it.

See [`adr/`](../adr/) for recorded decisions and [`core-model.md`](core-model.md) for the model.
