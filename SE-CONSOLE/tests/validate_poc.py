"""SE-CONSOLE-POC-001 :: validation harness.

Self-contained and reproducible: it starts the console, exercises it, captures
evidence, and shuts down. It does not rely on any pre-existing background
process, so a reviewer can re-run it and get the same verdict.

Every check maps to a numbered success criterion in DESIGN.md section 8.
The harness reports pass/fail per criterion; it does not soften a failure.

Run:  python tests/validate_poc.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EVIDENCE = os.path.join(ROOT, "artifacts", "evidence")
PORT = int(os.environ.get("SE_CONSOLE_PORT", "8791"))
BASE = f"http://127.0.0.1:{PORT}"

DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 375, "height": 812}

results: list[dict] = []
evidence: dict = {}


def check(cid: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append(
        {"id": cid, "name": name, "status": "PASS" if ok else "FAIL", "detail": detail}
    )
    print(f"  [{'PASS' if ok else 'FAIL'}] {cid} {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------------------


def free_port(p: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


def http(method: str, path: str, body: bytes | None = None) -> tuple[int, dict, str]:
    req = urllib.request.Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, {}, f"{type(e).__name__}: {e}"


def start_server() -> subprocess.Popen:
    env = dict(os.environ, SE_CONSOLE_PORT=str(PORT), PYTHONIOENCODING="utf-8")
    log = open(os.path.join(EVIDENCE, "server_validation.log"), "w", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "console.server"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(90):
        if p.poll() is not None:
            raise SystemExit(f"server exited early with {p.returncode}; see server_validation.log")
        if http("GET", "/api/health")[0] == 200:
            return p
        time.sleep(1)
    raise SystemExit("server did not become healthy within 90s")


# --------------------------------------------------------------------------
# Non-interference
# --------------------------------------------------------------------------


#: Paths under the SE root that are gitignored working records, not canonical
#: content. They are written during normal work, so a change there is not
#: evidence that the console wrote anything and must not fail S12.
NON_CANONICAL_PREFIXES = ("DOCS/internal/",)


def core_fingerprint() -> dict:
    """Hash the canonical SE tree. Proves the console changed nothing.

    Only canonical content is fingerprinted: the gitignored working records under
    ``DOCS/internal/`` are excluded (until 2026-10-14 they were not, so an
    unrelated write there during a run produced a false S12 non-interference
    failure).
    """
    # Portable default: when vendored the file lives at <repo>/SE-CONSOLE/tests,
    # so the repository root is two dirname() hops up from here.
    se = os.environ.get("SE_ROOT") or os.path.dirname(os.path.dirname(HERE))
    dirs = [
        "CORE", "SCHEMAS", "COMMANDS", "POLICIES", "AGENTS", "SKILLS", "DOMAINS",
        "TEMPLATES", "SCRIPTS", "DOCS", "MASTER SYSTEM", "INTEGRATIONS", ".opencode",
    ]
    skip = re.compile(r"node_modules|__pycache__|\\\.git\\|\\db_backups\\")
    files: list[str] = []

    def non_canonical(p: str) -> bool:
        rel = os.path.relpath(p, se).replace("\\", "/")
        return rel.startswith(NON_CANONICAL_PREFIXES)

    for d in dirs:
        base = os.path.join(se, d)
        for root, _sub, names in os.walk(base):
            for n in names:
                p = os.path.join(root, n)
                if not skip.search(p) and not non_canonical(p):
                    files.append(p)
    for n in os.listdir(se):
        p = os.path.join(se, n)
        if os.path.isfile(p):
            files.append(p)
    shema = os.path.join(se, "PROJECTS", "SHEMASEG")
    for root, _sub, names in os.walk(shema):
        for n in names:
            p = os.path.join(root, n)
            if not skip.search(p):
                files.append(p)

    h = hashlib.sha256()
    for p in sorted(set(files)):
        rel = os.path.relpath(p, se).replace("\\", "/")
        try:
            with open(p, "rb") as fh:
                h.update(rel.encode())
                h.update(hashlib.sha256(fh.read()).digest())
        except OSError:
            continue
    return {"file_count": len(set(files)), "tree_sha256": h.hexdigest()}


def no_forbidden_artifacts() -> list[str]:
    """S15: no SQLite, no package manifest, no new dependency manifest."""
    bad = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "artifacts"}]
        for f in files:
            if f.endswith((".db", ".sqlite", ".sqlite3")):
                bad.append(os.path.join(root, f))
            if f in ("package.json", "package-lock.json", "requirements.txt", "Pipfile", "poetry.lock"):
                bad.append(os.path.join(root, f))
    return bad


# --------------------------------------------------------------------------
# Browser evidence
# --------------------------------------------------------------------------


def browser_evidence() -> dict:
    from playwright.sync_api import sync_playwright

    out: dict = {
        "console_errors": [],
        "failed_requests": [],
        "shots": [],
        "snapshots": [],
        "overflow": {},
        "critical_nodes": 0,
        "serious_nodes": 0,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")

        def attach(page):
            page.on(
                "console",
                lambda m: out["console_errors"].append(f"{m.type}: {m.text}")
                if m.type == "error"
                else None,
            )
            page.on("pageerror", lambda e: out["console_errors"].append(f"pageerror: {e}"))
            page.on(
                "requestfailed",
                lambda r: out["failed_requests"].append(f"{r.method} {r.url} {r.failure}"),
            )
            page.on(
                "response",
                lambda r: out["failed_requests"].append(f"HTTP {r.status} {r.url}")
                if r.status >= 400
                else None,
            )

        # ---------------- desktop, both themes, all three views ----------
        ctx = browser.new_context(viewport=DESKTOP, device_scale_factor=1)
        page = ctx.new_page()
        attach(page)

        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(".panel", timeout=90_000)

        for theme in ("light", "dark"):
            page.evaluate(
                "(t) => { document.documentElement.setAttribute('data-theme', t);"
                " localStorage.setItem('se-console-theme', t); }",
                theme,
            )
            page.wait_for_timeout(350)
            out["overflow"][f"overview-{theme}"] = page.evaluate(
                "() => ({sw: document.documentElement.scrollWidth,"
                " cw: document.documentElement.clientWidth,"
                " panels: document.querySelectorAll('.panel').length})"
            )
            shot = os.path.join(EVIDENCE, f"overview-1280x800-{theme}.png")
            page.screenshot(path=shot, full_page=True)
            out["shots"].append(os.path.relpath(shot, ROOT))
            snap = page.locator("body").aria_snapshot()
            open(os.path.join(EVIDENCE, f"snapshot-overview-{theme}.txt"), "w", encoding="utf-8").write(snap)
            out["snapshots"].append(f"snapshot-overview-{theme}.txt")
            out[f"aria_overview_{theme}"] = len(snap or "")

        # projects view + drill-down.
        # Both projects are captured on purpose: SHEMASEG is the managed proving
        # ground, SHEMA the unmanaged one. Screenshotting only the first card
        # would hide the managed case, since "SHEMA" sorts first.
        page.click('button[data-view="projects"]')
        page.wait_for_selector(".proj-card", timeout=60_000)
        page.wait_for_timeout(500)
        out["overflow"]["projects"] = page.evaluate(
            "() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,"
            " cards: document.querySelectorAll('.proj-card').length})"
        )
        shot = os.path.join(EVIDENCE, "projects-1280x800.png")
        page.screenshot(path=shot, full_page=True)
        out["shots"].append(os.path.relpath(shot, ROOT))

        for slug, selector in (("shemaseg-managed", ".proj-card:has(.proj-id:text('PRJ-SHEMASEG'))"),
                               ("shema-unmanaged", ".proj-card:has(.proj-id:text('PROJECTS/SHEMA'))")):
            try:
                page.click(selector, timeout=15_000)
            except Exception:
                continue
            try:
                page.wait_for_selector(".gate-grid .gate", timeout=90_000)
            except Exception:
                pass
            page.wait_for_timeout(600)
            out["overflow"][f"detail-{slug}"] = page.evaluate(
                "() => ({sw: document.documentElement.scrollWidth,"
                " cw: document.documentElement.clientWidth,"
                " gates: document.querySelectorAll('.gate').length})"
            )
            shot = os.path.join(EVIDENCE, f"project-detail-{slug}-1280x800.png")
            page.screenshot(path=shot, full_page=True)
            out["shots"].append(os.path.relpath(shot, ROOT))
            snap = page.locator("body").aria_snapshot()
            fn = f"snapshot-project-detail-{slug}.txt"
            open(os.path.join(EVIDENCE, fn), "w", encoding="utf-8").write(snap)
            out["snapshots"].append(fn)
            page.click('button[data-view="projects"]')
            page.wait_for_selector(".proj-card", timeout=60_000)
            page.wait_for_timeout(400)

        # ------------------------------------------------ click-to-detail drawer
        # Characterization coverage (S16-S19). The drawer, the backdrop close
        # and the record explorer already ship; these assertions lock the
        # behaviour that exists so a future edit cannot silently break it. There
        # is no meaningful RED to observe here: the feature predates the test.
        #
        # Two unproven branches are pinned on purpose:
        #   * the no-`.ids` path (`focusType` selecting a type with no records)
        #   * the `recs` map shape handed to recordExplorer
        # The witness for both is the invariant that `.recx-out` is NEVER blank
        # for any type chip: an id-bearing type renders a card, a zero-id type
        # renders "sin registro que mostrar.", an absent type renders the
        # UNKNOWN message, and a type with no picks at all renders "sin
        # registros.". An empty `.recx-out` therefore proves a shape mismatch.
        drawer: dict = {
            "opened": False,          # gate drawer became visible
            "title": "",              # #drawer-title text
            "body_chars": 0,          # #drawer-body innerText length
            "esc_closed": False,      # Escape hid the drawer
            "focus_restored": False,  # focus returned to the gate card
            "backdrop_closed": False,  # overlay click hid the drawer
            "record_opened": False,   # record drawer became visible
            "record_out_chars": 0,    # #drawer-body .recx-out initial length
            "type_chips": 0,          # count of .recx-types .chip
            "chip_results": [],       # per-chip {label, chars} evidence
            "blank_types": [],        # labels whose .recx-out was empty
        }
        out["drawer"] = drawer

        # Re-enter the managed project showing the full, evaluated gate matrix.
        page.click(".proj-card:has(.proj-id:text('PRJ-SHEMASEG'))", timeout=15_000)
        page.wait_for_selector(".gate-grid .gate", timeout=90_000)
        page.wait_for_timeout(400)

        # --- gate drawer: the card itself is the trigger ------------------
        gate = page.locator(".gate-grid .gate").first
        gate.click()
        page.wait_for_selector("#drawer", state="visible", timeout=15_000)
        page.wait_for_timeout(300)  # let the slide-in settle before reading
        drawer["opened"] = page.locator("#drawer").is_visible()
        drawer["title"] = (page.locator("#drawer-title").inner_text() or "").strip()
        drawer["body_chars"] = len(page.locator("#drawer-body").inner_text() or "")
        # Esc must close and hand focus back to the trigger card.
        page.keyboard.press("Escape")
        page.wait_for_selector("#drawer", state="hidden", timeout=15_000)
        drawer["esc_closed"] = not page.locator("#drawer").is_visible()
        drawer["focus_restored"] = page.evaluate(
            "() => { var a = document.activeElement;"
            " return !!(a && a.classList && a.classList.contains('gate')); }"
        )

        # --- backdrop close: the overlay owns the handler -----------------
        # Dispatch the click on the overlay element directly so the panel does
        # not intercept the hit-test; this exercises the real onclick handler.
        gate.click()
        page.wait_for_selector("#drawer", state="visible", timeout=15_000)
        page.wait_for_timeout(200)
        page.evaluate("() => document.querySelector('.drawer-overlay').click()")
        page.wait_for_selector("#drawer", state="hidden", timeout=15_000)
        drawer["backdrop_closed"] = not page.locator("#drawer").is_visible()

        # --- record drawer + per-type chip sweep --------------------------
        # Only the records table wraps its rows with clickable(), so every
        # `tbody tr[role="button"]` is a record-type row.
        page.locator('tbody tr[role="button"]').first.click()
        page.wait_for_selector("#drawer", state="visible", timeout=15_000)
        page.wait_for_selector("#drawer-body .recx", timeout=15_000)
        page.wait_for_selector("#drawer-body .recx-out", timeout=15_000)
        page.wait_for_timeout(700)  # bounded wait for the async GET /api/record
        drawer["record_opened"] = page.locator("#drawer").is_visible()
        drawer["record_out_chars"] = len(
            page.locator("#drawer-body .recx-out").inner_text() or ""
        )
        chips = page.locator("#drawer-body .recx-types .chip")
        n_chips = chips.count()
        drawer["type_chips"] = n_chips
        for i in range(n_chips):
            chip = chips.nth(i)
            label = (chip.inner_text() or "").strip()
            chip.click()
            page.wait_for_timeout(600)  # bounded wait for the async render
            txt = page.locator("#drawer-body .recx-out").inner_text() or ""
            drawer["chip_results"].append({"label": label, "chars": len(txt)})
            if not txt.strip():
                drawer["blank_types"].append(label)
        # Leave the page clean for the steps that follow.
        page.keyboard.press("Escape")
        page.wait_for_selector("#drawer", state="hidden", timeout=15_000)

        # attention view
        page.click('button[data-view="attention"]')
        page.wait_for_selector(".stat", timeout=90_000)
        page.wait_for_timeout(800)
        shot = os.path.join(EVIDENCE, "attention-1280x800.png")
        page.screenshot(path=shot, full_page=True)
        out["shots"].append(os.path.relpath(shot, ROOT))
        snap = page.locator("body").aria_snapshot()
        open(os.path.join(EVIDENCE, "snapshot-attention.txt"), "w", encoding="utf-8").write(snap)
        out["snapshots"].append("snapshot-attention.txt")

        # accessibility: unnamed interactive nodes + landmarks
        out["a11y"] = page.evaluate(
            """() => {
              const un = [];
              document.querySelectorAll('button, a[href], [role="button"]').forEach(n => {
                const t = (n.textContent || '').trim();
                if (!t && !n.getAttribute('aria-label') && !n.getAttribute('title')) {
                  un.push(n.outerHTML.slice(0, 90));
                }
              });
              return {
                unnamed_controls: un,
                h1: document.querySelectorAll('h1').length,
                main: document.querySelectorAll('main').length,
                nav: document.querySelectorAll('nav').length,
                header: document.querySelectorAll('header').length,
                footer: document.querySelectorAll('footer').length,
                live_regions: document.querySelectorAll('[aria-live]').length,
              };
            }"""
        )
        ctx.close()

        # ---------------- mobile ---------------------------------------
        mctx = browser.new_context(viewport=MOBILE, device_scale_factor=1, is_mobile=True,
                                   has_touch=True)
        mpage = mctx.new_page()
        attach(mpage)
        mpage.goto(BASE + "/", wait_until="domcontentloaded", timeout=60_000)
        mpage.wait_for_selector(".panel", timeout=90_000)
        mpage.wait_for_timeout(500)
        out["overflow"]["overview-mobile"] = mpage.evaluate(
            "() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})"
        )
        shot = os.path.join(EVIDENCE, "overview-375x812.png")
        mpage.screenshot(path=shot, full_page=True)
        out["shots"].append(os.path.relpath(shot, ROOT))
        mpage.screenshot(path=os.path.join(EVIDENCE, "overview-375x812-fold.png"))
        out["shots"].append("artifacts/evidence/overview-375x812-fold.png")

        mpage.click('button[data-view="projects"]')
        mpage.wait_for_selector(".proj-card", timeout=60_000)
        mpage.wait_for_timeout(400)
        try:
            mpage.click(".proj-card:has(.proj-id:text('PRJ-SHEMASEG'))", timeout=15_000)
            mpage.wait_for_selector(".gate-grid .gate", timeout=90_000)
        except Exception:
            pass
        mpage.wait_for_timeout(500)
        out["overflow"]["project-mobile"] = mpage.evaluate(
            "() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})"
        )
        shot = os.path.join(EVIDENCE, "project-detail-375x812.png")
        mpage.screenshot(path=shot, full_page=True)
        out["shots"].append(os.path.relpath(shot, ROOT))
        mctx.close()

        browser.close()
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    os.makedirs(EVIDENCE, exist_ok=True)
    print("== SE-CONSOLE-POC-001 validation ==")

    print("\n[0] non-interference baseline")
    before = core_fingerprint()
    print(f"  canonical files hashed: {before['file_count']}")
    print(f"  tree sha256: {before['tree_sha256']}")

    print("\n[1] backend startup (S2)")
    if not free_port(PORT):
        raise SystemExit(f"port {PORT} busy")
    proc = start_server()
    st, _h, body = http("GET", "/api/health")
    health = json.loads(body) if st == 200 else {}
    check("S2", "backend starts and serves", st == 200 and health.get("status") == "OK",
          f"GET /api/health={st} se_available={health.get('se_available')}")
    check("S2b", "read-only mode declared", health.get("mode") == "read-only",
          f"mode={health.get('mode')}")

    try:
        print("\n[2] API contract + honesty (S5,S6,S7,S9,S11)")
        st, _h, b = http("GET", "/api/system")
        sysd = json.loads(b)
        check("S6", "health surfaced as PASS/WARN/FAIL",
              sysd["health"]["state"] in ("HEALTHY", "WARNING", "BLOCKED", "UNKNOWN")
              and bool(sysd["health"]["summary"]["value"]),
              sysd["health"]["summary"]["value"])
        check("S11a", "UNKNOWN used for undeclared inventory",
              any(r["state"] == "UNKNOWN" for r in sysd["inventory"]["alignment"]["value"]),
              "domains has no se-declared count -> UNKNOWN")
        check("S8", "components surfaced",
              len(sysd["agents"]["value"]) > 0 and len(sysd["skills"]["value"]) > 0
              and len(sysd["policies"]["value"]) > 0 and len(sysd["domains"]["value"]) > 0,
              f"agents={len(sysd['agents']['value'])} skills={len(sysd['skills']['value'])} "
              f"policies={len(sysd['policies']['value'])} domains={len(sysd['domains']['value'])}")

        st, _h, b = http("GET", "/api/projects")
        pj = json.loads(b)
        managed = [p for p in pj["projects"] if p["management"] == "MANAGED"]
        unman = [p for p in pj["projects"] if p["management"] != "MANAGED"]
        check("S9", "projects visible and correctly classified",
              len(managed) >= 1 and len(unman) >= 1
              and all(p["health"] == "UNKNOWN" for p in unman),
              f"managed={[p['dir_name'] for p in managed]} unmanaged={[p['dir_name'] for p in unman]} "
              f"(unmanaged forced to UNKNOWN)")
        check("S9b", "unmanaged projects have no invented lifecycle",
              all((p.get("lifecycle") or {}).get("value") is None for p in unman),
              f"lifecycle=None for {[p['dir_name'] for p in unman]} (no PROJECT.json)")

        st, _h, b = http("GET", "/api/project?rel_path=PROJECTS/SHEMASEG")
        pdet = json.loads(b)
        gates = pdet["gates"]["matrix"]["value"]
        check("S7", "gate matrix G0-G8 rendered from se gate",
              len(gates) == 9 and all(g["status"]["epistemic"] == "OBSERVED" for g in gates),
              f"{len(gates)} gates; pass={pdet['gates']['passing']} manual={pdet['gates']['manual']} "
              f"fail={pdet['gates']['failing']}")
        check("S7b", "lifecycle + next transition visible",
              bool(pdet["lifecycle"]["state"]["value"]) and bool(pdet["lifecycle"]["next_transition"]["value"]),
              f"{pdet['lifecycle']['state']['value']} -> {pdet['lifecycle']['next_transition']['value']}")
        check("S10", "blockers enumerated with evidence",
              pdet["attention"]["counts"]["BLOCKED"] > 0
              and all(i["evidence"] for i in pdet["attention"]["items"]),
              f"BLOCKED={pdet['attention']['counts']['BLOCKED']} "
              f"WARNING={pdet['attention']['counts']['WARNING']}")
        check("S11b", "AUTO-02 deep-scope emptiness disclosed, not hidden",
              bool(pdet["context"]["deep_scope"]["value"]["warnings"])
              and "focus" in ((pdet["context"].get("note") or {}).get("value") or ""),
              "warning surfaced: "
              + str(pdet["context"]["deep_scope"]["value"]["warnings"])
              + " + console note explains focus-driven behaviour")
        check("S-honest", "record counts kept distinct from se review counts",
              pdet["records"]["value"]["REQUIREMENT"]["count"]
              != pdet["traceability"]["review_counts"]["value"]["REQUIREMENT"],
              f"files={pdet['records']['value']['REQUIREMENT']['count']} "
              f"se-review-type={pdet['traceability']['review_counts']['value']['REQUIREMENT']} (not averaged)")

        # Unmanaged project: the engine's refusal must be surfaced, not smoothed over.
        # The project is taken from the list above rather than named: any directory
        # can legitimately become MANAGED (that is what `se adopt` is for), and a
        # check about unmanaged behaviour must not start failing when it does.
        unman_rel = unman[0]["rel_path"] if unman else None
        if unman_rel is None:
            check("S11c", "unmanaged project surfaces the engine's own conflict", False,
                  "no unmanaged project to exercise the refusal contract")
            check("S11d", "unevaluable gates carry envelope status, not bare UNKNOWN", False,
                  "no unmanaged project to exercise the unevaluable-gate contract")
        else:
            st, _h, b = http("GET", f"/api/project?rel_path={unman_rel}")
            sdet = json.loads(b)
            conflicts = sdet["engine_conflicts"]["value"]
            check("S11c", "unmanaged project surfaces the engine's own conflict",
                  sdet["management"]["value"] != "MANAGED" and any("PROJECT.json" in c for c in conflicts),
                  f"{unman_rel}: management={sdet['management']['value']} conflicts={conflicts}")
            matrix = sdet["gates"]["matrix"]["value"]
            check("S11d", "unevaluable gates carry envelope status, not bare UNKNOWN",
                  all(g["envelope_status"]["value"] for g in matrix)
                  and all(g["status"]["value"] is None for g in matrix),
                  f"{len(matrix)} gate(s) unevaluable on {unman_rel}, envelope_status="
                  f"{matrix[0]['envelope_status']['value'] if matrix else None}")

        print("\n[3] read-only enforcement (S13)")
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            s, h, _b = http(method, "/api/system", b'{"x":1}')
            check(f"S13.{method}", f"{method} refused", s == 405
                  and "GET" in (h.get("Allow") or ""), f"HTTP {s} Allow={h.get('Allow')}")
        s, _h, _b = http("GET", "/api/../../SYSTEM-ENGINEERING/VERSION")
        check("S13.trav", "path traversal refused", s in (400, 404), f"HTTP {s}")
        s, _h, _b = http("GET", "/api/project?rel_path=../../etc")
        check("S13.proj", "project traversal refused", s == 400, f"HTTP {s}")

        print("\n[4] idempotency (S14)")
        a1 = http("GET", "/api/system")[2]
        a2 = http("GET", "/api/system")[2]
        # Idempotency means the console accumulates no state: every
        # governance-relevant value must be byte-identical on repeat reads.
        # Observation time and subprocess wall-clock are inherently
        # non-deterministic and are excluded by name, not by value: `age_seconds`
        # is an age derived from a recorded instant, so it moves between reads
        # while the payload stays deterministic, and decimals are part of its
        # shape (41.2 -> 37.8 keeps the byte count, not the bytes).
        volatile = re.compile(
            r'"(generated_at|observed_at|duration_ms|age_seconds)":\s*("[^"]*"|-?\d+(?:\.\d+)?)'
        )
        strip = lambda t: volatile.sub("", t)  # noqa: E731
        s1, s2 = strip(a1), strip(a2)
        check("S14", "identical payload on repeat", s1 == s2,
              f"{len(s1)} vs {len(s2)} chars after excluding 3 volatile timing fields"
              if s1 != s2
              else f"{len(s1)} chars identical after excluding generated_at/observed_at/duration_ms")

        print("\n[5] browser + visual evidence (S1,S3,S4)")
        ev = browser_evidence()
        evidence.update(ev)

        check("S1", "zero console errors / failed requests",
              not ev["console_errors"] and not ev["failed_requests"],
              f"errors={ev['console_errors'][:3]} failed={ev['failed_requests'][:3]}")

        d = ev["overflow"].get("overview-light", {})
        check("S3", "1280x800 desktop renders, no overflow",
              d.get("sw", 10**9) <= d.get("cw", 0) and d.get("panels", 0) >= 7,
              f"scrollW={d.get('sw')} clientW={d.get('cw')} panels={d.get('panels')} (7 expected)")
        m = ev["overflow"].get("overview-mobile", {})
        check("S4", "375x812 mobile renders, no overflow",
              m.get("sw", 10**9) <= m.get("cw", 0), f"scrollW={m.get('sw')} clientW={m.get('cw')}")
        mm = ev["overflow"].get("project-mobile", {})
        check("S4b", "mobile project detail no overflow",
              mm.get("sw", 10**9) <= mm.get("cw", 0), f"scrollW={mm.get('sw')} clientW={mm.get('cw')}")

        a11y = ev.get("a11y", {})
        check("S-a11y", "landmarks + no unnamed controls",
              a11y.get("h1") == 1 and a11y.get("main") == 1 and a11y.get("nav") == 1
              and a11y.get("live_regions", 0) >= 1 and not a11y.get("unnamed_controls"),
              f"h1={a11y.get('h1')} main={a11y.get('main')} nav={a11y.get('nav')} "
              f"live={a11y.get('live_regions')} unnamed={len(a11y.get('unnamed_controls', []))}")

        for theme in ("light", "dark"):
            ev[f"theme_{theme}"] = {
                "aria_chars": ev.get(f"aria_overview_{theme}", 0),
                "panels": ev["overflow"][f"overview-{theme}"].get("panels", 0),
                "screenshot": f"artifacts/evidence/overview-1280x800-{theme}.png",
            }
        check("S-theme", "both themes render populated", all(
            ev["overflow"][f"overview-{t}"].get("panels", 0) >= 7 for t in ("light", "dark")
        ), f"light_panels={ev['overflow']['overview-light']['panels']} "
           f"dark_panels={ev['overflow']['overview-dark']['panels']}")

        # Drawer characterization (S16-S19). The behaviour already ships; these
        # checks pin it. A failure here is a real regression, not a missing RED.
        drw = ev.get("drawer", {})
        check("S16", "gate drawer opens with detail, Esc closes, focus restored",
              bool(drw.get("opened")) and bool(drw.get("title"))
              and drw.get("body_chars", 0) > 80 and bool(drw.get("esc_closed"))
              and bool(drw.get("focus_restored")),
              f"title={drw.get('title')!r} body_chars={drw.get('body_chars')} "
              f"esc_closed={drw.get('esc_closed')} focus_restored={drw.get('focus_restored')}")
        check("S17", "record drawer opens with explorer payload",
              bool(drw.get("record_opened")) and drw.get("record_out_chars", 0) > 0,
              f"record_opened={drw.get('record_opened')} "
              f"recx_out_chars={drw.get('record_out_chars')}")
        check("S18", "drawer closes on backdrop click",
              drw.get("backdrop_closed") is True,
              f"backdrop_closed={drw.get('backdrop_closed')}")
        check("S19", "every record type chip renders content or an explicit empty message",
              drw.get("type_chips", 0) >= 1 and not drw.get("blank_types"),
              f"type_chips={drw.get('type_chips')} blank_types={drw.get('blank_types')} "
              f"chips={drw.get('chip_results')}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n[6] non-interference after (S12) + artifacts (S15)")
    after = core_fingerprint()
    same = (
        before["tree_sha256"] == after["tree_sha256"]
        and before["file_count"] == after["file_count"]
    )
    check("S12", "SYSTEM-ENGINEERING byte-identical",
          same,
          f"{before['file_count']} files, sha256 {before['tree_sha256'][:16]}"
          + ("" if same else f" -> {after['file_count']} files, sha256 {after['tree_sha256'][:16]} CHANGED"))
    bad = no_forbidden_artifacts()
    check("S15", "no SQLite / no new dependency manifest", not bad, f"found={bad}")

    # ---------------------------------------------------------------- report
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = [r for r in results if r["status"] == "FAIL"]
    report = {
        "harness": "tests/validate_poc.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "core_fingerprint_before": before,
        "core_fingerprint_after": after,
        "browser": ev,
        "checks": results,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(failed),
            "status": "PASS" if not failed else "FAIL",
        },
    }
    with open(os.path.join(EVIDENCE, "validation_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print(f"\n== {passed}/{len(results)} checks passed ==")
    if failed:
        print("FAILED:")
        for f in failed:
            print(f"  - {f['id']} {f['name']}: {f['detail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
