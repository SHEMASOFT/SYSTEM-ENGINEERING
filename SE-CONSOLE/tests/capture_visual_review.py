"""SE-CONSOLE-002A :: visual review evidence pack.

Scope A of 002A: POC-001 had no human/vision review. This does NOT perform one
-- it makes one *possible* and cheap, and it states exactly what remains
unverified.

What it produces
----------------
1. Screenshots for every key surface x {light,dark} x {desktop,tablet,375}.
   Existing POC-001 screenshots are preserved untouched.
2. Light/dark contact sheets (side by side, labelled) so a reviewer can compare
   themes in one image instead of alt-tabbing.
3. review_manifest.json: per-surface deterministic results + what still needs a
   human eye.

What it does NOT do
-------------------
It does not look at the images. The reviewing model in this run has no image
input (verified: the file transports as media and the model then reports it
cannot decode it). PIL is used only to compose sheets, never to judge them.
VISUAL_REVIEW stays UNKNOWN.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE_ROOT = os.path.dirname(HERE)
EVIDENCE = os.path.join(CONSOLE_ROOT, "artifacts", "evidence")
SHOTS = os.path.join(EVIDENCE, "002a")
SE_ROOT = os.environ.get("SE_ROOT_REAL") or os.path.join(
    os.path.dirname(CONSOLE_ROOT), "SYSTEM-ENGINEERING"
)

#: surface key -> (human label). Captured per viewport according to PLAN.
SURFACES = {
    "overview": "Overview",
    "projects": "Projects",
    "detail-managed": "Project detail SHEMASEG (managed)",
    "detail-unmanaged": "Project detail SHEMA (unmanaged)",
    "attention": "Attention",
}

VIEWPORTS = {
    "desktop": (1280, 800),
    "tablet": (834, 1112),
    "mobile": (375, 812),
}

#: Which surfaces matter at which width. Desktop carries the full surface set;
#: the narrower widths carry the two that actually reflow (Overview and the
#: managed project detail, which now include the record explorer).
PLAN = {
    "desktop": ["overview", "projects", "detail-managed", "detail-unmanaged", "attention"],
    "tablet": ["overview", "detail-managed"],
    "mobile": ["overview", "detail-managed"],
}

#: Readiness timeout. The backend answers in ~1s worst case, so 30s is a 30x
#: margin. A shorter bound keeps a single stuck surface from consuming the run.
SETTLE_MS = 30_000


def free_port(preferred: int) -> int:
    for p in range(preferred, preferred + 60):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise SystemExit("no free port")


class Server:
    def __init__(self, port: int) -> None:
        env = dict(os.environ, SE_CONSOLE_PORT=str(port))
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "console.server"], cwd=CONSOLE_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.port = port

    def wait(self) -> bool:
        for _ in range(90):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=5) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.5)
        return False

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.communicate(timeout=15)
        except Exception:
            self.proc.kill()


def settle(page, extra: str = "", timeout: int = SETTLE_MS) -> None:
    """Wait for the view to finish rendering.

    Readiness is signalled by the app itself: `go()` renders a `.loading`
    placeholder and clears it when the view resolves (or replaces it with a
    visible error). Waiting on `.panel` was wrong -- the Projects view renders
    cards, not panels, so that wait could never resolve.

    The backend answers in well under a second (measured: /api/system 0.23s,
    /api/project 0.95s), so the earlier 240s `networkidle` timeout was
    Playwright's network-idle heuristic being unreliable, not server latency.
    """
    page.wait_for_selector("#view-root .loading", state="detached", timeout=timeout)
    if extra:
        page.wait_for_selector(extra, timeout=timeout)
    time.sleep(0.6)


def goto_surface(page, base: str, surface: str) -> None:
    page.goto(base, wait_until="domcontentloaded", timeout=SETTLE_MS)
    settle(page)
    if surface == "overview":
        return
    if surface == "attention":
        page.locator("[data-view=attention]").click()
    else:
        page.locator("[data-view=projects]").click()
    settle(page)
    if surface == "detail-managed":
        page.locator('.proj-card[data-rel="PROJECTS/SHEMASEG"]').first.click()
        settle(page, ".recx-out .panel")
    elif surface == "detail-unmanaged":
        page.locator('.proj-card[data-rel="PROJECTS/SHEMA"]').first.click()
        settle(page)


def capture() -> dict:
    os.makedirs(SHOTS, exist_ok=True)
    from playwright.sync_api import sync_playwright

    port = free_port(8851)
    srv = Server(port)
    if not srv.wait():
        srv.stop()
        raise SystemExit("console did not start")
    base = f"http://127.0.0.1:{port}/"
    manifest: dict = {"surfaces": {}, "deterministic": {}, "visual_review": "UNKNOWN"}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            for vp_name, (w, h) in VIEWPORTS.items():
                manifest["deterministic"][vp_name] = {}
                for theme in ("light", "dark"):
                    errors: list[str] = []
                    failed: list[str] = []
                    for surface in PLAN[vp_name]:
                        step = f"{vp_name}/{theme}/{surface}"
                        print(f"  capturing {step} ...", flush=True)
                        # A fresh CONTEXT per surface, not just a fresh page.
                        # The server speaks HTTP/1.1 with keep-alive
                        # (ThreadingHTTPServer holds a thread per socket) and
                        # Chrome caps connections per host, so reusing one
                        # context across surfaces exhausted the pool and left
                        # later fetches queued forever -- the page sat on
                        # "cargando ..." while the server had already answered
                        # 200. Measured: 0 stalls with a context per surface vs
                        # intermittent 30s timeouts when sharing one. Closing
                        # the context also makes each screenshot independent.
                        ctx = browser.new_context(viewport={"width": w, "height": h})
                        # BrowserContext.add_init_script takes no arg, so the
                        # theme is interpolated. It is a literal from a fixed
                        # set, not user input.
                        ctx.add_init_script(
                            "try { localStorage.setItem('se-console-theme', %r); } catch (e) {}" % theme
                        )
                        page = ctx.new_page()
                        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                        page.on("requestfailed", lambda r: failed.append(r.url))
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        try:
                            goto_surface(page, base, surface)
                            time.sleep(1.5)
                            name = f"002a-{surface}-{theme}-{vp_name}.png"
                            page.screenshot(path=os.path.join(SHOTS, name), full_page=False)
                            box = page.evaluate(
                                "() => ({sw: document.documentElement.scrollWidth,"
                                " cw: document.documentElement.clientWidth,"
                                " panels: document.querySelectorAll('.panel').length,"
                                " theme: document.documentElement.getAttribute('data-theme')})"
                            )
                            manifest["surfaces"][f"{surface}/{theme}/{vp_name}"] = {
                                "file": f"artifacts/evidence/002a/{name}",
                                "label": SURFACES[surface],
                                "theme_applied": box["theme"],
                                "viewport": f"{w}x{h}",
                                "scroll_width": box["sw"],
                                "client_width": box["cw"],
                                "overflow": box["sw"] > box["cw"] + 1,
                                "panels": box["panels"],
                            }
                        except Exception as exc:
                            # Fail with evidence rather than a bare timeout: a
                            # reviewer needs to see the page state that broke.
                            shot = os.path.join(SHOTS, f"FAILED-{step.replace('/', '-')}.png")
                            try:
                                page.screenshot(path=shot, full_page=False)
                            except Exception:
                                shot = "(screenshot unavailable)"
                            state = {}
                            try:
                                state = page.evaluate("""() => ({
                                  loading: document.querySelectorAll('#view-root .loading').length,
                                  panels: document.querySelectorAll('.panel').length,
                                  recx: document.querySelectorAll('.recx').length,
                                  recxOut: document.querySelectorAll('.recx-out').length,
                                  recxOutPanels: document.querySelectorAll('.recx-out .panel').length,
                                  recxOutText: (document.querySelector('.recx-out')||{innerText:''}).innerText.slice(0,160),
                                  noticeError: (document.querySelector('.notice-error')||{innerText:''}).innerText.slice(0,200)
                                })""")
                            except Exception as se:
                                state = {"evaluate failed": str(se)[:200]}
                            manifest.setdefault("failures", []).append({
                                "step": step, "error": f"{type(exc).__name__}: {exc}"[:300],
                                "screenshot": f"artifacts/evidence/002a/{os.path.basename(shot)}"
                                if shot != "(screenshot unavailable)" else shot,
                                "dom_state": state,
                                "console_errors": sorted(set(errors)),
                            })
                            print(f"    !! FAILED {step}: {type(exc).__name__}", flush=True)
                            print(f"    state: {state}", flush=True)
                        finally:
                            ctx.close()
                    manifest["deterministic"][vp_name].setdefault(theme, {
                        "console_errors": [], "failed_requests": []})
                    manifest["deterministic"][vp_name][theme]["console_errors"] = sorted(set(errors))
                    manifest["deterministic"][vp_name][theme]["failed_requests"] = sorted(set(failed))
            browser.close()
    finally:
        srv.stop()
    return manifest


def contact_sheets(manifest: dict) -> list[str]:
    """Compose light|dark sheets. Composition only -- no judgement."""
    from PIL import Image, ImageDraw

    made: list[str] = []
    by_surface: dict[str, dict] = {}
    for key, meta in manifest["surfaces"].items():
        surface, theme, vp = key.split("/")
        by_surface.setdefault(f"{surface}/{vp}", {})[theme] = meta

    for pair, themes in sorted(by_surface.items()):
        if "light" not in themes or "dark" not in themes:
            continue
        imgs = []
        for theme in ("light", "dark"):
            p = os.path.join(CONSOLE_ROOT, themes[theme]["file"].replace("/", os.sep))
            if not os.path.isfile(p):
                imgs = []
                break
            imgs.append((theme, Image.open(p).convert("RGB")))
        if not imgs:
            continue
        gap, bar = 16, 34
        w = sum(im.width for _t, im in imgs) + gap * (len(imgs) + 1)
        h = max(im.height for _t, im in imgs) + bar + gap * 2
        sheet = Image.new("RGB", (w, h), (24, 24, 27))
        d = ImageDraw.Draw(sheet)
        x = gap
        for theme, im in imgs:
            d.text((x + 4, gap + 8), f"{theme.upper()}  {im.width}x{im.height}", fill=(235, 235, 240))
            sheet.paste(im, (x, gap + bar))
            x += im.width + gap
        out = os.path.join(SHOTS, f"sheet-{pair.replace('/', '-')}.png")
        sheet.save(out)
        made.append(f"artifacts/evidence/002a/{os.path.basename(out)}")
    return made


def main() -> int:
    print("== SE-CONSOLE-002A visual review evidence pack ==")
    manifest = capture()
    print(f"  captured {len(manifest['surfaces'])} screenshots")
    manifest["contact_sheets"] = contact_sheets(manifest)
    print(f"  composed {len(manifest['contact_sheets'])} contact sheets")

    bad = [k for k, v in manifest["surfaces"].items() if v["overflow"]]
    print(f"  overflow failures: {len(bad)} {bad if bad else ''}")
    print(f"  capture failures  : {len(manifest.get('failures', []))}")
    for f in manifest.get("failures", []):
        print(f"    - {f['step']}: {f['error'][:90]}")
        print(f"      state: {f['dom_state']}")
    for vp, d in manifest["deterministic"].items():
        for theme, dd in d.items():
            print(f"  {vp}/{theme}: console_errors={len(dd['console_errors'])} "
                  f"failed_requests={len(dd['failed_requests'])}")
    wrong_theme = [k for k, v in manifest["surfaces"].items()
                   if v["theme_applied"] != v["file"].split("-")[-2]]
    print(f"  theme mismatches: {len(wrong_theme)} {wrong_theme if wrong_theme else ''}")

    out = os.path.join(EVIDENCE, "review_manifest.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(f"  manifest -> {out}")
    print("\n  VISUAL_REVIEW = UNKNOWN (no vision capability in this runtime)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
