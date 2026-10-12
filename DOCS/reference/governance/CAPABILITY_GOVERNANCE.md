# Capability Governance (CP-020)

Capability governance is the layer that sits **above providers (MCPs/tools) and below the
workload** (Agents, Skills, Tasks). It answers: *"may this Agent/Skill/Task use this capability in
this context, and why?"* — with a deterministic, auditable answer.

Principle: **Skills, Agents and Tasks declare *capabilities*, never concrete provider names.**
A skill says `documentation.lookup`, not `context7`. The declarative mapping from capability to
provider lives in exactly one place — the canonical capability registry — and is never duplicated
as hard-coded strings scattered around the code.

## 1. Model

```
MCP/tool (provider)  -->  Capability  -->  declared/required by  -->  Agent, Skill, Task
```

- **Provider**: a concrete tool/MCP server (`filesystem`, `context7`, `sequential-thinking`).
  SYSTEM-ENGINEERING **governs use** of providers; it does not own or install them.
- **Capability**: a semantic, provider-neutral ability with an *operation class*
  (`read`, `search`, `write`), e.g. `filesystem.read`, `filesystem.search`, `filesystem.write`,
  `documentation.lookup`, `structured.reasoning`.
- **Operation class** drives READ_ONLY semantics: `write` is the only forbidden class under
  READ_ONLY.

## 2. Canonical registry

`CORE/capabilities/capabilities.json` (schema `SCHEMAS/capability/capability.schema.json`,
registered in `SCHEMAS/index.json`) is the **single source of truth** for:

| Section | Purpose |
|---|---|
| `providers` | provider ids, type (mcp/tool/builtin), endpoint, availability |
| `capabilities` | capability ids, description, operation class, owning provider, availability |
| `operation_classes` | the closed set used to classify capabilities |

A capability is *available* only when both the capability and its provider are `available`.
`se capabilities` prints the registry + mapping; `se doctor` verifies it; `se validate` validates it
against its schema and rejects unknown providers / duplicate ids.

## 3. Declaring policies (optional, additive, backward-compatible)

None of these blocks are required; every pre-CP-020 contract keeps validating as-is.

### Skills — `SKILLS/<name>/SKILL.json`

```jsonc
"capabilities": {
  "required": ["filesystem.read", "filesystem.search"],
  "optional": ["structured.reasoning", "documentation.lookup"]
},
"constraints": { "write": "allowed" }   // or "forbidden"
```

`constraints.write: "forbidden"` is the explicit representation of a **READ_ONLY skill**
(`verification-review` SK-0002 uses it; `checkpoint-release` SK-0001 allows writes).

### Agents — `AGENTS/<role>/agent.json`

```jsonc
"capability_requires": ["filesystem.read", "filesystem.search", "structured.reasoning"]
```

Declared on the canonical agent contract and accepted (optional) by the legacy agent schema, so
migrated agents validate against both. `analyst` (AG-0001) and `documentation` (AG-0005) carry
real declarations.

### Tasks — `TASKS/TASK-####.json`

```jsonc
"capability_policy": {
  "mode": "READ_ONLY",                 // READ_ONLY | READ_WRITE
  "requires": [...], "allows": [...], "denies": [...]
}
```

The example target: review/audit-style tasks forbid writes (`mode: READ_ONLY`); implementation
tasks allow `filesystem.write`.

### Projects — `profiles` (Project Profile)

- `profiles.capability`: capability ids the project **needs** (dots allowed: `filesystem.read`).
- `profiles.toolchain.providers`: provider ids the project **works with**.

`se validate --project` runs capability policy checks; `se capabilities --project [--task]` resolves
the plan for the project/task scope.

## 4. Resolution

Deterministic order, **more specific layer prevails**:

```
SYSTEM (every available capability) -> Project profile -> Agent -> Skill -> Task
```

Statuses: `ALLOW`, `DENY`, `OPTIONAL`, `REQUIRED`. Layer decisions override less specific ones
(e.g. a Task `denies` overrides the SYSTEM default `ALLOW`; a Task `allows` re-grants a write that
a Skill forbids). Every entry carries its `sources` (which layers contributed) and its
`available` flag for auditability.

### READ_ONLY

`mode: READ_ONLY` (task) and `constraints.write: "forbidden"` (skill) are execution-contract
restrictions: all `write`-operation capabilities are `DENY`ed; read/search remain `ALLOW`ed.

### Conflicts (reported, never silent)

- **required-but-denied**: a capability is `REQUIRED` by project/agent/skill/task but ended `DENY`
  (task deny, READ_ONLY, skill write-forbidden).
- **required-but-unavailable**: a `REQUIRED` capability whose provider (or itself) is unavailable.
- **write in READ_ONLY**: a READ_ONLY context `requires`/`allows` a write-operation capability.
- **skill-task conflict**: a Skill forbids writes while the Task requires/allows a write capability.

A plan with any conflict is `CONFLICT`; a clean plan is `PASS`. `se capabilities --check` surfaces
unknown capability ids, unknown providers, requires∩denies overlaps and READ_ONLY inconsistencies
before any plan is resolved.

## 5. Enforcement limits (must be stated)

Governance is **contractual, not mechanical**. It produces a verifiable plan and policy validation,
but SYSTEM-ENGINEERING does not sandbox the runtime: the TRUSTED-instrument boundary is the agent's
frontmatter/prompt and the human checkpoint gates. READ_ONLY is a documented, checked execution
contract — it is not a filesystem ACL. No capability is *invented* for the runtime: if the harness
cannot actually enforce it, it is not claimed.

## 6. Adapter exposure

The OpenCode adapter embeds the registry view in the generated
`.opencode/adapter-manifest.json` as `capability_plan` (schema-validated): `registry`,
`available` ids, and the declarative `mapping` (provider → capabilities → availability). This makes
the capability contract versioned and auditable at runtime without claiming harness enforcement.

## 7. Interface

```text
se capabilities                      # registry + mapping
se capabilities --check [--project P [--task T]]   # validate declared policies
se capabilities --project P [--task T]             # resolved plan (PASS/CONFLICT)
```

## 8. Relationship to Project Profile

Toolchain Profile = what the project works **with**; Capability Profile = what capabilities the
project **needs**. They are distinct concepts and must never be conflated (see
`DOCS/PROJECT_PROFILE.md`). `profiles.capability` describes *needs*; `profiles.toolchain.providers`
declares *availability context* used by `se capabilities --check`.

## 9. Tests

`TESTS/test_capability_governance.py` (35 tests, areas A–N): registry and mapping; skill
required/optional (incl. `documentation.lookup` required + context7 available → RESOLVED);
task allow / deny / READ_ONLY (incl. READ_ONLY + `filesystem.write` → DENIED; implementation task +
`filesystem.write` → ALLOWED); inheritance and precedence; conflict detection; unavailable
capabilities; backward compatibility; adapter `capability_plan`; canonical skills (SK-0002 =
READ_ONLY) and doctor/validate coverage.