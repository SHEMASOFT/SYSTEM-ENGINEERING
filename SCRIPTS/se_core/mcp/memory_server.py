"""MCP server exposing SYSTEM-ENGINEERING memory as compact tools.

Independent from se-skill-server: this server owns memory operations only.
Reuses MemoryEngine, schemas, validation and storage without duplicating
business logic.

Transport: stdio (JSON-RPC 2.0), one process per runtime session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from se_core.memory.engine import MemoryEngine
from se_core.paths import repo_root, now_utc


def _log(msg: str) -> None:
    print(f"[se-memory-server] {msg}", file=sys.stderr, flush=True)


def _reply(request_id, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    return resp


def _error(code, message, data=None):
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return e


MCP_VERSION = "2024-11-05"


def _resolve_store(project):
    if project:
        p = Path(project)
        if not (p / "PROJECT.json").exists():
            raise ValueError(f"no PROJECT.json in {p}")
        from se_core.artifacts import read_manifest
        manifest = read_manifest(p)
        pid = manifest.get("project_id", p.name)
        engine = MemoryEngine(root=repo_root())
        return engine, pid

    cwd = Path.cwd().resolve()
    repo = None
    for candidate in [cwd] + list(cwd.parents):
        if (candidate / ".git").exists():
            repo = candidate
            break
    store = (repo / "MEMORY") if repo else (Path.home() / ".se" / "memory")
    store.mkdir(parents=True, exist_ok=True)
    (store / "memories").mkdir(parents=True, exist_ok=True)
    manifest_path = store / "PROJECT.json"
    if not manifest_path.exists():
        now = now_utc()
        data = {
            "schema_version": "1",
            "project_id": "PRJ-GLOBAL",
            "name": "Global Memory",
            "description": "Global memory store for work outside managed projects",
            "owner": "system",
            "domains": ["memory"],
            "criticality": "low",
            "lifecycle_state": "ACTIVE",
            "blocked": False,
            "version": "1.0.0",
            "created_at": now,
            "updated_at": now,
            "master_system_version": "1.0.0",
            "source": "se memory",
            "metadata": {"category": "GLOBAL"},
            "profiles": {"work": {"type": "brownfield", "scale": "small", "risk": "low"}},
        }
        manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    engine = MemoryEngine(root=repo_root(), global_store=store)
    return engine, "PRJ-GLOBAL"


class MemoryServer:
    def __init__(self):
        self.project_root = None
        self.project_id = None

    def initialize(self, params):
        self.project_root = Path(params.get("project_root", repo_root()))
        pid = params.get("project_id")
        if pid:
            self.project_id = pid
        return {
            "protocolVersion": MCP_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "se-memory-server", "version": "1.0.0"},
        }

    def list_tools(self):
        return [
            {
                "name": "memory_search",
                "description": "Search memories by text. Returns compact hits (id, type, score, snippet).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search text"},
                        "project": {"type": "string", "description": "Project directory path (optional; defaults to global store)"},
                        "types": {"type": "string", "description": "Comma-separated memory types"},
                        "tags": {"type": "string", "description": "Comma-separated tags"},
                        "limit": {"type": "integer", "description": "Max results (default 10)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memory_get",
                "description": "Get full content of a memory by ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Memory ID (MEM-XXXX)"},
                        "project": {"type": "string", "description": "Project directory path (optional)"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "memory_save",
                "description": "Save a memory record (decision, discovery, constraint, etc.).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "Memory type"},
                        "content": {"type": "object", "description": "Memory content as JSON object"},
                        "project": {"type": "string", "description": "Project directory path (optional; defaults to global store)"},
                        "tags": {"type": "string", "description": "Comma-separated tags"},
                        "scope": {"type": "string", "description": "Scope: project, global, architecture (default: project)"},
                        "topic_key": {"type": "string", "description": "Upsert key: revises existing record with same key"},
                        "by": {"type": "string", "description": "Author (default: mcp)"},
                    },
                    "required": ["type", "content"],
                },
            },
            {
                "name": "memory_checkpoint",
                "description": "Save a checkpoint memory for task resumption.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Checkpoint summary"},
                        "project": {"type": "string", "description": "Project directory path (optional)"},
                        "tags": {"type": "string", "description": "Comma-separated tags"},
                        "pending": {"type": "array", "items": {"type": "string"}, "description": "Pending tasks"},
                        "decisions": {"type": "array", "items": {"type": "string"}, "description": "Decisions made"},
                        "blockers": {"type": "array", "items": {"type": "string"}, "description": "Current blockers"},
                    },
                    "required": ["summary"],
                },
            },
            {
                "name": "memory_list",
                "description": "List memories with filters. Returns compact summaries.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory path (optional; None = all projects)"},
                        "types": {"type": "string", "description": "Comma-separated memory types"},
                        "tags": {"type": "string", "description": "Comma-separated tags"},
                        "limit": {"type": "integer", "description": "Max results (default 20)"},
                    },
                },
            },
        ]

    def call_tool(self, name, arguments):
        try:
            if name == "memory_search":
                return self._search(arguments)
            elif name == "memory_get":
                return self._get(arguments)
            elif name == "memory_save":
                return self._save(arguments)
            elif name == "memory_checkpoint":
                return self._checkpoint(arguments)
            elif name == "memory_list":
                return self._list(arguments)
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            _log(f"Tool {name} error: {e}")
            return {"error": str(e)}

    def _resolve(self, project):
        return _resolve_store(project)

    def _search(self, args):
        engine, pid = self._resolve(args.get("project"))
        result = engine.search(
            text=args["query"],
            project_id=pid if args.get("project") else None,
            types=args["types"].split(",") if args.get("types") else None,
            limit=args.get("limit", 10),
        )
        hits = result.get("hits", result.get("memories", []))
        compact = []
        for h in hits:
            compact.append({
                "id": h.get("memory_id") or h.get("id"),
                "type": h.get("type"),
                "score": h.get("score"),
                "snippet": (h.get("snippet") or "")[:200],
            })
        return {"hits": compact, "total": len(compact)}

    def _get(self, args):
        engine, pid = self._resolve(args.get("project"))
        record = engine.get(args["memory_id"], pid)
        if not record:
            return {"error": f"Memory {args['memory_id']} not found"}
        return record

    def _save(self, args):
        engine, pid = self._resolve(args.get("project"))
        result = engine.add(
            project_id=pid,
            type=args["type"],
            content=args["content"],
            author=args.get("by", "mcp"),
            scope=args.get("scope", "project"),
            tags=args["tags"].split(",") if args.get("tags") else None,
            topic_key=args.get("topic_key"),
            source="mcp",
        )
        return result

    def _checkpoint(self, args):
        content = {
            "summary": args["summary"],
            "pending": args.get("pending", []),
            "decisions": args.get("decisions", []),
            "blockers": args.get("blockers", []),
        }
        engine, pid = self._resolve(args.get("project"))
        result = engine.add(
            project_id=pid,
            type="checkpoint",
            content=content,
            author="mcp",
            scope="project",
            tags=args["tags"].split(",") if args.get("tags") else None,
            source="mcp",
        )
        return result

    def _list(self, args):
        engine, pid = self._resolve(args.get("project"))
        result = engine.query(
            project_id=pid if args.get("project") else None,
            types=args["types"].split(",") if args.get("types") else None,
            tags=args["tags"].split(",") if args.get("tags") else None,
            limit=args.get("limit", 20),
        )
        items = result.get("memories", [])
        compact = []
        for m in items:
            compact.append({
                "id": m.get("memory_id") or m.get("id"),
                "type": m.get("type"),
                "created_at": m.get("created_at"),
                "tags": m.get("tags", []),
                "summary": (m.get("content", {}).get("summary") or str(m.get("content", "")))[:150],
            })
        return {"memories": compact, "total": len(compact)}


def main():
    """Main entry point for MCP server (stdio transport)."""
    server = MemoryServer()

    line = sys.stdin.readline()
    if not line:
        return

    try:
        init_request = json.loads(line)
    except json.JSONDecodeError as e:
        print(json.dumps(_reply(None, error=_error(-32700, f"Parse error: {e}"))), flush=True)
        return

    if init_request.get("method") != "initialize":
        print(json.dumps(_reply(init_request.get("id"), error=_error(-32600, "Expected initialize"))), flush=True)
        return

    result = server.initialize(init_request.get("params", {}))
    print(json.dumps(_reply(init_request.get("id"), result=result)), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "tools/list":
            tools = server.list_tools()
            print(json.dumps(_reply(req_id, result={"tools": tools})), flush=True)
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            result = server.call_tool(tool_name, arguments)
            print(json.dumps(_reply(req_id, result={"content": [{"type": "text", "text": json.dumps(result)}]})), flush=True)
        else:
            print(json.dumps(_reply(req_id, error=_error(-32601, f"Method not found: {method}"))), flush=True)


if __name__ == "__main__":
    main()
