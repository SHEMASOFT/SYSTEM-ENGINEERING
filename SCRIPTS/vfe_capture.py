"""vfe_capture.py — Visual Frontend Engineering capture runner.

Provider-agnostic evidence capture for the visual-frontend-engineering skill.
Loads a local page (or URL) in a real browser (system Chrome preferred), captures
full-page and viewport screenshots, and emits structural metrics as JSON.

Usage (PowerShell):
    python SCRIPTS/vfe_capture.py <html|url> --out <dir> --db JOB_ID [--vps 1280x800 375x812]

Outputs in <dir>/<job>:
    <job>-viewport-<w>x<h>.png
    <job>-fullpage-<w>x<h>.png
    metrics.json   (structural checks: semantics, alt, contrast baseline, overflow)
    snapshot.json  (accessibility snapshot: landmarks, headings, images)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _url_of(target: str) -> str:
    if target.startswith(("http://", "https://")):
        return target
    p = Path(target).resolve()
    return "file:///" + str(p).replace("\\", "/")


def _hex_to_rgb(hexv: str):
    hexv = hexv.strip().lower().lstrip("#")
    if len(hexv) == 3:
        hexv = "".join(c * 2 for c in hexv)
    if len(hexv) != 6:
        return None
    return tuple(int(hexv[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _lum(hexv) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hexv)
    r, g, b = lin(r), lin(g), lin(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _color_of(raw: str):
    """Normalize a CSS color string (hex or rgb()) to #rrggbb."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("#"):
        return raw
    import re

    m = re.match(r"rgba?\(([^)]+)\)", raw)
    if m:
        parts = [float(x.strip()) for x in m.group(1).split(",")]
        return "#{:02x}{:02x}{:02x}".format(
            int(parts[0]), int(parts[1]), int(parts[2])
        )
    return raw


def capture(target: str, out_dir: Path, job: str, viewports, channel: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    url = _url_of(target)
    report = {"job": job, "target": str(target), "url": url, "viewport": {},
              "metrics": [], "summary": {"FAIL": 0, "CHECK": 0}}
    snapshots = []
    results = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=channel)
        for vp in viewports:
            w, h = vp
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(url, wait_until="networkidle")
            page.wait_for_load_state("load")

            shot_vp = out_dir / f"{job}-viewport-{w}x{h}.png"
            shot_fp = out_dir / f"{job}-fullpage-{w}x{h}.png"
            page.screenshot(path=shot_vp, animations="disabled")
            page.screenshot(path=shot_fp, full_page=True, animations="disabled")

            metrics = page.evaluate(
                """() => {
                    const d = document;
                    const headings = [...d.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => h.tagName);
                    const images = [...d.querySelectorAll('img')];
                    const missingAlt = images.filter(i => i.alt === undefined || i.alt === '');
                    const landmarks = [...d.querySelectorAll('header,main,footer,nav,[role]')].map(e =>
                        e.tagName.toLowerCase()).slice(0, 20);
                    const overflow = d.documentElement.scrollWidth > d.documentElement.clientWidth;
                    const h1count = headings.filter(h => h === 'H1').length;
                    return {
                        headings, h1count, missingAlt: missingAlt.length,
                        imgCount: images.length, landmarks, overflow,
                        scrollWidth: d.documentElement.scrollWidth,
                        clientWidth: d.documentElement.clientWidth,
                        title: d.title
                    };
                }"""
            )

            contrast_checks = []
            page_bg = None
            body = page.query_selector("body")
            if body:
                page_bg = _color_of(body.evaluate("e => getComputedStyle(e).backgroundColor"))
            for sel in ["p.muted", ".lead", "nav a", ".btn", "footer"]:
                el = page.query_selector(sel)
                if not el:
                    continue
                style = el.evaluate("e => { const s = getComputedStyle(e); " +
                                    "return {color: s.color, bg: s.backgroundColor}; }")
                try:
                    raw_bg = (style.get("bg") or "").strip()
                    fg = _color_of(style.get("color"))
                    bg = None
                    if not (raw_bg.startswith("rgba") and raw_bg.rstrip().endswith(", 0)")
                            or raw_bg in ("transparent", "rgba(0, 0, 0, 0)")):
                        bg = _color_of(raw_bg) or page_bg
                    else:
                        bg = page_bg
                    if fg and bg:
                        ratio = _contrast(fg, bg)
                        contrast_checks.append({"selector": sel, "fg": fg, "bg": bg,
                                                "ratio": round(ratio, 2),
                                                "pass": ratio >= 4.5})
                    else:
                        contrast_checks.append({"selector": sel, "note": "unresolved color"})
                except Exception:
                    contrast_checks.append({"selector": sel, "note": "unresolved color"})

            fail = []
            if metrics["h1count"] != 1:
                fail.append("h1count!=1")
            if metrics["missingAlt"]:
                fail.append("missing-alt")
            if metrics["overflow"]:
                fail.append("horizontal-overflow")
            for c in contrast_checks:
                if not c.get("pass"):
                    fail.append(f"contrast:{c['selector']}")
            if not metrics["landmarks"]:
                fail.append("no-landmarks")

            report["viewport"][f"{w}x{h}"] = {
                "metrics": metrics,
                "contrast": contrast_checks,
                "screenshot_viewport": str(shot_vp.relative_to(out_dir)),
                "screenshot_fullpage": str(shot_fp.relative_to(out_dir)),
                "fail": fail,
            }
            report["summary"]["CHECK"] += 1
            if fail:
                report["summary"]["FAIL"] += 1

            snap = page.evaluate(
                """() => ({
                    title: document.title,
                    lang: document.documentElement.lang,
                    h1: [...document.querySelectorAll('h1')].map(e => e.textContent.trim())[0] || null,
                    navLinks: [...document.querySelectorAll('nav a')].map(a => a.textContent.trim()),
                    landmarks: [...document.querySelectorAll('header,nav,main,footer')].map(e => e.tagName.toLowerCase())
                })"""
            )
            snapshots.append({"viewport": f"{w}x{h}", "snapshot": snap})
            page.close()
        browser.close()

    (out_dir / f"{job}-metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / f"{job}-snapshot.json").write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="VFE capture runner")
    ap.add_argument("target", help="path to .html file or http(s) URL")
    ap.add_argument("--out", required=True, help="evidence output directory")
    ap.add_argument("--job", required=True, help="job id used to name artifacts")
    ap.add_argument("--vps", default="1280x800,375x812",
                    help="comma-separated widthxheight viewports")
    ap.add_argument("--channel", default="chrome", help="browser channel (chrome|msedge)")
    args = ap.parse_args()

    vps = [tuple(int(x) for x in v.split("x")) for v in args.vps.split(",")]
    report = capture(args.target, Path(args.out), args.job, vps, args.channel)
    print(json.dumps(report["summary"], indent=2))
    horrendous = [k for k, v in report["viewport"].items() if v["fail"]]
    if horrendous:
        print(f"VIEWPORTS WITH FAILS: {horrendous}", file=sys.stderr)
        return 1
    print("STATUS: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())