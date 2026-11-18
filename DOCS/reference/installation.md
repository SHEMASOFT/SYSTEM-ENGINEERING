# Installation — SYSTEM ENGINEERING

SYSTEM ENGINEERING (SE) is **portable and self-contained**: it needs no `gentle-ai`,
no specific runtime, harness or model. This guide goes from a clean machine to a
working checkout, easiest path first.

The reference implementation is a Python CLI: `python3 SCRIPTS/se.py <command>`.
On Windows the interpreter is `python`, so read `python3` as `python` and use
backslash paths (`python SCRIPTS\se.py <command>`).

## Pick a path

| Path | Best for | Start with |
|---|---|---|
| **One command** (recommended) | A fresh machine; you want the console, the MCP servers and the adapters configured | `bootstrap.ps1 install --recommended` |
| **Browser UI** | You prefer clicking through components, runtimes and options | `install-web.ps1` |
| **Minimal** | You only want the CLI, or you are auditing the code | `git clone` + `pip install jsonschema` |

All three end with the same validation: `se doctor` and `se validate` both pass.

---

## 1. One command (recommended)

The installer creates an isolated virtual environment at `SE-INSTALLER/.venv`,
installs SE Core and the console into it, generates the runtime adapters and
registers the selected MCP servers.

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File SE-INSTALLER\bootstrap.ps1 install --recommended
```

```bash
# Linux / macOS
bash SE-INSTALLER/install.sh install --recommended
```

- `--dry-run` plans without installing anything.
- `tui` opens the interactive selector: `Space` select, `A` recommended set,
  `Enter` install, `D` dry-run, `R` refresh, `Q` quit.
- `--skip-mcp-registration` opts out of writing the MCP servers into the config.
- If the installer had to install Node or OpenCode, open a **new terminal** so the
  updated `PATH` is loaded, then run `opencode auth login` once.

On Windows the bootstrap installs Python 3.12 when no 3.10+ interpreter exists: it
tries winget, Chocolatey and Scoop, then the official signed python.org installer
for the current user (no administrator needed). Missing Node comes from the
official LTS ZIP (SHA256 verified) and OpenCode from its standalone binary when no
package manager is available. On Linux/macOS install `python3` (and
`python3-venv` on Debian/Ubuntu) first.

> **Where a virtualenv may live.** The entry points keep theirs at
> `SE-INSTALLER/.venv`, which `se doctor` audits cleanly. If you create your own,
> keep it **outside** the repository or name it `.venv` at the root: any other
> venv directory inside the repo is an unregistered root directory, and one not
> named `.venv` also trips the `secrets` scan (the bundled `certifi/cacert.pem`),
> so `se doctor` reports `FAIL`.

`se install --bootstrap` does the same from an already-cloned checkout: it runs
the installer first and then the MCP registration (see [§7](#7-register-mcps-optional)).

---

## 2. Browser UI (optional)

A local web interface over the same installer: components, runtimes, options and a
live log, all in the browser.

```powershell
# Windows — detects a free port (8765, 8766, …) and opens the browser
.\SE-INSTALLER\install-web.ps1
```

```bash
# Linux / macOS
bash SE-INSTALLER/install-web.sh
```

Direct alternatives: `pip install -e SE-INSTALLER` then `se-installer-web --port 8765`,
or without installing the package
`python -m uvicorn se_installer_web.main:app --host 127.0.0.1 --port 8765 --reload`.

The script picks a free port, opens **http://127.0.0.1:8765** (or the next free one)
and releases the port on `Ctrl+C`.

| Tab | What it does |
|---|---|
| **Install** | 22 components with checkboxes, runtime selection (OpenCode, Codex, Claude Code), dry-run / force / skip-verification / shortcut options, progress bar |
| **Uninstall** | `--all`, `--include-untracked-se-mcps`, `--remove-opencode-dir`, `--purge-adapter`, `--keep-opencode-jsonc`, `--force`, `--apply`; plan first, then apply |
| **Adapter** | Generate or remove the generated `.opencode/` layer |
| **Log** | Real-time stream over WebSocket |

REST surface for integrations: `/api/components`, `/api/status`, `/api/install`,
`/api/uninstall`, `/api/adapter/generate`, `/api/adapter/remove`, plus a WebSocket at
`/ws` for the live log.

Requirements: Python 3.10+ and the package (`pip install -e SE-INSTALLER`). The
frontend is vanilla HTML/JS/CSS at `SCRIPTS/se_installer_web/static/index.html` —
no build step. Development mode: `se-installer-web --dev --reload`.

Everything the UI does has a CLI equivalent:

```bash
se-installer-web --all --dry-run              # same as: python SCRIPTS/se.py uninstall --all --dry-run
se-installer-web --all --apply                # same as: python SCRIPTS/se.py uninstall --all --apply
```

---

## 3. Minimal (no installer)

```bash
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git SYSTEM-ENGINEERING
cd SYSTEM-ENGINEERING
pip install jsonschema
```

That is the whole minimal path: no Node, no runtime, no MCP server, no venv.

| Dependency | Required | Purpose |
|---|---|---|
| `python3` | **yes** | The reference CLI (`SCRIPTS/se.py`) and the SE Python MCP servers |
| `node` | **yes for MCP** | The portable Python MCP launcher |
| `npx` | **yes for MCP** | Package-based MCP servers (`context7`, `filesystem`) |
| `jsonschema` | **yes** | Schema validation; `se doctor` fails without it |
| `PyYAML` | optional | Skill frontmatter parsing (falls back to a line parser) |
| `requests` | optional | `local` LLM provider (Ollama / vLLM / OpenAI-compatible) |
| `openai`, `anthropic` | optional | The `openai` / `anthropic` providers |

`PROJECTS/` is intentionally excluded from version control: each project keeps its
own history. The clone carries the **system**, not the projects. The console is
vendored at `SE-CONSOLE/`.

---

## 4. Validate

```bash
python3 SCRIPTS/se.py doctor      # structure, contracts, dependencies, git, secrets
python3 SCRIPTS/se.py validate    # schemas, agents, domains
```

Both must pass before working with projects. `FAIL=0` is the part that matters;
`WARN` entries are informational. Both exit non-zero on `FAIL`, so they are safe to
wire into CI.

---

## 5. Adapt a runtime

SE generates the agent layer from its own contracts:

```bash
python3 SCRIPTS/se.py adapter opencode      # .opencode/
python3 SCRIPTS/se.py adapter claude-code   # .claude/ + .mcp.json + CLAUDE.md
python3 SCRIPTS/se.py adapter codex         # .codex/ + AGENTS.md
python3 SCRIPTS/se.py adapter all           # every runtime at one output root
```

The output is **generated only**: never edit `.opencode/`, regenerate instead.

- `shema-ai-coordinador` is generated as the **primary** agent and appears in the
  runtime's selector; the other 11 roles are **subagents** it can launch. Each
  subagent runs in its own fresh context and only its result returns, which is the
  token economy of the system.
- Commands render into `.opencode/commands/*.md`, skills into `.opencode/skills/`.
- To make new sessions start as the coordinator, set
  `"default_agent": "shema-ai-coordinador"` in `opencode.jsonc` (the master
  repository already does).

Runtime-specific behaviour belongs in `INTEGRATIONS/`, never in `CORE/` or `SCHEMAS/`.

---

## 6. Configure models per agent

Each agent declares its model in `AGENTS/<name>/agent.json`:

```json
"llm_config": {
  "provider": "openai | anthropic | local | dummy",
  "model": "<model-id>",
  "temperature": 0.3,
  "max_tokens": 4096,
  "provider_options": { "api_key_env": "OPENAI_API_KEY" }
}
```

Providers: `openai`, `anthropic`, `openrouter`, `ollama`, `local`
(Ollama / vLLM / OpenAI-compatible) and `dummy` (no key, deterministic, for tests).
Keys are read from the environment variable named in `provider_options.api_key_env`.

`se adapter opencode` renders `model: <provider>/<model>` into
`.opencode/agents/<role>.md`; `se adapter codex` writes it to
`.codex/agents/<role>.toml`. A model that already contains `/` is used verbatim,
otherwise the provider is prepended. Aliases: `free` → `openrouter`, `local` → `ollama`.

> There is no CLI command to set this yet: edit the contract and re-run the adapter.

SE never stores provider credentials. Authenticate the runtime once:

```bash
opencode auth login
opencode auth list      # verify the configured provider
```

Without a provider, OpenCode starts but agent calls fail. The environment variables
named by the contract (for example `OPENAI_API_KEY`) are the alternative to login.

---

## 7. Register MCPs (optional)

MCP integrations are **optional**; none is required by SE. `se install` takes a
cloned checkout to a configured OpenCode environment: it detects the OS, preflights
the external tools (never installing them for you), writes the servers declared in
`TEMPLATES/mcp/*.json.tmpl` into the runtime config with surgical, portable edits,
and reports what was registered, skipped or still missing.

Before writing, every selected `npx` server is started and asked for an MCP
`initialize` response, which catches a broken Node install, a bad shim or a package
that cannot start. A server that does not answer is reported and **skipped**. Pass
`--no-verify-servers` to skip the handshake (offline, or faster).

| MCP | Purpose | Third party |
|---|---|---|
| `context7` | Up-to-date library documentation | yes |
| `filesystem` | Read/write files under a root (reference server) | yes |
| `skill-server` | SE's stdio skill server (SDD/ODD/RDD + skill catalog tools) | SE-owned |
| `memory-server` | SE's shared memory engine over MCP | SE-owned |

```bash
python3 SCRIPTS/se.py install --dry-run     # plan only: writes nothing
python3 SCRIPTS/se.py install               # register every server in the project config
python3 SCRIPTS/se.py install --bootstrap   # run se-installer first, then register
```

| Flag | Effect |
|---|---|
| `--project <dir>` | Target project directory (default: current directory) |
| `--global` | Register into the user config instead of the project config |
| `--all` / `--with a,b,c` | Every server (default) / only the listed ones |
| `--no-register` | Preflight and plan only |
| `--no-verify-servers` | Skip the MCP `initialize` handshake |
| `--generate-adapter` | Also generate the OpenCode adapter for the target project |
| `--env-target {auto,windows,wsl,linux,macos}` | Path target (`wsl` translates Windows paths to `/mnt/<drive>`) |
| `--bootstrap` / `--bootstrap-components` / `--bootstrap-runtimes` | Run the unified installer first |
| `--dry-run` / `--json` | Plan only / machine-readable `se.report/1` envelope |

A server whose external binary is missing is skipped with per-OS guidance; one that
fails the handshake is skipped with the probe output. The SE Python servers launch
through `SCRIPTS/se_core/mcp/launch.mjs`, a portable Node launcher that resolves
`python3` or `python` at startup (`SE_PYTHON` pins an interpreter).

### Configuration shape (OpenCode V2)

Servers land under `mcp.servers.<name>`:

```json
{
  "mcp": {
    "servers": {
      "filesystem": {
        "type": "local",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path/to/project"],
        "disabled": false
      }
    }
  }
}
```

There is no `enabled` field: a server is active unless `disabled` is `true`.
`{env:NAME}` substitution is how `se install` passes secrets such as
`CONTEXT7_API_KEY` without embedding them.

**Portability rule.** Committed configuration is host-independent: relative paths
and `{env:NAME}` references, never absolute host paths. Host-specific resolution
belongs to the machine (global runtime config or environment variables). The Python
MCP entries therefore invoke the Node launcher instead of naming an interpreter, so
the tracked config works on Windows, WSL and Linux alike. `se doctor`'s
self-containment check fails any absolute host path that reaches an operational
surface (`opencode.jsonc`, `SCRIPTS/`, `CORE/`, …).

### Lifecycle

`se install` is the first step of one lifecycle with `se sync`, `se update` and
`se uninstall`. They share the ownership record at `<target>/.se/lifecycle-state.json`
and the same safety rules: plan first, byte-preserving edits, backups, rollback, and
foreign entries never touched. Full reference: [`lifecycle.md`](lifecycle.md).

```bash
python3 SCRIPTS/se.py sync --dry-run        # reconcile declared vs registered vs actual
python3 SCRIPTS/se.py update --dry-run      # apply declared changes (with rollback), plan only
python3 SCRIPTS/se.py uninstall             # plan: removes nothing
python3 SCRIPTS/se.py uninstall --apply     # perform, reversibly
```

`se uninstall` is a **simulation by default**: only `--apply` performs, and even then
it removes only the servers SE recorded, backing the config up and moving each
removed entry into an audit trail.

### Skill install tool

`skill_catalog_install` installs a skill from a controlled local source into
`SKILLS/` and registers it in `CATALOG/skills.json`. It requires `name`,
`source_path` (repo root or `<tmp>/se-skill-sources` only) and `confirm: true`;
traversal, symlinks and Windows reparse points are rejected, the `SKILL.json`
contract and the static security scan must pass, and activation is an atomic rename
with rollback. Known limits: no catalog lock for concurrent installs, no dependency
resolution, no update mechanism.

---

## 8. SE Console (ships with SE)

A **local-first, read-only web console** over the system: what SE is, what state it
is in, what it is made of, and what needs attention.

```bash
cd SE-CONSOLE
python scripts/dev_console.py start   # -> http://127.0.0.1:8777, in the background
python scripts/dev_console.py status
python scripts/dev_console.py stop    # clean shutdown
```

- **Requirements:** Python + `jsonschema` (already needed by `se doctor`). No Node, no build step.
- **Read-only by design:** writes answered 405; no database, no cache, no manifest of its own.
- **Epistemic labels:** every value is `OBSERVED` (verbatim from `se`), `DERIVED` (computed) or `UNKNOWN` — never defaulted to green.
- **Overrides:** `SE_ROOT`, `SE_CONSOLE_PORT` (default 8777), `SE_CONSOLE_IDLE_TIMEOUT`.
- **Docs:** [`SE-CONSOLE/docs/README.md`](../../SE-CONSOLE/docs/README.md).

`se-installer install --shortcuts` (or the TUI checkbox) creates **one** desktop
shortcut that starts it. There is no stop shortcut: `start` arms a 15-minute idle
timeout (`--idle-timeout SECONDS`, `0` disables it) and, once a client has connected,
the console stops itself when nothing asks it for anything. The timer stays disarmed
until the first client connects, so a console nobody opens never stops on its own.
`status` reports `idle_timeout=15 min`, `off`, or `unknown` (not started by the
helper). The helper is a local convenience: no Docker, no systemd, no boot entry, and
it writes only under `SE-CONSOLE/.runtime/` (gitignored).

---

## 9. Memory (built-in)

SE's persistent memory is **internal**: no third-party tool and no MCP server
required. Storage is JSON under `<root>/.se/memory/` with a derived, rebuildable
SQLite/FTS5 index; semantic search is an optional reranker over those results
(`se memory index --embeddings <vec>` or `SE_MEMORY_EMBEDDINGS`) that never touches
the network.

```bash
python3 SCRIPTS/se.py memory add --type decision --title "..." --body "..."
python3 SCRIPTS/se.py memory search "topic keywords"
python3 SCRIPTS/se.py intelligence --memory "topic"   # read-only context injection
```

Memory is **advisory**: no gate passes or fails because of it.

---

## 10. Optional: CodeGraph

An **optional accelerator**, not a dependency:

```bash
gentle-ai codegraph init --cwd <project-root>      # or: codegraph init <project-root>
```

On WSL with a project on a Windows drive it uses `.codegraph-wsl/` by design
(`se doctor` ignores it, `.gitignore` excludes it). SE works with or without an index.

---

## 11. Your first project

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

`se status` reporting `Overall: FAIL` on a brand-new project is expected: the later
gates have nothing to check yet. The exit code is the verdict, not a crash.

---

## Environment variables

| Variable | Purpose |
|---|---|
| `SE_ROOT` | Canon repository root (referenced by generated MCP configs) |
| `SE_PROJECT_ROOT` | Project root being adapted (referenced by generated MCP configs) |
| `CONTEXT7_API_KEY`, … | Optional third-party MCP settings |
| `SE_PYTHON` | Pins the interpreter the Node launcher resolves |
| `SE_MEMORY_EMBEDDINGS` | Optional local reranker for memory search |

---

## Updating

Two layers can drift from the current SE version, and they are updated separately.

The **managed project's SE layer** (adapter, `AGENTS.md`, version floor) is
reconciled with:

```bash
python3 SCRIPTS/se.py init PROJECTS/MyApp    # reconciles version, regenerates the adapter
```

The **runtime MCP registrations** are reconciled with the declared templates:

```bash
python3 SCRIPTS/se.py sync --project PROJECTS/MyApp --dry-run   # report missing / drifted
python3 SCRIPTS/se.py update --project PROJECTS/MyApp           # apply, with rollback
```

`se sync` registers missing servers and re-registers SE-owned drift while never
touching foreign entries; `se update` diffs the declared templates against the
registered state and applies changes, restoring a backup and reporting `BLOCKED` if
anything fails. See [`lifecycle.md`](lifecycle.md).

---

## Adopting an existing project

A directory that already contains its own artifacts (`.opencode`, `AGENTS.md`,
`opencode.json`, SDD) and has no `PROJECT.json` is classified
**EXTERNAL/INDEPENDENT**. `se init` **refuses** it by design; bring it under the
lifecycle with `se adopt`:

```bash
python3 SCRIPTS/se.py adopt PROJECTS/LegacyApp --owner "me" \
  --scale large --risk high --criticality high
```

Adoption is **additive**: it writes `PROJECT.json` (recording `metadata.adoption` and
a `profiles.work` starting at `brownfield`) plus the empty workspace directories, and
leaves every existing file byte-for-byte untouched. Installing a runtime adapter
stays a separate, explicit step. Use `--dry-run` to plan without writing.

---

## What SE does NOT require

- `gentle-ai`
- a specific runtime, harness, adapter, model or provider
- a specific machine or filesystem layout
