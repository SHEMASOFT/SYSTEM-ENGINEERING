#!/usr/bin/env python3
"""Render the SYSTEM ENGINEERING hero clips from the scenes in this folder.

Deterministic pipeline, no new dependencies: Playwright renders the scene and the
ffmpeg binary bundled with ``imageio_ffmpeg`` encodes the result. Every frame is a
pure function of time (``window.__render(t)``), so the output is reproducible.

    python DOCS/visuals/hero/render.py all                    # 16:9 for the README
    python DOCS/visuals/hero/render.py all --format vertical   # 9:16 for shorts/reels

Outputs (written to ``DOCS/assets``):

    wide       hero.mp4 (1440x810) · hero.gif (880 px) · hero-poster.png
    vertical   hero-vertical.mp4 (1080x1920) · hero-vertical-poster.png
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

FORMATS = {
    "wide": {
        "scene": HERE / "scene.html",
        "size": (1440, 810),
        "video": "hero.mp4",
        "gif": "hero.gif",
        "gif_width": 1000,
        "poster": "hero-poster.png",
        "poster_at": 6.9,
    },
    "vertical": {
        "scene": HERE / "scene-vertical.html",
        "size": (1080, 1920),
        "video": "hero-vertical.mp4",
        "gif": None,
        "gif_width": None,
        "poster": "hero-vertical-poster.png",
        "poster_at": 5.6,
    },
}

DURATION = 8.0
FPS_MASTER = 30
FPS_GIF = 18


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


def render_frames(dest: Path, cfg: dict, fps: int, duration: float) -> int:
    from playwright.sync_api import sync_playwright

    width, height = cfg["size"]
    dest.mkdir(parents=True, exist_ok=True)
    total = int(round(duration * fps))
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(cfg["scene"].as_uri())
        page.wait_for_timeout(250)
        for i in range(total):
            page.evaluate("t => window.__render(t)", i / fps)
            page.screenshot(path=str(dest / f"f{i:04d}.png"))
        browser.close()
    return total


def encode_video(frames: Path, cfg: dict, fps: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / cfg["video"]
    subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(fps),
         "-i", str(frames / "f%04d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19",
         "-preset", "slow", "-movflags", "+faststart", str(dest)],
        check=True,
    )
    return dest


def encode_gif(frames: Path, cfg: dict, fps: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / cfg["gif"]
    vf = (
        f"fps={fps},scale={cfg['gif_width']}:-1:flags=lanczos,split[s0][s1];"
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


def write_poster(frames: Path, cfg: dict, fps: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / cfg["poster"]
    idx = int(round(cfg["poster_at"] * fps))
    src = frames / f"f{idx:04d}.png"
    if not src.exists():
        src = sorted(frames.glob("f*.png"))[-1]
    shutil.copyfile(src, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", choices=["frames", "video", "gif", "poster", "all"], nargs="?", default="all")
    ap.add_argument("--format", choices=sorted(FORMATS), default="wide")
    args = ap.parse_args()

    cfg = FORMATS[args.format]
    if not cfg["scene"].exists():
        print(f"missing scene: {cfg['scene']}", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="se-hero-"))
    try:
        if args.what in {"frames", "all"}:
            n = render_frames(tmp, cfg, FPS_MASTER, DURATION)
            print(f"frames : {n} @ {FPS_MASTER} fps -> {tmp}")
        else:
            render_frames(tmp, cfg, FPS_MASTER, DURATION)

        if args.what in {"video", "all"}:
            p = encode_video(tmp, cfg, FPS_MASTER)
            print(f"video  : {p} ({p.stat().st_size / 1024 / 1024:.2f} MB)")

        if args.what in {"gif", "all"} and cfg["gif"]:
            p = encode_gif(tmp, cfg, FPS_GIF)
            mb = p.stat().st_size / 1024 / 1024
            print(f"gif    : {p} ({mb:.2f} MB)")
            if mb > 6.0:
                print("         WARNING: GIF above 6 MB — lower GIF_WIDTH or FPS_GIF", file=sys.stderr)

        if args.what in {"poster", "all"}:
            p = write_poster(tmp, cfg, FPS_MASTER)
            print(f"poster : {p} ({p.stat().st_size / 1024:.0f} KB)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
