"""Runtime MCP config access: jsonc-tolerant reads + surgical server removal.

OpenCode stores MCP servers in the project config (``opencode.jsonc``) under the
V2 ``mcp.servers.*`` map; legacy tools use ``mcpServers.*``. This module offers:

* ``parse_jsonc`` / ``read_config`` - a small dependency-free jsonc parser
  (strips ``//`` and ``/* */`` comments and a BOM, tolerates trailing commas);
* ``list_servers`` - a unified view over BOTH maps, each entry tagged with its
  scope (``v2`` | ``legacy``) so sync can dedupe;
* ``remove_server_text`` - SURGICAL removal of only one server object from
  ``mcp.servers.<name>`` and/or legacy ``mcpServers.<name>``, preserving every
  other byte (comments, formatting, whitespace) exactly;
* ``add_server_text`` - SURGICAL add/update of ``mcp.servers.<name>`` with the
  same byte-preserving, fail-closed guarantees (creates the file when absent).

Every edit is fail-closed: an unparseable file or a region that cannot be
isolated safely produces a structured error and NEVER rewrites the user's config
by reformatting. A backup is written to ``<target>/.se/backups/`` before any
rewrite of an existing file.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .lifecycle_state import backup_dir


#: Patterns that indicate an MCP server is part of System Engineering
SE_MCP_PATTERNS = (
    re.compile(r"se_core[\\/]+mcp[\\/]+"),
    re.compile(r"SCRIPTS[\\/]+se_core[\\/]+mcp[\\/]+"),
    re.compile(r"\\blaunch\.mjs\b"),
    re.compile(r"\\bmemory_server\.py\\b"),
    re.compile(r"\\bskill_server\.py\\b"),
)

#: Known SE MCP server names
SE_MCP_KNOWN = {"se-memory-server", "se-skill-server"}


def is_se_related_server(name: str, entry: dict, se_root: Path | None = None) -> tuple[bool, str]:
    """Return (True, reason) if an MCP entry looks like it's from System Engineering.

    Conservative by design: only flags entries that clearly point to SE code or
    use known SE server names/paths. Never flags arbitrary user MCPs.
    """
    if not isinstance(entry, dict):
        return False, ""

    name = str(name or "")

    if name in SE_MCP_KNOWN:
        return True, f"known SE MCP: {name}"

    # Collect all relevant strings to inspect
    parts = []
    cmd = entry.get("command")
    if isinstance(cmd, str):
        parts.append(cmd)
    elif isinstance(cmd, list):
        parts.extend(str(x) for x in cmd)
    if entry.get("args") is not None:
        parts.extend(str(x) for x in entry.get("args") or [])
    env = entry.get("env") or entry.get("environment") or {}
    if isinstance(env, dict):
        parts.extend(str(v) for v in env.values())
    if entry.get("cwd"):
        parts.append(str(entry["cwd"]))

    blob = " ".join(parts)

    for pat in SE_MCP_PATTERNS:
        if pat.search(blob):
            return True, f"matches SE MCP pattern ({pat.pattern})"

    if "${SE_ROOT}" in blob or "${SE_PROJECT_ROOT}" in blob:
        for pat in SE_MCP_PATTERNS:
            if pat.search(blob):
                return True, "uses SE paths with SE environment variables"
        if name.startswith("se-"):
            return True, "uses SE environment variables and has 'se-' prefix"

    if name.startswith("se-") and ("se_core" in blob or "memory_server" in blob or "skill_server" in blob):
        return True, "se- prefixed server pointing to SE code"

    return False, ""

#: Candidate config file names, in preference order.
CONFIG_NAMES = ("opencode.jsonc", "opencode.json")


def config_path(target: Path | str) -> Path:
    """Return the runtime config path for ``target``.

    Returns an existing ``opencode.jsonc`` / ``opencode.json`` when present, else
    the default ``<target>/opencode.jsonc`` (callers check ``exists()``).
    """
    target = Path(target)
    for name in CONFIG_NAMES:
        path = target / name
        if path.exists():
            return path
    return target / CONFIG_NAMES[0]


def _detect_newline(raw: str) -> str:
    """Return the EOL style already used by ``raw``.

    ``\\r\\n`` when the text contains at least one CRLF, else ``\\n``. A brand
    new file (no raw text) is written as LF.
    """
    return "\r\n" if "\r\n" in raw else "\n"


def _read_config_text(path: Path) -> tuple[str, str]:
    """Read the config once, returning ``(text_normalized_to_lf, detected_eol)``.

    The EOL style must be detected on the RAW bytes: ``read_text`` applies
    universal-newline translation, so the decoded string alone can no longer
    tell CRLF from LF.
    """
    raw = path.read_bytes().decode("utf-8")
    newline = _detect_newline(raw)
    return raw.replace("\r\n", "\n").replace("\r", "\n"), newline


def _write_text_preserving_newline(path: Path | str, text: str, newline: str) -> None:
    """Write ``text`` with an explicit EOL style and no platform translation.

    ``text`` is normalized to ``\\n`` first (``read_text`` applies universal
    newlines and ``json.dumps`` always emits ``\\n``), so converting never
    doubles ``\\r``. ``newline=""`` disables Python's own output translation.
    """
    path = Path(path)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    payload = normalized if newline == "\n" else normalized.replace("\n", newline)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(payload)


def _skip_string_end(text: str, i: int) -> int:
    """Return the index just after the string literal starting at ``text[i] == '"'``."""
    i += 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            return i + 1
        i += 1
    raise ValueError("unterminated string")


def strip_jsonc_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments (string-aware).

    Line comments are replaced by a newline so line numbers stay meaningful.
    """
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                i = n
            else:
                out.append("\n")
                i = j + 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated block comment")
            i = j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Remove commas that directly precede ``}`` / ``]`` (string-aware)."""
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1  # drop the trailing comma
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_jsonc(text: str) -> dict:
    """Parse jsonc text into a dict (comments, BOM and trailing commas tolerated).

    Raises :class:`ValueError` when the text is not parseable or the root is not
    an object.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    cleaned = _strip_trailing_commas(strip_jsonc_comments(text))
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid jsonc at line {exc.lineno} col {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")
    return data


def read_config(path: Path | str) -> dict:
    """Read and parse a jsonc config file into a dict.

    Raises :class:`FileNotFoundError` when ``path`` does not exist and
    :class:`ValueError` when it is unparseable.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return parse_jsonc(fh.read())


def list_servers(cfg: dict) -> list[dict]:
    """Unified, deterministic view of every MCP server in ``cfg``.

    Each entry is ``{"name", "scope" ("v2"|"legacy"), "value"}``. Both the V2
    ``mcp.servers`` map and the legacy ``mcpServers`` map are included so callers
    can dedupe across scopes.
    """
    view = []
    mcp = cfg.get("mcp") if isinstance(cfg, dict) else None
    servers_v2 = mcp.get("servers") if isinstance(mcp, dict) else None
    if isinstance(servers_v2, dict):
        view += [
            {"name": name, "scope": "v2", "value": value}
            for name, value in servers_v2.items()
        ]
    legacy = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    if isinstance(legacy, dict):
        view += [
            {"name": name, "scope": "legacy", "value": value}
            for name, value in legacy.items()
        ]
    return sorted(view, key=lambda item: (item["scope"], item["name"]))


def server_names(cfg: dict) -> set[str]:
    """Every server name present in either config map."""
    return {item["name"] for item in list_servers(cfg)}


def backup_config(
    path: Path | str,
    *,
    target: Path | str | None = None,
    label: str = "config",
    timestamp: str | None = None,
) -> Path:
    """Copy ``path`` to ``<target>/.se/backups/<label>-<timestamp>.jsonc``.

    The backup directory is created as needed. ``timestamp`` is injectable for
    deterministic tests.
    """
    path = Path(path)
    target = Path(target) if target is not None else path.parent
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir(target) / f"{label}-{ts}.jsonc"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    return backup


# --------------------------------------------------------------------------- #
# Surgical removal (byte-preserving)
# --------------------------------------------------------------------------- #


def _skip_ws_and_comments(text: str, i: int) -> int:
    """Advance past whitespace and jsonc comments (string-free zones only)."""
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated block comment")
            i = j + 2
            continue
        break
    return i


def _match_container(text: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    """Return the index of the closing bracket matching ``text[open_idx]``."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i = _skip_string_end(text, i)
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated block comment")
            i = j + 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unterminated {open_ch!r} container")


def _value_span(text: str, i: int) -> tuple[int, int]:
    """Return ``(start, end)`` of the whole value starting at ``text[i]``.

    ``end`` is exclusive and points just after the value (string, container or
    scalar). Raises :class:`ValueError` when the region is malformed.
    """
    ch = text[i]
    if ch == '"':
        return i, _skip_string_end(text, i)
    if ch == "{":
        return i, _match_container(text, i, "{", "}") + 1
    if ch == "[":
        return i, _match_container(text, i, "[", "]") + 1
    j = i
    n = len(text)
    while j < n and text[j] not in " \t\r\n,}]":
        j += 1
    if j == i:
        raise ValueError(f"unexpected token at offset {i}")
    return i, j


def _object_properties(text: str, value_start: int, value_end: int) -> list[tuple]:
    """Top-level ``(key_start, key_text, value_start, value_end)`` of an object.

    ``value_start`` must point at ``{`` and ``value_end`` just past its ``}``.
    Nested containers are skipped via :func:`_value_span`, so only properties at
    the object's own depth are returned.
    """
    if text[value_start] != "{":
        raise ValueError("expected object literal")
    props = []
    i = _skip_ws_and_comments(text, value_start + 1)
    while i < value_end:
        ch = text[i]
        if ch in "},":
            i = _skip_ws_and_comments(text, i + 1)
            continue
        if ch != '"':
            raise ValueError(f"unexpected token at offset {i}")
        key_start = i
        key_end = _skip_string_end(text, i)
        key_text = text[i + 1 : key_end - 1]
        j = _skip_ws_and_comments(text, key_end)
        if j >= len(text) or text[j] != ":":
            raise ValueError("malformed property (expected ':')")
        j = _skip_ws_and_comments(text, j + 1)
        v_start, v_end = _value_span(text, j)
        props.append((key_start, key_text, v_start, v_end))
        i = _skip_ws_and_comments(text, v_end)
    return props


def _locate_property(text: str, path: list[str]) -> tuple | None:
    """Locate the property ``path`` (from the root object) in raw ``text``.

    Returns ``(key_start, key_text, value_start, value_end)`` of the last path
    segment, or ``None`` when any segment is absent. Raises
    :class:`ValueError` when a traversed segment is not an object literal.
    """
    i = _skip_ws_and_comments(text, 0)
    if i >= len(text) or text[i] != "{":
        return None
    container_start, container_end = _value_span(text, i)
    for index, key in enumerate(path):
        props = _object_properties(text, container_start, container_end)
        found = next((p for p in props if p[1] == key), None)
        if found is None:
            return None
        if index == len(path) - 1:
            return found
        key_start, _, v_start, v_end = found
        if text[v_start] != "{":
            raise ValueError(f"path segment {key!r} is not an object literal")
        container_start, container_end = v_start, v_end
    return None


def _entry_span(text: str, key_start: int, value_end: int) -> tuple[int, int]:
    """Extend a property span to include its trailing comma + whitespace.

    The removed region starts at the property key and ends after the property's
    own trailing comma (or right after the value when there is none). Comments
    that follow the comma are preserved as bytes.
    """
    end = _skip_ws_and_comments(text, value_end)
    if end < len(text) and text[end] == ",":
        end = _skip_ws_and_comments(text, end + 1)
    return key_start, end


def _apply_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Remove disjoint ``(start, end)`` spans right-to-left."""
    result = text
    for start, end in sorted(spans, reverse=True):
        result = result[:start] + result[end:]
    return result


def remove_server_text(
    path: Path | str, name: str, *, target: Path | str | None = None
) -> dict:
    """Surgically remove server ``name`` from the config at ``path``.

    Removes the object from ``mcp.servers.<name>`` and/or legacy
    ``mcpServers.<name>``, preserving every other byte exactly. Backs the file
    up to ``<target>/.se/backups/<name>-<timestamp>.jsonc`` before rewriting.

    Returns a structured report::

        {"name", "removed": ["v2"|"legacy", ...], "backup": str|None,
         "changed": bool, "errors": [str, ...]}

    Fail-closed rules:
    * unparseable file -> no rewrite, error naming the file;
    * region cannot be isolated safely (non-object value, malformed text) ->
      no rewrite, error;
    * post-removal reparse fails or other servers change -> no rewrite, error.
    """
    path = Path(path)
    target = Path(target) if target is not None else path.parent
    result = {"name": name, "removed": [], "backup": None, "changed": False, "errors": []}
    if not path.exists():
        result["errors"].append(f"config file not found: {path}")
        return result

    raw, newline = _read_config_text(path)
    try:
        parsed = parse_jsonc(raw)
    except Exception as exc:  # noqa: BLE001 - reported, never rewritten
        result["errors"].append(f"config file unparseable ({path}): {exc}")
        return result

    mcp = parsed.get("mcp")
    servers_v2 = mcp.get("servers") if isinstance(mcp, dict) else None
    legacy = parsed.get("mcpServers")
    locators = []
    if isinstance(servers_v2, dict) and name in servers_v2:
        locators.append(["mcp", "servers", name])
    if isinstance(legacy, dict) and name in legacy:
        locators.append(["mcpServers", name])
    if not locators:
        return result

    spans = []
    try:
        for path_segments in locators:
            entry = _locate_property(raw, path_segments)
            if entry is None:
                raise ValueError(
                    f"could not locate {name!r} ({'/'.join(path_segments[:-1])})"
                )
            key_start, _key_text, v_start, v_end = entry
            if raw[v_start] != "{":
                raise ValueError(
                    f"server {name!r} is not an object literal; cannot isolate for removal"
                )
            spans.append(_entry_span(raw, key_start, v_end))
    except Exception as exc:  # noqa: BLE001 - fail closed, never rewrite
        result["errors"].append(f"cannot isolate {name!r} for removal ({path}): {exc}")
        return result

    new_text = _apply_spans(raw, spans)
    try:
        re_parsed = parse_jsonc(new_text)
    except Exception as exc:  # noqa: BLE001 - fail closed
        result["errors"].append(
            f"post-removal config would be unparseable ({path}): {exc}"
        )
        return result

    re_servers_v2 = re_parsed.get("mcp") if isinstance(re_parsed.get("mcp"), dict) else {}
    if isinstance(re_servers_v2, dict) and name in re_servers_v2:
        result["errors"].append(
            f"post-removal config still contains {name!r}; refusing to write"
        )
        return result
    re_legacy = re_parsed.get("mcpServers")
    if isinstance(re_legacy, dict) and name in re_legacy:
        result["errors"].append(
            f"post-removal config still contains {name!r}; refusing to write"
        )
        return result

    before_others = {
        item["name"]: item["value"]
        for item in list_servers(parsed)
        if item["name"] != name
    }
    after_others = {item["name"]: item["value"] for item in list_servers(re_parsed)}
    if before_others != after_others:
        result["errors"].append(
            "post-removal config changed other servers; refusing to write"
        )
        return result

    backup = backup_config(path, target=target, label=name)
    result["backup"] = str(backup)
    try:
        _write_text_preserving_newline(path, new_text, newline)
    except OSError as exc:
        result["errors"].append(f"cannot write config ({path}): {exc}")
        return result
    result["removed"] = ["v2" if segments[0] == "mcp" else "legacy" for segments in locators]
    result["changed"] = True
    return result


def _indent_fragment(fragment: str, base: str, strip: int = 2) -> str:
    """Re-indent a JSON fragment so every line starts at ``base``.

    ``fragment`` comes from ``json.dumps(..., indent=2)`` sliced to its inner
    lines, so each line already carries ``strip`` leading spaces of base
    indentation; that base is removed and ``base`` prepended instead.
    """
    lines = [
        line[strip:] if line.startswith(" " * strip) else line
        for line in fragment.strip("\n").splitlines()
    ]
    return "\n".join(base + line for line in lines)


def _reindent_value(fragment: str, base: str) -> str:
    """Re-indent a ``json.dumps(..., indent=2)`` value to match its key.

    The opening brace stays inline with the property key (so the caller can
    splice the result right after ``"key": ``); inner lines are indented one
    level past ``base`` and the closing brace sits at ``base``. Single-line
    fragments are returned unchanged.
    """
    lines = fragment.splitlines()
    if len(lines) <= 1:
        return fragment
    out = [lines[0]]
    for line in lines[1:-1]:
        stripped = line[2:] if line.startswith("  ") else line
        out.append(base + "  " + stripped)
    out.append(base + lines[-1])
    return "\n".join(out)


def _insert_property(raw: str, segments: list[str], property_text: str) -> str:
    """Insert a ``"key": value`` block into the object at ``segments``.

    ``segments`` addresses the target object (``[]`` = document root) and must
    already exist. Every other byte of ``raw`` is preserved; the new property is
    placed on its own line before the object's closing brace.
    """
    if segments:
        located = _locate_property(raw, segments)
        if located is None:
            raise ValueError(f"cannot locate {'/'.join(segments)}")
        _key_start, _key_text, obj_start, obj_end = located
        if raw[obj_start] != "{":
            raise ValueError(f"{'/'.join(segments)} is not an object literal")
    else:
        obj_start = raw.index("{")
        obj_end = _match_container(raw, obj_start, "{", "}") + 1

    close_idx = obj_end - 1  # index of the closing '}'
    props = _object_properties(raw, obj_start, obj_end)
    line_start = raw.rfind("\n", 0, close_idx) + 1
    closing_indent = raw[line_start:close_idx]
    if closing_indent.strip():
        closing_indent = ""
    entry = _indent_fragment(property_text, closing_indent + "  ")

    if props:
        content_end = raw[:close_idx].rstrip()
        comma = "" if content_end.endswith(",") else ","
        return content_end + comma + "\n" + entry + "\n" + closing_indent + raw[close_idx:]
    return raw[: obj_start + 1] + "\n" + entry + "\n" + closing_indent + raw[close_idx:]


def add_server_text(
    path: Path | str,
    name: str,
    server_config: dict,
    *,
    target: Path | str | None = None,
) -> dict:
    """Surgically add or update server ``name`` in the config at ``path``.

    Inserts or replaces the object in ``mcp.servers.<name>`` (V2 format),
    preserving every other byte exactly (comments, formatting, whitespace).
    Creates the file with a minimal ``mcp.servers`` structure when it does not
    exist. Backs the file up to ``<target>/.se/backups/<name>-install-<timestamp>.jsonc``
    before rewriting an existing file.

    Returns a structured report:
        {"name", "added": bool, "updated": bool, "backup": str|None, "changed": bool, "errors": [str, ...]}

    Fail-closed rules:
    * unparseable file -> no rewrite, error naming the file;
    * region cannot be isolated safely -> no rewrite, error;
    * post-write reparse fails, the new server is absent/different, or other
      servers change -> no rewrite, error.
    """
    path = Path(path)
    target = Path(target) if target is not None else path.parent
    result = {"name": name, "added": False, "updated": False, "backup": None, "changed": False, "errors": []}

    if not path.exists():
        document = {"mcp": {"servers": {name: server_config}}}
        new_text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_preserving_newline(path, new_text, "\n")
        except OSError as exc:
            result["errors"].append(f"cannot write config ({path}): {exc}")
            return result
        result["added"] = True
        result["changed"] = True
        return result

    raw, newline = _read_config_text(path)
    try:
        parsed = parse_jsonc(raw)
    except Exception as exc:
        result["errors"].append(f"config file unparseable ({path}): {exc}")
        return result
    if not isinstance(parsed, dict):
        result["errors"].append(f"config root must be an object ({path})")
        return result

    mcp = parsed.get("mcp")
    servers = mcp.get("servers") if isinstance(mcp, dict) else None

    try:
        if isinstance(servers, dict) and name in servers:
            located = _locate_property(raw, ["mcp", "servers", name])
            if located is None:
                raise ValueError("could not locate the existing server entry")
            _key_start, _key_text, v_start, v_end = located
            key_line_start = raw.rfind("\n", 0, _key_start) + 1
            key_indent = raw[key_line_start:_key_start]
            if key_indent.strip():
                key_indent = ""
            dumped = json.dumps(server_config, indent=2, ensure_ascii=False)
            new_text = raw[:v_start] + _reindent_value(dumped, key_indent) + raw[v_end:]
            result["updated"] = True
        elif isinstance(servers, dict):
            fragment = json.dumps({name: server_config}, indent=2, ensure_ascii=False)[1:-1]
            new_text = _insert_property(raw, ["mcp", "servers"], fragment)
            result["added"] = True
        elif isinstance(mcp, dict):
            fragment = json.dumps({"servers": {name: server_config}}, indent=2, ensure_ascii=False)[1:-1]
            new_text = _insert_property(raw, ["mcp"], fragment)
            result["added"] = True
        else:
            fragment = json.dumps(
                {"mcp": {"servers": {name: server_config}}}, indent=2, ensure_ascii=False
            )[1:-1]
            new_text = _insert_property(raw, [], fragment)
            result["added"] = True
    except Exception as exc:  # noqa: BLE001 - fail closed, never rewrite
        result["errors"].append(f"cannot isolate insertion point for {name!r} ({path}): {exc}")
        return result

    try:
        re_parsed = parse_jsonc(new_text)
    except Exception as exc:  # noqa: BLE001 - fail closed
        result["errors"].append(f"post-write config would be unparseable ({path}): {exc}")
        return result
    re_mcp = re_parsed.get("mcp") if isinstance(re_parsed, dict) else None
    re_servers = re_mcp.get("servers") if isinstance(re_mcp, dict) else None
    if not isinstance(re_servers, dict) or name not in re_servers:
        result["errors"].append(f"post-write config does not contain {name!r}; refusing to write")
        return result
    if re_servers.get(name) != server_config:
        result["errors"].append(
            f"post-write config {name!r} does not match the declared spec; refusing to write"
        )
        return result

    before_others = {
        item["name"]: item["value"]
        for item in list_servers(parsed)
        if item["name"] != name
    }
    after_others = {
        item["name"]: item["value"]
        for item in list_servers(re_parsed)
        if item["name"] != name
    }
    if before_others != after_others:
        result["errors"].append("post-write config changed other servers; refusing to write")
        return result

    backup = backup_config(path, target=target, label=f"{name}-install")
    result["backup"] = str(backup)
    try:
        _write_text_preserving_newline(path, new_text, newline)
    except OSError as exc:
        result["errors"].append(f"cannot write config ({path}): {exc}")
        return result
    result["changed"] = True
    return result