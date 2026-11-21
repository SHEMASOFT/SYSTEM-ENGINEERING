---
name: dbg-systematic
description: Systematic debugging workflow (workflow skill): reproduce -> hypothesis -> isolate -> fix -> verify, recording each hypothesis and its outcome as checkable EVD. Use when a failure/incident needs diagnosis that ends in demonstrable verification instead of blind fixes.
metadata:
  system: system-engineering
  schema_version: "1"
  adapter: opencode
  checkpoint: CP-023
---

# dbg-systematic

## purpose

Convertir el arreglo de fallos en un procedimiento reproducible: diagnosticar con
hipótesis explícitas, aislar causa, corregir y **verificar** el cierre con evidencia.
Evita el "cambio a ciegas" y deja un rastro demostrable de qué se probó y por qué
funcionó.

## when_to_use

- Ante un fallo/incidencia reproducible en código, datos o flujo.
- Cuando un cambio "ya se arregló" pero no hay verificación que lo cierre.
- Al depurar un problema que involucra varias capas (UI, lógica, datos, entorno).

## when_not_to_use

- Para tareas de implementación sin fallo conocido (usa `impl.tdd` / workflow normal).
- Como revisión de calidad: usa `verification-review`.
- Cuando no hay forma de reproducir ni verificar (primero definir cómo hacerlo o
  declarar el diagnóstico BLOCKED).

## inputs

- Fallo observado: qué se esperaba, qué pasó, dónde.
- Acceso al área afectada (repositorio, logs, entorno, artefactos).
- Evidencia inicial: salidas, errores, reproducción mínima si existe.

## preconditions

- El fallo es reproducible o al menos observable con entrada/salida.
- Se puede ejecutar una verificación después del cambio propuesto.
- Acceso de lectura al área afectada y (autorizado) de escritura para corregir.

## procedure

1. **REPRODUCIR**: construir una reproducción mínima o pasos deterministas;
   registrar cómo se reproduce (EVD) — si no se puede reproducir, detenerse y
   declarar BLOCKED con lo observado.
2. **HIPÓTESIS**: formular hipótesis de causa (una o varias, ordenadas);
   cada una se registra como EVD con su predicción comprobable.
3. **AISLAR**: reducir el espacio de búsqueda (binario, por capas, por datos);
   verificar/refutar hipótesis con evidencia, no con opinión.
4. **CORREGIR**: aplicar el cambio mínimo consistente con la hipótesis confirmada.
5. **VERIFICAR**: re-ejecutar la reproducción y las verificaciones relevantes
   (tests, `se verify`, checks estructurales); registrar el resultado como EVD.
6. **CERRAR**: resumir causa raíz, cambio, evidencia y verificación. Si la
   verificación no pasa, volver al paso 2 (máximo 3 rondas; después escalar).

## evidence

Cada paso emite EVD comprobable: reproducción, hipótesis (confirmada/refutada,
con la evidencia que la decidió), diff del cambio y resultado de verificación.
Un fallo "arreglado" sin verificación no es evidencia de cierre.

## validation

- Válido si: el fallo se reprodujo y se registró; al menos una hipótesis se
  confirmó con evidencia; el cambio se verificó (tests/checks) después de aplicarlo.
- "No encontré la causa" ≠ "refuté la hipótesis": cada refutación requiere la
  evidencia que la sostiene.

## failure_modes

- Saltar la reproducción y diagnosticar del aire.
- Corregir sin verificar el cierre.
- Refutar/confirmar hipótesis sin evidencia.
- Enmarañar el cambio (corrección no mínima) oscureciendo la causa.

## outputs

- EVD por paso (reproducción, hipótesis, verificación), diff del cambio y resumen
  final causa raíz -> cambio -> verificación con estado CERRADO / ESCALADO.

## restrictions

- NO modifica código fuera del flujo autorizado para el fallo.
- NO cierra sin verificación; si no se puede verificar, declara BLOCKED/ESCALADO.
- NO inventa hipótesis, causas ni resultados.
- Complementa los commands se plan|implement|verify|gate; no los reemplaza.