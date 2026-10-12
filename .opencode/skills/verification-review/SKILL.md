---
name: verification-review
description: Review an implementation or result against defined criteria and evidence (CRITERIA, EVIDENCE, VALIDATION, GAPS, RISKS, STATUS), reaching PASS, PARTIAL, BLOCKED or FAIL. Use when auditing tests, file changes, diffs, git state, hashes, schemas, runtime, logs, docs or acceptance criteria, distinguishing "no evidence found" from "verified absent" and never inventing results.
metadata:
  system: system-engineering
  schema_version: "1"
  adapter: opencode
---

# verification-review

## purpose

Revisar una implementación o resultado contra evidencia y criterios definidos, y
clasificarlo sin inventar resultados ni transformar ausencia de evidencia en PASS.

## when_to_use

- Al verificar que un trabajo cumple criterios de aceptación explícitos.
- Al auditar un resultado previo (checkpoint, release, cambio) con evidencia.
- Cuando haya que decidir PASS / PARTIAL / BLOCKED / FAIL de forma demostrable.

## when_not_to_use

- Para preparar o ejecutar el trabajo: usa `se plan|implement|verify`.
- Como reemplazo de la autorización de cambios: esta Skill NO modifica código.
- Cuando no existan criterios definidos: primero definir criterios (o marcar el review BLOCKED).

## inputs

- Criterios de aceptación (explícitos: tests, funcionalidad, contrato, docs).
- Evidencia: archivos modificados, diff, git, hashes, salidas de tests, schemas, runtime,
  logs, documentación.
- Baseline (estado anterior) cuando aplique.

## preconditions

- Criterios definidos y legibles para el revisor.
- Evidencia accesible (repos, logs, salidas) y verificable de forma independiente.
- El resultado final del checkpoint NO puede usarse como única fuente de evidencia.

## procedure

1. **CRITERIA**: listar los criterios y el peso de cada uno (requerido/informativo).
2. **EVIDENCE**: recolectar evidencia primaria por criterio: tests ejecutados, diffs,
   git status, hashes, schema validation, salidas de runtime/logs, docs.
3. **VALIDATION**: por cada criterio, comprobar contra su evidencia. Distinguir:
   - **VERIFIED**: hay evidencia y cumple.
   - **NO_EVIDENCE**: no se encontró evidencia → el criterio queda UNKNOWN (no aprobar).
   - **ABSENT**: se verificó activamente que el elemento no existe (probado; documentar cómo).
4. **GAPS**: listar criterios sin evidencia (NO_EVIDENCE) o con evidencia contradictoria.
5. **RISKS**: riesgos reales observados; no opiniones no demostradas.
6. **STATUS**:
   - **PASS**: todos los criterios requeridos VERIFIED.
   - **PARTIAL**: criterios requeridos cumplidos parcialmente (gaps documentados).
   - **BLOCKED**: falta evidencia o criterios para continuar.
   - **FAIL**: criterio requerido contradicho por evidencia.

## evidence

Solo evidencia primaria reproducible (salidas de comandos, hashes, diff, logs firmados).
Las opiniones sin soporte no son evidencia. Un resultado final declarado (p. ej. un
checkpoint PASS) es un dato, no una prueba: hay que revisar la evidencia subyacente.

## validation

- El review es válido si cada criterio tiene una etiqueta clara de evidencia
  (VERIFIED / NO_EVIDENCE / ABSENT) y el STATUS se deriva de esas etiquetas.
- "No se encontró evidencia" ≠ "se verificó que no existe": la segunda requiere
  haber comprobado activamente la ausencia.

## failure_modes

- Confundir NO_EVIDENCE con PASS.
- Usar la conclusión final como única fuente.
- Inventar resultados, hashes o salidas.
- Juzgar sin criterios o con evidencia irrelevante.

## outputs

- Revisión por criterio con etiqueta de evidencia, lista de gaps, riesgos y STATUS
  final con justificación derivada de la evidencia.

## restrictions

- NO modifica código ni ejecuta cambios destructivos (read-only salvo lo ya autorizado).
- NO inventa resultados; si no hay evidencia, decide NO_EVIDENCE/BLOCKED.
- NO usa la conclusión final del checkpoint como evidencia única.
- Complementa contracts/agents/commands/policies; no los reemplaza.