"""Component definitions for all installable components."""

from __future__ import annotations

from .models import InstallableComponent, ComponentType, OSType, InstallStatus


def get_all_components() -> list:
    """Get all installable component definitions."""

    components = []

    # ============================================
    # SE CORE (required)
    # ============================================
    components.append(InstallableComponent(
        id="se_core",
        name="SE Core",
        description="System Engineering Master System - schemas, lifecycle, agents, commands",
        component_type=ComponentType.SE_CORE,
        long_description=(
            "El nucleo de SYSTEM-ENGINEERING. Incluye los esquemas JSON, modelos de ciclo de vida, "
            "gates, agentes, comandos y la CLI de referencia (se.py). Es la base de todo el sistema."
        ),
        requires=[],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="pip",
        verification_command="python -m se doctor --json",
        homepage="https://github.com/SHEMASOFT/SYSTEM-ENGINEERING",
        docs_url="https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/tree/main/DOCS/reference",
        recommended=True,
        category="Core",
    ))

    components.append(InstallableComponent(
        id="se_console",
        name="SE Console",
        description="Consola web local-first, read-only sobre SE",
        component_type=ComponentType.SE_CONSOLE,
        long_description=(
            "Una consola web local-first y read-only que se ejecuta sobre SYSTEM-ENGINEERING. "
            "Responde que es SE, en que estado esta, de que esta hecho, que proyectos tiene y "
            "que necesita atencion. Todo en una interfaz web local (http://localhost:8777). "
            "Cero dependencias externas, solo Python + jsonschema. Read-only by design (405 en writes)."
        ),
        requires=["se_core"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="vendored",
        verification_command="python -m console.server --version",
        homepage="https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/tree/main/SE-CONSOLE",
        docs_url="https://github.com/SHEMASOFT/SYSTEM-ENGINEERING/tree/main/SE-CONSOLE/docs",
        recommended=True,
        category="Core",
    ))

    # ============================================
    # MEMORY (required for full functionality)
    # ============================================
    components.append(InstallableComponent(
        id="engram",
        name="Engram",
        description="Memoria persistente cross-session para SE",
        component_type=ComponentType.MCP,
        long_description=(
            "Sistema de memoria persistente que sobrevive entre sesiones. Guarda decisiones, fixes, "
            "discoveries, patrones y contexto de sesion. El orchestrator lo usa obligatoriamente: "
            "mem_context al arrancar, mem_search para historial, mem_save para decisiones, "
            "mem_session_summary al cerrar. Sin Engram, SE arranca 'en blanco' cada vez."
        ),
        requires=["se_core"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="binary",
        verification_command="engram --version",
        homepage="https://github.com/Gentleman-Programming/engram",
        docs_url="https://github.com/Gentleman-Programming/engram#readme",
        license="MIT/Apache-2.0",
        recommended=True,
        category="Memory",
    ))

    # ============================================
    # MCPs - Node-based (require node/npx)
    # ============================================
    components.append(InstallableComponent(
        id="context7",
        name="Context7",
        description="Documentacion actualizada de librerias (Context7 API)",
        component_type=ComponentType.MCP,
        long_description=(
            "MCP que consulta Context7 API para obtener documentacion actualizada de cualquier "
            "libreria/framework. Util para: 'Como configurar auth en Express?', 'React useEffect "
            "cleanup examples', 'Prisma schema reference'. Evita alucinaciones con docs obsoletas."
        ),
        requires=["se_core", "node"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="npx",
        verification_command="npx -y @upstash/context7-mcp --help",
        homepage="https://context7.com",
        docs_url="https://context7.com/docs",
        recommended=True,
        category="Documentation",
    ))

    components.append(InstallableComponent(
        id="filesystem",
        name="Filesystem MCP",
        description="Read/write files bajo un root (MCP reference server)",
        component_type=ComponentType.MCP,
        long_description=(
            "Servidor MCP de referencia para operaciones de archivos. Permite a los agentes leer, "
            "escribir, listar, buscar y manipular archivos bajo un root configurado. Es el servidor "
            "MCP de referencia oficial (modelcontextprotocol/server-filesystem)."
        ),
        requires=["se_core", "node"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="npx",
        verification_command="npx -y @modelcontextprotocol/server-filesystem --help",
        homepage="https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        recommended=True,
        category="File Operations",
    ))

    components.append(InstallableComponent(
        id="playwright",
        name="Playwright MCP",
        description="Browser automation MCP (chromium/firefox/webkit)",
        component_type=ComponentType.MCP,
        long_description=(
            "MCP para automatizacion de navegadores reales. Permite a los agentes navegar, "
            "hacer click, rellenar formularios, hacer screenshots, extraer datos de paginas web, "
            "testear flujos E2E. Incluye instalacion de Chromium. Requiere Node.js."
        ),
        requires=["se_core", "node"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="npx",
        post_install_commands=["npx playwright install chromium"],
        verification_command="npx -y @playwright/mcp --help",
        homepage="https://playwright.dev",
        docs_url="https://github.com/microsoft/playwright-mcp",
        recommended=False,
        category="Browser Automation",
    ))

    components.append(InstallableComponent(
        id="firecrawl",
        name="Firecrawl",
        description="Web scraping y search MCP (requiere API key)",
        component_type=ComponentType.MCP,
        long_description=(
            "MCP para scraping web y busqueda. Extrae contenido limpio de cualquier URL, "
            "hace crawling, busqueda web, extraccion estructurada. Requiere FIRECRAWL_API_KEY "
            "gratuita en firecrawl.dev. Util para research, competitive analysis, monitoring."
        ),
        requires=["se_core", "node"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="npx",
        verification_command="npx -y firecrawl-mcp --help",
        homepage="https://firecrawl.dev",
        docs_url="https://docs.firecrawl.dev",
        recommended=False,
        category="Web Scraping",
    ))

    components.append(InstallableComponent(
        id="sequential-thinking",
        name="Sequential Thinking MCP",
        description="Deliberate, structured and revisable multi-step reasoning",
        component_type=ComponentType.MCP,
        long_description=(
            "Servidor MCP de referencia para razonamiento secuencial estructurado. "
            "Descompone problemas complejos en pasos revisables, encadena pensamientos "
            "y permite backtracking controlado. Util para depurar, disenar y analizar "
            "decisiones multi-etapa."
        ),
        requires=["se_core", "node"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="npx",
        verification_command="npx -y @modelcontextprotocol/server-sequential-thinking --help",
        homepage="https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
        docs_url="https://modelcontextprotocol.io",
        recommended=False,
        category="Reasoning",
    ))

    # ============================================
    # MCPs - Binary-based
    # ============================================
    components.append(InstallableComponent(
        id="codegraph",
        name="CodeGraph",
        description="Code intelligence / blast radius analysis (Rust)",
        component_type=ComponentType.MCP,
        long_description=(
            "Indexador semantico de codigo en Rust. Proporciona blast-radius analysis (que archivos "
            "afecta un cambio), go-to-definition cross-repo, analisis de impacto de cambios. "
            "Opcional: SE funciona sin el (degrada a analisis sintactico). Requiere Rust/Cargo."
        ),
        requires=["se_core", "rust"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="cargo",
        verification_command="codegraph --version",
        homepage="https://codegraph.dev",
        docs_url="https://codegraph.dev/docs",
        recommended=False,
        category="Code Intelligence",
    ))

    # ============================================
    # Runtime dependencies
    # ============================================
    components.append(InstallableComponent(
        id="node",
        name="Node.js / npx",
        description="Runtime JavaScript + npx (requerido para MCPs npm)",
        component_type=ComponentType.MCP,
        long_description=(
            "Node.js LTS + npx. Requerido para MCPs basados en npm: Context7, Filesystem, "
            "Playwright, Firecrawl. Se instala via fnm (recomendado), winget, brew, o installer oficial."
        ),
        requires=[],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="auto",
        verification_command="node --version && npx --version",
        homepage="https://nodejs.org",
        recommended=True,
        category="Runtime",
    ))

    components.append(InstallableComponent(
        id="rust",
        name="Rust / Cargo",
        description="Toolchain Rust (requerido para CodeGraph)",
        component_type=ComponentType.MCP,
        long_description=(
            "Toolchain Rust (rustc + cargo). Requerido solo si vas a instalar CodeGraph. "
            "Se instala via rustup (https://rustup.rs/)."
        ),
        requires=[],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="rustup",
        verification_command="cargo --version",
        homepage="https://rustup.rs",
        recommended=False,
        category="Runtime",
    ))

    # ============================================
    # Runtimes to adapt
    # ============================================
    components.append(InstallableComponent(
        id="opencode",
        name="OpenCode",
        description="Runtime principal de SE (TUI + MCP host)",
        component_type=ComponentType.RUNTIME,
        long_description=(
            "El runtime que carga y ejecuta los agentes, skills y MCPs de SE. Proporciona TUI, "
            "gestion de sesiones, MCP host (stdio), y ejecucion de agentes. Es el motor principal "
            "que hace correr SE. Instalado via winget/scoop/brew/script oficial."
        ),
        requires=["se_core"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="auto",
        verification_command="opencode --version",
        homepage="https://opencode.ai",
        docs_url="https://opencode.ai/docs",
        recommended=True,
        category="Runtime",
    ))

    components.append(InstallableComponent(
        id="codex",
        name="Codex CLI",
        description="OpenAI Codex CLI",
        component_type=ComponentType.RUNTIME,
        long_description=(
            "CLI oficial de OpenAI Codex. Permite ejecutar agentes Codex desde terminal. "
            "Se integra como runtime alternativo para SE. Requiere cuenta OpenAI con API key."
        ),
        requires=["se_core", "node"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="npm",
        verification_command="codex --version",
        homepage="https://github.com/openai/codex",
        recommended=False,
        category="Runtime",
    ))

    components.append(InstallableComponent(
        id="claude_code",
        name="Claude Code",
        description="Anthropic Claude Code CLI",
        component_type=ComponentType.RUNTIME,
        long_description=(
            "CLI oficial de Anthropic para Claude Code. Ejecuta agentes Claude desde terminal. "
            "Runtime alternativo para SE. Requiere cuenta Anthropic con API key."
        ),
        requires=["se_core", "node"],
        supported_os=[OSType.WINDOWS, OSType.MACOS, OSType.LINUX],
        install_method="npm",
        verification_command="claude --version",
        homepage="https://github.com/anthropics/claude-code",
        recommended=False,
        category="Runtime",
    ))

    return components


# Convenience: get components by category
def get_components_by_category() -> dict:
    """Group components by category for UI display."""
    from collections import defaultdict
    components = get_all_components()
    by_cat = defaultdict(list)
    for c in components:
        by_cat[c.category].append(c)
    return dict(by_cat)


def get_recommended_components() -> list:
    """Get only recommended components."""
    return [c for c in get_all_components() if c.recommended]