# Lifecycle — `se install` / `se sync` / `se update` / `se uninstall`

SE gives its runtime integrations a single, observable lifecycle. The four commands
are **not four independent mechanisms**: they all read and write one shared state
file and they all follow the same ownership and safety rules. `install` creates the
registration, `sync` reconciles it with the declared source, `update` applies
declared changes with rollback, and `uninstall` removes only what SE owns.

This document is the normative reference for that lifecycle. It complements
[`installation.md`](installation.md), which covers obtaining SE and the shape of the
generated configuration.

---

## 1. One lifecycle, four commands

```
                TEMPLATES/mcp/*.json.tmpl          (DECLARED — canonical source)
                          │
                          ▼
   se install  ──▶  .se/lifecycle-state.json  ◀── se sync   (RECONCILE)
   (register)              (REGISTERED)          ▲  ▲
                    runtime config on disk        │  │      se update (apply + rollback)
                          (ACTUAL)───────────────┘  │
                                                     └────── se uninstall (remove owned only)
```

Three sources of truth are compared throughout the lifecycle:

| Source | What it is |
|---|---|
| **DECLARED** | `TEMPLATES/mcp/*.json.tmpl` — the canonical server templates shipped with SE. |
| **REGISTERED** | `<target>/.se/lifecycle-state.json` — what SE actually owns at this target. |
| **ACTUAL** | The runtime config on disk (`opencode.json(c)`) — what the runtime will load. |

Every command is a pure function over these three inputs plus an injectable runtime
seam, which is why the whole cycle can be exercised in a sandbox without a real
`opencode` binary.

---

## 2. Command reference

| Command | Purpose | Default behaviour | Mutates | Exit codes |
|---|---|---|---|---|
| `se install` | Register MCP servers and record SE ownership | Registers every declared server into the project config | Runtime config + lifecycle state | `0` PASS · `1` BLOCKED/FAIL · `2` usage |
| `se sync` | Reconcile declared ↔ registered ↔ actual | Registers missing servers, re-registers SE-owned drift; never touches foreign entries | Runtime config + lifecycle state (only when there is a diff) | `0` PASS · `1` BLOCKED/FAIL · `2` usage |
| `se update` | Apply declared changes to SE-owned servers, with rollback | No-op when nothing changed | Runtime config + lifecycle state (backup first) | `0` PASS · `1` BLOCKED/FAIL · `2` usage |
| `se uninstall` | Remove only SE-owned servers | **Plan only** — reports, mutates nothing | Nothing without `--apply` | `0` PASS/no-op · `1` BLOCKED · `2` usage |

Flags (per command):

| Command | Flags |
|---|---|
| `install` | `--project <dir>` · `--global` · `--all` / `--with a,b,c` · `--no-register` · `--generate-adapter` · `--dry-run` · `--json` |
| `sync` | `--project <dir>` · `--dry-run` · `--json` |
| `update` | `--project <dir>` · `--dry-run` · `--json` (lifecycle mode; see §6) |
| `uninstall` | `--project <dir>` · `--apply` · `--dry-run` · `--json` |

---

## 3. Ownership rules

SE draws a hard line between what it owns and what it does not:

- **SE-owned** — a server recorded in `<target>/.se/lifecycle-state.json`. Only
  these are ever re-registered or removed by `se sync`, `se update` and
  `se uninstall`.
- **Foreign / pre-existing** — a server present in the runtime config but **not**
  recorded in state. It is reported and **never** touched, rewritten or duplicated.
  This is how a hand-written entry survives the whole lifecycle byte-for-byte.
- **Orphan** — a server recorded in state but no longer declared by
  `TEMPLATES/mcp`. Reported only; v1 never auto-unregisters it.

Two legacy-specific rules protect pre-existing setups:

- A server declared by SE that already exists in the **legacy** `mcpServers` map is
  treated as foreign unless SE recorded it. SE will not duplicate it into
  `mcp.servers`.
- An SE-owned server found **only** in legacy `mcpServers` is reported for manual
  migration (`report_only`); SE will not re-register it, because that would
  duplicate the entry across the two maps.

---

## 4. Safety model

The lifecycle is **plan-first and fail-closed**:

1. **Simulation is the default for destructive work.** `se uninstall` only plans
   unless you pass `--apply`. `--dry-run` is available on every command and writes
   nothing.
2. **Byte-preserving removal.** Uninstall/update edit the runtime config with a
   surgical, jsonc-tolerant editor that removes **only** the target server's own
   span. Comments, formatting, whitespace and every other entry are preserved
   exactly — the file is never reformatted by re-serializing the parsed JSON.
3. **Backups before any rewrite.** Removals and updates copy the affected files into
   `<target>/.se/backups/` first.
4. **Fail-closed editing.** If the config cannot be parsed, if the target region
   cannot be isolated safely, or if a post-edit re-parse fails / changes other
   servers, the edit is **refused** and nothing is written.
5. **Rollback on failure.** `se update` backs up both the config and the state,
   applies changes, then verifies. If anything fails, both files are restored and
   the command reports **BLOCKED** with the restored-file hashes as evidence.
6. **Never delete data.** No command removes projects, user data, environment
   variables, third-party binaries, `.opencode/`, foreign config entries, or the
   `.se/` state directory itself.

---

## 5. The lifecycle state (`<target>/.se/lifecycle-state.json`)

One file records SE's ownership at a target. Schema **v1**:

```json
{
  "schema_version": "1",
  "se_version": "<SE version at registration>",
  "runtime": "opencode",
  "os": "windows",
  "target": "<project path>",
  "scope": "project",
  "servers": {
    "<server-name>": {
      "declared": "<sha256 of the resolved declared spec>",
      "registered_at": "<UTC ISO-8601>",
      "source": "TEMPLATES/mcp/<file>.json.tmpl",
      "scope": "project"
    }
  },
  "adapter": null,
  "uninstalled": []
}
```

- `servers.<name>.declared` is a canonical sha256 of the resolved spec (keys sorted),
  so equivalent specs always hash identically. `se sync`/`se update` compare this
  hash against the current declared spec to detect drift.
- `uninstalled` is an append-only audit trail: `se uninstall` **moves** an entry out
  of `servers` and into `uninstalled` rather than forgetting it.
- A missing state file and a corrupt state file are reported differently: missing =
  "nothing managed" (a normal no-op), corrupt = **BLOCKED** (exit 1).

The state lives **inside the target** (`<target>/.se/`) and `.se/` is
git-ignored, so lifecycle bookkeeping never leaks into the project's history.

---

## 6. Command details

### `se install`

Detects the OS, preflights the external tools (never installing them), builds the
`opencode mcp add` registrations from the declared templates, and records lifecycle
state for every server it actually registered.

- Registers at **project** scope by default; `--global` targets the user config.
- A server whose dependency is missing is **skipped** with per-OS guidance.
- State is written only after **at least one** server registered; the write merges
  with any existing state, preserving the `uninstalled` audit trail.

**`--global` is probed and fail-closed.** Before registering globally, SE runs
`opencode mcp add --help` once and scans stdout **and** stderr for `--global`. When
the installed CLI does not advertise it, the command reports **BLOCKED** (exit 1)
and performs **no** registration and writes **no** state, rather than silently doing
the wrong thing. This matters because not every installed `opencode` version
supports global registration.

### `se sync`

Reconciles DECLARED against REGISTERED and ACTUAL, mapping every server to exactly
one action:

| Classification | Condition | Action |
|---|---|---|
| register | declared, absent from the config | register + record state |
| up to date | declared, recorded, and the config entry matches the declared spec | none |
| SE-owned changed | declared, recorded, but the config entry differs | re-register + refresh state hash |
| foreign | declared but not recorded, yet present in the config | report only |
| orphan | recorded but no longer declared | report only |

- Sync always registers at **project** scope in v1 (global is install-only).
- A second run with no diff reports "Up to date / Applied: nothing" and changes
  nothing — it is **idempotent**, and it does not even invoke the runtime seam.
- A registration failure is a **FAIL** (exit 1); a missing dependency is a **WARN**
  (skip); a corrupt state file is **BLOCKED** (exit 1).

### `se update`

The lifecycle form of `se update` requires state: with nothing installed it reports
**BLOCKED** — *"nothing installed - run se install"*.

1. Diff DECLARED vs REGISTERED per server. Nothing changed → no-op report.
2. Report an SE-version mismatch against the recorded `se_version` **non-fatally**
   (advising `se adapter opencode` / `se init` when the generated adapters may be
   stale).
3. Otherwise back up the config **and** the state, apply the changed registrations
   (checkpointing state per server), then **verify** (config re-reads cleanly, state
   is consistent, the internal install plan re-runs without error).
4. On **any** failure, restore both backups and report BLOCKED with rollback
   evidence (restored files + before/after sha256 hashes + backup paths).

**Dual-mode command.** `se update` is one command with two modes, disambiguated by
positional arguments:

- `se update` (no record type) → the **lifecycle** update described here.
- `se update <record> <id> ...` → the **record mutation** path (updating an
  objective, requirement, task, … in a managed project).

A record type without a record id is a usage error.

### `se uninstall`

Removes only what SE owns, reversibly:

- **Default = simulation.** With no `--apply` (or with `--dry-run`) it prints exactly
  what *would* be removed and mutates nothing (exit 0).
- **`--apply`** removes only the servers recorded in state, one at a time, using the
  byte-preserving editor (each removal is backed up to `.se/backups/` first) and
  moves each removed server into the `uninstalled` audit trail.
- A server recorded in state but absent from the config is cleaned up in **state
  only** (no config rewrite) — this also covers a missing config file.
- Foreign entries are reported and left untouched. A missing state file means
  "nothing managed" (exit 0); a corrupt state file is BLOCKED (exit 1).
- The `.se/` state directory is **retained** as the audit trail; no project, data,
  binary or `.opencode/` is ever removed.

---

## 7. Scope (v1)

- **Runtime:** OpenCode only. Servers live under `mcp.servers.*` (V2) and are also
  read from the legacy `mcpServers.*` map for safety.
- **Platforms:** the OS is detected as `windows`, `linux` or `macos`; the tested,
  fully-supported path is **Windows + OpenCode**. Linux/macOS registration flows and
  per-OS package-manager guidance are planned.
- **Roadmap (not v1):** Claude Code / Codex adapters; platform-specific package
  managers; `se sync --prune-orphans`.

---

See [`installation.md`](installation.md) for obtaining SE, the `se install` flag
reference and the generated MCP configuration shape.
