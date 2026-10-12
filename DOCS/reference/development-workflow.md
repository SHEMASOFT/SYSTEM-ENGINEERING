# Development Workflow

This describes how to work on the Master System itself.

1. **Inspect** the repository and environment before changing anything.
2. **Plan** the change; record material decisions as an ADR in `DOCS/adr/`.
3. **Implement** the smallest change that satisfies the need. Prefer CORE/SCHEMAS changes
   to be schema-driven and tested.
4. **Validate**:
   ```powershell
   python SCRIPTS\se.py doctor
   python SCRIPTS\se.py validate
   python TESTS\run_tests.py
   ```
5. **Review** your own work against the review checklist (`DOCS/development-workflow.md`
   section below and the mission's review requirement).
6. **Commit** only after all validation succeeds. Never push.

## Review checklist

Look specifically for: over-engineering; unnecessary files; inconsistent terminology;
schema contradictions; permission escalation; missing validation; broken references;
undocumented assumptions; tool coupling (OpenCode); external-project coupling; security
problems; impossible workflows; incomplete tests.

## Environment

- Python 3.10+ (reference implementation; developed against 3.14).
- `jsonschema` (required for validation).
- Git (optional; required only for the commit checkpoint).

No other dependencies. Do not install global software without authorization.

## Adding a command

1. Define it in `COMMANDS/commands.json`.
2. Implement it in `SCRIPTS/se_core/commands.py`.
3. Wire it in `SCRIPTS/se_core/cli.py`.
4. Add a test in `TESTS/test_commands.py`.
5. Document it in `DOCS/commands.md`.
