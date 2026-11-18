# Architecture

SYSTEM ENGINEERING (SE) is a **project operating system for AI-assisted work**: a set
of contracts (schemas, models, policies) plus a thin reference implementation that
gives an AI coding runtime a process to execute instead of improvised prompting.

It is domain-agnostic. The same system governs software, data, cloud, security, media
or design work, because what it governs is the *process* — not the artifact type.

This page is the mental model. It takes about ten minutes and explains what the parts
are, how a piece of work moves through them, and where the boundaries are.

---

## 1. The problem it solves

An AI agent with a large context window can write code; it cannot, by itself, keep a
process. The failure modes are specific:

| Failure | What SE adds |
|---|---|
| Long sessions burn tokens re-explaining the same context | A coordinator delegates to subagents with their own fresh context; only results return |
| Decisions evaporate between sessions | Persistent memory, stored with the project, not in the model |
| Everything runs in one giant prompt | Roles, commands and skills are loaded on demand |
| "It works on my machine" process | A lifecycle where every transition is gated and recorded |
| Nobody can audit what happened | Work produces artifacts, evidence and receipts instead of claims |

## 2. The core loop: a lifecycle with gates

A **project** is the thing SE governs. It is always in exactly one lifecycle state,
and it can only move forward through a gate.

```
DRAFT ──G0──▶ DISCOVERY ──G1──▶ PLANNING ──G2,G3──▶ ACTIVE ──G4──▶ VERIFICATION
                                                                        │
     ARCHIVED ◀── OPERATING ◀──G8── RELEASED ◀──G6,G7── ACCEPTANCE ◀──G5─┘
```

- **Gates are checks, not ceremonies.** Each gate declares conditions over the
  project's records. `FAIL` and `WARN` block the transition; `MANUAL` needs a written
  human attestation and is never auto-passed.
- **`BLOCKED` is a condition, not a state.** It is recorded with a reason and a
  resolution path, and the project stays where it was.
- **The state machine is data.** It lives in `CORE/lifecycle/lifecycle.json`, so the
  CLI, the gate evaluator and the console read the same definition.

## 3. Who does the work: one coordinator, many roles

Twelve roles are defined in `AGENTS/`, each with its own permissions and, optionally,
its own model.

- **`shema-ai-coordinador`** is the primary agent. It owns the lifecycle: it reads the
  state, decides the next step and routes work to the other roles.
- The other eleven are **subagents**: explorer, analyst, architect, planner,
  implementer, tester, reviewer, security, documentation, devops and visual. Each runs
  in a **fresh context**, receives only what it needs, and returns only its result.
  That is the token economy: context does not accumulate across roles.
- Some roles carry a **work mode**: an `SDD` must exist before `spec` work, an `RDD`
  before `receipt` work. The rule is executable, not advice — it lives in
  `CORE/policies/ceremony.json` and `se validate --project` enforces it.

## 4. What a project produces

Work leaves records, not opinions. Every record is a JSON artifact validated against a
schema in `SCHEMAS/`, and every one is addressable by id so it can be referenced.

| Record | What it captures |
|---|---|
| `PROJECT.json` | Identity, owner, domains, criticality, current lifecycle state |
| `discovery.json` | Context, constraints, unknowns found before planning |
| `REQ-####` | Requirements, assumptions, constraints, risks |
| `TASK-####` | Units of work, with dependencies and gates |
| `EVD-####` | Evidence: the proof that something was done |
| `DEC-####` | Decisions, including architectural ones (ADRs) |
| `SDD / ODD / RDD` | The design and review records the work modes require |
| `REL-####` | Releases, with an explicit approver |

Two properties matter for a newcomer:

- **Traceability is bidirectional.** Forward: objective → requirement → task →
  implementation → test → evidence → acceptance → release. Reverse: release → changes
  → tasks → requirements → objectives. `se trace` walks that graph, read-only.
- **The project keeps its history.** `PROJECTS/` is excluded from this repository's
  version control; each project has its own repository and its own artifacts. SE is
  never coupled to the projects it governs.

## 5. The three surfaces

| Surface | What it is | Where it lives |
|---|---|---|
| **CLI** | `se <command>` over the reference Python implementation | `SCRIPTS/` |
| **Console** | Local, read-only web view of the system's state and attention list; three token-authenticated actions | `SE-CONSOLE/` |
| **Runtime adapters** | The generated agent layer (agents, commands, skills) for OpenCode, Claude Code or Codex | `.opencode/`, `.claude/`, `.codex/` — generated from `AGENTS/`, `COMMANDS/`, `SKILLS/` |

The adapters are **outputs**, never sources: edit the contracts, regenerate. The CLI
and the console are clients of the same contracts.

## 6. How one run executes

A workflow is a DAG of nodes; `OrchestrationEngine.execute` is the single entry point.

1. The workflow is validated against its schema and ordered topologically.
2. Each node is dispatched by one of two routes: the **native route**, where the
   coordinator delegates to a subagent with real tools, or the **internal route**,
   where `AgentRunner` runs in-process and dispatches only the `memory` tool.
3. A node's output can travel **inline** or as a **reference** (`memory:MEM-0007`,
   `literal:`), so a large payload stays in the project and only its id moves.
4. Each node declares its gates; `FAIL`/`WARN` block, `MANUAL` is recorded.
5. A checkpoint (`CP-NNNN`) is written per node and at the end, which is what makes a
   run resumable.

## 7. Layers and boundaries

```
SCHEMAS        machine-readable contracts for artifacts
CORE           lifecycle, gates, task states, artifact + permission models
DOMAINS        additive domain packs (software, security, cloud, ...)
AGENTS         agent contract + the 12 role definitions
TEMPLATES      fill-in artifact templates
COMMANDS       the conceptual command interface
POLICIES       human-readable normative policies
SCRIPTS        reference implementation (Python)
INTEGRATIONS   tool adapters (OpenCode, Claude Code, Codex, CI) — outside CORE
SE-CONSOLE     local web console
SE-INSTALLER   the unified installer
DOCS           this documentation, the ADRs and the working records
TESTS          hermetic tests for the system itself
```

**Boundaries, stated as rules:**

- **Tool independence.** `CORE/` and `SCHEMAS/` contain no tool-specific concept; tool
  integration lives in `INTEGRATIONS/`.
- **Additive extension.** Domain packs extend `CORE/`; they never override it.
- **Evidence over trust.** A claim without an evidence artifact is a claim.
- **No credentials, no provider calls.** SE ships no keys and calls no model by itself;
  it generates the agent layer for the runtime you already use.

## 8. What SE is not

- Not a model, an API or a hosted service.
- Not a framework you import: it is a process your runtime executes, plus a CLI.
- Not a replacement for your runtime: it needs one to drive agents.
- Not production-validated yet: the current version is a foundation, usable and tested,
  but young.

## 9. Where to go next

| If you want to… | Read |
|---|---|
| understand the records and gates in detail | [`core-model.md`](core-model.md) |
| install it and run the first project | [`installation.md`](installation.md) |
| drive an agent runtime | [`adapters.md`](adapters.md) and [`commands.md`](commands.md) |
| understand multi-agent runs | [`workflows.md`](workflows.md) |
| know when a mode is mandatory | [`work-modes.md`](work-modes.md) |
| see the decisions behind the design | [`../adr/`](../adr/) |
| look at it visually | the [interactive map](https://shemasoft.github.io/SYSTEM-ENGINEERING/) |
