"""Mapping helpers: canonical contracts -> OpenCode artifact content.

Every builder is deterministic (fixed key order, no timestamps) so generated
files are byte-identical across runs (idempotence is tested in FASE 5).
"""

from __future__ import annotations

import json

AGENT_DIR = "agents"
COMMAND_DIR = "commands"
SKILL_DIR = "skills"
AGENTS_DOC = "AGENTS.md"
ADAPTER_MANIFEST = "adapter-manifest.json"

# OpenCode V2 discovers agents in ``agents/`` (plural); the legacy singular
# ``agent/`` is not a V2 discovery path. Exactly one spelling is emitted so a
# tree can never register the same artifact twice.
#
# ``shema-ai-coordinador`` is the SE orchestrator, so it is the role offered as the
# selectable primary agent; every other role runs as a subagent launched by the
# primary agent or by a command's ``agent:`` frontmatter.
PRIMARY_AGENTS = frozenset({"shema-ai-coordinador"})
_MODE_PRIMARY = "primary"
_MODE_SUBAGENT = "subagent"


def agent_mode(role: str) -> str:
    """Return the OpenCode ``mode`` for an SE role."""
    return _MODE_PRIMARY if role in PRIMARY_AGENTS else _MODE_SUBAGENT


# The contract's provider vocabulary predates OpenCode's provider IDs. ``free``
# models are served through OpenRouter and local models through Ollama, so the
# adapter maps those two aliases; every other value is already a provider ID.
_PROVIDER_ALIASES = {"free": "openrouter", "local": "ollama"}


def agent_model(agent: dict) -> str:
    """Return the OpenCode ``model`` string for an agent contract.

    OpenCode wants ``provider/model-id``. Contracts may either write the fully
    qualified model (for example ``deepseek/deepseek-r1:free``) or split it into
    ``provider`` and ``model``. Empty/invalid configs render no ``model`` line.
    """
    llm = agent.get("llm_config")
    if not isinstance(llm, dict):
        return ""
    model = str(llm.get("model") or "").strip()
    if not model:
        return ""
    provider = str(llm.get("provider") or "").strip().lower()
    if provider and "/" not in model:
        provider = _PROVIDER_ALIASES.get(provider, provider)
        return f"{provider}/{model}"
    return model


def agent_temperature(agent: dict) -> float | None:
    """Return a valid temperature from ``llm_config``, if one is declared."""
    llm = agent.get("llm_config")
    if not isinstance(llm, dict):
        return None
    value = llm.get("temperature")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if 0 <= value <= 2:
        return float(value)
    return None


def _yaml_scalar(value: str) -> str:
    """Render a string as a safe YAML scalar (quoted when necessary)."""
    needs_quote = (
        not value
        or value != value.strip()
        or any(char in value for char in (":", "#", "{", "}", "[", "]", "'", '"', "\\"))
    )
    if needs_quote:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _bullet(items) -> str:
    return "\n".join(f"- {item}" for item in items)


def build_agent_markdown(agent: dict, role: str) -> str:
    """Serialize an agent contract to ``agents/<role>.md``."""
    # Derive display name from description (text before first colon) or fallback to role
    description = agent.get('description') or agent.get('purpose', '')
    display_name = description.split(':')[0].strip() if ':' in description else role.replace('-', ' ').title()
    
    frontmatter = [
        "---",
        f"description: {_yaml_scalar(agent.get('description') or agent.get('purpose', ''))}",
    ]
    model = agent_model(agent)
    if model:
        frontmatter.append(f"model: {_yaml_scalar(model)}")
    temperature = agent_temperature(agent)
    if temperature is not None:
        frontmatter.append(f"temperature: {temperature:g}")
    frontmatter += [
        f"mode: {agent_mode(role)}",
        f"name: {_yaml_scalar(display_name)}",
        "---",
    ]
    lines = frontmatter + [
        "",
        f"# {display_name}",
        "",
        f"- **id**: {agent.get('id')}",
        f"- **version**: {agent.get('version')}",
        f"- **purpose**: {agent.get('purpose', '')}",
        f"- **gates**: {', '.join(agent.get('gate_responsibility', []))}",
        f"- **lifecycle**: {agent.get('lifecycle', {}).get('status', '')}",
        "",
        "## Capabilities",
        "",
    ]
    for cap in agent.get("capabilities", []):
        cap_name = cap.get("name", "")
        lines.append(f"- **{cap_name}** — {cap.get('description', '')}")
    lines += ["", "## Required capabilities", ""]
    required = sorted(agent.get("capability_requires") or [])
    if required:
        for cid in required:
            lines.append(f"- `{cid}`")
    else:
        lines.append("- _none declared_")
    lines += ["", "## Restrictions", ""]
    lines.append(_bullet(agent.get("restrictions", [])))
    lines += ["", "## Permissions", "", _bullet(sorted(agent.get("permissions", [])))]
    lines += ["", "## Verification requirements", ""]
    lines.append(_bullet(agent.get("verification_requirements", [])))
    delegation = agent.get("delegation_instructions") or []
    if delegation:
        lines += ["", "## Delegation", ""]
        lines.append(_bullet(delegation))
    communication = agent.get("communication_preferences") or []
    if communication:
        lines += ["", "## Communication", ""]
        lines.append(_bullet(communication))
    lines.append("")
    return "\n".join(lines)


def _project_flag_on_subcommands(command: dict) -> bool:
    """Whether the CLI declares ``--project`` on the subcommands, not at top level.

    Commands whose contract declares a required ``subcommand`` argument take
    ``--project`` on each subcommand, so the default
    ``se <name> --project $ARGUMENTS`` template is not a valid invocation:
    argparse reads the project path as the subcommand and exits with code 2
    (``invalid choice``). Verified for CMD-0019 (handoff) and CMD-0024
    (orchestrate).
    """
    return any(arg.get("name") == "subcommand" for arg in command.get("arguments", []))


def build_command_markdown(command: dict) -> str:
    """Serialize a command contract to ``commands/<name>.md``."""
    name = command["name"]
    args = command.get("arguments", [])
    # Caller supplies the subcommand and its own --project flag.
    execution = (
        f"se {name} $ARGUMENTS" if _project_flag_on_subcommands(command)
        else f"se {name} --project $ARGUMENTS"
    )
    lines = [
        "---",
        f"description: {_yaml_scalar(command.get('description') or command.get('purpose', ''))}",
        f"agent: {command.get('agent') or command.get('primary_agent')}",
        "---",
        "",
        f"# {name}",
        "",
        f"- **id**: {command.get('id')}",
        f"- **version**: {command.get('version')}",
        f"- **purpose**: {command.get('purpose', '')}",
        f"- **execution_intent**: {command.get('execution_intent')}",
        f"- **risk_level**: {command.get('risk_level')}",
        f"- **gate**: {command.get('gate')}",
        f"- **permissions**: {', '.join(command.get('permissions', []))}",
        "",
        "## Execution",
        "",
        execution,
        "",
        "## Arguments",
        "",
    ]
    if args:
        for arg in args:
            required = "required" if arg.get("required") else "optional"
            lines.append(
                f"- `{arg.get('name')}` ({arg.get('type')}, {required}) — {arg.get('description', '')}"
            )
    else:
        lines.append("- _no arguments_")
    lines.append("")
    return "\n".join(lines)


def build_agents_doc(agents: list) -> str:
    """Serialize the generated ``AGENTS.md`` overview."""
    lines = [
        "# AGENTS",
        "",
        "Generated by `se adapter opencode` from canonical contracts "
        "(`AGENTS/*/agent.json`, `COMMANDS/commands.json`). Generated output only; "
        "do not edit by hand — regenerate instead.",
        "",
        "## Roles",
        "",
    ]
    for agent in sorted(agents, key=lambda a: a["name"]):
        lines.append(f"- **{agent['name']}** — {agent.get('description') or agent.get('purpose', '')}")
    lines.append("")
    return "\n".join(lines)


def build_project_agents_doc(agents: list, commands: list, project_name: str = "") -> str:
    """Serialize the project ``AGENTS.md`` (installed subset + installed commands)."""
    lines = [
        "# AGENTS",
        "",
        "Generated by `se init` from canonical contracts "
        "(`AGENTS/*/agent.json`, `COMMANDS/commands.json`). Generated output only; "
        "do not edit by hand — regenerate with `se init <project>` instead.",
        "",
        f"- **project**: {project_name}" if project_name else "- **project**: _unnamed_",
        "- **scope**: only the agents and skills declared by the project are installed",
        "",
        "## Roles",
        "",
    ]
    if agents:
        for agent in sorted(agents, key=lambda a: a["name"]):
            payload = agent.get("id", "") + " — " + (agent.get("description") or agent.get("purpose", ""))
            lines.append(f"- **{agent['name']}** {payload}")
    else:
        lines.append("- _no agents installed_")
    lines += ["", "## Commands", ""]
    if commands:
        for command in sorted(commands, key=lambda c: c["name"]):
            explicit = command.get("agent") or command.get("primary_agent") or ""
            lines.append(
                f"- **{command['name']}** — {command.get('description') or command.get('purpose', '')}"
                + (f" (agent: {explicit})" if explicit else "")
            )
    else:
        lines.append("- _no commands installed_")
    lines.append("")
    return "\n".join(lines)


def build_config(
    input_sources: dict,
    output_artifacts: list,
    generated_files: list,
    counts: dict,
    master_version: str,
    metadata: dict | None = None,
    capability_plan: dict | None = None,
) -> dict:
    """Build the output manifest conforming to ``SCHEMAS/adapter-manifest.schema.json``.

    ``capability_plan`` (CP-020) is optional and, when provided, exposes the
    capability registry view to the runtime as an auditable contract.
    """
    config_metadata = {"generator": "se_core.opencode", "counts": counts}
    if metadata:
        config_metadata.update(metadata)
    manifest = {
        "schema_version": "1",
        "adapter_id": "opencode",
        "adapter_version": master_version,
        "target": "opencode",
        "engine_version": master_version,
        "input": input_sources,
        "output": {
            "artifacts": output_artifacts,
            "generated_files": sorted(generated_files),
            "validation": {
                "enabled": True,
                "strategy": "content-hash",
                "schema_version": "1",
            },
        },
        "capabilities": {
            "agents": "SUPPORTED",
            "commands": "SUPPORTED",
            "skills": "SUPPORTED",
            "policies": "PARTIAL",
            "workflows": "UNSUPPORTED",
        },
        "metadata": config_metadata,
    }
    if capability_plan is not None:
        manifest["capability_plan"] = capability_plan
    return manifest


def build_config_markdown(config: dict) -> str:
    """Serialize the output manifest to text (deterministic JSON)."""
    return json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


INSTALLATION_FILE = "MASTER-SYSTEM-MANIFEST.json"


def build_installation_manifest(
    project_id: str,
    master_version: str,
    selections: dict,
    files_hashes: dict,
    counts: dict,
    project_context: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build the installation manifest conforming to
    ``SCHEMAS/installation-manifest.schema.json`` (deterministic JSON)."""
    manifest = {
        "schema_version": "1",
        "project_id": project_id,
        "distributor": "se init",
        "master_system_version": master_version,
        "adapter_id": "opencode",
        "installed": {
            "agents": sorted(selections.get("agents", [])),
            "commands": sorted(selections.get("commands", [])),
            "skills": sorted(selections.get("skills", [])),
        },
        "files": dict(sorted(files_hashes.items())),
        "validation": {
            "enabled": True,
            "strategy": "content-hash",
            "schema_version": "1",
        },
        "metadata": {"generator": "se_core.opencode", "counts": counts},
    }
    if project_context is not None:
        manifest["project_context"] = {
            "project_id": project_context.get("project_id"),
            "master_system_version": project_context.get("master_system_version"),
            "domains": sorted(project_context.get("domains", []) or []),
            "required_agents": sorted(project_context.get("required_agents", []) or []),
            "inherited_skills": sorted(project_context.get("inherited_skills", []) or []),
        }
    if metadata:
        manifest["metadata"].update(metadata)
    return manifest