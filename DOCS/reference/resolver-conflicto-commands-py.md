# Resolver conflicto de merge en `SCRIPTS/se_core/commands.py`

Cuando abras el PR de `integrate-shema-ai` a `main` desde GitHub, puede haber conflicto en `SCRIPTS/se_core/commands.py`. Ambas ramas tocaron este archivo en áreas distintas, así que **Git suele hacer el merge automático**. Si no, resuélvelo así.

## Pasos (en tu computadora)

```powershell
cd <ruta>\SYSTEM-ENGINEERING
git fetch origin --tags --prune
git switch main
git pull --ff-only
git switch integrate-shema-ai
git merge main
```

Si Git detiene el merge con:

```
CONFLICT (content): Merge conflict in SCRIPTS/se_core/commands.py
```

abre el archivo y busca los marcadores `<<<<<<< HEAD`, `=======`, `>>>>>>> integrate-shema-ai`.

## Qué cambió en cada rama (para decidir qué queda)

### `p3-complete` (los 3 fixes del implementador)

| Zona | Cambio | Qué queda |
|---|---|---|
| `cmd_review` (~línea 2136) | `"unreadable ({message})"` → `"{message}"` | Quedarse con `"{message}"` |
| `cmd_validate` (~línea 3383) | idem | Quedarse con `"{message}"` |
| `cmd_status` (~línea 3905) | idem | Quedarse con `"{message}"` |
| `_resolve_memory_project()` (~línea 4197) | Nueva función helper | Quedarse (la usa `cmd_memory`) |
| `cmd_memory` (líneas 4222-4410) | Usa `_resolve_memory_project()` y pasa `project_dir` | Quedarse |

### `integrate-shema-ai` (tu trabajo, sobre p3-complete)

| Zona | Cambio | Qué queda |
|---|---|---|
| Imports (líneas 3-14) | Agrega `os`, `shlex`, `subprocess`, `sys`, `from . import authority` | Quedarse |
| `cmd_resume` (líneas 255-340) | Ahora ejecuta realmente el comando con `subprocess.run` | Quedarse |
| `cmd_transition` (líneas 2287-2410) | Verificación de autoridad con `SE_CONSOLE_TOKEN` (fail closed) | Quedarse |
| `cmd_subagent` (líneas 4828-4940) | Mensajes de `remedy` mencionan `SE_LLM_PROVIDER/SE_LLM_MODEL` | Quedarse |
| `cmd_shema_main` (línea 7530+) | Nueva función menú TUI SHEMA-AI | Quedarse |

## Regla práctica por zona

| Zona del conflicto | Qué elegir |
|---|---|
| `cmd_review` / `cmd_validate` / `cmd_status` | **Versión de p3-complete** (`"{message}"`) |
| `cmd_memory` + `_resolve_memory_project` | **Versión de p3-complete** |
| `cmd_resume` | **Versión de shema-ai** |
| `cmd_transition` | **Versión de shema-ai** |
| Imports | **Ambos** (todos los imports de ambas) |
| Cualquier otra zona | La que tenga más sentido; si duda, pregunta |

## Después de resolver

```powershell
git add SCRIPTS/se_core/commands.py
git commit -m "resolve merge conflict in commands.py"
git push origin integrate-shema-ai
```

Luego verifica que nada se rompió:

```powershell
python TESTS\run_tests.py          # 1469 OK
python SCRIPTS\se.py validate      # VALIDATE: PASS
python SCRIPTS\se.py doctor        # PASS=21 WARN=0 FAIL=0
```

Después el PR a `main` se puede mergear sin conflicto.

## Si no hay conflicto

Git hará el merge automático. Solo haz:

```powershell
git switch main
git pull --ff-only
git switch integrate-shema-ai
git merge main
git push origin integrate-shema-ai
```

Y abre el PR desde GitHub.
