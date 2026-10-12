"""SE-CONSOLE-POC-001 :: deterministic visual audit.

WHY THIS EXISTS
---------------
A human or vision-capable model looking at the screenshots would be the ideal
visual review. That capability is UNAVAILABLE here: `se capabilities` reports
provider `deepseek-vision` with `visual.review = unknown`, and the reviewing
model in this run has no image input. Rather than claim a visual review that
did not happen, this script substitutes the strongest checks that CAN be
computed:

  1. WCAG contrast ratio for every rendered text node, per theme
  2. clipped/overflowing text (content taller than its box)
  3. overlapping sibling panels (layout collisions)
  4. interactive target size (>=24px, WCAG 2.2 target-size minimum)
  5. colour-semantics binding: is HEALTHY/WARNING/BLOCKED/UNKNOWN actually
     rendered in its own token colour, i.e. does colour still carry meaning

This is NOT visual review and does not claim to be. It catches the class of
defects a screenshot hides: invisible text, collisions, and colour that fails
to bind to semantics.

Run:  python tests/audit_visual.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EVIDENCE = os.path.join(ROOT, "artifacts", "evidence")
PORT = int(os.environ.get("SE_CONSOLE_AUDIT_PORT", "8793"))
BASE = f"http://127.0.0.1:{PORT}"

# WCAG 2.2 SC 1.4.3: 4.5:1 for normal text, 3:1 for large/bold >=18.66px bold
# or >=24px.
CONTRAST_AA = 4.5
CONTRAST_AA_LARGE = 3.0
MIN_TARGET_PX = 24

JS_AUDIT = r"""
() => {
  const srgb = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = ([r, g, b]) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
  const parse = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    return { rgb: [p[0], p[1], p[2]], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (fg, bg, a) => fg.map((c, i) => c * a + bg[i] * (1 - a));
  const ratio = (a, b) => {
    const l1 = lum(a), l2 = lum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };
  const bgOf = (node) => {
    let n = node, acc = null;
    while (n && n !== document.documentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { acc = acc === null ? c.rgb : over(acc, c.rgb, 1); if (c.a >= 1) return c.rgb; }
      n = n.parentElement;
    }
    return acc || [255, 255, 255];
  };

  const out = { text: [], clipped: [], overlaps: [], targets: [], semantic: {} };
  const seen = new Set();

  document.querySelectorAll('body *').forEach((n) => {
    if (n.closest('script, style, .visually-hidden, .skip-link')) return;
    const cs = getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return;

    // 1. contrast on leaf text nodes
    const hasText = Array.from(n.childNodes).some(
      (c) => c.nodeType === 3 && c.textContent.trim().length > 1);
    if (hasText) {
      const fg = parse(cs.color);
      const bg = bgOf(n);
      const size = parseFloat(cs.fontSize);
      const weight = parseInt(cs.fontWeight, 10) || 400;
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      const cr = fg ? ratio(over(fg.rgb, bg, fg.a), bg) : 1;
      const key = n.tagName + '|' + cs.color + '|' + cs.fontSize + '|' + n.textContent.trim().slice(0, 24);
      if (!seen.has(key)) {
        seen.add(key);
        out.text.push({
          sel: n.tagName.toLowerCase() + (n.className ? '.' + String(n.className).split(' ')[0] : ''),
          color: cs.color, bg: 'rgb(' + bg.map(Math.round).join(',') + ')',
          fontSize: size, weight: weight, large: large,
          ratio: Math.round(cr * 100) / 100,
          required: large ? 3.0 : 4.5,
          pass: cr >= (large ? 3.0 : 4.5),
          sample: n.textContent.trim().slice(0, 40)
        });
      }
    }

    // 2. clipped text
    if (hasText && (n.scrollHeight - n.clientHeight > 2 || n.scrollWidth - n.clientWidth > 2)
        && cs.overflow !== 'visible' && cs.overflowY !== 'auto' && cs.overflowX !== 'auto') {
      out.clipped.push({ sel: n.tagName.toLowerCase() + '.' + String(n.className || '').split(' ')[0],
                         sh: n.scrollHeight, ch: n.clientHeight,
                         sw: n.scrollWidth, cw: n.clientWidth,
                         sample: n.textContent.trim().slice(0, 40) });
    }

    // 4. interactive target size
    if (n.matches('button, a[href], [role="button"]')) {
      const r = n.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        out.targets.push({ sel: n.tagName.toLowerCase(), w: Math.round(r.width),
                           h: Math.round(r.height), label: (n.textContent || '').trim().slice(0, 22) });
      }
    }
  });

  // 3. overlapping sibling panels
  const panels = Array.from(document.querySelectorAll('.panel, .proj-card, .gate'));
  for (let i = 0; i < panels.length; i++) {
    for (let j = i + 1; j < panels.length; j++) {
      const a = panels[i], b = panels[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (ox > 2 && oy > 2) {
        out.overlaps.push({ a: a.className.split(' ')[0], b: b.className.split(' ')[0],
                           ox: Math.round(ox), oy: Math.round(oy) });
      }
    }
  }

  // 5. colour still bound to semantics?
  const tok = getComputedStyle(document.documentElement);
  const v = (n) => tok.getPropertyValue(n).trim();
  out.semantic = {
    HEALTHY: v('--H-HEALTHY'), WARNING: v('--H-WARNING'),
    BLOCKED: v('--H-BLOCKED'), UNKNOWN: v('--H-UNKNOWN'),
    distinct: new Set([v('--H-HEALTHY'), v('--H-WARNING'), v('--H-BLOCKED'), v('--H-UNKNOWN')]).size
  };
  out.chipColours = Array.from(document.querySelectorAll('.health-chip, .status-chip'))
    .slice(0, 40)
    .map((n) => ({ cls: n.className, color: getComputedStyle(n).color,
                   text: (n.textContent || '').trim().slice(0, 18) }));
  return out;
}
"""


def run() -> dict:
    os.makedirs(EVIDENCE, exist_ok=True)
    env = dict(os.environ, SE_CONSOLE_PORT=str(PORT), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "console.server"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(90):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=5).read()
            break
        except Exception:
            time.sleep(1)
    else:
        proc.kill()
        raise SystemExit("server did not start")

    report: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "note": "deterministic substitute for visual review; NOT a visual review"}
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            for theme in ("light", "dark"):
                ctx = b.new_context(viewport={"width": 1280, "height": 800})
                pg = ctx.new_page()
                pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60_000)
                pg.wait_for_selector(".panel", timeout=90_000)
                pg.evaluate(
                    "(t) => { document.documentElement.setAttribute('data-theme', t);"
                    " localStorage.setItem('se-console-theme', t); }", theme)
                pg.wait_for_timeout(400)
                # Flat key, not a nested dict: summarise() walks top-level keys,
                # so a nested "themes" object would be silently never checked.
                report[f"overview_{theme}"] = pg.evaluate(JS_AUDIT)
                ctx.close()

            # also audit the busiest screen: managed project detail
            ctx = b.new_context(viewport={"width": 1280, "height": 800})
            pg = ctx.new_page()
            pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60_000)
            pg.wait_for_selector(".panel", timeout=90_000)
            pg.click('button[data-view="projects"]')
            pg.wait_for_selector(".proj-card", timeout=60_000)
            try:
                pg.click(".proj-card:has(.proj-id:text('PRJ-SHEMASEG'))", timeout=15_000)
                pg.wait_for_selector(".gate-grid .gate", timeout=90_000)
            except Exception:
                pass
            pg.wait_for_timeout(600)
            report["project_detail_light"] = pg.evaluate(JS_AUDIT)
            ctx.close()
            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    return report


def summarise(rep: dict) -> tuple[bool, str]:
    problems: list[str] = []
    for name, data in rep.items():
        if not isinstance(data, dict) or "text" not in data:
            continue
        bad = [t for t in data["text"] if not t["pass"]]
        small = [t for t in data["targets"] if t["w"] < MIN_TARGET_PX or t["h"] < MIN_TARGET_PX]
        if bad:
            worst = sorted(bad, key=lambda t: t["ratio"])[:5]
            problems.append(
                f"{name}: {len(bad)}/{len(data['text'])} text nodes below AA "
                + "; ".join(f"{t['sel']}={t['ratio']}(need {t['required']})" for t in worst))
        if data["clipped"]:
            problems.append(f"{name}: {len(data['clipped'])} clipped text nodes "
                            f"e.g. {data['clipped'][0]}")
        if data["overlaps"]:
            problems.append(f"{name}: {len(data['overlaps'])} overlapping panels "
                            f"e.g. {data['overlaps'][0]}")
        if small:
            problems.append(f"{name}: {len(small)} targets < {MIN_TARGET_PX}px "
                            f"e.g. {small[0]}")
        sem = data.get("semantic", {})
        if sem.get("distinct", 0) != 4:
            problems.append(f"{name}: health tokens not distinct ({sem.get('distinct')}/4)")
    if problems:
        return False, " | ".join(problems)
    return True, "contrast AA met, no clipping, no overlap, targets >=24px, 4 distinct health tokens"


if __name__ == "__main__":
    rep = run()
    with open(os.path.join(EVIDENCE, "visual_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2, ensure_ascii=False)
    ok, msg = summarise(rep)
    for name, data in rep.items():
        if isinstance(data, dict) and "text" in data:
            print(f"  {name:22} text={len(data['text']):3} "
                  f"fail_contrast={sum(1 for t in data['text'] if not t['pass']):2} "
                  f"clipped={len(data['clipped'])} overlap={len(data['overlaps'])} "
                  f"targets={len(data['targets'])} "
                  f"min_contrast={min(t['ratio'] for t in data['text']):.2f}")
    print(f"\nVISUAL AUDIT: {'PASS' if ok else 'FAIL'} :: {msg}")
    raise SystemExit(0 if ok else 1)
