---
description: Upgrade the installed Master System to a published tag with a verifiable snapshot, rollback and recovery.
agent: devops
---

# upgrade

- **id**: CMD-0025
- **version**: 1.0.0
- **purpose**: Plan (--check/--dry-run) or execute a fail-closed upgrade of the installed Master System: ff-only advance to a published tag, ordered migrations, adapter regeneration, sync, doctor gate, snapshot rollback and interrupted-run recovery.
- **execution_intent**: MUTATE
- **risk_level**: high
- **gate**: None
- **permissions**: READ, ANALYZE, WRITE_DOCS, DEPLOY

## Execution

se upgrade --project $ARGUMENTS

## Arguments

- `--project` (path, optional) — Target system directory (default: current directory).
- `--check` (boolean, optional) — Resolve the target version and run the read-only preflight (writes nothing).
- `--dry-run` (boolean, optional) — Same as --check; report the plan without writing.
- `--json` (boolean, optional) — Emit a machine-readable se.report/1 envelope.
- `--offline` (boolean, optional) — Use local tags only; never invoke git ls-remote.
- `--git-path` (string, optional) — Explicit path to the git binary (when git is not on PATH).
- `--include-projects` (boolean, optional) — Include PROJECTS/ in a snapshot (opt-in; never copied by default).
- `--allow-downgrade` (boolean, optional) — Allow selecting a tag older than the current version.
- `--allow-prerelease` (boolean, optional) — Consider pre-release tags (-rc, -beta) as candidates.
- `--no-sync` (boolean, optional) — Do not require the opencode CLI during preflight and skip the sync step.
- `--recover` (boolean, optional) — Recover an interrupted upgrade from .se/upgrade-in-progress.json (restores the snapshot and resets HEAD).
