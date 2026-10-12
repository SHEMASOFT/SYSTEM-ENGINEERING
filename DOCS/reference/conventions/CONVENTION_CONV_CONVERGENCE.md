# Convention: conv.convergence

**Guard: ARCH-ECOSYSTEM-002, F4 · P3 — documental.** Mantener **un solo término por
concepto** y **una sola fuente de verdad** entre agentes, skills y docs del Master
System (evita duplicación y ambigüedad léxica).

## Principio

El lenguaje del sistema converge: un concepto tiene un nombre canónico. Cuando dos
nombres compiten, se decide en una ADR o en la nota del documento de cambio, y el
nombre ganador pasa a la guía/skills correspondientes.

## Reglas

1. Identificar términos en colisión al añadir una skill/doc nuevo (grep previo).
2. Si el término ya existe con otro nombre, **reusar** el canónico; no inventar sinónimo.
3. Los sinónimos residuales se registran como alias en la sección `glosario` del doc,
   marcando el canónico.
4. Verificación: ningún doc introduce una definición contradictoria del mismo término.

## Ejemplo histórico aplicado

- `SK-0004` como `dbg-systematic` (NO `dbg.systematic`) — nombre canónico del folder/skill.
- `metadata.review_lens` como campo canónico de lente (NO `review.lens`/`reviewLens`).

Referencias: `DOCS/CONVENTION_CONV_CONVERGENCE.md` ·
`TEMPLATES/convention.conv.convergence.example.md`.