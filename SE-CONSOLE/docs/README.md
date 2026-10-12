# SE-CONSOLE-POC-001

A **local-first, read-only console** over [SYSTEM-ENGINEERING](../../SYSTEM-ENGINEERING).
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

## Verify it

```powershell
python tests\validate_poc.py    # 29 checks: contract, read-only, browser, non-interference
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
