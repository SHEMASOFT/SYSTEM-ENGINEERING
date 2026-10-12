# OpenCode Adapter

> Adapter oficial: `se adapter opencode` (v0.6.0, ADR-0015 / ADR-0017 / ADR-0020).

El adaptador transforma los **contratos canónicos** del SYSTEM-ENGINEERING en artefactos
OpenCode generados (`.opencode/`). La fuente de verdad **no cambia**:

| Fuente única | Salida generada |
|---|---|
| `AGENTS/*/agent.json` | `.opencode/agent/<role>.md` |
| `COMMANDS/commands.json` | `.opencode/command/<cmd>.md` |
| `SKILLS/*/SKILL.md` | `.opencode/skill/<skill>/SKILL.md` |
| `CORE/policies/*`, `POLICIES/*.md` | auditadas (mapeo de permisos) |

No se crean agentes directamente en `.opencode`: `.opencode` es **solo salida generada**.

## Arquitectura

```
AGENTS/ COMMANDS/ SKILLS/ POLICIES/
        |
        v
Contract Layer (SCHEMAS/*-contract.schema.json, index.json)
        |
        v
SCRIPTS/se_core/opencode/
  generator.py   <- autoridad de generación (plan + escritura / dry-run)
  mappings.py    <- contracts -> markdown / adapter-manifest.json / AGENTS.md
  validators.py  <- validación de entrada (contracts) y salida (adapter-manifest)
        |
        v
.opencode/
  agent/*.md  command/*.md  skill/*  adapter-manifest.json  AGENTS.md
```

## Comando

```powershell
python SCRIPTS\se.py adapter opencode                # genera en .opencode/
python SCRIPTS\se.py adapter opencode --dry-run      # muestra el plan, no escribe
python SCRIPTS\se.py adapter opencode --output <dir> # salida personalizada
```

Flujo interno:

1. **Leer contratos**: 12 `AGENTS/*/agent.json`, `COMMANDS/commands.json` (13), skills, policies.
2. **Validar schemas**: agentes vs `agent-contract.schema.json`; comandos vs
   `command-contract.schema.json`; skills (frontmatter `name`/`description`/`metadata`,
   nombre igual a la carpeta).
3. **Generar archivos**: markdown con frontmatter OpenCode + cuerpo derivado del contrato.
4. **Resumen**:

```
OpenCode Adapter
Agents: 12 generated
Commands: 13 generated
Skills: 0 generated
Config: generated
Status: PASS
```

Si la validación falla, `Status: FAIL` y **no se escribe nada**.

## Mapeo

### Agent (`agent/<role>.md`)

```yaml
---
description: <description>
mode: subagent
permission: {}
---
```

El cuerpo enriquece con `id`, `version`, `purpose`, `gates`, `capabilities`,
`restrictions`, `permissions` y `verification_requirements` (todo derivado del contrato).

### Command (`command/<cmd>.md`)

```yaml
---
description: <description>
agent: <primary_agent>
---
```

Cuerpo: `id`, `version`, `purpose`, `execution_intent`, `risk_level`, `gate`,
`permissions`, `arguments`; ejecución como `se <name> --project $ARGUMENTS`
(`doctor`/`validate` no requieren `--project`).

### Skills (`skill/<skill>/SKILL.md`)

Se valida el frontmatter (`name`, `description`, `metadata`) y que `name` coincida con la
carpeta antes de copiar el archivo fuente. Desde CHECKPOINT-017 las Skills canónicas son
`checkpoint-release` (SK-0001) y `verification-review` (SK-0002), cada una con su sidecar
`SKILLS/<skill>/SKILL.json` (contrato `SCHEMAS/skill-contract.schema.json`). Se copian al
repo (`.opencode/skill/`) y a los proyectos que las declaran en `inherited_skills`.

## Garantías

- **Idempotencia**: bytes idénticos entre ejecuciones (orden fijo, sin timestamps, LF).
- **Seguridad**: guard que impide escribir bajo un segmento de ruta `PROJECTS`.
- **Manifiesto**: `adapter-manifest.json` conforma a `SCHEMAS/adapter-manifest.schema.json` e
  incluye `metadata.content_hashes` (sha256 por archivo) para detección de drift.
- **Determinismo**: escritura con `newline="\n"` (misma salida en Windows/Linux).

## Limitaciones OpenCode

- El frontmatter (`mode: subagent`, `permission`) es un **mapeo *hint***; la autoridad sigue
  siendo el contrato canónico (sección `## Permissions` del cuerpo). `permission` se emite
  como `{}`: el runtime de OpenCode valida `permission` como objeto (`PermissionActionConfig`,
  15 tools, cada una `allow|ask|deny`) y un escalar rompe el parse en v1.18.31; un objeto
  vacío hereda la política global sin sobreescribir nada.
- La CLI no expone un subcomando `command`; los artefactos invocan `se <name>` directamente.
- `.opencode/` en la raíz del repo puede ser interpretado por OpenCode como instrucciones
  (`AGENTS.md`). En un proyecto, `se adapter opencode --output <proyecto>/.opencode` genera
  el mismo material dentro del workspace del proyecto (el guard impide `PROJECTS/`).

## Diferencia contratos vs salida

| | Contratos | Salida generada |
|---|---|---|
| Rol | Fuente de verdad | Artefacto consumible |
| Ubicación | `AGENTS/`, `COMMANDS/`, `SKILLS/` | `.opencode/` |
| Edición | manual (gobernada, ADR-0019) | **prohibida**; regenerar |
| Validación | schemas canónicos | frontmatter + adapter-manifest |
| Comitido | sí | sí (como snapshot versionada) |

## Instalación futura (global)

El adapter está pensado para instalarse como `se` global (distribución `MASTER SYSTEM`,
ADR-0016). Cuando exista instalación global:

- `se adapter opencode` generará en el proyecto actual (o `--project <dir>`).
- `se adapter opencode --output ~/.config/opencode/agent` publicará agentes globales
  (fuera del alcance de este checkpoint; requiere revisión de permisos).

## Verificación

- `TESTS/test_opencode_adapter.py` (15 tests: 12 agentes, 13 comandos, skills, config,
  idempotencia, `--dry-run`, guard de seguridad `PROJECTS`).
- `se doctor` reporta `contracts`, `adapter` y `manifests` como PASS (validación hermenéutica).