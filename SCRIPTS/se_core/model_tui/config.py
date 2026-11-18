"""Model configuration persistence for opencode.jsonc.

surgical: only the model keys are rewritten.

The write path edits the existing document in place instead of re-serializing
it.  Comments, blank lines, key order, indentation and trailing commas of every
region that is not a model key survive byte for byte.  When the document cannot
be patched safely (malformed JSONC, duplicate keys, an unexpected shape) the
writer falls back to the previous full-serialization behaviour and, when even
that cannot parse the file, leaves the file untouched instead of corrupting it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import httpx

from ..mcpconfig import (
    _match_container,
    _object_properties,
    _skip_ws_and_comments,
    _write_text_preserving_newline,
    parse_jsonc,
)


@dataclass
class AgentModelOverride:
    """Override for a specific agent's model."""
    provider: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None

    def to_dict(self) -> dict:
        result = {}
        if self.provider:
            result["providerID"] = self.provider
        if self.model:
            result["model"] = self.model
        if self.variant:
            result["variant"] = self.variant
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "AgentModelOverride":
        return cls(
            provider=data.get("providerID"),
            model=data.get("model"),
            variant=data.get("variant"),
        )


@dataclass
class ModelConfig:
    """Model configuration from opencode.jsonc.

    ``global_model`` is ``None`` when the document declares no ``model`` key.
    That absence is deliberate: an unconfigured checkout must report that
    nobody chose a model instead of claiming a fabricated default.
    """
    global_model: Optional[str] = None
    agent_overrides: dict[str, AgentModelOverride] = field(default_factory=dict)

    @classmethod
    def from_opencode_config(cls, config: dict) -> "ModelConfig":
        """Parse model config from opencode.jsonc (no model key -> None)."""
        global_model = config.get("model")
        if not isinstance(global_model, str) or not global_model.strip():
            global_model = None
        agent_overrides = {}

        agents = config.get("agents", {})
        for agent_name, agent_config in agents.items():
            if isinstance(agent_config, dict) and "model" in agent_config:
                model_config = agent_config["model"]
                if isinstance(model_config, dict):
                    agent_overrides[agent_name] = AgentModelOverride(
                        provider=model_config.get("providerID"),
                        model=model_config.get("model"),
                        variant=model_config.get("variant"),
                    )
                elif isinstance(model_config, str):
                    # Simple string format "provider/model"
                    parts = model_config.split("/", 1)
                    agent_overrides[agent_name] = AgentModelOverride(
                        provider=parts[0] if len(parts) > 1 else None,
                        model=parts[1] if len(parts) > 1 else model_config,
                    )

        return cls(global_model=global_model, agent_overrides=agent_overrides)

    def to_opencode_config(self) -> dict:
        """Convert to opencode.jsonc format (an unset model writes no key)."""
        config: dict = {}
        if self.global_model:
            config["model"] = self.global_model
        if self.agent_overrides:
            config["agents"] = {}
            for agent_name, override in self.agent_overrides.items():
                if override.provider or override.model:
                    model_dict = override.to_dict()
                    if model_dict:
                        config["agents"][agent_name] = {"model": model_dict}
        return config


def _parse_jsonc(content: str) -> dict:
    """Parse JSONC content (strip comments properly - not inside strings)."""
    lines = []
    in_string = False
    escape_next = False
    for line in content.splitlines():
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"' and not escape_next:
                in_string = not in_string
            elif ch == '\\' and not escape_next:
                escape_next = True
                i += 1
                continue
            elif ch == '/' and i + 1 < len(line) and line[i + 1] == '/' and not in_string:
                line = line[:i]
                break
            escape_next = False
            i += 1
        stripped = line.strip()
        if stripped and not stripped.startswith("//"):
            lines.append(line)
    cleaned = "\n".join(lines)
    return json.loads(cleaned)


def resolve_agent_model(project_root: Path, agent_name: str) -> Optional[str]:
    """The model the harness will run one agent with, or None when unset.

    Unlike :func:`load_model_config`, this never invents a default: an absent
    ``model`` key resolves to ``None`` instead of a fabricated model id. The
    per-agent override wins; otherwise the global ``model`` applies.
    """
    config_path = Path(project_root) / "opencode.jsonc"
    if not config_path.exists():
        config_path = Path(project_root) / ".opencode" / "opencode.jsonc"
        if not config_path.exists():
            return None

    try:
        parsed = _parse_jsonc(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    agents = parsed.get("agents")
    if isinstance(agents, dict):
        entry = agents.get(agent_name)
        if isinstance(entry, dict):
            value = entry.get("model")
            if isinstance(value, dict) and value.get("model"):
                provider = value.get("providerID")
                model = str(value["model"])
                return f"{provider}/{model}" if provider else model
            if isinstance(value, str) and value:
                return value

    global_model = parsed.get("model")
    return global_model if isinstance(global_model, str) and global_model else None


def load_model_config(project_root: Path) -> ModelConfig:
    """Load model configuration from opencode.jsonc.

    A missing or unparseable file loads an *unset* configuration: the global
    model stays ``None`` rather than inventing a model nobody selected.
    """
    config_path = project_root / "opencode.jsonc"
    if not config_path.exists():
        # Try .opencode/opencode.jsonc
        config_path = project_root / ".opencode" / "opencode.jsonc"
        if not config_path.exists():
            return ModelConfig()

    try:
        content = config_path.read_text(encoding="utf-8")
        config = _parse_jsonc(content)
        return ModelConfig.from_opencode_config(config)
    except Exception:
        return ModelConfig()


# --------------------------------------------------------------------------- #
# Surgical JSONC editing
#
# The helpers below locate the exact character spans of the keys the caller
# wants to change and rewrite only those spans.  They are deliberately
# fail-closed: any shape they do not understand raises ``_CannotPatch`` so the
# caller can fall back instead of guessing.
# --------------------------------------------------------------------------- #


class _CannotPatch(ValueError):
    """The document cannot be edited surgically without reformatting it."""


@dataclass(frozen=True)
class _Member:
    """One property of a JSON object, with absolute character offsets."""

    key: str
    key_start: int
    key_end: int
    value_start: int
    value_end: int
    comma: Optional[int]


@dataclass
class _Container:
    """An object value: its bounds plus its top-level properties."""

    start: int
    end: int
    members: list[_Member]


def _members(text: str, start: int, end: int) -> list[_Member]:
    """List the properties of the object spanning ``text[start:end]``."""
    members = []
    for key_start, raw_key, value_start, value_end in _object_properties(text, start, end):
        key_end = key_start + len(raw_key) + 2  # both quotes
        key = json.loads(text[key_start:key_end])
        after = _skip_ws_and_comments(text, value_end)
        comma = after if after < len(text) and text[after] == "," else None
        members.append(_Member(key, key_start, key_end, value_start, value_end, comma))
    return members


def _container(text: str, start: int, end: int) -> _Container:
    """Build a container for the object literal that must span exactly start..end."""
    if end <= start or text[start] != "{":
        raise _CannotPatch("expected an object literal")
    if _match_container(text, start, "{", "}") + 1 != end:
        raise _CannotPatch("object span is not self-contained")
    return _Container(start, end, _members(text, start, end))


def _document(text: str) -> _Container:
    """Parse the root object of a JSONC document."""
    start = _skip_ws_and_comments(text, 0)
    if start >= len(text) or text[start] != "{":
        raise _CannotPatch("document root is not an object")
    end = _match_container(text, start, "{", "}") + 1
    if _skip_ws_and_comments(text, end) != len(text):
        raise _CannotPatch("trailing content after the document root")
    return _Container(start, end, _members(text, start, end))


def _single(container: _Container, key: str) -> Optional[_Member]:
    """Return the unique property ``key``, or None when it is absent."""
    found = [member for member in container.members if member.key == key]
    if len(found) > 1:
        raise _CannotPatch(f"duplicate key {key!r}")
    return found[0] if found else None


def _override_dict(override) -> dict:
    """Normalise an override value (dataclass or mapping) to its model dict."""
    if hasattr(override, "to_dict"):
        return override.to_dict()
    if isinstance(override, dict):
        return {
            key: override[key]
            for key in ("providerID", "model", "variant")
            if override.get(key)
        }
    return {}


def _resolve_overrides(agent_overrides) -> tuple[dict, set]:
    """Split requested overrides into ``(writes, names_to_keep)``.

    A ``None`` value means "remove this override"; an override that renders to
    an empty dict keeps the agent entry untouched (as the previous writer did).
    """
    requested: dict[str, dict] = {}
    keep: set[str] = set()
    for agent_name, override in (agent_overrides or {}).items():
        name = str(agent_name)
        if override is None:
            continue
        keep.add(name)
        model_dict = _override_dict(override)
        if model_dict:
            requested[name] = model_dict
    return requested, keep


def _line_start(text: str, position: int) -> int:
    return text.rfind("\n", 0, position) + 1


def _line_indent(text: str, position: int) -> str:
    start = _line_start(text, position)
    index = start
    while index < len(text) and text[index] in " \t":
        index += 1
    return text[start:index]


def _line_end(text: str, position: int) -> int:
    index = text.find("\n", position)
    return len(text) if index == -1 else index + 1


def _indent_unit(text: str) -> str:
    """Infer the indentation step used by the document (default two spaces)."""
    indents = []
    for line in text.split("\n"):
        stripped = line.lstrip(" \t")
        if stripped and len(stripped) != len(line):
            indents.append(line[:len(line) - len(stripped)])
    if not indents:
        return "  "
    return min(indents, key=len) or "  "


def _member_indent(text: str, container: _Container, unit: str) -> str:
    """Indentation to use for a property added to ``container``."""
    if container.members:
        indent = _line_indent(text, container.members[0].key_start)
        if indent:
            return indent
    return _line_indent(text, container.start) + unit


def _render(value, key_indent: str, unit: str) -> str:
    """Render ``value`` as JSON, aligned under a key at ``key_indent``."""
    rendered = json.dumps(value, indent=unit, ensure_ascii=False)
    if "\n" not in rendered:
        return rendered
    lines = rendered.split("\n")
    return "\n".join([lines[0]] + [key_indent + line for line in lines[1:]])


class _Edits:
    """Collect disjoint text edits and apply them right-to-left."""

    def __init__(self, text: str):
        self.text = text
        self.unit = _indent_unit(text)
        self._edits: list[tuple[int, int, str]] = []

    def replace(self, start: int, end: int, replacement: str) -> None:
        if self.text[start:end] != replacement:
            self._edits.append((start, end, replacement))

    def delete(self, start: int, end: int) -> None:
        if end > start:
            self._edits.append((start, end, ""))

    def insert(self, position: int, text: str) -> None:
        if text:
            self._edits.append((position, position, text))

    def apply(self) -> str:
        result = self.text
        limit = len(result) + 1
        for start, end, replacement in sorted(
            self._edits, key=lambda edit: (edit[0], edit[1]), reverse=True
        ):
            if end > limit:
                raise _CannotPatch("overlapping edits")
            result = result[:start] + replacement + result[end:]
            limit = start
        return result


def _append_members(edits: _Edits, text: str, container: _Container, pairs) -> None:
    """Append ``(key, value)`` properties to ``container``, touching only them."""
    indent = _member_indent(text, container, edits.unit)
    rendered = []
    for key, value in pairs:
        key_text = json.dumps(key, ensure_ascii=False)
        rendered.append(f"{key_text}: {_render(value, indent, edits.unit)}")
    joined = (",\n" + indent).join(rendered)

    if container.members:
        last = container.members[-1]
        if last.comma is not None:
            edits.insert(last.comma + 1, "\n" + indent + joined)
        else:
            edits.insert(last.value_end, ",\n" + indent + joined)
        return

    inner = text[container.start + 1:container.end - 1]
    closing_indent = _line_indent(text, container.start)
    if "\n" in inner:
        edits.insert(container.start + 1, "\n" + indent + joined)
        return
    if inner.strip():
        # Comment-only inline object: the new member goes before the comment.
        edits.insert(
            container.start + 1,
            "\n" + indent + joined + "\n" + closing_indent,
        )
        return
    edits.replace(
        container.start,
        container.end,
        "{\n" + indent + joined + "\n" + closing_indent + "}",
    )


def _delete_member(
    edits: _Edits,
    text: str,
    container: _Container,
    index: int,
    previous_deleted: bool = False,
) -> None:
    """Delete property ``index`` from ``container`` without reformatting the rest."""
    members = container.members
    member = members[index]
    previous = members[index - 1] if index > 0 else None
    following = members[index + 1] if index + 1 < len(members) else None
    token_end = member.comma + 1 if member.comma is not None else member.value_end
    line_start = _line_start(text, member.key_start)
    owns_line = text[line_start:member.key_start].strip() == ""

    if owns_line:
        line_end = _line_end(text, token_end)
        tail = text[token_end:line_end]
        if "//" in tail or "/*" in tail:
            # Keep the comment that shared the deleted property's line.
            edits.delete(member.key_start, token_end)
        else:
            edits.delete(line_start, line_end)
        if (
            following is None
            and previous is not None
            and not previous_deleted
            and member.comma is None
            and previous.comma is not None
        ):
            # The separator comma belonged to the property we just removed.
            edits.delete(previous.comma, previous.comma + 1)
        return

    if member.comma is not None:
        edits.delete(member.key_start, member.comma + 1)
    elif previous is not None and not previous_deleted and previous.comma is not None:
        edits.delete(previous.comma, member.value_end)
    else:
        edits.delete(member.key_start, member.value_end)


def _remove_overrides(text: str, keep_names: set) -> tuple[str, bool]:
    """Remove every agent model override whose name is not requested."""
    document = _document(text)
    agents_member = _single(document, "agents")
    if agents_member is None:
        return text, False
    if text[agents_member.value_start] != "{":
        raise _CannotPatch("agents is not an object")
    agents = _container(text, agents_member.value_start, agents_member.value_end)

    entry_deletions: list[int] = []
    model_deletions: list[tuple[_Container, int]] = []
    for index, member in enumerate(agents.members):
        if member.key in keep_names:
            continue
        if text[member.value_start] != "{":
            # Not an object: it cannot carry a model override; leave it alone.
            continue
        entry = _container(text, member.value_start, member.value_end)
        model_members = [item for item in entry.members if item.key == "model"]
        if len(model_members) > 1:
            raise _CannotPatch(f"duplicate model key for agent {member.key!r}")
        if not model_members:
            # An agent entry without a model override is unrelated configuration.
            continue
        if len(entry.members) == 1:
            entry_deletions.append(index)
        else:
            model_deletions.append((entry, entry.members.index(model_members[0])))

    if not entry_deletions and not model_deletions:
        return text, False

    edits = _Edits(text)
    deleted = set(entry_deletions)
    for index in sorted(entry_deletions, reverse=True):
        _delete_member(
            edits,
            text,
            agents,
            index,
            previous_deleted=(index - 1) in deleted,
        )
    for entry, index in model_deletions:
        _delete_member(edits, text, entry, index)
    return edits.apply(), True


def _drop_empty_agents(text: str) -> str:
    """Remove an ``agents`` object that is now empty and comment-free."""
    document = _document(text)
    agents_member = _single(document, "agents")
    if agents_member is None or text[agents_member.value_start] != "{":
        return text
    agents = _container(text, agents_member.value_start, agents_member.value_end)
    if agents.members:
        return text
    if text[agents.start + 1:agents.end - 1].strip():
        return text  # comments inside the empty object are preserved
    index = next(
        index
        for index, member in enumerate(document.members)
        if member is agents_member
    )
    edits = _Edits(text)
    _delete_member(edits, text, document, index)
    return edits.apply()


def _apply_sets(
    text: str, global_model: Optional[str], requested: dict
) -> str:
    """Set every requested agent override and the global model when one is set.

    ``global_model`` is ``None`` when no global model is configured: the
    ``model`` key is then removed (or not created) instead of being written as
    an explicit ``null``.
    """
    document = _document(text)
    edits = _Edits(text)
    root_additions: list[tuple[str, object]] = []

    agents_member = _single(document, "agents") if requested else None
    agents_value = (
        {name: {"model": model_dict} for name, model_dict in requested.items()}
        if requested and agents_member is None
        else None
    )

    model_member = _single(document, "model")
    if global_model is None:
        if model_member is not None:
            if agents_value is not None:
                # The new agents object takes the model member's place, so the
                # member (and its separator comma) stays valid without an
                # intermediate deletion.
                edits.replace(
                    model_member.key_start,
                    model_member.value_end,
                    json.dumps("agents")
                    + ": "
                    + _render(
                        agents_value,
                        _line_indent(text, model_member.key_start),
                        edits.unit,
                    ),
                )
                agents_value = None
            else:
                _delete_member(
                    edits, text, document, document.members.index(model_member)
                )
    elif model_member is None:
        root_additions.append(("model", global_model))
    else:
        edits.replace(
            model_member.value_start,
            model_member.value_end,
            json.dumps(global_model, ensure_ascii=False),
        )

    if agents_member is None:
        if agents_value is not None:
            root_additions.append(("agents", agents_value))
        if root_additions:
            _append_members(edits, text, document, root_additions)
        return edits.apply()

    if text[agents_member.value_start] != "{":
        raise _CannotPatch("agents is not an object")
    agents = _container(text, agents_member.value_start, agents_member.value_end)
    new_entries = []
    for name, model_dict in requested.items():
        existing = [member for member in agents.members if member.key == name]
        if len(existing) > 1:
            raise _CannotPatch(f"duplicate agent {name!r}")
        if not existing:
            new_entries.append((name, {"model": model_dict}))
            continue
        member = existing[0]
        if text[member.value_start] != "{":
            value = {"model": model_dict}
            edits.replace(
                member.value_start,
                member.value_end,
                _render(value, _line_indent(text, member.key_start), edits.unit),
            )
            continue
        entry = _container(text, member.value_start, member.value_end)
        model_members = [item for item in entry.members if item.key == "model"]
        if len(model_members) > 1:
            raise _CannotPatch(f"duplicate model key for agent {name!r}")
        if model_members:
            target = model_members[0]
            edits.replace(
                target.value_start,
                target.value_end,
                _render(
                    model_dict,
                    _line_indent(text, target.key_start),
                    edits.unit,
                ),
            )
        else:
            _append_members(edits, text, entry, [("model", model_dict)])

    if new_entries:
        _append_members(edits, text, agents, new_entries)
    if root_additions:
        _append_members(edits, text, document, root_additions)
    return edits.apply()


def _patch_jsonc(
    text: str, global_model: Optional[str], agent_overrides
) -> str:
    """Return ``text`` with only the model keys rewritten."""
    requested, keep_names = _resolve_overrides(agent_overrides)
    text, removed = _remove_overrides(text, keep_names)
    if removed and not requested:
        text = _drop_empty_agents(text)
    return _apply_sets(text, global_model, requested)


def _verify(
    text: str, original: dict, global_model: Optional[str], agent_overrides
) -> None:
    """Fail closed unless the patch produced exactly the requested model state."""
    parsed = parse_jsonc(text)
    if parsed.get("model") != global_model:
        raise _CannotPatch(
            "global model was not written"
            if global_model is not None
            else "an unset global model left a model key behind"
        )
    for key, value in original.items():
        if key in ("model", "agents"):
            continue
        if parsed.get(key) != value:
            raise _CannotPatch(f"unrelated key {key!r} changed")

    agents = parsed.get("agents")
    if agents is not None and not isinstance(agents, dict):
        raise _CannotPatch("agents is not an object")
    agents = agents or {}
    original_agents = original.get("agents")
    if original_agents is not None and not isinstance(original_agents, dict):
        raise _CannotPatch("original agents is not an object")
    original_agents = original_agents or {}
    requested, _keep = _resolve_overrides(agent_overrides)

    for name, model_dict in requested.items():
        entry = agents.get(name)
        if not isinstance(entry, dict) or entry.get("model") != model_dict:
            raise _CannotPatch(f"override for {name!r} was not written")
        reference = original_agents.get(name)
        if isinstance(reference, dict):
            if _without_model(entry) != _without_model(reference):
                raise _CannotPatch(f"unrelated keys changed for agent {name!r}")

    expected_rest = {
        name: _without_model(entry) if isinstance(entry, dict) else entry
        for name, entry in original_agents.items()
        if name not in requested
    }
    expected_rest = {name: value for name, value in expected_rest.items() if value}
    actual_rest = {
        name: _without_model(entry) if isinstance(entry, dict) else entry
        for name, entry in agents.items()
        if name not in requested
    }
    actual_rest = {name: value for name, value in actual_rest.items() if value}
    if actual_rest != expected_rest:
        raise _CannotPatch("an unrelated agent entry changed")


def _without_model(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if key != "model"}


def _legacy_save(
    config_path: Path, global_model: Optional[str], agent_overrides
) -> bool:
    """Previous behaviour: parse the whole file and re-serialize it.

    Used only when the surgical path cannot prove it is safe.  An unparseable
    file is left untouched (the old writer would have raised here).  Returns
    True when the file was rewritten.
    """
    try:
        config = _parse_jsonc(config_path.read_bytes().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(config, dict):
        return False

    if global_model is None:
        config.pop("model", None)
    else:
        config["model"] = global_model
    if agent_overrides:
        if not isinstance(config.get("agents"), dict):
            if config.get("agents") is not None:
                return False
            config["agents"] = {}
        for agent_name, override in agent_overrides.items():
            model_dict = _override_dict(override)
            if model_dict:
                config["agents"][str(agent_name)] = {"model": model_dict}
        for agent_name in list(config["agents"]):
            if agent_name not in agent_overrides:
                del config["agents"][agent_name]
    else:
        config.pop("agents", None)

    config_path.write_bytes((json.dumps(config, indent=2) + "\n").encode("utf-8"))
    return True


def _write_new_config(
    config_path: Path, global_model: Optional[str], agent_overrides
) -> None:
    """Create a fresh config, omitting an unset model instead of writing null."""
    config: dict = {}
    if global_model:
        config["model"] = global_model
    if agent_overrides:
        config["agents"] = {}
        for agent_name, override in agent_overrides.items():
            model_dict = _override_dict(override)
            if model_dict:
                config["agents"][str(agent_name)] = {"model": model_dict}
    config_path.write_bytes(
        (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )


def save_model_config(
    project_root: Path,
    global_model: Optional[str],
    agent_overrides: dict,
) -> bool:
    """Save model configuration to opencode.jsonc, surgically when possible.

    ``global_model=None`` means "no global model is configured": the ``model``
    key is removed or never created, while the agent overrides are still
    written.  The file is never given a ``"model": null`` entry.

    Returns True when the configuration was written, and False when there was
    nothing to persist (no global model, no overrides and no config file) or
    the file was already in the requested state.  Callers report the empty
    case honestly instead of silently creating an empty selection.
    """
    if not global_model:
        global_model = None
    requested, _keep = _resolve_overrides(agent_overrides)

    config_path = project_root / "opencode.jsonc"
    if not config_path.exists():
        config_path = project_root / ".opencode" / "opencode.jsonc"
        if not config_path.exists():
            if global_model is None and not requested:
                return False
            _write_new_config(
                project_root / "opencode.jsonc", global_model, agent_overrides
            )
            return True

    original_bytes = config_path.read_bytes()
    raw = original_bytes.decode("utf-8")
    has_bom = raw.startswith("\ufeff")
    text = raw[1:] if has_bom else raw
    newline = "\r\n" if "\r\n" in text else "\n"
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    try:
        original_config = parse_jsonc(normalized)
        patched = _patch_jsonc(normalized, global_model, agent_overrides)
        _verify(patched, original_config, global_model, agent_overrides)
    except (ValueError, TypeError, KeyError, IndexError):
        return _legacy_save(config_path, global_model, agent_overrides)

    payload = ("\ufeff" if has_bom else "") + patched
    if newline != "\n":
        payload = payload.replace("\n", newline)
    if payload.encode("utf-8") == original_bytes:
        return False
    _write_text_preserving_newline(config_path, ("\ufeff" if has_bom else "") + patched, newline)
    return True


async def reload_opencode_config(project_root: Path) -> bool:
    """Trigger OpenCode hot reload via API."""
    # Try HTTP API
    ports = [49374, 49375, 49376, 49377, 49378]
    for port in ports:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"http://localhost:{port}/api/config/reload")
                if resp.status_code == 200:
                    return True
        except Exception:
            continue

    # Try CLI
    try:
        result = subprocess.run(
            ["opencode", "config", "reload"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        pass

    return False


import subprocess  # noqa: E402
