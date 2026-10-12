# spec.write — ejemplo

```markdown
## Especificación (spec)

- **SPEC-0001** WHEN el usuario autentica y su sesión es válida THEN se le muestra el panel
  principal en <=2s (percebible, medible).
- **SPEC-0002** WHEN una operación falla y la transacción ya fue confirmada THEN el sistema
  registra un EVD de resultado FAIL y lo vincula a la tarea.
- **SPEC-0003** WHEN el contenido del activo cambia THEN el diff queda registrado con autor
  (humano o agente) y trazabilidad (ARCH/WORK + commit).

## Criterios de aceptación (por spec line)

- SPEC-0001: latencia medible en EVD type=test; tolerancia declarada.
- SPEC-0002: EVD con result FAIL presente en el proyecto.
- SPEC-0003: diff + autor + referencia al documento de cambio.
```