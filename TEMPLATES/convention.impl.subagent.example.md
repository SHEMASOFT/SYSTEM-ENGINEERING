# impl.subagent — ejemplo de contrato

```markdown
## Contrato para subagente `implementer`

- **Entradas**: requisito REQ-0001 aprobado; spec SPEC-0001; repos elegidos.
- **Producir**: artefacto ART-0001 con su EVD (result PASS/FAIL) y diff.
- **Restricciones**: NO commit/push; NO tocar CORE/; solo archivos bajo ESCRITURA permitida.
- **Verificación**: suite local + `se validate` + revisión con lente (AG-0009).
- **Fallback**: si hay bloqueo real, reportar en vez de cubrir con evidencia falsa.
```