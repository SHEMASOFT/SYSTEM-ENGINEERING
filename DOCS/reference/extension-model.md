# Extension Model

Three extension points, in order of preference.

## 1. Domain packs (preferred)

Add `DOMAINS/<id>/domain.json` conforming to
`DOMAINS/_contract/domain.schema.json`. Extend artifacts, gate conditions, agents and
checklists additively. See `DOCS/domains.md`.

## 2. Artifact extensions

If a domain needs a new artifact type, define a schema under `SCHEMAS/<domain>/` and
reference it from the domain pack's `artifact_extensions`. Core schemas are not modified.

## 3. Integrations (adapters)

Tool-specific behavior belongs in `INTEGRATIONS/<tool>/`. Adapters translate between the
tool and the tool-independent contracts (commands, artifacts, gates). CORE and SCHEMAS must
remain free of tool-specific concepts.

## Rules

- Extensions are additive; they never remove or weaken CORE gates.
- New extensions require tests.
- Material shared-behavior changes require an ADR.
- Keep terminology consistent with `DOCS/core-model.md`.
