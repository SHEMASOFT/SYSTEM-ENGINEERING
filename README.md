# SYSTEM ENGINEERING

A reusable, domain-agnostic **project operating system for AI-assisted work**.

SYSTEM ENGINEERING (SE) gives an AI coding runtime structure instead of improvisation:
a lifecycle, gates, roles, commands and skills that turn ad-hoc prompting into a
traceable, repeatable process — for software, data, cloud, security, media, design
or any other kind of project.

This repository **is the system itself**. It creates and operates other projects
without being coupled to them.

> Version 0.10.0 — Status: **foundation / development**. Smallest system capable of
> becoming the larger one; not yet validated in production.

---

## Why SE

| Problem | What SE does |
|---|---|
| Long sessions burn tokens re-explaining context | A **coordinator** orchestrates and delegates to specialized **subagents**; each runs in its own fresh context and returns only its result |
| The model forgets decisions between sessions | **Built-in memory** persists decisions, fixes and discoveries across sessions |
| Everything runs in one giant prompt | Roles, **commands** and **skills** are loaded on demand, not all at once |
| "It works on my machine" process | A **lifecycle with gates** makes every transition explicit, gated and recorded |
| Output nobody can audit | Evidence-based workflow: plans, artifacts and reports instead of claims |

In short: SE makes AI work **cheaper (tokens), clearer and auditable**.

---

## Requirements

| Dependency | Needed for |
|---|---|
| Python 3.10+ | The reference CLI (`SCRIPTS/se.py`) |
| `jsonschema` (`pip install jsonschema`) | Schema validation; `se doctor` fails without it |
| git | Version control checks and project isolation |
| [OpenCode](https://opencode.ai) *(optional)* | Running the generated agent layer |
| Node.js *(optional)* | MCP servers that use `npx` |

---

## Quickstart

**Minimal** — clone it and run the reference CLI:

```bash
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
cd SYSTEM-ENGINEERING

pip install jsonschema

python SCRIPTS/se.py doctor      # health check — must report PASS
python SCRIPTS/se.py validate    # schemas, agents, domains — must report PASS
```

On Windows use `python SCRIPTS\se.py ...` (not `python3`).

**One command (recommended on a fresh machine)** — installs SE Core + the web console
+ the selected MCP servers + runtime adapters into an isolated venv, and generates a
portable runtime config:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File SE-INSTALLER\bootstrap.ps1 install --recommended
```

```bash
# Linux / macOS
bash SE-INSTALLER/install.sh install --recommended
```

Add `--dry-run` to plan without installing, or pass `tui` for the interactive
selector. See [`DOCS/reference/installation.md`](DOCS/reference/installation.md)
for the full path.

> **Where the venv goes.** The installer keeps its own venv at `SE-INSTALLER/.venv`,
> which `se doctor` audits cleanly. If you create your own venv, either keep it
> **outside** the repository or name it `.venv` at the root — a differently-named venv
> *inside* the repo makes `se doctor` report `FAIL` (`secrets`, `root_hygiene`).

Optional: start the read-only web console over the system:

```bash
cd SE-CONSOLE
python scripts/dev_console.py start   # http://127.0.0.1:8777, in the background
python scripts/dev_console.py status
python scripts/dev_console.py stop    # clean shutdown
```

`start` also arms a 15-minute idle timeout — close the browser and the console
shuts itself down (`--idle-timeout 0` keeps it up until you stop it). If the
installer created the desktop shortcut (`install --shortcuts`), that is the
one-click way in. `python -m console.server` runs the same console directly, in
the foreground and with no timeout. Details:
[`SE-CONSOLE/docs/README.md`](SE-CONSOLE/docs/README.md).

---

## Use it with OpenCode

Generate the agent layer from the canonical contracts:

```bash
python SCRIPTS/se.py adapter opencode
```

This writes `.opencode/` with **12 agents, 24 commands and 7 skills**, all generated —
never edit them by hand, regenerate instead.

- **`coordinator`** is the primary agent: it orchestrates the lifecycle and routes work
  to the other roles (`planner`, `implementer`, `tester`, `reviewer`, ...), each of
  which runs as a subagent.
- Commands (for example `/plan`, `/implement`, `/review`) are reusable prompt templates.
- Skills (for example `impl-tdd`, `rev-adversarial`) are loaded only when relevant.

To make new sessions start as the coordinator, add to `opencode.jsonc`:

```jsonc
{
  "default_agent": "coordinator",
}
```

MCP servers are optional; none is required by SE. See
[`DOCS/reference/installation.md`](DOCS/reference/installation.md) for registration
and lifecycle commands (`se install`, `se sync`, `se update`, `se uninstall`).

---

## Persistent memory

SE works without memory, but it is built to use one.
**Memory is built in**: one JSON record per memory inside the project, a
derived search index under `.se/`, and an optional local reranker. There is
nothing to install and nothing is downloaded.

- **No external server.** Records live in the project
  (`memories/MEM-XXXX.json`) and are read and written through `se memory`.
  The index under `.se/` is a rebuildable cache, never a dependency: delete
  it and search keeps working.
- **A convention, not a black box.** At the start of a session the agent
  states what it is about and `se intelligence --memory <topic>` injects the
  matching records; it saves each decision, bug fix, discovery and convention
  as it happens (`se memory add`) and closes every session with a summary
  (`--type session`) — memory is bookkeeping, never the user-facing answer.
- **Advisory, never a gate.** No gate passes or fails because of memory. The
  auditable record stays in the project artifacts, evidence and receipts;
  memory only makes the *next* session cheaper.

Storage model, commands, the optional semantic reranker and the
session-start convention:
[`DOCS/reference/memory.md`](DOCS/reference/memory.md).

---

## Projects

Bootstrap a managed project from scratch:

```bash
python SCRIPTS/se.py init --dir PROJECTS/MyApp --name "MyApp" --owner "me" --domains software
```

`se init` also takes `--agents`, `--skills` and `--criticality`
(`low|medium|high|critical|unknown`; it defaults to `unknown`, never a silent
guess). A project can declare an **optional profile** in `PROJECT.json`
([reference](DOCS/reference/project-profile.md)):

```jsonc
"profiles": {
  "work": { "type": "greenfield|brownfield", "scale": "small|medium|large",
            "risk": "low|medium|high", "cadence": "..." }
}
```

The declared profile is **enforced**: `se validate --project` refuses a project whose
scale/risk/criticality demand an approved SDD or a passing review receipt and it does
not have them (see [Work modes](#work-modes)).

To bring an **existing / advanced project** under the SE lifecycle — one that already
has its own `.opencode/`, `AGENTS.md`, `opencode.json` or `SDD/` and that `se init`
refuses by design — use `se adopt`:

```bash
python SCRIPTS/se.py adopt PROJECTS/LegacyApp --owner "me" \
  --scale large --risk high --criticality high
```

Adoption is **additive**: it writes `PROJECT.json` (recording `metadata.adoption` and a
`profiles.work` starting at `brownfield`) and the empty workspace directories, and
leaves every file the project already had byte-for-byte untouched. Installing a runtime
adapter stays a separate, explicit step (`se adapter ...`). Use `--dry-run` to plan
without writing.

## Work modes

The agent picks the mode **from the project**, not from habit:

| Mode | What it is |
|---|---|
| **organic** | Daily flow: explore → clarify → execute the authorized change → proportional checks. |
| **spec** | Formal flow for contract changes and large/high-risk work: objective, requirements, design (`se new sdd`), tasks, gates. |
| **receipt** | Evidence-review layer: binds a verdict to the exact change candidate (`se new rdd` = candidate + evidence + verdict). |

See [`DOCS/reference/work-modes.md`](DOCS/reference/work-modes.md) for the
selection rule (profile → mode). The rule is **executable, not advice**: the floor
lives in [`CORE/policies/ceremony.json`](CORE/policies/ceremony.json),
`se ceremony --project <dir>` shows the effective requirements, and
`se validate --project` enforces them. It ships as the canonical skill
`work-mode-selection` (SK-0007), so the runtime agent loads it on demand.

### Design records

The modes are backed by concrete records, created with `se new` and validated against
[`SCHEMAS/`](SCHEMAS/):

| Record | Name | What it captures | Created with |
|---|---|---|---|
| **SDD** | Software Design Document (*spec*-driven development) | The agreed design: architecture, interfaces, data models, and the requirements it covers | `se new sdd --project <dir>` → `sdds/SDD-####` |
| **ODD** | Open Design Document | A design still *open*: problem, alternatives with trade-offs, evaluation and the proposed design — kept collaborative and iterative while the decision is unsettled | `se new odd --project <dir>` → `odds/ODD-####` |
| **RDD** | Review receipt (*receipt*-driven development) | A verdict bound to the **exact change candidate** it reviewed, with the evidence that supports it — so a review can never drift from the version it reviewed | `se new rdd --project <dir>` → `rdds/RDD-####` |

Open work as an **ODD** while alternatives are still on the table, then close the agreed
design into an **SDD**. `spec` work needs an approved **SDD**; `receipt` work needs a
passing **RDD** — both are enforced by `CORE/policies/ceremony.json` once a project
declares `profiles.work` (`large`/`high-risk` → SDD; `medium` → at least an RDD). Point
decisions — including architectural ones — are recorded separately with
`se new decision`.

## Create and drive a project

```bash
# 1. Bootstrap a managed project
python SCRIPTS/se.py init --dir PROJECTS/MyApp --name "MyApp" --owner "me" --domains software

# 2. Move it through its lifecycle (intake -> release)
python SCRIPTS/se.py transition --project PROJECTS/MyApp --to requirements
python SCRIPTS/se.py gate       --project PROJECTS/MyApp --evaluate G1
python SCRIPTS/se.py review     --project PROJECTS/MyApp
python SCRIPTS/se.py release    --project PROJECTS/MyApp

# 3. Run multi-agent workflows (DAG + gates)
python SCRIPTS/se.py orchestrate create --project PROJECTS/MyApp \
  --name "Feature Development" --nodes nodes.json --edges edges.json --gates gates.json
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp --workflow WF-0001 --dry-run
```

`PROJECTS/` is intentionally excluded from version control: each project keeps its
own repository and history.

---

## Repository map

| Path | Purpose |
|---|---|
| `CORE/` | Lifecycle, gates, task states, artifact and permission models |
| `DOMAINS/` | Domain-pack contract and initial domain definitions |
| `AGENTS/` | Agent contract and the 12 agent definitions |
| `COMMANDS/` | Command contracts (rendered into runtime commands) |
| `SKILLS/` | LLM-first skills (Agent Skills format) |
| `SCHEMAS/` | Machine-readable JSON Schemas for core artifacts |
| `TEMPLATES/` | Fill-in templates for artifacts, projects and MCP servers |
| `SCRIPTS/` | Reference Python CLI (`se.py`, `se_core/`) |
| `POLICIES/` | Human-readable policies (permissions, evidence, release, security) |
| `INTEGRATIONS/` | Runtime adapters (OpenCode, Claude Code, Codex) |
| `SE-CONSOLE/` | Local-first, read-only web console |
| `SE-INSTALLER/` | Unified installer + TUI for SE + MCP servers + runtimes |
| `DOCS/` | Architecture, references and working records |
| `TESTS/` | Hermetic tests for the Master System itself |

---

## Runtimes

Adapters render the same contracts for different runtimes:

```bash
python SCRIPTS/se.py adapter opencode      # .opencode/ (audited by se doctor)
python SCRIPTS/se.py adapter claude-code   # .claude/ + .mcp.json + CLAUDE.md
python SCRIPTS/se.py adapter codex         # .codex/ + AGENTS.md (config fragment)
python SCRIPTS/se.py adapter all           # every runtime at one output root
```

Every adapter is deterministic, idempotent and **portable** (no absolute host
paths). Runtime specifics stay in `INTEGRATIONS/`; see
[`DOCS/reference/adapters.md`](DOCS/reference/adapters.md).

---

## Design principles

SIMPLE · MODULAR · TRACEABLE · VERIFIABLE · EXTENSIBLE · DOMAIN-AGNOSTIC ·
HUMAN-CONTROLLED · AUTOMATION-FRIENDLY · TOOL-INDEPENDENT.

---

## Documentation

Start at [`DOCS/reference/architecture.md`](DOCS/reference/architecture.md).
See [`DOCS/README.md`](DOCS/README.md) for the full index.

Key references:

- [`installation.md`](DOCS/reference/installation.md) — obtain, install, run, update
- [`core-model.md`](DOCS/reference/core-model.md) — lifecycle, gates, tasks, artifacts
- [`work-modes.md`](DOCS/reference/work-modes.md) — organic / spec / receipt, and the SDD/ODD/RDD records
- [`commands.md`](DOCS/reference/commands.md) — the command surface
- [`workflows.md`](DOCS/reference/workflows.md) — multi-agent DAG execution
- [`lifecycle.md`](DOCS/reference/lifecycle.md) — install/sync/update/uninstall lifecycle
- [`opencode-adapter.md`](DOCS/reference/opencode-adapter.md) — how the agent layer is generated

---

## Roadmap

Shipped:

- **Adopt existing / advanced projects** → `se adopt` (additive; never overwrites
  project artifacts).
- **Per-size flows** → `profiles.work.scale` (with risk and criticality) drives
  `se validate --project` through `CORE/policies/ceremony.json`.
- **Work-mode skill** → `SKILLS/work-mode-selection` (SK-0007) plus `se ceremony`.
- **Receipts by default** → the ceremony floor requires a passing RDD for
  medium/large (and high-risk / critical) work.
- **Coordinator capability** → the coordinator contract (AG-0003) declares
  `work_mode_selection` as a capability and responsibility, so every deployed
  runtime coordinator advertises the rule.
- **Installer UX** → one-command bootstrap (`SE-INSTALLER/bootstrap.ps1` and
  `SE-INSTALLER/install.sh`) over the unified `se-installer` package for
  SE + MCP servers + runtimes, with a CI-enforced installer test suite and a
  registry-parity contract against `CORE/capabilities/capabilities.json`.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). CI runs `se doctor`, `se validate` and
the full test suite on Linux and Windows for every pull request.

---

## License

MIT — see [`LICENSE`](LICENSE).
