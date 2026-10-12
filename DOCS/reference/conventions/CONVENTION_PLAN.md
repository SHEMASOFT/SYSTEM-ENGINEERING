# Convention: Plan (verificación por tarea)

**Guard: ARCH-ECOSYSTEM-002, F5 · P2/P3 — documental + informativa.** Todo plan
(WORK/ARCH) declara, **por cada tarea**, el paso de verificación que la cierra.
Hace la verificación un ciudadano de primera clase del plan, sin endurecer gates.

## Regla

Cada tarea del plan lleva:

- `verification.step`: qué comando/criterio la verifica (suite local, `se validate`,
  `se doctor`, test específico, revisión con lente).
- `verification.evidence`: EVD esperada/emitida al cierre (result PASS/FAIL, link a
  artifact/task).
- `verification.by`: quién la ejecuta (tester/implementer/reviewer o human).

Una tarea **no se marca completada** sin su paso de verificación resuelto. Esto es
convención; la autoridad de cierre sigue siendo `se verify` G5 y la política de evidence.

## Verificación automatizada (informativa)

- `se validate` emite **WARN no bloqueante** (F5) ante referencias colgantes a skills
  (`SK-000x` sin `SKILL.json` declarándola).
- `se gate --gate G5` imprime **GUIDE: MIN_EVIDENCE** con el criterio mínimo
  (G5.1/G5.2/G5.3) — orientación, no nueva condición.

Referencias: `DOCS/CONVENTION_SPEC_DELTA.md` (delta del plan) ·
`DOCS/CONVENTION_PLAN_ROLES.md` (lead/roles) ·
`TEMPLATES/convention.plan.verify.example.json`.