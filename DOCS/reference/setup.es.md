# `se setup`: de clon a consola en un comando

`se setup` encadena lo que ya existía; no inventa otro instalador. Sirve para
llegar a un proyecto usable sin memorizar cuatro comandos.

```bash
python SCRIPTS/se.py setup --project .
```

## Antes de empezar en un equipo nuevo

`se setup` **no aprovisiona el sistema**. Necesitas, en el intérprete que ejecuta
`se.py`:

- Python 3.10+ con `jsonschema` (`pip install jsonschema`).
- `se-installer` importable (`pip install -e SE-INSTALLER`).

En una máquina limpia usa primero los wrappers:
`SE-INSTALLER/bootstrap.ps1 install --recommended` (Windows, puede instalar Python
y Node) o `SE-INSTALLER/install.sh install --recommended` (Linux/macOS). Crean
`SE-INSTALLER/.venv` e instalan el paquete; en Linux/macOS **no** instalan
Python, así que instala `python3`, `venv` y `pip` con el gestor del sistema.
`se setup` es el atajo cuando esos prerrequisitos ya están resueltos.

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
| `--dry-run` | Los pasos 1 y 2 solo planean y no se abre el navegador; `doctor` corre igual y el orquestador puede crear `~/.se-installer/state/`. |
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

`--project <dir>` se aplica a la instalación y al `doctor`, pero **no** se propaga
al generador de adapters: esos archivos se escriben en la raíz del repositorio SE.

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

Para las tres entradas de bootstrap (scripts y `se install --bootstrap`) y la
interfaz web como UI alternativa, ver `installation.md`, § "Una sola ruta, tres entradas".
