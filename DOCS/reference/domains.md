# Domain Packs

Domain packs extend CORE additively. Contract:
`DOMAINS/_contract/domain.schema.json`. See `DOMAINS/README.md`.

A pack declares:

- `artifact_extensions` — domain-specific artifact types;
- `gate_additions` — extra, additive gate conditions;
- `agent_additions` — specialist roles;
- `checklists` — required reviews;
- `tooling` — informational suggestions.

Status values:

- `FULL` — usable initial pack. Currently only `software`.
- `MINIMAL` — interface stub; establishes the contract without promising completeness.

Initial packs: `software` (FULL), `security`, `cloud`, `ai-data`, `media`, `design`,
`architecture`, `automation`, `social-media` (MINIMAL).

Projects select packs through `domains` in `PROJECT.json`, e.g.
`["software", "security"]`.

## Extension model (summary)

1. Add a new folder `DOMAINS/<id>/domain.json` conforming to the contract.
2. Add any domain-specific schemas under `SCHEMAS/<id>/` (optional).
3. Add gate additions using existing gate ids.
4. Add tests for the new pack (see `TESTS/test_domains.py`).
5. Record a decision if the pack changes shared behavior.
