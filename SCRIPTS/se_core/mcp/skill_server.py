#!/usr/bin/env python3
"""MCP Skill Server for SYSTEM-ENGINEERING.

Exposes skill operations as MCP tools for lazy-loading skills on demand.

Tools exposed:
SDD:
- skill_sdd_create: Create a new SDD artifact
- skill_sdd_validate: Validate an SDD artifact
- skill_sdd_list: List SDD artifacts in a project
ODD:
- skill_odd_create: Create a new ODD artifact
- skill_odd_validate: Validate an ODD artifact against schema
- skill_odd_evaluate: Evaluate an ODD artifact
- skill_odd_list: List ODD artifacts in a project
RDD:
- skill_rdd_create: Create a new RDD (review receipt) artifact
- skill_rdd_validate: Validate an RDD artifact
- skill_rdd_list: List RDD artifacts in a project
Catalog:
- skill_catalog_list: List skills in the SE skill catalog
- skill_catalog_search: Search the skill catalog
- skill_catalog_show: Show full details of a skill
- skill_catalog_validate: Validate a skill's structure and run the security scan
- skill_catalog_enable: Enable a skill in the catalog
- skill_catalog_disable: Disable a skill in the catalog
- skill_catalog_remove: Remove a skill from the catalog
- skill_catalog_install: Install a skill from a controlled local source
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
            {
                "name": "skill_catalog_enable",
                "description": "Enable an installed skill (set installation_state to installed). Idempotent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name to enable"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "skill_catalog_disable",
                "description": "Disable an installed skill (set installation_state to disabled). Idempotent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name to disable"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "skill_catalog_remove",
                "description": "Remove a skill from SKILLS/ and update catalog. Requires confirm=true.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name to remove"},
                        "confirm": {"type": "boolean", "description": "Must be true to confirm removal"},
                    },
                    "required": ["name", "confirm"],
                },
            },
            {
                "name": "skill_catalog_install",
                "description": "Install a skill from a local source directory. Validates before activating. Atomic: stages in temp, validates, then activates.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name to install"},
                        "source_path": {"type": "string", "description": "Path to source directory containing SKILL.md and SKILL.json"},
                        "confirm": {"type": "boolean", "description": "Must be true to confirm installation"},
                    },
                    "required": ["name", "source_path", "confirm"],
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
            elif name == "skill_catalog_enable":
                return self._catalog_enable(arguments)
            elif name == "skill_catalog_disable":
                return self._catalog_disable(arguments)
            elif name == "skill_catalog_remove":
                return self._catalog_remove(arguments)
            elif name == "skill_catalog_install":
                return self._catalog_install(arguments)
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
        from se_core.paths import load_json, repo_root, now_utc
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

    def _catalog_enable(self, args: Dict) -> Dict:
        name = args.get("name")
        catalog = self._load_catalog()
        for s in catalog.get("skills", []):
            if s.get("name") == name:
                s["installation_state"] = "installed"
                self._save_catalog(catalog)
                return {"name": name, "installation_state": "installed", "status": "enabled"}
        return {"error": f"Skill '{name}' not found in catalog"}

    def _catalog_disable(self, args: Dict) -> Dict:
        name = args.get("name")
        catalog = self._load_catalog()
        for s in catalog.get("skills", []):
            if s.get("name") == name:
                s["installation_state"] = "disabled"
                self._save_catalog(catalog)
                return {"name": name, "installation_state": "disabled", "status": "disabled"}
        return {"error": f"Skill '{name}' not found in catalog"}

    def _catalog_remove(self, args: Dict) -> Dict:
        name = args.get("name")
        if not args.get("confirm"):
            return {"error": "confirm must be true to remove a skill"}
        catalog = self._load_catalog()
        entry = None
        for s in catalog.get("skills", []):
            if s.get("name") == name:
                entry = s
                break
        if not entry:
            return {"error": f"Skill '{name}' not found in catalog"}

        # Remove directory if it exists
        skill_dir = repo_root() / entry.get("path", f"SKILLS/{name}")
        removed_files = []
        if skill_dir.exists():
            import shutil
            shutil.rmtree(skill_dir)
            removed_files.append(str(skill_dir))

        # Update catalog
        catalog["skills"] = [s for s in catalog.get("skills", []) if s.get("name") != name]
        self._save_catalog(catalog)
        return {"name": name, "status": "removed", "removed_files": removed_files}

    def _save_catalog(self, catalog: Dict) -> None:
        """Save the catalog file atomically."""
        from se_core.paths import write_json_atomic, now_utc
        path = self._catalog_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, catalog)

    @staticmethod
    def _is_symlink_or_reparse(path: Path) -> bool:
        """Detect symlinks and Windows reparse points (junctions, mount points).

        On POSIX, os.path.islink detects symlinks. On Windows, junctions are
        reparse points that islink() may not detect in all Python versions.
        We check both islink() and st_file_attributes (Windows-specific).
        """
        if path.is_symlink():
            return True
        try:
            st = os.stat(str(path), follow_symlinks=False)
        except OSError:
            return False
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & 0x400:
            return True
        return False

    def _catalog_install(self, args: Dict) -> Dict:
        name = args.get("name")
        source_path = args.get("source_path")
        if not args.get("confirm"):
            return {"error": "confirm must be true to install a skill"}

        if not name or not source_path:
            return {"error": "name and source_path are required"}

        # Validate name against skill identifier contract
        import re
        if not re.match(r"^[a-z][a-z0-9-]*$", name):
            return {"error": f"invalid skill name: {name!r} (must match ^[a-z][a-z0-9-]*$)"}

        import shutil, hashlib, json as _json, os, tempfile
        from se_core.paths import write_json_atomic, now_utc

        src = Path(source_path)
        # Reject symlinks (source directory and files)
        if self._is_symlink_or_reparse(src):
            return {"error": f"source_path is a symlink or reparse point (not allowed): {source_path}"}
        if not src.is_dir():
            return {"error": f"source_path is not a directory: {source_path}"}

        # Resolve and verify containment within allowed locations.
        # Allowed: repo_root() and subdirectories (for SE-native skills),
        # or the designated staging directory under the system temp dir.
        try:
            resolved = src.resolve()
        except (OSError, ValueError) as e:
            return {"error": f"source_path cannot be resolved: {e}"}
        allowed_roots = [repo_root().resolve()]
        # Designated temp staging dir for external skill sources
        staging_root = Path(tempfile.gettempdir()).resolve() / "se-skill-sources"
        allowed_roots.append(staging_root)
        if not any(resolved == root or root in resolved.parents for root in allowed_roots):
            return {"error": f"source_path outside allowed locations: {source_path}. Allowed: repo root or {staging_root}"}
        # Reject path traversal components
        if ".." in Path(source_path).parts:
            return {"error": f"source_path contains traversal: {source_path}"}

        src_md = src / "SKILL.md"
        src_json = src / "SKILL.json"
        if self._is_symlink_or_reparse(src_md) or self._is_symlink_or_reparse(src_json):
            return {"error": "SKILL.md or SKILL.json is a symlink or reparse point (not allowed)"}
        if not src_md.is_file():
            return {"error": "SKILL.md not found in source directory"}
        if not src_json.is_file():
            return {"error": "SKILL.json not found in source directory"}

        # Read and validate source
        try:
            sidecar = json.loads(src_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return {"error": f"Invalid SKILL.json: {e}"}

        content = src_md.read_text(encoding="utf-8")

        # Schema validation against skill-contract
        schemas = self._get_schemas()
        schema_errors = validate(sidecar, schemas["skill_contract"])
        if schema_errors:
            return {"error": f"SKILL.json validation failed: {schema_errors}"}

        # Verify declared name matches requested name
        if sidecar.get("name") != name:
            return {"error": f"skill name mismatch: catalog name '{name}' != SKILL.json name '{sidecar.get('name')}'"}

        # Security scan
        from se_core.skills.security import scan_skill_dir
        security = scan_skill_dir(str(src), content, sidecar)
        if security["risk_level"] == "high":
            return {"error": f"Security scan failed (high risk): {security['findings']}"}

        # Check if already installed (filesystem)
        target_dir = repo_root() / "SKILLS" / name
        if target_dir.exists() or target_dir.is_symlink():
            return {"error": f"Skill '{name}' already installed. Use update or remove first."}

        # Check catalog for collisions BEFORE any filesystem changes
        catalog = self._load_catalog()
        for s in catalog.get("skills", []):
            if s.get("id") == sidecar.get("skill_id"):
                return {"error": f"Duplicate skill_id: {sidecar.get('skill_id')}"}
            if s.get("name") == name:
                return {"error": f"Skill '{name}' already in catalog"}

        # Stage in temp directory on same filesystem as destination
        skills_dir = repo_root() / "SKILLS"
        skills_dir.mkdir(parents=True, exist_ok=True)
        stage_parent = None
        stage_dir = None
        activated = False
        try:
            stage_parent = Path(tempfile.mkdtemp(dir=str(skills_dir)))
            stage_dir = stage_parent / name
            stage_dir.mkdir()
            (stage_dir / "SKILL.md").write_text(content, encoding="utf-8")
            (stage_dir / "SKILL.json").write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )

            # Verify staged files
            if not (stage_dir / "SKILL.md").is_file() or not (stage_dir / "SKILL.json").is_file():
                raise RuntimeError("staging failed: files not created")

            # Atomic activation: rename stage dir to target (atomic on same filesystem)
            try:
                os.rename(str(stage_dir), str(target_dir))
                stage_dir = None  # moved, no cleanup needed
                activated = True
            except OSError as e:
                raise RuntimeError(f"activation failed (atomic rename): {e}")

            # Update catalog
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()

            entry = {
                "id": sidecar.get("skill_id"),
                "name": name,
                "purpose": sidecar.get("description", ""),
                "category": sidecar.get("metadata", {}).get("category", "general"),
                "source": "third-party",
                "source_url": sidecar.get("metadata", {}).get("source_url"),
                "maintainer": sidecar.get("metadata", {}).get("maintainer", "unknown"),
                "version": sidecar.get("version", "0.0.0"),
                "license": sidecar.get("license"),
                "provenance": "installed-from-local-source",
                "supported_runtimes": sidecar.get("metadata", {}).get("supported_runtimes", ["opencode"]),
                "dependencies": sidecar.get("dependencies", []),
                "permissions": sidecar.get("capabilities", {}).get("required", []),
                "risk_level": security["risk_level"],
                "validation_status": "validated" if security["risk_level"] != "high" else "rejected",
                "installation_state": "installed",
                "path": f"SKILLS/{name}",
                "skill_md_path": f"SKILLS/{name}/SKILL.md",
                "skill_json_path": f"SKILLS/{name}/SKILL.json",
                "restrictions": sidecar.get("restrictions", []),
                "skill_kind": sidecar.get("skill_kind", "knowledge"),
                "installed_at": now_utc(),
                "checksum": checksum,
            }
            entry = {k: v for k, v in entry.items() if v is not None}

            catalog.setdefault("skills", []).append(entry)
            self._save_catalog(catalog)

            return {
                "name": name,
                "status": "installed",
                "source": source_path,
                "version": sidecar.get("version"),
                "risk_level": security["risk_level"],
                "findings": security["findings"],
                "installed_at": entry.get("installed_at"),
            }

        except Exception as e:
            # Rollback: remove target_dir ONLY if activation succeeded
            if activated and target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            # Remove catalog entry ONLY if activation succeeded
            if activated:
                try:
                    catalog = self._load_catalog()
                    catalog["skills"] = [s for s in catalog.get("skills", []) if s.get("name") != name]
                    self._save_catalog(catalog)
                except Exception:
                    pass
            return {"error": f"installation failed: {e}"}

        finally:
            # Clean up stage directory if it still exists
            if stage_dir is not None and stage_dir.exists():
                shutil.rmtree(stage_dir.parent, ignore_errors=True)
            # Always clean up the temp parent directory if it still exists
            if stage_parent is not None and stage_parent.exists():
                shutil.rmtree(stage_parent, ignore_errors=True)

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

        # JSON-RPC 2.0: notifications (no "id") never get a response. Replying
        # to e.g. "notifications/initialized" with "id": null makes strict MCP
        # clients such as OpenCode V2 log a transport error.
        if req_id is None:
            continue

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
        elif method == "ping":
            print(json.dumps(_reply(req_id, result={})), flush=True)
        else:
            print(json.dumps(_reply(req_id, error=_error(-32601, f"Method not found: {method}"))), flush=True)


if __name__ == "__main__":
    main()
