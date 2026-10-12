# Policy: Destructive Actions

Destructive operations include deleting data, dropping resources, force-pushing,
rewriting history, or anything irreversible.

Rules:

1. `DESTRUCTIVE` is never granted by default (see `agent-permissions.md`).
2. Destructive actions require:
   - explicit human authorization,
   - a recorded decision (`decisions/ADR-*.json`),
   - a backup or rollback plan,
   - a defined scope.
3. Prefer reversible operations. If none exists, stop and report BLOCKED.
4. Never delete user files or data outside the authorized scope.
5. Never force-push or rewrite published history.
6. In this repository: never modify anything outside `SYSTEM-ENGINEERING`, never touch
   infrastructure belonging to other projects, and never push.
