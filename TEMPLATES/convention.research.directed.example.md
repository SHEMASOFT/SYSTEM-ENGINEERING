# research.directed — ejemplo

```markdown
## Pregunta
Q1: ¿Qué capability (CP-020) cubre el debugging sistemático sin añadir providers?

## Dominios acotados
- `CORE/capabilities/capabilities.json` (registry canónico)
- `DOCS/reference/governance/CAPABILITY_GOVERNANCE.md`
- grep de capabilities existentes en skills previas

## Evidencia
- EVD: registry contiene `structured.reasoning`, `filesystem.read`, `filesystem.search`.
- `se capabilities --check` PASS tras declararlas en SK-0004.

## Conclusión
**CERRADA**: `dbg-systematic` (SK-0004) usa solo capabilities existentes; sin ADR/provider nuevo.
```