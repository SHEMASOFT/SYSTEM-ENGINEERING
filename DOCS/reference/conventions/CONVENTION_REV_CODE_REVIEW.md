# Convention: rev.code_review

**Guard: ARCH-ECOSYSTEM-002, F4 · P3 — documental.** Cómo ejecutar una code review en
proyectos gestionados por SYSTEM-ENGINEERING: objetividad, evidencia por hallazgo y
uso de lentes (`metadata.review_lens`).

## Principio

Una revisión es un **juicio fundamentado con evidencia**, no una opinión. Todo
hallazgo se expresa con: qué se observó (archivo/línea/columna donde aplique),
por qué importa (criterio), y qué evidencia lo sustenta.

## Reglas

1. Registrar la revisión como EVIDENCE `type=review`, con `metadata.review_lens`
   (ver `DOCS/REVIEW_LENSES.md` y convención de lentes). Reviewer transversal = AG-0009.
2. El autor del código no revisa su propio trabajo como autoridad final (criterio
   `G6`/cobertura).
3. Cada objeción se etiqueta a un hallazgo reproducible; "sentía que estaba mal" no es
   revisión — el hallazgo incluye el criterio y la traza (p.ej. `se doctor`), o pasa a ser
   duda (WARN, no bloqueante).
4. Risks/gaps se reportan como FYI/WARN; solo hallazgos con criterio aceptado son FAIL.

## Verificación

- La EVD de revisión lista los hallazgos y su estado final (ied.).
- `rev-adversarial` (SK-0005) puede usarse como lente adversarial automática.

Referencias: `DOCS/CONVENTION_REV_CODE_REVIEW.md` · `DOCS/REVIEW_LENSES.md` ·
`AGENTS/reviewer/agent.json` (AG-0009) · ejemplo `TEMPLATES/convention.rev.code_review.example.md`.