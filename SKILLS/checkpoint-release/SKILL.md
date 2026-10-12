---
name: checkpoint-release
description: Prepare, review and validate a SYSTEM-ENGINEERING technical checkpoint or release into a verifiable checklist (BASELINE, SCOPE, CHANGES, VALIDATION, TESTS, EVIDENCE, RISKS, GIT STATE, STATUS, NEXT STEP). Use when closing or auditing a checkpoint (CHECKPOINT-###), before declaring PASS, or when a deliverable must report scope, changes, evidence and git state with claims tagged FACT/VERIFIED/INFERRED/UNKNOWN/CONFLICTING.
metadata:
  system: system-engineering
  schema_version: "1"
  adapter: opencode
---

# checkpoint-release

## purpose

Estandarizar la preparación y validación de un checkpoint/release técnico de
SYSTEM-ENGINEERING: convertir un scope real, cambios reales y evidencia en una
secuencia verificable, clasificando cada afirmación.

## when_to_use

- Al cerrar un checkpoint/release (CHECKPOINT-###, MASTER-###) y producir AUDIT/REPORT.
- Antes de declarar PASS sobre un checkpoint ya cerrado.
- Cuando un entregable deba reportar modificaciones, tests, evidencia y estado Git
  de forma estructurada.

## when_not_to_use

- Para ejecutar operaciones: usa los commands `se verify|validate|doctor|gate|release`.
- Para investigación abierta o debugging: usa explorer/analyst.
- Cómo autorización: esta Skill es procedimiento; la autorización viene del usuario/contexto.

## inputs

- Scope declarado (objetivo, inclusión/exclusión).
- Modificaciones reales (paths, contexto del cambio).
- Evidencia: salidas de tests, doctor, validate, git status, hashes.
- Baseline conocido (tests, doctor, estado Git, versión) y checkpoint previo (CP-016 etc.).

## preconditions

- Scope autorizado y escrito.
- Evidencia recolectable (tests corribles, git legible, archivos legibles).
- Agente corriendo dentro del entorno SYSTEM-ENGINEERING correcto.

## procedure

1. **BASELINE**: registrar el estado inicial verificado (suite de tests, doctor, git, versiones).
2. **SCOPE**: listar lo declarado; todo lo observado fuera de él es **scope drift**.
3. **CHANGES**: listar archivos modificados/creados y su razón; explicar cualquier cambio
   no derivado del scope.
4. **VALIDATION**: mapear cada requisito del scope a evidencia concreta (tests, hashes,
   salidas de comandos).
5. **TESTS**: ejecutar la suite completa cuando corresponda; registrar conteo y fallos;
   comparar contra el baseline.
6. **EVIDENCE**: citar salidas completas. Cada afirmación se etiqueta:
   - **FACT**: observable directo (existe un archivo, un test corrió, un hash es X).
   - **VERIFIED**: comprobado activamente en esta sesión (comando ejecutado).
   - **INFERRED**: conclusión derivada de hechos; se marca como interpretación.
   - **UNKNOWN**: no hay evidencia; pendiente de trabajo o inaccesible.
   - **CONFLICTING**: la evidencia apunta en direcciones opuestas; resolver antes de cerrar.
7. **RISKS**: listar riesgos reales con mitigación; riesgos de diseño no son defectos.
8. **GIT STATE**: reportar siempre el estado Git (HEAD, dirty, cambios) aunque no se
   commitée; registrar NO COMMIT/NO PUSH salvo autorización explícita.
9. **STATUS**: PASS / PARTIAL / BLOCKED / FAIL según los criterios de validación.
10. **NEXT STEP**: qué sigue (próximo checkpoint, decisiones pendientes).

## evidence

Salidas completas de comandos (suite, doctor, validate), git status, hashes (sha256),
paths enumerados. Si no hay evidencia de algo, declararlo UNKNOWN — nunca inferir PASS.

## validation

- PASS: cada ítem del scope tiene VERIFIED; sin drift sin explicar; tests sin regresiones
  nuevas; evidencia citada; estado Git documentado; riesgos enumerados.
- PARTIAL / BLOCKED / FAIL según faltantes: evidencia ausente, tests rotos, drift,
  claims no verificadas, GIT no documentado.
- "No se encontró evidencia" NO es "se verificó que no existe".

## failure_modes

- Scope drift silencioso; cambios no explicados; tests faltantes o no ejecutados;
  evidencia insuficiente; claims sin verificar; estado Git omitido; modificaciones
  fuera de scope; resultados repetidos como "hecho" sin verificación.

## outputs

- Entrada preparada para el reporte del checkpoint: scope, cambios, evidencia, riesgos,
  git, status, next step, con etiquetas FACT/VERIFIED/INFERRED/UNKNOWN/CONFLICTING.

## restrictions

- NO COMMIT / NO PUSH / NO RESET salvo autorización explícita del usuario/contexto.
- No crear ni modificar AUDIT/REPORT automáticamente sin autorización.
- No fabricar evidencia; no transformar ausencia de evidencia en PASS.
- La Skill provee procedimiento/contexto; los commands ejecutan operaciones.