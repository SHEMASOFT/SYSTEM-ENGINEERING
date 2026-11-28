# SE Installer Web — Documentación

Interfaz web interactiva para instalar, desinstalar y gestionar componentes del Sistema de Ingeniería (SE), incluida la selección de modelo para agentes.

---

## 1. Ejecución

### Arranque rápido (recomendado)

```powershell
# Windows (PowerShell): los parámetros son -Port, -NoBrowser, -Dev, -Help
.\SE-INSTALLER\install-web.ps1

# Linux / macOS
bash SE-INSTALLER/install-web.sh
```

El script detecta un puerto libre en 8765–8784, abre el navegador automáticamente
y el puerto queda libre cuando termina el proceso (Ctrl+C). No crea venv ni
registra MCPs: para eso usa `bootstrap.ps1`/`install.sh` o `se install --bootstrap`.

### Comando directo

```powershell
# Requiere pip install -e SCRIPTS/se_installer_web
se-installer-web --port 8765 --reload

# Directo con uvicorn (sin instalar paquete)
python -m uvicorn se_installer_web.main:app --host 127.0.0.1 --port 8765 --reload
```

Abre **http://127.0.0.1:8765** (o el puerto asignado) en el navegador.

---

## 2. Interfaz — Pestañas

| Pestaña | Icono | Funcionalidad |
|---------|-------|---------------|
| **📦 Instalar** | Instalar | Lista de componentes con checkboxes. Selección de runtimes (OpenCode, Codex, Claude Code). Opciones: Dry-run, Force reinstall, Skip verification, Crear acceso directo. Barra de progreso durante instalación. |
| **🗑️ Desinstalar** | Desinstalar | Limpieza de artefactos SE en OpenCode. Checkboxes: `--all`, `--include-untracked-se-mcps`, `--remove-opencode-dir`, `--purge-adapter`, `--keep-opencode-jsonc`, `--force`, `--apply`. Botones "Ver Plan (Dry-Run)" y "Aplicar Desinstalación". |
| **⚙️ Adaptador** | Adaptador | Generar/eliminar adaptador OpenCode (`.opencode/` con agentes, comandos, skills). |
| **🧠 Modelo** | Modelo | Selección de modelo para agentes: global (un mismo modelo para todos), per-agente (un modelo por subagente), o saltar. Catálogo de modelos con autocompletado. |
| **📋 Log** | Log | Streaming en tiempo real vía WebSocket. Muestra progreso, errores, completado. |

---

## 3. Pestaña "Modelo" (Selección de Modelo)

Permite configurar qué modelo usarán los agentes de SE. La selección se persiste en `opencode.jsonc` a través del mismo backend que usa `se shema-ai model`.

### Modos

| Modo | Descripción |
|------|-------------|
| **Un mismo modelo para todos** | Escribe un `global_model` que aplica a todos los agentes a menos que tengan override. |
| **Un modelo por subagente** | Escribe overrides individuales por nombre de agente. Los campos vacíos no se escriben. |
| **Saltar** | No escribe nada. La configuración queda exactamente como está. |

### Flujo

1. Abre la pestaña **🧠 Modelo** — se carga automáticamente el estado actual (`GET /api/models`).
2. Selecciona el modo deseado.
3. Escribe el modelo en formato `provider/model` (ej. `nvidia/nemotron-3-ultra-550b-a55b`). Hay un `<datalist>` con el catálogo disponible para autocompletado.
4. Clic **💾 Aplicar selección** — envía `POST /api/models`.
5. El panel derecho muestra la **Selección Efectiva** (lo que el runtime usará para cada agente).
6. Opcional: clic **🔄 Refrescar** para recargar el estado desde el servidor.

### Resolución de modelo

La resolución de prioridad es: **agent contract → harness config (opencode.jsonc) → repo-level JSON → dummy**. El instalador web escribe a nivel de harness (`opencode.jsonc`), no a `agent.json`.

---

## 4. API REST

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `GET /api/components` | GET | Lista componentes con estado |
| `GET /api/status` | GET | Resumen de instalación |
| `POST /api/install` | POST | Iniciar instalación (async + WebSocket progress) |
| `POST /api/uninstall` | POST | Desinstalar (stream output) |
| `POST /api/adapter/generate` | POST | Generar adaptador OpenCode |
| `POST /api/adapter/remove` | POST | Eliminar `.opencode/` |
| `GET /api/models` | GET | Estado actual de selección de modelo, roster de agentes y catálogo |
| `POST /api/models` | POST | Aplicar selección de modelo (global, per-agente, skip) |
| `WS /ws` | WebSocket | Logs en tiempo real |

### Ejemplo: `GET /api/models`

```json
{
  "selection": {
    "global_model": "nvidia/nemotron-3-ultra-550b-a55b",
    "agent_overrides": {},
    "apply_to_all": true,
    "roster": [],
    "prefill": null,
    "model_step_disabled": false,
    "runtimes": ["opencode"]
  },
  "roster": ["_contract", "_migration", "analyst", "architect", "devops", "documentation", "explorer", "implementer", "planner", "reviewer", "security", "shema-ai-coordinador", "tester", "visual"],
  "catalogue": {
    "free": [{"id": "deepseek-r1-free", "name": "DeepSeek R1 (Free)", ...}],
    "openai": [{"id": "gpt-4o", "name": "GPT-4o", ...}],
    "anthropic": [{"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", ...}],
    "local": [{"id": "llama-3.1-8b-local", "name": "Llama 3.1 8B (Local)", ...}]
  }
}
```

### Ejemplo: `POST /api/models`

```json
// Global
{ "global_model": "nvidia/nemotron-3-ultra-550b-a55b" }

// Per-agente
{ "agents": { "reviewer": "anthropic/claude-3.5-sonnet", "tester": "openai/gpt-4o-mini" } }

// Saltar
{ "skip": true }
```

---

## 5. Requisitos

- Python 3.10+
- `pip install -e SCRIPTS/se_installer_web` (instala el comando `se-installer-web`;
  `pip install -e SE-INSTALLER` instala el CLI `se-installer`, no el backend web)
- O directo: `python -m uvicorn se_installer_web.main:app --host 127.0.0.1 --port 8765 --reload`
- `se-installer-web` solo acepta `--host`, `--port` y `--reload`; `--dev`, `--all` y
  `--apply` se ignoran. El backend usa el repositorio desde el que se lanzó.

---

## 6. Desarrollo

El frontend está en `SCRIPTS/se_installer_web/static/index.html` (vanilla JS/HTML/CSS, sin build step, sin framework).

```bash
# Con auto-reload
se-installer-web --dev --reload
# O
python -m uvicorn se_installer_web.main:app --reload
```

---

## 7. Comparación con Branding SE-CONSOLE

El instalador web usa una paleta oscura tipo GitHub (`#0d1117` fondo, `#161b22` tarjetas, `#1f6feb` acento azul). A continuación se compara con el contrato de diseño de **SE-CONSOLE** (`SE-CONSOLE/docs/DESIGN.md`):

| Aspecto | Instalador Web actual | SE-CONSOLE Design (referencia) | Coincide |
|---------|----------------------|-------------------------------|----------|
| **Tema por defecto** | Ambos (light/dark con toggle) | Ambos (light por defecto, dark completo) | ✅ Sí |
| **Theme toggle** | Sí (localStorage + prefers-color-scheme) | Sí (localStorage + prefers-color-scheme) | ✅ Sí |
| **Colores de salud** | Tokens semánticos: HEALTHY, WARNING, BLOCKED, UNKNOWN | Tokens semánticos: HEALTHY, WARNING, BLOCKED, UNKNOWN | ✅ Sí |
| **Tipografía** | Dual: Mono (IDs/códigos) + Sans (prosa) | Dual: Mono (IDs/códigos) + Sans (prosa) | ✅ Sí |
| **Espaciado** | Escala `4/8/12/16/24/32` | Escala `4/8/12/16/24/32` | ✅ Sí |
| **Radius** | `6px` controles, `10px` paneles | `6px` controles, `10px` paneles | ✅ Sí |
| **Elevación** | `0 1px 2px` + hairline border | `0 1px 2px` + hairline border | ✅ Sí |
| **Health chip global** | Badge de conexión WebSocket | Hero status con `se doctor` summary | ⚠️ Parcial |
| **Provenance strip** | No | Persistente `OBSERVED`/`DERIVED`/`UNKNOWN` | ❌ No |
| **Responsive** | Grid 1fr 400px → 1fr en móvil | Multi-column desktop, single column mobile | ✅ Sí |

**Conclusión:** El instalador web ahora sigue el contrato de diseño de SE-CONSOLE en la mayoría de aspectos: tema claro/oscuro con persistencia, tokens semánticos de salud, tipografía dual mono/sans, escala de espaciado, radius y elevación consistentes. Quedan dos diferencias menores: no tiene un "hero status" con `se doctor` en el header (solo estado de conexión WebSocket) y no incluye el strip de procedencia epistémica (`OBSERVED`/`DERIVED`/`UNKNOWN`), que es más propio del console de solo lectura que de un instalador transaccional.

---

## 8. Comandos CLI equivalentes

```bash
# Instalar componentes seleccionados (vía UI)
se-installer-web --port 8765
# → Pestaña "Instalar" → seleccionar componentes → "Instalar Seleccionados"

# Desinstalar todo (dry-run)
python SCRIPTS/se.py uninstall --all --dry-run

# Desinstalar todo (aplicar)
python SCRIPTS/se.py uninstall --all --apply

# Generar adaptador OpenCode (vía UI)
se-installer-web --port 8765
# → Pestaña "Adaptador" → "Generar Adaptador"

# Seleccionar modelo (vía UI)
se-installer-web --port 8765
# → Pestaña "Modelo" → elegir modelo → "Aplicar selección"

# Seleccionar modelo (vía CLI)
se shema-ai model --global nvidia/nemotron-3-ultra-550b-a55b
```
