# Instalar SE en DeepSeek Harness (DSH)

Guía corta y en español para dejar SYSTEM-ENGINEERING funcionando dentro de
DeepSeek Harness. No necesitas cuenta de nadie: todo se genera desde el propio
repo.

> **Idea en una línea:** SE no se "instala dentro" de DSH. SE genera unos
> archivos que DSH sabe leer, y tú se los aplicas con `--patch`.

---

## 0. Qué necesitas

| Requisito | Para qué |
|---|---|
| `python` 3.10+ | Ejecutar `se` y los servidores MCP |
| `node` + `npx` | Servidores MCP |
| Un clon de SYSTEM-ENGINEERING | Fuente de los contratos |
| DSH instalado | Aplicar el overlay |

Comprueba el clon:

```powershell
cd C:\ruta\a\SYSTEM-ENGINEERING
python SCRIPTS\se.py doctor
```

Si `doctor` no da `FAIL=0`, no sigas: primero arregla eso.

---

## 1. Genera la capa de DSH

```powershell
python SCRIPTS\se.py adapter deepseek
```

Escribe **tres cosas** en la raíz del proyecto:

```
AGENTS.local.md               ← quiénes son los 12 roles y 27 comandos
.dsh\se.patch.yml             ← el overlay con un preset por rol
.dsh\skills\<skill>\SKILL.md  ← las 7 skills de SE
```

Para ver qué haría sin escribir nada:

```powershell
python SCRIPTS\se.py adapter deepseek --dry-run
```

> Se llama `AGENTS.local.md` y no `AGENTS.md` a propósito: así no choca con el
> archivo que genera el adapter de Codex si usas los dos.

---

## 2. Aplícalo en DSH

Para una sesión:

```powershell
dsh --patch .dsh\se.patch.yml
```

Para dejarlo fijo en un perfil:

```powershell
Get-Content .dsh\se.patch.yml | Add-Content "$env:DSH_HOME\profiles\<perfil>\cordis.patch.yml"
```

---

## 3. Elige al coordinador

En DSH **no hay** un "agente primario" como en OpenCode. El coordinador es un
**preset más** dentro del overlay, con nombre `shema-ai-coordinador`.

- Selecciona ese preset cuando quieras que la sesión orqueste.
- Los otros 11 roles son los subagentes a los que delega.
- El coordinador **no implementa**: enruta, exige gates y mantiene trazabilidad.

Si no aparece, revisa que el patch se aplicó:

```powershell
Select-String -Path .dsh\se.patch.yml -Pattern "preset-shema-ai-coordinador"
```

---

## 4. Monta los MCP (manual, una vez)

DSH monta MCP en la fila `mcp-manager` del perfil (`config.servers`). El adapter
solo los **lista** en `AGENTS.local.md`; no toca tu perfil.

Los cuatro servidores de SE:

| Servidor | Qué aporta |
|---|---|
| `context7` | Documentación de librerías |
| `filesystem` | Lectura/escritura de archivos del proyecto |
| `se-memory-server` | Memoria compartida de SE |
| `se-skill-server` | Descubrimiento de skills |

Ejemplo mínimo para el perfil:

```yaml
- id: mcp-manager
  config:
    servers:
      se-memory-server:
        command: node
        args: [SCRIPTS/se_core/mcp/launch.mjs, SCRIPTS/se_core/mcp/memory_server.py]
      se-skill-server:
        command: node
        args: [SCRIPTS/se_core/mcp/launch.mjs, SCRIPTS/se_core/mcp/skill_server.py]
```

---

## 5. Modelos

DSH 0.2.2-rc.3 solo enlaza modelo por agente en las filas de launcher y
delegación (`agent-loop.agents[]`, `tool-subagent.agentOptions`). Un preset no
lleva ruta de modelo.

Por eso el adapter:

- anota el modelo de cada rol como comentario `# model: provider/model`;
- escribe `agent-default-model` **solo si todos los roles usan el mismo**;
- si no hay modelo configurado, no inventa nada.

Para configurarlo:

```powershell
python SCRIPTS\se.py shema-ai model --global-model openai/gpt-4o
python SCRIPTS\se.py adapter deepseek
```

Si los roles usan modelos distintos, DSH elegirá la ruta por sesión.

---

## 6. Verifica

```powershell
# 1. El patch es YAML válido
python -c "import yaml; yaml.safe_load(open('.dsh/se.patch.yml', encoding='utf-8')); print('YAML OK')"

# 2. Los 12 roles están
Select-String -Path .dsh\se.patch.yml -Pattern "id: preset-" | Measure-Object

# 3. Las skills están
Get-ChildItem .dsh\skills -Directory | Measure-Object
```

Esperado: `YAML OK`, **12** presets, **7** skills.

---

## 7. Problemas típicos

| Síntoma | Causa | Solución |
|---|---|---|
| `dsh` rechaza el patch | YAML inválido | Actualiza SE: el bug de indentación se corrigió; regenera con `adapter deepseek` |
| No aparece el coordinador | Patch no aplicado | Revisa `--patch` o el `cordis.patch.yml` del perfil |
| Faltan tools en un rol | Un preset reemplaza la lista completa de plugins | Añade las filas de tools que tu despliegue conceda |
| Los MCP no responden | No están montados en `mcp-manager` | Añádelos a `config.servers` |
| Todos los roles caen en un modelo raro | `agent-default-model` global | Usa modelos distintos por rol vía `agent-loop`/`tool-subagent` |

---

## 8. Regenerar y deshacer

Regenerar (siempre que cambie un contrato):

```powershell
python SCRIPTS\se.py adapter deepseek
```

Deshacer es borrar lo generado:

```powershell
Remove-Item .dsh -Recurse -Force
Remove-Item AGENTS.local.md -Force
```

No borres nada fuera de esas dos rutas: SE no escribe en tu `$DSH_HOME`.

---

## Checklist

- [ ] `se doctor` sin FAIL
- [ ] `se adapter deepseek` sin errores
- [ ] `dsh --patch .dsh/se.patch.yml` carga
- [ ] 12 presets y 7 skills presentes
- [ ] Preset `shema-ai-coordinador` seleccionable
- [ ] MCP montados en `mcp-manager`
- [ ] Modelo decidido (global o por sesión)

---

## Ver también

- `INTEGRATIONS/deepseek/README.md` — referencia técnica del adapter.
- `DOCS/reference/adapters.md` — los seis adapters y su mapeo.
- `DOCS/reference/roadmap-mejoras.es.md` — pendientes y seguimiento.
