# Documentation index

Start here to understand, install and operate SYSTEM ENGINEERING.

## Core documents

| Document | What it explains |
|---|---|
| [`reference/architecture.md`](reference/architecture.md) | The system at a glance: layers, boundaries, how the parts fit |
| [`reference/core-model.md`](reference/core-model.md) | Lifecycle, gates, task states, artifacts, permissions |
| [`reference/domains.md`](reference/domains.md) | Domain packs and how a project picks its domains |
| [`reference/extension-model.md`](reference/extension-model.md) | How to extend SE without touching the core |
| [`reference/schemas.md`](reference/schemas.md) | The JSON Schemas and how validation works |

## Install and operate

| Document | What it explains |
|---|---|
| [`reference/installation.md`](reference/installation.md) | Obtain SE, install, run the console, register MCPs, update |
| [`reference/lifecycle.md`](reference/lifecycle.md) | `se install` / `sync` / `update` / `uninstall` and their safety rules |
| [`reference/project-bootstrap.md`](reference/project-bootstrap.md) | Creating and bootstrapping managed projects |
| [`reference/project-profile.md`](reference/project-profile.md) | Project manifest and profile fields |
| [`reference/versioning.md`](reference/versioning.md) | Version and release conventions |
| [`reference/se-installer.md`](reference/se-installer.md) | The unified installer workspace (`SE-INSTALLER/`) |

## Work with a runtime

| Document | What it explains |
|---|---|
| [`reference/commands.md`](reference/commands.md) | The command surface (`init`, `plan`, `gate`, `orchestrate`, ...) |
| [`reference/workflows.md`](reference/workflows.md) | Multi-agent workflows: DAGs, gates, context passing |
| [`reference/opencode-adapter.md`](reference/opencode-adapter.md) | How the OpenCode agent layer is generated |
| [`reference/development-workflow.md`](reference/development-workflow.md) | Day-to-day development flow inside SE |
| [`reference/execute-integrity.md`](reference/execute-integrity.md) | Execution, integrity and evidence rules |

## Decisions

Architecture decisions are recorded as ADRs under [`adr/`](adr/).

## Working records

Working records — checkpoints, audits, reviews, evidence and validation reports —
are kept locally under `DOCS/internal/` for provenance. That directory is not
published: it is gitignored and excluded from every check, so the public tree
contains only the reference documentation above.
