# spec.delta — ejemplo de convención (brownfield "qué cambia")

Contexto: documento de cambio sobre una baseline existente. No reescribe la spec;
declara qué cambia y por qué, con la mínima traza.

```markdown
## Delta (sobre baseline v0.10.0)

- **ADDED** `SKILLS/dbg-systematic/` (SK-0004): workflow de debugging sistemático
  (workflow skill). New capability de proceso transversal; aditivo, sin CORE.
- **ADDED** `SKILLS/rev-adversarial/` (SK-0005): lente adversarial; registra
  `metadata.review_lens` en EVD type=review. Behavioral.
- **ADDED** `SKILLS/impl-tdd/` (SK-0006): disciplina test-first opt-in
  (RED-GREEN-REFACTOR). Behavioral.
- **MODIFIED** `TESTS/test_skills.py`: `CANONICAL_SKILLS` 3 -> 6 (aditivo).
- **VERIFIED** suite verde, `se doctor` 15/2/0 o superior, `se validate` PASS.

Alertas:
- **REMOVED** n/a en este delta. Sin cambios breaking (sin marca BREAKING).
```

Guía de tipos: `ADDED` (nuevo, backward-safe), `MODIFIED` (compat declarada),
`REMOVED` (justificar + breaking?), `VERIFIED` (cambio ya comprobado).