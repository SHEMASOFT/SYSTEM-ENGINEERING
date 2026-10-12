---
$schema: https://github.com/google-labs-code/design.md
type: design-spec
title: VFE Demo — Product Landing Page
version: 0.1.0
---

# Design Tokens

```yaml
tokens:
  color.bg: "#ffffff"
  color.surface: "#f8fafc"
  color.text: "#0f172a"
  color.muted: "#475569"
  color.primary: "#2563eb"
  color.primary.contrast: "#ffffff"
  color.border: "#e2e8f0"
  color.good: "#047857"
  color.bad: "#b91c1c"
  type.family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
  type.h1.size: "clamp(2rem, 5vw, 3.25rem)"
  type.h2.size: "clamp(1.5rem, 3vw, 2rem)"
  type.base: "1rem"
  space.unit: "0.5rem"
  space.card: "1.5rem"
  space.section: "clamp(3rem, 8vw, 6rem)"
  radius.card: "1rem"
  radius.btn: "9999px"
```

# Design Principles

- **Contraste WCAG**: texto sobre fondo ≥ 4.5:1 (2:1 solo para texto decorativo ≥ 24px).
- **Jerarquía tipográfica**: un solo h1 claro, h2 para secciones, base legible (≥ 1rem).
- **Responsive**: grid fluido con `auto-fit`; móvil 375px sin overflow horizontal.
- **Estados**: `:focus-visible` visible, hover con feedback; nunca quitar outline del foco.
- **Accesibilidad**: landmarks semánticos, `alt` en toda imagen, sólo un h1.

# Estructura objetivo (AFTER)

`header/nav` → `h1` → `main` con `section` cards → `footer`. Imágenes `alt` descriptivo.

# Dungeones de diseño (BEFORE)

- Fuente base 12px, contraste `#333` sobre fondo con `#ccc`, layout `<table>`.
- Sin alt, sin landmark, `div`-soup, sin foco visible, overflow al estrechar.