# OpenCode adapter (`se_core/opencode`)

Transforma contratos canónicos del SYSTEM-ENGINEERING en artefactos OpenCode
generados (`.opencode/`). La fuente de verdad sigue en `AGENTS/*/agent.json`,
`COMMANDS/commands.json`, `SKILLS/*/SKILL.md` y `POLICIES/*.md`; todo lo que se
escribe en la salida es **solo salida generada**.

## Archivos

| Módulo | Responsabilidad |
|--------|-----------------|
| `__init__.py` | API pública (`generate`) |
| `generator.py` | Orquestación: lee contratos, valida, construye plan, escribe (o `--dry-run`) |
| `mappings.py` | Serialización determinista contracts -> `.md` / `adapter-manifest.json` / `AGENTS.md` |
| `validators.py` | Validación de contratos de entrada y del manifiesto de salida |

## Uso

```powershell
python SCRIPTS\se.py adapter opencode                 # genera en .opencode/
python SCRIPTS\se.py adapter opencode --dry-run       # muestra el plan, sin escribir
python SCRIPTS\se.py adapter opencode --output <dir>  # salida personalizada
```

## Garantías

- **Idempotencia**: contenido determinista (orden fijo, sin timestamps); dos ejecuciones
  producen bytes idénticos.
- **Seguridad**: nunca escribe dentro de un segmento de ruta `PROJECTS` (guard en
  `generator._guard_output`).
- **Validación**: los contratos de entrada se validan contra `agent-contract.schema.json`
  y `command-contract.schema.json`; `adapter-manifest.json` se valida contra
  `adapter-manifest.schema.json`. Si falla, `Status: FAIL` y no se escribe nada.
- **Manifiesto**: `adapter-manifest.json` declara input, artifacts, generated_files, validation
  (content-hash) y `metadata.content_hashes` (sha256 por archivo) para detección de drift.
- **Conformance del árbol** (AUTO-08): `validators.audit_adapter(root, output)` compara un
  árbol generado o desplegado contra su propio manifiesto: identidad y versiones, ruta de
  descubrimiento de skills, frontmatter, byte-identidad de las skills, `content_hashes`
  y `capability_plan` frente al registro canónico (CP-020). `se doctor` falla si hay drift.
  La comparación se limita a las rutas que posee el adaptador (`agent/`, `command/`,
  `skill/`, `AGENTS.md`), de modo que archivos del runtime de OpenCode en el mismo
  directorio (`package.json`, `node_modules/`, `.gitignore`) no se consideran.

## Límites

- El frontmatter OpenCode (`mode: subagent`, `permission`) es un mapeo *hint*: la fuente
  autoritativa sigue siendo el contrato canónico.
- La ejecución se documenta como `se <name> --project $ARGUMENTS` (la CLI no expone un
  subcomando `command`).