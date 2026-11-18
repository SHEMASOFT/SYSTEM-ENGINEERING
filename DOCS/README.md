# Documentation

SYSTEM ENGINEERING is a process your AI runtime executes, plus the contracts that
define it. This page tells you which document to read for what — by intent, not by
file name.

## Three doors

| You want | Read | Time |
|---|---|---|
| **to understand what this is** | [`reference/architecture.md`](reference/architecture.md) — the mental model: lifecycle, roles, records, surfaces, boundaries | 10 min |
| **to install it and validate the checkout** | [`reference/installation.md`](reference/installation.md) — one command, browser UI, or the minimal path | 10 min |
| **to drive a project end to end** | [`reference/core-model.md`](reference/core-model.md) then [`reference/commands.md`](reference/commands.md) | 20 min |

Everything below is reference: read it when the task in front of you needs it.

## Understanding the system

| Document | What it explains |
|---|---|
| [`reference/architecture.md`](reference/architecture.md) | The system at a glance: the loop, the roles, the records, the three surfaces, the boundaries |
| [`reference/core-model.md`](reference/core-model.md) | Lifecycle, gates, task states, artifacts, permissions — the model in detail |
| [`reference/domains.md`](reference/domains.md) | Domain packs and how a project picks its domains |
| [`reference/extension-model.md`](reference/extension-model.md) | How to extend SE without touching the core |
| [`reference/schemas.md`](reference/schemas.md) | The JSON Schemas and how validation works |

## Running it

| Document | What it explains |
|---|---|
| [`reference/installation.md`](reference/installation.md) | Obtain SE, install, run the console, register MCPs, update |
| [`reference/se-installer.md`](reference/se-installer.md) | Inside the installer: components, model and MCP registries, agent binding, runtime config |
| [`reference/lifecycle.md`](reference/lifecycle.md) | `se install` / `sync` / `update` / `uninstall` and their safety rules |
| [`reference/project-bootstrap.md`](reference/project-bootstrap.md) | Creating and bootstrapping managed projects |
| [`reference/project-profile.md`](reference/project-profile.md) | Project manifest and profile fields |
| [`reference/versioning.md`](reference/versioning.md) | The current version and its references |
| [`reference/versioning-strategy.md`](reference/versioning-strategy.md) | How versions are bumped, and what counts as compatible |

## Working with a runtime

| Document | What it explains |
|---|---|
| [`reference/adapters.md`](reference/adapters.md) | Runtime adapters: OpenCode, Claude Code, Codex |
| [`reference/opencode-adapter.md`](reference/opencode-adapter.md) | How the OpenCode agent layer is generated |
| [`reference/commands.md`](reference/commands.md) | The command surface (`init`, `plan`, `gate`, `orchestrate`, …) |
| [`reference/workflows.md`](reference/workflows.md) | Multi-agent workflows: DAGs, gates, context passing |
| [`reference/checkpoint-recovery.md`](reference/checkpoint-recovery.md) | Workflow checkpoints and resuming an interrupted run |
| [`reference/memory.md`](reference/memory.md) | Memory: storage, commands, semantic reranker, session-start injection |
| [`reference/work-modes.md`](reference/work-modes.md) | organic / spec / receipt: when the agent must apply each one |
| [`reference/execution-integrity.md`](reference/execution-integrity.md) | Execution, integrity and evidence rules |
| [`reference/development-workflow.md`](reference/development-workflow.md) | Day-to-day development flow inside SE |
| [`../INTEGRATIONS/ci/README.md`](../INTEGRATIONS/ci/README.md) | CI governance adapter: provider-neutral scripts and a GitHub Actions reference workflow |

## Conventions and governance

| Document set | What it explains |
|---|---|
| [`reference/conventions/`](reference/conventions/) | Naming, precedence and per-phase conventions the agents follow |
| [`reference/governance/`](reference/governance/) | Capability governance and agent/permission governance |
| [`reference/policies/`](reference/policies/) | Minimum-context, project and state policies |
| [`reference/skills/`](reference/skills/) | How to author a skill in the Agent Skills format |
| [`reference/review-lenses.md`](reference/review-lenses.md) | Review lenses (`metadata.review_lens`) and their vocabulary |
| [`reference/visual-frontend-engineering.md`](reference/visual-frontend-engineering.md) | Building and reviewing frontends with verifiable visual evidence |

## Decisions

Every structural decision is an ADR under [`adr/`](adr/). Each one records the
context, the options considered, the decision and its consequences — including the
ones that were reverted later.

## How this folder is organised

Two kinds of material live here, and they must not be confused:

- **Reference** (`DOCS/reference/`, `DOCS/adr/`) — published guidance. It describes
  how the system works *today*, and it is the material a reader should trust.
- **Working records** (`DOCS/internal/`) — checkpoints, audits, reviews and validation
  reports, kept for provenance. The directory is gitignored and excluded from every
  check, so it is not published. It documents what happened, not how the system works;
  do not read it first and do not treat it as guidance.
