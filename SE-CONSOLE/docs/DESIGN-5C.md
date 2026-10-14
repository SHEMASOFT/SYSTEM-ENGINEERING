# SE-CONSOLE — 5C · Lifecycle & Shutdown (Design)

Status: **ACCEPTED — 2026-10-14. Not implemented.** The owner decided (see §7, §11):
option **A** (idle-timeout heartbeat), **N = 15 min**, **one** desktop shortcut (start only).
This document records the design; it does **not** authorise code (§10). Each phase in §9 is
its own work unit with its own go-ahead.

Extends `docs/DESIGN.md`. Follows `docs/DESIGN-5B.md` (5B opened one named exception to
the read-only invariant; this document asks whether a second one is ever needed at all).

5B §9 lists what 5B did *not* authorise and says nothing about the console's **lifecycle** —
it neither authorises nor parks a shutdown surface. This document exists to close that gap
deliberately, now that a concrete use case has arrived (§2), instead of letting it drift into
code.

> Rule inherited from 5B: revising an invariant is a deliberate, reviewed act — never a drift.

---

## 1. Objective

Let the operator **stop the console without hunting for a command**, ideally by doing what
they already do when they finish: closing the browser page.

Two questions, and they are coupled:

| # | Question | Decides |
|---|---|---|
| Q1 | How does the server stop? | whether a Stop affordance is needed at all |
| Q2 | What does the installer put on the desktop? | one shortcut or two |

Q2 cannot be answered before Q1: if the server stops by itself, a "detener" shortcut is
clutter; if it does not, that shortcut *is* the feature.

## 2. Why now

An install-time desktop shortcut was requested so the console can be started by double-click
and stopped with a button, with **no external dependency** (no Docker, no systemd, no NSSM,
no boot entry). The launcher half of that is delivered as tooling in a **sibling change**
(branch `feat/console-launcher`, reviewed separately from this note):
`SE-CONSOLE/scripts/dev_console.py` (`start` / `stop` / `status` / `restart` / `logs`),
with `SE-CONSOLE/scripts/Start|Stop SE Console.cmd|.command` as double-click entry points.

The open half is exactly this document: the operator asked whether **closing the web page
can stop the server**, which would remove the Stop button from the desktop entirely.

## 3. Verified state today (evidence, 2026-10-14)

| Claim | Evidence | Tag |
|---|---|---|
| The front end does **no polling** | `web/assets/console.js`: 0 hits for `setInterval`; `fetch` only on demand (`/api/action` L393, generic JSON L462) | VERIFIED |
| The front end has **no unload handler** | 0 hits for `pagehide` / `unload` / `visibilitychange` / `beforeunload` / `sendBeacon` | VERIFIED |
| The server stops **only** on `KeyboardInterrupt` | `console/server.py`: `serve_forever()` wrapped in `try/except KeyboardInterrupt`; no other exit path | VERIFIED |
| There is **no shutdown route** | route table is GET-only except the single named `POST /api/action` (5B §6); no control/control-plane route exists | VERIFIED |
| The console **cannot write SE state** | `se_cli.py` read-only allow-list + action allow-list; refuses mutating `se` verbs by name | VERIFIED |
| Bind is local-only by design | `BIND_HOST`/`BIND_PORT` from env, default `127.0.0.1:8777` | VERIFIED |
| An **external** stop is delivered by the launcher change | `scripts/dev_console.py stop` (SIGINT on POSIX; `taskkill` on Windows — the console is stateless, so a hard stop loses nothing) | VERIFIED (sibling change) |
| All options below are **stdlib-only** | nothing in this document needs a third-party dependency | ASSUMED (by construction) |

## 4. The question, stated precisely

> "When I close the web page, can it stop the server?"

**No — not from the page, and not reliably.** Three independent reasons:

1. **No dependable signal.** `pagehide` + `navigator.sendBeacon()` is *best effort*. It does
   **not** fire when the browser crashes, when the process is killed from the task manager,
   or when the machine suspends or is shut down. It **does** fire on reload and on
   navigation — events that do not mean "I am done".
2. **Multi-tab.** With two console tabs, closing one would stop the server for the other.
3. **It is a write.** Stopping the server on demand is a state-changing control action, so it
   needs a `POST` control route — i.e. a **second named exception** to the GET-only invariant
   (5B §6 created the first), with the same `Origin`/`Host` + token defences as `/api/action`.

A page can *ask* to stop the server. Only the **server** can decide it is safe to stop — and
the robust trigger is not a request, but the **absence** of one.

## 5. Options

### A. Idle timeout (heartbeat) — the server stops when nobody is watching

The page sends a lightweight heartbeat (a `GET`, e.g. every ~30 s). The server keeps a
monotonic *last seen* and a watcher thread calls `shutdown()` after `--idle-timeout` with no
heartbeat. Close the page → after N the console stops by itself.

- **Reliability: high.** Covers the cases §4.1 lists, because the trigger is absence, not an
  event. Crash, kill, suspend, power-off — all degrade to "no heartbeat" → stop.
- **Contract: the GET-only default is preserved.** No POST appears; the read-only *data plane*
  is untouched (the console still writes no SE state). What is added is operational,
  in-memory state — the same *kind* of thing as the existing shared audit pass and `se` probe
  cache, not a ledger.
- **Not a CSRF target.** Shutdown is triggered by absence; a hostile page can only *delay* a
  stop, never cause one. A `POST /shutdown` endpoint (option B) would be a target and would
  need 5B-grade defences.
- **Cost: small.** One timer in `console.js`; one route (or a marker on the existing
  `/api/health`) and one watcher thread in `server.py`; one flag.
- **Caveat, declared:** background/mobile tabs get their timers throttled, so a short N can
  stop the console while a tab is still open. Mitigation: a long N (15–30 min) and/or
  treating `visibilitychange` as activity. Worst case it is the current behaviour (the
  operator stops it themselves).

### B. Beacon on page hide — immediate, best effort

`pagehide` (or `visibilitychange` → hidden) fires `navigator.sendBeacon('/api/control/shutdown')`.

- **Reliability: best effort only** — see §4.1 and §4.2. It cannot be the only mechanism.
- **Contract: a second named exception** to GET-only, with the full 5B §5 defence set. This is
  the part that must be *decided*, not drifted into.
- **Cost: larger** (route + auth + `Origin`/`Host` validation + tests + an entry in the
  action/audit story).
- Sensible only **on top of** A, as an accelerator: immediate when it works, A as the net.

### C. Lifecycle owned by the window — zero change to the console

The desktop shortcut starts the server **in its own console window**; closing that window
delivers `SIGINT`, which is the clean path `server.py` already implements.

- **Reliability: total** — for the action the operator actually performs ("I finished, close
  it"). The signal is the OS's, not the page's.
- **Contract: unchanged.** No new route, no new state, no new invariant question.
- **Cost: zero.**
- **The trade:** the operator closes a *window*, not a *tab* — not what was asked, but it is
  what guarantee looks like.

### D. No auto-stop

Keep the explicit Stop affordance (a second desktop shortcut, or `scripts/dev_console.py stop`).

- **Reliability: total.** **Contract: unchanged.** **Cost: zero.** *Not what was asked.*

## 6. The read-only invariant, revisited

5B §6 replaced exactly one of the three POC layers and named one exception. 5C asks whether
anything changes at all. Stated as a table so the answer can be audited:

| Layer (`DESIGN.md`) | Today (POC + 5B) | 5C · A (idle timeout) | 5C · B (beacon) |
|---|---|---|---|
| 1. Route table is GET-only except one named POST | `POST /api/action` | **unchanged** — the heartbeat is a `GET` | **replaced again**: a second named POST (`/api/control/shutdown`) |
| 2. Non-GET/HEAD/OPTIONS rejected | 405 + `Allow` | **unchanged** | **unchanged** (POST allowed *only* on the control route) |
| 3. Static serving confined to `WEB_ROOT` | traversal refused | **unchanged** | **unchanged** |
| 4. Console writes no SE state | enforced by `se_cli` allow-lists | **unchanged** | **unchanged** |
| 5. Console re-implements no governance | verdicts relayed verbatim | **unchanged** | **unchanged** |

**Consequence:** option **A changes no invariant.** Option **B changes layer 1 again**, which
is precisely why it must be an explicit decision with its own §-equivalent, not a footnote.

## 7. Decision (accepted 2026-10-14)

1. **Q1 → option A** (idle timeout). It is the only mechanism that delivers the requested
   behaviour *and* survives the cases the page cannot see (§4). Default **off**
   (`--idle-timeout 0`); the launcher passes **15 min** when it starts the console, so a
   hand-run `python -m console.server` keeps today's behaviour.
2. **Option B is rejected as the mechanism.** It may be revisited only as an accelerator on
   top of A, and only if the second named POST exception is judged worth it — that would be
   a **new** decision, not a continuation of this one.
3. **Option C is not chosen.** It stays documented as the fallback if A proves insufficient
   in practice.
4. **Q2 → one shortcut.** The installer creates a single "SE Console" shortcut (start; the
   browser opens). There is no Stop shortcut: the server stops itself (A).

## 8. What would change, and what would not

**Would change (option A only):**

- `console/server.py` — a `--idle-timeout` flag (default `0` = off) and a watcher thread that
  calls `shutdown()`.
- `console/api.py` — one GET heartbeat route, or a "last seen" marker on `/api/health`.
- `web/assets/console.js` — a heartbeat timer (~30 s).
- `scripts/dev_console.py` — pass `--idle-timeout` on start; `status` reports it.
- `tests/` — a test that the server stops after the timeout and, critically, that it does
  **not** stop while heartbeats keep arriving.

**Would not change:** the read-only invariant (§6), the action surface, any `/api/*` payload
shape, any `se` delegation, the `se.report/1` handling. No third-party dependency is added.

## 9. Phasing

Each phase is independently verifiable and is its own work unit:

1. **This document** — the decision, recorded. *(now)*
2. **Idle timeout** — server flag + heartbeat, off by default; tests prove stop-on-idle and
   stay-alive-under-heartbeat.
3. **Launcher wiring** — `dev_console.py start` passes the timeout; `status` shows it.
4. **Install-time shortcut** — `se_installer/shortcuts.py` + `InstallationPlan.create_shortcuts`
   + TUI prompt; one or two shortcuts per §7.4.

Phase 4 follows from the accepted Q2 (§7.4) and no longer waits on a decision. All phases
remain separate work units: acceptance of this design is **not** authorisation to write the
code (§10).

## 10. Explicitly NOT authorised by this document

Accepting the design is **not** authorising its implementation. This document does not
authorise:

- Writing any of the code listed in §8.
- Adding any route — POST or **GET** — to the console's table.
- Adding a `--idle-timeout` flag, a heartbeat, or a watcher thread.
- Creating anything in `se_installer/` or on any desktop.
- Option **B**: no second named exception to the GET-only invariant has been approved.
- Options **C** or **D** as the mechanism.

Phases 2–4 (§9) each begin only on their own explicit go-ahead.

## 11. Decision record

| # | Choice | Decided | Options considered |
|---|---|---|---|
| D1 | Stop mechanism (Q1) | **A — idle-timeout heartbeat** | A idle timeout / B beacon (+A) / C window-owned / D none |
| D2 | If A: idle N | **15 min** | 5 / 15 / 30 min |
| D3 | Desktop shortcuts (Q2) | **one (start only)** | one (start) / two (start + stop) |
| D4 | If B: a second named POST exception | **n/a — B rejected** | yes / no |

Decided by the project owner, 2026-10-14. The console's lifecycle stays as it is today until
phase 2 lands (§9): this decision governs the **design**, not the schedule.
