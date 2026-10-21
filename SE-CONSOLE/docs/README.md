# SE-CONSOLE-POC-001

A **local-first, read-only console** over [SYSTEM-ENGINEERING](../..).
It answers, in one interface, what SYSTEM-ENGINEERING is, what state it is in,
what it is made of, what its projects are, and what needs attention.

> **This console writes nothing.** It has no database, no ledger, no cache and
> no manifest of its own. Every request re-reads canonical state, and every
> governance verdict is relayed verbatim from the `se` engine.

---

## Run it

The console ships inside SYSTEM-ENGINEERING at `SE-CONSOLE/`. From the
repository root:

```powershell
cd SE-CONSOLE
python -m console.server
# -> http://127.0.0.1:8777
```

No install step, no build step, no `npm install`. Requirements: the Python
interpreter that already runs `se`, and `jsonschema` (already present for
`se doctor`). Nothing else.

Point it elsewhere with `SE_ROOT`; change the port with `SE_CONSOLE_PORT`.
The console defaults `SE_ROOT` to the repository root when vendored.

Run this way the console stays up until you stop it: `--idle-timeout SECONDS` is
the server's own flag and defaults to `0` (never stop). The helper below is what
arms it.

### Start / stop with one click (optional)

`scripts/dev_console.py` is a small local helper for the operator: bring the
console up while you work, take it down when you stop. It is **not** a service
and needs no privileges -- no Docker, no systemd, no NSSM, no boot entry. It
writes only under `SE-CONSOLE/.runtime/` (gitignored); the console process itself
still writes nothing into the SE tree.

```powershell
python scripts\dev_console.py start     # up in the background, waits for /api/health
python scripts\dev_console.py status
python scripts\dev_console.py stop      # clean shutdown
python scripts\dev_console.py restart
python scripts\dev_console.py logs -n 40
```

Double-clickable shortcuts live next to it:

- Windows: `scripts\Start SE Console.cmd`, `scripts\Stop SE Console.cmd`
  (point a Desktop shortcut at either one)
- macOS: `scripts\Start SE Console.command`, `scripts\Stop SE Console.command`

Installing SE with `se-installer install --shortcuts` (or ticking the box in
`se-installer tui`) creates that Desktop shortcut for you: **one**, which starts
the console. It is start-only on purpose -- the console stops itself, so a Stop
shortcut would have nothing to do.

#### It stops when you close the browser

`start` and `restart` arm the console's **idle timeout**: 15 minutes with no
client asking for anything, and the console shuts itself down. Closing the tab is
therefore enough; nothing of yours stays running behind the desktop.

| How | Effect |
|---|---|
| `start` (default) | `--idle-timeout 900` -- stop after 15 min with no client |
| `--idle-timeout 0` | never stop on its own; only `stop` takes it down |
| `--idle-timeout SECONDS` | any other value |
| `SE_CONSOLE_IDLE_TIMEOUT` | environment override of the default |

The timer stays **disarmed until the first client connects**, so a console nobody
opens never stops by itself. `status` reports what the process was started with:
`idle_timeout=15 min`, `idle_timeout=off`, or `unknown` when the console was not
started by this helper -- including one started before the option existed. Run
directly with `python -m console.server` the timeout is `off`; the helper is what
arms it.

The helper proves a running console by its `/api/health` signature
(`console=se-console`, `mode=read-only`), never by a bare PID, and refuses to
kill a process it cannot prove is this console (`--force` overrides).

## Verify it

```powershell
python tests\validate_poc.py    # 33 checks: contract, read-only, browser, non-interference
python tests\audit_visual.py    # contrast / clipping / overlap / target size, both themes
```

Both write evidence into `artifacts/evidence/` and exit non-zero on failure.

---

## Why this stack

Node is not installed on this machine, so Next.js/Vite were not options without
first adding a toolchain. For a read-only JSON view, the minimal professional
answer is static HTML/CSS/JS with no build step, served by the same Python that
runs `se`. Zero third-party dependencies; the smallest possible surface between
canonical bytes and pixels. See `DESIGN.md` §2.2.

---

## Architecture

```
web/                    static frontend, no build
  index.html            shell: header, tabs, epistemic strip, footer
  assets/console.css    design tokens + components, light & dark
  assets/console.js     vanilla rendering, no framework

console/                thin read layer (stdlib only)
  se_cli.py             the ONLY way to reach the engine: read-only allow-list,
                        se.report/1 envelopes relayed verbatim
  se_reader.py          transcription-only canonical reader (parse/validate/index)
  read_model.py         maps SE verdicts -> the 4 health states, attention queue
  api.py                GET-only routes, traversal-safe static serving
  server.py             http.server, preflight, 405 for any mutating verb

tests/
  validate_poc.py       end-to-end harness + evidence capture
  audit_visual.py       deterministic visual audit (contrast, clipping, overlap)

docs/DESIGN.md          design contract, tokens, layout, success criteria
```

### The three rules that keep it honest

1. **No re-implemented governance.** Gate status comes from `se gate`, review
   gaps from `se review`, capabilities from `se capabilities`, project identity
   from `se context`. The console cannot report a gate as passing unless `se` did.
2. **Transcription is not judgement.** `se_reader` may parse, validate and
   index. It never decides. The single derived computation is an inverted link
   index, rebuilt per request, and it is labelled `DERIVED`.
3. **Fail closed.** Anything undeterminable renders as an explicit `UNKNOWN`
   with its reason. It is never rendered as `0`, `""`, or green.

---

## Epistemic labelling

Every value on screen is tagged with where it came from:

| Tag | Meaning |
|---|---|
| `OBSERVED` | an `se` verdict or a canonical field, verbatim |
| `DERIVED` | computed by the console from observed facts |
| `UNKNOWN` | not determinable — shown as unknown, never defaulted |

`UNKNOWN` is rendered hatched, not muted-green, so an unresolved value can never
be mistaken for a healthy one.

---

## Read-only enforcement

Three independent layers, so no single mistake can make it a writer:

1. The route table contains only GET handlers — there is no POST/PUT/PATCH/DELETE
   route to dispatch to.
2. Any mutating verb is answered `405` with `Allow: GET, HEAD, OPTIONS`.
3. `se_cli` refuses mutating `se` subcommands (`new`, `update`, `transition`,
   `plan`, `release`, `init`, `explore`) by name, not by convention.

Verified live by the harness, not merely asserted.

---

## Visual verification status — stated plainly

**No visual review was performed.** `se capabilities` reports provider
`deepseek-vision` with `visual.review = unknown`, and the reviewing model in
this run has no image input. The console says so in its own footer.

What *was* done instead, and is a different claim:

- screenshots at 1280×800 and 375×812, both themes, three screens
- accessibility-tree snapshots (`aria_snapshot`) of each screen
- zero console errors and zero failed requests
- no horizontal overflow at 375 / 768 / 1440
- WCAG AA contrast computed for every text node, both themes
- no clipped text, no overlapping panels, all targets ≥24px

`tests/audit_visual.py` is the reproducible form of that audit.

---

## Known limitations

- `visual.review` unverified → no human/vision sign-off on appearance.
- `se doctor` takes ~9s, so the Overview takes ~10s to populate. This is the
  real engine's cost; the console is forbidden from caching it away.
- An unmanaged `PROJECTS/` entry: the engine refuses to evaluate its gates, and
  the console shows that refusal (`FAIL · no PROJECT.json`) rather than
  inventing a state or creating a manifest.
- `se report/1` is a pseudo-contract: no machine-checkable interface exists
  upstream. The console pins the id and warns on mismatch.
