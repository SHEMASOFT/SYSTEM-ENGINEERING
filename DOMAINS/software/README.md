# Software Domain Pack

`software` is the first useful domain pack (`status: FULL`). It extends CORE with:

- Artifact extensions: `SOURCE_CODE`, `BUILD`, `TEST_SUITE`, `DEPENDENCY_MANIFEST`.
- Gate additions on G4, G5 and G7 (build, tests, dependency security, reproducible release).
- An additional specialist agent: `code-reviewer`.
- A review checklist covering code review, test coverage, dependency review, input
  validation, secret handling and documentation.

The pack intentionally does **not** mandate a language, framework or CI system. Those are
project decisions recorded as ADRs. This keeps CORE and the pack tool-independent.

A managed project selects domains through `domains` in `PROJECT.json`, e.g.
`["software", "security"]`.
