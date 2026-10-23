# Migrations

`MIGRATIONS/` holds optional, ordered data migrations that `se upgrade` runs
after the code has fast-forwarded to the target tag and **before** adapters are
regenerated, MCP servers are reconciled and `se doctor` verifies the system.

This directory intentionally contains no migration today. It exists so the
contract and the runner are reviewed before the first migration is needed.

## Contract

A migration is a top-level `*.py` file (files whose name starts with `_` are
ignored). Every file must expose:

```python
ID = "001_example"          # non-empty string, unique across the directory

def migrate(root, context):  # root is a pathlib.Path, context is a dict
    ...
```

* `ID` must be a non-empty string and unique. A missing/blank `ID`, a
  non-callable `migrate`, an unimportable module or a duplicate `ID` aborts the
  run **before any migration is applied** (fail-closed).
* `migrate(root, context)` may return anything; the return value is ignored.
  Raising an exception aborts the run and makes `se upgrade` roll back.
* `context` contains:

  ```json
  {
    "from_version": "0.10.1",
    "to_version": "0.10.2",
    "target": "<absolute target root>",
    "git_head_before": "<commit before the fast-forward>"
  }
  ```

## Order

Files are applied in **filename order** (byte-wise sort of the file name), not
in `ID` order. Prefix names with a zero-padded sequence (`001_`, `002_`, ...)
so the file name and the intended order agree.

## Idempotence and the ledger

Applied migrations are recorded in `<target>/.se/migrations.json`:

```json
{
  "schema_version": "1",
  "applied": [
    {"id": "001_example", "version": "0.10.2", "applied_at": "2026-10-23T01:20:00Z"}
  ]
}
```

* A migration whose `ID` is already in the ledger is **skipped**.
* The ledger is rewritten atomically after **each** successful migration, so an
  interrupted run never loses an applied step.
* An unreadable ledger, an unsupported `schema_version` or an invalid entry is
  an error; the upgrade rolls back instead of guessing.
* When the ledger exists before an upgrade, it is part of the snapshot and a
  rollback restores it.

Write every migration so it is safe to run twice anyway: a crash can happen
between `migrate()` returning and the ledger write. Prefer "create if absent",
"set to this value", or "remove if present" over blind appends.

## Rules

* **No network.** Migrations must not fetch, clone, download or call remote
  services. The upgrade itself only uses `git ls-remote`/`git fetch`.
* **No external side effects.** Do not install packages, change global user
  configuration, write outside `root`, or start long-running processes.
* **Do not touch files the snapshot already covers** (`opencode.jsonc`,
  `.se/lifecycle-state.json`, `.se/migrations.json`) unless the migration is
  explicitly about them; a rollback restores those from the snapshot.
* **Do not delete user data.** Projects, memories and `.se/` backups are not
  copied by default (`--include-projects` is opt-in), so a destructive
  migration is unrecoverable.
* **Fail loudly.** Raising is the supported way to abort; never swallow an
  error and pretend the migration succeeded.

## Minimal example

```python
"""001_example - rename a key in a project-owned file (idempotent)."""

from __future__ import annotations

import json
from pathlib import Path

ID = "001_example"


def migrate(root: Path, context: dict) -> dict:
    path = Path(root) / "PROJECTS" / "example.json"
    if not path.is_file():
        return {"skipped": "no example.json"}
    data = json.loads(path.read_text(encoding="utf-8"))
    if "old_key" not in data:
        return {"skipped": "already migrated"}
    data["new_key"] = data.pop("old_key")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"migrated": str(path)}
```

Run the upgrade with `se upgrade --offline` in a disposable repository first;
`se upgrade --check` never runs migrations and never writes.
