# AGENTS

Agent definitions follow [`_contract/agent.schema.json`](_contract/agent.schema.json).

Every agent declares: `purpose`, `responsibilities`, `inputs`, `outputs`, `permissions`,
`restrictions`, `activation_conditions`, `verification_requirements` and (optionally)
`gate_responsibility`.

Permission model (`CORE/policies/permissions.json`):
`READ`, `ANALYZE`, `WRITE_DOCS`, `IMPLEMENT`, `TEST`, `DEPLOY`, `DESTRUCTIVE`.

Hard rules:

- `DESTRUCTIVE` is granted to **no agent by default**.
- No agent may bypass a gate or self-approve a `manual_attestation` condition.
- An agent's effective permissions are the **intersection** of its declared permissions
  and a task's `authorized_actions`.
- Agents produce artifacts and evidence; they do not grant themselves authority.

The 12 initial agents:

| Agent | Primary focus | Notable permissions |
|-------|---------------|---------------------|
| coordinator | Orchestration, gates, traceability | READ, ANALYZE, WRITE_DOCS |
| explorer | Discovery and context | READ, ANALYZE |
| analyst | Analysis, requirements, risk | READ, ANALYZE, WRITE_DOCS |
| architect | Architecture and design | READ, ANALYZE, WRITE_DOCS |
| planner | Planning and task decomposition | READ, ANALYZE, WRITE_DOCS |
| implementer | Implementation | READ, ANALYZE, WRITE_DOCS, IMPLEMENT, TEST |
| tester | Verification and evidence | READ, ANALYZE, TEST, WRITE_DOCS |
| reviewer | Independent review | READ, ANALYZE, WRITE_DOCS |
| security | Security analysis and evidence | READ, ANALYZE, TEST, WRITE_DOCS |
| documentation | Documentation and release notes | READ, ANALYZE, WRITE_DOCS |
| devops | Deployment and operations | READ, ANALYZE, WRITE_DOCS, IMPLEMENT, TEST, DEPLOY |
| visual | Visual and media deliverables | READ, ANALYZE, WRITE_DOCS, IMPLEMENT |

Definitions live in `<agent>/agent.json`.
