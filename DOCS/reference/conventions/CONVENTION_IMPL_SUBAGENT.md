# Convention: impl.subagent

**Guard: ARCH-ECOSYSTEM-002, F4 · P3 — documental.** Reglas para delegar trabajo de
implementación a subagentes: contrato claro, autoridad acotada y cierre verificable.

## Principio

Un subagente recibe un **contrato** (qué necesita producir, con qué entradas, bajo qué
restricciones y cómo se verificará). La autoridad del subagente está acotada por
`capabilities` del plan (CP-020) — nunca por el texto del prompt a solas.

## Reglas

1. El prompt al subagente declara: entradas, salida esperada, límites (NO COMMIT/PUSH,
   no tocar X), y el criterio de verificación.
2. El subagente reporta evidencia (rutas/archivos/diffs) de lo producido; "lo hice" sin
   rastro no es entrega.
3. El resultado se verifica por el lead (test/validate/review) antes de integrarlo.
4. Si un subagente no puede cumplir, reporta obstáculo en vez de inventar salida.

## Relación con skills

`impl-tdd` (SK-0006) es la disciplina de comportamiento del subagente implementador
(RED-GREEN-REFACTOR, opt-in); no cambia gates ni autoridad de cierre (`se verify` G5 y
la política de evidence siguen mandando).

Referencias: `DOCS/CONVENTION_IMPL_SUBAGENT.md` · `SKILLS/impl-tdd/` ·
`TEMPLATES/convention.impl.subagent.example.md`.