# SE Installer

Instalador unificado para **System Engineering Master System (SE)**.

## Características

- **Instalación unificada**: SE Core + SE Console + MCPs + Runtimes en un solo comando
- **Selección interactiva**: TUI (Textual) con checkboxes, descripciones y dependencias
- **CLI completo**: `se-installer install`, `list`, `status`, `doctor`, `tui`
- **Dependencias inteligentes**: Solo instala `node/npx` si se seleccionan MCPs que lo requieren
- **Multi-plataforma**: Windows (winget/scoop/choco), macOS (brew), Linux (apt/dnf/pacman)
- **Dry-run**: Valida y planifica sin instalar
- **Atajo de escritorio opcional**: `--shortcuts` (o el checkbox de la TUI) crea un único acceso directo que arranca SE Console; sin esa opción no se toca el Escritorio
- **Estado persistente**: Guarda progreso y permite reanudar
- **Paridad con el registro**: el catálogo de componentes se verifica contra `CORE/capabilities/capabilities.json` (fuente de verdad única)

## Componentes incluidos

### Core (requeridos)
- **SE Core** — Esquemas, lifecycle, agents, commands, CLI
- **SE Console** — Consola web local-first read-only (puerto 8777)

### MCPs (seleccionables)
| MCP | Descripción | Requiere |
|-----|-------------|----------|
| **Context7** | Docs actualizadas librerías | node |
| **Filesystem** | Read/write files MCP | node |
| **Playwright** | Browser automation | node + browsers |
| **Firecrawl** | Web scraping/search | node + API key |
| **Sequential Thinking** | Razonamiento estructurado multi-paso | node |
| **CodeGraph** | Code intelligence (Rust) | cargo |

### Runtimes (para adaptar SE)
| Runtime | Descripción |
|---------|-------------|
| **OpenCode** | Runtime principal SE (TUI + MCP host) |
| **Codex** | OpenAI Codex CLI |
| **Claude Code** | Anthropic Claude Code CLI |

## Instalación rápida — un solo comando

```bash
# Windows (PowerShell)
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
powershell -ExecutionPolicy Bypass -File SYSTEM-ENGINEERING/SE-INSTALLER/bootstrap.ps1 tui

# Linux / macOS
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
bash SYSTEM-ENGINEERING/SE-INSTALLER/install.sh install --recommended
```

El script crea un virtualenv aislado (`.venv`), instala el paquete `se-installer`
dentro y reenvía los argumentos restantes a la CLI (`se-installer`). Sin argumentos,
ejecuta la ayuda del CLI.

Tras un `install` correcto (y salvo que se use `--dry-run`), el bootstrap también
ejecuta `se install` sobre el repositorio para registrar los MCP de SE en OpenCode.
Usa `--skip-mcp-registration` para omitir ese paso, por ejemplo si solo vas a
configurar otro runtime. El modo `tui` y la instalación manual con `se-installer`
no hacen ese registro automático: ejecuta `se install` después.

### Instalación manual

```bash
# Clonar
git clone https://github.com/SHEMASOFT/SYSTEM-ENGINEERING.git
cd SYSTEM-ENGINEERING/SE-INSTALLER

# Instalar dependencias
pip install -e .

# Modo interactivo (TUI)
se-installer tui

# O CLI directo
se-installer install --recommended     # Solo recomendados
se-installer install --all             # Todo
se-installer install -c context7 filesystem # Selección específica
se-installer install --dry-run         # Solo planificar
se-installer install --shortcuts       # Además, atajo en el Escritorio

# Otros comandos
se-installer list                      # Listar componentes
se-installer status                    # Ver qué está instalado
se-installer doctor                    # Health checks
```

## Uso en Windows

```powershell
# Instalador interactivo
.\bootstrap.ps1

# O usando el CLI
python -m se_installer.cli tui
```

## Atajo de escritorio para SE Console (opcional)

El instalador puede crear **un** acceso directo que arranca la consola. Es opt-in:
por defecto no se crea nada, porque un instalador no debe escribir en el Escritorio
de nadie sin que se lo pidan.

```bash
se-installer install --recommended --shortcuts      # crear el atajo
se-installer install --recommended --no-shortcuts   # no crearlo (por defecto)
```

En la TUI el mismo efecto tiene el checkbox *"Crear acceso directo en el
Escritorio (SE Console)"*. Reglas:

- **Uno solo, y solo de arranque** (decisión D3 de `DESIGN-5C`): la consola se
  apaga sola cuando dejas de usarla, así que un atajo de parada no tendría nada
  que hacer.
- Se crea **solo si SE Console forma parte de la instalación** y **solo si esa
  instalación termina bien**. Un atajo hacia una consola que no se instaló, o
  hacia una instalación que falló, sería un enlace que se rompe en silencio
  semanas después.
- Con `--dry-run` se informa del atajo que se crearía y no se crea ninguno.

Por plataforma apunta al punto de entrada que la consola ya trae:

| Plataforma | Archivo creado | Apunta a |
|---|---|---|
| Windows | `SE Console.lnk` | `SE-CONSOLE/scripts/Start SE Console.cmd` |
| macOS | `SE Console.command` | `SE-CONSOLE/scripts/Start SE Console.command` |
| Linux | `SE Console.desktop` | `SE-CONSOLE/scripts/dev_console.py start` |

En Windows el Escritorio se pregunta al sistema
(`[Environment]::GetFolderPath('Desktop')`) en vez de asumir
`%USERPROFILE%\Desktop`, porque OneDrive lo reubica. En Linux el archivo se marca
como confiable con `gio` cuando está disponible. En macOS es un envoltorio
`.command` y no un enlace simbólico: el launcher de la consola empieza con
`cd "$(dirname "$0")"`, que a través de un enlace en el Escritorio resolvería al
propio Escritorio y no encontraría la consola.

## Requisitos

- Python 3.10+
- Windows 10/11, macOS 12+, o Linux moderno
- Para MCPs node: Node.js LTS (se instala automáticamente si se selecciona)
- Para CodeGraph: Rust (rustup.rs)

## Arquitectura

```
se_installer/
├── models.py                     # Modelos de datos (Plan, Component, Status, OS)
├── components.py                 # Definiciones de todos los componentes
├── orchestrator.py               # Orquestador de instalación (topological sort)
├── cli.py                        # CLI: install, list, status, doctor, tui
├── tui.py                        # TUI interactivo (Textual)
├── shortcuts.py                  # Atajo de escritorio (opt-in, DESIGN-5C fase 4)
├── state/                        # Persistencia de estado (JSON)
├── model_registry.py             # Modelos seleccionables por agente
├── mcp_registry.py               # Registro de MCPs con schemas de funciones
├── agent_mcp_binding.py          # Bindings agente → MCP + modelo
├── skill_mcp_bridge.py           # Skills declaran capacidades MCP
├── runtime_config_generator.py   # Generación de configs de runtime
└── installers/
    ├── base.py                   # BaseInstaller + mixins OS
    ├── mcp/                      # Instaladores MCP (npx/binary/cargo)
    └── runtime/                  # Instaladores de runtimes
```

## Ejemplos

```bash
# Solo lo esencial (recomendado)
se-installer install --recommended

# Todo menos CodeGraph
se-installer install -c se_core se_console context7 filesystem opencode

# Solo verificar qué hay instalado
se-installer status

# Health check completo
se-installer doctor

# Dry-run para ver plan sin instalar
se-installer install --dry-run --all
```

## Licencia

MIT — misma licencia que el repositorio SYSTEM-ENGINEERING (ver [`LICENSE`](../LICENSE)).