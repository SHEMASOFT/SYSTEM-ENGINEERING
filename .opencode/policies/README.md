# POLICIES

Readable by both humans and agents. Machine-readable permission model:
[`../CORE/policies/permissions.json`](../../CORE/policies/permissions.json).

| Policy | Scope |
|--------|-------|
| [`agent-permissions.md`](agent-permissions.md) | What agents may do |
| [`change-control.md`](change-control.md) | How changes are proposed, reviewed, applied |
| [`evidence.md`](evidence.md) | What counts as evidence |
| [`release.md`](release.md) | Release and rollback requirements |
| [`security.md`](security.md) | Security expectations |
| [`secrets.md`](secrets.md) | Secret handling |
| [`destructive-actions.md`](destructive-actions.md) | Irreversible operations |

Policies are normative for agents. If a policy and a command conflict, the policy wins and
the command must be fixed.
