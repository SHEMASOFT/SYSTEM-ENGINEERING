# Contributing

Thanks for your interest in SYSTEM ENGINEERING. This guide covers everything you
need to open a pull request that passes CI.

## Requirements

- Python 3.10+
- git

`se doctor` also needs `jsonschema` (`pip install jsonschema`). `PyYAML` and
`requests` are optional but recommended.

## Setup

```bash
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
cd SYSTEM-ENGINEERING
python -m pip install jsonschema PyYAML requests

python SCRIPTS/se.py doctor      # must be PASS
python SCRIPTS/se.py validate    # must be PASS
python TESTS/run_tests.py        # must be OK
```

On Windows use `python` (not `python3`).

## Workflow

1. Branch from `main` (`feat/...`, `fix/...`, `docs/...`).
2. Keep each pull request focused on one topic.
3. Run the three commands above before pushing.
4. Open a pull request against `main`. CI runs `doctor`, `validate` and the full
   test suite on Linux and Windows.

## Rules CI enforces

### Generated output is never edited by hand

`.opencode/` is generated from the canonical contracts:

```bash
python SCRIPTS/se.py adapter opencode
```

Edit `AGENTS/`, `COMMANDS/`, `SKILLS/` or `TEMPLATES/` and regenerate. A manual
edit shows up as manifest drift and fails `se doctor`.

### No host-specific paths in tracked files

`se doctor`'s self-containment check fails absolute host paths (Windows drive
letters, WSL mount points, personal folders) on operational surfaces such as
`opencode.jsonc` or `SCRIPTS/`. Use relative paths or `{env:NAME}` substitution
so the system works on Windows, WSL and Linux alike.

### Line endings are LF everywhere

`.gitattributes` normalizes text files to LF. Do not override it or convert files
to CRLF: content hashes (coverage baseline, adapter manifest) are part of the
contract, and mixed line endings make `se doctor` and `se validate` fail on a
fresh clone.

### Published docs are hash-tracked

Editing (or adding) a document under `DOCS/reference/` changes its content hash.
Until the coverage baseline records that change, `se validate` reports the
document as replaced. Rebase it through the governed path:

```bash
python SCRIPTS/se.py coverage rebase --reason "why the document changed"
```

This appends one line to `DOCS/coverage-baseline.log.jsonl` (who changed what and
why). Never edit `DOCS/coverage-baseline.json` by hand — a hand-written rebase
destroys the only evidence that a document was lost or rewritten.

### No secrets

Never commit credentials, API keys, tokens or `.env` files. Use environment
variables and reference them with `{env:NAME}`.

### Local-only directories

`DOCS/internal/`, `.se/`, `PROJECTS/*`, `MEMORY/` and `.local/` are never
published. Do not make tracked code depend on them existing in a fresh clone.

## Scope

- Keep runtime-specific behavior in `INTEGRATIONS/`, never in `CORE/` or
  `SCHEMAS/`.
- Add or update tests for behavior changes; the suite must stay green.
- Update `DOCS/reference/` when behavior or contracts change (and rebase the
  baseline as described above).

## Reporting issues

Open an issue with: what you expected, what happened, the exact commands, your
OS (Windows / WSL / Linux) and the output of `python SCRIPTS/se.py doctor`.
