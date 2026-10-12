# Project Bootstrap — `se init <project>`

> Capacidad de distribución (CHECKPOINT-005, MASTER SYSTEM v0.7.0). Permite instalar la
> capa OpenCode de un proyecto (AGENTS.md, adapter-manifest.json, `.opencode/`) directamente desde
> los contratos canónicos del Master System, sin copiar archivos a mano.
> Soporte: ADR-0015 (adapter-only bridge) + ADR-0017 (generation pipeline).

## Objetivo

Un proyecto **nuevo o existente** puede inicializarse desde SYSTEM-ENGINEERING con un solo
comando. El Master System no se copia al proyecto: los artefactos se **generan** a partir de
los contratos (`AGENTS/*/agent.json`, `COMMANDS/commands.json`, `SKILLS/`), y la instalación
se registra en un manifest de instalación verificable.

## Flujo

```
se init <project-path> [--agents a,b,c] [--skills s1,s2] [--force]
```

1. Se resuelve el proyecto: si `PROJECT.json` existe se usa como fuente de verdad; si no, se
   crea uno nuevo (proyecto vacío) con valores derivados del directorio y las opciones CLI.
2. Se valida el `PROJECT.json` contra `project-context.schema.json` y `project.schema.json`.
3. Se calcula la selección: `--agents`/`--skills` tienen prioridad; si no se pasan, se usan
   las declaraciones `required_agents` e `inherited_skills` del `PROJECT.json`.
4. Se genera la capa OpenCode (mismo pipeline del adapter, selección limitada a lo pedido).
5. Si todo es válido, se escribe el proyecto; en caso de error no se deja nada a medias
   (el `PROJECT.json` nuevo se escribe solo tras el éxito de la generación).

## Que genera

```
<project>/
├── PROJECT.json                 # contexto del proyecto (creado o reutilizado)
├── AGENTS.md                    # documentación de los agentes instalados
├── adapter-manifest.json        # manifest del adapter (artefactos + hashes de contenido)
├── MASTER-SYSTEM-MANIFEST.json  # manifest de instalación (ver abajo)
└── .opencode/
    ├── agent/<role>.md          # solo los agentes solicitados
    ├── command/<name>.md        # todos los comandos canónicos del adapter
    └── skill/<name>/SKILL.md    # solo las skills declaradas (ninguna si SKILLS/ está vacío)
```

## Reglas

- **Agentes**: se instalan **solo los solicitados** (`required_agents` en `PROJECT.json` o
  `--agents`). Los no solicitados no se copian.
- **Comandos**: los 13 comandos canónicos se instalan siempre; `init` en el proyecto es
  global y el bootstrap es quien los materializa.
- **Skills**: solo las declaradas (`inherited_skills` o `--skills`). Skills desconocidas →
  `FAIL` con la lista de disponibles.
- **Agentes/skills desconocidos**: el comando falla (exit 1) y no escribe nada.
- **Idempotencia**: re-ejecutar el comando no cambia ningún archivo (`Wrote 0 file(s)`);
  los hashes de contenido coinciden byte a byte.
- **No destructivo**: nunca borra contenido del proyecto; solo crea/actualiza los archivos
  generados. Proyectos existentes (`.gitignore`, `discovery.json`, archivos del usuario)
  se conservan intactos.
- **Determinista**: escritura LF, orden fijo, sin timestamps en el contenido generado.
- **Aislamiento**: el proyecto instalado no copia CORE/SCHEMAS; depende de la distribución
  instalada (ADR-0016). El guard de seguridad `PROJECTS` del adapter del repositorio sigue
  activo; el bootstrap es la vía explícita de distribución a proyectos.

## Hardening de target y categorías (CP-016)

Desde CHECKPOINT-016 el target se resuelve y valida antes de escribir nada:

1. **Resolución determinista**: `se init <path>` con ruta absoluta se usa tal cual; un
   `se init <name>` simple (sin separadores) se resuelve bajo `PROJECTS/<name>` **si ese
   directorio existe**; si no existe ni bajo `PROJECTS/` ni como directorio real del CWD, el
   comando falla sin crear nada (evita el footgun de rutas relativas al CWD).
2. **Transparencia**: se imprime `TARGET: <ruta-resuelta>` antes de escribir.
3. **Protección de la infraestructura**: se rechaza inicializar la raíz del repositorio o
   `PROJECTS/`.
4. **EXTERNAL rechazado**: `se init` estándar se niega sobre un proyecto EXTERNAL/INDEPENDENT
   (declarado con `metadata.category: EXTERNAL` o detectado por marcadores `AGENTS.md`/
   `.opencode`/`opencode.json`/`SDD` sin `PROJECT.json`). No existe `--force` que lo salte.
5. **No-overwrite**: ningún artefacto existente de un proyecto independiente se sobrescribe
   silenciosamente; la re-ejecución sobre un MANAGED sigue siendo idempotente.

Detalle completo en `DOCS/PROJECT_POLICY.md`.

## Selección de agentes y skills

| Fuente | Prioridad |
|--------|-----------|
| `--agents ...` / `--skills ...` (CLI) | 1 (sobrescribe) |
| `PROJECT.json` → `required_agents` / `inherited_skills` | 2 (si no hay flags) |
| Proyecto vacío sin flags | 0 agentes, 0 skills (comandos sí se instalan) |

`PROJECT.json` acepta ambas propiedades como opcionales (extension aditiva de
`project.schema.json`, v0.7.0):

```json
{
  "schema_version": "1",
  "project_id": "PRJ-DEMO",
  "name": "Demo",
  "owner": "me",
  "domains": ["software"],
  "lifecycle_state": "DRAFT",
  "required_agents": ["architect", "reviewer"],
  "inherited_skills": []
}
```

## Manifest de instalación

`MASTER-SYSTEM-MANIFEST.json` conforma `SCHEMAS/installation-manifest.schema.json`
(registrada en `SCHEMAS/index.json`):

- `distributor`: `"se init"`, `adapter_id`: `"opencode"`;
- `installed`: agentes/comandos/skills instalados (orden estable);
- `files`: `rel → sha256` de cada archivo generado (`.opencode/...`, `AGENTS.md`,
  `adapter-manifest.json`, el propio manifest);
- `validation`: `content-hash` habilitado;
- `metadata`: counts y versión del generador.

## Verificación posterior

```powershell
se doctor                          # contracts / adapter / manifests PASS, configuration 0.7.0
se validate --project <project>    # valida PROJECT.json contra los schemas
```

`se init` deja el proyecto listo para `explore`, `plan`, `review`, etc. La capa OpenCode del
propio repositorio se regeneró con la versión 0.7.0 (`se adapter opencode`).

## Ejemplos

```powershell
# Proyecto vacío: crear PROJECT.json y materializar la capa OpenCode
python SCRIPTS\se.py init .workspaces\demo --agents architect,reviewer,security

# Proyecto existente con PROJECT.json (usa required_agents / inherited_skills)
python SCRIPTS\se.py init .workspaces\demo

# Selección explícita de skills (falla si no existen en SKILLS/)
python SCRIPTS\se.py init .workspaces\demo --agents architect --skills documentation
```

## Cobertura

`TESTS/test_project_bootstrap.py`: proyectos vacíos, no-destrucción de proyectos existentes,
generación correcta de agentes, no-copia de agentes no solicitados, hashes coherentes,
doctor/validate posteriores, idempotencia, rechazo de agentes/skills desconocidos y de
`PROJECT.json` inválido.