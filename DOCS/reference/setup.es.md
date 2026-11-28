# `se setup`: de clon a consola en un comando

`se setup` encadena lo que ya existía; no inventa otro instalador. Sirve para
llegar a un proyecto usable sin memorizar cuatro comandos.

```bash
python SCRIPTS/se.py setup --project .
```

## ¿Qué hace?

| Paso | Comando que ejecuta | Qué toca |
|---|---|---|
| 1. Instalar | `se install --project . --bootstrap` | `~/.se-installer/`, runtimes y la config del harness |
| 2. Adaptar | `se adapter <harness>` | `.opencode/`, `.dsh/`, `.codex/`, `.claude/`, `.pi/` o `.hermes/` |
| 3. Registrar MCP | incluido en el paso 1 | servidores declarados en la config del runtime |
| 4. Verificar | `se doctor` | solo lectura |
| 5. Consola | muestra la URL | **no inicia ningún servidor** |

Si un paso falla, los siguientes se omiten: nunca se genera un adapter sobre
una instalación rota. Repetir el comando es seguro; los archivos que no cambian
se reportan como `unchanged`.

## Modos para mirar antes de tocar nada

| Modo | Efecto |
|---|---|
| `--dry-run` | Los pasos 1 y 2 solo planean; no se escribe nada ni se abre el navegador. |
| `--explain` | Imprime cada paso y qué superficie toca. **No ejecuta nada.** |
| `--check` | Ejecuta únicamente `se doctor` (diagnóstico de solo lectura). |

Los tres modos son mutuamente excluyentes. Ejemplos:

```bash
python SCRIPTS/se.py setup --explain        # qué haría, sin hacerlo
python SCRIPTS/se.py setup --dry-run        # plan real, sin escribir
python SCRIPTS/se.py setup --check          # solo health check
python SCRIPTS/se.py setup --harness deepseek   # forzar un harness
python SCRIPTS/se.py setup --open           # abrir la URL (si el servidor ya corre)
```

## Detección del harness

Con `--harness auto` (predeterminado) se elige el primer artefacto presente, en
este orden:

| Artefacto | Harness |
|---|---|
| `.opencode/` | `opencode` (predeterminado si no hay ninguno) |
| `.codex/` | `codex` |
| `.claude/` | `claude-code` |
| `.dsh/` | `deepseek` |
| `.pi/` | `pi` |
| `.hermes/` | `hermes` |

## La consola

`se setup` termina mostrando `http://127.0.0.1:8777` y cómo iniciarla:

```bash
cd SE-CONSOLE
python -m console.server --port 8777
```

El puerto canónico es **8777**. El comando **no** levanta la consola por su
cuenta: así se evita dejar dos instancias compitiendo por el puerto. `--open`
solo abre la URL en el navegador y asume que el servidor ya está corriendo.

Para las tres formas de llegar al instalador (scripts, `se install --bootstrap`
y la interfaz web), ver `installation.md`, § "Una sola ruta, tres entradas".
