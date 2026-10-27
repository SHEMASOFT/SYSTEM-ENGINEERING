# INTEGRATIONS

Tool adapters live here. CORE and SCHEMAS must remain free of tool-specific concepts
(ADR-0004).

An adapter translates between a tool and the tool-independent contracts:

- **commands** (`COMMANDS/commands.json`) — expose or invoke `init`, `explore`, `plan`,
  `implement`, `verify`, `review`, `release`, `doctor`;
- **artifacts** (`SCHEMAS/`) — read/write artifacts using the schemas;
- **gates** (`CORE/gates/gates.json`) — evaluate gate conditions.

Available adapters:

| Adapter | Status |
|---------|--------|
| [opencode](opencode/README.md) | Implemented (`se adapter opencode` + `se init <project>`, docs: `DOCS/reference/opencode-adapter.md`, `DOCS/reference/project-bootstrap.md`) |
| [ci](ci/README.md) | Implemented (neutral scripts + GitHub Actions reference workflow; `se validate`/`se gate` adapted, manual conditions reported, never attested) |
| reference CLI (`SCRIPTS/se.py`) | Implemented |

Adding an adapter must not require changes to CORE or SCHEMAS. If it does, that is a design
smell and should be recorded as an ADR.
