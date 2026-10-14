# SE Installer — Unified Installer for System Engineering Master System

## Overview

The **SE Installer** (`se-installer`) is a standalone package that provides an interactive, unified installation experience for the System Engineering Master System (SE). It installs and configures:

- **SE Core** — schemas, lifecycle, agents, commands, CLI (`se.py`)
- **SE Console** — local-first read-only web console (http://localhost:8777)
- **MCPs** — Model Context Protocol servers (Context7, Filesystem, Sequential Thinking, Playwright, Firecrawl, Engram, CodeGraph)
- **Runtime Adapters** — OpenCode, Codex CLI, Claude Code
- **User-selectable Models** — not tied to specific models; free tiers for OpenCode

---

## Architecture

```
se_installer/
├── models.py                 # Core data models (Component, Plan, Status, OSType)
├── components.py             # 14 component definitions with metadata
├── orchestrator.py           # Installation orchestration (topo sort, progress, state)
├── state/                    # Persistent installation state (JSON)
├── cli.py                    # CLI: install, list, status, doctor, tui
├── tui.py                    # Textual TUI (interactive component selection)
├── model_registry.py         # 14 models, user selections, recommendations
├── mcp_registry.py           # 6 MCPs with OpenAI function schemas
├── agent_mcp_binding.py      # 12 agent types → MCP + model bindings
├── skill_mcp_bridge.py       # Skills declare MCP capabilities @decorator
├── runtime_config_generator.py # OpenCode/Codex/Claude Code config generation
└── installers/
    ├── base.py               # BaseInstaller interface
    ├── mcp/__init__.py       # 7 MCP installers (npx, binary, cargo)
    └── runtime/__init__.py   # 3 runtime installers (opencode, codex, claude_code)
```

---

## Component Catalog

| ID | Name | Type | Category | Recommended | Install Method |
|----|------|------|----------|-------------|----------------|
| `se_core` | SE Core | `se_core` | Core | ✅ | pip (vendored) |
| `se_console` | SE Console | `se_console` | Core | ✅ | vendored |
| `engram` | Engram | `mcp` | Memory | ✅ | binary (GitHub releases) |
| `context7` | Context7 | `mcp` | Documentation | ✅ | npx |
| `filesystem` | Filesystem MCP | `mcp` | File Operations | ✅ | npx |
| `playwright` | Playwright MCP | `mcp` | Browser Automation | ❌ | npx + `playwright install chromium` |
| `firecrawl` | Firecrawl | `mcp` | Web Scraping | ❌ | npx (requires API key) |
| `sequential-thinking` | Sequential Thinking MCP | `mcp` | Reasoning | ❌ | npx |
| `codegraph` | CodeGraph | `mcp` | Code Intelligence | ❌ | cargo (Rust) |
| `node` | Node.js / npx | `mcp` | Runtime | ✅ | auto (fnm/winget/brew) |
| `rust` | Rust / Cargo | `mcp` | Runtime | ❌ | rustup |
| `opencode` | OpenCode | `runtime` | Runtime | ✅ | auto (winget/scoop/brew/script) |
| `codex` | Codex CLI | `runtime` | Runtime | ❌ | npm |
| `claude_code` | Claude Code | `runtime` | Runtime | ❌ | npm |

> **Note**: MCPs requiring Node.js (`context7`, `filesystem`, `playwright`, `firecrawl`, `sequential-thinking`) declare `requires: ["node"]`. The installer auto-installs Node.js only when at least one of these is selected.

---

## Model Registry — User-Selectable Models

The installer includes a **Model Registry** with 14 pre-registered models. Users choose per agent — no hardcoded bindings.

### Free Tier (OpenRouter / OpenCode Zen)

| ID | Name | Provider ID | Capabilities | Context | Tags |
|----|------|-------------|--------------|---------|------|
| `deepseek-r1-free` | DeepSeek R1 (Free) | `deepseek/deepseek-r1:free` | chat, code, reasoning, tools | 16K | reasoning, free |
| `llama-3.1-8b-free` | Llama 3.1 8B (Free) | `meta-llama/llama-3.1-8b-instruct:free` | chat, code, tools | 8K | fast, free |
| `qwen-2.5-coder-free` | Qwen 2.5 Coder (Free) | `qwen/qwen-2.5-coder-32b-instruct:free` | code, tools | 32K | coding, long-context |
| `gemini-flash-free` | Gemini 1.5 Flash (Free) | `google/gemini-flash-1.5:free` | chat, code, tools, vision | 1M | vision, long-context |
| **`nemotron-3-ultra-free`** | **Nemotron 3 Ultra (Free)** | **`nvidia/nemotron-3-ultra-550b-a55b:free`** | chat, code, reasoning, tools | 128K | reasoning, nvidia |
| **`nemotron-4-340b-free`** | **Nemotron 4 340B (Free)** | **`nvidia/nemotron-4-340b-instruct:free`** | chat, code, reasoning, tools | 128K | flagship, nvidia |

### Paid / BYOK

| ID | Provider | Cost (1k in/out) | Best For |
|----|----------|------------------|----------|
| `gpt-4o` | OpenAI | $0.005 / $0.015 | flagship multimodal |
| `gpt-4o-mini` | OpenAI | $0.00015 / $0.0006 | cheap, fast, vision |
| `o1-preview` | OpenAI | $0.015 / $0.06 | advanced reasoning |
| `claude-3.5-sonnet` | Anthropic | $0.003 / $0.015 | coding, reasoning |
| `claude-3.5-haiku` | Anthropic | $0.001 / $0.005 | fast, cheap |

### Local (Ollama / vLLM / LM Studio)

| ID | Model | Provider ID |
|----|-------|-------------|
| `llama-3.1-8b-local` | Llama 3.1 8B | `llama3.1:8b` |
| `qwen2.5-coder-local` | Qwen 2.5 Coder | `qwen2.5-coder:32b` |
| `deepseek-r1-local` | DeepSeek R1 | `deepseek-r1:32b` |

### Extending Models

Add custom models via JSON file:
```json
{
  "models": [
    {
      "id": "groq-llama-3.1-70b",
      "name": "Llama 3.1 70B (Groq)",
      "provider": "groq",
      "capabilities": ["chat", "code", "tools", "reasoning"],
      "context_window": 131072,
      "max_output": 8192,
      "is_free": false,
      "cost_per_1k_input": 0.00059,
      "cost_per_1k_output": 0.00079,
      "description": "Groq ultra-fast inference",
      "provider_model_id": "llama-3.1-70b-versatile",
      "tags": ["fast", "groq"]
    }
  ]
}
```
Load: `ModelRegistry(custom_models_path=Path("mis-modelos.json"))`

---

## MCP Registry — 6 Servers with Function Schemas

Each MCP declares:
- **Capabilities** (enum: `FILE_READ`, `WEB_SEARCH`, `CODE_INTELLIGENCE`, etc.)
- **Functions** (OpenAI function calling format with JSON Schema)
- **Install method** (`npx`, `binary`, `cargo`, `pip`)
- **Required env vars** (e.g., `CONTEXT7_API_KEY`, `FIRECRAWL_API_KEY`)

| MCP | Transport | Command | Key Functions | Requires |
|-----|-----------|---------|---------------|----------|
| Context7 | stdio | `npx -y @upstash/context7-mcp` | `resolve-library-id`, `query-docs` | Node, `CONTEXT7_API_KEY` |
| Filesystem | stdio | `npx -y @modelcontextprotocol/server-filesystem <root>` | `read_file`, `write_file`, `list_directory`, `search_files` | Node |
| Playwright | stdio | `npx -y @playwright/mcp` | `navigate`, `click`, `screenshot`, `fill_form`, `evaluate` | Node, Chromium |
| Firecrawl | stdio | `npx -y firecrawl-mcp` | `scrape`, `crawl`, `search` | Node, `FIRECRAWL_API_KEY` |
| Engram | stdio | `engram mcp --tools=agent` | `mem_save`, `mem_search`, `mem_get` | binary |
| CodeGraph | stdio | `codegraph-mcp` | `blast_radius`, `go_to_definition`, `find_references`, `impact_analysis` | Rust/cargo |

---

## Agent-MCP Binding — 12 Agent Types

Each agent type declares:
- **Required MCPs** (always available)
- **Allowed MCPs** (can use if installed)
- **Preferred model** + **fallback models**
- **Capability requirements** (maps to model capabilities)

| Agent | Required MCPs | Preferred Model | Fallbacks |
|-------|---------------|-----------------|-----------|
| Analyst | context7, filesystem, engram | deepseek-r1-free | gpt-4o-mini, claude-3.5-haiku |
| Architect | context7, filesystem, codegraph | claude-3.5-sonnet | gpt-4o, deepseek-r1-free |
| Implementer | filesystem, engram | claude-3.5-sonnet | gpt-4o, qwen-2.5-coder-free |
| Tester | filesystem, playwright | gpt-4o-mini | claude-3.5-haiku, deepseek-r1-free |
| Reviewer | filesystem, codegraph | claude-3.5-sonnet | gpt-4o, deepseek-r1-free |
| Planner | context7, filesystem, engram | claude-3.5-sonnet | gpt-4o, deepseek-r1-free |
| Coordinator | engram, filesystem | claude-3.5-sonnet | gpt-4o, deepseek-r1-free |
| Explorer | filesystem, context7 | deepseek-r1-free | claude-3.5-sonnet, gpt-4o-mini |
| Security | filesystem, codegraph | claude-3.5-sonnet | gpt-4o, deepseek-r1-free |
| Documentation | context7, filesystem | gpt-4o-mini | claude-3.5-haiku, gemini-flash-free |
| DevOps | filesystem, engram | gpt-4o-mini | claude-3.5-haiku, deepseek-r1-free |
| Visual | playwright, filesystem | gpt-4o-mini | gemini-flash-free, claude-3.5-haiku |

### Usage

```python
from se_installer import get_agent_mcp_registry, get_runtime_config_generator

amr = get_agent_mcp_registry()
rcg = get_runtime_config_generator()

# Get MCPs available for an agent
mcps = amr.get_available_mcps("implementer")

# Generate OpenCode config for agent
config = rcg.generate_opencode_config("implementer")
rcg.write_opencode_config(config, Path(".opencode/config.jsonc"))
```

---

## Skill-MCP Bridge

Skills declare MCP capabilities via decorator:

```python
from se_installer import requires_mcp_capabilities, MCPCapability

@requires_mcp_capabilities(MCPCapability.FILE_READ, MCPCapability.WEB_SEARCH)
class MyResearchSkill:
    def run(self, bridge):
        # bridge.get_function_schema_for_skill("my_skill") returns OpenAI functions
        functions = bridge.get_all_functions_for_skill("my_skill")
        # ... use functions via MCP transport
```

The bridge auto-resolves which MCPs provide the declared capabilities and exposes their functions in OpenAI format.

---

## Runtime Config Generator

Generates ready-to-use configuration files for supported runtimes:

### OpenCode (V2 format)
```python
config = rcg.generate_opencode_config("implementer")
# Returns RuntimeConfig with:
# - model: {provider, model, temperature, max_tokens}
# - mcp_servers: {"Context7": {...}, "Filesystem": {...}, ...}
# - env_vars: {...}
# - missing_env_vars: ["CONTEXT7_API_KEY", ...]

rcg.write_opencode_config(config, Path(".opencode/config.jsonc"))
```

Output (`.opencode/config.jsonc`):
```jsonc
{
  "version": "2",
  "theme": "default",
  "model": {
    "provider": "free",
    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "temperature": 0.3,
    "max_tokens": 8192
  },
  "mcp": {
    "servers": {
      "Context7": {
        "name": "Context7",
        "type": "local",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "environment": { "CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}" }
      },
      "Filesystem": {
        "name": "Filesystem",
        "type": "local",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/project"]
      }
    }
  },
  "environment": {}
}
```

### Codex CLI
```python
config = rcg.generate_codex_config("implementer")
rcg.write_codex_config(config, Path(".codex/config.json"))
```

### Claude Code
```python
config = rcg.generate_claude_code_config("implementer")
rcg.write_claude_code_config(config, Path(".claude/config.json"))
```

### UI Menus (for TUI/CLI selection)
```python
# Model selection menu for agent
models = rcg.get_model_selection_menu("implementer")
# Returns: [{"id": "...", "name": "...", "provider": "...", "is_free": true, "cost": "GRATIS", ...}, ...]

# MCP selection menu for runtime
mcps = rcg.get_mcp_selection_menu("opencode")
# Returns: [{"id": "...", "name": "...", "category": "...", "selected": false, "requires_env": [...], ...}, ...]
```

---

## CLI Usage

```bash
# Install recommended components (SE Core, Console, Engram, Context7, Filesystem, Node, OpenCode)
se-installer install --recommended

# Install specific components
se-installer install -c se_core se_console engram context7 filesystem opencode

# Install all components
se-installer install --all

# Dry run (plan only)
se-installer install --dry-run --recommended --json

# Also create the SE Console desktop shortcut (opt-in; one shortcut, start only)
se-installer install --recommended --shortcuts

# List all components
se-installer list --json

# List only installed
se-installer list --installed

# Check status (verifies installations)
se-installer status --json

# Health checks
se-installer doctor --json

# Interactive TUI
se-installer tui
```

### Target Runtimes
```bash
se-installer install --recommended --runtimes opencode codex claude_code
```

---

## Console Desktop Shortcut (opt-in)

`se-installer install --shortcuts` creates **one** desktop shortcut that starts the SE
Console. `--no-shortcuts` is the default and writes nothing to anybody's Desktop. The TUI
asks the same question with one checkbox.

- **One shortcut, start only** (DESIGN-5C D3). The console stops itself once nothing is
  watching it, so a Stop shortcut would have nothing to do.
- **Created only when `se_console` is part of the installation, and only after that
  installation succeeds.** A shortcut to a console that was never installed — or to an
  install that failed — breaks silently on the operator's Desktop weeks later.
- **`--dry-run` reports the shortcut it would create and creates nothing.**

| Platform | File | Points at |
|---|---|---|
| Windows | `SE Console.lnk` | `SE-CONSOLE/scripts/Start SE Console.cmd` |
| macOS | `SE Console.command` | `SE-CONSOLE/scripts/Start SE Console.command` |
| Linux | `SE Console.desktop` | `SE-CONSOLE/scripts/dev_console.py start` |

Windows is asked where the Desktop is (`[Environment]::GetFolderPath('Desktop')`) instead
of assuming `%USERPROFILE%\Desktop`, because OneDrive relocates it. Linux marks the
`.desktop` file trusted through `gio` where available. macOS gets a wrapper `.command`
rather than a symlink: the console's launcher begins with `cd "$(dirname "$0")"`, which
through a Desktop symlink would resolve to the Desktop instead of the console.

---

## TUI

The Textual TUI (`se-installer tui`) provides:
- Collapsible tree by category (Core, Memory, Documentation, File Operations, Browser, Web Scraping, Code Intelligence, Runtime)
- Checkbox selection with dependency auto-resolution
- Desktop shortcut opt-in (one checkbox: *Crear acceso directo en el Escritorio (SE Console)*)
- Model selection per agent (shows free/paid, capabilities, cost)
- MCP selection per runtime
- Real-time progress bar during installation
- Log panel with detailed output

---

## Installation State

State persisted to `~/.se-installer/state.json`:
```json
{
  "plan": { ... },
  "components": [
    { "id": "engram", "status": "success", "installed_version": "3.2.1", ... }
  ],
  "created_at": "2026-10-11T19:00:00Z",
  "completed_at": "2026-10-11T19:02:00Z"
}
```

---

## Integration with SE Lifecycle

The SE Installer is **independent** from the SE Core lifecycle commands (`se install`, `se sync`, `se update`, `se uninstall`):

| Layer | Responsibility |
|-------|----------------|
| `se-installer` | **Bootstrap**: install binaries, runtimes, MCPs, generate runtime configs |
| `se install` | **Runtime integration**: register MCPs in OpenCode, write lifecycle state |
| `se sync` | **Reconcile**: declared vs registered vs actual |
| `se update` | **Update**: diff + apply + verify + rollback |
| `se uninstall` | **Remove**: SE-owned entries only, preserve foreign config |

`se install --bootstrap` delegates to `se-installer` for the bootstrap phase
(installing SE Core, Console, MCPs and runtimes) and then continues with the MCP
registration described in [`installation.md`](installation.md). The one-command
entry points are `SE-INSTALLER/bootstrap.ps1` (Windows) and `SE-INSTALLER/install.sh`
(Linux/macOS).

---

## Development

```bash
cd SE-INSTALLER
pip install -e .[dev]
pytest tests/
python -m se_installer.cli doctor --json
```

### Adding a New MCP

1. Add `MCPServer` definition in `mcp_registry.py:_load_builtin_mcps()`
2. Add installer in `installers/mcp/__init__.py` (if not npx/binary/cargo)
3. Add component in `components.py`
4. Update agent bindings in `agent_mcp_binding.py` if needed

### Adding a New Runtime

1. Add installer in `installers/runtime/__init__.py`
2. Add component in `components.py` (type `RUNTIME`)
3. Add `generate_<runtime>_config()` in `runtime_config_generator.py`
4. Add `write_<runtime>_config()` method

---

## Design Principles

1. **Official sources only** — MCPs installed from official channels (`npx -y @pkg`, GitHub releases, cargo, winget/brew). No vendored binaries.
2. **User choice** — Models not tied to agents; free tiers prioritized; selections persisted.
3. **Agent awareness** — Agents know which MCPs are available (like skills).
4. **Skill-MCP bridge** — Skills declare capabilities; bridge resolves to MCP functions.
5. **Runtime configs** — Generated, not hand-written; OpenCode V2 format native.
6. **Node conditional** — Node.js only installed when an npx-based MCP (Context7, Filesystem, Playwright, Firecrawl, Sequential Thinking) is selected.
7. **Hermetic tests** — Fake runners, temp sandboxes, no real CLI invocation.

---

## References

- [OpenCode MCP Documentation](https://opencode.ai/v2/docs/mcp-servers)
- [Model Context Protocol Spec](https://modelcontextprotocol.io)
- [OpenCode Zen Free Models](https://opencode.ai/docs/zen)
- [Context7 API](https://context7.com)
- [Engram Memory](https://github.com/Gentleman-Programming/engram)
- [CodeGraph](https://codegraph.dev)