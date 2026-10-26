# Commands and Doctor

## Commands

Machine-readable: `COMMANDS/commands.json`. Human summary: `COMMANDS/README.md`.

| Command | Gate | Primary agent |
|---------|------|---------------|
| `init` | G0 | coordinator |
| `explore` | G1 | explorer |
| `new` | — | coordinator |
| `update` | — | coordinator |
| `transition` | varies | coordinator |
| `plan` | G3 | planner |
| `implement` | G4 | implementer |
| `verify` | G5 | tester |
| `review` | G6 | reviewer |
| `release` | G7 | devops |
| `doctor` | — | coordinator |
| `validate` | — | coordinator |
| `gate` | — | coordinator |
| `capabilities` | — | coordinator |
| `context` | — | coordinator |
| `health` | — | coordinator |
| `auto` | — | coordinator |
| `intent` | — | coordinator |
| `handoff` | — | coordinator |
| `archive` | — | coordinator |
| `restore` | — | coordinator |
| `execute` | G3 | implementer |
| `observe` | — | implementer |
| `orchestrate` | varies | coordinator |
| `upgrade` | — | devops |

`adapter` is a CLI infrastructure group (not a contract command — it consumes the contracts
to generate tool artifacts):

```powershell
python SCRIPTS\se.py adapter opencode                # generate .opencode/ from contracts
python SCRIPTS\se.py adapter opencode --dry-run      # show plan, write nothing
python SCRIPTS\se.py adapter opencode --output <dir> # custom output
```

See `DOCS/OPENCODE_ADAPTER.md` for the full mapping and guarantees.

### Upgrade

`upgrade` advances the installed Master System to a published tag, fail-closed:

```powershell
python SCRIPTS\se.py upgrade --check            # resolve target + read-only preflight (writes nothing)
python SCRIPTS\se.py upgrade --dry-run          # same as --check
python SCRIPTS\se.py upgrade                    # execute (ff-only, snapshot, migrations, adapters, sync, doctor)
python SCRIPTS\se.py upgrade --recover          # repair an interrupted run from .se/upgrade-in-progress.json
```

`--check` and `--dry-run` are read-only: they resolve the target version and run the preflight
without creating `.se/` or writing any file. Execution is ff-only (`git merge --ff-only <tag>`)
after a verified snapshot, with an atomic marker, ordered idempotent migrations, adapter
regeneration, `se sync` and a `se doctor` gate that requires `FAIL == 0` and accepts a recorded
WARN. Any failure after the marker rolls back: the snapshot is verified, HEAD is restored to the
recorded pre-upgrade commit, and config/state/ledger are restored with hash verification.
`--recover` repairs a marker left by an interrupted upgrade (a marker without `git_head_before`
is blocked). `--include-projects` is opt-in: `PROJECTS/` is never copied into a snapshot by
default.

### Project bootstrap

`init` also accepts a **project path as its only argument** to install the OpenCode layer
for a new or existing project from the canonical contracts (CHECKPOINT-005):

```powershell
python SCRIPTS\se.py init .workspaces\demo --agents architect,reviewer,security
python SCRIPTS\se.py init .workspaces\demo                # reuses PROJECT.json selection
```

The bootstrap generates `AGENTS.md`, `adapter-manifest.json`, `MASTER-SYSTEM-MANIFEST.json` and
`.opencode/{agent,command,skill}` (only requested agents and declared skills; all commands).
See `DOCS/PROJECT_BOOTSTRAP.md`. Since CHECKPOINT-016 the target is hardened: bare names
resolve under `PROJECTS/` when present, `TARGET:` is printed before writing, initialization of
EXTERNAL/INDEPENDENT projects is refused, and no existing independent artifacts
(`AGENTS.md`/`.opencode`/`opencode.json`/`SDD`) are overwritten. See `DOCS/PROJECT_POLICY.md`.

### Adopt an existing project

`se init` refuses a directory that already carries independent-project artifacts.
`adopt` is the dedicated, **additive** integration path for those: it writes
`PROJECT.json` (MANAGED, lifecycle `DISCOVERY`, recording `metadata.adoption` and a
`profiles.work` starting at `brownfield`) plus the empty workspace directories, and
leaves every pre-existing file byte-for-byte untouched.

```powershell
python SCRIPTS\se.py adopt PROJECTS\LegacyApp --owner "alice" --scale large --risk high
python SCRIPTS\se.py adopt PROJECTS\LegacyApp --owner "alice" --dry-run   # plan only
```

It refuses the master repository and any directory that already has a `PROJECT.json`.
Installing a runtime adapter stays a separate, explicit step (`se adapter ...`).

### Ceremony floor

The declared work profile is enforced through `CORE/policies/ceremony.json`:
scale/risk/criticality map to `spec_required` (an approved SDD) and `receipt_required`
(a passing RDD). `se ceremony` shows the effective requirements;
`se validate --project` enforces them.

```powershell
python SCRIPTS\se.py ceremony --project PROJECTS\LegacyApp
python SCRIPTS\se.py ceremony --project PROJECTS\LegacyApp --json
```

Reference CLI:

```powershell
python SCRIPTS\se.py doctor
python SCRIPTS\se.py validate
python SCRIPTS\se.py init --dir .workspaces\demo --name "Demo" --owner "alice" --domains software
python SCRIPTS\se.py explore --project .workspaces\demo
python SCRIPTS\se.py new objective --project .workspaces\demo --title "Goal" --epistemic-status OBJECTIVE
python SCRIPTS\se.py new requirement --project .workspaces\demo --title "R1" --acceptance-criteria "C1"
python SCRIPTS\se.py new task --project .workspaces\demo --title "T1" --objective "Do it"
python SCRIPTS\se.py new artifact --project .workspaces\demo --title "A1" --kind code --produced-by TASK-0001
python SCRIPTS\se.py new evidence --project .workspaces\demo --title "E1" --type test --result PASS
python SCRIPTS\se.py new acceptance --project .workspaces\demo --scope "Accept R1" --decided-by alice --evidence EVD-0001
python SCRIPTS\se.py new decision --project .workspaces\demo --context "c" --problem "p" --decision "d" --reason "r" --consequences "x" --affected-components svc
python SCRIPTS\se.py update requirement REQ-0001 --project .workspaces\demo --set "status=DEFERRED" --set "rationale=Postponed." --by alice
python SCRIPTS\se.py transition --project .workspaces\demo --to DISCOVERY
python SCRIPTS\se.py transition --project .workspaces\demo --to PLANNING --attest "discovery reviewed"
python SCRIPTS\se.py gate --project .workspaces\demo --gate G0
python SCRIPTS\se.py plan --project .workspaces\demo --create-tasks
python SCRIPTS\se.py verify --project .workspaces\demo
python SCRIPTS\se.py review --project .workspaces\demo
python SCRIPTS\se.py release --project .workspaces\demo --version 0.1.0 --approve --by alice
python SCRIPTS\se.py handoff create --project .workspaces\demo --scope trace --by alice
python SCRIPTS\se.py handoff load --project .workspaces\demo
python SCRIPTS\se.py archive --project .workspaces\demo --by alice
python SCRIPTS\se.py restore .workspaces\demo\PRJ-XXXX-0.1.0-20260101.tar.gz
```

Exit codes: `0` success, `1` validation/gate failure, `2` usage error.

`transition` is a gate controller (see `COMMANDS/README.md`): it refuses `FAIL`/`WARN`,
requires `--attest` for `MANUAL`, and has no bypass flag. `new` refuses to overwrite and
validates each generated record.

## Machine-readable output (`--json`)

The read-only inspection commands `doctor`, `validate`, `review`, `gate` and `capabilities`
accept `--json` to emit a stable `se.report/1` envelope instead of human-readable text:

```powershell
python SCRIPTS\se.py doctor --json
python SCRIPTS\se.py validate --json
python SCRIPTS\se.py review --project .workspaces\demo --json
python SCRIPTS\se.py gate --project .workspaces\demo --gate G5 --json
python SCRIPTS\se.py capabilities --check --json
```

The envelope has stable, additive-only keys (see
`DOCS/adr/ADR-0022-readonly-aggregation-minimum-context.json` and
`DOCS/MINIMUM_CONTEXT_POLICY.md`); `observation.observed_at` is the only non-deterministic
field. JSON is emitted only when explicitly requested and the default output is unchanged.
Errors in JSON mode remain valid JSON. `doctor`/`validate`/`review`/`gate`/`capabilities` are a
serialization surface: they perform no context reconstruction, never dump the project graph, and
grant no authority.

### Context reconstruction (AUTO-02)

`context` is the read-only, deterministic, on-demand reconstruction of the smallest sufficient
context for a project or a focused entity. DEFAULT = `identity` (LEVEL 0); broader levels
require an explicit `--scope`:

```powershell
python SCRIPTS\se.py context --project .workspaces\demo --json                          # LEVEL 0 identity
python SCRIPTS\se.py context --project .workspaces\demo --scope work --json             # LEVEL 1 work
python SCRIPTS\se.py context --project .workspaces\demo --scope authority --json        # LEVEL 2 authority
python SCRIPTS\se.py context --project .workspaces\demo --scope trace --focus TASK-0001 --json
python SCRIPTS\se.py context --project .workspaces\demo --scope deep --focus TASK-0001 --json
```

`operation` is `context reconstruction`; the level selector is `--scope`
(`identity|work|authority|trace|deep` ↔ LEVEL 0–4) and the optional `--focus` accepts an
existing record id (OBJ/REQ/TASK/ART/EVD/ADR/ACC/REL) or the project id. Lists are
reference-first; the bounded transitive link closure is deterministic; full record bodies appear
only at `deep`; the mutation log, CORE, documents and other projects are never emitted. It never
approves, attests, transitions or mutates anything.

## Doctor

`doctor` validates the Master System installation and environment:

- project structure and required files;
- configuration consistency (`VERSION` vs `SYSTEM.json`);
- schema index references and schema syntax;
- contract layer (agents, commands, skills, policies), OpenCode adapter output, and
  distribution manifest pinning (`contracts` / `adapter` / `manifests`);
- JSON integrity;
- Python runtime and `jsonschema` availability;
- Git availability and repository state;
- secret-file scan;
- self-containment scan (no external infrastructure references).

Results are `PASS` / `WARN` / `FAIL`; the command exits non-zero if any `FAIL`. The doctor
never reports `PASS` for a check it could not actually perform (e.g. a missing dependency
is a `FAIL`, an unavailable tool is a `WARN`). A managed workspace under `PROJECTS/` that is
behind master is reported as an informational `PASS` detail when it is excluded from version
control (reconcile it with `se init <project>` when you work on it); a project that is
shipped by this repository and behind master stays `WARN`.

---

## Web Installer (se-installer-web)

Interfaz web interactiva para instalar, desinstalar y gestionar componentes SE.

```powershell
# Arranque rápido (detecta puerto libre, abre navegador)
.\SE-INSTALLER\install-web.ps1          # Windows
bash SE-INSTALLER/install-web.sh        # Linux/macOS

# Comando directo (requiere pip install -e SE-INSTALLER)
se-installer-web --port 8765 --reload

# Directo con uvicorn (sin instalar)
python -m uvicorn se_installer_web.main:app --host 127.0.0.1 --port 8765 --reload
```

Abre **http://127.0.0.1:8765** (o el puerto asignado) en el navegador.

### Pestañas
| Pestaña | Descripción |
|---|---|
| **📦 Instalar** | Componentes, runtimes, dry-run, force, shortcuts |
| **🗑️ Desinstalar** | --all, --include-untracked-se-mcps, --remove-opencode-dir, --apply |
| **⚙️ Adaptador** | Generar/eliminar .opencode/ |
| **📋 Log** | Streaming WebSocket tiempo real |

### API
- `GET /api/components` - Lista componentes
- `GET /api/status` - Resumen
- `POST /api/install` - Instalar (async + WS)
- `POST /api/uninstall` - Desinstalar (stream)
- `POST /api/adapter/generate|remove` - Adaptador
- `WS /ws` - WebSocket logs tiempo real
