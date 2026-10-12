# SE-CONSOLE — 5B · Action Surface (Design)

Status: **IMPLEMENTED** — 2026-10-07. Scope approved by the project owner; §8 phases 1–3 have
landed, including the `web/` UI. `transition.attest` (v1.1) is **not** implemented.

> UI scope note: the front end wires the surface (token in `sessionStorage`, an "Acciones"
> column, `POST /api/action`). No browser is available in the build environment, so the UI
> is verified at the **asset** level (the shipped JS wires the surface) plus the HTTP
> end-to-end tests — **not** by a browser-driven test. That gap is declared, not hidden.
Extends `docs/DESIGN.md`. That document declared *"Writes anything to SYSTEM-ENGINEERING"*
a structural non-goal; 5B **consciously revises that non-goal** (§6) instead of letting it drift.

> This document is the design contract for 5B. It exists so that turning a read-only
> console into one that can act is a deliberate, reviewable decision — not an accident.

---

## 1. Objective

Let a human act, from the console, on the intervention points the console *already*
surfaces — by **delegating to the `se` engine**.

The console still owns no state and writes no canonical artifact. It **delegates**,
and it **records that it delegated**. `se` remains the only writer of SE state.

## 2. Scope

### 2.1 A1 — Action catalog (v1)

| # | Action id | Delegates to | Kind |
|---|---|---|---|
| 1 | `run.checkpoint` | `se run checkpoint` | progress / unblock |
| 2 | `run.close` | `se run close` | decide the outcome |

**Deliberately out of v1:** `new`, `update`, `init`, `plan`, `explore`, `release`, `execute`.
**Deferred to v1.1:** `transition.attest` (`se transition --attest`) — the human gate
decision. Higher impact (advances the lifecycle), so it lands after the chain is proven.

### 2.2 A3 — Intervention → action mapping

| Intervention point (attention item) | Enabled actions |
|---|---|
| RUN `BLOCKED`, or `checkpoint.blocked` non-empty | `run.checkpoint`, `run.close` |
| RUN `FAILED` | `run.checkpoint`, `run.close` |
| RUN with a pending `recovery.handoff` | `run.checkpoint` |
| RUN `RUNNING` (no intervention) | `run.checkpoint` |
| Gate condition `MANUAL` | *(v1.1)* `transition.attest` |
| integrity / review / discovery items | **none** — diagnosis, not actionable |

**Rule:** no intervention point without a mapped action; no action without the
intervention point that originates it. There is **no** generic "run any command" surface.

## 3. Identity (A2)

v1 = **one local operator**, declared explicitly (not inferred from the OS user).
The actor name travels with every delegated action and is written to both audit logs.

Real identities / locking are **step 6** and are explicitly out of scope here.
v1 must not pretend to be multi-user.

## 4. Prerequisites on the SE side (gaps to close first)

Evidence gathered 2026-10-07 against `SCRIPTS/se_core`:

| # | Gap | Evidence |
|---|---|---|
| 1 | **No idempotency anywhere.** Replaying an action duplicates it. | 0 hits for `idempot` across `SCRIPTS/se_core/*.py` |
| 2 | **`run start` / `run checkpoint` leave no audit trail.** | `_append_mutation_log` is called only by `execute`, `update`, and `run close` |
| 3 | **`run checkpoint` has no optimistic concurrency.** A concurrent writer is silently clobbered. | `_is_stale` is used only by `cmd_update` |
| 4 | **No "action" contract exists.** Nothing models *command + args + expected revision + result*. | no such schema or type in `SCHEMAS/` |

These are additive and are closed before any console action is enabled.

## 5. Security design

**Threat.** Adding a POST route on `127.0.0.1` without authentication means any page
the operator happens to have open can drive actions against the console
(CSRF, and DNS-rebinding onto localhost). Today this is harmless only because the
console is GET-only.

**Controls (v1), all stdlib:**

| Control | Purpose |
|---|---|
| Bearer token, generated once, stored `0600` outside the repo | authenticates the operator |
| Mandatory **custom header** (`X-SE-Console-Token`) | a cross-origin page cannot set a custom header without a CORS preflight, which the console never grants |
| `Origin` validation (absent, or same-origin `127.0.0.1`/`localhost`) | blocks browser-originated cross-site requests |
| `Host` validation | blocks DNS-rebinding |
| No CORS headers ever emitted | nothing to preflight against |
| Explicit per-action allowlist, checked server-side | a route cannot be widened by a caller |

A request that fails any control is refused **before** `se` is invoked.

## 6. Revision of the read-only invariant

`docs/DESIGN.md` enforced read-only in **three** layers. 5B replaces exactly one:

| Layer | POC | 5B |
|---|---|---|
| 1. Route table contains only GET handlers | no write route exists | **replaced**: an explicit, authenticated, allowlisted POST surface |
| 2. Non-GET/HEAD/OPTIONS rejected | 405 + `Allow` | **unchanged** (POST is now an allowed verb *only* on the action route) |
| 3. Static serving confined to `WEB_ROOT` | traversal refused | **unchanged** |

GET-only remains the default. The action surface is the single, named exception.

## 7. Idempotency, concurrency and audit

| Concern | v1 mechanism |
|---|---|
| Idempotency | client sends `Idempotency-Key`; `se` records applied keys and returns the prior result on replay instead of re-applying |
| Concurrency | client sends the record's `sha256` (the console already reads it) as `--expected-revision`; `se` refuses if the file changed |
| Audit | `se` writes every delegated action to `mutation-log.jsonl`; the console additionally writes `artifacts/actions.jsonl` with actor, action, target, key, revision, exit code and result |

Two independent records, on purpose: one lives with the project (§4 gap 2), one with
the console. Neither is a source of truth for the other.

### 7.1 HTTP status of a refused action (deliberate)

A well-formed, authenticated request whose delegated `se` run **exits non-zero** is
returned as **HTTP 200 carrying the engine's envelope** (`status: "FAIL"`,
`result.exit_code`), not as an error status. Deliberate: the console does not re-derive
a verdict it did not make. It maps only *its own* refusals to HTTP statuses — `401`
missing/incorrect token, `403` bad `Origin`/`Host`, `405` wrong method/path, `400`
malformed body. The engine's refusal is relayed verbatim.

**Consequence for callers:** a `2xx` means "the console relayed the request", not "the
action succeeded". Callers MUST read the envelope's `status` / `result.exit_code`.
Verified end-to-end: a stale `--expected-revision` returns `200` with `status: "FAIL"`
and leaves the artifact byte-identical.

## 8. Phasing

1. **SE enablers** — idempotency, audit coverage, expected revision (§4). Additive, no console change.
2. **Console auth** — token, custom header, `Origin`/`Host` validation. Tightening only; adds no capability.
3. **Console actions** — the POST surface + the A3 mapping. The new capability.
4. **v1.1** — `transition.attest`.

Each phase is independently verifiable and is committed as its own work unit.

## 9. Explicitly NOT authorised by this document

- Any action outside the v1 catalog in §2.1.
- Any generic command-execution surface.
- Multi-user identities, claims or locking (step 6).
- Enabling actions before the §4 gaps are closed.
