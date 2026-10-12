# Convention: arch.impact

**Guard: ARCH-ECOSYSTEM-002, F4 · P3 — documental.** Declarar **qué se toca y qué no**
al proponer/implementar un cambio de arquitectura, para que el reviewer sepa el alcance
y los riesgos de forma inmediata.

## Principio

Todo cambio arquitectónico declara su **impacto** sobre: agentes, skills, commands,
CORE (schemas/gates), DOCS, registries y projects. "No tocar X" se dice explícitamente,
igual que "verificado que no se toca".

## Reglas

1. En el documento del cambio (ARCH/WORK), sección `## Impacto`: tabla o lista con
   `IN-SCOPE` y `OUT-OF-SCOPE`.
2. Los elementos declarados OUT-OF-SCOPE se verifican al cierre (grep/evidencia), no se
   asumen.
3. Si el impacto real difiere del declarado, el cambio se detiene hasta re-declararlo.
4. Los cambios de schema/gates van cubiertos por ADR + batch de tests que lo prueban.

## Verificación

- `se doctor` + `se validate` post-cambio sin nuevas WARN/FAIL en el alcance declarado.
- Grep de que los OUT-OF-SCOPE no mutaron (p.ej. MCP/HOME untouched).

Referencias: `DOCS/CONVENTION_ARCH_IMPACT.md` · `ARCH-ECOSYSTEM-002-02` §2 (IN/OUT table) ·
ejemplo `TEMPLATES/convention.arch.impact.example.md`.