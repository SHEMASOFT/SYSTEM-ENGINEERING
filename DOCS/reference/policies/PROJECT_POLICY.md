# PROJECT POLICY — MANAGED vs EXTERNAL/INDEPENDENT

> Política de topología de proyectos (CHECKPOINT-015/016). Define cómo SYSTEM-ENGINEERING
> clasifica, escanea y (si procede) inicializa directorios bajo `PROJECTS/`.

## Categorías

### MANAGED — administrado por SYSTEM-ENGINEERING

- Tiene (o está a punto de recibir) un `PROJECT.json` conforme a `project.schema.json`.
- Participa normalmente en el ciclo de vida SE: `se init`, `explore`, `plan`, `implement`,
  `verify`, `review`, `transition`, `release`, `gate`, `validate --project`,
  `handoff`, `archive`, `restore`.
- `se init` puede (re)generar su capa OpenCode de forma idempotente.
- `doctor` y `validate` escanean su contenido (secrets, self-containment, integridad JSON).

### EXTERNAL / INDEPENDENT — proyecto independiente

- Proyecto con gobernanza propia (`.git` propio, `.opencode` autoritativo, `AGENTS.md` raíz,
  SDD, infraestructura/scripts propios).
- **Puede residir físicamente dentro de `PROJECTS/`**.
- **`PROJECT.json` NO es obligatorio.**
- `se init` estándar **refundado** (no hay `--force` para saltarlo; se prefiere el rechazo seguro).
- La herramienta SE **no lo modifica automáticamente**: `se init`, `se explore/plan/...` y las
  escrituras no deben operar sobre él.
- `doctor`/`validate` **no tratan la ausencia de `PROJECT.json` como defecto**; solo escanean
  lo que realmente corresponde a la política EXTERNAL (nada). Los artefactos del proyecto
  EXTERNAL quedan fuera del escaneo de SE.

## Cómo se declara / detecta la categoría

`metadata.category` (opcional, aditivo) en el `PROJECT.json` / `project-context`:

```json
{ "metadata": { "category": "EXTERNAL" } }
```

Valores canónicos: `MANAGED`, `EXTERNAL`. Cualquier otro valor es rechazado por el schema.

Resolución determinista (`SCRIPTS/se_core/projects.py::project_category`):

| Condición | Categoría |
|---|---|
| `PROJECT.json` con `metadata.category` válido | esa categoría |
| `PROJECT.json` sin categoría | `MANAGED` (compatibilidad retro) |
| Sin `PROJECT.json` y con artefactos independientes (`AGENTS.md`, `.opencode/`, `opencode.json`, `SDD/`) | `EXTERNAL` |
| Sin `PROJECT.json` y sin marcadores | `None` (no clasificado; no escaneado) |

## `se init` — hardening (CP-016)

1. El target se resuelve de forma determinista: rutas absolutas tal cual; **nombres simples
   (`se init <name>`) se resuelven bajo `PROJECTS/<name>` cuando el directorio existe**; si no
   existe ni bajo `PROJECTS/` ni como directorio real del CWD, el comando falla sin crear nada.
2. El target real se imprime (`TARGET: <path>`) antes de escribir.
3. Se rechaza inicializar la propia infraestructura (raíz del repositorio o `PROJECTS/`).
4. Se rechaza el bootstrap estándar sobre un target EXTERNAL (declarado o por marcadores).
5. Ningún artefacto existente se sobrescribe silenciosamente: `AGENTS.md`, `.opencode/`,
   `opencode.json`, `SDD/`, `PROJECT.json` de un proyecto independiente nunca se tocan.
6. La idempotencia MANAGED se conserva (`Wrote N file(s)`, re-ejecución = `Wrote 0`).

## Doctor y validate

- `doctor` aplica el conjunto correcto de checks por categoría: los escaneos globales
  (secrets, self-containment, integridad JSON) **omiten los directorios EXTERNAL** bajo
  `PROJECTS/` (y los no clasificados). Se sigue exigiendo lo exigible para MANAGED.
- `validate --project` sobre un EXTERNAL no inventa un `PROJECT.json`: valida el manifest
  **solo si existe** y reporta PASS con la categoría visible. Un directorio SIN `PROJECT.json`
  y sin clasificar sigue fallando igual que antes (`no PROJECT.json`).

## Estado actual

| Directorio | Categoría |
|---|---|
| `PROJECTS/<managed-project>` | `MANAGED` (has a `PROJECT.json` manifest) |
| `PROJECTS/<external-project>` | `EXTERNAL` (no `PROJECT.json`; never migrated or moved) |

## Adopción de un EXTERNAL → MANAGED

No se hace con `se init` estándar. Requiere **decisión del propietario del proyecto** y un
**checkpoint de integración dedicado** que preserve `AGENTS.md`, `.opencode/`, `opencode.json`
y `SDD/` antes de introducir la capa SE.

## Implementación

- `SCRIPTS/se_core/projects.py` (clasificación + resolución de target).
- `SCHEMAS/project/project.schema.json` y `SCHEMAS/project-context.schema.json`:
  `metadata.category` (aditivo).
- `SCRIPTS/se_core/commands.py` (`cmd_init`, `cmd_init_bootstrap`, `cmd_validate`).
- `SCRIPTS/se_core/doctor.py` (escaneos category-aware).
- `TESTS/test_project_policy.py`.