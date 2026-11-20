---
name: impl-tdd
description: Test-first implementation (behavioral, opt-in): RED -> GREEN -> REFACTOR with the test as contract of acceptance for the change. Apply when the task/policy calls for it (opt-in); NOT mandatory for every task and does not harden any gate.
metadata:
  system: system-engineering
  schema_version: "1"
  adapter: opencode
  checkpoint: CP-023
---

# impl-tdd

## purpose

Implementar con disciplina test-first: la prueba fija el contrato del cambio y la
implementación pasa cuando la prueba pasa. Reduce regresiones y hace que "terminado"
tenga una definición objetiva (suite verde), sin sustituir la autoridad de G5.

## when_to_use

- Cuando la tarea/política declare test-first (opt-in) o el entregable sea código
  con comportamiento verificable.
- Cuando el contrato de aceptación pueda expresarse como caso de prueba.
- Al implementar correcciones donde una regresión es costosa.

## when_not_to_use

- Como obligación para toda tarea (es opt-in; `se verify` G5 sigue siendo autoridad).
- Para trabajo puramente documental o sin comportamiento verificable.
- Si no existe runner/herramienta de test en el proyecto (definir qué significa
  "verde" antes de aplicar).

## inputs

- Tarea/requisito con criterio de aceptación expresable como costo de prueba.
- Estado actual del área (si hay suite existente, adaptarse a su convención).
- Herramienta de test disponible en el proyecto.

## preconditions

- Opt-in activo (tarea o política) o caso claramente testeable.
- Existe una forma ejecutable de correr la suite/tests.
- El cierre `se verify` G5 se ejecutará además de la suite.

## procedure

1. **RED**: escribir el test que falla (contrato del cambio); ejecutarlo y
   registrar que falla por la razón esperada (no por error de setup).
2. **GREEN**: implementar el mínimo cambio para que pase; ejecutar la suite y
   registrar verde.
3. **REFACTOR**: limpiar (según convención del proyecto) manteniendo la suite verde.
4. **INTEGRAR**: registrar en la EVD/reporte G5 el modo test-first, tests
   ejecutados y resultado; correr `se verify`/`se gate` según el flujo.

## evidence

- Test en RED con salida (la que falla).
- Test en GREEN tras el cambio mínimo; suite completa (o subset relevante) en verde.
- Referencia a la EVD y resultado de cierre si aplica.

## validation

- Válido si el ciclo RED->GREEN->REFACTOR quedó documentado con salidas reales.
- "El test pasó" sin mostrar el fallo inicial (RED) no demuestra test-first.

## failure_modes

- Escribir el test y "hacerlo pasar" sin ver el fallo inicial.
- Refactor con suite roja.
- Aplicar TDD como dogma donde no aplica (opt-in violado).
- Saltarse la verificación de cierre G5 tras la suite verde.

## outputs

- Tests (cambio de contrato) + cambio de implementación + evidencia RED/GREEN +
  nota de cierre (resultado de `se verify`/`se gate`).

## restrictions

- Opt-in: NO mandatorio para todas las tareas ni endurece gates.
- NO relaja la autoridad de cierre de `se verify` G5.
- NO escribe la prueba para que pase sin verificar el caso.
- Complementa implementer/tester y sus contracts; no los reemplaza.