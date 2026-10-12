# SCHEMAS

Machine-readable [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/schema)
definitions for the Master System's core records.

| Schema | Validates |
|--------|-----------|
| `project/project.schema.json` | `PROJECT.json` project manifest |
| `objective/objective.schema.json` | Objectives (lifecycle + epistemic status) |
| `requirement/requirement.schema.json` | Requirements, assumptions, constraints, risks, ideas, unknowns |
| `task/task.schema.json` | Tasks |
| `artifact/artifact.schema.json` | Deliverables produced by tasks |
| `evidence/evidence.schema.json` | Evidence objects |
| `acceptance/acceptance.schema.json` | Acceptance decisions |
| `decision/decision.schema.json` | Decisions / ADRs |
| `release/release.schema.json` | Releases |
| `discovery/discovery.schema.json` | `discovery.json` discovery report |
| `../AGENTS/_contract/agent.schema.json` | Agent definitions |
| `../DOMAINS/_contract/domain.schema.json` | Domain packs |
| `agent-contract.schema.json` | Agent contract (superset of the legacy agent definition) |
| `command-contract.schema.json` | Master command interface (`COMMANDS/commands.json`) |
| `skill-contract.schema.json` | Skill contract (sidecar `SKILLS/<skill>/SKILL.json`) |
| `adapter-manifest.schema.json` | Distribution adapter manifests (input contracts, output artifacts, validation) |
| `installation-manifest.schema.json` | Installation manifests written by `se init <project>` (`MASTER-SYSTEM-MANIFEST.json`) |
| `project-context.schema.json` | How a project consumes SYSTEM-ENGINEERING (inheritance + overrides) |

`index.json` maps logical names to schema paths and is the entry point for tooling.

## Contract layer

The contract schemas form the **internal API** between the contract sources and the future
generation adapter (`se adapter opencode`):

```
AGENTS + COMMANDS + SKILLS + POLICIES
                |
                v
   contract schemas (this directory)
                |
                v
      se adapter opencode
                |
                v
 .opencode/agent | .opencode/command | .opencode/skill
```

- `agent-contract.schema.json` validates `AGENTS/<role>/agent.json` and declares the agent
  contract vocabulary (`id`, `version`, `role`, `capabilities`, `lifecycle`) as an optional
  superset of the legacy fields so current definitions validate unchanged.
- `command-contract.schema.json` validates `COMMANDS/commands.json` and adds
  `execution_intent`, `risk_level`, `permissions` and `arguments` as optional fields.
- `skill-contract.schema.json` validates `SKILLS/<skill>/SKILL.json` (sidecar next to the
  human-readable `SKILL.md`).
- `adapter-manifest.schema.json` declares what an adapter consumes (agents, commands, skills,
  policies) and produces (artifacts, generated files, validation metadata with drift check).
- `project-context.schema.json` describes a project's consumption of the Master System:
  inherited policies/skills, required agents and scoped overrides.

Generation flow (implemented since v0.6.0 as `se adapter opencode`): the adapter reads the
contract sources, validates them against the contract schemas, and emits OpenCode assets
(`.opencode/agent|command|skill`) tracked by an adapter manifest whose `validation` section
enables drift detection via `metadata.content_hashes` (checked by `se doctor` -> `adapter`).

Design rules:

- Schemas are **versioned** via the `schema_version` property (currently `"1"`) and the
  repository `VERSION` file.
- Schemas are **self-contained**: no cross-schema `$ref` resolution is required, which
  keeps validation hermetic and dependency-free.
- Strict `additionalProperties: false` plus an optional free-form `metadata` object
  balances validation with domain extensibility.
- Conditional rules (e.g. `BLOCKED` requires a reason; an OBJECTIVE with
  `epistemic_status: FACT` requires evidence) are expressed with `if`/`then`.
- Formats `date` and `date-time` are enforced by a stdlib-only format checker.
