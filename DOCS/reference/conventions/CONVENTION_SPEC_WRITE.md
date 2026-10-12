# Convention: spec.write

**Guard: ARCH-ECOSYSTEM-002, F4 · P3 — documental.** Cómo redactar una *especificación*
en SYSTEM-ENGINEERING cuando el proyecto necesita un documento de referência de
requisitos (al margen de REQUIREMENT/TASK records del lifecycle).

## Principio

La spec es **declarativa, verificable y trazable**. Una frase de spec = un
requisito comprobable; nunca un consejo cualitativo sin criterio de aceptación.

## Reglas

1. Escribir la spec como lista de declaraciones `WHEN <contexto> THEN <comportamiento>`.
2. Cada declaración referenciada (p.ej. `SPEC-0001`) y vinculable a REQUIREMENT/TASK/EVD.
3. Profundidad proporcional a la criticalidad del activo (CP default `risk` del proyecto).
4. Se versiona con el documento de cambio correspondiente (`ARCH-`/`WORK-`), no aislada.

## Anti-patrones

- Espec que describe *cómo* se implementa (eso es el plan/tasks).
- Requisitos sin criterio de aceptación o sin evidencia de cierre.

## Verificación

- `se review` no debe reportar gaps introducidos por la spec (requisito↔task↔EVD).
- Términos del negocio usados consistentemente (ver `conv.convergence`).

Referencias: `DOCS/CONVENTION_SPEC_WRITE.md` (este) · ejemplo `TEMPLATES/convention.spec.write.example.md`.