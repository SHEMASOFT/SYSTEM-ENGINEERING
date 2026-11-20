"""Runtime adapters beyond OpenCode: Claude Code, Codex, and DeepSeek Harness.

Each adapter renders the same canonical contracts — ``AGENTS/*/agent.json``,
``COMMANDS/commands.json``, ``SKILLS/*/SKILL.md`` and ``TEMPLATES/mcp/*`` — into
the files that runtime discovers. Generation is deterministic (fixed order, LF,
no timestamps) and never edits the canonical sources, exactly like the OpenCode
adapter.

MCP entries reuse :func:`se_core.install.resolved_server_spec` in portable mode:
project-relative paths (plus a working directory where the runtime supports it),
so a generated runtime config never carries a host path.
"""

from __future__ import annotations

import json
from pathlib import Path

from .install import (
    load_mcp_templates,
    read_project_id,
    resolved_server_spec,
)

from .model_tui.config import resolve_agent_model


# --------------------------------------------------------------------------- #
# canonical inputs
# --------------------------------------------------------------------------- #


def _load_agents(root: Path) -> list[dict]:
    agents = []
    for path in sorted((root / "AGENTS").glob("*/agent.json")):
        agents.append(json.loads(path.read_text(encoding="utf-8")))
    return agents


def _load_commands(root: Path) -> list[dict]:
    data = json.loads((root / "COMMANDS" / "commands.json").read_text(encoding="utf-8"))
    return data["commands"]


def _load_skills(root: Path) -> dict[str, str]:
    return {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted((root / "SKILLS").glob("*/SKILL.md"))
    }


def mcp_entries(root: Path, project: Path | None = None) -> dict:
    """Portable MCP server entries for a runtime config (no host paths)."""
    project = Path(project or root)
    project_id = read_project_id(project)
    entries = {}
    for template in load_mcp_templates(root):
        spec = resolved_server_spec(
            template,
            se_root=root,
            project=project,
            project_id=project_id,
            interpreter=None,
            portable=True,
        )
        entries[spec["name"]] = spec
    return entries


# --------------------------------------------------------------------------- #
# shared rendering
# --------------------------------------------------------------------------- #


def _yaml(value: str) -> str:
    """Render a string as a safe single-line YAML scalar."""
    text = " ".join(str(value).split())
    if not text or any(ch in text for ch in (":", "#", "{", "}", "[", "]", '"', "'")):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _agent_body(agent: dict) -> str:
    lines = [
        f"- **id**: {agent.get('id')}",
        f"- **version**: {agent.get('version')}",
        f"- **purpose**: {agent.get('purpose', '')}",
        f"- **gates**: {', '.join(agent.get('gate_responsibility', []))}",
        "",
        "## Capabilities",
        "",
    ]
    for cap in agent.get("capabilities", []):
        lines.append(f"- **{cap.get('name', '')}** — {cap.get('description', '')}")
    lines += ["", "## Restrictions", ""]
    for item in agent.get("restrictions", []) or ["none declared"]:
        lines.append(f"- {item}" if not str(item).startswith("-") else str(item))
    lines += ["", "## Permissions", ""]
    for item in sorted(agent.get("permissions", [])):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _command_body(command: dict) -> str:
    return "\n".join([
        f"# {command['name']}",
        "",
        f"- **purpose**: {command.get('purpose', '')}",
        f"- **execution_intent**: {command.get('execution_intent')}",
        f"- **risk_level**: {command.get('risk_level')}",
        f"- **gate**: {command.get('gate')}",
        "",
        f"se {command['name']} --project $ARGUMENTS",
        "",
    ])


# --------------------------------------------------------------------------- #
# Claude Code
# --------------------------------------------------------------------------- #


def render_claude_code(root: Path) -> dict[str, str]:
    """Render the Claude Code layer (``.claude/`` + ``.mcp.json`` + CLAUDE.md)."""
    root = Path(root)
    agents = _load_agents(root)
    commands = _load_commands(root)
    files: dict[str, str] = {}

    for agent in sorted(agents, key=lambda a: a["name"]):
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        front = f"---\nname: {agent['name']}\ndescription: {_yaml(description)}\n---\n\n"
        files[f".claude/agents/{agent['name']}.md"] = front + _agent_body(agent)

    for command in sorted(commands, key=lambda c: c["name"]):
        description = (command.get("description") or command.get("purpose") or "").strip()
        front = f"---\ndescription: {_yaml(description)}\n---\n\n"
        files[f".claude/commands/{command['name']}.md"] = front + _command_body(command)

    for name, content in _load_skills(root).items():
        files[f".claude/skills/{name}/SKILL.md"] = content

    servers = {}
    for name, spec in mcp_entries(root).items():
        entry = {"command": spec["command"][0], "args": spec["command"][1:]}
        if spec.get("environment"):
            entry["env"] = spec["environment"]
        servers[name] = entry
    files[".mcp.json"] = json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False) + "\n"

    lines = [
        "# CLAUDE",
        "",
        "Generated by `se adapter claude-code` from the canonical contracts. Generated",
        "output only; regenerate instead of editing.",
        "",
        "## Agents",
        "",
    ]
    for agent in sorted(agents, key=lambda a: a["name"]):
        lines.append(f"- **{agent['name']}** — {agent.get('description') or agent.get('purpose', '')}")
    lines += ["", "## Commands", ""]
    for command in sorted(commands, key=lambda c: c["name"]):
        lines.append(f"- **/{command['name']}** — {command.get('description') or command.get('purpose', '')}")
    lines += ["", "## MCP servers", ""]
    for name in sorted(servers):
        lines.append(f"- `{name}`")
    lines.append("")
    files["CLAUDE.md"] = "\n".join(lines)
    return files


# --------------------------------------------------------------------------- #
# Codex
# --------------------------------------------------------------------------- #


def _toml_string(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_array(items) -> str:
    return "[" + ", ".join(_toml_string(item) for item in items) + "]"


def render_codex(root: Path) -> dict[str, str]:
    """Render the Codex layer (``.codex/`` + ``AGENTS.md``)."""
    root = Path(root)
    agents = _load_agents(root)
    commands = _load_commands(root)
    files: dict[str, str] = {}

    lines = [
        "# AGENTS",
        "",
        "Generated by `se adapter codex` from the canonical contracts. Generated output",
        "only; regenerate instead of editing.",
        "",
        "## Roles",
        "",
    ]
    for agent in sorted(agents, key=lambda a: a["name"]):
        lines.append(f"- **{agent['name']}** — {agent.get('description') or agent.get('purpose', '')}")
    lines += ["", "## Commands", ""]
    for command in sorted(commands, key=lambda c: c["name"]):
        lines.append(f"- **{command['name']}** — {command.get('description') or command.get('purpose', '')}")
    lines.append("")
    files["AGENTS.md"] = "\n".join(lines)

    for command in sorted(commands, key=lambda c: c["name"]):
        files[f".codex/prompts/{command['name']}.md"] = _command_body(command)

    for agent in sorted(agents, key=lambda a: a["name"]):
        role_lines = []
        llm = agent.get("llm_config") or {}
        if llm.get("model"):
            role_lines.append(f"model = {_toml_string(str(llm['model']))}")
        role_lines.append('developer_instructions = """')
        role_lines.append(_agent_body(agent).rstrip())
        role_lines.append('"""')
        role_lines.append("")
        files[f".codex/agents/{agent['name']}.toml"] = "\n".join(role_lines)

    config = [
        "# Codex configuration fragment generated by `se adapter codex`.",
        "# Codex reads ~/.codex/config.toml: merge this fragment into it (or pass the",
        "# file with --config). Regenerate with `se adapter codex`.",
        "",
    ]
    for name, spec in sorted(mcp_entries(root).items()):
        config.append(f"[mcp_servers.{name}]")
        config.append(f"command = {_toml_string(spec['command'][0])}")
        config.append(f"args = {_toml_array(spec['command'][1:])}")
        if spec.get("cwd"):
            config.append(f"cwd = {_toml_string(spec['cwd'])}")
        env = spec.get("environment") or {}
        if env:
            config.append(f"[mcp_servers.{name}.env]")
            for key in sorted(env):
                config.append(f"{key} = {_toml_string(env[key])}")
        config.append("")
    for agent in sorted(agents, key=lambda a: a["name"]):
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        config.append(f"[agents.{agent['name']}]")
        config.append(f"description = {_toml_string(description)}")
        config.append(f"config_file = {_toml_string('agents/%s.toml' % agent['name'])}")
        config.append("")
    files[".codex/config.toml"] = "\n".join(config)
    return files


# --------------------------------------------------------------------------- #
# writing and entry points
# --------------------------------------------------------------------------- #


def _write(output: Path, files: dict[str, str], dry_run: bool) -> list[dict]:
    written = []
    for rel in sorted(files):
        dest = output / rel
        content = files[rel]
        existed = dest.exists()
        unchanged = existed and dest.read_bytes() == content.encode("utf-8")
        action = "unchanged" if unchanged else ("overwrite" if existed else "write")
        written.append({"path": rel, "action": action, "bytes": len(content.encode("utf-8"))})
        if not dry_run and not unchanged:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8", newline="\n")
    return written


def _model_for_agent(root: Path, agent: dict) -> str | None:
    """Resolve the model one agent should run with, as ``provider/model``.

    The agent contract wins when it declares one; otherwise the harness-level
    selection (the same one `se shema-ai model` writes) applies. There is no
    invented fallback: an unconfigured model stays unset.
    """
    contract = agent.get("llm_config") or {}
    if contract.get("model"):
        provider = str(contract.get("provider") or "").strip()
        model = str(contract["model"]).strip()
        return f"{provider}/{model}" if provider and "/" not in model else model

    try:
        from .model_tui.config import resolve_agent_model

        return resolve_agent_model(Path(root), agent.get("name") or "")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# DeepSeek Harness
# --------------------------------------------------------------------------- #

_DEEPSEEK_HEADER = (
    "Generated by `se adapter deepseek` from the canonical contracts. "
    "Generated output only; regenerate instead of editing."
)

_DSH_PRESET_PLUGIN = "@deepseek-ai/dsh-agent-preset"
_DSH_PERSONA_PLUGIN = "@deepseek-ai/dsh-persona"
_DSH_INSTRUCTION_BYTES = 65536


def _deepseek_frontmatter(content: str, header: str) -> str:
    """Place ``header`` after a leading YAML frontmatter block, if any.

    DSH parses a skill's frontmatter first, so provenance cannot go above it;
    inserting it directly after the closing fence keeps ``name`` and
    ``description`` at the top of the file while still marking the copy as
    generated output.
    """
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            cut = end + len("\n---\n")
            return content[:cut] + "\n" + header + "\n" + content[cut:]
    return header + "\n\n" + content


def _yaml_block(text: str, indent: str) -> str:
    """Render ``text`` as a literal YAML block scalar body at ``indent``."""
    lines = text.rstrip("\n").split("\n")
    return "\n".join(indent + line if line else "" for line in lines)


def _deepseek_route(spec: str | None) -> tuple[str, str] | None:
    """Split a ``provider/model`` spec into DSH's separate ``provider``/``model``."""
    if not spec:
        return None
    provider, _, model_id = spec.partition("/")
    if not model_id:
        provider, model_id = "", provider
    return provider, model_id


def _deepseek_patch(agents: list[dict], routes: dict[str, str | None]) -> str:
    """Compose the DSH profile patch overlay (``dsh --patch <file>``)."""
    lines = [
        f"# {_DEEPSEEK_HEADER}",
        "#",
        "# DSH applies a patch list after the profile layer, so this overlay is used as",
        "#   dsh --patch .dsh/se.patch.yml",
        "# or appended to $DSH_HOME/profiles/<profile>/cordis.patch.yml. It declares one",
        "# agent preset per SE role; the preset's persona carries the role contract.",
        "#",
        "# A DSH preset replaces the complete child plugin list, so this adapter renders",
        "# role instructions, the project instruction file and the SE skill surface. Add",
        "# the tool rows your deployment grants instead of expecting them here.",
        "#",
        "# DSH 0.2.2-rc.3 binds a model per agent only on launcher and delegation rows",
        "# (`agent-loop.agents[].provider/model`, `tool-subagent.agentOptions`); a preset",
        "# declares identity, tools and prompt, never a route. Each role's resolved model",
        "# is recorded below, and it is applied through the deployment default when every",
        "# role resolves to the same provider/model.",
        "",
    ]
    if agents:
        lines.append("- insert:")
    for order, agent in enumerate(sorted(agents, key=lambda a: a["name"]), start=1):
        spec = routes.get(agent["name"])
        if spec:
            lines.append(f"    # model: {spec}")
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        lines += [
            f"    - id: preset-{agent['name']}",
            f"      name: '{_DSH_PRESET_PLUGIN}'",
            "      config:",
            f"        id: {_yaml(agent['name'])}",
            f"      name: {_yaml(agent['name'])}",
            f"        description: {_yaml(description)}",
            f"        order: {order}",
            "        plugins:",
            "          - id: persona",
            f"            name: '{_DSH_PERSONA_PLUGIN}'",
            "            config:",
            "              prefix: |-",
            _yaml_block(_agent_body(agent), " " * 16),
            "          - id: agent-instructions",
            "            name: '@deepseek-ai/dsh-agent-instructions'",
            "            config:",
            f"              maxBytes: {_DSH_INSTRUCTION_BYTES}",
            "          - id: skill-filesystem",
            "            name: '@deepseek-ai/dsh-skill-filesystem'",
            "          - id: tool-skill",
            "            name: '@deepseek-ai/dsh-tool-skill'",
        ]

    uniform = _deepseek_uniform_route(routes)
    if uniform is not None:
        provider, model_id = uniform
        lines += [
            "",
            "# Every role resolves to the same route: apply it as the deployment default.",
            "- id: agent-default-model",
            "  name: '@deepseek-ai/dsh-agent-default-model'",
            "  config:",
            f"    provider: {_yaml(provider)}",
            f"    model: {_yaml(model_id)}",
        ]
    elif any(routes.values()):
        lines.append(
            "Roles resolve to different models. DSH 0.2.2-rc.3 has no per-preset model"
            " field, so the selection is recorded per role in `.dsh/se.patch.yml` and in"
            " this roster; DSH selects the route per session (or through"
            " `agent-loop.agents[]` / `tool-subagent.agentOptions`)."
        )
    else:
        lines.append(
            "No model is configured, so none is invented: select one with"
            " `se shema-ai model`, or declare `llm_config` on the agent contract."
        )
    return "\n".join(lines) + "\n"


def _deepseek_uniform_route(routes: dict[str, str | None]) -> tuple[str, str] | None:
    """The one route every agent resolves to, or None when they differ.

    A deployment default is a single process-wide route, so it is only written
    when writing it would not misroute anyone: every role must resolve to the
    same non-empty provider/model.
    """
    values = set(routes.values())
    if len(values) != 1:
        return None
    spec = values.pop()
    route = _deepseek_route(spec)
    if route is None or not route[0]:
        return None
    return route


def _deepseek_instructions(
    agents: list[dict], commands: list[dict], servers: dict, routes: dict[str, str | None]
) -> str:
    lines = [
        "# AGENTS",
        "",
        _DEEPSEEK_HEADER,
        "",
        "DSH reads project instructions from ``AGENTS.md``/``CLAUDE.md`` plus their",
        "``.local.md`` overlays, skills from ``<projectRoot>/.dsh/skills``, and agent",
        "presets only from Cordis patch lists — never a scanned preset directory. So",
        "the roles are rendered as a patch overlay the operator applies with",
        "``--patch``, and the instruction file uses the overlay name so it does not",
        "collide with the ``AGENTS.md`` the Codex adapter writes.",
        "",
        "## Roles",
        "",
    ]
    for agent in sorted(agents, key=lambda a: a["name"]):
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        spec = routes.get(agent["name"])
        model = f" (model: `{spec}`)" if spec else ""
        lines.append(f"- **{agent['name']}** — {description}{model}")
    lines += ["", "## Commands", ""]
    for command in sorted(commands, key=lambda c: c["name"]):
        description = (command.get("description") or command.get("purpose") or "").strip()
        lines.append(f"- **{command['name']}** — {description}")
    lines += [
        "",
        "## MCP servers",
        "",
        "DSH mounts MCP servers on the profile's ``mcp-manager`` row",
        "(`config.servers`); they are listed here for the operator.",
        "",
    ]
    for name in sorted(servers):
        lines.append(f"- `{name}`")
    lines += ["", "## Model selection", ""]
    uniform = _deepseek_uniform_route(routes)
    if uniform is not None:
        lines.append(
            f"Every role resolves to `{uniform[0]}/{uniform[1]}`, applied by"
            " `.dsh/se.patch.yml` as the `agent-default-model` deployment default."
        )
    elif any(routes.values()):
        lines.append(
            "Roles resolve to different models. DSH 0.2.2-rc.3 has no per-preset model"
            " field, so the selection is recorded per role in `.dsh/se.patch.yml` and in"
            " this roster; DSH selects the route per session (or through"
            " `agent-loop.agents[]` / `tool-subagent.agentOptions`)."
        )
    else:
        lines.append(
            "No model is configured, so none is invented: select one with"
            " `se shema-ai model`, or declare `llm_config` on the agent contract."
        )
    lines.append("")
    return "\n".join(lines)


def render_deepseek(root: Path) -> dict[str, str]:
    """Render the DeepSeek Harness layer (``.dsh/`` + ``AGENTS.local.md``).

    DSH reads project instructions from ``AGENTS.md``/``CLAUDE.md`` plus their
    ``.local.md`` overlays, skills from ``<projectRoot>/.dsh/skills``, and agent
    presets only from Cordis patch lists — never a scanned preset directory. So
    the roles are rendered as a patch overlay the operator applies with
    ``--patch``, and the instruction file uses the overlay name so it does not
    collide with the ``AGENTS.md`` the Codex adapter writes.
    """
    root = Path(root)
    agents = _load_agents(root)
    commands = _load_commands(root)
    routes = {agent["name"]: _model_for_agent(root, agent) for agent in agents}
    servers = mcp_entries(root)
    files: dict[str, str] = {}

    files["AGENTS.local.md"] = _deepseek_instructions(agents, commands, servers, routes)
    files[".dsh/se.patch.yml"] = _deepseek_patch(agents, routes)

    header = f"<!-- {_DEEPSEEK_HEADER} -->"
    for name, content in _load_skills(root).items():
        files[f".dsh/skills/{name}/SKILL.md"] = _deepseek_frontmatter(content, header)
    return files


def generate_deepseek(root, output, dry_run: bool = False) -> dict:
    files = render_deepseek(Path(root))
    return {
        "status": "PASS",
        "adapter": "deepseek",
        "output": str(output),
        "files": _write(Path(output), files, dry_run),
    }


def generate_claude_code(root, output, dry_run: bool = False) -> dict:
    files = render_claude_code(Path(root))
    return {
        "status": "PASS",
        "adapter": "claude-code",
        "output": str(output),
        "files": _write(Path(output), files, dry_run),
    }


def generate_codex(root, output, dry_run: bool = False) -> dict:
    files = render_codex(Path(root))
    return {
        "status": "PASS",
        "adapter": "codex",
        "output": str(output),
        "files": _write(Path(output), files, dry_run),
    }


def generate_all(root, output, dry_run: bool = False) -> dict:
    claude = generate_claude_code(root, output, dry_run)
    codex = generate_codex(root, output, dry_run)
    deepseek = generate_deepseek(root, output, dry_run)
    pi = generate_pi(root, output, dry_run)
    return {
        "status": "PASS",
        "adapter": "all",
        "output": str(output),
        "files": claude["files"] + codex["files"] + deepseek["files"] + pi["files"],
        "adapters": {"claude-code": claude, "codex": codex, "deepseek": deepseek, "pi": pi},
    }


def _pi_settings(project_root: Path) -> dict[str, Any]:
    """Generate Pi settings.json content."""
    root = Path(project_root)
    agents = _load_agents(root)
    commands = _load_commands(root)
    skills = _load_skills(root)
    servers = mcp_entries(root)

    # Resolve model for each agent
    routes = {agent["name"]: _model_for_agent(root, agent) for agent in agents}

    # Default model from first agent with a model, or None
    default_model = None
    for agent in agents:
        spec = _model_for_agent(Path("."), agent)
        if spec:
            provider, _, model_id = spec.partition("/")
            if not model_id:
                provider, model_id = "", provider
            break

    # Build tools list from skills
    tools = []
    for skill_name in skills:
        if skill_name != "impl-tdd":  # impl-tdd is a workflow, not a tool
            tools.append(f"skill:{skill_name}")

    # Add built-in tools
    tools.extend(["read", "write", "edit", "bash", "grep", "find", "ls"])

    settings = {
        "model": default_model or "nvidia/nemotron-3-ultra-550b-a55b",
        "tools": tools,
        "permissions": {
            "read": True,
            "write": True,
            "execute": True,
        },
        "mcpServers": {},
        "hooks": {},
        "env": {},
    }

    # Add MCP servers
    for name, spec in servers.items():
        settings["mcpServers"][name] = {
            "command": spec["command"],
            "args": spec.get("args", []),
            "env": spec.get("environment", {}),
        }

    return settings


def _pi_mcp_json(project_root: Path) -> str:
    """Generate .pi/mcp.json for Pi (Pi uses .pi/mcp.json)."""
    servers = mcp_entries(Path("."))
    entries = {}
    for name, spec in servers.items():
        entry = {"command": spec["command"], "args": spec.get("args", [])}
        if spec.get("environment"):
            entry["env"] = spec["environment"]
        entries[name] = entry
    return json.dumps({"mcpServers": entries}, indent=2, ensure_ascii=False) + "\n"


def _pi_agents_md(project_root: Path) -> str:
    """Generate AGENTS.md content for Pi."""
    root = Path(project_root)
    agents = _load_agents(root)
    commands = _load_commands(root)

    lines = [
        "# AGENTS",
        "",
        "Generated by `se adapter pi` from the canonical contracts.",
        "Generated output only; regenerate instead of editing.",
        "",
        "## Roles",
        "",
    ]
    for agent in sorted(agents, key=lambda a: a["name"]):
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        spec = resolve_agent_model(Path("."), agent.get("name"))
        model = f" (model: `{spec}`)" if spec else ""
        lines.append(f"- **{agent['name']}** — {description}{model}")

    lines += ["", "## Commands", ""]
    for command in sorted(commands, key=lambda c: c["name"]):
        description = (command.get("description") or command.get("purpose") or "").strip()
        lines.append(f"- **/{command['name']}** — {description}")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Pi
# --------------------------------------------------------------------------- #

_PI_HEADER = (
    "Generated by `se adapter pi` from the canonical contracts. "
    "Generated output only; regenerate instead of editing."
)

_PI_SETTINGS_HEADER = (
    "Generated by `se adapter pi` from the canonical contracts. "
    "Generated output only; regenerate instead of editing."
)

_PI_PRESET_PLUGIN = "@deepseek-ai/dsh-agent-preset"
_PI_PERSONA_PLUGIN = "@deepseek-ai/dsh-persona"
_PI_INSTRUCTION_BYTES = 65536


def _pi_frontmatter(content: str, header: str) -> str:
    """Place ``header`` after a leading YAML frontmatter block, if any.

    DSH parses a skill's frontmatter first, so provenance cannot go above it;
    inserting it directly after the closing fence keeps ``name`` and
    ``description`` at the top of the file while still marking the copy as
    generated output.
    """
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            cut = end + len("\n---\n")
            return content[:cut] + "\n" + header + "\n" + content[cut:]
    return header + "\n\n" + content


def _yaml_block(text: str, indent: str) -> str:
    """Render ``text`` as a literal YAML block scalar body at ``indent``."""
    lines = text.rstrip("\n").split("\n")
    return "\n".join(indent + line if line else "" for line in lines)


def _pi_route(spec: str | None) -> tuple[str, str] | None:
    """Split a ``provider/model`` spec into DSH's separate ``provider``/``model``."""
    if not spec:
        return None
    provider, _, model_id = spec.partition("/")
    if not model_id:
        provider, model_id = "", provider
    return provider, model_id


def _pi_patch(agents: list[dict], routes: dict[str, str | None]) -> str:
    """Compose the DSH profile patch overlay (``dsh --patch <file>``)."""
    lines = [
        f"# {_DEEPSEEK_HEADER}",
        "#",
        "# DSH applies a patch list after the profile layer, so this overlay is used as",
        "#   dsh --patch .dsh/se.patch.yml",
        "# or appended to $DSH_HOME/profiles/<profile>/cordis.patch.yml. It declares one",
        "# agent preset per SE role; the preset's persona carries the role contract.",
        "#",
        "# A DSH preset replaces the complete child plugin list, so this adapter renders",
        "# role instructions, the project instruction file and the SE skill surface. Add",
        "# the tool rows your deployment grants instead of expecting them here.",
        "#",
        "# DSH 0.2.2-rc.3 binds a model per agent only on launcher and delegation rows",
        "# (`agent-loop.agents[].provider/model`, `tool-subagent.agentOptions`); a preset",
        "# declares identity, tools and prompt, never a route. Each role's resolved model",
        "# is recorded below, and it is applied through the deployment default when every",
        "# role resolves to the same provider/model.",
        "",
    ]
    if agents:
        lines.append("- insert:")
    for order, agent in enumerate(sorted(agents, key=lambda a: a["name"]), start=1):
        spec = routes.get(agent["name"])
        if spec:
            lines.append(f"    # model: {spec}")
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        lines += [
            f"    - id: preset-{agent['name']}",
            f"      name: '{_DSH_PRESET_PLUGIN}'",
            "      config:",
            f"        id: {_yaml(agent['name'])}",
            f"      name: {_yaml(agent['name'])}",
            f"        description: {_yaml(description)}",
            f"        order: {order}",
            "        plugins:",
            "          - id: persona",
            f"            name: '{_DSH_PRESET_PLUGIN}'",
            "            config:",
            "              prefix: |-",
            _yaml_block(_agent_body(agent), " " * 16),
            "          - id: agent-instructions",
            "            name: '@deepseek-ai/dsh-agent-instructions'",
            "            config:",
            f"              maxBytes: {_PI_INSTRUCTION_BYTES}",
            "          - id: skill-filesystem",
            "            name: '@deepseek-ai/dsh-skill-filesystem'",
            "          - id: tool-skill",
            "            name: '@deepseek-ai/dsh-tool-skill'",
        ]

    uniform = _deepseek_uniform_route(routes)
    if uniform is not None:
        provider, model_id = uniform
        lines += [
            "",
            "# Every role resolves to the same route: apply it as the deployment default.",
            "- id: agent-default-model",
            "  name: '@deepseek-ai/dsh-agent-default-model'",
            "  config:",
            f"    provider: {_yaml(provider)}",
            f"    model: {_yaml(model_id)}",
        ]
    elif any(routes.values()):
        lines.append(
            "Roles resolve to different models. DSH 0.2.2-rc.3 has no per-preset model"
            " field, so the selection is recorded per role in `.dsh/se.patch.yml` and in"
            " this roster; DSH selects the route per session (or through"
            " `agent-loop.agents[]` / `tool-subagent.agentOptions`)."
        )
    else:
        lines.append(
            "No model is configured, so none is invented: select one with"
            " `se shema-ai model`, or declare `llm_config` on the agent contract."
        )
    return "\n".join(lines) + "\n"


def _pi_uniform_route(routes: dict[str, str | None]) -> tuple[str, str] | None:
    """The one route every agent resolves to, or None when they differ.

    A deployment default is a single process-wide route, so it is only written
    when writing it would not misroute anyone: every role must resolve to the
    same non-empty provider/model.
    """
    values = set(routes.values())
    if len(values) != 1:
        return None
    spec = values.pop()
    route = _deepseek_route(spec)
    if route is None or not route[0]:
        return None
    return route


def _pi_instructions(
    agents: list[dict], commands: list[dict], servers: dict, routes: dict[str, str | None]
) -> str:
    lines = [
        "# AGENTS",
        "",
        _DEEPSEEK_HEADER,
        "",
        "DSH reads project instructions from ``AGENTS.md``/``CLAUDE.md`` plus their",
        "`.local.md`` overlays, skills from ``<projectRoot>/.dsh/skills``, and agent",
        "presets only from Cordis patch lists — never a scanned preset directory. So",
        "the roles are rendered as a patch overlay the operator applies with",
        "``--patch``, and the instruction file uses the overlay name so it does not",
        "collide with the ``AGENTS.md`` the Codex adapter writes.",
        "",
        "## Roles",
        "",
    ]
    for agent in sorted(agents, key=lambda a: a["name"]):
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        spec = routes.get(agent["name"])
        model = f" (model: `{spec}`)" if spec else ""
        lines.append(f"- **{agent['name']}** — {description}{model}")
    lines += ["", "## Commands", ""]
    for command in sorted(commands, key=lambda c: c["name"]):
        description = (command.get("description") or command.get("purpose") or "").strip()
        lines.append(f"- **{command['name']}** — {description}")
    lines += [
        "",
        "## MCP servers",
        "",
        "DSH mounts MCP servers on the profile's ``mcp-manager`` row",
        "(`config.servers`); they are listed here for the operator.",
        "",
    ]
    for name in sorted(servers):
        lines.append(f"- `{name}`")
    lines += ["", "## Model selection", ""]
    uniform = _pi_uniform_route(routes)
    if uniform is not None:
        lines.append(
            f"Every role resolves to `{uniform[0]}/{uniform[1]}`, applied by"
            " `.dsh/se.patch.yml` as the `agent-default-model` deployment default."
        )
    elif any(routes.values()):
        lines.append(
            "Roles resolve to different models. DSH 0.2.2-rc.3 has no per-preset model"
            " field, so the selection is recorded per role in `.dsh/se.patch.yml` and in"
            " this roster; DSH selects the route per session (or through"
            " `agent-loop.agents[]` / `tool-subagent.agentOptions`)."
        )
    else:
        lines.append(
            "No model is configured, so none is invented: select one with"
            " `se shema-ai model`, or declare `llm_config` on the agent contract."
        )
    lines.append("")
    return "\n".join(lines)


def render_pi(root: Path) -> dict[str, str]:
    """Render the Pi layer (settings.json, .pi/mcp.json, skills).

    Pi reads AGENTS.md from the project root (generated by Codex adapter),
    so this adapter only generates Pi-specific files.
    """
    root = Path(root)
    files: dict[str, str] = {}

    # settings.json (Pi-specific settings)
    files["settings.json"] = json.dumps(_pi_settings(root), indent=2, ensure_ascii=False) + "\n"

    # .pi/mcp.json (Pi's MCP config location)
    files[".pi/mcp.json"] = _pi_mcp_json(root)

    # Skills
    for name, content in _load_skills(root).items():
        files[f".pi/skills/{name}/SKILL.md"] = content

    return files


def generate_pi(root, output, dry_run: bool = False) -> dict:
    from .runtimes import _write
    root = Path(root)
    files = render_pi(root)
    return {
        "status": "PASS",
        "adapter": "pi",
        "output": str(output),
        "files": _write(Path(output), files, dry_run),
    }


# --------------------------------------------------------------------------- #
# Hermes
# --------------------------------------------------------------------------- #

_HERMES_HEADER = (
    "Generated by `se adapter hermes` from the canonical contracts. "
    "Generated output only; regenerate instead of editing."
)


def _hermes_settings(project_root: Path) -> dict[str, Any]:
    """Generate Hermes settings.json content."""
    root = Path(project_root)
    agents = _load_agents(root)
    commands = _load_commands(root)
    skills = _load_skills(root)
    servers = mcp_entries(root)

    # Resolve model for each agent
    routes = {agent["name"]: _model_for_agent(root, agent) for agent in agents}

    # Default model from first agent with a model, or None
    default_model = None
    for agent in agents:
        spec = _model_for_agent(Path("."), agent)
        if spec:
            provider, _, model_id = spec.partition("/")
            if not model_id:
                provider, model_id = "", provider
            break

    # Build tools list from skills
    tools = []
    for skill_name in skills:
        if skill_name != "impl-tdd":  # impl-tdd is a workflow, not a tool
            tools.append(f"skill:{skill_name}")

    # Add built-in tools
    tools.extend(["read", "write", "edit", "bash", "grep", "find", "ls"])

    settings = {
        "model": default_model or "nvidia/nemotron-3-ultra-550b-a55b",
        "tools": tools,
        "permissions": {
            "read": True,
            "write": True,
            "execute": True,
        },
        "mcpServers": {},
        "hooks": {},
        "env": {},
    }

    # Add MCP servers
    for name, spec in servers.items():
        settings["mcpServers"][name] = {
            "command": spec["command"],
            "args": spec.get("args", []),
            "env": spec.get("environment", {}),
        }

    return settings


def _hermes_agents_md(project_root: Path) -> str:
    """Generate AGENTS.md content for Hermes."""
    root = Path(project_root)
    agents = _load_agents(root)
    commands = _load_commands(root)

    lines = [
        "# AGENTS",
        "",
        "Generated by `se adapter hermes` from the canonical contracts.",
        "Generated output only; regenerate instead of editing.",
        "",
        "## Roles",
        "",
    ]
    for agent in sorted(agents, key=lambda a: a["name"]):
        description = (agent.get("description") or agent.get("purpose") or "").strip()
        spec = resolve_agent_model(Path("."), agent["name"])
        model = f" (model: `{spec}`)" if spec else ""
        lines.append(f"- **{agent['name']}** — {description}{model}")

    lines += ["", "## Commands", ""]
    for command in sorted(commands, key=lambda c: c["name"]):
        description = (command.get("description") or command.get("purpose") or "").strip()
        lines.append(f"- **/{command['name']}** — {description}")

    return "\n".join(lines) + "\n"


def _hermes_mcp_json(project_root: Path) -> str:
    """Generate .hermes/mcp.json for Hermes (Hermes uses .hermes/mcp.json)."""
    servers = mcp_entries(Path("."))
    entries = {}
    for name, spec in servers.items():
        entry = {"command": spec["command"], "args": spec.get("args", [])}
        if spec.get("environment"):
            entry["env"] = spec["environment"]
        entries[name] = entry
    return json.dumps({"mcpServers": entries}, indent=2, ensure_ascii=False) + "\n"


def render_hermes(project_root: Path) -> dict[str, str]:
    """Render the Hermes layer (settings.json, AGENTS.md, .hermes/mcp.json, skills)."""
    root = Path(project_root)
    files: dict[str, str] = {}

    # settings.json (Hermes-specific settings)
    files["settings.json"] = json.dumps(_hermes_settings(root), indent=2, ensure_ascii=False) + "\n"

    # AGENTS.md (Hermes reads this for role definitions)
    files["AGENTS.md"] = _hermes_agents_md(root)

    # .hermes/mcp.json (Hermes's MCP config location)
    files[".hermes/mcp.json"] = _hermes_mcp_json(root)

    # Skills
    for name, content in _load_skills(root).items():
        files[f".hermes/skills/{name}/SKILL.md"] = content

    return files


def generate_hermes(root, output, dry_run: bool = False) -> dict:
    from .runtimes import _write
    root = Path(root)
    files = render_hermes(root)
    return {
        "status": "PASS",
        "adapter": "hermes",
        "output": str(output),
        "files": _write(Path(output), files, dry_run),
    }


def _hermes_model_for_agent(root: Path, agent: dict) -> str | None:
    """Resolve model for an agent, Hermes-specific."""
    # Try agent contract first
    contract = agent.get("llm_config") or {}
    if contract.get("model"):
        provider = str(contract.get("provider") or "").strip()
        model = str(contract["model"]).strip()
        return f"{provider}/{model}" if provider and "/" not in model else model

    # Fall back to harness selection
    try:
        from .model_tui.config import resolve_agent_model
        return resolve_agent_model(Path("."), agent.get("name") or "")
    except Exception:
        return None