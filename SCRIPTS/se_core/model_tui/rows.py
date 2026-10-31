"""Agent row definitions for the model picker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentRow:
    """Definition of an agent row in the picker."""
    agent_id: str
    display_name: str
    category: str
    description: str = ""


# SE SHEMA-AI Agent definitions
# Ordered by orchestration layer
AGENT_ROWS: list[AgentRow] = [
    # Coordinator (primary agent)
    AgentRow(
        agent_id="shema-ai-coordinador",
        display_name="shema-ai-coordinador (coordinator)",
        category="orchestration",
        description="Orchestrates lifecycle, routes work, enforces gates",
    ),
    # Core agents
    AgentRow(
        agent_id="analyst",
        display_name="analyst",
        category="analysis",
        description="Formalize requirements, assumptions, constraints, risks",
    ),
    AgentRow(
        agent_id="planner",
        display_name="planner",
        category="planning",
        description="Decompose requirements into traceable task plans",
    ),
    AgentRow(
        agent_id="architect",
        display_name="architect",
        category="design",
        description="Define architecture and design satisfying requirements",
    ),
    AgentRow(
        agent_id="implementer",
        display_name="implementer",
        category="implementation",
        description="Implement authorized tasks with verifiable artifacts",
    ),
    AgentRow(
        agent_id="tester",
        display_name="tester",
        category="verification",
        description="Verify implementation satisfies requirements",
    ),
    AgentRow(
        agent_id="reviewer",
        display_name="reviewer",
        category="assurance",
        description="Independent review of artifacts, evidence, process",
    ),
    AgentRow(
        agent_id="security",
        display_name="security",
        category="security",
        description="Identify security risks and produce security evidence",
    ),
    AgentRow(
        agent_id="devops",
        display_name="devops",
        category="operations",
        description="Prepare deployment, operations and rollback",
    ),
    AgentRow(
        agent_id="documentation",
        display_name="documentation",
        category="documentation",
        description="Produce and maintain clear documentation",
    ),
    AgentRow(
        agent_id="visual",
        display_name="visual",
        category="design",
        description="Produce visual, media and design deliverables",
    ),
    AgentRow(
        agent_id="explorer",
        display_name="explorer",
        category="discovery",
        description="Discover context, constraints, unknowns before planning",
    ),
]

# Categories for grouping
AGENT_CATEGORIES = {
    "orchestration": "Orchestration",
    "analysis": "Analysis",
    "planning": "Planning",
    "design": "Design",
    "implementation": "Implementation",
    "verification": "Verification",
    "assurance": "Assurance",
    "security": "Security",
    "operations": "Operations",
    "documentation": "Documentation",
    "discovery": "Discovery",
}


def get_agents_by_category() -> dict[str, list[AgentRow]]:
    """Get agents grouped by category."""
    result: dict[str, list[AgentRow]] = {}
    for row in AGENT_ROWS:
        result.setdefault(row.category, []).append(row)
    return result