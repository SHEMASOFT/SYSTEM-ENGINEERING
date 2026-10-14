# COMMANDS

The conceptual command interface. Machine-readable source: [`commands.json`](commands.json).

| Command | Gate | Primary agent | Purpose |
|---------|------|---------------|---------|
| `init` | G0 | coordinator | Create/repair a workspace; seeds `.gitignore` + `discovery.json` without overwriting |
| `explore` | G1 | explorer | Produce a discovery report |
| `new` | — | coordinator | Create a record from its template |
| `update` | — | coordinator | Controlled mutation of an existing record |
| `transition` | varies | coordinator | Advance the lifecycle through gates |
| `plan` | G3 | planner | Check coverage / scaffold tasks |
| `implement` | G4 | implementer | Report actionable tasks |
| `verify` | G5 | tester | Report verification readiness |
| `review` | G6 | reviewer | Static review + coverage (link mismatches are informational) |
| `release` | G7 | devops | Create/approve a release |
| `doctor` | — | coordinator | Validate the Master System |
| `validate` | — | coordinator | Validate schemas/agents/domains/project |
| `gate` | — | coordinator | Evaluate a single gate |
| `capabilities` | — | coordinator | Inspect the capability registry; validate declared policies and resolve a capability plan |
| `context` | — | coordinator | Reconstruct the minimum relevant context (AUTO-02, read-only, on demand) |
| `health` | — | coordinator | Aggregate read-only checks into one deterministic health envelope |
| `auto` | — | coordinator | Decide the next AUTO pipeline step from health (read-only, auditable) |
| `intent` | — | coordinator | Validate and normalize a structured intent into a `se.intent/1` envelope |
| `handoff` | — | coordinator | Create or load a handoff artifact (state, context snapshot, blockers, next actions) |
| `archive` | — | coordinator | Create a tamper-evident `.tar.gz` with SHA-256 hashes and an embedded manifest |
| `restore` | — | coordinator | Restore a project from a verified archive and re-validate it |
| `execute` | G3 | implementer | Execute actionable tasks, fail-closed, with receipts and evidence |
| `observe` | — | implementer | Read-only view of execution progress, evidence, artifacts and receipts |
| `orchestrate` | varies | coordinator | Create/execute/list workflows with topological order and gate enforcement |

Conventions:

- `--project <dir>` targets a managed project workspace.
- Exit codes: `0` success, `1` validation/gate failure, `2` usage error.
- Commands never bypass gates; manual conditions are reported, never auto-passed.
- Read-only inspection commands (`doctor`, `validate`, `review`, `gate`, `capabilities`,
  `context`) accept `--json` to emit a stable, machine-readable `se.report/1` envelope
  (ADR-0022). The default human-readable output is unchanged; JSON is emitted only when
  explicitly requested. `context` reconstructs minimum context (`--scope
  identity|work|authority|trace|deep`, optional `--focus <ID>`); the B1 commands remain a
  serialization surface and perform no reconstruction.

## Lifecycle control

`transition` is a **gate controller**, not a state setter. It only accepts a target state
that has a declared transition from the current state, evaluates the transition's gates, and
refuses to advance on `FAIL`/`WARN`. `MANUAL` conditions require an explicit human
`--attest "<reason>"`, which is recorded in `metadata.transitions`. There is no flag to skip
gates.

## Record creation

`new <record>` generates the next ID, applies the template, sets `project_id`, validates the
result against the schema, and refuses to overwrite an existing file. Artifacts require
`--produced-by`; acceptances require `--scope`, `--decided-by` and `--evidence`; a
`REQUIREMENT` requires `--acceptance-criteria`.

## Record mutation

`update <record> <record-id> --project <dir> [--set FIELD=VALUE]... [--add FIELD=VALUE]...
[--remove FIELD=VALUE]... [--by <human>]` applies a controlled mutation:

- identity fields (`id`/`*_id`, `project_id`, `schema_version`, `created_at`/`collected_at`)
  are **immutable**;
- unknown fields are rejected;
- controlled fields (requirement `status`/`type`, objective `status`/`epistemic_status`,
  acceptance `result`/`decided_by`/`authority`, release `status`/`approval`) require `--by`;
- the complete resulting record is validated against its schema and its references must
  resolve before writing;
- writes are atomic and the original is preserved on any failure;
- each success appends an entry to `<project>/mutation-log.jsonl`.

`metadata` and arrays of objects (e.g. `options_considered`) cannot be edited via the CLI;
edit the file and run `validate`.

The reference implementation is `SCRIPTS/se.py`. The command model is intentionally
tool-independent: the same commands can later be exposed through a CLI, OpenCode, other
agents or automation via `INTEGRATIONS/`.
