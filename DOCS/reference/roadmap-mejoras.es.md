# Roadmap de mejoras — seguimiento

Documento vivo. Cada tarea tiene un ID, prioridad y estado. Se actualiza en el
mismo PR que resuelve la tarea.

**Última actualización:** 2026-11-28

## Leyenda

| Símbolo | Estado |
|---|---|
| ✅ | Hecho y verificado |
| 🔄 | En curso |
| ⬜ | Pendiente |
| ⛔ | Bloqueado |
| 🗑️ | Descartado (con motivo) |

---

## 1. Punto de partida (evidencia)

Instalación completa probada en un clon limpio de `main` (v0.12.0) en Windows:

| Verificación | Resultado |
|---|---|
| Instalador (`bootstrap.ps1 install`) | 8/8 componentes, 0 fallos |
| `se doctor` | PASS 21 · WARN 0 · FAIL 0 |
| SE-CONSOLE | HEALTHY, 21 PASS, `:8777` |
| MCP registrados | 2 de 4 (`se-memory-server`, `se-skill-server`) |
| Config global de OpenCode | intacta |

Ese estado es la línea base: cualquier regresión se compara contra esto.

---

## 2. Hallazgos

| ID | Hallazgo | Evidencia | Prioridad |
|---|---|---|---|
| F1 | El adapter `deepseek` generaba **YAML inválido** | `yaml.safe_load` fallaba en `.dsh/se.patch.yml` línea 25: `name: analyst` a 6 espacios con hijos a 8 | **P0** |
| F2 | DeepSeek Harness sin documentación | Cero menciones en `DOCS/`; sin `INTEGRATIONS/deepseek/` | **P0** |
| F3 | `--runtimes` es un no-op | `plan.target_runtimes` solo se persiste; `runtime_config_generator.py` no se importa en ningún flujo | **P0** |
| F4 | El probe MCP descarta servidores por timeout de `npx` en frío | `context7` y `filesystem` → `skipped` | P1 |
| F5 | `--all` falla en componentes que piden cuenta o toolchain | `firecrawl`, `codex`, `claude_code`, `codegraph`, `rust` | P1 |
| F6 | La TUI no tiene pasos de modelo, runtime ni adaptador | `model_step.py` solo lo usa el installer-web | P1 |
| F7 | La consola solo expone 3 acciones | `actions.py`: `run.checkpoint`, `run.close`, `transition.attest` | P2 |
| F8 | Pi y Hermes implementados y sin documentar | `se adapter pi` / `se adapter hermes` existen; no están en la tabla | P2 |
| F9 | `se adapter all` omite Hermes | `generate_all()` incluye claude-code, codex, deepseek y pi | P2 |
| F10 | `_pi_patch()` es código muerto | Definido, nunca llamado | P2 |
| F11 | `runtime_config_generator.py` es código muerto | 12 KB sin consumidores | P2 |
| F12 | ~~El dry-run del adapter cuenta un archivo menos~~ | **No era un bug**: `AGENTS.local.md` ya existía y se cuenta como `unchanged`; el dry-run y la escritura coinciden para el mismo destino | 🗑️ Descartado |
| F13 | Dos consolas pueden quedar corriendo | `:8631` de prueba y `:8777` del clon | P3 |
| F14 | Sin `gh` CLI en el entorno | PRs creados por REST | P3 |

Todos los hallazgos están cerrados: P0 F1-F3, P1 F4-F6, P2 F7-F11 (F12 descartado) y P3 F13-F14. El detalle está en la sección 8.

---

## 3. Plan por fases

### Fase 1 — DeepSeek Harness de primera clase (P0)

- [x] **T1** Corregir la indentación del preset en `_deepseek_patch`
      (`SCRIPTS/se_core/runtimes.py`).
- [x] **T2** Añadir test que **parsee** el YAML generado
      (`TESTS/test_adapter_deepseek.py::test_patch_parses_as_yaml`).
- [x] **T3** Crear `INTEGRATIONS/deepseek/README.md`.
- [x] **T4** Crear `DOCS/reference/deepseek-harness-install.es.md` (guía en español).
- [x] **T5** Actualizar `DOCS/reference/adapters.md` con los 6 adapters y el mapeo DSH.
- [x] **T6** Actualizar `README.md` (comandos de adapter y tabla de artefactos).
- [x] **T7** Verificar: 16 tests del adapter en verde.

**Criterio de cierre:** `se adapter deepseek` produce un patch que
`yaml.safe_load` acepta, con 12 presets y 7 skills, y la guía en español cubre
instalación, coordinador, MCP, modelo y troubleshooting.

### Fase 2 — Instalador honesto (P0/P1)

- [x] **T8** Conectar `--runtimes` a los generadores de adapters. Decisión:
      **conectarlo** en el CLI (el flag dice "runtimes a configurar", no
      "runtimes a recordar"). Implementado en
      `SE-INSTALLER/se_installer/runtime_adapters.py` y `cli.py`. La TUI y el
      instalador web se dejaron intactos a propósito.
      Evidencia: `pytest SE-INSTALLER/tests -q` → 167 passed, 3 skipped;
      `install --runtimes deepseek --json` → `adapters: [{deepseek, PASS, 9}]`.
- [x] **T9** Reintentos con backoff en el probe MCP antes de marcar `skipped`.
      Decisión: reintentar dentro de `probe_mcp_server`
      (`SCRIPTS/se_core/install.py`), no en `verify_mcp_servers`, para no tocar
      los `probe=` inyectados por los tests. Solo se reintentan timeouts y
      fallos de transporte; comandos inexistentes o errores JSON-RPC fallan a
      la primera. Backoff 0.25 s → 0.5 s, 3 intentos.
      Evidencia: `pytest TESTS/test_install.py -q` → 103 passed (3 tests nuevos:
      flaky que responde al 2.º intento, fallo determinista sin reintento y
      agotamiento con `tras 2 intentos`).
- [x] **T10** Marcar componentes con `requires_account` / `requires_toolchain`
      y excluirlos de `--all`, con `--include-gated` como opt-in explícito.
      Los omitidos se reportan en `gated_excluded` (JSON) y en stderr (texto);
      `-c <id>` sigue instalando cualquiera directamente.
      Evidencia: 170 tests del instalador OK; `install --all --dry-run --json`
      → `gated_excluded: [firecrawl, codegraph, rust, codex, claude_code]`.
- [x] **T11** Unificar `bootstrap.ps1` + `se install --bootstrap` +
      `install-web.ps1` en una sola ruta documentada. No se refactoriza código:
      las tres son entradas al mismo `se_installer.orchestrator`. Tabla en
      `installation.md` (§ "Una sola ruta, tres entradas") y puntero desde
      `se-installer.md`. El instalador web no se tocó.
      Evidencia: `se validate` PASS tras rebase; mismos scripts y flags que antes.

**Criterio de cierre:** una instalación limpia con `--runtimes codex,deepseek`
deja ambos adapters generados y 4/4 MCP registrados.

### Fase 3 — Comando único para principiantes (P1)

- [x] **T12** `se setup`: install + adapter (autodetectado) + MCP + doctor +
      URL de la consola, idempotente y con `--dry-run`. Implementado en
      `SCRIPTS/se_core/setup.py`; la consola **no** se inicia sola (evita T28).
- [x] **T13** Detección automática del harness por artefactos presentes
      (`.opencode/`, `.claude/`, `.codex/`, `.dsh/`, `.pi/`, `.hermes/`),
      con `opencode` como predeterminado.
- [x] **T14** Modo `--explain`: cada paso dice qué hace y qué superficie toca.
- [x] **T15** `se setup --check` que solo ejecuta `se doctor`.
      Evidencia: 16 tests de `test_setup.py` + 6 subtests; contract de CLI OK;
      `se setup --dry-run` real → install PASS, adapter PASS, doctor 21 PASS /
      0 FAIL, sin archivos nuevos. Guía: `DOCS/reference/setup.es.md`.

**Criterio de cierre:** un usuario nuevo ejecuta `se setup`, ve la URL de la
consola y puede verificar todo con `--explain` / `--check` antes de escribir.

### Fase 4 — Interfaz (P2)

- [x] **T16** TUI: pestaña **Configurar** con los tres pasos, en orden: modelo
      (`provider/model`), runtimes (opencode, claude-code, codex, deepseek, pi)
      y generación de adaptadores después de instalar. Hermes queda fuera del
      lote (T24). La selección se lee al pulsar Instalar y alimenta
      `prepare_plan(target_runtimes=...)`; en dry-run no se escribe nada.
      Evidencia: `SE-INSTALLER/tests/test_tui_config.py` (7 tests, incluye
      montaje real de la pestaña con Textual).
- [x] **T17** Catálogo de informes de consola: `GET /api/report` con lista
      cerrada (`health`, `verify`, `gate`, `plan`) y argv reconstruido por
      `console/reports.py`; `se_cli.run_se` vuelve a validar el argv antes de
      ejecutarlo. `explore` **no entra**: escribe `discovery.json` y puede
      avanzar el lifecycle (`mutates=true`). `plan` solo entra en su forma
      derivación (`--json`), nunca con `--create-tasks` ni `--intent`.
      Evidencia: `SE-CONSOLE/tests/test_report_catalog.py` (61 tests del
      conjunto enfocado, 21 subtests).
- [x] **T18** Botón **Arreglar** en cada check WARN/FAIL de `se doctor`: abre un
      drawer con los comandos exactos (`se doctor`, `se validate` y, según el
      check, `se adapter all --dry-run`, `se coverage rebase ...` o
      `se setup --dry-run`) y botón de copiar. La consola **no ejecuta** nada:
      el botón solo entrega comandos para la terminal del operador.
- [x] **T19** Atención agrupable por **proyecto** (default) o **causa raíz**.
      `/api/attention` añade `_cause` y un resumen `causes` ordenado por
      BLOCKED/WARNING; el agrupamiento es una pista de UI, no un veredicto.
      Silenciar causas guarda la preferencia en `localStorage` del navegador,
      sin escribir estado SE ni ampliar la superficie autenticada.
- [x] **T20** Búsqueda global `GET /api/search?q=...`: coincidencias léxicas
      sobre nombres de proyecto, memoria de la consola y records canónicos,
      con límite de 40 resultados y aviso de truncamiento. Vista **Buscar** en
      la consola. No es un veredicto de governance. De paso se corrigió
      `_SE_ROOT` (nombre no definido) en cuatro endpoints de memoria.
      Evidencia: `SE-CONSOLE/tests/test_search.py` (4 tests).
- [🗑️] **T21** SSE/WebSocket en vez de polling → descartado: no hay polling de
      datos que sustituir. `DESIGN-5C` §3 lo verificó (`console.js`: 0
      `setInterval` para lecturas; el único intervalo es el *heartbeat* de
      keepalive del timeout de inactividad). Añadir SSE crearía una conexión
      permanente y contradeciría el diseño sin resolver ningún problema real.
- [x] **T22** Token autogenerado en el primer arranque: ya existía en
      `SE-CONSOLE/console/auth.py` (`secrets.token_urlsafe(32)` en
      `~/.config/se-console/token`, modo 0600, valor nunca registrado).
      Evidencia: `SE-CONSOLE/tests/test_actions.py` cubre creación, ruta
      externa al repo, cabecera obligatoria y comparación `compare_digest`.

### Fase 5 — Limpieza y coherencia (P2/P3)

- [x] **T23** Documentar Pi y Hermes: `INTEGRATIONS/pi/README.md` y
      `INTEGRATIONS/hermes/README.md`; tabla de adapters y `INTEGRATIONS/` ya
      los incluían.
- [x] **T24** Decisión: **no incluir Hermes en `se adapter all`**. Escribe
      `AGENTS.md` y `settings.json`, los mismos archivos compartidos que otros
      adapters; meterlo en el lote los sobrescribiría en silencio. El help del
      comando y los READMEs lo dicen, y un test fija la exclusión. Hermes se
      genera con `se adapter hermes` o `se setup --harness hermes`.
- [x] **T25** Eliminar `_pi_patch()`: estaba definido pero nunca se llamaba.
      El fix de YAML de Fase 1 se fue con la función al confirmar que era
      inalcanzable; `_deepseek_patch` (sí usado) conserva el arreglo.
- [x] **T26** Decisión: **conservar `runtime_config_generator.py`**. Es API
      pública exportada en `se_installer/__init__.py` y cubierta por
      `test_registries.py`. T8 usa los generadores canónicos de `se_core`, así
      que conectarlo duplicaría la generación; borrarlo rompería consumidores.
      Queda documentado como biblioteca opcional, no como código muerto.
- [🗑️] **T27** Corregir el conteo del dry-run del adapter → descartado: F12 no
      era un bug (`AGENTS.local.md` ya existía y se cuenta como `unchanged`).
- [x] **T28** Evitar dos consolas simultáneas: `bind_console()` hace el bind
      real antes de calentar auditoría/attention y devuelve un error claro con
      `--port` / `SE_CONSOLE_PORT` como siguiente acción (exit 2). Chequear el
      puerto antes de bind introduzca una carrera TOCTOU. Flag `--port` nuevo.
      Evidencia: `SE-CONSOLE/tests/test_port_guard.py` (3 tests) y
      `test_idle_timeout.py`, 10 tests en verde.

---

## 4. Decisiones

| Fecha | Decisión | Motivo |
|---|---|---|
| 2026-11-27 | El puerto canónico de la consola es **8777** | `dev_console.py` y `server.py`; 8631 era solo prueba |
| 2026-11-27 | El adapter DSH emite un **overlay**, no archivos por rol | DSH solo lee presets desde patch lists de Cordis |
| 2026-11-27 | `AGENTS.local.md` en vez de `AGENTS.md` | Evitar colisión con el adapter de Codex |
| 2026-11-27 | El modelo por rol se anota; el default solo si es uniforme | Un default process-wide misroutea un roster mixto |
| 2026-11-28 | Hermes queda fuera de `se adapter all` | Escribe `AGENTS.md` y `settings.json`; en un lote sobrescribiría a otros adapters |
| 2026-11-28 | No se añade SSE a la consola | El front-end no hace polling de datos; el heartbeat solo mantiene el timeout de inactividad |
| 2026-11-28 | El bind del puerto es la comprobación de consola única | Un pre-check tiene carrera TOCTOU; el bind real da un error accionable |
| 2026-11-28 | `explore` queda fuera del catálogo de informes | Escribe `discovery.json` y puede avanzar el lifecycle; `plan --json` es derivación read-only |
| 2026-11-28 | "Arreglar" entrega comandos, no los ejecuta | La consola conserva su única superficie de escritura autenticada (`/api/action`) |
| 2026-11-28 | Silenciar causas vive en `localStorage` | Evita crear estado SE nuevo para una preferencia visual del navegador |

---

## 5. Qué sobra (candidatos a eliminar)

| Elemento | Estado | Acción |
|---|---|---|
| `_pi_patch()` | Eliminado | ✅ T25 |
| `runtime_config_generator.py` | API pública con tests; no se usa en el flujo de install | ✅ T26: conservar |
| `--runtimes` (si no se conecta) | Conectado en el CLI | ✅ T8 |
| Componentes con cuenta en `--all` | Excluidos con opt-in | ✅ T10 |
| Tres bootstraps distintos | Una implementación, tres entradas documentadas | ✅ T11 |

---

## 6. Bloqueos

| Bloqueo | Impacto | Desbloqueo |
|---|---|---|
| PR #111 requiere 1 review y `enforce_admins=true` | Nada llega a `main` sin aprobación humana | Aprobar en GitHub |
| Sin `gh` CLI | PRs por REST | Instalar `gh` o mantener el script actual |

---

## 7. Cómo se actualiza este documento

1. Al cerrar una tarea, cambia `[ ]` → `[x]` y anota la evidencia (comando,
   test o archivo).
2. Si una tarea cambia de alcance, actualiza el hallazgo, no lo borres.
3. Si se descarta, usa 🗑️ y escribe el motivo en Decisiones.
4. La fecha de cabecera se actualiza en cada PR que toque este archivo.

---

## 8. Resueltos

| ID | Cierre | Evidencia |
|---|---|---|
| F1 | Preset movido dentro de `config` en `_deepseek_patch` y `_pi_patch` | `yaml.safe_load` OK: 12 presets, 7 skills; `_pi_patch` después eliminado en T25 |
| F2 | `INTEGRATIONS/deepseek/README.md` + guía en español + tabla de 6 adapters | PR #111 |
| F3 | `--runtimes` conectado en el CLI | 167 tests del instalador OK; `adapters` en el resumen JSON |
| F4 | Probe MCP con 3 intentos y backoff 0.25/0.5 s | 103 tests de `test_install.py` OK; detalle `tras N intentos` solo tras agotar |
| F5 | `--all` excluye componentes con cuenta/toolchain | 170 tests del instalador OK; `gated_excluded` en el resumen JSON |
| F6 | TUI con pasos de modelo, runtime y adaptador | Pestaña **Configurar**; `SE-INSTALLER/tests/test_tui_config.py` (7 tests) |
| F7 | Catálogo de informes read-only | `console/reports.py` + `GET /api/report`; `test_report_catalog.py` |
| F8 | Pi y Hermes documentados | `INTEGRATIONS/pi/README.md`, `INTEGRATIONS/hermes/README.md`, tabla en `adapters.md` |
| F9 | Hermes queda fuera de `adapter all` a propósito | Test en `test_runtime_adapters.py`; motivo: colisión de `AGENTS.md`/`settings.json` |
| F10 | `_pi_patch()` eliminado | Sin referencias en código; `_deepseek_patch` conserva el fix de YAML |
| F11 | `runtime_config_generator.py` conservado como API pública | Exportado en `se_installer/__init__.py`, cubierto por `test_registries.py` |
| F12 | Descartado: no era un bug | `AGENTS.local.md` ya existía y se cuenta como `unchanged` |
| F13 | Consola única por bind | `bind_console()` en `server.py`; 3 tests en `test_port_guard.py` |
| F14 | Sin `gh` CLI: PRs por REST | Decisión operativa, sin código; ver `git credential fill` + API de GitHub |

---

## 9. Verificación de instalación en equipos nuevos (2026-11-28)

Auditoría de las cuatro formas de llegar a SE (CLI, scripts, TUI y web) contra el
código y las guías. No cambió el comportamiento: se corrigió la documentación
para que describa lo que realmente hace una máquina limpia.

| Hallazgo | Corrección aplicada |
|---|---|
| `installation.md` anunciaba 3 adapters y `all` para todos | 6 adapters; `all` = claude-code + codex + deepseek + pi, Hermes aparte |
| «CLI para modelos no implementado» | Existe `se shema-ai model --list/--set/--global-model` |
| Probe MCP descrito como un solo intento | 3 intentos con backoff 0.25/0.5 s; `tras N intentos` solo al agotar |
| `--skip-mcp-registration` como flag de `se install` | Solo lo aceptan los wrappers y la TUI |
| «`se install` nunca instala herramientas» | Cierto sin `--bootstrap`; con `--bootstrap` delega en `se-installer` |
| `se install --bootstrap --json` | Devuelve el resumen y omite el registro MCP |
| «22 componentes» / «14 componentes» | 13 componentes en `components.py` |
| `~/.se-installer/state.json` | `state/installation_state.json` + `installation_history.jsonl` |
| `pip install -e SE-INSTALLER` instalaba la web | El entry point está en `SCRIPTS/se_installer_web` |
| `se-installer-web --dev/--all/--apply` | Se ignoran: la UI elige opciones y el CLI acepta solo `--host/--port/--reload` |
| PowerShell con `--port` | Parámetros reales: `-Port`, `-NoBrowser`, `-Dev`, `-Help` |
| Consola «solo GET» | GET + un `POST /api/action` autenticado; guardia de puerto por bind con `--port` |
| Guía «otra computadora» en rama vieja | Ahora parte de `main` |
| Smoke sin Python en CI | CI hace `setup-python` 3.12; la instalación de Python se prueba en Sandbox/VM |

Evidencia: lectura de los parsers y comandos citados, `pip install -e
SCRIPTS/se_installer_web --dry-run` (rc=0), `se validate` y `se doctor` en verde.
La suite completa de este PR se registró en el commit de cierre. Detalle en
`installation.md`, `setup.es.md`, `installer-web.md`, `clean-machine-smoke.md` y
la guía resumida `instalacion-equipos-nuevos.es.md`.
