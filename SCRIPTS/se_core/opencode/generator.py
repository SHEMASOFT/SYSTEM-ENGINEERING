"""Generation engine for the OpenCode adapter.

``generate`` reads canonical contracts, validates them against the contract layer,
builds the OpenCode artifacts in memory, and (unless ``dry_run``) writes them to the
output directory. Generation never writes inside a ``PROJECTS`` path segment.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from ..paths import load_json, repo_root, tree_fingerprint
from ..schemas import load_schemas, validate
from . import mappings
from .validators import audit_contracts, validate_generated_config, validate_skill

from ..capabilities import capability_plan_view

FORBIDDEN_SEGMENTS = {"projects"}

def _atomic_write_text(dest: Path, content: str) -> None:
    """Write ``content`` to ``dest`` so readers never observe a partial file.

    Truncate-and-write leaves a window where the file exists with zero or partial
    bytes, which concurrent readers observe as JSONDecodeError ("line 1 column 1") or
    FileNotFoundError. Writing a sibling temp file and ``os.replace``-ing it publishes
    the complete content atomically, so a concurrent reader sees either the previous
    file or the new one, never an intermediate state.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(dest.parent), prefix=dest.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _guard_output(output: Path) -> None:
    """Reject output directories that would write inside a PROJECTS workspace."""
    output = Path(output)
    if any(part.lower() in FORBIDDEN_SEGMENTS for part in output.parts):
        raise ValueError(
            f"refusing to write into a PROJECTS path segment: {output}"
        )


def _build_plan(root: Path, schemas, errors, counts):
    """Return (planned_files, output_artifacts, generated_files, input_sources)."""
    root = Path(root)
    agents = []
    for path in sorted((root / "AGENTS").glob("*/agent.json")):
        data = load_json(path)
        agents.append(data)
        role = data["name"]
    planned = {}
    for agent in sorted(agents, key=lambda a: a["name"]):
        planned[f"{mappings.AGENT_DIR}/{agent['name']}.md"] = mappings.build_agent_markdown(
            agent, agent["name"]
        )
    for command in load_json(root / "COMMANDS" / "commands.json")["commands"]:
        planned[f"{mappings.COMMAND_DIR}/{command['name']}.md"] = mappings.build_command_markdown(
            command
        )
    for path in sorted((root / "SKILLS").glob("*/SKILL.md")):
        name = path.parent.name
        planned[f"{mappings.SKILL_DIR}/{name}/SKILL.md"] = path.read_text(encoding="utf-8")

    # Policy files (canonical governance, copied verbatim)
    policies_dir = root / "POLICIES"
    if policies_dir.exists():
        for path in sorted(policies_dir.glob("*.md")):
            planned[f"policies/{path.name}"] = path.read_text(encoding="utf-8")

    # MCP configuration files
    mcp_dir = root / "TEMPLATES" / "mcp"
    if mcp_dir.exists():
        for path in sorted(mcp_dir.glob("*.json.tmpl")):
            # Host paths stay as ${SE_ROOT} / ${SE_PROJECT_ROOT} placeholders so the
            # generated config is portable across machines. The runtime expands them.
            # The canonical adapter has no project id; use the system directory name.
            content = path.read_text(encoding="utf-8").replace("{{project_id}}", root.name)
            planned[f"mcp/{path.name.replace('.tmpl', '')}"] = content

    agents_doc = mappings.build_agents_doc(agents)
    planned[mappings.AGENTS_DOC] = agents_doc

    input_sources = {
        "agents": "AGENTS/*/agent.json",
        "commands": "COMMANDS/commands.json",
        "skills": "SKILLS/*/SKILL.md",
        "policies": "POLICIES/*.md",
        "mcp": "TEMPLATES/mcp/*.json.tmpl",
    }
    generated_files = list(planned)
    output_artifacts = [
        {"type": "agent", "path": f".opencode/{mappings.AGENT_DIR}/{a['name']}.md",
         "format": "markdown", "description": a.get("description") or a.get("purpose", "")}
        for a in sorted(agents, key=lambda a: a["name"])
    ]
    output_artifacts += [
        {"type": "command", "path": f".opencode/{mappings.COMMAND_DIR}/{c['name']}.md",
         "format": "markdown", "description": c.get("description") or c.get("purpose", "")}
        for c in load_json(root / "COMMANDS" / "commands.json")["commands"]
    ]
    for path in sorted((root / "SKILLS").glob("*/SKILL.md")):
        output_artifacts.append(
            {"type": "skill", "path": f".opencode/{mappings.SKILL_DIR}/{path.parent.name}/SKILL.md",
             "format": "markdown", "description": f"Skill {path.parent.name}"}
        )
    policies_dir = root / "POLICIES"
    if policies_dir.exists():
        for path in sorted(policies_dir.glob("*.md")):
            output_artifacts.append(
                {"type": "policy", "path": f".opencode/policies/{path.name}",
                 "format": "markdown", "description": f"Policy {path.stem}"}
            )
    output_artifacts += [
        {"type": "config", "path": ".opencode/adapter-manifest.json", "format": "json",
         "description": "OpenCode adapter output manifest"},
        {"type": "docs", "path": ".opencode/AGENTS.md", "format": "markdown",
         "description": "Generated agent/command overview"},
    ]
    # MCP config artifacts
    mcp_dir = root / "TEMPLATES" / "mcp"
    if mcp_dir.exists():
        for path in sorted(mcp_dir.glob("*.json.tmpl")):
            name = path.name.replace('.json.tmpl', '')
            output_artifacts.append(
                {"type": "mcp", "path": f".opencode/mcp/{name}.json", "format": "json",
                 "description": f"MCP {name} configuration"}
            )
    return planned, output_artifacts, generated_files, input_sources, agents


def _compute_hashes(planned: dict) -> dict:
    return {
        rel: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for rel, content in planned.items()
    }


def _build_config(root: Path, planned, output_artifacts, generated_files, input_sources,
                  counts, master_version):
    hashes = _compute_hashes(planned)
    config = mappings.build_config(
        input_sources,
        output_artifacts,
        generated_files,
        counts,
        master_version,
        metadata={"content_hashes": hashes},
        capability_plan=capability_plan_view(root),
    )
    return config


def generate(root: Path | str, output: Path | str, dry_run: bool = False) -> dict:
    """Generate OpenCode artifacts from canonical contracts.

    Returns a dict with ``status`` ("PASS" or "FAIL"), counts, ``files`` (list of
    {path, action}) and optionally ``errors``. Never writes when ``dry_run``.
    """
    root = Path(root)
    output = Path(output)
    _guard_output(output)

    schemas = load_schemas(root)
    errors, counts = audit_contracts(root, schemas)
    base = {
        "root": str(root),
        "output": str(output),
        "dry_run": bool(dry_run),
        "counts": counts,
        "status": "PASS",
        "files": [],
    }
    if errors:
        base["status"] = "FAIL"
        base["errors"] = errors[:20]
        return base

    planned, output_artifacts, generated_files, input_sources, _agents = _build_plan(
        root, schemas, errors, counts
    )
    master_version = load_json(root / "SYSTEM.json").get("master_system_version", "0")
    config = _build_config(
        root, planned, output_artifacts, generated_files, input_sources, counts,
        master_version,
    )
    config_text = mappings.build_config_markdown(config)
    planned[mappings.ADAPTER_MANIFEST] = config_text

    config_errors = validate_generated_config(config, schemas)
    if config_errors:
        base["status"] = "FAIL"
        base["errors"] = [mappings.ADAPTER_MANIFEST + ": " + message for message in config_errors][:20]
        return base

    files = []
    for rel in sorted(planned):
        dest = output / rel
        existed = dest.exists()
        unchanged = existed and dest.read_bytes() == planned[rel].encode("utf-8")
        action = "unchanged" if unchanged else ("overwrite" if existed else "write")
        files.append({"path": rel, "action": action, "bytes": len(planned[rel].encode("utf-8"))})
        if not dry_run:
            _atomic_write_text(dest, planned[rel])

    base["files"] = files
    base["config"] = {
        "adapter_id": config["adapter_id"],
        "adapter_version": config["adapter_version"],
        "generated_files": len(generated_files) + 2,
    }
    return base


def generate_default_output(root=None, dry_run: bool = False) -> dict:
    """Generate into the default location (``<repo>/.opencode``)."""
    root = Path(root) if root else repo_root()
    return generate(root, root / ".opencode", dry_run=dry_run)


def _write_all(output: Path, entries: list, dry_run: bool) -> list:
    """Write ``(relative_path, content)`` entries with LF endings. Returns file list."""
    files = []
    for rel, content in entries:
        dest = output / rel
        existed = dest.exists()
        unchanged = existed and dest.read_bytes() == content.encode("utf-8")
        action = "unchanged" if unchanged else ("overwrite" if existed else "write")
        files.append({"path": rel, "action": action, "bytes": len(content.encode("utf-8"))})
        if not dry_run:
            _atomic_write_text(dest, content)
    return files


def generate_project(
    root: Path | str,
    project_dir: Path | str,
    project_data: dict,
    agents: list | None = None,
    skills: list | None = None,
    dry_run: bool = False,
) -> dict:
    """Generate a project's OpenCode layer from canonical contracts.

    Only the ``agents`` requested (or ``project_data["required_agents"]``) and the
    ``skills`` requested (or ``project_data["inherited_skills"]``) are installed; all
    canonical commands are installed. Output layout (relative to ``project_dir``):

        AGENTS.md  adapter-manifest.json  MASTER-SYSTEM-MANIFEST.json  .opencode/{agents,commands,skills}

    Deterministic (fixed order, no timestamps, LF) and idempotent. Never deletes files
    and never touches anything outside the generated names. This is the explicit
    project-distribution path; it is not blocked by the repository ``PROJECTS`` guard.
    """
    root = Path(root)
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    schemas = load_schemas(root)
    errors, counts = audit_contracts(root, schemas)
    base = {
        "root": str(root),
        "output": str(project_dir),
        "dry_run": bool(dry_run),
        "counts": counts,
        "status": "PASS",
        "files": [],
    }
    if errors:
        base["status"] = "FAIL"
        base["errors"] = errors[:20]
        return base

    configured_agents = agents if agents is not None else (project_data.get("required_agents") or [])
    configured_skills = skills if skills is not None else (project_data.get("inherited_skills") or [])
    selected_agents = sorted({str(a) for a in (configured_agents or []) if a})
    selected_skills = sorted({str(s) for s in (configured_skills or []) if s})

    agents_by_name = {}
    for path in sorted((root / "AGENTS").glob("*/agent.json")):
        data = load_json(path)
        agents_by_name[data["name"]] = data
    missing_agents = [n for n in selected_agents if n not in agents_by_name]
    if missing_agents:
        available = ", ".join(sorted(agents_by_name))
        base["status"] = "FAIL"
        base["errors"] = [f"unknown agent(s): {', '.join(missing_agents)}; available: {available}"]
        return base

    skill_files = {path.parent.name: path for path in (root / "SKILLS").glob("*/SKILL.md")}
    missing_skills = [n for n in selected_skills if n not in skill_files]
    if missing_skills:
        available = ", ".join(sorted(skill_files)) or "(none)"
        base["status"] = "FAIL"
        base["errors"] = [f"unknown skill(s): {', '.join(missing_skills)}; available: {available}"]
        return base
    skill_errors = []
    for name in selected_skills:
        skill_errors.extend(validate_skill(skill_files[name], name))
    if skill_errors:
        base["status"] = "FAIL"
        base["errors"] = skill_errors[:20]
        return base

    commands = load_json(root / "COMMANDS" / "commands.json")["commands"]

    planned = {}
    for agent in sorted(selected_agents):
        planned[f"{mappings.AGENT_DIR}/{agent}.md"] = mappings.build_agent_markdown(
            agents_by_name[agent], agent
        )
    for command in commands:
        planned[f"{mappings.COMMAND_DIR}/{command['name']}.md"] = mappings.build_command_markdown(
            command
        )
    for name in selected_skills:
        planned[f"{mappings.SKILL_DIR}/{name}/SKILL.md"] = skill_files[name].read_text(
            encoding="utf-8"
        )

    # MCP configuration files: only the project id is substituted; host paths stay
    # as ${SE_ROOT} / ${SE_PROJECT_ROOT} placeholders so the output is portable.
    mcp_dir = root / "TEMPLATES" / "mcp"
    if mcp_dir.exists():
        for path in sorted(mcp_dir.glob("*.json.tmpl")):
            name = path.name.replace('.json.tmpl', '')
            template = path.read_text(encoding="utf-8")
            content = template.replace("{{project_id}}", project_data.get("project_id", "{{project_id}}"))
            planned[f"mcp/{name}.json"] = content

    project_agents = [agents_by_name[n] for n in selected_agents]
    project_name = str(project_data.get("name") or "")
    agents_doc_text = mappings.build_project_agents_doc(
        project_agents, commands, project_name
    )
    planned_hashes = _compute_hashes(planned)

    output_artifacts = [
        {"type": "agent", "path": f".opencode/{mappings.AGENT_DIR}/{a['name']}.md",
         "format": "markdown", "description": a.get("description") or a.get("purpose", "")}
        for a in sorted(project_agents, key=lambda a: a["name"])
    ]
    output_artifacts += [
        {"type": "command", "path": f".opencode/{mappings.COMMAND_DIR}/{c['name']}.md",
         "format": "markdown", "description": c.get("description") or c.get("purpose", "")}
        for c in commands
    ]
    for name in selected_skills:
        output_artifacts.append(
            {"type": "skill", "path": f".opencode/{mappings.SKILL_DIR}/{name}/SKILL.md",
             "format": "markdown", "description": f"Skill {name}"}
        )

    # MCP config artifacts
    mcp_dir = root / "TEMPLATES" / "mcp"
    if mcp_dir.exists():
        for path in sorted(mcp_dir.glob("*.json.tmpl")):
            name = path.name.replace('.json.tmpl', '')
            output_artifacts.append(
                {"type": "mcp", "path": f".opencode/mcp/{name}.json", "format": "json",
                 "description": f"MCP {name} configuration"}
            )

    input_sources = {
        "agents": "AGENTS/*/agent.json",
        "commands": "COMMANDS/commands.json",
        "skills": "SKILLS/*/SKILL.md",
        "policies": "POLICIES/*.md",
        "mcp": "TEMPLATES/mcp/*.json.tmpl",
    }
    subset_counts = {
        "agents": len(selected_agents),
        "commands": len(commands),
        "skills": len(selected_skills),
        "policies": counts["policies"],
    }
    master_version = load_json(root / "SYSTEM.json").get("master_system_version", "0")
    config = mappings.build_config(
        input_sources,
        output_artifacts,
        list(planned),
        subset_counts,
        master_version,
        metadata={"content_hashes": planned_hashes},
        capability_plan=capability_plan_view(root),
    )
    config_text = mappings.build_config_markdown(config)
    config_errors = validate_generated_config(config, schemas)
    if config_errors:
        base["status"] = "FAIL"
        base["errors"] = [mappings.ADAPTER_MANIFEST + ": " + message for message in config_errors][:20]
        return base

    project_context = {
        "project_id": project_data.get("project_id"),
        "master_system_version": project_data.get("master_system_version"),
        "domains": project_data.get("domains", []),
        "required_agents": project_data.get("required_agents", []),
        "inherited_skills": project_data.get("inherited_skills", []),
    }
    files_hashes = {".opencode/" + rel: digest for rel, digest in planned_hashes.items()}
    files_hashes["AGENTS.md"] = hashlib.sha256(agents_doc_text.encode("utf-8")).hexdigest()
    files_hashes[mappings.ADAPTER_MANIFEST] = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
    selections = {
        "agents": [a["name"] for a in project_agents],
        "commands": [c["name"] for c in commands],
        "skills": selected_skills,
    }
    manifest = mappings.build_installation_manifest(
        project_id=project_data.get("project_id"),
        master_version=master_version,
        selections=selections,
        files_hashes=files_hashes,
        counts=subset_counts,
        project_context=project_context,
        metadata={"distributed_at_version": master_version},
    )
    manifest_text = mappings.build_config_markdown(manifest)
    manifest_errors = validate(manifest, schemas["installation_manifest"])
    if manifest_errors:
        base["status"] = "FAIL"
        base["errors"] = ["MASTER-SYSTEM-MANIFEST.json: " + message for message in manifest_errors][:20]
        return base

    root_entries = [
        (mappings.AGENTS_DOC, agents_doc_text),
        (mappings.ADAPTER_MANIFEST, config_text),
        (mappings.INSTALLATION_FILE, manifest_text),
    ]
    oc_entries = sorted(planned.items())
    opencode_dir = project_dir / ".opencode"

    files = []
    if not dry_run:
        for subdir in (mappings.AGENT_DIR, mappings.COMMAND_DIR, mappings.SKILL_DIR, "mcp"):
            (opencode_dir / subdir).mkdir(parents=True, exist_ok=True)
    for rel, content in oc_entries:
        files += _write_all(opencode_dir, [(rel, content)], dry_run)
    files += _write_all(project_dir, root_entries, dry_run)

    base["counts"] = subset_counts
    base["files"] = files
    base["config"] = {
        "adapter_id": config["adapter_id"],
        "adapter_version": config["adapter_version"],
        "generated_files": len(manifest["files"]),
    }
    return base