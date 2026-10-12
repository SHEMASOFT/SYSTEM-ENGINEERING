# Convention: Review Lenses (metadata.review_lens)

**Guard: ARCH-ECOSYSTEM-002, P3.** Etiqueta cada revisión con su **objetivo** a
través del campo `metadata.review_lens` de la EVIDENCIA de tipo `review`
(`metadata` es objeto libre en `SCHEMAS/evidence/evidence.schema.json`). Vocabulario
**abierto** (sin enum cerrado) con un **set semilla** documentado; sin cambio de
schema hoy (ADR requerido para promover a propiedad de schema).

## Vocabulario semilla

`adversarial` · `quality_assurance` · `security` · `traceability` · `compliance` ·
`usability` · `performance`

La lente declara *qué busca esa revisión* y endurece el hallazgo: cada objeción
tiene la evidencia que la motiva. `rev-adversarial` (SK-0005) es el consumidor
de la lente.

## Uso

- En `new`/`update` de EVIDENCE type=review, añadir:

```json
"type": "review",
"metadata": {
  "review_lens": "adversarial",
  "gate": "G6"
}
```

- El revisor registra la lente; la lente condiciona el checklist y el reporte.

## Validación vs futuro

- Hoy: convención documental + metadata libre (sin validación de enum).
- Promoción a propiedad de schema SOLO con consumidor real de indexado/consulta
  (requisito `ARCH-ECOSYSTEM-002-01` §D.8): entonces con ADR.

## Integración (reviewer)

`AGENTS/reviewer/agent.json` (AG-0009) declara comportamiento vía skills y docs;
su rol no cambia. Guía de integración: `DOCS/REVIEW_LENSES.md`.

## Referencias

`ARCH-ECOSYSTEM-002-01-DECISION.md` §D · `SKILLS/rev-adversarial/` ·
`SCHEMAS/evidence/*` · `TESTS/test_evidence*` (metadata válida).