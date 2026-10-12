# SE Installer

Instalador unificado para **System Engineering Master System (SE)**.

## Características

- **Instalación unificada**: SE Core + SE Console + MCPs + Runtimes en un solo comando
- **Selección interactiva**: TUI (Textual) con checkboxes, descripciones y dependencias
- **CLI completo**: `se-installer install`, `list`, `status`, `doctor`, `tui`
- **Dependencias inteligentes**: Solo instala `node/npx` si se seleccionan MCPs que lo requieren
- **Multi-plataforma**: Windows (winget/scoop/choco), macOS (brew), Linux (apt/dnf/pacman)
- **Dry-run**: Valida y planifica sin instalar
- **Estado persistente**: Guarda progreso y permite reanudar
- **Paridad con el registro**: el catálogo de componentes se verifica contra `CORE/capabilities/capabilities.json` (fuente de verdad única)

## Componentes incluidos

### Core (requeridos)
- **SE Core** — Esquemas, lifecycle, agents, commands, CLI
- **SE Console** — Consola web local-first read-only (puerto 8777)
- **Engram** — Memoria persistente cross-session

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
bash SYSTEM-ENGINEERING/SE-INSTALLER/install.sh install --recommended --dry-run
```

El script crea un virtualenv aislado (`.venv`), instala el paquete `se-installer`
dentro y reenvía los argumentos restantes a la CLI (`se-installer`). Sin argumentos,
ejecuta la ayuda del CLI.

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
se-installer install -c context7 engram # Selección específica
se-installer install --dry-run         # Solo planificar

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
se-installer install -c se_core se_console engram context7 filesystem opencode

# Solo verificar qué hay instalado
se-installer status

# Health check completo
se-installer doctor

# Dry-run para ver plan sin instalar
se-installer install --dry-run --all
```

## Licencia

MIT — misma licencia que el repositorio SYSTEM-ENGINEERING (ver [`LICENSE`](../LICENSE)).