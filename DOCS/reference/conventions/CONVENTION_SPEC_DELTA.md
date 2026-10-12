# Convention: spec.delta (ADDED / MODIFIED / REMOVED)

**Guard: ARCH-ECOSYSTEM-002, P2 — OPTATIVA.** Difunde a los change docs de
SYSTEM-ENGINEERING una notación mínima "qué cambia" en contexto *brownfield*, sin
reescribir la spec completa. Origen: OpenSpec (`ADDED/MODIFIED/REMOVED` +
`WHEN/THEN`), adaptado como convención documental ADAPT_NATIVE (cero schema, cero
CORE).

## Cuando aplicar

- Documentos de cambio/checkpoint que describan *evolución* sobre una spec o
  baseline existente (ARCH-*, WORK-*, CHECKPOINT-*-REPORT).
- Notas de release/CHANGELOG que necesiten explicitar el delta sobre la versión
  anterior.
- Contextos `project-context.profiles.work.type = brownfield`.

Posición por defecto: **optativa**. Se promoverá a obligatoria únicamente con
demanda brownfield real (≥2 proyectos gestionados pidiéndola — criterio ADR-0014).

## Formato

Cada entrada del delta:

```
- **<TIPO>** `ref/área`: qué cambió, con la mínima traza (why) y WHEN/THEN si aplica.
```

| Tipo | Uso |
|---|---|
| `ADDED` | Elemento nuevo que no existía en el baseline (backward-safe). |
| `MODIFIED` | Comportamiento/contrato existente alterado (indicar compat). |
| `REMOVED` | Elemento eliminado (justificar; recordar si es breaking). |
| `VERIFIED` | Cambio ya verificado (tests/validate/evidencia) en este delta. |

## Ejemplo

```markdown
## Delta (sobre v0.10.0)

- **ADDED** `SKILLS/dbg-systematic/` (SK-0004): workflow de debugging sistemático;
  new, aditivo, sin tocar skills previas.
- **ADDED** `SKILLS/rev-adversarial/` (SK-0005): lente adversarial
  (metadata.review_lens); behavioral.
- **ADDED** `SKILLS/impl-tdd/` (SK-0006): test-first opt-in (RED-GREEN-REFACTOR).
- **VERIFIED** suite 288 OK (baseline pre-F1) → suite verde post-F1;
  `se doctor` 15/2/0; `se validate` PASS.
```

## Validación / límites

- La notación es *informativa*: `se validate` emite un **WARN** (no bloqueante)
  cuando encuentra una sección Delta con entradas sin tipo del vocabulario
  (`ADDED/MODIFIED/REMOVED/VERIFIED`), pero **nunca cambia el exit code** de
  validate ni ninguna condición de gate.
- No reescribe la spec: describe el *cambio* sobre ella.

## Referencias

`ARCH-ECOSYSTEM-002-01-DECISION.md` §C · `DOCS/CAPABILITY_GOVERNANCE.md` ·
`COMMANDS/commands.json` (`validate`) · OpenSpec stand-alone convention (attribution
documental).