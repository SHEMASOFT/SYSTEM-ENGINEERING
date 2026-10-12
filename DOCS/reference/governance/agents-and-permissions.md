# Agents and Permissions

Twelve core agents are defined in `AGENTS/<name>/agent.json` against
`AGENTS/_contract/agent.schema.json`.

| Agent | Focus |
|-------|-------|
| coordinator | Orchestration, gates, traceability |
| explorer | Discovery and context |
| analyst | Analysis, requirements, risk |
| architect | Architecture and design |
| planner | Planning and task decomposition |
| implementer | Implementation |
| tester | Verification and evidence |
| reviewer | Independent review |
| security | Security analysis and evidence |
| documentation | Documentation and release notes |
| devops | Deployment and operations |
| visual | Visual and media deliverables |

Each agent declares purpose, responsibilities, inputs, outputs, permissions, restrictions,
activation conditions, verification requirements and gate responsibility.

## Permission model

`READ`, `ANALYZE`, `WRITE_DOCS`, `IMPLEMENT`, `TEST`, `DEPLOY`, `DESTRUCTIVE`
(`CORE/policies/permissions.json`).

- Effective permissions = agent permissions **intersected with** a task's
  `authorized_actions`.
- `DESTRUCTIVE` is granted to no agent by default.
- `DEPLOY` requires an approved release, a rollback, and explicit environment
  authorization.
- No agent may bypass a gate or self-approve a manual condition.

See `POLICIES/agent-permissions.md` and `POLICIES/destructive-actions.md`.
