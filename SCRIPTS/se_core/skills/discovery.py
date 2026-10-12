"""Skill Discovery Engine for SYSTEM-ENGINEERING.

Discovers skills matching project capabilities by analyzing:
- Project profile (domains, agents, skills, criticality)
- Skill registry metadata (capabilities, scope, compatibility)
- Policy constraints (approval, experimental, limits)

Produces ranked candidates with match scores and reasoning.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict

from ..paths import repo_root, load_json
from ..schemas import load_schemas, validate


@dataclass
class SkillMatch:
    """A single skill match with scoring and reasoning."""
    skill_id: str
    skill_name: str
    version: str
    match_score: float
    matched_capabilities: List[str]
    reason: str
    source: str  # canonical, project, external
    status: str  # available, installed, deprecated, experimental
    requires_approval: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SkillDiscovery:
    """Skill Discovery Engine.

    Matches project capabilities to available skills using:
    - Direct capability matching
    - Domain/agent affinity
    - Dependency analysis
    - Policy compliance
    """

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else repo_root()
        self._schemas = None
        self._skill_registry = None

    @property
    def schemas(self) -> Dict[str, Any]:
        if self._schemas is None:
            self._schemas = load_schemas(repo_root())
        return self._schemas

    def discover(
        self,
        project_id: str,
        capabilities: Optional[List[str]] = None,
        project_profile: Optional[Dict[str, Any]] = None,
        policy: Optional[Dict[str, Any]] = None,
        author: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Discover skills matching project capabilities.

        Args:
            project_id: Target project (e.g., PRJ-EXAMPLE)
            capabilities: Explicit capabilities to match (e.g., ["verification", "testing"])
            project_profile: Project profile to infer capabilities from
            policy: Discovery policy overrides
            author: Requesting author

        Returns:
            Discovery result as dict (validated against result schema)
        """
        # Load project manifest - find project dir by project_id
        project_dir = None
        for p in (self.root / "PROJECTS").glob("*"):
            if (p / "PROJECT.json").exists():
                from ..artifacts import read_manifest
                manifest = read_manifest(p)
                if manifest.get("project_id") == project_id:
                    project_dir = p
                    break
        if project_dir is None:
            raise ValueError(f"Project {project_id} not found")

        from ..artifacts import read_manifest
        manifest = read_manifest(project_dir)

        # Determine capabilities to match
        target_capabilities = set(capabilities or [])

        # Infer from project profile if provided
        if project_profile:
            target_capabilities.update(self._infer_capabilities(project_profile))

        # Infer from manifest if no explicit capabilities
        if not target_capabilities:
            target_capabilities.update(self._infer_from_manifest(manifest))

        # Load skill registry
        skills = self._load_skill_registry()

        # Match skills to capabilities
        candidates = self._match_skills(target_capabilities, skills)

        # Apply policy
        policy = policy or {}
        max_candidates = policy.get("max_candidates", 10)
        require_approval = policy.get("require_approval", True)
        include_experimental = policy.get("include_experimental", False)

        # Filter and rank
        candidates = self._filter_candidates(candidates, include_experimental)
        candidates = sorted(candidates, key=lambda c: c.match_score, reverse=True)[:policy.get("max_candidates", 10)]

        # Build result
        from ..paths import now_utc
        discovered_at = now_utc()
        request_id = f"SDR-{random.randint(1000, 9999):04d}"

        candidates = self._filter_candidates(candidates, policy.get("include_experimental", False))
        candidates = sorted(candidates, key=lambda c: c.match_score, reverse=True)[:policy.get("max_candidates", 10)]

        result = {
            "schema_version": "1",
            "request_id": f"SDR-{random.randint(1000, 9999):04d}",
            "project_id": project_id,  # This needs fixing
            "discovered_at": now_utc(),
            "capabilities_requested": sorted(target_capabilities),
            "candidates": [c.to_dict() for c in candidates],
            "summary": {
                "total_candidates": len(candidates),
                "by_status": self._count_by_status(candidates),
                "approval_required": sum(1 for c in candidates if c.requires_approval),
            },
        }

        # Validate result
        from ..schemas import load_schemas, validate
        schemas = load_schemas(repo_root())
        errors = validate(result, self.schemas.get("skill_discovery_result", {}))
        if errors:
            raise ValueError(f"Discovery result validation failed: {errors}")

        return result

    def _infer_capabilities(self, profile: Dict[str, Any]) -> Set[str]:
        """Infer capabilities from project profile."""
        capabilities = set()

        # From domains
        domains = profile.get("domains", [])
        domain_capability_map = {
            "security": ["verification", "audit", "compliance", "threat-modeling"],
            "software": ["testing", "build", "deployment", "linting", "documentation"],
            "data": ["validation", "transformation", "quality", "pipeline"],
            "infrastructure": ["provisioning", "monitoring", "scaling", "backup"],
        }
        for domain in domains:
            capabilities.update(domain_capability_map.get(domain, []))

        # From required agents
        agents = profile.get("required_agents", [])
        agent_capability_map = {
            "analyst": ["analysis", "research", "discovery"],
            "architect": ["design", "architecture", "decision"],
            "planner": ["planning", "estimation", "scheduling"],
            "security": ["audit", "compliance", "threat-modeling"],
            "documentation": ["documentation", "technical-writing"],
            "explorer": ["discovery", "research", "analysis"],
            "implementer": ["implementation", "coding", "testing"],
            "reviewer": ["review", "quality-assurance", "code-review"],
            "tester": ["testing", "validation", "quality-assurance"],
            "coordinator": ["coordination", "planning", "governance"],
            "devops": ["deployment", "infrastructure", "automation"],
            "documentation": ["documentation", "technical-writing"],
            "visual": ["visual-design", "ui", "frontend"],
        }
        for agent in agents:
            capabilities.update(agent_capability_map.get(agent, []))

        # From inherited skills
        skills = profile.get("inherited_skills", [])
        skill_capability_map = {
            "verification-review": ["verification", "review", "audit"],
            "checkpoint-release": ["release", "checkpoint", "governance"],
            "dbg-systematic": ["debugging", "analysis", "troubleshooting"],
            "impl-tdd": ["tdd", "testing", "implementation"],
            "rev-adversarial": ["adversarial-review", "security", "audit"],
            "visual-frontend-engineering": ["visual-testing", "frontend", "ui"],
        }
        for skill in skills:
            capabilities.update(skill_capability_map.get(skill, []))

        return capabilities

    def _infer_from_manifest(self, manifest: Dict[str, Any]) -> Set[str]:
        """Infer capabilities from project manifest."""
        capabilities = set()

        # From domains
        for domain in manifest.get("domains", []):
            if domain == "security":
                capabilities.update(["verification", "audit", "compliance"])
            elif domain == "software":
                capabilities.update(["testing", "build", "deployment"])
            elif domain == "data":
                capabilities.update(["validation", "transformation"])

        # From criticality
        criticality = manifest.get("criticality", "unknown")
        if criticality in ("high", "critical"):
            capabilities.update(["verification", "audit", "compliance"])

        return capabilities

    def _load_skill_registry(self) -> List[Dict[str, Any]]:
        """Load all available skills from registry."""
        if self._skill_registry is not None:
            return self._skill_registry

        skills = []

        # Load canonical skills
        skills_dir = self.root / "SKILLS"
        if skills_dir.exists():
            for skill_dir in skills_dir.glob("*"):
                skill_json = skill_dir / "SKILL.json"
                skill_md = skill_dir / "SKILL.md"
                if skill_json.exists():
                    try:
                        data = json.loads(skill_json.read_text(encoding="utf-8"))
                        data["_source"] = "canonical"
                        data["_dir"] = str(skill_dir)
                        data["_has_md"] = skill_md.exists()
                        skills.append(data)
                    except Exception:
                        pass

        # Load project-specific skills (installed)
        projects_dir = self.root / "PROJECTS"
        if projects_dir.exists():
            for project_dir in projects_dir.glob("*"):
                skills_dir = project_dir / "skills"
                if skills_dir.exists():
                    for skill_dir in skills_dir.glob("*"):
                        skill_json = skill_dir / "SKILL.json"
                        if skill_json.exists():
                            try:
                                data = json.loads(skill_json.read_text(encoding="utf-8"))
                                data["_source"] = "project"
                                data["_project"] = project_dir.name
                                skills.append(data)
                            except Exception:
                                pass

        self._skill_registry = skills
        return skills

    def _match_skills(self, capabilities: Set[str], skills: List[Dict]) -> List:
        """Match skills to requested capabilities."""
        from ..schemas import load_schemas
        from ..paths import repo_root
        schemas = load_schemas(repo_root())

        candidates = []

        for skill in skills:
            skill_id = skill.get("skill_id", "")
            skill_name = skill.get("name", "")
            version = skill.get("version", "0.1.0")
            source = skill.get("_source", "unknown")

            # Get skill capabilities from metadata
            skill_caps = set()
            metadata = skill.get("metadata", {})
            if "capabilities" in metadata:
                skill_caps.update(metadata["capabilities"])
            if "capabilities" in skill:
                skill_caps.update(skill.get("capabilities", []))

            # Also check skill description/name for capability keywords
            desc = skill.get("description", "").lower()
            name = skill.get("name", "").lower()
            for cap in ["verification", "audit", "testing", "deployment", "build",
                        "documentation", "debugging", "analysis", "release",
                        "compliance", "security", "linting", "documentation"]:
                if cap in desc or cap in name:
                    skill_caps.add(cap)

            # Calculate match score
            matched = capabilities & skill_caps
            if not capabilities or matched:
                score = len(matched) / len(capabilities) if capabilities else 0.5
                if score > 0 or not capabilities:
                    reason_parts = []
                    if matched:
                        reason_parts.append(f"Matches capabilities: {', '.join(sorted(matched))}")
                    if not capabilities:
                        reason_parts.append("No specific capabilities requested; skill available")
                    reason = "; ".join(reason_parts)

                    candidate = SkillMatch(
                        skill_id=skill.get("skill_id", ""),
                        skill_name=skill.get("name", ""),
                        version=skill.get("version", "0.1.0"),
                        match_score=round(score, 3),
                        matched_capabilities=sorted(matched),
                        reason=reason,
                        source=source,
                        status="available",
                        requires_approval=True,
                    )
                    candidates.append(candidate)

        return candidates

    def _filter_candidates(self, candidates: List, include_experimental: bool) -> List:
        """Filter candidates based on policy."""
        filtered = []
        for c in candidates:
            if c.status == "experimental" and not include_experimental:
                continue
            if c.status == "deprecated":
                continue
            filtered.append(c)
        return filtered

    def _count_by_status(self, candidates: List) -> Dict[str, int]:
        counts = {}
        for c in candidates:
            counts[c.status] = counts.get(c.status, 0) + 1
        return counts

    def _generate_request_id(self) -> str:
        """Generate SDR-XXXX request ID."""
        import random
        return f"SDR-{random.randint(1000, 9999):04d}"


def discover_skills(
    project_id: str,
    capabilities: Optional[List[str]] = None,
    project_profile: Optional[Dict[str, Any]] = None,
    policy: Optional[Dict[str, Any]] = None,
    author: Optional[str] = None,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Convenience function for skill discovery."""
    discovery = SkillDiscovery(root)
    return discovery.discover(project_id, capabilities, project_profile, policy, author)
