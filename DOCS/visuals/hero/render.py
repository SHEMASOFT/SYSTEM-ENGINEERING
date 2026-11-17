#!/usr/bin/env python3
"""Render the SYSTEM ENGINEERING README hero from ``scene.html``.

Deterministic pipeline, no external dependencies beyond the ones already used by
the rest of the repository's tooling (Playwright + the ffmpeg binary bundled
with ``imageio_ffmpeg``):

    python DOCS/visuals/hero/render.py all

Outputs (written next to this folder, in ``DOCS/assets``):

    hero.mp4         1440x810, H.264, 30 fps  — full quality, for releases
    hero.gif         880 px wide, 18 fps      — autoplaying README hero
    hero-poster.png  1440x810 still           — social previews and fallbacks

The scene is a pure function of time (``window.__render(t)``), so every frame is
reproducible: same code in, same pixels out.
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
ROOT = HERE.parents[2]                      # repository root
OUT = ROOT / "DOCS" / "assets"
SCENE = HERE / "scene.html"

DURATION = 8.0
FPS_MASTER = 30
FPS_GIF = 18
WIDTH = 1440
HEIGHT = 810
GIF_WIDTH = 880
POSTER_AT = 6.9


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _launch(playwright):
    """Prefer a real Chrome; fall back to Playwright's bundled Chromium."""
    for kwargs in ({"channel": "chrome"}, {}):
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception:
            continue
    raise RuntimeError("no Chromium/Chrome available for Playwright")


def render_frames(dest: Path, fps: int, duration: float) -> int:
    from playwright.sync_api import sync_playwright

    dest.mkdir(parents=True, exist_ok=True)
    total = int(round(duration * fps))
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.goto(SCENE.as_uri())
        page.wait_for_timeout(250)
        for i in range(total):
            page.evaluate("t => window.__render(t)", i / fps)
            page.screenshot(path=str(dest / f"f{i:04d}.png"))
        browser.close()
    return total


def encode_video(frames: Path, fps: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "hero.mp4"
    subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(fps),
         "-i", str(frames / "f%04d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19",
         "-preset", "slow", "-movflags", "+faststart", str(dest)],
        check=True,
    )
    return dest


def encode_gif(frames: Path, fps: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "hero.gif"
    vf = (
        f"fps={fps},scale={GIF_WIDTH}:-1:flags=lanczos,split[s0][s1];"
        "[s0]palettegen=max_colors=128:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle"
    )
    subprocess.run(
        # the frames are a master at FPS_MASTER; resample to the GIF rate instead
        # of reinterpreting them, or the GIF plays in slow motion
        [ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(FPS_MASTER),
         "-i", str(frames / "f%04d.png"), "-vf", vf, "-loop", "0", str(dest)],
        check=True,
    )
    return dest


def write_poster(frames: Path, fps: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "hero-poster.png"
    idx = int(round(POSTER_AT * fps))
    src = frames / f"f{idx:04d}.png"
    if not src.exists():
        src = sorted(frames.glob("f*.png"))[-1]
    shutil.copyfile(src, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", choices=["frames", "video", "gif", "poster", "all"], nargs="?", default="all")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="se-hero-"))
    try:
        if args.what in {"frames", "all"}:
            fps = FPS_MASTER
            n = render_frames(tmp, fps, DURATION)
            print(f"frames : {n} @ {fps} fps -> {tmp}")
        else:
            fps = FPS_MASTER
            render_frames(tmp, fps, DURATION)

        if args.what in {"video", "all"}:
            p = encode_video(tmp, FPS_MASTER)
            print(f"video  : {p} ({p.stat().st_size / 1024 / 1024:.2f} MB)")

        if args.what in {"gif", "all"}:
            p = encode_gif(tmp, FPS_GIF)
            mb = p.stat().st_size / 1024 / 1024
            print(f"gif    : {p} ({mb:.2f} MB)")
            if mb > 6.0:
                print("         WARNING: GIF above 6 MB — lower GIF_WIDTH or FPS_GIF", file=sys.stderr)

        if args.what in {"poster", "all"}:
            p = write_poster(tmp, FPS_MASTER)
            print(f"poster : {p} ({p.stat().st_size / 1024:.0f} KB)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
