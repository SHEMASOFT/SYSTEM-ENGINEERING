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
| **CodeGraph** | Code intelligence (Rust) | cargo |

### Runtimes (para adaptar SE)
| Runtime | Descripción |
|---------|-------------|
| **OpenCode** | Runtime principal SE (TUI + MCP host) |
| **Codex** | OpenAI Codex CLI |
| **Claude Code** | Anthropic Claude Code CLI |

## Instalación rápida

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
se-installer/
├── components.py      # Definiciones de todos los componentes
├── models.py          # Modelos de datos (Plan, Component, Status, OS)
├── orchestrator.py    # Orquestador de instalación (topological sort)
├── state.py           # Persistencia de estado (JSON + history)
├── tui.py             # TUI interactivo (Textual)
├── cli.py             # CLI entry point (Typer-like)
├── components.py      # Definiciones de componentes
├── installers/
│   ├── base.py        # BaseInstaller + mixins OS
│   ├── mcp/           # MCP installers (6 MCPs)
│   └── runtime/       # Runtime installers (3 runtimes)
└── state/             # Persistencia JSON
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

UNKNOWN — no license declared. REQUIRES_VERIFICATION before public distribution.