# DOMAINS

A **domain pack** extends the domain-agnostic CORE for a specific field without
modifying CORE. Every pack conforms to
[`_contract/domain.schema.json`](_contract/domain.schema.json) and declares:

- `artifact_extensions` — domain-specific artifact types and their schemas;
- `gate_additions` — extra gate conditions (always additive, never removing CORE gates);
- `agent_additions` — specialist roles beyond the 12 core agents;
- `checklists` — required reviews for that domain;
- `tooling` — suggested tooling (informational only).

Rules:

- Domain packs **extend**, never override, CORE.
- A pack with `status: MINIMAL` only establishes its interface; it is a stub, not a
  guarantee of completeness.
- CORE must not import domain-specific concepts.

Initial packs: `software` (FULL), and `security`, `cloud`, `ai-data`, `media`, `design`,
`architecture`, `automation`, `social-media` (MINIMAL).
