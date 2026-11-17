# Repository assets

Publishing material used by the root README and by the repository's social
preview. Everything here is **generated**, never edited by hand.

| File | Size | Used for |
|---|---|---|
| `hero.gif` | ~1.7 MB, 880 px, 18 fps | The animated hero at the top of `README.md` (GitHub autoplays GIFs; it does not embed MP4) |
| `hero.mp4` | ~0.34 MB, 1440×810, 8 s | The "same clip as MP4" link, release attachments and social posts |
| `hero-poster.png` | ~0.19 MB, 1440×810 | Repository social preview and static fallbacks |

## Regenerate

```bash
python DOCS/visuals/hero/render.py all
```

The pipeline is deterministic: `DOCS/visuals/hero/scene.html` is a scene
parameterised by time (`window.__render(t)`), Playwright renders every frame and
the ffmpeg binary bundled with `imageio_ffmpeg` encodes the three files. No
extra dependency is required beyond what the repository tooling already uses.

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
