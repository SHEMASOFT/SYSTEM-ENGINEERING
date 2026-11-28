# Instalar SE en un equipo nuevo

Guía práctica para llegar desde un clon limpio a un SE verificable. Las cuatro
entradas comparten `se_installer.orchestrator`: no son instaladores distintos.

## 1. Elige la entrada

| Situación | Entrada | ¿Instala prerrequisitos? | ¿Registra MCP? |
|---|---|---|---|
| Windows sin Python ni Node | `SE-INSTALLER\bootstrap.ps1 install --recommended` | Sí: Python 3.12 y Node/OpenCode | Sí, tras el `install` |
| Linux/macOS con Python 3.10+ | `SE-INSTALLER/install.sh install --recommended` | No; crea `SE-INSTALLER/.venv` | Sí, tras el `install` |
| Ya tienes Python y `se-installer` | `python SCRIPTS/se.py setup --project .` | No | Sí (paso 1 de `setup`) |
| Prefieres una interfaz visual | `install-web.ps1` / `install-web.sh` | No | No |

La interfaz web solo cambia cómo se eligen los componentes: no aprovisiona
Python, no crea venv y no registra MCPs.

## 2. Windows: clon limpio

```powershell
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
cd SYSTEM-ENGINEERING
powershell -ExecutionPolicy Bypass -File SE-INSTALLER\bootstrap.ps1 install --recommended
```

Si winget, Chocolatey y Scoop no están disponibles, el bootstrap usa el
instalador oficial firmado de python.org para el usuario actual y el ZIP LTS de
nodejs.org verificado por SHA256. Después de instalar herramientas, **abre una
terminal nueva** para cargar el `PATH`.

## 3. Linux / macOS

Requisitos previos: `python3` 3.10+, `venv`, `pip`, `git` y red. El script solo
los comprueba; en Debian/Ubuntu instala antes `python3 python3-venv python3-pip
git` con el gestor del sistema.

```bash
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
cd SYSTEM-ENGINEERING
bash SE-INSTALLER/install.sh install --recommended
```

## 4. Ya con Python: `se setup`

Necesitas `jsonschema` y `se-installer` importables **en el mismo intérprete**
que ejecuta `se.py`:

```bash
pip install jsonschema
pip install -e SE-INSTALLER
python SCRIPTS/se.py setup --explain       # qué haría
python SCRIPTS/se.py setup --dry-run       # plan; doctor corre igual
python SCRIPTS/se.py setup --project .     # ejecuta
```

`--project <dir>` no se propaga al generador de adapters: esos archivos se
escriben en la raíz del repositorio SE. `setup` termina mostrando la URL de la
consola (`:8777`), pero **no inicia ningún servidor**.

## 5. Verificación

```bash
python SCRIPTS/se.py doctor
python SCRIPTS/se.py validate
cd SE-CONSOLE
python -m console.server                  # http://127.0.0.1:8777
```

El segundo intento de consola en el mismo puerto se rechaza con un mensaje
accionable y `exit 2`; para abrir otra, usa `--port 8778` o `SE_CONSOLE_PORT`.
Si el proveedor del modelo no está autenticado, ejecuta `opencode auth login`.

## 6. Trampas frecuentes

| Síntoma | Causa | Salida |
|---|---|---|
| `No module named se_installer` | `se setup`/`--bootstrap` corre en el intérprete de `se.py` | Usa los wrappers o `pip install -e SE-INSTALLER` |
| `pip` rechaza instalar en el sistema | PEP 668 en Debian/Ubuntu | Instala en un venv |
| `node`/`opencode` no aparecen | El bootstrap actualizó `PATH` solo en su hijo | Terminal nueva |
| `--all` no instala todo | Excluye componentes con cuenta o toolchain | Añade `--include-gated` |
| `se install --bootstrap --json` no registra MCP | El sobre JSON omite el registro | Repite sin `--json` |
| Web con `--port` en PowerShell | Los parámetros son de PowerShell | Usa `-Port`, `-NoBrowser`, `-Dev`, `-Help` |
| Consola «GET only» pero hay un POST | Es `/api/action`, autenticado por token | No es una escritura de datos del sistema |

Fuentes: [`installation.md`](installation.md), [`setup.es.md`](setup.es.md),
[`installer-web.md`](installer-web.md) y
[`clean-machine-smoke.md`](clean-machine-smoke.md).
