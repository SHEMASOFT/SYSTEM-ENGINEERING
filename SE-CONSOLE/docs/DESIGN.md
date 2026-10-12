# SE-CONSOLE-POC-001 — Design

> Read-only console over SYSTEM-ENGINEERING. This document is the design
> contract for the POC. Every decision here is traceable to an observed fact or
> to an explicitly declared limitation.

---

## 1. Objective

Answer, in one local-first interface, five questions a maintainer currently has
to answer by hand:

1. **What is SYSTEM-ENGINEERING?** identity, version, purpose, boundaries.
2. **What is its state?** health, lifecycle, gate position, next transition.
3. **What is it made of?** agents, skills, policies, domains, commands, schemas.
4. **What are its projects?** managed vs unmanaged, lifecycle, record counts.
5. **What needs attention?** blocked conditions, manual gates, integrity gaps.

### Non-goals (structural, not aspirational)

| Non-goal | How it is prevented |
|---|---|
| Write anything to SYSTEM-ENGINEERING | console opens files `"r"` only; subprocess allow-list refuses mutating verbs |
| Become a second source of truth | no DB, no ledger, no cache, no manifest; every request re-reads canon |
| Re-implement SE governance | every verdict is an `se` CLI envelope relayed verbatim |
| Introduce a control plane / workflow engine | none; the console has no state machine of its own |
| Require Node.js | zero build step, zero npm dependency |

---

## 2. Design direction

**"Instrument panel, not dashboard."**

The console is an *observability surface for a governed system*, so the visual
language is that of an instrument cluster, not a marketing dashboard:

- **Evidence over ornament.** Every value is paired with its provenance chip
  (`OBSERVED` / `DERIVED` / `UNKNOWN`) and its source. A value without a source
  is treated as a defect, not a cosmetic gap.
- **Colour carries semantics, never decoration.** A colour is bound to a health
  state. If something is unknown it is visibly unknown — it is never painted
  green by default. This is the single most important visual rule in the system.
- **Fail-closed rendering.** Missing data renders an explicit `UNKNOWN` chip
  with the reason, not an empty cell and not a zero. A zero would be a claim.
- **Density with air.** Engineered multi-column grid on desktop, single column
  on mobile; generous vertical rhythm so scan density stays legible.

### 2.1 The five design questions, answered explicitly

SK-0003 requires the direction to be justified against five questions. The POC's
answers, and the constraint that follows from each:

| # | Question | Answer for this console | Consequence in the design |
|---|---|---|---|
| 1 | Panel de control, herramienta o Consumer App? | **Herramienta de inspeccion**, orientada al estado. The user is a maintainer debugging *why* something is not green. | Dense information, provenance visible at all times, drill-down beats landing-page hierarchy. |
| 2 | ¿Desktop, mobile o web app? | **Web app**, usable 1280×800 → 375×812, served from `127.0.0.1`. | No app store, no install, no build. Same URL opens the evidence. |
| 3 | Que densidad y estilo visual? | **Densidad media-alta**, estilo instrument cluster: monospace para identificadores y codigos, sans humanista para prosa. | Two type roles only. Monospace carries record ids, statuses and source paths. |
| 4 | ¿Dark mode por defecto, light mode, o ambos? | **Ambos**, light por defecto, dark completo, con persistencia en `localStorage` y respeto por `prefers-color-scheme`. Both are verified by screenshot, not assumed. | Tokens defined once per theme; no component hard-codes a colour. |
| 5 | Con que provider se implementa? | **Vanilla HTML/CSS/JS**, sin framework y sin build. | Justified in section 2.2. |

### 2.2 Why vanilla and not a framework

Observed constraint: **Node is not installed** on this machine
(`node : El término 'node' no se reconoce...`). Next.js, Vite and every
conventional frontend build path are therefore unavailable without first
installing a toolchain, which would violate the minimal-dependency constraint
and make the visual evidence depend on that toolchain.

The brief requires the *minimal professional* alternative. For a read-only JSON
view over six GET endpoints, the minimal professional answer is static
HTML/CSS/JS with no build step, served by the same Python that runs `se`.

This is not a downgrade forced by ignorance: static delivery is the smallest
possible surface between "canonical bytes" and "pixels", which is exactly what
a read-only evidence console wants. The cost is manual DOM rendering, accepted
because the data is flat and the screen count is 3.

Backend: Python standard library (`http.server`). Chosen over FastAPI to add
**zero** third-party dependencies; the console reuses the interpreter that
already runs `se`, so there is nothing to install and nothing to keep in sync.

---

## 3. Visual verification: stated up front

SK-0003 makes visual review **optional and decoupled**. It is declared
**UNAVAILABLE** for this POC, and the console says so in its own footer rather
than implying a human looked at it.

Reason: `se capabilities` reports provider `deepseek-vision` with
`visual.review = unknown`. Unverified provider → capability not assumed.

Consequence — the console is verified by **deterministic checks instead**:

| Check | Method | Pass condition |
|---|---|---|
| Layout integrity | Playwright `browser.snapshot` accessibility tree | no unnamed/role-less nodes in the main region |
| Desktop render | screenshot 1280×800 | ≥8 non-empty regions, no horizontal overflow |
| Mobile render | screenshot 375×812 | no horizontal overflow, single column |
| Console errors | page event capture | zero `error` events, zero failed requests |
| Contract check | TSV parse of `browser.snapshot` | 0 critical, 0 serious |
| Read-only | live `POST`/`DELETE` probes | `405` + `Allow: GET, HEAD, OPTIONS` |
| Non-interference | SHA-256 of 414 canonical files, before vs after | byte-identical |
| Idempotency | same endpoint twice | identical JSON payload |

Visual review is *not* claimed. Automated screenshot evidence is a different
class of claim and is labelled as such.

---

## 4. Design tokens

Defined once, consumed by both themes. No component may hard-code a colour.

### 4.1 Health semantics (the core token set)

| Health | Meaning | Light | Dark | Never means |
|---|---|---|---|---|
| `HEALTHY` | `se` reported PASS/OK | `#0f7b3f` | `#4ade80` | "probably fine" |
| `WARNING` | `se` reported WARN/**MANUAL** | `#9a5b00` | `#fbbf24` | ignorable |
| `BLOCKED` | `se` reported FAIL/ERROR | `#b42318` | `#f87171` | cosmetic |
| `UNKNOWN` | console could not determine | `#5b6472` | `#94a3b8` | anything at all |

`MANUAL` maps to `WARNING` **by design**: a condition awaiting a human decision
is unresolved work, and painting it green would make a project look releasable
when a human still has to act.

`UNKNOWN` is rendered as a distinct hatched chip, not a muted green. This is the
token that prevents the console from ever lying by omission.

### 4.2 Epistemic tags (provenance)

| Tag | Source | Visual |
|---|---|---|
| `OBSERVED` | an `se` verdict or canonical field, verbatim | solid tag, neutral ink |
| `DERIVED` | computed by the console from observed facts | solid tag + dotted underline |
| `UNKNOWN` | not determinable | hatched tag, muted ink |

### 4.3 Type

Two roles, no more:

- **Mono** (`ui-monospace, "Cascadia Code", Consolas, monospace`) — record ids,
  statuses, file paths, hashes, condition ids.
- **Sans** (`system-ui, "Segoe UI", sans-serif`) — prose, labels, headings.

Scale: `12 / 13 / 14 / 16 / 20 / 28` px, line-height 1.5 body / 1.2 headings.

### 4.4 Space, shape, elevation

Space scale `4 / 8 / 12 / 16 / 24 / 32`. Radius `6px` controls, `10px` panels.
One elevation only (`0 1px 2px` + hairline border); heavy shadow is rejected
because it fights the hairline-grid aesthetic.

---

## 5. Layout structure

### 5.1 Global chrome

- **Header** — product name, `SYSTEM-ENGINEERING v0.10.0` (observed), global
  health chip, theme toggle, refresh with last-generated timestamp.
- **Nav** — 3 tabs: Overview / Projects / Attention. Keyboard reachable.
- **Footer** — `se` root path, envelope contract `se.report/1`, source
  fingerprint, and the standing capability disclosure
  (`visual.review: unknown`).
- **Provenance strip** — persistent one-liner: every value is
  `OBSERVED` or `DERIVED`. Not decoration: it is the epistemic contract.

### 5.2 Screen A — Overview

1. **Identity panel** — name, version, purpose, epistemic status, domains.
2. **Health panel** — hero status, `se doctor` summary line, split
   `PASS / WARN / FAIL`, then the failing and warning checks enumerated with
   their own descriptions. A `WARN` total is shown as a warning, never absorbed
   into a green header.
3. **Capabilities panel** — 12 available, provider availability breakdown, plus
   the explicit note that capability is a provider property and is
   **not** overlaid on project lifecycle.
4. **Inventory panel** — SE-declared contract counts (from the `se doctor`
   contracts check) against console-observed counts, per item, with mismatch
   state. `domains` is `UNKNOWN` because `se doctor` does not declare it.
5. **Framework panel** — lifecycle states, the G0→G8 gate ladder, agents,
   skills, policies, domains.

### 5.3 Screen B — Projects

1. **Project cards** — one per `PROJECTS/` entry, managed or not.
   - Managed → lifecycle, current gate, next transition, record counts.
   - Unmanaged → explicit `UNMANAGED` state with the reason
     (`no PROJECT.json`), lifecycle `UNKNOWN`. Unmanaged projects are rendered this
     way and are never given an invented state.
2. **Project detail** (drill-down) — the primary screen:
   - identity + manifest schema validity + sha256
   - **gate matrix G0–G8** with per-condition ids and states
   - lifecycle + declared transitions/migrations
   - discovery record (summary, unknowns, assumptions, risks)
   - record inventory by type with schema-validation flags
   - traceability chain built from `se review` counts
   - integrity: findings, gaps, link notes — attributed to `se review`
   - mutation log with visible normalisation
   - AUTO-02 context panel showing identity and deep scope separately, with the
     explanation that AUTO-02 is focus-driven

### 5.4 Screen C — Attention

One prioritized queue: `BLOCKED` first, then `WARNING`. Each row carries area,
title, detail and the exact command or file that evidences it. Ordering is
declared as *attention priority, not a governance verdict*.

### 5.5 Responsive behaviour

- `≥1100px` — 12-col grid; Overview 2×2; gate matrix 3 cols.
- `760–1099px` — single column; gate matrix 2 cols.
- `<760px` — single column, no horizontal scroll at 375px; nav becomes a
  horizontal row; tables become stacked definition rows.

---

## 6. Accessibility

- Semantic landmarks: `header`, `nav`, `main`, `footer`; one `h1`.
- Skip link to `main`.
- Health conveyed by text + colour, never colour alone → status chips always
  carry their label.
- `aria-live="polite"` on the health and attention summaries.
- Full keyboard operation; visible focus ring (`2px` outline, offset 2px).
- Minimum 4.5:1 text contrast in **both** themes (asserted in review, not
  assumed).
- `prefers-reduced-motion` disables transitions.

---

## 7. Non-goals restated for the reviewer

To be explicit about what this POC is **not**, so it is not credited for it:

- It does not implement gates, transitions, lifecycle rules, record CRUD,
  traceability semantics, or any SE governance concept.
- It does not cache, store, or persist any SE-derived state. Reload re-reads
  everything from canon.
- It does not aggregate external telemetry. It reports the repository only.
- It does not render `docs/` as authoritative for gates.
- It is a local POC, not a deployed product.

---

## 8. Success criteria (verifiable)

| # | Criterion | Verification |
|---|---|---|
| S1 | Frontend builds/loads with zero errors | console-error capture = 0 events |
| S2 | Backend starts and serves | `se_console_preflight` + `GET /api/health` = 200 |
| S3 | 1280×800 renders correctly | screenshot + snapshot: 0 critical / 0 serious |
| S4 | 375×812 renders correctly | screenshot: no horizontal overflow |
| S5 | Answers the 5 questions | each question mapped to a rendered panel (§5) |
| S6 | Health shown as PASS/WARN/FAIL | gate matrix + health panel populated from `se` |
| S7 | Lifecycle + gates visible | G0–G8 matrix rendered from `se gate` |
| S8 | Components visible | agents/skills/policies/domains panels populated |
| S9 | Projects visible | managed and unmanaged projects rendered, correctly classified |
| S10 | Blockers / attention visible | `BLOCKED: 9` items enumerated with evidence |
| S11 | Unknowns shown as UNKNOWN | `domains` alignment and unmanaged-project lifecycle are `UNKNOWN` |
| S12 | SYSTEM-ENGINEERING unmodified | 414-file SHA-256 before/after identical |
| S13 | Read-only proven | live `POST`/`DELETE` → `405` + `Allow` |
| S14 | Idempotent | identical JSON on repeated identical requests |
| S15 | No SQLite / no control plane / no new deps | no DB file, no requirement manifest, stdlib only |

---

## 9. Risks and honest limitations

| Risk / limitation | Status |
|---|---|
| `visual.review` provider unverified | **DISCLOSED** — cannot claim visual review; deterministic checks used instead |
| AUTO-02 deep scope returns empty without `--focus` | **DISCLOSED** as SE behaviour in the UI; not presented as a data gap |
| Discovery record has no status field | **DISCLOSED** — rendered `UNKNOWN`, never inferred |
| No mutating command has ever been exercised by the console | **TRUE** — the surface is read-only by construction, so there is no mutation path to test |
| `se report/1` is a pseudo-contract | **NOTED** — no machine-checkable interface exists upstream; the console pins the id and warns on mismatch |
| Performance ~1–3s per project view | **ACCEPTED** — inherent to invoking the real engine; no caching allowed |
