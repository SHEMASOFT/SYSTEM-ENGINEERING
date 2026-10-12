# Convention: plan.roles

**Guard: ARCH-ECOSYSTEM-002, F4 · P3 — documental.** Asignar **un rol por tarea** en
los planes (WORK/ARCH) y mantenerlo durante la ejecución, para que cada tarea tenga un
dueño inequívoco y una trazabilidad verificable.

## Principio

Toda tarea de un plan tiene exactamente un *lead* responsable y, opcionalmente,
colaborator/reseñador. El rol no implica permisos globales: los permisos los decide el
capability resolver (CP-020) al ejecutar.

## Reglas

1. En la tarea, declarar `lead` (agente o humano) y opcional `reviewers`/`contributors`.
2. `lead` responde del artefacto y del cierre (EVD/verificación); quien review no
   participa como autoridad de la misma pieza (ver `rev.code_review`).
3. Los roles se declaran por tarea y cambian explícitamente (nota en el CHANGELOG/delta),
   no implícitamente.
4. Verificación: todas las tareas de un plan tienen `lead` resuelto; ninguna cierra sin
   el paso de verificación (ver convención de plan F5 y `plan.roles`).

Referencias: `DOCS/CONVENTION_PLAN_ROLES.md` ·
`TEMPLATES/convention.plan.roles.example.json`.