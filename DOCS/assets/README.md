# Repository assets

Publishing material used by the root README and by the repository's social
preview. Everything here is **generated**, never edited by hand.

| File | Size | Used for |
|---|---|---|
| `hero.gif` | ~2.2 MB, 1000 px, 18 fps | The animated hero at the top of `README.md` (GitHub autoplays GIFs; it does not embed MP4) |
| `hero.mp4` | ~0.38 MB, 1440×810, 8 s | The "same clip as MP4" link, release attachments and social posts |
| `hero-poster.png` | ~0.22 MB, 1440×810 | Repository social preview and static fallbacks |
| `hero-vertical.mp4` | ~0.42 MB, 1080×1920, 8 s | Shorts, Reels and TikTok — same story, vertical cut |
| `hero-vertical-poster.png` | ~0.25 MB, 1080×1920 | Cover image for the vertical platforms |
| `social-60s.mp4` | ~1.95 MB, 1080×1920, 60 s | The full social clip: problem → coordinator → gates → memory → ODD/SDD/RDD → real `se doctor` → call to action |
| `social-60s-poster.png` | ~0.34 MB, 1080×1920 | Cover for the 60 s clip |

## Regenerate

```bash
python DOCS/visuals/hero/render.py all                    # 16:9 for the README
python DOCS/visuals/hero/render.py all --format vertical   # 9:16 for shorts
python DOCS/visuals/social/render.py all                   # 60 s social clip
```

The pipeline is deterministic: each `scene.html` is a scene parameterised by
time (`window.__render(t)`), Playwright renders every frame and the ffmpeg
binary bundled with `imageio_ffmpeg` encodes the result. No extra dependency is
required beyond what the repository tooling already uses.

Editing the video means editing the scene (copy, positions in the `NODES` array
and the `--cyan` / `--magenta` custom properties), not the exported files.

## Palette

Brand ramp cyan → magenta; the four capability states keep their own accents so
colour is never the only signal (the page and the video always print the status
label next to the colour):

| Token | Hex | Meaning |
|---|---|---|
| cyan | `#00E5FF` | brand, start of the flow, *implemented* |
| blue | `#3B82F6` | *depends on route/config* |
| magenta | `#FF2BD6` | brand end of the flow, *new* badge |
| slate | `#64748B` | *not implemented* |

## Social preview

GitHub does not read this folder automatically. Upload `hero-poster.png` once in
**Settings → Social preview** so shared links render the card instead of the
generic placeholder.
