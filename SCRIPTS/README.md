# SCRIPTS

Reference implementation of the Master System. Python 3 standard library, plus
`jsonschema` for validation.

```
python SCRIPTS\se.py <command> [options]
```

| File | Responsibility |
|------|----------------|
| `se.py` | CLI entry point |
| `se_core/paths.py` | Repository root and JSON IO |
| `se_core/schemas.py` | Schema loading and validation |
| `se_core/artifacts.py` | Project workspace artifact collections |
| `se_core/gates.py` | Gate evaluation and checks |
| `se_core/doctor.py` | System doctor checks |
| `se_core/opencode/` | OpenCode adapter (generator, mappings, validators) |
| `se_core/commands.py` | Command implementations |
| `se_core/cli.py` | Argument parsing and dispatch |

This implementation is a **reference**, not the only way to run the system. CORE and
SCHEMAS contain no Python-specific concepts; any tool could implement the same contracts.
