#!/usr/bin/env python3
"""MCP Skill Server for SYSTEM-ENGINEERING.

Exposes skill operations as MCP tools for lazy-loading skills on demand.

Tools exposed:
- skill_sdd_create: Create a new SDD artifact
- skill_sdd_validate: Validate an SDD artifact
- skill_sdd_list: List SDD artifacts in a project
- skill_odd_create: Create a new ODD artifact
- skill_odd_validate: Validate an ODD artifact against schema
- skill_odd_evaluate: Evaluate an ODD artifact
- skill_odd_list: List ODD artifacts in a project
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path for imports
SE_ROOT = Path(os.environ.get("SE_ROOT") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(SE_ROOT / "SCRIPTS"))

from se_core.commands import (
    create_record,
    COLLECTIONS,
    ID_FIELD,
    all_collections,
    read_manifest,
    write_artifact,
)
from se_core.paths import repo_root
from se_core.schemas import load_schemas, validate


# MCP Protocol constants
MCP_VERSION = "2024-11-05"


def _log(msg: str) -> None:
    """Log to stderr (stdout is reserved for JSON-RPC)."""
    print(f"[se-skill-server] {msg}", file=sys.stderr, flush=True)


def _reply(request_id: Any, result: Any = None, error: Dict = None) -> Dict:
    """Build JSON-RPC response."""
    resp = {"jsonrpc": "2.0", "id": request_id}
    if error:
        resp["error"] = error
    else:
        resp["result"] = result
    return resp


def _error(code: int, message: str, data: Any = None) -> Dict:
    """Build JSON-RPC error."""
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


class SkillServer:
    """MCP Skill Server implementation."""

    def __init__(self):
        self.project_root: Optional[Path] = None
        self.project_id: Optional[str] = None
        self._schemas = None

    def initialize(self, params: Dict) -> Dict:
        """Initialize the server with project context."""
        self.project_root = Path(params.get("project_root", repo_root()))
        project_id = params.get("project_id")
        if project_id:
            self.project_id = project_id
        else:
            # Try to detect from project directory
            for proj_dir in (self.project_root / "PROJECTS").glob("*"):
                manifest = proj_dir / "PROJECT.json"
                if manifest.exists():
                    self.project_id = proj_dir.name
                    break
        _log(f"Initialized: root={self.project_root}, project_id={self.project_id}")
        return {
            "protocolVersion": MCP_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "se-skill-server", "version": "0.1.0"}
        }

    def list_tools(self) -> List[Dict]:
        """Return available MCP tools."""
        return [
            {
                "name": "skill_sdd_create",
                "description": "Create a new SDD (Software Design Document) artifact",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                        "title": {"type": "string", "description": "SDD title"},
                        "context": {"type": "string", "description": "Design context"},
                    },
                    "required": ["project", "title", "context"],
                },
            },
            {
                "name": "skill_sdd_validate",
                "description": "Validate an SDD artifact against schema",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                        "sdd_id": {"type": "string", "description": "SDD ID (e.g., SDD-0001)"},
                    },
                    "required": ["project", "sdd_id"],
                },
            },
            {
                "name": "skill_sdd_list",
                "description": "List all SDD artifacts in a project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                    },
                    "required": ["project"],
                },
            },
            {
                "name": "skill_odd_create",
                "description": "Create a new ODD (Open Design Document) artifact",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                        "title": {"type": "string", "description": "ODD title"},
                        "context": {"type": "string", "description": "Design context"},
                        "problem": {"type": "string", "description": "Problem statement"},
                        "alternatives": {
                            "type": "array",
                            "description": "Alternative approaches to evaluate",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "pros": {"type": "array", "items": {"type": "string"}},
                                    "cons": {"type": "array", "items": {"type": "string"}},
                                    "estimated_effort": {"type": "string", "enum": ["small", "medium", "large"]},
                                    "decision": {"type": "string", "enum": ["chosen", "rejected", "deferred"]}
                                },
                                "required": ["id", "name", "description", "pros", "cons", "estimated_effort", "decision"]
                            }
                        }
                    },
                    "required": ["project", "title", "context", "problem"],
                },
            },
            {
                "name": "skill_odd_validate",
                "description": "Validate an ODD artifact against schema",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                        "odd_id": {"type": "string", "description": "ODD ID (e.g., ODD-0001)"},
                    },
                    "required": ["project", "odd_id"],
                },
            },
            {
                "name": "skill_odd_evaluate",
                "description": "Evaluate an ODD artifact",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                        "odd_id": {"type": "string", "description": "ODD ID (e.g., ODD-0001)"},
                    },
                    "required": ["project", "odd_id"],
                },
            },
            {
                "name": "skill_odd_list",
                "description": "List all ODD artifacts in a project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                    },
                    "required": ["project"],
                },
            },
            {
                "name": "skill_rdd_create",
                "description": "Create a new RDD (review receipt) that binds a verdict to a change candidate and its evidence",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                        "title": {"type": "string", "description": "Receipt title"},
                        "candidate": {
                            "type": "object",
                            "description": "The exact artifact under review",
                            "properties": {
                                "kind": {"type": "string", "enum": ["commit", "worktree", "artifact", "release", "patch"]},
                                "ref": {"type": "string"},
                                "hash": {"type": "string"},
                                "captured_at": {"type": "string"},
                            },
                            "required": ["kind", "ref", "hash"],
                        },
                        "verdict": {"type": "string", "enum": ["PASS", "PARTIAL", "BLOCKED", "FAIL"]},
                        "evidence": {
                            "type": "array",
                            "description": "Evidence supporting the verdict",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "claim": {"type": "string"},
                                    "result": {"type": "string", "enum": ["PASS", "PARTIAL", "BLOCKED", "FAIL", "INFO"]},
                                    "path": {"type": "string"},
                                },
                                "required": ["id", "claim", "result"],
                            },
                        },
                        "linked_change": {"type": "string", "description": "Task/artifact id this review belongs to"},
                        "scope": {"type": "string", "description": "What was reviewed"},
                    },
                    "required": ["project", "title"],
                },
            },
            {
                "name": "skill_rdd_validate",
                "description": "Validate an RDD artifact against schema",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                        "rdd_id": {"type": "string", "description": "RDD ID (e.g., RDD-0001)"},
                    },
                    "required": ["project", "rdd_id"],
                },
            },
            {
                "name": "skill_rdd_list",
                "description": "List all RDD artifacts in a project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project directory name"},
                    },
                    "required": ["project"],
                },
            },
            {
                "name": "skill_catalog_list",
                "description": "List skills in the SE skill catalog with optional category filter.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "Filter by category (optional)"},
                    },
                },
            },
            {
                "name": "skill_catalog_search",
                "description": "Search skills by keyword in name, purpose, or tags.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keyword"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "skill_catalog_show",
                "description": "Show full details of a skill from the catalog.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "skill_catalog_validate",
                "description": "Validate a skill structure and run security scan.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name to validate"},
                    },
                    "required": ["name"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        """Execute a tool."""
        try:
            if name == "skill_sdd_create":
                return self._sdd_create(arguments)
            elif name == "skill_sdd_validate":
                return self._sdd_validate(arguments)
            elif name == "skill_sdd_list":
                return self._sdd_list(arguments)
            elif name == "skill_odd_create":
                return self._odd_create(arguments)
            elif name == "skill_odd_validate":
                return self._odd_validate(arguments)
            elif name == "skill_odd_evaluate":
                return self._odd_evaluate(arguments)
            elif name == "skill_odd_list":
                return self._odd_list(arguments)
            elif name == "skill_rdd_create":
                return self._rdd_create(arguments)
            elif name == "skill_rdd_validate":
                return self._rdd_validate(arguments)
            elif name == "skill_rdd_list":
                return self._rdd_list(arguments)
            elif name == "skill_catalog_list":
                return self._catalog_list(arguments)
            elif name == "skill_catalog_search":
                return self._catalog_search(arguments)
            elif name == "skill_catalog_show":
                return self._catalog_show(arguments)
            elif name == "skill_catalog_validate":
                return self._catalog_validate(arguments)
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            _log(f"Tool {name} error: {e}")
            return {"error": str(e)}

    def _get_project_dir(self, project: str) -> Path:
        """Get project directory path."""
        if self.project_root:
            return self.project_root / "PROJECTS" / project
        return repo_root() / "PROJECTS" / project

    def _sdd_create(self, args: Dict) -> Dict:
        project = args["project"]
        project_dir = self._get_project_dir(args["project"])
        overrides = {
            "title": args["title"],
            "context": args["context"],
        }
        path, identifier, errors = create_record(
            Path(project_dir), "sdd", overrides
        )
        if errors:
            return {"error": errors}
        return {"sdd_id": identifier, "path": str(path.relative_to(self.project_root))}

    def _sdd_validate(self, args: Dict) -> Dict:
        project = args["project"]
        sdd_id = args["sdd_id"]
        project_dir = self._get_project_dir(args["project"])
        sdd_path = project_dir / "sdds" / f"{sdd_id}.json"
        if not sdd_path.exists():
            return {"error": f"SDD {sdd_id} not found"}
        from se_core.paths import load_json, repo_root
        sdd = load_json(sdd_path)
        schemas = self._get_schemas()
        errors = validate(sdd, schemas["sdd"])
        return {"valid": len(errors) == 0, "errors": errors}

    def _sdd_list(self, args: Dict) -> Dict:
        project_dir = self._get_project_dir(args["project"])
        items, _ = all_collections(project_dir).get("sdd", ([], []))
        sdds = [{"id": d.get("sdd_id"), "title": d.get("title"), "status": d.get("status")} for _, d in items]
        return {"sdds": sdds}

    def _odd_create(self, args: Dict) -> Dict:
        project = args["project"]
        project_dir = self._get_project_dir(args["project"])
        overrides = {
            "title": args["title"],
            "context": args["context"],
            "problem": args["problem"],
        }
        if "alternatives" in args:
            overrides["alternatives"] = args["alternatives"]
        path, identifier, errors = create_record(
            Path(project_dir), "odd", overrides
        )
        if errors:
            return {"error": errors}
        return {"odd_id": identifier, "path": str(path.relative_to(self.project_root))}

    def _odd_validate(self, args: Dict) -> Dict:
        """Validate an ODD artifact against schema."""
        return self._odd_evaluate(args)

    def _odd_evaluate(self, args: Dict) -> Dict:
        project = args["project"]
        odd_id = args["odd_id"]
        project_dir = self._get_project_dir(args["project"])
        odd_path = project_dir / "odds" / f"{odd_id}.json"
        if not odd_path.exists():
            return {"error": f"ODD {odd_id} not found"}
        from se_core.paths import load_json
        odd = load_json(odd_path)
        schemas = self._get_schemas()
        errors = validate(odd, schemas["odd"])
        return {"valid": len(errors) == 0, "errors": errors}

    def _odd_list(self, args: Dict) -> Dict:
        project_dir = self._get_project_dir(args["project"])
        items, _ = all_collections(project_dir).get("odd", ([], []))
        odds = [{"id": d.get("odd_id"), "title": d.get("title"), "status": d.get("status")} for _, d in items]
        return {"odds": odds}

    def _rdd_create(self, args: Dict) -> Dict:
        project_dir = self._get_project_dir(args["project"])
        overrides = {"title": args["title"]}
        for key in ("candidate", "verdict", "evidence", "linked_change", "scope"):
            if key in args and args[key] is not None:
                overrides[key] = args[key]
        path, identifier, errors = create_record(
            Path(project_dir), "rdd", overrides
        )
        if errors:
            return {"error": errors}
        return {"rdd_id": identifier, "path": str(path.relative_to(self.project_root))}

    def _rdd_validate(self, args: Dict) -> Dict:
        rdd_id = args["rdd_id"]
        project_dir = self._get_project_dir(args["project"])
        rdd_path = project_dir / "rdds" / f"{rdd_id}.json"
        if not rdd_path.exists():
            return {"error": f"RDD {rdd_id} not found"}
        from se_core.paths import load_json
        rdd = load_json(rdd_path)
        schemas = self._get_schemas()
        errors = validate(rdd, schemas["rdd"])
        return {"valid": len(errors) == 0, "errors": errors}

    def _rdd_list(self, args: Dict) -> Dict:
        project_dir = self._get_project_dir(args["project"])
        items, _ = all_collections(project_dir).get("rdd", ([], []))
        rdds = [
            {
                "id": d.get("rdd_id"),
                "title": d.get("title"),
                "status": d.get("status"),
                "verdict": d.get("verdict"),
                "candidate": (d.get("candidate") or {}).get("ref"),
            }
            for _, d in items
        ]
        return {"rdds": rdds}

    def _catalog_path(self) -> Path:
        """Path to the skill catalog file."""
        return repo_root() / "CATALOG" / "skills.json"

    def _load_catalog(self) -> Dict:
        """Load the skill catalog. Returns empty list if not found."""
        path = self._catalog_path()
        if not path.exists():
            return {"catalog_version": "1", "skills": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _catalog_list(self, args: Dict) -> Dict:
        catalog = self._load_catalog()
        skills = catalog.get("skills", [])
        category = args.get("category")
        if category:
            skills = [s for s in skills if s.get("category") == category]
        compact = []
        for s in skills:
            compact.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "category": s.get("category"),
                "version": s.get("version"),
                "risk_level": s.get("risk_level"),
                "validation_status": s.get("validation_status"),
                "installation_state": s.get("installation_state"),
            })
        return {"skills": compact, "total": len(compact)}

    def _catalog_search(self, args: Dict) -> Dict:
        query = args.get("query", "").lower()
        catalog = self._load_catalog()
        skills = catalog.get("skills", [])
        results = []
        for s in skills:
            searchable = " ".join([
                s.get("name", ""),
                s.get("purpose", ""),
                s.get("category", ""),
                " ".join(s.get("tags", [])),
            ]).lower()
            if query in searchable:
                results.append({
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "category": s.get("category"),
                    "purpose": s.get("purpose", "")[:120],
                    "risk_level": s.get("risk_level"),
                })
        return {"results": results, "total": len(results)}

    def _catalog_show(self, args: Dict) -> Dict:
        name = args.get("name")
        catalog = self._load_catalog()
        for s in catalog.get("skills", []):
            if s.get("name") == name:
                return s
        return {"error": f"Skill '{name}' not found in catalog"}

    def _catalog_validate(self, args: Dict) -> Dict:
        name = args.get("name")
        # Find skill in catalog
        catalog = self._load_catalog()
        entry = None
        for s in catalog.get("skills", []):
            if s.get("name") == name:
                entry = s
                break
        if not entry:
            return {"error": f"Skill '{name}' not found in catalog"}

        # Read SKILL.md if installed
        skill_dir = repo_root() / entry.get("path", f"SKILLS/{name}")
        skill_md_path = skill_dir / "SKILL.md"
        skill_json_path = skill_dir / "SKILL.json"

        issues = []
        if not skill_md_path.exists():
            issues.append("SKILL.md not found")
        if not skill_json_path.exists():
            issues.append("SKILL.json sidecar not found")

        # Security scan
        from se_core.skills.security import scan_skill_content, scan_skill_dir
        content = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""
        security = scan_skill_dir(str(skill_dir), content, entry)

        # Check required fields
        for field in ("id", "name", "purpose", "category", "version"):
            if not entry.get(field):
                issues.append(f"missing required field: {field}")

        return {
            "name": name,
            "valid": len(issues) == 0 and security["risk_level"] != "high",
            "issues": issues,
            "security": security,
        }

    def _get_schemas(self):
        if self._schemas is None:
            self._schemas = load_schemas(repo_root())
        return self._schemas


def main():
    """Main entry point for MCP server (stdio transport)."""
    server = SkillServer()
    
    # Read initialization from stdin
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

    # Send initialization response
    result = server.initialize(init_request.get("params", {}))
    print(json.dumps(_reply(init_request.get("id"), result=result)), flush=True)

    # Process subsequent requests
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
            args = params.get("arguments", {})
            result = server.call_tool(tool_name, args)
            if "error" in result:
                print(json.dumps(_reply(req_id, error=_error(-32603, result["error"]))), flush=True)
            else:
                print(json.dumps(_reply(req_id, result=result)), flush=True)
        elif method == "notifications/initialized":
            # Client confirmed initialization
            pass
        else:
            print(json.dumps(_reply(req_id, error=_error(-32601, f"Method not found: {method}"))), flush=True)


if __name__ == "__main__":
    main()
