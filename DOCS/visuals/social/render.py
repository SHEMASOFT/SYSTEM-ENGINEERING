#!/usr/bin/env python3
"""Render the 60-second vertical social clip from ``scene.html``.

Same deterministic pipeline as the hero: Playwright renders each frame from
``window.__render(t)`` and the ffmpeg binary bundled with ``imageio_ffmpeg``
encodes the result.

    python DOCS/visuals/social/render.py all

Outputs (``DOCS/assets``):

    social-60s.mp4         1080x1920, 60 s — Shorts / Reels / TikTok
    social-60s-poster.png  1080x1920 still — cover
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "DOCS" / "assets"
SCENE = HERE / "scene.html"

DURATION = 60.0
FPS = 30
SIZE = (1080, 1920)
POSTER_AT = 50.2


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _launch(playwright):
    for kwargs in ({"channel": "chrome"}, {}):
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception:
            continue
    raise RuntimeError("no Chromium/Chrome available for Playwright")


def render_frames(dest: Path) -> int:
    from playwright.sync_api import sync_playwright

    dest.mkdir(parents=True, exist_ok=True)
    total = int(round(DURATION * FPS))
    width, height = SIZE
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(SCENE.as_uri())
        page.wait_for_timeout(300)
        for i in range(total):
            page.evaluate("t => window.__render(t)", i / FPS)
            page.screenshot(path=str(dest / f"f{i:05d}.png"))
        browser.close()
    return total


def encode(frames: Path) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "social-60s.mp4"
    subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(FPS),
         "-i", str(frames / "f%05d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
         "-preset", "slow", "-movflags", "+faststart", str(dest)],
        check=True,
    )
    return dest


def poster(frames: Path) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "social-60s-poster.png"
    idx = int(round(POSTER_AT * FPS))
    src = frames / f"f{idx:05d}.png"
    if not src.exists():
        src = sorted(frames.glob("f*.png"))[-1]
    shutil.copyfile(src, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", choices=["frames", "video", "poster", "all"], nargs="?", default="all")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="se-social-"))
    try:
        n = render_frames(tmp)
        print(f"frames : {n} @ {FPS} fps -> {tmp}")
        if args.what in {"video", "all"}:
            p = encode(tmp)
            print(f"video  : {p} ({p.stat().st_size / 1024 / 1024:.2f} MB)")
        if args.what in {"poster", "all"}:
            p = poster(tmp)
            print(f"poster : {p} ({p.stat().st_size / 1024:.0f} KB)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
