# Installation — SYSTEM ENGINEERING

SYSTEM ENGINEERING (SE) is **portable and self-contained**. It does not require
`gentle-ai`, a specific runtime, a specific harness, or a specific model. This guide
describes how to obtain SE on a clean machine and get it running, and how to add
optional capabilities.

The reference implementation is a Python CLI: `python3 SCRIPTS/se.py <command>`.
On Windows the interpreter is `python`, so throughout this guide read `python3` as
`python` and use backslash paths (`python SCRIPTS\se.py <command>`).

---

## 1. Runtime base

| Dependency | Required | Purpose |
|---|---|---|
| `python3` | **yes** | Runs the reference CLI (`SCRIPTS/se.py`) |
| `jsonschema` | **yes** | Schema validation; `se doctor` reports FAIL without it |
| `PyYAML` | optional | Skill frontmatter parsing (falls back to a line parser if absent) |
| `requests` | optional | `local` LLM provider (Ollama / vLLM / OpenAI-compatible) |
| `openai`, `anthropic` | optional | `openai` / `anthropic` LLM providers |

Validate the runtime at any time:

```bash
python3 SCRIPTS/se.py doctor
```

---

## 2. Obtain SE

```bash
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git SYSTEM-ENGINEERING
cd SYSTEM-ENGINEERING
```

`PROJECTS/` is intentionally excluded from version control: each project keeps its
own history (often its own repository). The clone carries the **system**, not the
projects. The vendored **SE-CONSOLE** web console is included at `SE-CONSOLE/`.

---

## 3. Bootstrap

There are two paths, depending on how much you want installed.

**Minimal (no installer).** Bootstrap is composed from the validated commands:

```bash
python3 SCRIPTS/se.py doctor      # structure, contracts, dependencies, git
```

**Unified installer (recommended).** The `se-installer` package installs SE Core +
Console + the selected MCP servers + runtime adapters in one step, into an isolated
virtual environment. The one-command entry points create that venv and forward every
argument to the CLI:

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File SE-INSTALLER\bootstrap.ps1 install --recommended
# Linux / macOS
bash SE-INSTALLER/install.sh install --recommended
```

Add `--dry-run` to plan without installing, or pass `tui` for the interactive
selector. From an already-cloned checkout you can also chain it through the CLI with
`se install --bootstrap` (see §7).

> **Where to put a virtualenv.** The one-command entry points keep their venv at
> `SE-INSTALLER/.venv`, which `se doctor` audits cleanly. If you create your own venv,
> keep it **outside** the repository or name it `.venv` at the repository root. Any
> other venv directory *inside* the repo is an unregistered root directory, and one
> whose name is not `.venv` also trips the `secrets` scan (the bundled
> `certifi/cacert.pem`), so `se doctor` reports `FAIL`.

---

## 4. Validate

```bash
python3 SCRIPTS/se.py doctor      # canonical health checks
python3 SCRIPTS/se.py validate    # schemas, agents, domains
```

Both must pass before working with projects.

---

## 5. Adapt agents to a runtime

SE generates the agent layer from its own contracts:

```bash
python3 SCRIPTS/se.py adapter opencode
```

This deploys `agents/`, `commands/`, `skills/` and `mcp/` under `.opencode/`
(generated from `AGENTS/`, `COMMANDS/`, `SKILLS/` and `TEMPLATES/mcp/`), following
OpenCode V2's discovery paths. The output is **generated only** — never edit
`.opencode/` by hand; regenerate instead.

- `coordinator` is generated as the **primary** agent, so it appears in the runtime's
  agent selector; the other 11 roles are generated as **subagents** the primary agent
  can launch. This keeps sessions token-efficient: each subagent runs in its own fresh
  context and only its result returns to the parent.
- Commands render into `.opencode/commands/*.md`; skills render into `.opencode/skills/`.

To start new sessions as the orchestrator, add `"default_agent": "coordinator"` to
`opencode.jsonc`.

> All three adapters ship today: `se adapter opencode`, `se adapter claude-code` and
> `se adapter codex` (or `se adapter all` for every runtime at one output root).
> Runtime-specific behavior belongs in `INTEGRATIONS/`, never in `CORE/` or `SCHEMAS/`.

---

## 6. Configure models per agent

Each agent declares its model in its contract, `AGENTS/<name>/agent.json`:

```json
"llm_config": {
  "provider": "openai | anthropic | local | dummy",
  "model": "<model-id>",
  "temperature": 0.3,
  "max_tokens": 4096,
  "provider_options": { "api_key_env": "OPENAI_API_KEY" }
}
```

Providers available: `openai`, `anthropic`, `local` (Ollama / vLLM / OpenAI-compatible),
`dummy` (no key, deterministic — for tests). API keys are read from environment
variables named in `provider_options.api_key_env`.

> A dedicated CLI command to set this is not implemented yet; edit the contract and
> re-run `se adapter opencode`.

---

## 7. Register MCPs with `se install` (optional)

MCP integrations are **optional**; none is required by SE. `se install` takes you from a
cloned checkout to a runtime-configured OpenCode environment: it detects the OS, preflights
the external tools (never installing them for you), writes the servers declared in
`TEMPLATES/mcp/*.json.tmpl` straight into the runtime config (surgical, portable edits — the
`opencode` CLI is not needed for registration), and reports what was registered, skipped or
still missing.

For a full bootstrap — SE Core + Console + MCPs + runtimes installed, then the MCP servers
registered — pass `--bootstrap`: it runs the unified installer (`se-installer`) first and
then continues with the registration below. The one-command entry points are
[`SE-INSTALLER/bootstrap.ps1`](../../SE-INSTALLER/bootstrap.ps1) (Windows) and
[`SE-INSTALLER/install.sh`](../../SE-INSTALLER/install.sh) (Linux/macOS), which create an
isolated venv, install `se-installer` into it, and forward the arguments to the CLI.

```bash
python3 SCRIPTS/se.py install --dry-run     # plan only: writes nothing
python3 SCRIPTS/se.py install               # register every server in the project config
python3 SCRIPTS/se.py install --bootstrap   # run se-installer, then register
```

| MCP | What it is for | Third party |
|---|---|---|
| `engram` | Persistent memory across sessions | yes |
| `context7` | Up-to-date library documentation | yes |
| `filesystem` | Read/write files under a root (MCP reference server) | yes |
| `skill-server` | SE's own stdio skill server (SDD/ODD tools) | SE-owned |

### Flags

| Flag | Effect |
|---|---|
| `--project <dir>` | Target project directory (default: current directory) |
| `--global` | Register into the user config instead of the project config |
| `--all` | Register every server (default; mutually exclusive with `--with`) |
| `--with a,b,c` | Register only the listed servers |
| `--no-register` | Preflight and plan only; perform no registration |
| `--generate-adapter` | Also generate the OpenCode adapter for the target project |
| `--env-target {auto,windows,wsl,linux,macos}` | Runtime environment to target when resolving paths (default: `auto`; `wsl` translates Windows paths to `/mnt/<drive>`) |
| `--bootstrap` | Run the unified `se-installer` (SE Core + Console + MCPs + runtimes, and runtime configs) first, then register |
| `--bootstrap-components a,b` | Installer component ids for `--bootstrap` (default: recommended) |
| `--bootstrap-runtimes a,b` | Runtimes `--bootstrap` should configure (default: `opencode`) |
| `--dry-run` | Plan only; write nothing |
| `--json` | Emit a machine-readable `se.report/1` envelope |

Examples:

```bash
python3 SCRIPTS/se.py install --with engram,context7         # only these two
python3 SCRIPTS/se.py install --global                       # user config, not the project
python3 SCRIPTS/se.py install --no-register --project PROJECTS/MyApp
python3 SCRIPTS/se.py install --generate-adapter --project PROJECTS/MyApp
```

A server whose external binary is missing (for example `engram` before Engram is
installed) is **skipped** with per-OS install guidance; `se install` never installs
third-party tools itself. The python interpreter name is resolved at registration time
(`python3`, else `python`), and `se install` only registers a server when its dependency
is present.

### Configuration shape (OpenCode V2)

Registered servers land under `mcp.servers.<name>` in `opencode.json(c)`. A local server is:

```json
{
  "mcp": {
    "servers": {
      "engram": {
        "type": "local",
        "command": ["engram", "mcp"],
        "disabled": false
      }
    }
  }
}
```

Server names live under `mcp.servers` (never directly under `mcp`); there is no `enabled`
field — a server is active unless `disabled` is `true`. Environment values support
`{env:NAME}` substitution, which is how `se install` passes secrets such as
`CONTEXT7_API_KEY` without embedding them literally.

**Portability rule.** Configuration committed to a repository is host-independent:
relative paths (`"."`, `SCRIPTS/...`) and `{env:NAME}` references, never absolute host
paths. Host-specific resolution (absolute paths, interpreter names, credentials) belongs
to the machine, not the repo — it lives in the runtime's global configuration or in
environment variables. `se doctor`'s self-containment check fails any absolute host path
that reaches an operational surface (`opencode.jsonc`, `SCRIPTS/`, `CORE/`, ...), so the
tracked config keeps working on Windows, WSL and Linux alike.

### Lifecycle

`se install` is the first step of a single lifecycle that also includes
`se sync`, `se update` and `se uninstall`. They share one ownership record at
`<target>/.se/lifecycle-state.json` and the same safety rules (plan-first,
byte-preserving edits, backups, rollback, foreign entries never touched). The full
reference is [`lifecycle.md`](lifecycle.md).

```bash
python3 SCRIPTS/se.py sync --dry-run                 # reconcile declared vs registered vs actual
python3 SCRIPTS/se.py update --dry-run               # apply declared changes (with rollback) — plan only
python3 SCRIPTS/se.py uninstall                      # plan: remove only SE-owned servers (mutates nothing)
python3 SCRIPTS/se.py uninstall --apply              # perform the removal, reversibly
```

`se uninstall` is a **simulation by default**; only `--apply` performs, and even then
it removes only the servers SE recorded in the lifecycle state, backing the config up
and moving each removed server into an audit trail.

---

## SE-CONSOLE (web console — ships with SE)

A **local-first, read-only web console** over SYSTEM-ENGINEERING. It answers what SE is,
what state it's in, what it's made of, what its projects are, and what needs attention.

### Run it

```bash
cd SE-CONSOLE
python -m console.server          # -> http://127.0.0.1:8777
```

- **Requirements:** Python + `jsonschema` (already used by `se doctor`); no Node, no build step
- **Read-only by design:** writes answered 405; no DB, no cache, no manifest of its own
- **Epistemic labels:** every value tagged `OBSERVED` (verbatim from `se`), `DERIVED` (computed), or `UNKNOWN` (never defaulted to green)
- **Env overrides:** `SE_ROOT` (defaults to repo root when vendored), `SE_CONSOLE_PORT` (default 8777)
- **Docs:** `SE-CONSOLE/docs/README.md` · this guide

### Lifecycle with SE

The console ships inside the SYSTEM-ENGINEERING repository at `SE-CONSOLE/`. After cloning,
it's ready to run. No separate install step. `se doctor` and `se validate` cover its
dependencies (Python + `jsonschema`).

### Engram (persistent memory)

Engram is an **independent, third-party tool** with its own repository:
[`github.com/Gentleman-Programming/engram`](https://github.com/Gentleman-Programming/engram).
SE neither bundles it nor pins its executable path. Install it, then either let Engram
register itself (`engram setup opencode`, which also installs the session-tracking plugin)
or let `se install` register its MCP entry.

```bash
# Homebrew (macOS / Linux)
brew install gentleman-programming/tap/engram

# or build the current v3 line from source:
go install github.com/Gentleman-Programming/engram/v3/cmd/engram@latest

# or download a prebuilt binary from the official Releases page.
```

If you prefer to edit `opencode.json` by hand, use the V2 shape shown above:
`mcp.servers.engram` with `disabled` — never the old `mcp.engram` with `enabled`.

The variables to set for the registered servers (`SE_ROOT`, `SE_PROJECT_ROOT`,
`ENGRAM_PROJECT`, `CONTEXT7_API_KEY`, ...) are listed under **Environment variables**
below; `se install` prints the same list in its summary.

> **Recommended wording for users:** *"For additional capabilities you may install these
> third-party MCPs. None is a dependency of SE."*

---

## 8. Optional: CodeGraph

CodeGraph is an **optional accelerator**, not a dependency.

```bash
gentle-ai codegraph init --cwd <project-root>      # or: codegraph init <project-root>
```

Notes:
- On WSL with a project on a Windows drive, CodeGraph uses `.codegraph-wsl/` by
  design; the canon tolerates it (`doctor` ignores it, `.gitignore` excludes it).
- SE works with or without an index.

---

## 9. Quickstart

```bash
# create a managed project
python3 SCRIPTS/se.py init --dir PROJECTS/MyApp --name "MyApp" --owner "me" --domains software

# aggregate status
python3 SCRIPTS/se.py status --project PROJECTS/MyApp

# discover skills that match the project's capabilities
python3 SCRIPTS/se.py skill discover --project PROJECTS/MyApp --capability verification

# read-only integration: discovery + memory + orchestration plan + gates
python3 SCRIPTS/se.py intelligence --project PROJECTS/MyApp
```

---

## Environment variables

| Variable | Purpose |
|---|---|
| `SE_ROOT` | Canon repository root (referenced by generated MCP configs) |
| `SE_PROJECT_ROOT` | Project root being adapted (referenced by generated MCP configs) |
| `ENGRAM_PROJECT`, `CONTEXT7_API_KEY`, ... | Optional third-party MCP settings (Engram project name; API keys) |

---

## Updating

Two layers can drift from the current SE version, and they are updated separately.

The **managed project's SE layer** (adapter, `AGENTS.md`, version floor) is
reconciled with:

```bash
python3 SCRIPTS/se.py init PROJECTS/MyApp    # reconciles version + regenerates the adapter
```

The **runtime MCP registrations** are reconciled with the declared templates by the
lifecycle commands:

```bash
python3 SCRIPTS/se.py sync --project PROJECTS/MyApp --dry-run   # report missing / drifted servers
python3 SCRIPTS/se.py update --project PROJECTS/MyApp           # apply declared changes, with rollback
```

`se sync` registers missing servers and re-registers SE-owned drift while never
touching foreign entries; `se update` diffs the declared templates against the
registered state and applies changes, restoring a backup and reporting BLOCKED if
anything fails. See [`lifecycle.md`](lifecycle.md) for the full reference.

---

## Adopting an existing / independent project

A directory that already contains its own artifacts (`.opencode`, `AGENTS.md`,
`opencode.json`, SDD) and has no `PROJECT.json` is classified **EXTERNAL/INDEPENDENT**.
`se init` **refuses** it by design; bring it under the SE lifecycle with `se adopt`
instead:

```bash
python3 SCRIPTS/se.py adopt PROJECTS/LegacyApp --owner "me" \
  --scale large --risk high --criticality high
```

Adoption is **additive**: it writes `PROJECT.json` (recording `metadata.adoption` and a
`profiles.work` starting at `brownfield`) plus the empty workspace directories, and
leaves every file the project already had byte-for-byte untouched. Installing a runtime
adapter stays a separate, explicit step (`se adapter ...`). Use `--dry-run` to plan
without writing.

---

## What SE does NOT require

- `gentle-ai`
- a specific runtime, harness, adapter, model, or provider
- a specific machine or filesystem layout
