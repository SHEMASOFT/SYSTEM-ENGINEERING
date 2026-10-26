# SYSTEM ENGINEERING

[![CI](https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/actions/workflows/ci.yml)

A reusable, domain-agnostic **project operating system for AI-assisted work**.

SYSTEM ENGINEERING (SE) gives an AI coding runtime structure instead of improvisation:
a lifecycle, gates, roles, commands and skills that turn ad-hoc prompting into a
traceable, repeatable process — for software, data, cloud, security, media, design
or any other kind of project.

This repository **is the system itself**. It creates and operates other projects
without being coupled to them.

Developed and maintained by [Moises](https://github.com/SHEMASOFT) —
[`SHEMASOFT/SYSTEM-ENGINEERING`](https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/).

> Version 0.11.0 — Status: **foundation / development**. Smallest system capable of
> becoming the larger one; not yet validated in production.

**New here?** Jump to [Requirements](#requirements), the
[5-minute quickstart](#quickstart) and
[how to check that it works](#check-that-it-works). Everything else can wait.

---

## Contents

- [What it is, and what it is not](#what-it-is-and-what-it-is-not)
- [Why SE](#why-se)
- [How the pieces fit together](#how-the-pieces-fit-together)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Check that it works](#check-that-it-works)
- [One-command install (optional)](#one-command-install-optional)
- [Configure your runtime (optional)](#configure-your-runtime-optional)
- [Your first project](#your-first-project)
- [SE Console (optional)](#se-console-optional)
- [Troubleshooting](#troubleshooting)
- [Persistent memory](#persistent-memory)
- [Projects](#projects)
- [Work modes](#work-modes)
- [Create and drive a project](#create-and-drive-a-project)
- [Repository map](#repository-map)
- [Runtimes](#runtimes)
- [Design principles](#design-principles)
- [Documentation](#documentation)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Author and maintainer](#author-and-maintainer)
- [License](#license)

---

## What it is, and what it is not

**What it does.** SE gives an AI coding runtime a process it can execute: a
lifecycle with gates, roles that do one job each, commands and skills loaded on
demand, and a memory that survives sessions. Work produces artifacts, evidence and
receipts instead of claims.

**What it does not do.**

- It is **not a model, an API or a hosted service**. SE ships no credentials and
  calls no provider by itself; it generates the agent layer for a runtime you
  already use.
- It does **not install third-party tools for you** — with one explicit exception:
  the one-command bootstrap (`SE-INSTALLER/bootstrap.ps1`, `SE-INSTALLER/install.sh`
  or `se install --bootstrap`) delegates to the unified installer, which is what
  installs a missing Python, Node.js or OpenCode. A plain `se install` registers
  only servers whose dependencies are already present (Node, `npx`, Python) and
  reports the rest as skipped.
- It does **not touch anything you did not ask it to touch**. Commands write inside
  the repository or the project directory you name; the console's views are
  read-only, and its only writes come from three explicit, token-authenticated
  actions that you trigger yourself.
- It is **not production-validated yet**. Version 0.10.1 is
  *foundation / development*: usable and tested, but young.

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

## How the pieces fit together

Four things you will meet in this repository, and what each one is responsible for:

| Piece | What it is | Where it lives |
|---|---|---|
| **SYSTEM ENGINEERING** | The system itself: contracts, lifecycle, gates, CLI, adapters. This repository. | the clone |
| **Managed projects** | The work SE governs: each project keeps its own repository, history and artifacts. SE is never coupled to them. | `PROJECTS/` by default (excluded from version control), or any directory you pass with `--dir` |
| **SE Console** | A local web console that shows what SE is, what state it is in and what needs attention. Its views are read-only; three explicit, token-authenticated actions delegate to `se`. | `SE-CONSOLE/`, on `http://127.0.0.1:8777` |
| **Runtime adapters** | The generated agent layer (agents, commands, skills) for a runtime such as OpenCode, Claude Code or Codex. Generated, never hand-edited. | `.opencode/`, `.claude/`, `.codex/` |

MCP servers (Context7, filesystem, SE's own skill/memory servers) are **optional
integrations**. None of them is required by SE.

---

## Requirements

| Dependency | Needed for |
|---|---|
| Python 3.10+ | The reference CLI (`SCRIPTS/se.py`) |
| `jsonschema` (`pip install jsonschema`) | Schema validation; `se doctor` fails without it |
| git | Version control checks and project isolation |
| [OpenCode](https://opencode.ai) *(optional)* | Running the generated agent layer |
| Node.js *(optional)* | MCP servers that use `npx` |

### Supported environments

| Environment | How it is handled | Evidence |
|---|---|---|
| **Windows 10/11** (PowerShell) | `SE-INSTALLER/bootstrap.ps1` installs Python 3.12, and — through the `se-installer` package it forwards to — Node.js LTS and OpenCode when they are missing | CI runs the full suite on `windows-latest` plus a bootstrap dry-run smoke test |
| **Linux** | `SE-INSTALLER/install.sh` (POSIX, no privileges needed); install `python3` and `python3-venv` first | CI runs the full suite on `ubuntu-latest` |
| **WSL** | Portable by design: no absolute host paths on the operational surfaces (`opencode.jsonc`, `SCRIPTS/`, the generated adapters); `se install --env-target wsl` translates Windows paths to `/mnt/<drive>` | documented in [`installation.md`](DOCS/reference/installation.md); not covered by CI |
| **macOS** | `SE-INSTALLER/install.sh`; the installer uses Homebrew when available | documented in [`SE-INSTALLER/README.md`](SE-INSTALLER/README.md); not covered by CI |

> On Windows, `bootstrap.ps1` installs Python 3.12, Node.js LTS and OpenCode when
> they are missing. It uses winget, Chocolatey or Scoop when available; otherwise
> Python comes from the official signed python.org installer and Node from the
> official nodejs.org LTS ZIP (SHA256 verified). On Linux/macOS, install `python3`
> (and `python3-venv` on Debian/Ubuntu) first.

---

## Quickstart

**Minimal** — clone it and run the reference CLI. This is everything you need to
see SE work; it takes a couple of minutes.

```bash
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
cd SYSTEM-ENGINEERING

pip install jsonschema

python SCRIPTS/se.py doctor      # health check — must report PASS
python SCRIPTS/se.py validate    # schemas, agents, domains — must report PASS
```

On Windows use `python SCRIPTS\se.py ...` (not `python3`). On Linux/macOS use
`python3 SCRIPTS/se.py ...` (and `pip3`) if your system has no `python` alias.

That is the whole minimal path: no installer, no Node, no runtime, no MCP server.
The installer below only adds convenience (isolated venv, MCP registration,
optional desktop shortcut).

---

## Check that it works

Run the two commands from the repository root and read the summary line:

```bash
python SCRIPTS/se.py doctor
python SCRIPTS/se.py validate
```

What a healthy checkout prints as the last line of each command (the exact counts
depend on your machine — `FAIL=0` is the part that matters):

```text
Doctor summary: PASS=19 WARN=2 FAIL=0
VALIDATE: PASS (schemas, agents, domains)
```

- **What matters is `FAIL=0`.** `WARN` entries are informational. For example,
  `[WARN] git_available` simply means no `git` was found on `PATH`, and
  `[WARN] self_containment` on this repository points at guidance text in the
  reference docs, not at an operational surface.
- `se doctor` checks the layout, the contracts, the generated adapter, the
  dependencies, git and secrets. `se validate` checks the schemas, the 12 agents
  and the domain definitions.
- Both exit non-zero on `FAIL`, so they are safe to wire into CI.

---

## One-command install (optional)

**Recommended on a fresh machine** — installs SE Core + the web console
+ the selected MCP servers + runtime adapters into an isolated venv, and registers
the SE MCP servers in `opencode.jsonc`:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File SE-INSTALLER\bootstrap.ps1 install --recommended
```

```bash
# Linux / macOS
bash SE-INSTALLER/install.sh install --recommended
```

If the bootstrap installed Node or OpenCode during this run and the command is not
found afterwards, open a new terminal so the updated `PATH` is loaded. Then
authenticate OpenCode once, before starting a session:

```bash
opencode auth login
```

Add `--dry-run` to plan without installing. For the interactive selector:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File SE-INSTALLER\bootstrap.ps1 tui
```

```bash
# Linux / macOS
bash SE-INSTALLER/install.sh tui
```

In the TUI, `Space` selects, `A` selects the recommended set, `Enter` installs,
`D` toggles dry-run, `R` refreshes and `Q` quits. After a successful install, the
TUI registers the selected MCPs that have a template, just like the one-command
`install`. Pass `--skip-mcp-registration` to opt out.

### Web Installer (nuevo)

Interfaz visual en el navegador para instalar/desinstalar componentes SE:

```powershell
# Windows
.\SE-INSTALLER\install-web.ps1          # Auto port, abre navegador

# Linux / macOS
bash SE-INSTALLER/install-web.sh
```

O directo (requiere `pip install -e SE-INSTALLER`):
```bash
se-installer-web --port 8765 --reload
# o
python -m uvicorn se_installer_web.main:app --port 8765 --reload
```

Abre **http://127.0.0.1:8765** → 4 pestañas: Instalar, Desinstalar, Adaptador, Log (WebSocket tiempo real).

Ver [`DOCS/reference/installation.md#9-instalador-web-interactivo-nuevo`](DOCS/reference/installation.md#9-instalador-web-interactivo-nuevo) para detalles.

See [`DOCS/reference/installation.md`](DOCS/reference/installation.md) for the full path.

> **Where the venv goes.** The installer keeps its own venv at `SE-INSTALLER/.venv`,
> which `se doctor` audits cleanly. If you create your own venv, either keep it
> **outside** the repository or name it `.venv` at the root — a differently-named venv
> *inside* the repo makes `se doctor` report `FAIL` on `secrets` (the bundled
> `certifi/cacert.pem`) and a `WARN` on `root_hygiene` (unregistered directory).

---

## Configure your runtime (optional)

SE works from the CLI alone. To drive it from an agent runtime, install the adapter
and point the runtime at it.

The generated agent layer (`.opencode/`) is versioned in this repository, and the
one-command install above already registers the SE MCP servers. To regenerate the
agent layer after changing contracts, use the installer venv (it contains
`jsonschema`):

```powershell
# Windows
SE-INSTALLER\.venv\Scripts\python.exe SCRIPTS\se.py adapter opencode
```

```bash
# Linux / macOS
SE-INSTALLER/.venv/bin/python SCRIPTS/se.py adapter opencode
```

`se adapter opencode` writes `.opencode/` with **12 agents, 24 commands and 7
skills**, all generated — never edit them by hand, regenerate instead.

If you installed with `tui`, a custom `-c/--components` selection, or
`--skip-mcp-registration`, register the MCP servers once:

```powershell
# Windows
SE-INSTALLER\.venv\Scripts\python.exe SCRIPTS\se.py install
```

```bash
# Linux / macOS
SE-INSTALLER/.venv/bin/python SCRIPTS/se.py install
```

`se install` registers the SE MCP servers through the portable Node launcher
`SCRIPTS/se_core/mcp/launch.mjs`, which resolves `python3` or `python` at startup,
and rewrites only the MCP entries in `opencode.jsonc`. Set `SE_PYTHON` to pin a
specific interpreter.

- **`shema-ai-coordinador`** is the primary agent: it orchestrates the lifecycle and routes work
  to the other roles (`planner`, `implementer`, `tester`, `reviewer`, ...), each of
  which runs as a subagent.
- Commands (for example `/plan`, `/implement`, `/review`) are reusable prompt templates.
- Skills (for example `impl-tdd`, `rev-adversarial`) are loaded only when relevant.

To make new sessions start as the coordinator, set its generated agent ID in
`opencode.jsonc` (the master repository already does this):

```jsonc
{
  "default_agent": "shema-ai-coordinador",
}
```

MCP servers are optional; none is required by SE. See
[`DOCS/reference/installation.md`](DOCS/reference/installation.md) for registration
and lifecycle commands (`se install`, `se sync`, `se update`, `se uninstall`).

---

## Your first project

A **project** is the thing SE governs. Create one, pass its first gate, move it
forward and look at its status — all four commands work on a fresh clone:

```bash
# 1. Create a managed project (its artifacts live under PROJECTS/)
python SCRIPTS/se.py init --dir PROJECTS/MyApp --name "MyApp" --owner "me" --domains software

# 2. Evaluate the intake gate
python SCRIPTS/se.py gate --project PROJECTS/MyApp --gate G0

# 3. Move the project through that gate
python SCRIPTS/se.py transition --project PROJECTS/MyApp --to DISCOVERY --by "me"

# 4. See where it stands
python SCRIPTS/se.py status --project PROJECTS/MyApp
```

What each step prints:

```text
TARGET: <your-dir>\PROJECTS\MyApp
PASS: initialized project PRJ-MYAPP at <your-dir>\PROJECTS\MyApp
PASS: created .gitignore
PASS: created discovery.json
PASS: init complete (existing files were not overwritten)

Gate G0 - PROJECT INTAKE (DRAFT -> DISCOVERY)
  [PASS  ] G0.1: PROJECT.json is valid
  [PASS  ] G0.2: owner=me
  [PASS  ] G0.3: domains=['software']
  [PASS  ] G0.4: criticality=unknown
Gate result: PASS

PASS: lifecycle DRAFT -> DISCOVERY
```

(The paths are printed in full; they are shortened to `<your-dir>` here.)

**`se status` reports `Overall: FAIL` on a brand-new project, and that is
correct**: most of the later gates (G1, G2, G3, G5, …) have nothing to check yet
because there are no requirements, tasks or evidence. The command exits `1` while
any gate fails; that exit code is the verdict, not a crash.

### Lifecycle states

`se transition` accepts only the states in
[`CORE/lifecycle/lifecycle.json`](CORE/lifecycle/lifecycle.json)
(a state name such as `requirements` is **not** valid — use `PLANNING`):

| State | Meaning | Gate in |
|---|---|---|
| `DRAFT` | Project registered but not yet explored | — (start) |
| `DISCOVERY` | Context, constraints and unknowns are being identified | G0 |
| `PLANNING` | Requirements and plan are being defined | G1 |
| `ACTIVE` | Implementation work is in progress | G2, G3 |
| `VERIFICATION` | Implementation is being verified against requirements | G4 |
| `ACCEPTANCE` | Owner reviews and formally accepts the result | G5 |
| `RELEASED` | A release has been produced | G6, G7 |
| `OPERATING` | The released system is in operation | G8 |
| `ARCHIVED` | Project is closed and preserved | — (terminal) |

`BLOCKED` is a condition, not a state: it is recorded with a reason and a
resolution path. Some gate conditions are `[MANUAL]` — they require a human
attestation with a written reason (`se transition --attest "<reason>"`), and SE
never auto-approves them.

`PROJECTS/` is intentionally excluded from version control: each project keeps its
own repository and history.

---

## SE Console (optional)

A local web console over the system — what SE is, what state it is in, what needs
attention. The information views are read-only and the server answers GET only, except
`POST /api/action`: a token-authenticated surface (token at
`~/.config/se-console/token`, outside the repository) limited to three catalog
actions that delegate to `se` — `run checkpoint`, `run close` and
`transition --attest`. The console owns no SE state; its own writes are the audit
line in the gitignored `SE-CONSOLE/artifacts/actions.jsonl` and the PID/log the
helper keeps under `SE-CONSOLE/.runtime/`.

```bash
cd SE-CONSOLE
python scripts/dev_console.py start   # http://127.0.0.1:8777, in the background
python scripts/dev_console.py status
python scripts/dev_console.py stop    # clean shutdown
```

`start` also arms a 15-minute idle timeout — close the browser and the console
shuts itself down (`--idle-timeout 0` keeps it up until you stop it). If the
installer created the desktop shortcut (`se-installer install --shortcuts`), that
is the one-click way in. `python -m console.server` runs the same console directly,
in the foreground and with no timeout. Details:
[`SE-CONSOLE/docs/README.md`](SE-CONSOLE/docs/README.md).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `se doctor` reports `FAIL` on `jsonschema` | The optional validation dependency is missing | `pip install jsonschema` (or use the installer venv, which has it) |
| `se doctor` reports `FAIL` on `secrets` (plus a `WARN` on `root_hygiene`) | A virtualenv was created inside the repository with a name other than `.venv` | Keep your venv outside the repo, or name it `.venv` at the root |
| `[WARN] git_available: git executable not found on PATH` | `git` is not on `PATH` for this shell | Install git, or open a new terminal after installing it. It is a `WARN`, so the check still passes |
| `[WARN] self_containment ... none on operational surfaces` | Guidance text inside the reference docs mentions host paths | Informational on this repository; it does not block. A hit **on an operational surface** (`opencode.jsonc`, `SCRIPTS/`) is what must be fixed |
| `se status --project <dir>` says `Overall: FAIL` right after `se init` | Most later gates have no requirements, tasks or evidence to check yet (some, like G4, pass vacuously) | Expected. Pass the gates in order (G0 → G8) as the project produces its artifacts |
| `FAIL: target state '...' is not a valid state` | The lifecycle states are `DRAFT`, `DISCOVERY`, `PLANNING`, `ACTIVE`, `VERIFICATION`, `ACCEPTANCE`, `RELEASED`, `OPERATING`, `ARCHIVED` | Use one of those names, e.g. `--to DISCOVERY` |
| A gate shows `[MANUAL]` and the transition stops | That condition requires human attestation by design, and `--attest` requires a written reason | Attest it explicitly: `se transition --project <dir> --to <STATE> --by <you> --attest "<reason>"` |
| `opencode` (or `node`) “not found” right after the bootstrap | The installer updated `PATH` for its own process only | Open a new terminal |
| `se doctor` fails after you edited `.opencode/` | `.opencode/` is generated; a manual edit shows as manifest drift | Edit `AGENTS/`, `COMMANDS/`, `SKILLS/` or `TEMPLATES/` and regenerate with `se adapter opencode` |

Still stuck? See [`SUPPORT.md`](.github/SUPPORT.md).

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

# 2. Move it through its lifecycle (DRAFT -> DISCOVERY -> PLANNING -> ...)
python SCRIPTS/se.py gate       --project PROJECTS/MyApp --gate G0
python SCRIPTS/se.py transition --project PROJECTS/MyApp --to DISCOVERY --by "me"
python SCRIPTS/se.py review     --project PROJECTS/MyApp
python SCRIPTS/se.py release    --project PROJECTS/MyApp --version 0.1.0 --approve --by "me"

# 3. Run multi-agent workflows (DAG + gates)
python SCRIPTS/se.py orchestrate create --project PROJECTS/MyApp \
  --name "Feature Development" --nodes nodes.json --edges edges.json --gates gates.json
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp --workflow WF-0001 --dry-run
```

Every transition is gated (see [Lifecycle states](#lifecycle-states)) and
fail-closed: a blocked transition reports which gate condition failed, manual
conditions need a written human attestation (`--attest "<reason>"`), and
`se release` never records an empty approver: `approved_by` falls back to the
project owner, and the release schema rejects an empty value. The command surface
is documented in [`DOCS/reference/commands.md`](DOCS/reference/commands.md).

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
| `INTEGRATIONS/` | Runtime adapters (OpenCode, Claude Code, Codex) and the provider-neutral CI governance adapter |
| `SE-CONSOLE/` | Local-first web console: read-only views, authenticated actions |
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

- **Bugs, questions and feature requests** — open an issue:
  <https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/issues>
- **Help and where to ask** — [`SUPPORT.md`](.github/SUPPORT.md)
- **Security** — [`SECURITY.md`](.github/SECURITY.md). Do not disclose a
  vulnerability in a public issue.
- **Community standards** — [`CODE_OF_CONDUCT.md`](.github/CODE_OF_CONDUCT.md)

---

## Author and maintainer

**Developed and maintained by Moises**<br>
**Project:** SHEMASOFT/SYSTEM-ENGINEERING<br>
**Repository:** https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/

Moises develops and maintains SYSTEM ENGINEERING and is the owner of the
[`SHEMASOFT`](https://github.com/SHEMASOFT) GitHub account. Contributions from
other developers are recorded in the repository's
[commit history](https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/commits/main)
and are not attributed to the maintainer.

---

## License

MIT — see [`LICENSE`](LICENSE).

The MIT License allows you to use, copy, modify, merge, publish, distribute,
sublicense and sell copies of the system, provided the copyright notice and the
permission notice are included in all copies or substantial portions of it. In
practice: keep [`LICENSE`](LICENSE) with any copy or derivative you distribute.

Some skills adapt third-party material that carries its own license; the
attribution lives with the skill itself (for example
[`SKILLS/visual-frontend-engineering/SKILL.md`](SKILLS/visual-frontend-engineering/SKILL.md)).
The MIT license of this repository does not override those terms.
