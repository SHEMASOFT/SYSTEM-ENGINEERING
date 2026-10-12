---
name: rev-adversarial
description: Adversarial review lens (behavioral skill): review by actively looking for non-conformity and reviewer blind spots instead of confirming the result. Record the lens in metadata.review_lens of the type=review EVIDENCE and do not accept a delivery until objections are answered.
metadata:
  system: system-engineering
  schema_version: "1"
  adapter: opencode
  checkpoint: CP-023
---

# rev-adversarial

## purpose

Poner a la revisión a buscar la no-conformidad (evidencia que rompe el claim) en vez
de validar el claim. Previene aprobaciones que "ven lo que esperan ver" y deja
objeciones explícitas respondidas antes de cerrar.

## when_to_use

- Al revisar implementaciones, checkpoints o resultados donde el autor ya está
  convencido de que está bien.
- Cuando el costo de una aprobación errónea es alto (gates G5/G6, releases, claims
  de evidencia).
- Al auditar claim vs evidence (complementa `verification-review` con lente).

## when_not_to_use

- Como reemplazo de la autorización de cambios (NO aprueba releases).
- Para trabajo propio (el revisor debe ser independiente).
- Cuando no hay entregable claro al que objetar (primero definir el alcance).

## inputs

- Entregable a revisar (artefactos, evidencia, claims, diffs).
- Criterios contra los que revisar (ACE, requisitos, contrato).
- Evidencia primaria disponible para contrastar.

## preconditions

- El revisor es independiente del autor.
- Criterios objetivos y legibles.
- Se puede registrar la lente en metadata.review_lens de la EVD type=review.

## procedure

1. **ESTABLECER LENTE**: elegir y declarar `metadata.review_lens` (vocabulario
   semilla: adversarial, quality_assurance, security, traceability, compliance,
   usability, performance); describir qué busca esa lente.
2. **BUSCAR NO-CONFORMIDAD**: para cada claim, intentar **refutarlo** primero con
   evidencia; registrar cada objeción con la evidencia que la motiva.
3. **CATALOGAR OBJECIONES**: severidad, criterio afectado y evidencia en contra.
4. **EXIGIR RESPUESTA**: no aceptar mientras existan objeciones sin responder
   (corregir, evidencia, o aceptación documentada del riesgo).
5. **DECIDIR**: PASS solo si todas las objeciones se respondieron conforme al
   criterio; PARTIAL si quedan gap/riesgos aceptados; FAIL si hay no-conformidad
   demostrada sin resolver.

## evidence

EVD type=review con lente declarada, lista de objeciones, evidencia de cada una y
estado de respuesta. La ausencia de objeciones encontradas se registra como tal
(no como "verificado") si no se probó activamente.

## validation

- Válido si cada claim tuvo intento de refutación explícito y las objeciones
  registradas tienen evidencia y estado de respuesta.
- PASS sin lente declarada o sin intento de refutación = revisión no válida.

## failure_modes

- Revisar confirmando el resultado en vez de refutarlo.
- Omitir la lente (revisión genérica sin objetivo).
- Ignorar objeciones del revisado (PASS sin respuesta).
- Confundir "no encontré objeciones" con "no hay objeciones".

## outputs

- EVD de revisión con lente, objeciones (evidencia + severidad), respuestas y
  decisión PASS/PARTIAL/FAIL justificada.

## restrictions

- NO aprueba releases; el cierre es del owner.
- NO revisa trabajo propio.
- NO inventa objeciones ni evidencia.
- Complementa `verification-review`, G5/G6 y `se review`; no los sustituye.