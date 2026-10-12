"""Runtime adapters beyond OpenCode: Claude Code and Codex.

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
    resolve_python_interpreter,
    resolved_server_spec,
)


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
    interpreter = resolve_python_interpreter()
    project_id = read_project_id(project)
    entries = {}
    for template in load_mcp_templates(root):
        spec = resolved_server_spec(
            template,
            se_root=root,
            project=project,
            project_id=project_id,
            interpreter=interpreter,
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
    for item in agent.get("restrictions", []) or ["- none declared"]:
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
    return {
        "status": "PASS",
        "adapter": "all",
        "output": str(output),
        "files": claude["files"] + codex["files"],
        "adapters": {"claude-code": claude, "codex": codex},
    }
