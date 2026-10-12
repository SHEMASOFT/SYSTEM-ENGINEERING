"""Validators for the OpenCode adapter: contract inputs and generated output.

Two audit layers:

* :func:`audit_contracts` - canon inputs (agents, commands, skills) for AUTO-07.
* :func:`audit_adapter` - a generated/deployed adapter tree for AUTO-08.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from ..capabilities import available_capabilities, known_providers
from ..paths import load_json, repo_root, tree_fingerprint
from ..schemas import load_schemas, validate
from .mappings import ADAPTER_MANIFEST, AGENT_DIR, AGENTS_DOC, COMMAND_DIR, SKILL_DIR

SKILL_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*(?=\n|$)", re.DOTALL)
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")

# Skill ID pattern from the contract
SKILL_ID_RE = re.compile(r"^SK-\d{4}$")
# Skill name pattern (lowercase alphanumeric with hyphens)
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

REQUIRED_SECTIONS = [
    "purpose",
    "when_to_use",
    "when_not_to_use",
    "inputs",
    "preconditions",
    "procedure",
    "evidence",
    "validation",
    "failure_modes",
    "outputs",
    "restrictions",
]

# Valid skill kinds from the contract
VALID_SKILL_KINDS = {"knowledge", "behavioral", "workflow"}

# Valid OpenCode compatibility values
VALID_COMPATIBILITY = {"opencode", "claude-code", "cursor", "vscode", "other"}

# Standard resource directories per skill authoring guide
STANDARD_RESOURCE_DIRS = {"scripts", "references", "assets"}


def parse_frontmatter(text: str):
    """Return a dict of frontmatter keys or ``None`` if no frontmatter block.
    
    Tries YAML first (handles nested objects), falls back to line-by-line
    parser that handles unquoted colons in values and nested metadata.
    """
    match = SKILL_FRONTMATTER_RE.match(text)
    if not match:
        return None
    frontmatter_content = match.group(1)
    
    # Try YAML first (handles nested objects correctly)
    if HAS_YAML:
        try:
            result = yaml.safe_load(frontmatter_content)
            if result is not None:
                return result
        except Exception:
            pass  # Fall through to fallback
    
    # Fallback: simple line-by-line parser that handles unquoted colons in values
    # and attempts to reconstruct nested metadata structure
    lines = frontmatter_content.splitlines()
    front = {}
    i = 0
    total_lines = len(lines)
    while i < total_lines:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"')
            # Check if this key has nested content (indented lines following)
            if not value and i + 1 < total_lines:
                # Check if next lines are indented (nested content)
                nested = {}
                for j in range(i + 1, total_lines):
                    next_line = lines[j]
                    next_stripped = next_line.lstrip()
                    # Check if line is indented (starts with whitespace)
                    if next_line and (next_line.startswith("  ") or next_line.startswith("\t")):
                        if ":" in next_line.lstrip():
                            nk, nv = next_line.lstrip().split(":", 1)
                            nested[nk.strip()] = nv.strip().strip('"')
                        else:
                            break
                    else:
                        break
                if nested:
                    front[key.strip()] = nested
                else:
                    front[key.strip()] = value.strip().strip('"')
            else:
                front[key.strip()] = value.strip().strip('"')
        i += 1
    return front or None


def _validate_metadata_structure(metadata, skill_name: str) -> list:
    """Validate that metadata is a string-to-string map."""
    errors = []
    if not isinstance(metadata, dict):
        errors.append(f"skill {skill_name}: metadata must be an object")
        return errors
    for key, value in metadata.items():
        if not isinstance(key, str):
            errors.append(f"skill {skill_name}: metadata keys must be strings")
        if not isinstance(value, str):
            errors.append(f"skill {skill_name}: metadata values must be strings (key: {key})")
    return errors


def _validate_resource_directories(skill_dir: Path, skill_name: str) -> list:
    """Return errors for standard resource directories that exist but are not directories.

    Absence is not an error: ``scripts/``, ``references/`` and ``assets/`` are
    optional in the contract, and ``audit_contracts`` has no warning channel.
    """
    errors = []
    for dir_name in sorted(STANDARD_RESOURCE_DIRS):
        dir_path = skill_dir / dir_name
        if dir_path.exists() and not dir_path.is_dir():
            errors.append(f"skill {skill_name}: {dir_name} exists but is not a directory")
    return errors


def _validate_skill_md_structure(text: str, skill_name: str) -> list:
    """Validate SKILL.md has all required sections."""
    errors = []
    
    # Check for required sections (## SectionName format)
    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in text:
            errors.append(f"skill {skill_name}: missing required section '## {section}'")
    
    return errors


def _validate_sidecar_contract(skill_dir: Path, skill_name: str, schemas=None) -> list:
    """Validate the SKILL.json sidecar against the skill contract schema."""
    errors = []
    sidecar = skill_dir / "SKILL.json"

    if not sidecar.exists():
        errors.append(f"skill {skill_name}: missing SKILL.json sidecar")
        return errors

    try:
        data = load_json(sidecar)
    except Exception as exc:
        errors.append(f"skill {skill_name}: SKILL.json unreadable ({exc})")
        return errors

    schemas_all = schemas or load_schemas()
    errors.extend(validate(data, schemas_all["skill_contract"]))

    if data.get("name") != skill_name:
        errors.append(
            f"skill {skill_name}: SKILL.json name {data.get('name')!r} does not match folder name"
        )

    if data.get("version") != "0.1.0":
        errors.append(
            f"skill {skill_name}: version must be '0.1.0' (got {data.get('version')!r})"
        )

    skill_id = data.get("skill_id", "")
    if not SKILL_ID_RE.match(skill_id or ""):
        errors.append(
            f"skill {skill_name}: skill_id must match pattern ^SK-\\d{{4}}$ (got {skill_id!r})"
        )

    skill_kind = data.get("skill_kind")
    if skill_kind and skill_kind not in VALID_SKILL_KINDS:
        errors.append(
            f"skill {skill_name}: invalid skill_kind {skill_kind!r} "
            f"(must be one of {sorted(VALID_SKILL_KINDS)})"
        )

    metadata = data.get("metadata")
    if metadata is not None:
        errors.extend(_validate_metadata_structure(metadata, skill_name))

    return errors


def validate_skill(path: Path, name: str, schemas=None) -> list:
    """Validate one ``SKILL.md`` against the canonical skill contract.

    Enforced per SE-SKILL-RECON-001 / AUTO-07:

    - folder name matches ``^[a-z][a-z0-9-]*$`` and equals the frontmatter ``name``
    - frontmatter present with ``name``, ``description`` (<= 1024 chars) and ``metadata``
    - optional ``license`` / ``compatibility`` are strings with recognized values
    - ``metadata`` is a string -> string map
    - required structural sections are present
    - the ``SKILL.json`` sidecar conforms to ``skill-contract.schema.json``
    - standard resource directories are real directories when present

    Corpus-level rules (Skill ID uniqueness, duplicate/corrupt sidecars) belong to
    :func:`audit_contracts`, which sees every skill at once.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"skill {name}: unreadable ({exc})"]

    front = parse_frontmatter(text)
    if front is None:
        return [f"skill {name}: missing frontmatter"]
    if not isinstance(front, dict):
        return [f"skill {name}: frontmatter must be a mapping"]

    errors = []

    if not SKILL_NAME_RE.match(name):
        errors.append(f"skill {name}: invalid name format (must match ^[a-z][a-z0-9-]*$)")
    if "name" not in front:
        errors.append(f"skill {name}: frontmatter has no name")
    elif front.get("name") != name:
        errors.append(
            f"skill {name}: frontmatter name {front.get('name')!r} does not match folder name"
        )

    description = front.get("description")
    if description is None or not str(description).strip():
        errors.append(f"skill {name}: frontmatter has no description")
    elif len(str(description)) > 1024:
        errors.append(f"skill {name}: description exceeds 1024 characters")

    if "metadata" not in front:
        errors.append(f"skill {name}: frontmatter has no metadata")
    elif front.get("metadata") is not None:
        errors.extend(_validate_metadata_structure(front.get("metadata"), name))

    license_val = front.get("license")
    if license_val is not None and not isinstance(license_val, str):
        errors.append(f"skill {name}: license must be a string if present")

    compat = front.get("compatibility")
    if compat is not None:
        if not isinstance(compat, str):
            errors.append(f"skill {name}: compatibility must be a string if present")
        elif compat not in VALID_COMPATIBILITY:
            errors.append(
                f"skill {name}: compatibility {compat!r} not recognized "
                f"(valid: {sorted(VALID_COMPATIBILITY)})"
            )

    errors.extend(_validate_skill_md_structure(text, name))
    errors.extend(_validate_sidecar_contract(path.parent, name, schemas))
    errors.extend(_validate_resource_directories(path.parent, name))
    return errors


_AUDIT_CACHE: dict = {}
_AUDIT_CACHE_MAX = 8

_AUDIT_DIRS = ("AGENTS", "COMMANDS", "SKILLS", "POLICIES")
# Fingerprint de la raíz canónica: se computa una sola vez por proceso.
# Los tests no mutan el canon (usan tmp roots), así que es estable.
_CANONICAL_FINGERPRINT: tuple | None = None


def reset_audit_cache() -> None:
    """Drop memoized contract-audit results (used by tests and long-lived processes)."""
    _AUDIT_CACHE.clear()
    global _CANONICAL_FINGERPRINT
    _CANONICAL_FINGERPRINT = None


def _get_canonical_fingerprint(canonical_root: Path) -> tuple:
    """Return cached fingerprint for canonical root, computing once per process."""
    global _CANONICAL_FINGERPRINT
    if _CANONICAL_FINGERPRINT is None:
        _CANONICAL_FINGERPRINT = tree_fingerprint(canonical_root, _AUDIT_DIRS)
    return _CANONICAL_FINGERPRINT


def audit_contracts(root: Path, schemas=None):
    """Validate canon contracts (agents, commands, skills). Returns (errors, counts).

    Errors are human-readable strings; an empty list means the corpus is valid.

    Memoized **only** for the canonical repository root (``repo_root()``). Tests that
    build temporary roots do not benefit from caching (they audit once and discard),
    and fingerprinting them adds overhead. The cache key covers every contract file
    this function reads (``AGENTS/*/agent.json``, ``COMMANDS/commands.json``,
    ``SKILLS/*`` including sidecars and resources, and the ``POLICIES`` count set).
    Any add, edit, or removal changes the fingerprint and forces a real re-audit.
    Returned containers are copies; mutating them does not poison it.
    """
    root = Path(root)
    canonical_root = repo_root()
    # Cache only the canonical root: temporary roots are audited once and
    # fingerprinting them on DrvFs costs ~200ms per call with zero reuse.
    is_canonical = root.resolve() == canonical_root.resolve()
    if is_canonical:
        resolved = schemas if schemas is not None else load_schemas(root)
        # ``resolved`` is stored in the cache entry, which pins its id(): a garbage
        # collected dict can have its address reused, and a stale id in the key would
        # produce a false cache hit (a false PASS).
        fp = _get_canonical_fingerprint(canonical_root)
        key = (str(canonical_root), fp, id(resolved))
        cached = _AUDIT_CACHE.get(key)
        if cached is not None:
            return list(cached[0]), dict(cached[1])
        schemas = resolved
    else:
        schemas = schemas or load_schemas(root)

    errors = []
    counts = {"agents": 0, "commands": 0, "skills": 0, "policies": 0}

    agent_files = sorted((root / "AGENTS").glob("*/agent.json"))
    counts["agents"] = len(agent_files)
    for path in agent_files:
        data = load_json(path)
        for message in validate(data, schemas["agent"]):
            errors.append(f"{path.relative_to(root).as_posix()}: {message}")

    commands_file = root / "COMMANDS" / "commands.json"
    data = load_json(commands_file)
    for message in validate(data, schemas["command_contract"]):
        errors.append(f"{commands_file.relative_to(root).as_posix()}: {message}")
    counts["commands"] = len(data.get("commands", []))

    skill_files = sorted((root / "SKILLS").glob("*/SKILL.md"))
    counts["skills"] = len(skill_files)
    skill_id_owners: dict = {}
    for path in skill_files:
        errors.extend(validate_skill(path, path.parent.name, schemas))
        sidecar = path.parent / "SKILL.json"
        if not sidecar.exists():
            continue
        try:
            skill_id = load_json(sidecar).get("skill_id")
        except Exception:
            continue
        owner = skill_id_owners.get(skill_id)
        if owner is None:
            skill_id_owners[skill_id] = path.parent.name
        else:
            errors.append(
                f"SKILLS: duplicate skill_id {skill_id!r} shared by "
                f"{owner!r} and {path.parent.name!r}"
            )

    counts["policies"] = len(list((root / "POLICIES").glob("*.md")))

    if is_canonical:
        if len(_AUDIT_CACHE) >= _AUDIT_CACHE_MAX:
            _AUDIT_CACHE.clear()
        _AUDIT_CACHE[key] = (list(errors), dict(counts), resolved)
    return list(errors), dict(counts)


def validate_generated_config(config: dict, schemas=None) -> list:
    """Validate the generated adapter-manifest.json against the adapter manifest schema."""
    schemas = schemas or load_schemas()
    return validate(config, schemas["adapter_manifest"])


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _deployed_files(output: Path, roots=None) -> set:
    """Files under ``output``, optionally limited to the given top-level roots.

    A deployed ``.opencode`` tree can carry OpenCode runtime directories
    (``node_modules/`` with thousands of files). Walking them is pure waste: the
    audit only ever compares the roots the adapter owns, and on a network or 9p
    mount the extra ``stat`` calls dominate (tens of seconds). The doctor's
    ``_walk`` already prunes these; this mirrors that discipline.
    """
    output = Path(output)
    if not roots:
        return {
            p.relative_to(output).as_posix()
            for p in output.rglob("*")
            if p.is_file()
        }
    found: set = set()
    for root in roots:
        base = output / root
        if base.is_file():
            found.add(root)
        elif base.is_dir():
            found.update(
                p.relative_to(output).as_posix()
                for p in base.rglob("*")
                if p.is_file()
            )
    return found


def audit_adapter(root: Path, output: Path, schemas=None) -> list:
    """Audit a generated OpenCode tree against its own manifest (AUTO-08).

    Mechanical adapter conformance rules:

    1. the manifest conforms to ``SCHEMAS/adapter-manifest.schema.json``;
    2. adapter identity (``adapter_id``/``target``) and ``adapter_version``/
       ``engine_version`` match ``SYSTEM.json``;
    3. runtime discovery paths: only the V2 plural ``agents/``, ``commands/`` and
       ``skills/`` directories may exist, because the legacy singular spellings
       are ignored or double-registered by OpenCode V2;
    4. the deployed tree matches ``output.generated_files`` and
       ``metadata.content_hashes`` - no missing, undeclared or modified file;
    5. frontmatter preservation: every generated Markdown file keeps a parseable
       ``description`` frontmatter, and generated skills stay byte-identical to
       ``SKILLS/<name>/SKILL.md``;
    6. capability representation (CP-020): ``capability_plan`` mirrors the canonical
       registry, every provider is known, and no capability id is spelled like a
       provider id.

    Returns human-readable error strings; an empty list means conforming.
    """
    root = Path(root)
    output = Path(output)
    schemas = schemas or load_schemas(root)
    errors = []

    manifest_path = output / ADAPTER_MANIFEST
    if not manifest_path.exists():
        return [f"adapter: missing {ADAPTER_MANIFEST} in {output}"]
    try:
        config = load_json(manifest_path)
    except Exception as exc:
        return [f"adapter: {ADAPTER_MANIFEST} unreadable ({exc})"]

    errors.extend(validate(config, schemas["adapter_manifest"]))

    # 2. identity and versions
    if config.get("adapter_id") != "opencode":
        errors.append(
            f"adapter: adapter_id must be 'opencode' (got {config.get('adapter_id')!r})"
        )
    if config.get("target") != "opencode":
        errors.append(f"adapter: target must be 'opencode' (got {config.get('target')!r})")
    master_version = load_json(root / "SYSTEM.json").get("master_system_version")
    for key in ("adapter_version", "engine_version"):
        if config.get(key) != master_version:
            errors.append(
                f"adapter: {key} {config.get(key)!r} does not match SYSTEM.json "
                f"master_system_version {master_version!r}"
            )

    # 3. runtime discovery directories. OpenCode V2 discovers agents in
    # ``agents/``, commands in ``commands/`` and skills in ``skills/``. A tree
    # carrying the legacy singular spelling alongside the plural one would either
    # register the same artifact twice or shadow it depending on load order, so
    # exactly one spelling may exist on disk.
    for legacy, canonical in (
        ("agent", AGENT_DIR),
        ("command", COMMAND_DIR),
        ("skill", SKILL_DIR),
    ):
        if (output / legacy).exists():
            errors.append(
                f"adapter: legacy singular {legacy}/ directory is present; "
                f"OpenCode V2 discovers {canonical}/, so {legacy}/ is ignored "
                f"or loaded twice (remove {legacy}/ and regenerate)"
            )

    # 4. deployed tree vs manifest declarations
    declared = set(config.get("output", {}).get("generated_files") or [])
    hashes = (config.get("metadata") or {}).get("content_hashes") or {}
    if not hashes:
        errors.append("adapter: metadata.content_hashes is empty; drift cannot be checked")
    only_hashes = sorted(set(hashes) - declared)
    only_declared = sorted(declared - set(hashes))
    if only_hashes:
        errors.append(f"adapter: content_hashes not in output.generated_files: {only_hashes}")
    if only_declared:
        errors.append(f"adapter: output.generated_files without content_hashes: {only_declared}")

    # Drift is scoped to the top-level entries the adapter owns (agents/,
    # commands/, skills/, AGENTS.md). The same directory may legitimately host
    # OpenCode runtime files (package.json, node_modules/, .gitignore) that the
    # adapter never writes.
    owned_roots = {rel.split("/", 1)[0] for rel in declared}
    on_disk = _deployed_files(output, owned_roots)
    for segment in sorted(owned_roots):
        on_segment = {rel for rel in on_disk if rel.split("/", 1)[0] == segment}
        in_manifest = {rel for rel in declared if rel.split("/", 1)[0] == segment}
        for rel in sorted(in_manifest - on_segment):
            errors.append(f"adapter: declared generated file is missing on disk: {rel}")
        for rel in sorted(on_segment - in_manifest):
            errors.append(f"adapter: undeclared file present in generated tree: {rel}")
    for rel, digest in sorted(hashes.items()):
        target = output / rel
        if target.is_file() and _sha256_file(target) != digest:
            errors.append(f"adapter: content hash mismatch (drift): {rel}")

    # 5. frontmatter preservation. Only the artifacts that OpenCode loads as
    # agents/commands/skills carry frontmatter; AGENTS.md is an overview document.
    artifact_roots = (f"{AGENT_DIR}/", f"{COMMAND_DIR}/", f"{SKILL_DIR}/")
    for rel in sorted(declared):
        target = output / rel
        if not rel.endswith(".md") or not rel.startswith(artifact_roots):
            continue
        if not target.is_file():
            continue
        front = parse_frontmatter(target.read_text(encoding="utf-8"))
        if not isinstance(front, dict) or not str(front.get("description") or "").strip():
            errors.append(f"adapter: {rel} has no frontmatter description")
        if rel.startswith(f"{SKILL_DIR}/"):
            name = Path(rel).parent.name
            canonical = root / "SKILLS" / name / "SKILL.md"
            if not canonical.is_file():
                errors.append(
                    f"adapter: {rel} has no canonical source SKILLS/{name}/SKILL.md"
                )
            elif target.read_bytes() != canonical.read_bytes():
                errors.append(
                    f"adapter: {rel} is not byte-identical to canonical SKILL.md"
                )

    # 6. capability representation (CP-020)
    plan = config.get("capability_plan")
    if not isinstance(plan, dict):
        errors.append("adapter: capability_plan is missing or not an object")
    else:
        expected = sorted(available_capabilities(root))
        planned = sorted(plan.get("available") or [])
        if planned != expected:
            errors.append(
                f"adapter: capability_plan.available does not mirror the registry "
                f"({planned} != {expected})"
            )
        providers = known_providers(root)
        capability_ids = set(planned)
        for entry in plan.get("mapping") or []:
            provider = entry.get("provider")
            if provider not in providers:
                errors.append(
                    f"adapter: capability_plan references unknown provider {provider!r}"
                )
            for cid in entry.get("capabilities") or []:
                capability_ids.add(cid)
                if "." not in str(cid):
                    errors.append(
                        f"adapter: capability {cid!r} lacks domain.operation form; a "
                        "logical capability must not be spelled like a provider id"
                    )
        collisions = sorted(capability_ids & set(providers))
        if collisions:
            errors.append(f"adapter: capability/provider id collision (CP-020): {collisions}")

    return errors
