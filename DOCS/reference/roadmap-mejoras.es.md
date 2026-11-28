# Roadmap de mejoras — seguimiento

Documento vivo. Cada tarea tiene un ID, prioridad y estado. Se actualiza en el
mismo PR que resuelve la tarea.

**Última actualización:** 2026-11-27

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
| F12 | El dry-run del adapter cuenta un archivo menos | Dijo 8, escribió 9 | P3 |
| F13 | Dos consolas pueden quedar corriendo | `:8631` de prueba y `:8777` del clon | P3 |
| F14 | Sin `gh` CLI en el entorno | PRs creados por REST | P3 |

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

- [ ] **T8** Conectar `--runtimes` a `runtimes.generate_*`, o eliminarlo.
      Decisión pendiente: ¿el instalador genera adapters o solo componentes?
      - Si se conecta: tras instalar, ejecutar `se adapter <runtime>` por cada
        runtime pedido y reportarlo en el resumen.
      - Si se elimina: quitar el flag de `cli.py`, `orchestrator` y la TUI.
- [ ] **T9** Reintentos con backoff en el probe MCP (3 intentos, timeout
      creciente) antes de marcar `skipped`.
- [ ] **T10** Marcar componentes con `requires_account` / `requires_toolchain`
      y excluirlos de `--all` (o pedir confirmación explícita).
- [ ] **T11** Unificar `bootstrap.ps1` + `se install --bootstrap` +
      `install-web.ps1` en una sola ruta documentada.

**Criterio de cierre:** una instalación limpia con `--runtimes codex,deepseek`
deja ambos adapters generados y 4/4 MCP registrados.

### Fase 3 — Comando único para principiantes (P1)

- [ ] **T12** `se setup`: install + adapter (autodetectado) + MCP + doctor +
      abrir consola, idempotente y con `--dry-run`.
- [ ] **T13** Detección automática del harness por artefactos presentes
      (`.opencode/`, `.claude/`, `.codex/`, `.dsh/`, `.pi/`, `.hermes/`).
- [ ] **T14** Modo `--explain`: cada paso dice qué hace y qué archivo toca.
- [ ] **T15** `se setup --check` que solo diagnostique.

**Criterio de cierre:** un usuario nuevo pasa de clon a consola abierta con un
comando y sin leer documentación.

### Fase 4 — Interfaz (P2)

- [ ] **T16** TUI: pasos de modelo, runtime y adaptador.
- [ ] **T17** Consola: añadir al catálogo `explore`, `plan`, `gate`, `verify`,
      `health` (con su argv validado).
- [ ] **T18** Consola: botón "Arreglar" cuando `se doctor` falla.
- [ ] **T19** Consola: agrupar Atención por causa raíz y permitir silenciar.
- [ ] **T20** Consola: búsqueda global (proyectos, memoria, records).
- [ ] **T21** Consola: progreso en vivo (SSE/WebSocket) en vez de polling.
- [ ] **T22** Consola: token autogenerado en el primer arranque.

### Fase 5 — Limpieza y coherencia (P2/P3)

- [ ] **T23** Documentar Pi y Hermes (README de integración + tabla).
- [ ] **T24** Incluir Hermes en `se adapter all` (o renombrar el comando).
- [ ] **T25** Eliminar `_pi_patch()` o conectarlo.
- [ ] **T26** Eliminar `runtime_config_generator.py` o conectarlo (depende de T8).
- [ ] **T27** Corregir el conteo del dry-run del adapter.
- [ ] **T28** Evitar dos consolas simultáneas (bloqueo de puerto o aviso).

---

## 4. Decisiones

| Fecha | Decisión | Motivo |
|---|---|---|
| 2026-11-27 | El puerto canónico de la consola es **8777** | `dev_console.py` y `server.py`; 8631 era solo prueba |
| 2026-11-27 | El adapter DSH emite un **overlay**, no archivos por rol | DSH solo lee presets desde patch lists de Cordis |
| 2026-11-27 | `AGENTS.local.md` en vez de `AGENTS.md` | Evitar colisión con el adapter de Codex |
| 2026-11-27 | El modelo por rol se anota; el default solo si es uniforme | Un default process-wide misroutea un roster mixto |

---

## 5. Qué sobra (candidatos a eliminar)

| Elemento | Estado | Acción |
|---|---|---|
| `_pi_patch()` | Muerto | T25 |
| `runtime_config_generator.py` | Muerto | T26 |
| `--runtimes` (si no se conecta) | No-op | T8 |
| Componentes con cuenta en `--all` | Fallan siempre | T10 |
| Tres bootstraps distintos | Duplicación | T11 |

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
