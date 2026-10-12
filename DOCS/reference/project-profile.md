# Project Profile

Optional, additive block on `PROJECT.json` / project-context (ARCH-ADAPT-001). Absent = current
behavior. It does **not** change lifecycle, gates, evidence, acceptance or release semantics.

## Shape

```jsonc
"profiles": {
  "work":      { "type": "greenfield|brownfield", "scale": "small|medium|large",
                 "risk": "low|medium|high", "cadence": "<string>" },
  "domain":    [ "<domain-id>" ],
  "toolchain": { "languages": [], "frameworks": [], "platforms": [],
                 "integrations": [], "tools": [], "providers": [] },
  "capability":[ "<capability-id>" ]
}
```

Capability ids (CP-020) are dotted names that refer to the canonical capability registry
(`CORE/capabilities/capabilities.json`), e.g. `filesystem.read`, `documentation.lookup`.
`toolchain.providers` refers to provider ids declared in the same registry (e.g. `context7`,
`filesystem`, `sequential-thinking`). Providers describe infrastructure availability; capabilities
describe what the project needs semantically. Neither list must ever hard-code a provider-specific
string in code — the registry owns the mapping.

## Non-confusion rule (binding)

| Profile | Meaning | Answers |
|---|---|---|
| **Toolchain Profile** | What the project **works with** | languages, frameworks, platforms, integrations, tools |
| **Capability Profile** | What capabilities the project **needs** | e.g. `multi-tenant`, `offline-first`, `audit` |
| **Work Profile** | Nature/size/risk of the work | greenfield/brownfield, scale, risk |
| **Domain Profile** | Business/technical domains | security, software, … |

Toolchain ≠ Capability. They are distinct fields and must never be conflated.

## Validation

- `profiles` is optional; unknown keys inside `profiles`, `work` or `toolchain` are rejected
  (`additionalProperties: false`).
- Existing projects without `profiles` remain valid.

## Relation to existing fields

- `domains` (required) remains the minimal identity field; `profiles.domain` is an optional
  extension, not a replacement.
- `required_agents` / `inherited_skills` remain selection fields; `profiles.capability` describes
  *needs*, not selections.

## Tests

`TESTS/test_project_profile.py`.
