# AGENTS Migration (CHECKPOINT-003)

Este directorio documenta la migración de los contratos de agentes desde el vocabulario
legacy hacia el contrato canónico (ADR-0020). No contiene código; es registro de la
estrategia aplicada y de la limitación del `$ref`.

## Estrategia

```
legacy:   AGENTS/<rol>/agent.json  (vocabulario name/purpose/responsibilities/...)
        +
          AGENTS/_contract/agent.schema.json  (schema legacy)

   v   migración aditiva (FASE 2)
   v   conserva TODOS los campos legacy
   v   añade: id, version, role, description, capabilities, lifecycle

canonical:  SCHEMAS/agent-contract.schema.json  (superset, valida legacy + nuevo)
```

- **No se elimina** ningún archivo legacy.
- Los agentes migrados validan **contra ambos** schemas: el legacy
  (`AGENTS/_contract/agent.schema.json`) y el canónico (`SCHEMAS/agent-contract.schema.json`).
- La consolidación del schema legacy se hace vía `SCHEMAS/index.json`: el nombre lógico
  `agent` pasa a resolver el contrato canónico. `AGENTS/_contract/agent.schema.json` queda
  como referencia legacy inmutable (documentada, no eliminada).

## Asignaciones

Agentes (12) migrados con `id` secuencial (orden alfabético de directorio), `version: 1.0.0`,
`role` = `name`, `lifecycle.status: ACTIVE` con `since: 2026-09-19`.

| AG-#### | Rol | Notas |
|---------|-----|-------|
| AG-0001 | analyst | capabilities derivadas de responsibilities |
| AG-0002 | architect | idem |
| AG-0003 | coordinator | gates G0..G8 completos |
| AG-0004 | devops | única con DEPLOY |
| AG-0005 | documentation | liberación (G7, G8) |
| AG-0006 | explorer | read-only |
| AG-0007 | implementer | IMPLEMENT + TEST |
| AG-0008 | planner | G2, G3 |
| AG-0009 | reviewer | G5, G6 |
| AG-0010 | security | TEST |
| AG-0011 | tester | TEST |
| AG-0012 | visual | IMPLEMENT |

## Vocabulario por dominio

- `execution_intent` y `risk_level` **no** son campos del agente en el schema canónico
  (`additionalProperties: false`); son vocabulario de comandos. Véase Riesgo R1 del AUDIT.
- `description`, `capabilities`, `lifecycle` se derivan de `purpose`/`responsibilities`
  existentes, sin alterar el contenido legacy.

## Limitación documentada: `$ref`

Reemplazar el cuerpo de `_contract/agent.schema.json` por un `"$ref"` externo no es seguro:
el diseño exige schemas self-contained y el runtime valida sin registry
(`SCRIPTS/se_core/schemas.py`). La consolidación efectiva se logra apuntando el nombre
lógico `agent` del `SCHEMAS/index.json` al contrato canónico.

Próximo hito (CHECKPOINT-004): `se adapter opencode` consumirá el vocabulario canónico para
generar `.opencode/agent|command|skill`.