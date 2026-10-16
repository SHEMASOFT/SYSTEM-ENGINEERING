"""Intelligence Layer for SYSTEM-ENGINEERING.

Deterministic integration of the three foundations:

* Skill Discovery  -> which skills match the project's capabilities
* Memory Engine    -> what the project already knows (decisions, discoveries)
* Orchestration    -> the deterministic plan for a workflow (dry-run)
* Gates            -> the actionable lifecycle gate for the current state

The layer is READ-ONLY: it aggregates existing facts and emits one
``se.report/1`` envelope. It never mutates project state. Execution stays the
job of ``se execute`` / ``se orchestrate``.

The one cache it may create is the derived memory index under the engine root's
``.se/`` (see ``memory_context``): it is disposable, gitignored and rebuildable,
and it holds nothing that is not already in the project's JSON. Project state
itself is never written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..artifacts import read_manifest
from ..gates import evaluate_gate, load_gate_model
from ..memory.engine import MemoryEngine
from ..orchestration.engine import OrchestrationEngine
from ..paths import now_utc, repo_root
from ..schemas import load_schemas, validate
from ..skills.discovery import discover_skills


def _one_or_mixed(values: List[str]) -> Optional[str]:
    """A single reported value, ``"mixed"`` when they disagree, ``None`` if none.

    Reporting which backend and reranker answered is part of the answer: a
    session must be able to tell "no memories matched" from "no search engine
    was available", and the two are indistinguishable from an empty hit list.
    """
    distinct = sorted({value for value in values if value})
    if not distinct:
        return None
    if len(distinct) == 1:
        return distinct[0]
    return "mixed"


class IntelligenceEngine:
    """Deterministic integration of discovery, memory, orchestration and gates."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else repo_root()

    def _find_project_dir(self, project_id: str) -> Optional[Path]:
        for p in (self.root / "PROJECTS").glob("*"):
            if (p / "PROJECT.json").exists():
                try:
                    if read_manifest(p).get("project_id") == project_id:
                        return p
                except Exception:
                    continue
        return None

    def run(
        self,
        project_id: str,
        capabilities: Optional[List[str]] = None,
        workflow_id: Optional[str] = None,
        execute: bool = False,
        author: Optional[str] = None,
        memory_topics: Optional[List[str]] = None,
        memory_limit: int = 10,
    ) -> Dict[str, Any]:
        """Run the intelligence pipeline for a project (read-only)."""
        project_dir = self._find_project_dir(project_id)
        if project_dir is None:
            raise ValueError(f"Project {project_id} not found")

        manifest = read_manifest(project_dir)
        lifecycle = manifest.get("lifecycle_state") or "UNKNOWN"

        # 1. Skill discovery (deterministic matching, approval policy respected).
        discovery = discover_skills(
            project_id=project_id,
            capabilities=capabilities,
            author=author,
            root=self.root,
        )
        discovered = [
            {
                "skill_id": c.get("skill_id", ""),
                "skill_name": c.get("skill_name", ""),
                "match_score": float(c.get("match_score", 0.0)),
                "requires_approval": bool(c.get("requires_approval", True)),
            }
            for c in discovery.get("candidates", [])
        ]

        # 2. Memory context (recent project knowledge + what the session is about).
        memory_context = self.memory_context(
            project_id,
            topics=memory_topics,
            relevance_limit=memory_limit,
        )

        # 3. Gate evaluation (all gates informative + actionable frontier).
        gate_results: Dict[str, str] = {}
        gate_model = load_gate_model()
        gates = gate_model.get("gates", [])
        for gate in gates:
            gate_id = gate.get("id", "")
            try:
                gate_results[gate_id] = evaluate_gate(project_dir, gate_id).get("status", "UNKNOWN")
            except Exception:
                gate_results[gate_id] = "ERROR"

        applicable = [g for g in gates if g.get("from_state") == lifecycle]
        actionable = self._actionable_gate(applicable, gate_results, lifecycle)

        # 4. Orchestration plan (dry-run only; execution is never implicit).
        workflow_plan = None
        if workflow_id:
            try:
                plan = OrchestrationEngine(root=self.root).execute(
                    workflow_id=workflow_id, project_id=project_id, dry_run=True
                )
                workflow_plan = {
                    "workflow_id": plan.get("workflow_id", workflow_id),
                    "status": plan.get("status", "UNKNOWN"),
                    "execution_order": plan.get("execution_order", []),
                }
            except Exception as exc:
                workflow_plan = {
                    "workflow_id": workflow_id,
                    "status": "ERROR",
                    "execution_order": [],
                    "error": str(exc),
                }

        # 5. Verification aggregation + next action.
        verification, next_action = self._verification(actionable, gate_results, lifecycle)

        result = {
            "schema_version": "1",
            "project_id": project_id,
            "generated_at": now_utc(),
            "capabilities": discovery.get("capabilities_requested", []),
            "discovered_skills": discovered,
            "memory_context": memory_context,
            "workflow": workflow_plan,
            "gates": gate_results,
            "verification": verification,
            "next_action": next_action,
        }

        errors = validate(result, load_schemas(self.root).get("intelligence_result", {}))
        if errors:
            raise ValueError(f"Intelligence result validation failed: {errors}")

        return result

    def memory_context(
        self,
        project_id: str,
        topics: Optional[List[str]] = None,
        recent_limit: int = 20,
        relevance_limit: int = 10,
    ) -> Dict[str, Any]:
        """What the project already knows, shaped for injection into a session.

        Two signals, deliberately separate rather than merged into one list:

        * ``recent`` is what was learned last, regardless of the session's
          subject. It answers "where were we", and it is what the pipeline has
          always reported.
        * ``relevance`` is what matches the topics the caller is about to work
          on. It answers "what do we already know about *this*", and it is empty
          unless the caller states topics, so a run with no subject behaves
          exactly as before.

        Only the derived index cache under ``.se/`` may be created or refreshed
        here, exactly as ``se memory search`` does; nothing under the project is
        written.

        Each topic is one query with the same AND semantics as ``se memory
        search``, and the merged list keeps the order the topics were given with
        the best-ranked hits of each topic first. Scores are backend-relative
        and are therefore never compared *across* topics. The merged list is
        capped at ``relevance_limit`` so the injected context stays bounded no
        matter how many topics are asked for.

        ``topics`` entries that carry no searchable term are dropped from
        ``queries`` rather than failing the run: a session must still start when
        a topic was phrased in a way nothing can be matched from.
        """
        memory = MemoryEngine(root=self.root)
        listing = memory.query(project_id=project_id, limit=recent_limit)
        memories = listing.get("memories", [])
        recent = [
            {
                "memory_id": m.get("memory_id", ""),
                "type": m.get("type", ""),
                "title": (m.get("content") or {}).get("title", ""),
            }
            for m in memories
        ]

        queries: List[str] = []
        hits: List[Dict[str, Any]] = []
        backends: List[str] = []
        rerankers: List[str] = []
        seen: set = set()

        for topic in topics or []:
            text = (topic or "").strip()
            if not text:
                continue
            try:
                found = memory.search(text, project_id=project_id, limit=relevance_limit)
            except ValueError:
                # No searchable term in this topic: it is reported by not being
                # in `queries`, and the rest of the session start still happens.
                continue
            queries.append(text)
            backends.append(found.get("backend", "unknown"))
            reranker = (found.get("reranker") or {}).get("backend")
            if reranker:
                rerankers.append(reranker)
            for hit in found.get("hits", []):
                key = (hit.get("project_id"), hit.get("memory_id"))
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    {
                        "memory_id": hit.get("memory_id", ""),
                        "type": hit.get("type", ""),
                        "score": hit.get("score", 0.0),
                        "snippet": hit.get("snippet", ""),
                    }
                )

        relevance = {
            "queries": queries,
            "hits": hits[:relevance_limit],
            "backend": _one_or_mixed(backends),
            "reranker": _one_or_mixed(rerankers),
        }

        return {
            "total": listing.get("summary", {}).get("total", len(memories)),
            "by_type": listing.get("summary", {}).get("by_type", {}),
            "recent": recent,
            "relevance": relevance,
        }

    @staticmethod
    def _actionable_gate(applicable, gate_results, lifecycle):
        """Return the gate(s) that can be advanced from the current lifecycle state."""
        if not applicable:
            return []
        out = []
        for gate in applicable:
            gate_id = gate.get("id", "")
            out.append({
                "id": gate_id,
                "to_state": gate.get("to_state"),
                "status": gate_results.get(gate_id, "UNKNOWN"),
            })
        return out

    @staticmethod
    def _verification(actionable, gate_results, lifecycle):
        """Deterministic verification status + next action from the actionable gate."""
        if not actionable:
            return (
                {"status": "UNKNOWN", "checks": []},
                f"no gate applies from state {lifecycle}; verify lifecycle state",
            )

        checks = [
            {"name": a["id"], "status": a["status"], "detail": f"to {a['to_state']}"}
            for a in actionable
        ]
        statuses = {a["status"] for a in actionable}

        if "FAIL" in statuses or "ERROR" in statuses:
            target = next(a for a in actionable if a["status"] in ("FAIL", "ERROR"))
            return (
                {"status": "FAIL", "checks": checks},
                f"resolve blocking conditions of gate {target['id']} (se gate --gate {target['id']})",
            )
        if "MANUAL" in statuses:
            target = next(a for a in actionable if a["status"] == "MANUAL")
            return (
                {"status": "WARN", "checks": checks},
                f"advance {target['id']} to {target['to_state']} (se transition --to {target['to_state']} --attest <reason>)",
            )
        target = actionable[0]
        return (
            {"status": "PASS", "checks": checks},
            f"all conditions met; advance {target['id']} to {target['to_state']} (se transition --to {target['to_state']})",
        )
