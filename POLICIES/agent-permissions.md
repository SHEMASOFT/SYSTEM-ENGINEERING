# Policy: Agent Permissions

Permissions: `READ`, `ANALYZE`, `WRITE_DOCS`, `IMPLEMENT`, `TEST`, `DEPLOY`, `DESTRUCTIVE`.

Rules:

1. An agent's effective permissions are the **intersection** of:
   - the permissions declared in its `agent.json`, and
   - the `authorized_actions` of the task it is working on.
2. `DESTRUCTIVE` is granted to **no agent by default** and requires explicit human
   authorization recorded as a decision.
3. No agent may:
   - bypass, skip or self-approve a gate;
   - satisfy a `manual_attestation` condition on its own;
   - grant permissions to another agent;
   - expand its own scope.
4. `DEPLOY` requires: an APPROVED release, a defined rollback, and explicit authorization
   for the target environment.
5. `IMPLEMENT` is limited to the scope of the authorized task.
6. An agent that finds itself needing more permission must stop and report BLOCKED rather
   than exceed its authority.

Enforcement: agent definitions are validated against `AGENTS/_contract/agent.schema.json`;
tasks declare `authorized_actions`; gates are evaluated before transitions.
