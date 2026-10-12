---
name: visual-frontend-engineering
description: Construir, renderizar, capturar y revisar visualmente un frontend de bajo costo y agnóstico de proveedor (builder + screenshot loop + diseño direccional). Úsalo cuando una UI deba ser visualmente verificable (screenshots/evidencia) sin depender de un modelo con visión; la revisión visual por modelo vision-capable (visual.review) es opcional y desacoplada.
metadata:
  system: system-engineering
  schema_version: "1"
  adapter: opencode
---

# visual-frontend-engineering

## purpose

Producir frontends (HTML/CSS/JS/static) cuyo resultado visual se pueda **verificar con
evidencia** (screenshots, estructura, métricas) a costo $0, sin atarse a un proveedor concreto
de modelo. Concepto: procesos verificables > modelo mágico.

## when_to_use

- Cuando se construye o modifica una interfaz y el criterio de aceptación es **visual**.
- Cuando se quiere demostrar calidad visual sin depender de visión del modelo implementador.
- Cuando se necesita un loop de revisión con capturas (BEFORE/AFTER) y diseño direccional (DESIGN.md).
- Para declarar la capacidad: providers `playwright` (browser.preview/snapshot/screenshot) y la
  revisión visual `visual.review` (deepseek-vision, availabilidad `unknown`).

## when_not_to_use

- Backend, lógica de negocio, APIs: usa agentes/skills de propósito general.
- Frontends ya a cargo de frameworks con su propio pipeline visual verificado.
- Cuando el entorno no tiene navegador (headless host sin Chrome/Edge) → resolver runtime primero.
- Como reemplazo de los commands `se validate|verify|doctor`: la Skill orquesta; los commands validan el Master System.

## inputs

- Código fuente de la UI (paths) y/o spec de la tarea visual.
- Navegador disponible: Chrome o Edge instalados (`channel="chrome"` / `channel="msedge"`), o Playwright instalado.
- (Opcional) token clave de proveedor vision-capable para `visual.review` (ej. DeepSeek).
- DESIGN.md o template (TEMPLATES/DESIGN.template.md) con dirección de diseño.

## preconditions

- Runtime de captura operable (Playwright instalado o `--channel chrome` … usar Chrome del sistema).
- Sin acceso a red del navegador → capturar sobre `file://` o servidor estático local.
- Scope autorizado; no tocar proyectos externos ni sus `.opencode`.

## procedure

1. **DIRECCIÓN**: crear/leer `DESIGN.md` (tokens YAML + prosa; formato Google DESIGN.md). Si
   no existe, partir del `TEMPLATES/DESIGN.template.md`. Definir: paleta (contraste WCAG ≥ 4.5:1
   texto), tipografía jerárquica, espaciado, radios, focus/estados, responsive breakpoints.
   Referencia licenciada (Apache-2.0/MIT, atribución en docs): Anthropic `frontend-design`,
   Vercel `web-interface-guidelines`.
2. **BUILD**: implementar la UI siguiendo DESIGN.md. Mantener el código estático y autónomo
   (sin build server interno) salvo que el task lo requiera.
3. **PREVIEW (browser.preview)**: abrir la página. Preferir `playwright-cli` (node) si existe;
   si no, usar Python: `pip install playwright` y `channel="chrome"` para reutilizar el Chrome
   instalado. Nunca descargar navegadores innecesarios.
4. **SNAPSHOT (browser.snapshot)**: capturar árbol de accesibilidad (`snapshot`) → verificar
   estructura semántica, landmarks, alternativas de imágenes (alt), foco navegable.
5. **SCREENSHOT (browser.screenshot)**: capturar **full-page** y **viewport** (1280×800 y
   375×812) a un dir de evidencia. Nombrar: `<paso>-<vista>.png` (ej. `r1-viewport.png`).
6. **REVIEW (visual.review → opcional)**: si `visual.review` está disponible (provider
   vision-capable configurado), pedir revisión de los PNG contra DESIGN.md. Si NO está
   disponible, hacer revisión estructural automática (métricas: contraste, overflow, jerarquía,
   alt faltantes) desde el DOM/computed styles — evidencia honesta sin visión.
7. **FIX**: aplicar correcciones derivadas de la revisión; iterar paso 3→6.
   **Máximo 3 rondas**; criterio de parada: revisión sin hallazgos accionables o ronda 3.
8. **EVIDENCE**: guardar en el dir de evidencia: screenshots (mandatorio para claims visuales),
   snapshot estructural, métricas JSON, DESIGN.md usado, diffs de cambios.
9. **CIERRE**: reportar qué se verificó (FACT/VERIFIED), qué quedó UNKNOWN (p. ej. revisión
   visual por modelo no disponible), costos ($0/opcional), y entregar paths de evidencia.

## evidence

- PNG full-page + viewport (al menos 1 juego por ronda; `rN-*.png`).
- Snapshot de accesibilidad y métricas (contraste, scroll horizontal, alt, jerarquía).
- DESIGN.md (baseline de diseño) y descripción de cambios ronda a ronda.
- Claims visuales = FACT sólo con screenshot citado; nunca inferir PASS visual sin captura.

## validation

- PASS: estructura semántica correcta, contraste WCAG, sin overflow horizontal, responsive en
  breakpoints, screenshots citados, DESIGN.md respetado, riesgos UNKNOWN declarados (p. ej.
  revisión por modelo no ejecutada si no hay provider).
- PARTIAL/BLOCKED: hallazgos sin corregir, capturas faltantes, contraste fallido, ronda de
  revisión que excede el cap sin evidencia.
- "No se encontró evidencia de revisión visual" NO es "la UI se ve bien".

## failure_modes

- Loop infinito: controlar por cap de 3 rondas y criterio de parada explícito.
- Modelo que se cuelga/refusa (reportado en comunidad para Big Pickle): reintentar 1 vez, luego
  fallar explícito con evidencia parcial — nunca fabricar.
- Sin runtime de captura → no declarar images verificables; reportar UNKNOWN.
- Screenshots que no reflejan la página (contenido no cargado): esperar `load` + `networkidle`.
- Múltiples providers: resultado no reproducible por dependencia del proveedor; fijar paso a paso.

## outputs

- Código de UI implementado/corregido.
- Dir de evidencia: screenshots, snapshot, métricas, DESIGN.md.
- Reporte de validación visual (PASS/PARTIAL/BLOCKED + evidencia citada + costos).

## restrictions

- No usar API keys ni tokens en logs/artefactos/prompts; el provider vision se configura fuera
  del alcance y su presencia se declara como availabilidad `unknown` hasta verificarse.
- No instalar navegadores ni descargar runtimes sin necesidad (reusar Chrome/Edge del sistema).
- No tocar proyectos externos ni sus `.opencode`.
- No fabricar screenshots ni claims visuales: cada claim visual cita su captura.
- Proveedor decoupled: la implementación nunca nombra un modelo como dependencia arquitectónica.