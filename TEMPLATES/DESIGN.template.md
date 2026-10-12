---
$schema: https://github.com/google-labs-code/design.md
type: design-spec
title: <Project/UI name>
version: 0.1.0
status: draft
last_reviewed: <YYYY-MM-DD>
---

# ≤ 3 line summary

Which page/component this design governs, the business goal, and what "done visually"
means (verified by screenshot + WCAG checks, not vibes).

# Design tokens

```yaml
tokens:
  color.bg: "#ffffff"
  color.surface: "#f8fafc"
  color.text: "#0f172a"            # ≥ 4.5:1 on color.bg (WCAG AA)
  color.muted: "#475569"           # ≥ 4.5:1 on color.bg ; avoid < 4.5 for body text
  color.primary: "#2563eb"
  color.primary.contrast: "#ffffff"
  color.border: "#e2e8f0"
  color.good: "#047857"
  color.bad: "#b91c1c"
  type.family: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
  type.base: "1rem"
  type.h1: "clamp(2rem, 5vw, 3.25rem)"
  type.h2: "clamp(1.5rem, 3vw, 2rem)"
  space.unit: "0.5rem"
  space.section: "clamp(3rem, 8vw, 6rem)"
  radius.card: "1rem"
  radius.control: "9999px"
  layout.maxwidth: "64rem"
```

# Design decisions

- **Contrast**: define the paired (foreground, background) pairs in tokens; a check must
  assert WCAG AA (≥ 4.5:1 normal text, ≥ 3:1 large text) — no exceptions for body copy.
- **Typography**: one `<h1>` per page; hierarchy h1>h2>h3; base ≥ 1rem; fluid `clamp()`.
- **Spacing**: spacing scale from `space.unit`; consistent rhythm; whitespace is a feature.
- **States**: visible `:focus-visible` (never removed), hover feedback; disabled states ≥ 3:1.
- **Responsive**: desktop 1280 and mobile 375 both screenshot-verified; no horizontal overflow.

# Not-in-scope (avoid "AI slop")

- No decorative gradients/glows without a stated function.
- No latin placeholder text (`Lorem ipsum`) in shipped UI — use real content or `<<PLACEHOLDER>>`.
- No emojis as primary affordance; icons only with accessible labels.
- No fixed pixel widths inside responsive layouts it shrinks/hides.

# Evidence checklist

- [ ] `snapshot`: landmarks (header/nav/main/footer), single h1, images with alt.
- [ ] `screenshot` viewport 1280x800 + full-page named `rN-*`.
- [ ] `screenshot` mobile 375x812 + full-page, no horizontal overflow.
- [ ] contrast pairs automated (muted, lead, nav links, buttons, footer).
- [ ] DESIGN.md version bumped with each material change.

## References

- Google DESIGN.md spec (Apache-2.0): https://github.com/google-labs-code/design.md
- Anthropic frontend-design principles (Apache-2.0)
- Vercel web-interface-guidelines (MIT)