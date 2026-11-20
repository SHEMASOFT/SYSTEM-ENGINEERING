/* SE-CONSOLE :: frontend (vanilla, no build step)
 *
 * Acciones: action surface enabled (delegates to se). Rendering contract: a value is never shown without its provenance. Every
 * fact carries an epistemic tag (OBSERVED / DERIVED / UNKNOWN) and, when it is
 * OBSERVED, the `se` command or canonical file it came from. Absence renders
 * as UNKNOWN with a reason, never as 0, "" or a green tick.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- state
  var state = { view: "overview", project: null, system: null, projects: null, attention: null };
  var root = document.getElementById("view-root");

  // ------------------------------------------------------------- ui / i18n
  // Spanish-first copy: every user-facing string rendered below lives here so
  // wording changes never require hunting through render code. Technical
  // identifiers, gate ids and se status values shown as data (OBSERVED,
  // DERIVED, UNKNOWN, PASS, WARN, FAIL, UNMANAGED) stay verbatim on purpose.
  var UI = {
    outage: {
      tag: "MOTOR CAÍDO",
      title: "El motor del sistema no puede ejecutarse: ",
      unknownReason: "motivo desconocido",
      sub: "Todos los veredictos de gobierno se muestran como UNKNOWN. No se calcula ni se infiere nada: la consola no sustituye al motor."
    },
    identity: {
      title: "Identidad del sistema",
      sub: "Qué es SYSTEM-ENGINEERING",
      name: "nombre",
      version: "versión",
      status: "estado",
      description: "descripción",
      schemaVersion: "schema_version",
      models: "modelos canónicos",
      sourceNote: "Fuente canónica: SYSTEM.json, VERSION, MASTER SYSTEM/MANIFEST.json"
    },
    health: {
      title: "Salud del sistema",
      sub: "Veredicto de se doctor, sin recalcular",
      checkNote: "cada check se lista abajo, sin agregar",
      explain: "Cuántas comprobaciones del sistema están bien (PASS), avisan (WARN) o fallan (FAIL). Muestra si el sistema de ingeniería necesita atención.",
      evidenceNote: "De dónde sale cada dato: medido directamente (OBSERVED), calculado (DERIVED) o no disponible (UNKNOWN).",
      focusTitle: "Checks que requieren atención"
    },
    healthCmd: {
      title: "Salud del motor (CMD-0016)",
      sub: "se health · envelope del motor",
      declared: "declarado",
      implemented: "implementado",
      invocable: "invocable ahora",
      mutates: "escribe canónico",
      note: "nota",
      helper: "`declarado` viene de COMMANDS/commands.json; `invocable ahora` incluye un sondeo real del motor. Se muestran por separado a propósito."
    },
    capabilities: {
      title: "Capacidades",
      sub: "se capabilities",
      state: "estado",
      available: "disponibles",
      providers: "proveedores",
      explain: "Qué sabe hacer el sistema de ingeniería: las capacidades disponibles para comprobar y avanzar el trabajo.",
      callout: "La capacidad es una propiedad del proveedor, no un campo del proyecto: la consola no la superpone al ciclo de vida."
    },
    inventory: {
      title: "Inventario de contratos",
      sub: "declarado por se vs observado por la consola",
      item: "elemento",
      declared: "se declara",
      observed: "consola observa",
      state: "estado"
    },
    lifecycle: {
      title: "Ciclo de vida y gates",
      sub: "Definición del framework (CORE/)",
      statesLabel: "estados: ",
      explain: "Las etapas por las que pasa un proyecto; un gate es una compuerta que debe abrirse para avanzar."
    },
    components: {
      agentsTitle: "Componentes: agentes y skills",
      agentsCount: "agentes",
      skillsCount: "skills",
      id: "id",
      role: "rol / descripción",
      source: "fuente",
      skillsTitle: "Skills",
      policiesTitle: "Componentes: políticas y dominios",
      policiesCount: "políticas",
      domainsCount: "dominios",
      policiesHeading: "Políticas",
      domainsHeading: "Dominios",
      commandsHeading: "Comandos se"
    },
    projects: {
      title: "Proyectos",
      explain: "Los proyectos registrados y su estado de salud. Cada tarjeta indica en qué punto está el proyecto y si está gestionado.",
      managedCount: "gestionado(s)",
      unmanagedCount: "no gestionado(s)",
      location: "en PROJECTS/",
      honesty: "Un proyecto sin PROJECT.json se declara UNMANAGED; nunca se inventa su estado.",
      lifecycle: "ciclo de vida: ",
      unmanagedExplain: "Proyecto sin gestión: no se vigila ni avanza por gates. Solo se muestra tal cual, sin inventar su estado.",
      // Friendly one-line summaries (T3). They only re-word what the engine
      // returned; the contract verdict (PASS/WARN/FAIL/UNKNOWN/MANUAL and the
      // gate/state ids) is shown verbatim on purpose.
      gateOk: "El gate {gate} está en PASS: el proyecto puede avanzar.",
      gateOkTo: "El gate {gate} está en PASS: el proyecto puede avanzar hacia {to}.",
      gateWarn: "El gate {gate} está en {status}: requiere revisión antes de avanzar.",
      gateWarnTo: "El gate {gate} está en {status}: requiere revisión antes de avanzar hacia {to}.",
      gateFail: "El gate {gate} está en {status}: el proyecto no puede avanzar hasta resolverlo.",
      gateFailTo: "El gate {gate} está en {status}: el proyecto no puede avanzar hacia {to} hasta resolverlo.",
      gateUnknown: "No se pudo determinar el estado del proyecto (UNKNOWN): el motor no devolvió un veredicto.",
      countsPass: "Los {pass} gates evaluados pasan (PASS): el proyecto no tiene bloqueos conocidos.",
      countsWarn: "Ningún gate falla, pero {warn} tienen condiciones pendientes de decisión humana (MANUAL).",
      countsFail: "Hay {fail} gates que no pasan (FAIL) y {warn} con pendientes (MANUAL): el proyecto tiene bloqueos registrados.",
      countsUnknown: "No se pudo evaluar {unknown} gates (UNKNOWN): su estado no se infiere."
    },
    detail: {
      unmanagedStrong: "Este directorio no es un proyecto gestionado por SYSTEM-ENGINEERING",
      unmanagedExplain: "Proyecto sin gestión: no se vigila ni avanza por gates. Solo se muestra tal cual, sin inventar su estado.",
      unmanagedConflicts: "Conflictos reportados por el motor",
      unmanagedReadonly: "SE-CONSOLE no crea un PROJECT.json ni infiere un estado para este directorio: la consola es de solo lectura.",
      owner: "responsable: ",
      gateMatrixTitle: "Matriz de gates G0–G8",
      gateMatrixSub: "Cada veredicto viene de se gate; no se recalcula",
      gateManualNote: "MANUAL se muestra como WARNING: una condición pendiente de juicio humano no es un PASS.",
      lifecycleTitle: "Ciclo de vida",
      lifecycleSub: "se context",
      lcState: "estado",
      lcNext: "siguiente transición",
      lcDeclared: "transiciones declaradas",
      lcMigrations: "migraciones",
      nextExplain: "El siguiente paso que desbloquea el avance del proyecto: el estado al que puede pasar y qué gates debe superar.",
      nextFail: "Para avanzar a {to} hay que resolver primero lo que falla: {conds}.",
      nextManual: "Para avanzar a {to} falta una decisión humana (MANUAL): {conds}.",
      nextClearOne: "El gate {gates} ya pasa (PASS): el proyecto puede avanzar a {to}.",
      nextClearMany: "Los gates {gates} ya pasan (PASS): el proyecto puede avanzar a {to}.",
      nextUnknown: "Para avanzar a {to} hay que superar los gates {gates}; no se pudo evaluar su detalle (UNKNOWN).",
      nextNone: "No hay una transición declarada desde el estado actual; no se puede indicar qué la desbloquea.",
      healthTitle: "Salud del proyecto",
      healthSub: "se health · CMD-0016 (envelope del motor)",
      healthState: "estado",
      healthPresent: "salud (presentación)",
      healthAvailable: "disponible",
      healthReason: "motivo",
      healthHelper: "El motor es la autoridad; la consola no re-ordena ni re-puntúa este envelope.",
      healthRawLabel: "ver envelope se.health verbatim",
      healthNoEnvelope: "Envelope no disponible (UNKNOWN). No se sintetiza uno.",
      manifestTitle: "PROJECT.json",
      manifestSub: "Manifiesto canónico",
      manifestSchema: "schema válido",
      discoveryTitle: "Discovery",
      discoverySub: "registro DISCOVERY (sin campo de estado)",
      discoveryNoSummary: "sin resumen",
      discoveryFindings: "hallazgos",
      discoveryUnknowns: "desconocidos",
      discoveryAssumptions: "suposiciones",
      discoveryConstraints: "restricciones",
      discoveryRisks: "riesgos",
      discoveryReviewed: "revisado por",
      discoveryHelper: "El registro DISCOVERY no transporta estado de gate; por eso se muestra UNKNOWN y no se infiere."
    },
    records: {
      title: "Registros por tipo",
      sub: "Transcripción + validación contra SCHEMAS/",
      colType: "tipo",
      colDisk: "en disco",
      colReview: "se review",
      colInvalid: "schema inválido",
      explain: "Las piezas de trabajo del proyecto (objetivos, requisitos, tareas) y su integridad: cuántas hay y si respetan el esquema.",
      helper: "'en disco' cuenta archivos; 'se review' cuenta registros por tipo según el motor. Difieren cuando existen registros de tipo no estándar (p.ej. REQ con type UNKNOWN/ASSUMPTION). No se promedian.",
      itemSuffix: " elemento(s)",
      linksTitle: "Enlaces entrantes",
      linksNone: "Sin enlaces entrantes: UNKNOWN o ninguno — no se infiere.",
      explorerTitle: "Explorar registros",
      explorerSub: "GET /api/record · solo lectura",
      traceLabel: "ver traza AUTO-02 (se context --scope trace --focus)",
      cardSub: "registro canónico + traza AUTO-02",
      explorerHelper: "Muestra el registro canónico tal cual y la traza que el motor reconstruye con AUTO-02 (se context --scope trace --focus). Las lecturas siguen siendo GET-only; la única vía de escritura es el POST autenticado y en lista blanca a /api/action, que delega a se (la consola no escribe estado de SE)."
    },
    trace: {
      title: "Trazabilidad e integridad",
      sub: "se review",
      gaps: "Gaps",
      links: "Notas de enlace"
    },
    context: {
      title: "Contexto AUTO-02 (se context)",
      sub: "reconstrucción de contexto",
      deepTitle: "scope deep (sin foco)",
      deepHelper: "AUTO-02 es focus-driven: sin --focus, scope>=work devuelve un conjunto de trabajo vacío de forma legítima.",
      deepNote: "Esto es comportamiento de SE, no una laguna de datos."
    },
    audit: {
      title: "Registro de cambios (mutation log)",
      entries: "entradas (solo lectura)",
      colSeq: "#",
      colRecord: "registro",
      colField: "campo",
      colValue: "valor",
      empty: "sin registros de cambios",
      helper: "Normalización: los ids separados por coma se interpretan como lista; el valor crudo se conserva para auditoría."
    },
    attention: {
      title: "Atención requerida · Acciones",
      projectTitle: "Atención requerida en este proyecto · Acciones",
      intro: "Consolida los gates FAIL, las condiciones MANUAL, los gaps de se review y los registros que fallan schema. La severidad ordena la atención; no sustituye un veredicto del motor.",
      orderNote: "el orden es prioridad de atención, no un veredicto de governance",
      severity: "severidad",
      area: "área",
      detail: "detalle",
      evidence: "evidencia",
      actions: "Acciones",
      empty: "sin elementos que requieran atención",
      total: "total"
    },
    action: {
      checkpoint: "Registrar avance",
      close: "Cerrar ejecución"
    },
    drawer: {
      close: "Cerrar detalle",
      gateTitle: "Detalle del gate",
      recordTitle: "Detalle del registro",
      openGate: "Ver detalle del gate",
      openRecord: "Ver detalle del registro",
      gateId: "gate",
      gateName: "nombre",
      gateFlow: "transición",
      gateVerdict: "Veredicto",
      gateStatus: "estado",
      gateHealth: "salud",
      gateConditions: "Condiciones",
      gateConflicts: "Conflictos del motor",
      noConditions: "El motor no reporta condiciones para este gate.",
      gateHelper: "Cada condición proviene de se gate; la consola no la recalcula ni la promedia.",
      gateNotEvaluated: "Este es el gate tal como lo define el framework. Su veredicto (condiciones y conflictos) es por proyecto: se consulta desde un proyecto gestionado.",
      recordHelper: "Mismo registro canónico y traza AUTO-02 que la vista del proyecto; lectura GET-only.",
      blocked_hint: "Bloqueado",
      blocked_hint_detail: "El proyecto no puede avanzar hacia {to} hasta resolver el gate {gates}. Vea Atención para ver los pasos a seguir.",
      warning_hint: "Revisar antes de avanzar",
      warning_hint_detail: "El gate {gates} tiene condiciones pendientes. Revíalas en Atención antes de avanzar hacia {to}.",
      ready_hint: "Listo para avanzar",
      ready_hint_detail: "El gate {gates} ya pasa. El proyecto puede avanzar hacia {to}.",
      what_happens: "Qué pasa",
      what_to_do: "Qué hacer",
      view_details: "Ver detalles",
      steps_to_follow: "Pasos a seguir",
      blocked_explain: "Este elemento está bloqueado. No se puede avanzar hasta resolverlo.",
      warning_explain: "Este elemento tiene una advertencia. Revíselo pronto; no detiene el proyecto por sí solo.",
      info_explain: "Información para revisar.",
      no_steps: "No hay pasos específicos definidos todavía.",
      where_it_belongs: "A qué pertenece",
      actions_available: "Acciones disponibles",
      step_receipt: "Registre la evidencia de ejecución (receipt) de la tarea.",
      step_artifact: "Revise y corrija el archivo del artefacto indicado.",
      step_gate: "Revise las condiciones del gate y resuelva las que fallen.",
      step_evidence: "Aporte la evidencia faltante para el registro indicado.",
      step_acceptance: "Complete la evidencia de aceptación de usuario (UAT).",
      step_release: "Publique el release y vincúlelo a la evidencia.",
      step_operations: "Cree el documento de operaciones (docs/operations.md).",
      step_generic: "Revise el detalle del elemento y resuelva lo que corresponda."
    }
  };

  // ------------------------------------------------------------- i18n
  // Every user-facing string lives here, keyed by language. UI.es is populated
  // by copying UI (above); UI.en carries the English wording. Change language
  // with the header selector; the choice persists in localStorage.
  var LANG_ES = JSON.parse(JSON.stringify(UI));
  var LANG_EN = {
    outage: {
      tag: "ENGINE DOWN",
      title: "The system engine cannot run: ",
      unknownReason: "reason unknown",
      sub: "All governance verdicts show UNKNOWN. Nothing is calculated or inferred: the console does not replace the engine."
    },
    identity: {
      title: "System identity",
      sub: "What SYSTEM-ENGINEERING is",
      name: "name",
      version: "version",
      status: "status",
      description: "description",
      schemaVersion: "schema_version",
      models: "canonical models",
      sourceNote: "Canonical source: SYSTEM.json, VERSION, MASTER SYSTEM/MANIFEST.json"
    },
    health: {
      title: "System health",
      sub: "se doctor verdict, not recalculated",
      checkNote: "each check is listed below, as-is",
      explain: "How many system checks pass (PASS), warn (WARN) or fail (FAIL). Shows whether the engineering system needs attention.",
      evidenceNote: "Where each datum comes from: measured directly (OBSERVED), calculated (DERIVED) or unavailable (UNKNOWN).",
      focusTitle: "Checks needing attention"
    },
    healthCmd: {
      title: "Engine health (CMD-0016)",
      sub: "se health · engine envelope",
      declared: "declared",
      implemented: "implemented",
      invocable: "invokable now",
      mutates: "writes canonical",
      note: "note",
      helper: "`declared` comes from COMMANDS/commands.json; `invokable now` includes a real engine probe. They are shown separately on purpose."
    },
    capabilities: {
      title: "Capabilities",
      sub: "se capabilities",
      state: "state",
      available: "available",
      providers: "providers",
      explain: "What the engineering system knows how to do: the capabilities available to check and advance work.",
      callout: "The capability is a property of the provider, not a field of the project: the console does not overlay it onto the lifecycle."
    },
    inventory: {
      title: "Contract inventory",
      sub: "declared by se vs observed by the console",
      item: "item",
      declared: "se declares",
      observed: "console observes",
      state: "state"
    },
    lifecycle: {
      title: "Lifecycle and gates",
      sub: "Framework definition (CORE/)",
      statesLabel: "stages: ",
      explain: "The stages a project passes through; a gate is a checkpoint that must open to advance."
    },
    components: {
      agentsTitle: "Components: agents and skills",
      agentsCount: "agents",
      skillsCount: "skills",
      id: "id",
      role: "role / description",
      source: "source",
      skillsTitle: "Skills",
      policiesTitle: "Components: policies and domains",
      policiesCount: "policies",
      domainsCount: "domains",
      policiesHeading: "Policies",
      domainsHeading: "Domains",
      commandsHeading: "se commands"
    },
    projects: {
      title: "Projects",
      explain: "Registered projects and their health. Each card shows where the project stands and whether it is managed.",
      managedCount: "managed",
      unmanagedCount: "unmanaged",
      location: "in PROJECTS/",
      honesty: "A project without PROJECT.json is declared UNMANAGED; its state is never invented.",
      lifecycle: "lifecycle: ",
      unmanagedExplain: "Unmanaged project: it is not monitored or advanced through gates. It is shown as-is, with no invented state.",
      gateOk: "Gate {gate} is PASS: the project can advance.",
      gateOkTo: "Gate {gate} is PASS: the project can advance toward {to}.",
      gateWarn: "Gate {gate} is {status}: needs review before advancing.",
      gateWarnTo: "Gate {gate} is {status}: needs review before advancing toward {to}.",
      gateFail: "Gate {gate} is {status}: the project cannot advance until it is resolved.",
      gateFailTo: "Gate {gate} is {status}: the project cannot advance toward {to} until it is resolved.",
      gateUnknown: "The project state could not be determined (UNKNOWN): the engine returned no verdict.",
      countsPass: "All {pass} evaluated gates pass (PASS): the project has no known blocks.",
      countsWarn: "No gate fails, but {warn} have conditions pending a human decision (MANUAL).",
      countsFail: "There are {fail} failing gates (FAIL) and {warn} pending (MANUAL): the project has registered blocks.",
      countsUnknown: "Could not evaluate {unknown} gates (UNKNOWN): their state cannot be inferred."
    },
    detail: {
      unmanagedStrong: "This directory is not a SYSTEM-ENGINEERING managed project",
      unmanagedExplain: "Unmanaged project: it is not monitored or advanced through gates. It is shown as-is, with no invented state.",
      unmanagedConflicts: "Conflicts reported by the engine",
      unmanagedReadonly: "SE-CONSOLE does not create a PROJECT.json or infer a state for this directory: the console is read-only.",
      owner: "owner: ",
      gateMatrixTitle: "Gate matrix G0–G8",
      gateMatrixSub: "Each verdict comes from se gate; it is not recalculated",
      gateManualNote: "MANUAL shows as WARNING: a condition pending human judgment is not a PASS.",
      lifecycleTitle: "Lifecycle",
      lifecycleSub: "se context",
      lcState: "state",
      lcNext: "next transition",
      lcDeclared: "declared transitions",
      lcMigrations: "migrations",
      nextExplain: "The next step that unblocks project advancement: the state it can reach and which gates it must clear.",
      nextFail: "To advance to {to}, you must first resolve what fails: {conds}.",
      nextManual: "To advance to {to}, a human decision (MANUAL) is missing: {conds}.",
      nextClearOne: "Gate {gates} already passes (PASS): the project can advance to {to}.",
      nextClearMany: "Gates {gates} already pass (PASS): the project can advance to {to}.",
      nextUnknown: "To advance to {to} you must clear gates {gates}; their detail could not be evaluated (UNKNOWN).",
      nextNone: "No transition is declared from the current state; nothing can be indicated to unblock it.",
      healthTitle: "Project health",
      healthSub: "se health · CMD-0016 (engine envelope)",
      healthState: "state",
      healthPresent: "health (presentation)",
      healthAvailable: "available",
      healthReason: "reason",
      healthHelper: "The engine is the authority; the console does not re-order or re-score this envelope.",
      healthRawLabel: "view raw se.health envelope",
      healthNoEnvelope: "Envelope unavailable (UNKNOWN). No synthetic one is produced.",
      manifestTitle: "PROJECT.json",
      manifestSub: "Canonical manifest",
      manifestSchema: "schema valid",
      discoveryTitle: "Discovery",
      discoverySub: "DISCOVERY record (no state field)",
      discoveryNoSummary: "no summary",
      discoveryFindings: "findings",
      discoveryUnknowns: "unknowns",
      discoveryAssumptions: "assumptions",
      discoveryConstraints: "constraints",
      discoveryRisks: "risks",
      discoveryReviewed: "reviewed by",
      discoveryHelper: "The DISCOVERY record carries no gate state; therefore it shows UNKNOWN and nothing is inferred."
    },
    records: {
      title: "Records by type",
      sub: "Transcription + validation against SCHEMAS/",
      colType: "type",
      colDisk: "on disk",
      colReview: "se review",
      colInvalid: "schema invalid",
      explain: "The project's pieces of work (objectives, requirements, tasks) and their integrity: how many there are and whether they respect the schema.",
      helper: "'on disk' counts files; 'se review' counts records by type per the engine. They differ when non-standard type records exist (e.g. REQ with type UNKNOWN/ASSUMPTION). They are not averaged.",
      itemSuffix: " item(s)",
      linksTitle: "Incoming links",
      linksNone: "No incoming links: UNKNOWN or none — nothing is inferred.",
      explorerTitle: "Explore records",
      explorerSub: "GET /api/record · read-only",
      traceLabel: "view AUTO-02 trace (se context --scope trace --focus)",
      cardSub: "canonical record + AUTO-02 trace",
      explorerHelper: "Shows the canonical record as-is and the trace the engine reconstructs with AUTO-02 (se context --scope trace --focus). Reads are GET-only; the only write path is the authenticated, allow-listed POST to /api/action, which delegates to se (the console never writes SE state)."
    },
    trace: {
      title: "Traceability and integrity",
      sub: "se review",
      gaps: "Gaps",
      links: "Link notes"
    },
    context: {
      title: "AUTO-02 context (se context)",
      sub: "context reconstruction",
      deepTitle: "scope deep (no focus)",
      deepHelper: "AUTO-02 is focus-driven: without --focus, scope>=work legitimately returns an empty work set.",
      deepNote: "This is SE behavior, not a data gap."
    },
    audit: {
      title: "Change log (mutation log)",
      entries: "entries (read-only)",
      colSeq: "#",
      colRecord: "record",
      colField: "field",
      colValue: "value",
      empty: "no change records",
      helper: "Normalization: comma-separated ids are interpreted as a list; the raw value is preserved for audit."
    },
    attention: {
      title: "Attention required · Actions",
      projectTitle: "Attention required in this project · Actions",
      intro: "Consolidates FAIL gates, MANUAL conditions, se review gaps and records that fail schema. Severity orders attention; it does not replace an engine verdict.",
      orderNote: "the order is attention priority, not a governance verdict",
      severity: "severity",
      area: "area",
      detail: "detail",
      evidence: "evidence",
      actions: "Actions",
      empty: "no items needing attention",
      total: "total"
    },
    action: {
      checkpoint: "Register progress",
      close: "Close execution"
    },
    drawer: {
      close: "Close detail",
      gateTitle: "Gate detail",
      recordTitle: "Record detail",
      openGate: "View gate detail",
      openRecord: "View record detail",
      gateId: "gate",
      gateName: "name",
      gateFlow: "transition",
      gateVerdict: "Verdict",
      gateStatus: "state",
      gateHealth: "health",
      gateConditions: "Conditions",
      gateConflicts: "Engine conflicts",
      noConditions: "The engine reports no conditions for this gate.",
      gateHelper: "Each condition comes from se gate; the console does not recalculate or average it.",
      gateNotEvaluated: "This is the gate as defined by the framework. Its verdict (conditions and conflicts) is per-project: it is queried from a managed project.",
      recordHelper: "Same canonical record and AUTO-02 trace as the project view; GET-only reading.",
      blocked_hint: "Blocked",
      blocked_hint_detail: "The project cannot advance to {to} until gate {gates} is resolved. See Attention for the steps to follow.",
      warning_hint: "Review before advancing",
      warning_hint_detail: "Gate {gates} has pending conditions. Review them in Attention before advancing to {to}.",
      ready_hint: "Ready to advance",
      ready_hint_detail: "Gate {gates} already passes. The project can advance to {to}.",
      what_happens: "What happens",
      what_to_do: "What to do",
      view_details: "View details",
      steps_to_follow: "Steps to follow",
      blocked_explain: "This item is blocked. It cannot be advanced until resolved.",
      warning_explain: "This item has a warning. Review it soon; it does not block the project by itself.",
      info_explain: "Information to review.",
      no_steps: "No specific steps defined yet.",
      where_it_belongs: "Where it belongs",
      actions_available: "Actions available",
      step_receipt: "Register the execution evidence (receipt) for the task.",
      step_artifact: "Review and fix the indicated artifact file.",
      step_gate: "Review the gate conditions and resolve the failing ones.",
      step_evidence: "Provide the missing evidence for the indicated record.",
      step_acceptance: "Complete the user acceptance evidence (UAT).",
      step_release: "Publish the release and link it to the evidence.",
      step_operations: "Create the operations document (docs/operations.md).",
      step_generic: "Review the item detail and resolve what applies."
    }
  };

  var currentLang = "es";
  function t(path) {
    var langObj = currentLang === "en" ? LANG_EN : LANG_ES;
    var parts = path.split(".");
    var cur = langObj;
    for (var i = 0; i < parts.length; i++) {
      if (!cur || typeof cur !== "object") return path;
      cur = cur[parts[i]];
    }
    return cur === undefined ? path : cur;
  }
  function setLang(code) {
    currentLang = code;
    document.documentElement.setAttribute("lang", code);
    try { localStorage.setItem("se-console-lang", code); } catch (e) {}
    go(state.view);
  }

  function initLang() {
    var saved = null;
    try { saved = localStorage.getItem("se-console-lang"); } catch (e) {}
    if (saved === "en") setLang("en");
    var sel = document.getElementById("sel-lang");
    if (sel) sel.value = currentLang;
  }

  // ---------------------------------------------------------------- utils
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") n.className = attrs[k];
        else if (k === "text") n.textContent = attrs[k];
        else if (k === "html") n.innerHTML = attrs[k];
        else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) n.setAttribute(k, attrs[k]);
      });
    }
    // Accept a node, an array of nodes, a string, or nothing. Normalising here
    // keeps call sites free of wrapper arrays and removes a whole error class.
    var list = kids === undefined || kids === null ? [] :
      (Array.isArray(kids) ? kids : [kids]);
    list.forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      n.appendChild(typeof c === "string" || typeof c === "number"
        ? document.createTextNode(String(c)) : c);
    });
    return n;
  }

  function get(path, obj) {
    var parts = path.split("."), cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur === null || cur === undefined) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  /* A "fact" from the API is {value, epistemic, source, note}. */
  function fact(path, obj, fallback) {
    var f = get(path, obj);
    if (f === undefined || f === null) return { value: undefined, epistemic: "UNKNOWN", source: "—", note: null };
    if (f && typeof f === "object" && "epistemic" in f) return f;
    return { value: f, epistemic: "OBSERVED", source: "—", note: null };
  }

  function isEmpty(v) {
    return v === undefined || v === null || v === "" ||
      (Array.isArray(v) && v.length === 0);
  }

  /** Render a value with its provenance. Empty -> explicit UNKNOWN + reason. */
  function val(path, obj, opts) {
    opts = opts || {};
    var f = fact(path, obj);
    var span = el("span", { class: opts.cls || "" });
    if (isEmpty(f.value) && f.value !== 0) {
      // The UNKNOWN chip *is* the epistemic statement here. Appending a second
      // OBSERVED/DERIVED tag would read as a contradiction.
      span.appendChild(el("span", {
        class: "tag tag-UNKNOWN",
        title: "fuente declarada: " + (f.source || "—") + (f.note ? " · " + f.note : "")
      }, "UNKNOWN"));
      if (opts.reason !== false) {
        span.appendChild(el("span", { class: "muted", text: " " + (f.note || "no observado") }));
      }
      return span;
    }
    span.appendChild(document.createTextNode(opts.fmt ? opts.fmt(f.value) : String(f.value)));
    if (opts.tags !== false) {
      span.appendChild(document.createTextNode(" "));
      span.appendChild(epTag(f.epistemic, f.source));
    }
    return span;
  }

  function epTag(epistemic, source) {
    var t = el("span", {
      class: "tag tag-" + (epistemic || "UNKNOWN"),
      text: epistemic || "UNKNOWN",
      title: source ? "fuente: " + source : "sin fuente declarada"
    });
    return t;
  }

  function healthChip(health, label) {
    return el("span", { class: "health-chip health-" + (health || "UNKNOWN") }, [
      el("span", { class: "chip-dot" }),
      el("span", { class: "chip-label", text: label || health || "UNKNOWN" })
    ]);
  }

  function statusChip(status) {
    var s = status || "UNKNOWN";
    return el("span", { class: "status-chip status-" + s, text: s });
  }

  // ---------------------------------------------------------------- token
  function getToken() {
    try { return sessionStorage.getItem("se-console-token") || ""; } catch (e) { return ""; }
  }
  function setToken(v) {
    try { sessionStorage.setItem("se-console-token", v || ""); } catch (e) {}
  }

  function labelForAction(id) {
    if (id === "run.checkpoint") return t("action.checkpoint");
    if (id === "run.close") return t("action.close");
    return id;
  }

  function executeAction(actionId, item, projectRel) {
    var token = getToken();
    if (!token) {
      alert("Falta el token. Pegalo una vez en la cabecera (guardado en sessionStorage). Ruta: ~/.config/se-console/token");
      return;
    }

    var params = {};
    if (actionId === "run.checkpoint") {
      var nextStep = prompt("next_step (opcional):", item.detail || "");
      if (nextStep === null) return;
      if (nextStep) params.next_step = nextStep;
      var completed = prompt("completed (opcional, separado por comas):", "");
      if (completed === null) return;
      if (completed.trim()) params.completed = completed.trim();
      var pending = prompt("pending (opcional, separado por comas):", "");
      if (pending === null) return;
      if (pending.trim()) params.pending = pending.trim();
      var blocked = prompt("blocked (opcional, separado por comas):", "");
      if (blocked === null) return;
      if (blocked.trim()) params.blocked = blocked.trim();
    } else if (actionId === "run.close") {
      var state = prompt("state (COMPLETED|FAILED|BLOCKED|CANCELLED):", "");
      if (state === null) return;
      params.state = state.trim();
      var summary = prompt("summary (opcional):", "");
      if (summary === null) return;
      if (summary.trim()) params.summary = summary.trim();
      var by = prompt("by (opcional):", "");
      if (by === null) return;
      if (by.trim()) params.by = by.trim();
    } else if (actionId === "transition.attest") {
      // action_params comes from read_model.build_attention: { to, conditions[], context[] }
      var ap = item && item.action_params;
      if (!ap || !ap.to || !ap.conditions || !ap.conditions.length) {
        alert("Faltan parámetros de transición: to y conditions son obligatorios.");
        return;
      }
      params.to = ap.to;
      params.conditions = ap.conditions;

      // Show context to the human so they know what they're attesting to
      var ctx = ap.context || [];
      var detailLines = ctx.map(function (c) {
        return "- " + (c.id || "?") + ": " + (c.description || c.detail || "sin descripción");
      }).join("\n");
      var msg = "Confirmar attest para la transición a " + ap.to + ".\nCondiciones:\n" + detailLines +
        "\n\nEscribe 'ATTEST' para confirmar (mayúsculas requeridas):";
      var attest = prompt(msg, "");
      if (attest === null) return;
      if (attest !== "ATTEST") {
        alert("Attest cancelado: se esperaba 'ATTEST' exacto.");
        return;
      }
      params.attest = "confirmed";

      var by = prompt("by (opcional, identificación del humano):", "");
      if (by === null) return;
      if (by.trim()) params.by = by.trim();
    }

    var payload = {
      action: actionId,
      project: projectRel,
      // The attention title reads "RUN RUN-0001 blocked": a pattern like
      // /RUN ([^-\s]+)/ matches the word "RUN" and drops the id. Prefer the
      // evidence path ("runs/RUN-0001.json") and match the id shape directly.
      run: ((item.evidence || "").match(/RUN-\d+/) || item.title.match(/RUN-\d+/) || [""])[0],
      params: params,
      idempotency_key: (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : ("k-" + Date.now())
    };
    if (item.expected_revision) payload.expected_revision = item.expected_revision;

    fetch("/api/action", {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-SE-Console-Token": token
      },
      body: JSON.stringify(payload)
    }).then(function(r) {
      return r.json().then(function(j){ return {status:r.status, body:j}; });
    }).then(function(res){
      var out = JSON.stringify(res.body, null, 2);
      alert("HTTP " + res.status + "\n" + out);
    }).catch(function(e){
      alert("Error: " + e.message);
    });
  }



  function panel(title, sub, bodyKids, bodyClass) {
    return el("section", { class: "panel" }, [
      el("div", { class: "panel-head" }, [
        el("div", {}, [
          el("h2", { class: "panel-title", text: title }),
          sub ? el("p", { class: "panel-sub", text: sub }) : null
        ])
      ]),
      el("div", { class: "panel-body " + (bodyClass || "") }, bodyKids)
    ]);
  }

  function kv(pairs) {
    var dl = el("dl", { class: "kv" });
    pairs.forEach(function (p) {
      if (!p) return;
      dl.appendChild(el("dt", { text: p[0] }));
      var dd = el("dd");
      var v = p[1];
      if (typeof v === "string" || typeof v === "number") dd.textContent = String(v);
      else if (v) dd.appendChild(v);
      dl.appendChild(dd);
    });
    return dl;
  }

  function list(items, render) {
    if (!items || !items.length) return el("p", { class: "empty", text: "sin elementos" });
    var ul = el("ul", { class: "list" });
    items.forEach(function (i) { ul.appendChild(render(i)); });
    return ul;
  }

  function bullets(items) {
    if (!items || !items.length) return el("p", { class: "empty", text: "—" });
    var d = el("div", { class: "bullets" });
    items.forEach(function (t) { d.appendChild(el("div", { class: "bullet", text: t })); });
    return d;
  }

  function raw(obj, label) {
    return el("details", { class: "raw" }, [
      el("summary", { text: label || "ver JSON observado" }),
      el("pre", { text: JSON.stringify(obj, null, 2) })
    ]);
  }

  // ---------------------------------------------------------------- fetch
  function api(path) {
    return fetch(path, { headers: { "Accept": "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error(path + " -> HTTP " + r.status);
      return r.json();
    });
  }

  // ------------------------------------------------------------ lifecycle
  // DESIGN-5C option A. The console stops itself once nobody has asked it for
  // anything for a while, so the operator needs no "stop" button: closing this
  // page is enough. This ping is the cheap GET /api/heartbeat -- no SE read, no
  // subprocess -- and it is what tells the server a client is still here.
  //
  // Deliberate caveat (declared in DESIGN-5C 5/A, not hidden here): browsers
  // throttle timers in background tabs, so the ping can slow down while the tab
  // stays open. That is why the timeout the launcher uses is minutes, not
  // seconds.
  var HEARTBEAT_MS = 30000;
  function startHeartbeat() {
    function ping() {
      // The server may be stopping right now; a failed ping is not an error.
      fetch("/api/heartbeat", { headers: { "Accept": "application/json" } })
        .catch(function () {});
    }
    ping();
    setInterval(ping, HEARTBEAT_MS);
  }

  // ------------------------------------------------------- record explorer
  // Read-only disclosure over GET /api/record. It displays canonical bytes and
  // the engine's own AUTO-02 focus trace. There is deliberately no affordance
  // to create, edit or transition anything: the endpoint is GET-only and the
  // console is a viewer, not an editor.
  function recordExplorer(relPath, recs, focusType) {
    var host = el("div", { class: "recx" });
    var listBox = el("div", { class: "recx-ids" });   // siblings: persistent
    var out = el("div", { class: "recx-out" });        // detail: replaced

    function showRecord(type, id) {
      Array.prototype.forEach.call(listBox.querySelectorAll("[data-rec-id]"), function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-rec-id") === id ? "true" : "false");
      });
      out.textContent = "cargando " + type + " " + id + "…";
      api("/api/record?rel_path=" + encodeURIComponent(relPath) +
          "&type=" + encodeURIComponent(type) + "&id=" + encodeURIComponent(id))
        .then(function (d) { out.textContent = ""; out.appendChild(recordCard(d, type, id)); })
        .catch(function (e) {
          out.textContent = "";
          out.appendChild(el("p", { class: "muted", text: "no se pudo leer el registro: " + e.message }));
        });
    }

    // The sibling list must survive a record selection, otherwise picking one
    // record destroys the only way to pick another.
    function idList(type) {
      var row = (recs || {})[type] || {};
      var ids = row.ids || [];
      listBox.textContent = "";
      if (row.absent) {
        listBox.appendChild(el("p", { class: "muted", text: type + ": el motor no declara este tipo — UNKNOWN, no 0." }));
        return;
      }
      if (!ids.length) {
        listBox.appendChild(el("p", { class: "muted", text: type + ": sin registros." }));
        return;
      }
      ids.forEach(function (id) {
        listBox.appendChild(el("button", {
          class: "chip chip-btn", type: "button", "data-rec-id": id,
          "aria-pressed": "false", text: id,
          onclick: function () { showRecord(type, id); }
        }));
      });
    }

    // Every declared record type is offered, including empty ones. Hiding a
    // type with zero records would be a silent absence; showing "sin registros"
    // states the fact. A type the engine does not declare at all is shown as
    // "—" (UNKNOWN), which is a different claim from zero.
    var types = Object.keys(recs || {});
    var first = (focusType && recs && recs[focusType]) ? focusType
      : types.filter(function (t) { return (recs[t].ids || []).length; })[0];

    host.appendChild(el("div", { class: "recx-types" }, types.map(function (t) {
      var n = ((recs[t] || {}).ids || []).length;
      return el("button", {
        class: "chip chip-btn", type: "button", text: t + " (" + (recs[t].absent ? "—" : n) + ")",
        "aria-pressed": t === first ? "true" : "false",
        onclick: function () {
          Array.prototype.forEach.call(host.querySelectorAll(".recx-types .chip"), function (b) {
            b.setAttribute("aria-pressed", "false");
          });
          this.setAttribute("aria-pressed", "true");
          out.textContent = "";
          idList(t);
          var ids = (recs[t].ids || []);
          if (ids.length) showRecord(t, ids[0]); else out.appendChild(el("p", { class: "muted", text: "sin registro que mostrar." }));
        }
      });
    })));
    host.appendChild(listBox);

    var firstIds = first ? ((recs[first] || {}).ids || []) : [];
    if (first && firstIds.length) { idList(first); showRecord(first, firstIds[0]); }
    else if (first) { idList(first); out.appendChild(el("p", { class: "muted", text: "sin registro que mostrar." })); }
    else { out.appendChild(el("p", { class: "muted", text: "sin registros." })); }

    return el("div", {}, [host, out]);
  }

  function recordCard(d, type, id) {
    var facts = d.record || {};
    var val = facts.value;
    var rows = [];
    Object.keys(val || {}).forEach(function (k) {
      var v = val[k];
      var shown = (v && typeof v === "object")
        ? (Array.isArray(v) ? (v.length ? v.length + t("records.itemSuffix") : "[]") : JSON.stringify(v))
        : String(v);
      if (shown === "" || shown === "undefined" || shown === "null") shown = "UNKNOWN";
      rows.push([k, shown]);
    });
    var kids = [kv(rows)];

    var links = (d.inbound_links || {}).value;
    if (Array.isArray(links) && links.length) {
      kids.push(el("h3", { class: "panel-title", style: "font-size:13px;margin:14px 0 8px",
        text: t("records.linksTitle") + " (" + links.length + ")" }));
      kids.push(bullets(links));
    } else {
      kids.push(el("p", { class: "muted", style: "font-size:12px",
        text: t("records.linksNone") }));
    }

    var trace = (d.trace || d.context || {}).value;
    kids.push(el("div", { class: "tag-row", style: "margin-top:12px" }, [
      epTag(facts.epistemic || "UNKNOWN", facts.source || "unknown"),
      epTag("OBSERVED", "GET /api/record")
    ]));
    if (trace) kids.push(raw(trace, t("records.traceLabel")));

    return panel(type + " · " + id, t("records.cardSub"), kids, "tight");
  }

  // ---------------------------------------------------------------- drawer
  // Click-to-detail side drawer. It is a viewer only: every panel it renders
  // reuses data the page already fetched (the gates matrix, the framework gate
  // list) or the existing GET /api/record fetch-on-click. No new endpoint and
  // no new API shape are introduced.
  var _drawer = null;
  var drawerOpen = false;
  var drawerTrigger = null;
  var drawerKeyHandler = null;

  function drawerEls() {
    if (_drawer) return _drawer;
    var title = el("h2", { class: "drawer-title", id: "drawer-title" });
    var closeBtn = el("button", {
      type: "button", class: "btn btn-icon drawer-close",
      "aria-label": t("drawer.close"), title: t("drawer.close"),
      onclick: function () { closeDrawer(); }
    }, el("span", { "aria-hidden": "true", text: "✕" }));
    var body = el("div", { class: "drawer-body", id: "drawer-body" });
    var overlay = el("div", {
      class: "drawer-overlay", hidden: "hidden",
      onclick: function () { closeDrawer(); }
    });
    var panelEl = el("aside", {
      class: "drawer", id: "drawer", role: "dialog", "aria-modal": "true",
      "aria-labelledby": "drawer-title", tabindex: "-1", hidden: "hidden"
    }, [
      el("div", { class: "drawer-head" }, [title, closeBtn]),
      body
    ]);
    document.body.appendChild(overlay);
    document.body.appendChild(panelEl);
    _drawer = { overlay: overlay, panel: panelEl, title: title, body: body, closeBtn: closeBtn };
    return _drawer;
  }

  function openDrawer(title, node, trigger) {
    var d = drawerEls();
    d.title.textContent = title;
    d.body.textContent = "";
    if (node) d.body.appendChild(node);
    drawerTrigger = trigger || document.activeElement || null;
    d.overlay.hidden = false;
    d.panel.hidden = false;
    // Restart the slide-in from the off-screen state.
    d.panel.classList.remove("is-open");
    void d.panel.offsetWidth;
    d.panel.classList.add("is-open");
    d.overlay.classList.add("is-open");
    drawerOpen = true;
    document.body.classList.add("drawer-open");
    d.panel.focus();
    if (!drawerKeyHandler) {
      drawerKeyHandler = function (e) {
        if (e.key === "Escape" || e.key === "Esc") closeDrawer();
      };
      document.addEventListener("keydown", drawerKeyHandler);
    }
  }

  function closeDrawer() {
    if (!drawerOpen) return;
    var d = drawerEls();
    drawerOpen = false;
    d.panel.classList.remove("is-open");
    d.overlay.classList.remove("is-open");
    d.panel.hidden = true;
    d.overlay.hidden = true;
    document.body.classList.remove("drawer-open");
    if (drawerKeyHandler) {
      document.removeEventListener("keydown", drawerKeyHandler);
      drawerKeyHandler = null;
    }
    var t = drawerTrigger;
    drawerTrigger = null;
    if (t && t.focus && document.contains(t)) {
      try { t.focus(); } catch (e) {}
    }
  }

  // Make an existing node activate on click and on Enter/Space, without
  // changing its tag or its CSS class (tests select `.gate` and `.proj-card`).
  function clickable(node, onActivate, label) {
    node.classList.add("is-clickable");
    node.setAttribute("role", "button");
    node.setAttribute("tabindex", "0");
    if (label) node.setAttribute("aria-label", label);
    node.addEventListener("click", function (e) { onActivate(e, node); });
    node.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        onActivate(e, node);
      }
    });
    return node;
  }

  function conditionNode(c) {
    var desc = c && (c.description || c.detail);
    return el("li", { class: "list-item" }, [
      el("div", { class: "li-main" }, [
        el("div", { class: "li-title mono", text: (c && c.id) || "—" }),
        desc ? el("div", { class: "li-sub", text: desc }) : null
      ]),
      statusChip((c && c.status) || "UNKNOWN")
    ]);
  }

  /* Gate detail. `evaluated` distinguishes a per-project verdict (full matrix
     entry: status, conditions, conflicts) from the framework definition shown
     on the overview, which carries no per-project verdict. */
  function gateDetailNode(gt, evaluated) {
    var kids = [kv([
      [t("drawer.gateId"), el("span", { class: "mono", text: gt.id || "—" })],
      [t("drawer.gateName"), gt.name || "—"],
      [t("drawer.gateFlow"), el("span", { class: "mono",
        text: (gt.from_state || "?") + " → " + (gt.to_state || "?") })]
    ])];

    if (!evaluated) {
      kids.push(el("p", { class: "muted", style: "font-size:12px;margin-top:10px",
        text: t("drawer.gateNotEvaluated") }));
      return el("div", {}, kids);
    }

    var gstatus = get("status.value", gt);
    var eStatus = get("envelope_status.value", gt);
    kids.push(el("h3", { class: "drawer-sub", text: t("drawer.gateVerdict") }));
    kids.push(kv([
      [t("drawer.gateStatus"), gstatus ? statusChip(gstatus)
        : (eStatus ? el("span", { class: "status-chip status-UNKNOWN", text: eStatus + " · no evaluable" })
                   : statusChip("UNKNOWN"))],
      [t("drawer.gateHealth"), healthChip(gt.health || "UNKNOWN")]
    ]));

    var conds = (gt.conditions && gt.conditions.value) || [];
    kids.push(el("h3", { class: "drawer-sub", text: t("drawer.gateConditions") + " (" + conds.length + ")" }));
    kids.push(conds.length ? el("ul", { class: "list" }, conds.map(conditionNode))
                           : el("p", { class: "muted", text: t("drawer.noConditions") }));

    var conflicts = (gt.envelope_conflicts && gt.envelope_conflicts.value) || [];
    if (conflicts.length) {
      kids.push(el("h3", { class: "drawer-sub", text: t("drawer.gateConflicts") }));
      kids.push(bullets(conflicts));
    }
    kids.push(el("p", { class: "muted", style: "font-size:12px;margin-top:10px",
      text: t("drawer.gateHelper") }));
    return el("div", {}, kids);
  }

  function openGateDrawer(gt, evaluated, trigger) {
    openDrawer(t("drawer.gateTitle") + " · " + (gt.id || ""), gateDetailNode(gt, evaluated), trigger);
  }

  function openRecordDrawer(type, relPath, recs, trigger) {
    openDrawer(t("drawer.recordTitle") + " · " + type, el("div", { class: "drawer-explorer" }, [
      recordExplorer(relPath, recs, type),
      el("p", { class: "muted", style: "font-size:12px;margin-top:10px", text: t("drawer.recordHelper") })
    ]), trigger);
  }

  // ---------------------------------------------------------------- header
  function renderHeader(sys) {
    var id = (sys && sys.identity) || {};
    document.getElementById("hdr-system").textContent = (id.name && id.name.value) || "SYSTEM-ENGINEERING";
    document.getElementById("hdr-version").textContent = "v" + ((id.version && id.version.value) || "—");
    var h = (sys && sys.health) || {};
    var chip = document.getElementById("hdr-health");
    chip.className = "health-chip health-" + (h.state || "UNKNOWN");
    chip.querySelector(".chip-label").textContent = h.state || "UNKNOWN";
    chip.setAttribute("title", "se doctor: " + ((h.se_status && h.se_status.value) || "UNKNOWN"));

    document.getElementById("ft-root").textContent = (sys && sys.se_root) || "—";
    var t = (sys && sys.generated_at) || "";
    document.getElementById("ft-time").textContent = t.replace("T", " ").replace("Z", " UTC");
  }

  function renderFooterMeta() {
    api("/api/provenance").then(function (p) {
      var f = document.getElementById("ft-fp");
      f.textContent = (p.fingerprint || "—").slice(0, 16);
      f.setAttribute("title", p.fingerprint || "");
    }).catch(function () {
      document.getElementById("ft-fp").textContent = "UNKNOWN";
    });
  }

  // ------------------------------------------------------- screen: overview
  function viewOverview() {
    // The overview renders only /api/system. It does not show an attention
    // table, so it does not fetch one: no unused requests, no dead route.
    return api("/api/system").then(function (sys) {
      state.system = sys;
      renderHeader(sys);
      var g = el("div", { class: "grid" });

      // --- engine outage banner ---------------------------------------
      // If the engine cannot be invoked, say so at the top of every screen.
      // Everything below is then known to be UNKNOWN rather than absent, and
      // the operator learns why before reading a single number.
      var eng = (sys.health && sys.health.engine && sys.health.engine.value) || null;
      if (eng && eng.operational === false) {
        g.appendChild(el("div", { class: "col-12" }, [
          el("div", { class: "banner banner-BLOCKED", role: "status" }, [
            el("span", { class: "banner-tag", text: t("outage.tag") }),
            el("div", {}, [
              el("div", { class: "banner-title", text: t("outage.title") + (eng.reason || t("outage.unknownReason")) }),
              el("div", { class: "banner-sub", text: t("outage.sub") })
            ])
          ])
        ]));
      }

      // --- identity ---------------------------------------------------
      var idRows = [
        [t("identity.name"), val("identity.name", sys)],
        [t("identity.version"), val("identity.version", sys)],
        [t("identity.status"), val("identity.status", sys)],
        [t("identity.description"), el("p", { class: "prose", text: (fact("identity.description", sys).value) || "" })],
        [t("identity.schemaVersion"), val("identity.schema_version", sys)]
      ];
      var models = (fact("identity.models", sys).value) || {};
      if (Object.keys(models).length) {
        idRows.push([t("identity.models"), el("div", { class: "tag-row" },
          Object.keys(models).map(function (k) {
            return el("span", { class: "count-pill", title: k, text: models[k] });
          }))]);
      }
      g.appendChild(el("div", { class: "col-6" }, [
        panel(t("identity.title"), t("identity.sub"), [
          kv(idRows),
          el("p", { class: "muted", style: "margin-top:12px;font-size:12px" },
            t("identity.sourceNote"))
        ])
      ]));

      // --- health -----------------------------------------------------
      var h = sys.health || {};
      var by = (h.by_status && h.by_status.value) || {};
      var hero = el("div", { class: "hero" }, [
        el("div", { class: "hero-state hero-" + (h.state || "UNKNOWN").toLowerCase(), text: h.state || "UNKNOWN" }),
        el("div", { class: "hero-meta" }, [
          el("p", { class: "mono", text: (h.summary && h.summary.value) || "—" }),
          el("div", { class: "tag-row", style: "margin-top:6px" }, [
            epTag("OBSERVED", "se doctor"),
            el("span", { class: "muted", style: "font-size:12px", text: t("health.checkNote") })
          ])
        ])
      ]);
      var stats = el("div", { class: "stat-row", style: "margin-top:16px" }, [
        el("div", { class: "stat stat-pass" }, [el("div", { class: "stat-n", text: by.PASS || 0 }), el("div", { class: "stat-k", text: "PASS" })]),
        el("div", { class: "stat stat-warn" }, [el("div", { class: "stat-n", text: (by.WARN || 0) + (by.WARNING || 0) }), el("div", { class: "stat-k", text: "WARN" })]),
        el("div", { class: "stat stat-fail" }, [el("div", { class: "stat-n", text: by.FAIL || 0 }), el("div", { class: "stat-k", text: "FAIL" })])
      ]);
      var failing = (h.failing_checks && h.failing_checks.value) || [];
      var warning = (h.warning_checks && h.warning_checks.value) || [];
      g.appendChild(el("div", { class: "col-6" }, [
        panel(t("health.title"), t("health.sub"), [
          hero, stats,
          el("p", { class: "muted", style: "margin-top:10px;font-size:12px", text: t("health.explain") }),
          el("p", { class: "muted", style: "margin-top:6px;font-size:12px", text: t("health.evidenceNote") }),
          el("h3", { class: "panel-title", style: "margin:16px 0 8px;font-size:13px", text: t("health.focusTitle") }),
          list(warning.concat(failing), function (c) {
            return el("li", { class: "list-item" }, [
              el("div", { class: "li-main" }, [
                el("div", { class: "li-title", text: c.description || c.id }),
                el("div", { class: "li-sub", text: c.detail || "" })
              ]),
              statusChip(c.status)
            ]);
          })
        ])
      ]));

      // --- CMD-0016 availability ----------------------------------------
      // Declared-vs-invocable is reported as two separate facts. During the
      // SE-AUTOMATION-001C refactor CMD-0016 was declared and implemented
      // while the engine entrypoint was momentarily unrunnable; collapsing
      // those into one boolean would have hidden a real outage.
      var hc = sys.health_command || {};
      if (hc.command_id) {
        g.appendChild(el("div", { class: "col-4" }, [
          panel(t("healthCmd.title"), t("healthCmd.sub"), [
            kv([
              [t("healthCmd.declared"), (hc.declared || {}).value === true
                ? el("span", { class: "tag tag-OBSERVED", text: "si" })
                : el("span", { class: "tag tag-UNKNOWN", text: "no" })],
              [t("healthCmd.implemented"), (hc.implemented || {}).value === true
                ? el("span", { class: "tag tag-OBSERVED", text: "si" })
                : el("span", { class: "tag tag-UNKNOWN", text: "no" })],
              [t("healthCmd.invocable"), (hc.invocable || {}).value === true
                ? el("span", { class: "tag tag-OBSERVED", text: "si" })
                : el("span", { class: "tag tag-UNKNOWN", text: "no" })],
              [t("healthCmd.mutates"), hc.mutates && hc.mutates.value === false
                ? el("span", { class: "tag tag-OBSERVED", text: "no (mutates=false)" })
                : el("span", { class: "tag tag-UNKNOWN", text: "UNKNOWN" })],
              [t("healthCmd.note"), (hc.note || {}).value || "—"]
            ]),
            el("p", { class: "muted", style: "margin-top:10px;font-size:12px",
              text: t("healthCmd.helper") })
          ], "tight")
        ]));
      }

      // --- capabilities ------------------------------------------------
      var caps = sys.capabilities || {};
      var byAvail = (caps.by_availability && caps.by_availability.value) || {};
      var prov = (caps.providers && caps.providers.value) || [];
      g.appendChild(el("div", { class: "col-4" }, [
        panel(t("capabilities.title"), t("capabilities.sub"), [
          kv([
            [t("capabilities.state"), val("capabilities.health", caps)],
            [t("capabilities.available"), val("capabilities.available_count", caps)],
            [t("capabilities.providers"), el("span", { class: "count-pill", text: String(prov.length) })]
          ]),
          el("div", { class: "tag-row", style: "margin-top:12px" },
            Object.keys(byAvail).map(function (k) {
              return el("span", {
                class: "status-chip status-" + (k === "available" ? "PASS" : k === "unknown" ? "UNKNOWN" : k === "degraded" ? "WARN" : "FAIL"),
                text: k + ": " + byAvail[k]
              });
            })),
          el("p", { class: "muted", style: "margin-top:10px;font-size:12px", text: t("capabilities.explain") }),
          list(prov, function (p) {
            var d = el("li", { class: "list-item" }, [
              el("div", { class: "li-main" }, [
                el("div", { class: "li-title mono", text: p.provider }),
                el("div", { class: "li-sub", text: (p.capabilities || []).join(", ") })
              ]),
              statusChip(p.availability)
            ]);
            return d;
          }),
          el("div", { class: "callout", style: "margin-top:12px" },
            t("capabilities.callout"))
        ])
      ]));

      // --- inventory ---------------------------------------------------
      var inv = sys.inventory || {};
      var rows = (inv.alignment && inv.alignment.value) || [];
      g.appendChild(el("div", { class: "col-4" }, [
        panel(t("inventory.title"), t("inventory.sub"), [
          el("div", { class: "table-wrap" }, [
            el("table", { class: "table" }, [
              el("thead", {}, [el("tr", {}, [
                el("th", { text: t("inventory.item") }), el("th", { text: t("inventory.declared") }),
                el("th", { text: t("inventory.observed") }), el("th", { text: t("inventory.state") })
              ])]),
              el("tbody", {}, rows.map(function (r) {
                return el("tr", {}, [
                  el("td", { text: r.item }),
                  el("td", { class: "mono", text: r.declared === null ? "UNKNOWN" : r.declared }),
                  el("td", { class: "mono", text: r.observed }),
                  el("td", {}, [healthChip(r.state)])
                ]);
              }))
            ])
          ]),
          el("p", { class: "muted", style: "margin-top:10px;font-size:12px",
                    text: (inv.declared_statement && inv.declared_statement.value) || "" })
        ])
      ]));

      // --- gate ladder (framework) --------------------------------------
      var states = (sys.lifecycle_framework && sys.lifecycle_framework.states && sys.lifecycle_framework.states.value) || [];
      var gates = (sys.lifecycle_framework && sys.lifecycle_framework.gates && sys.lifecycle_framework.gates.value) || [];
      g.appendChild(el("div", { class: "col-4" }, [
        panel(t("lifecycle.title"), t("lifecycle.sub"), [
          el("p", { class: "mono muted", style: "font-size:12px;margin-bottom:8px",
                    text: t("lifecycle.statesLabel") + (Array.isArray(states) ? states.join(" -> ") : String(states)) }),
          el("div", { class: "gate-grid", style: "grid-template-columns:repeat(2,1fr)" },
            gates.map(function (gt) {
              var card = el("div", { class: "gate gate-UNKNOWN" }, [
                el("div", { class: "gate-head" }, [el("span", { class: "gate-id", text: gt.id })]),
                el("div", { class: "gate-name", text: gt.name || "" }),
                el("div", { class: "gate-flow", text: (gt.from_state || "?") + " -> " + (gt.to_state || "?") })
              ]);
              return clickable(card, function () {
                openGateDrawer(gt, false, card);
              }, t("drawer.openGate") + " " + gt.id);
            })),
          el("p", { class: "muted", style: "margin-top:10px;font-size:12px",
                    text: t("lifecycle.explain") })
        ])
      ]));

      // --- components ---------------------------------------------------
      var agents = (sys.agents && sys.agents.value) || [];
      var skills = (sys.skills && sys.skills.value) || [];
      var policies = (sys.policies && sys.policies.value) || [];
      var domains = (sys.domains && sys.domains.value) || [];
      g.appendChild(el("div", { class: "col-6" }, [
        panel(t("components.agentsTitle"),
          agents.length + " " + t("components.agentsCount") + " · " + skills.length + " " + t("components.skillsCount"), [
          el("div", { class: "table-wrap" }, [
            el("table", { class: "table" }, [
              el("thead", {}, [el("tr", {}, [
                el("th", { text: t("components.id") }), el("th", { text: t("components.role") }), el("th", { text: t("components.source") })
              ])]),
              el("tbody", {}, agents.map(function (a) {
                return el("tr", {}, [
                  el("td", { class: "mono", text: a.id }),
                  el("td", { text: a.role || a.description || "—" }),
                  el("td", { class: "mono", text: a.source || "" })
                ]);
              }))
            ])
          ]),
          el("h3", { class: "panel-title", style: "margin:16px 0 8px;font-size:13px", text: t("components.skillsTitle") }),
          bullets(skills.map(function (s) { return s.id + (s.description ? " — " + s.description : ""); }))
        ], "tight")
      ]));

      g.appendChild(el("div", { class: "col-6" }, [
        panel(t("components.policiesTitle"),
          policies.length + " " + t("components.policiesCount") + " · " + domains.length + " " + t("components.domainsCount"), [
          el("h3", { class: "panel-title", style: "margin-bottom:8px;font-size:13px", text: t("components.policiesHeading") }),
          el("div", { class: "tag-row" }, policies.map(function (p) {
            return el("span", { class: "count-pill", title: p.source, text: p.id });
          })),
          el("h3", { class: "panel-title", style: "margin:16px 0 8px;font-size:13px", text: t("components.domainsHeading") }),
          el("div", { class: "tag-row" }, domains.map(function (d) {
            return el("span", { class: "count-pill", title: d.source, text: d.id });
          })),
          el("h3", { class: "panel-title", style: "margin:16px 0 8px;font-size:13px", text: t("components.commandsHeading") }),
          el("div", { class: "tag-row" }, ((sys.command_surface && sys.command_surface.available.value) || [])
            .map(function (c) { return el("span", { class: "count-pill", text: c }); }))
        ], "tight")
      ]));

      return g;
    });
  }

  // ---------------------------------- friendly project summaries (T3)
  // Plain-language rollups for readers without a development background. They
  // never re-evaluate a gate or invent a verdict: they re-word the statuses and
  // counts the engine already returned, keeping contract literals verbatim.
  function fmt(tpl, vars) {
    return String(tpl).replace(/\{(\w+)\}/g, function (_m, k) {
      var v = vars ? vars[k] : undefined;
      return v === undefined || v === null || v === "" ? "—" : String(v);
    });
  }

  // One coloured chip per gate outcome. `status` drives the colour only; the
  // label carries the meaning in text.
  function outcomeChip(status, label) {
    return el("span", {
      class: "status-chip status-" + (status || "UNKNOWN"),
      text: label
    });
  }

  // Roll the already-fetched gate matrix into outcome counts (pass/warn/fail/
  // unknown). This counts what `se gate` returned; it evaluates nothing.
  function gateOutcomeCounts(d) {
    var matrix = (d.gates && d.gates.matrix && d.gates.matrix.value) || [];
    var passing = (d.gates && d.gates.passing) || [];
    var manual = (d.gates && d.gates.manual) || [];
    var failing = (d.gates && d.gates.failing) || [];
    var pass = passing.length, warn = manual.length, fail = failing.length;
    return {
      total: matrix.length, pass: pass, warn: warn, fail: fail,
      unknown: Math.max(0, matrix.length - pass - warn - fail)
    };
  }

  // One-line summary from a single evaluated gate (project list card).
  function gateSentence(gate, to) {
    var st = (gate && gate.status) || "UNKNOWN";
    var id = (gate && gate.id) || "";
    var g = String(st).toUpperCase();
    var tpl;
    if (g === "PASS" || g === "OK") tpl = to ? t("projects.gateOkTo") : t("projects.gateOk");
    else if (g === "FAIL" || g === "BLOCKED" || g === "ERROR" || g === "CRITICAL") {
      tpl = to ? t("projects.gateFailTo") : t("projects.gateFail");
    } else if (g === "WARN" || g === "WARNING" || g === "MANUAL" || g === "SKIP") {
      tpl = to ? t("projects.gateWarnTo") : t("projects.gateWarn");
    } else return t("projects.gateUnknown");
    if (!id) return t("projects.gateUnknown");
    return fmt(tpl, { gate: id, status: st, to: to });
  }

  // One-line summary from the whole-matrix outcome counts (detail hero).
  function countsSentence(counts) {
    if (!counts.total) return t("projects.gateUnknown");
    if (counts.fail > 0) return fmt(t("projects.countsFail"), counts);
    if (counts.warn > 0) return fmt(t("projects.countsWarn"), counts);
    if (counts.unknown > 0) return fmt(t("projects.countsUnknown"), counts);
    return fmt(t("projects.countsPass"), counts);
  }

  // Chips row + one plain sentence, shared by the list card and the hero.
  function projectSummaryLine(chips, sentence) {
    return el("div", { class: "proj-summary" }, [
      chips,
      el("p", { class: "proj-summary-line", text: sentence })
    ]);
  }

  function gateSummaryChips(counts) {
    var chips = el("div", { class: "tag-row" });
    chips.appendChild(outcomeChip("PASS", counts.pass + " PASS"));
    chips.appendChild(outcomeChip("WARN", counts.warn + " WARN"));
    chips.appendChild(outcomeChip("FAIL", counts.fail + " FAIL"));
    if (counts.unknown > 0) chips.appendChild(outcomeChip("UNKNOWN", counts.unknown + " UNKNOWN"));
    return chips;
  }

  // What unblocks the next transition, in plain Spanish (detail lifecycle
  // panel). Reuses the already-fetched gate matrix: only conditions the engine
  // itself marked FAIL or MANUAL on the transition's own gates are named.
  function nextTransitionSentence(nt, gates) {
    if (!nt || !nt.to) return t("detail.nextNone");
    var ids = nt.gates || [];
    var byId = {};
    (gates || []).forEach(function (g) { if (g && g.id) byId[g.id] = g; });
    var fails = [], manuals = [], seen = 0;
    ids.forEach(function (gid) {
      var g = byId[gid];
      if (!g) return;
      seen += 1;
      var conds = (g.conditions && g.conditions.value) || [];
      conds.forEach(function (c) {
        if (c.status === "FAIL") fails.push(c.id || gid);
        else if (c.status === "MANUAL") manuals.push(c.id || gid);
      });
    });
    var to = nt.to;
    if (fails.length) return fmt(t("detail.nextFail"), { to: to, conds: fails.join(", ") });
    if (manuals.length) return fmt(t("detail.nextManual"), { to: to, conds: manuals.join(", ") });
    if (seen === ids.length && ids.length) {
      return ids.length === 1
        ? fmt(t("detail.nextClearOne"), { gates: ids[0], to: to })
        : fmt(t("detail.nextClearMany"), { gates: ids.join(", "), to: to });
    }
    return fmt(t("detail.nextUnknown"), { gates: ids.join(", "), to: to });
  }

  // ------------------------------------------------------- screen: projects
  function viewProjects() {
    return api("/api/projects").then(function (pj) {
      state.projects = pj;
      var wrap = el("div");
      wrap.appendChild(el("h2", { class: "section-title", text: t("projects.title") }));
      wrap.appendChild(el("p", { class: "muted", style: "font-size:12px;margin-bottom:4px",
        text: t("projects.explain") }));
      wrap.appendChild(el("p", { class: "muted", style: "font-size:12px;margin-bottom:16px",
        text: pj.managed + " " + t("projects.managedCount") + " · " + pj.unmanaged + " " +
              t("projects.unmanagedCount") + " " + t("projects.location") + " " + t("projects.honesty") }));

      var grid = el("div", { class: "proj-grid" });
      (pj.projects || []).forEach(function (p) {
        var card = el("button", {
          type: "button", class: "proj-card", "data-rel": p.rel_path,
          onclick: function () { openProject(p.rel_path); }
        }, [
          el("div", { class: "proj-head" }, [
            el("div", {}, [
              el("div", { class: "proj-name", text: p.name || p.dir_name }),
              el("div", { class: "proj-id", text: p.project_id || p.rel_path })
            ]),
            p.management === "MANAGED" ? healthChip(p.health) : el("span", { class: "tag tag-UNKNOWN", text: "UNKNOWN" })
          ]),
          p.reason ? el("p", { class: "muted", style: "font-size:12px", text: p.reason }) : null,
          el("div", { class: "proj-summary" }, projectCardBody(p))
        ]);
        grid.appendChild(card);
      });
      wrap.appendChild(grid);
      return wrap;
    });

    // Build the body of a project card: chips + plain-language summary + next step hint.
    function projectCardBody(p) {
      var chips = el("div", { class: "counts" });
      var lines = [];
      if (p.management === "MANAGED") {
        chips.appendChild(el("span", { class: "count-pill", text: t("projects.lifecycle") + (((p.lifecycle || {}).value) || "UNKNOWN") }));
        var gate = ((p.gate || {}).value) || {};
        var gst = gate.status || "UNKNOWN";
        chips.appendChild(outcomeChip(gst, gate.id ? gate.id + " " + gst : gst));
        var nt = ((p.next_transition || {}).value);
        lines.push(el("p", { class: "proj-summary-line",
          text: gateSentence(gate, nt && nt.to) }));
        // Next step in plain language
        var nextHtml = nextStepHint(nt, gate);
        if (nextHtml) lines.push(el("p", { class: "proj-next-step", style: "font-size:12px;color:var(--muted);margin-top:6px", html: nextHtml }));
      } else {
        chips.appendChild(el("span", { class: "tag tag-UNKNOWN", text: "UNMANAGED" }));
        lines.push(el("p", { class: "proj-summary-line", text: t("projects.unmanagedExplain") }));
      }
      return el("div", {}, [chips].concat(lines));
    }

    // Plain-language "what to do next" hint for a project card.
    function nextStepHint(nt, gate) {
      if (!nt || !nt.to) return null;
      var gst = (gate && gate.status) || "UNKNOWN";
      var to = nt.to;
      var gates = (nt.gates || []).join(", ");
      var es = {
        blocked: "<strong>Bloqueado</strong> El proyecto no puede avanzar hacia <strong>" + to + "</strong> hasta resolver el gate <strong>" + gates + "</strong>. Vea la pestaña Atención para ver los pasos.",
        warning: "<strong>Revisar antes de avanzar</strong> El gate <strong>" + gates + "</strong> tiene condiciones pendientes. Revíselas en Atención antes de avanzar hacia <strong>" + to + "</strong>.",
        ready: "<strong>Listo para avanzar</strong> El gate <strong>" + gates + "</strong> ya pasa. El proyecto puede avanzar hacia <strong>" + to + "</strong>."
      };
      var en = {
        blocked: "<strong>Blocked</strong> The project cannot advance to <strong>" + to + "</strong> until gate <strong>" + gates + "</strong> is resolved. See Attention for the steps.",
        warning: "<strong>Review before advancing</strong> Gate <strong>" + gates + "</strong> has pending conditions. Review them in Attention before advancing to <strong>" + to + "</strong>.",
        ready: "<strong>Ready to advance</strong> Gate <strong>" + gates + "</strong> already passes. The project can advance to <strong>" + to + "</strong>."
      };
      var dict = currentLang === "en" ? en : es;
      if (gst === "FAIL" || gst === "BLOCKED") return dict.blocked;
      if (gst === "WARN" || gst === "WARNING" || gst === "MANUAL") return dict.warning;
      if (gst === "PASS") return dict.ready;
      return null;
    }
  }

  function openProject(rel) {
    state.view = "project";
    state.project = rel;
    root.innerHTML = "";
    root.appendChild(el("p", { class: "loading", text: "Consultando se gate, se review y se context…" }));
    api("/api/project?rel_path=" + encodeURIComponent(rel)).then(function (d) {
      state.projectData = d;
      root.innerHTML = "";
      root.appendChild(renderProjectDetail(d));
    }).catch(function (e) {
      root.innerHTML = "";
      root.appendChild(el("p", { class: "notice notice-error", text: "No se pudo cargar " + rel + ": " + e.message }));
    });
  }

  function renderProjectDetail(d) {
    var wrap = el("div");
    wrap.appendChild(el("div", { class: "breadcrumb" }, [
      el("button", { type: "button", class: "crumb-btn", text: t("projects.title"), onclick: function () { go("projects"); } }),
      el("span", { class: "muted", text: "/" }),
      el("span", { class: "mono", text: d.rel_path })
    ]));

    /* Unmanaged projects must be announced, not rendered as a page of blanks:
       the engine refuses to evaluate gates, and the reason is explicit. */
    var mgmt = (d.management || {}).value;
    if (mgmt && mgmt !== "MANAGED") {
      var conflicts = ((d.engine_conflicts || {}).value) || [];
      wrap.appendChild(el("div", { class: "panel", style: "margin-bottom:20px;border-color:var(--H-BLOCKED)" }, [
        el("div", { class: "panel-head", style: "background:var(--H-BLOCKED-bg)" }, [
          el("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" }, [
            el("span", { class: "status-chip status-FAIL", text: mgmt }),
            el("strong", { text: t("detail.unmanagedStrong") })
          ])
        ]),
        el("div", { class: "panel-body" }, [
          el("p", { class: "prose", text: (d.management_reason || {}).value || "" }),
          el("p", { class: "prose", style: "margin-top:8px",
            text: "El motor se niega a evaluar gates y lifecycle sin PROJECT.json. Todo lo de abajo se muestra como UNKNOWN por honestidad, no porque falte información: la información que falta es precisamente el manifest del proyecto." }),
          el("p", { class: "muted", style: "margin-top:10px;font-size:12px", text: t("detail.unmanagedExplain") }),
          conflicts.length ? el("div", { style: "margin-top:12px" }, [
            el("h3", { class: "panel-title", style: "font-size:13px;margin-bottom:6px", text: t("detail.unmanagedConflicts") }),
            bullets(conflicts)
          ]) : null,
          el("p", { class: "muted", style: "margin-top:12px;font-size:12px",
            text: t("detail.unmanagedReadonly") })
        ])
      ]));
    }

    var ident = d.identity || {};
    var lc = d.lifecycle || {};
    var gcounts = gateOutcomeCounts(d);
    wrap.appendChild(el("div", { class: "hero", style: "margin-bottom:20px" }, [
      el("div", { class: "hero-state hero-" + String(lc.health || "UNKNOWN").toLowerCase(),
                  text: (lc.state && lc.state.value) || "UNKNOWN" }),
      el("div", { class: "hero-meta" }, [
        el("h2", { style: "font-size:20px", text: (ident.value && ident.value.name) || d.rel_path }),
        el("p", { class: "muted", style: "font-size:12px",
                  text: (ident.value && ident.value.project_id ? ident.value.project_id + " · " : "") +
                        t("detail.owner") + ((ident.value && ident.value.owner) || "UNKNOWN") }),
        el("div", { class: "tag-row", style: "margin-top:6px" }, [epTag("OBSERVED", "se context")]),
        projectSummaryLine(gateSummaryChips(gcounts), countsSentence(gcounts))
      ])
    ]));

    var g = el("div", { class: "grid" });

    // --- gate matrix -------------------------------------------------
    var gates = (d.gates && d.gates.matrix && d.gates.matrix.value) || [];
    g.appendChild(el("div", { class: "col-12" }, [
      panel(t("detail.gateMatrixTitle"), t("detail.gateMatrixSub"), [
        el("div", { class: "gate-grid" }, gates.map(function (gt) {
          var gstatus = (gt.status || {}).value;
          var eStatus = (gt.envelope_status || {}).value;
          var conflicts = (gt.envelope_conflicts || {}).value || [];
          var card = el("div", { class: "gate gate-" + gt.health }, [
            el("div", { class: "gate-head" }, [
              el("span", { class: "gate-id", text: gt.id }),
              gstatus ? statusChip(gstatus)
                      : (eStatus ? el("span", {
                          class: "status-chip status-" + (eStatus === "FAIL" ? "FAIL" : "UNKNOWN"),
                          text: eStatus + " · no evaluable"
                        }) : statusChip("UNKNOWN"))
            ]),
            el("div", { class: "gate-name", text: gt.name || "" }),
            el("div", { class: "gate-flow", text: (gt.from_state || "?") + " -> " + (gt.to_state || "?") }),
            conflicts.length
              ? el("div", { class: "li-sub", style: "margin-top:6px;color:var(--H-BLOCKED)",
                            text: conflicts.join("; ") })
              : null,
            el("div", { class: "conds" }, (gt.conditions && gt.conditions.value || []).map(function (c) {
              return el("span", { class: "cond cond-" + c.status, text: c.id + " " + c.status });
            }))
          ]);
          return clickable(card, function () {
            openGateDrawer(gt, true, card);
          }, t("drawer.openGate") + " " + gt.id);
        })),
        el("p", { class: "muted", style: "margin-top:12px;font-size:12px",
                  text: t("detail.gateManualNote") })
      ])
    ]));

    // --- lifecycle + next transition ---------------------------------
    var nt = (lc.next_transition || {}).value;
    g.appendChild(el("div", { class: "col-4" }, [
      panel(t("detail.lifecycleTitle"), t("detail.lifecycleSub"), [
        kv([
          [t("detail.lcState"), val("lifecycle.state", d)],
          [t("detail.lcNext"), nt && nt.to
            ? el("span", {}, [document.createTextNode(nt.to + " vía " + (nt.gates || []).join(", ")), document.createTextNode(" "), epTag("OBSERVED", "se context")])
            : val("lifecycle.next_transition", d)],
          [t("detail.lcDeclared"), (lc.declared_transitions.value || []).length],
          [t("detail.lcMigrations"), (lc.migrations.value || []).length]
        ]),
        el("p", { class: "prose", style: "margin-top:8px;font-size:13px",
                  text: nextTransitionSentence(nt, gates) }),
        el("p", { class: "muted", style: "margin-top:6px;font-size:12px", text: t("detail.nextExplain") })
      ])
    ]));

    // --- CMD-0016 se health ------------------------------------------
    // The engine's own aggregate health envelope, relayed verbatim. The
    // console shows the engine's status and the raw envelope side by side so
    // nobody has to take the console's word for it.
    var sh = d.se_health || {};
    var shStatus = (sh.status || {}).value;
    g.appendChild(el("div", { class: "col-4" }, [
      panel(t("detail.healthTitle"), t("detail.healthSub"), [
        kv([
          [t("detail.healthState"), statusChip(shStatus || "UNKNOWN")],
          [t("detail.healthPresent"), (sh.health || {}).value
            ? healthChip((sh.health || {}).value, (sh.health || {}).value)
            : el("span", { class: "tag tag-UNKNOWN", text: "UNKNOWN" })],
          [t("detail.healthAvailable"), (sh.available || {}).value === true
            ? el("span", { class: "tag tag-OBSERVED", text: "si" })
            : el("span", { class: "tag tag-UNKNOWN", text: "no" })],
          [t("detail.healthReason"), (sh.reason || {}).value || "—"]
        ]),
        el("div", { class: "tag-row", style: "margin-top:10px" }, [
          epTag("OBSERVED", "se health"),
          el("span", { class: "muted", style: "font-size:12px",
            text: t("detail.healthHelper") })
        ]),
        (sh.envelope || {}).value
          ? raw(sh.envelope.value, t("detail.healthRawLabel"))
          : el("p", { class: "muted", style: "font-size:12px",
              text: t("detail.healthNoEnvelope") })
      ], "tight")
    ]));

    // --- manifest + discovery ----------------------------------------
    var mf = d.manifest || {};
    var disc = d.discovery || {};
    g.appendChild(el("div", { class: "col-4" }, [
      panel(t("detail.manifestTitle"), t("detail.manifestSub"), [
        kv([
          [t("detail.manifestSchema"), mf.schema_valid ? (mf.schema_valid.value ? el("span", { class: "tag tag-DERIVED", text: "VALID" }) : el("span", { class: "tag tag-UNKNOWN", text: "INVALID" })) : val("manifest.schema_valid", d)],
          ["sha256", el("span", { class: "mono", text: ((mf.sha256 || {}).value || "—").slice(0, 24) })],
          ["project_id", ((mf.data || {}).value || {}).project_id || "—"],
          ["version", ((mf.data || {}).value || {}).version || "—"]
        ]),
        ((mf.schema_errors || {}).value || []).length
          ? el("div", { class: "callout", style: "margin-top:10px" },
              "Errores de schema: " + mf.schema_errors.value.join("; "))
          : null
      ])
    ]));

    var dcounts = (disc.counts || {}).value || {};
    g.appendChild(el("div", { class: "col-4" }, [
      panel(t("detail.discoveryTitle"), t("detail.discoverySub"), [
        el("p", { class: "prose", style: "font-size:13px;margin-bottom:10px",
                  text: (disc.summary || {}).value || t("detail.discoveryNoSummary") }),
        kv([
          [t("detail.discoveryFindings"), dcounts.findings], [t("detail.discoveryUnknowns"), dcounts.unknowns],
          [t("detail.discoveryAssumptions"), dcounts.assumptions], [t("detail.discoveryConstraints"), dcounts.constraints],
          [t("detail.discoveryRisks"), dcounts.risks],
          [t("detail.discoveryReviewed"), val("discovery.reviewed_by", d)]
        ]),
        el("p", { class: "muted", style: "margin-top:10px;font-size:12px",
                  text: t("detail.discoveryHelper") })
      ])
    ]));

    // --- records -----------------------------------------------------
    var recs = (d.records || {}).value || {};
    g.appendChild(el("div", { class: "col-6" }, [
      panel(t("records.title"), t("records.sub"), [
        el("div", { class: "table-wrap" }, [
          el("table", { class: "table" }, [
            el("thead", {}, [el("tr", {}, [
              el("th", { text: t("records.colType") }), el("th", { text: t("records.colDisk") }),
              el("th", { text: t("records.colReview") }), el("th", { text: t("records.colInvalid") })
            ])]),
            el("tbody", {}, Object.keys(recs).map(function (t) {
              var row = recs[t];
              var rc = (d.traceability.review_counts.value || {})[t];
              var tr = el("tr", {}, [
                el("td", { class: "mono", text: t }),
                el("td", { class: "mono", text: row.absent ? "UNKNOWN" : row.count }),
                el("td", { class: "mono", text: rc === undefined ? "UNKNOWN" : rc }),
                el("td", {}, [row.invalid_count
                  ? el("span", { class: "tag tag-UNKNOWN", text: String(row.invalid_count) })
                  : el("span", { class: "tag tag-DERIVED", text: "0" })])
              ]);
              return clickable(tr, function () {
                openRecordDrawer(t, d.rel_path, recs, tr);
              }, t("drawer.openRecord") + " " + t);
            }))
          ])
        ]),
        el("p", { class: "muted", style: "margin-top:10px;font-size:12px", text: t("records.explain") }),
        el("p", { class: "muted", style: "margin-top:6px;font-size:12px", text: t("records.helper") })
      ], "tight")
    ]));

    // --- record drill-down (GET /api/record, read-only) ------------------
    g.appendChild(el("div", { class: "col-12" }, [
      panel(t("records.explorerTitle"), t("records.explorerSub"), [
        recordExplorer(d.rel_path, recs),
        el("p", { class: "muted", style: "margin-top:10px;font-size:12px",
          text: t("records.explorerHelper") })
      ], "tight")
    ]));

    // --- traceability + integrity -----------------------------------
    var chain = (d.traceability.chain || {}).value || [];
    var integ = d.integrity || {};
    g.appendChild(el("div", { class: "col-6" }, [
      panel(t("trace.title"), t("trace.sub"), [
        el("div", { class: "chain", style: "margin-bottom:14px" }, chain.map(function (c) {
          var n = (c.count || {}).value || 0;
          return el("div", { class: "chain-node" + (n === 0 ? " is-zero" : "") }, [
            el("div", { class: "chain-n", text: n }),
            el("div", { class: "chain-k", text: c.type })
          ]);
        })),
        el("h3", { class: "panel-title", style: "font-size:13px;margin-bottom:8px", text: t("trace.gaps") }),
        bullets((integ.gaps || {}).value || []),
        el("h3", { class: "panel-title", style: "font-size:13px;margin:12px 0 8px", text: t("trace.links") }),
        bullets((integ.link_notes || {}).value || []),
        el("div", { class: "tag-row", style: "margin-top:12px" }, [
          statusChip((integ.review_status || {}).value),
          epTag("OBSERVED", "se review")
        ])
      ], "tight")
    ]));

    // --- AUTO-02 context ---------------------------------------------
    var cx = d.context || {};
    var idc = (cx.identity_scope || {}).value || {};
    var dpc = (cx.deep_scope || {}).value || {};
    g.appendChild(el("div", { class: "col-6" }, [
      panel(t("context.title"), t("context.sub"), [
        kv([
          ["scope identity", statusChip(idc.status)],
          ["epistemic", (idc.epistemic || {}).state || "UNKNOWN"],
          ["next_action", idc.next_action && idc.next_action.kind
            ? idc.next_action.kind + (idc.next_action.target ? " -> " + idc.next_action.target : "")
            : "UNKNOWN"]
        ]),
        el("h3", { class: "panel-title", style: "font-size:13px;margin:14px 0 8px", text: t("context.deepTitle") }),
        el("p", { class: "muted", style: "font-size:12px;margin-bottom:8px",
                  text: t("context.deepHelper") }),
        kv([["estado", statusChip(dpc.status)]].concat(
          Object.keys(dpc.counts || {}).map(function (k) { return [k, dpc.counts[k]]; }))),
        el("p", { class: "muted", style: "margin-top:10px;font-size:12px",
                  text: t("context.deepNote") })
      ], "tight")
    ]));

    // --- mutation log -------------------------------------------------
    var ml = d.mutation_log || {};
    var entries = (ml.entries || {}).value || [];
    g.appendChild(el("div", { class: "col-6" }, [
      panel(t("audit.title"), (entries.length || 0) + " " + t("audit.entries"), [
        entries.length ? el("div", { class: "table-wrap", style: "max-height:280px;overflow-y:auto" }, [
          el("table", { class: "table" }, [
            el("thead", {}, [el("tr", {}, [
              el("th", { text: t("audit.colSeq") }), el("th", { text: t("audit.colRecord") }),
              el("th", { text: t("audit.colField") }), el("th", { text: t("audit.colValue") })
            ])]),
            el("tbody", {}, entries.slice(-40).map(function (e) {
              return el("tr", {}, [
                el("td", { class: "mono", text: e.seq }),
                el("td", { class: "mono", text: (e.record_type || "") + " " + (e.record_id || "") }),
                el("td", { class: "mono", text: (e.changes[0] || {}).field || "" }),
                el("td", { class: "mono", text: String((e.changes[0] || {}).value_raw || "") })
              ]);
            }))
          ])
        ]) : el("p", { class: "empty", text: t("audit.empty") }),
        el("p", { class: "muted", style: "margin-top:10px;font-size:12px",
                  text: t("audit.helper") })
      ], "tight")
    ]));

    wrap.appendChild(g);

    // --- attention for this project -----------------------------------
    var att = d.attention || {};
    wrap.appendChild(el("h2", { class: "section-title", text: t("attention.projectTitle") }));
    wrap.appendChild(el("p", { class: "muted", style: "margin-bottom:12px",
      text: (att.counts.BLOCKED || 0) + " BLOCKED · " + (att.counts.WARNING || 0) + " WARNING · " +
            t("attention.orderNote") + "." }));
    wrap.appendChild(renderAttentionTable(att));
    return wrap;
  }

  // ------------------------------------------------------ screen: attention
  function renderAttentionTable(att) {
    var items = (att && att.items) || [];
    if (!items.length) return el("p", { class: "empty", text: t("attention.empty") });
    var t = el("table", { class: "table" }, [
      el("thead", {}, [el("tr", {}, [
        el("th", { text: t("attention.severity") }), el("th", { text: t("attention.area") }),
        el("th", { text: t("attention.what_happens") }), el("th", { text: t("attention.what_to_do") }),
        el("th", { text: t("attention.evidence") }), el("th", { text: t("attention.actions") })
      ])]),
      el("tbody", {}, items.map(function (i) {
        var actionsTd = el("td");
        if (i.actions && i.actions.length) {
          i.actions.forEach(function (aid) {
            actionsTd.appendChild(el("button", {
              type: "button", class: "btn btn-small", text: labelForAction(aid),
              onclick: function (e) {
                e.stopPropagation();
                var projRel = state.project || i._project;
                executeAction(aid, i, projRel);
              }
            }));
            actionsTd.appendChild(document.createTextNode(" "));
          });
        } else {
          actionsTd.appendChild(el("span", { class: "muted", text: "—" }));
        }
        // Plain-language explanation of what this item means
        var explain = attentionExplain(i);
        // Clickable row: opens a drawer with steps to follow
        var row = el("tr", { class: "attn-row", "data-severity": i.severity }, [
          el("td", {}, [el("span", { class: "status-chip status-" + (i.severity === "BLOCKED" ? "FAIL" : "WARN"), text: i.severity })]),
          el("td", { class: "mono", text: i.area }),
          el("td", {}, [
            el("div", { class: "attn-title", text: i.title }),
            el("div", { class: "attn-detail", text: i.detail })
          ]),
          el("td", {}, [el("div", { class: "attn-explain", text: explain })]),
          el("td", { class: "mono", text: i.evidence }),
          actionsTd
        ]);
        return clickable(row, function () { openAttentionDrawer(i); }, t("attention.view_details"));
      }))
    ]);
    return el("div", { class: "panel" }, [el("div", { class: "panel-body tight" }, [
      el("div", { class: "table-wrap" }, [t])
    ])]);
  }

  // Plain-language explanation of what an attention item means and what to do.
  function attentionExplain(i) {
    var sev = i.severity;
    var es = {
      BLOCKED: "Este elemento está bloqueado. No se puede avanzar hasta resolverlo.",
      WARNING: "Este elemento tiene una advertencia. Revíselo pronto; no detiene el proyecto por sí solo.",
      INFO: "Información para revisar."
    };
    var en = {
      BLOCKED: "This item is blocked. It cannot be advanced until resolved.",
      WARNING: "This item has a warning. Review it soon; it does not block the project by itself.",
      INFO: "Information to review."
    };
    var dict = currentLang === "en" ? en : es;
    return dict[sev] || dict.INFO;
  }

  // Drawer with steps to follow for an attention item.
  function openAttentionDrawer(item) {
    var kids = [];
    kids.push(el("h3", { class: "drawer-sub", text: item.title }));
    kids.push(el("p", { class: "prose", text: item.detail || "" }));
    kids.push(el("h3", { class: "drawer-sub", text: currentLang === "en" ? "Steps to follow" : "Pasos a seguir" }));
    var steps = attentionSteps(item);
    if (steps.length) {
      kids.push(el("ol", { class: "list" }, steps.map(function (s) {
        return el("li", { class: "list-item" }, [el("div", { class: "li-main", text: s })]);
      })));
    } else {
      kids.push(el("p", { class: "muted", text: currentLang === "en" ? "No specific steps defined yet." : "No hay pasos específicos definidos todavía." }));
    }
    kids.push(el("h3", { class: "drawer-sub", text: currentLang === "en" ? "Where it belongs" : "A qué pertenece" }));
    kids.push(el("p", { class: "prose", text: (item.area || "—") + " · " + (item.evidence || "sin evidencia") }));
    if (item.actions && item.actions.length) {
      kids.push(el("h3", { class: "drawer-sub", text: currentLang === "en" ? "Actions available" : "Acciones disponibles" }));
      item.actions.forEach(function (aid) {
        kids.push(el("button", {
          type: "button", class: "btn btn-small", text: labelForAction(aid),
          onclick: function () {
            closeDrawer();
            var projRel = state.project || item._project;
            executeAction(aid, item, projRel);
          }
        }));
        kids.push(document.createTextNode(" "));
      });
    }
    openDrawer(currentLang === "en" ? "View details" : "Ver detalles", el("div", {}, kids), null);
  }

  // Suggested steps for an attention item, based on its content.
  function attentionSteps(item) {
    var steps = [];
    var detail = (item.detail || "").toLowerCase();
    var title = (item.title || "").toLowerCase();
    var area = (item.area || "").toLowerCase();
    var es = {
      receipt: "Registre la evidencia de ejecución (receipt) de la tarea.",
      artifact: "Revise y corrija el archivo del artefacto indicado.",
      gate: "Revise las condiciones del gate y resuelva las que fallen.",
      evidence: "Aporte la evidencia faltante para el registro indicado.",
      acceptance: "Complete la evidencia de aceptación de usuario (UAT).",
      release: "Publique el release y vincúlelo a la evidencia.",
      operations: "Cree el documento de operaciones (docs/operations.md).",
      generic: "Revise el detalle del elemento y resuelva lo que corresponda."
    };
    var en = {
      receipt: "Register the execution evidence (receipt) for the task.",
      artifact: "Review and fix the indicated artifact file.",
      gate: "Review the gate conditions and resolve the failing ones.",
      evidence: "Provide the missing evidence for the indicated record.",
      acceptance: "Complete the user acceptance evidence (UAT).",
      release: "Publish the release and link it to the evidence.",
      operations: "Create the operations document (docs/operations.md).",
      generic: "Review the item detail and resolve what applies."
    };
    var dict = currentLang === "en" ? en : es;
    if (detail.includes("receipt") || title.includes("receipt")) steps.push(dict.receipt);
    if (detail.includes("artifact") || title.includes("artifact")) steps.push(dict.artifact);
    if (detail.includes("gate") || area.includes("gate")) steps.push(dict.gate);
    if (detail.includes("evidence") || title.includes("evidence")) steps.push(dict.evidence);
    if (detail.includes("acceptance") || title.includes("acceptance")) steps.push(dict.acceptance);
    if (detail.includes("release") || title.includes("release")) steps.push(dict.release);
    if (detail.includes("operations") || detail.includes("operations.md")) steps.push(dict.operations);
    if (steps.length === 0) steps.push(dict.generic);
    return steps;
  }

  function viewAttention() {
    return Promise.all([api("/api/system"), api("/api/projects")]).then(function (res) {
      renderHeader(res[0]);
      var wrap = el("div");
      wrap.appendChild(el("h2", { class: "section-title", text: t("attention.title") }));
      wrap.appendChild(el("p", { class: "muted", style: "margin-bottom:16px",
        text: t("attention.intro") }));
      // aggregate per project
      var jobs = (res[1].projects || []).filter(function (p) { return p.management === "MANAGED"; })
        .map(function (p) {
          return api("/api/project?rel_path=" + encodeURIComponent(p.rel_path)).then(function (d) {
            return { name: p.dir_name, rel_path: p.rel_path, attention: d.attention };
          });
        });
      return Promise.all(jobs).then(function (rows) {
        var all = [];
        rows.forEach(function (r) {
          (r.attention.items || []).forEach(function (i) { var it = Object.assign({}, i); it._project = r.rel_path; all.push(it); });
        });
        all.sort(function (a, b) {
          var o = { BLOCKED: 0, WARNING: 1, UNKNOWN: 2, INFO: 3 };
          return (o[a.severity] || 9) - (o[b.severity] || 9);
        });
        wrap.appendChild(el("div", { class: "stat-row", style: "margin-bottom:16px" }, [
          el("div", { class: "stat stat-fail" }, [el("div", { class: "stat-n", text: all.filter(function (i) { return i.severity === "BLOCKED"; }).length }), el("div", { class: "stat-k", text: "BLOCKED" })]),
          el("div", { class: "stat stat-warn" }, [el("div", { class: "stat-n", text: all.filter(function (i) { return i.severity === "WARNING"; }).length }), el("div", { class: "stat-k", text: "WARNING" })]),
          el("div", { class: "stat" }, [el("div", { class: "stat-n", text: all.length }), el("div", { class: "stat-k", text: t("attention.total") })])
        ]));
        wrap.appendChild(renderAttentionTable({ items: all }));
        return wrap;
      });
    });
  }

  // ---------------------------------------------------------------- router
  function go(view) {
    state.view = view;
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) {
      var on = t.getAttribute("data-view") === view;
      t.classList.toggle("is-active", on);
      if (on) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
    });
    root.innerHTML = "";
    root.appendChild(el("p", { class: "loading", text: "Cargando…" }));
    var p;
    if (view === "projects") p = viewProjects();
    else if (view === "attention") p = viewAttention();
    else p = viewOverview();
    p.then(function (node) {
      root.innerHTML = "";
      root.appendChild(node);
    }).catch(function (e) {
      // Log the real cause: a rendering bug must not be able to hide behind a
      // friendly message, otherwise it is invisible to both user and evidence.
      if (window.console && console.error) console.error("se-console render failed:", e);
      root.innerHTML = "";
      root.appendChild(el("p", { class: "notice notice-error" }, [
        el("strong", { text: "Error de consola: " }),
        el("span", { class: "mono", text: e && e.message ? e.message : String(e) }),
        el("br"),
        el("span", { text: "El backend puede no estar disponible. Detalle en la consola del navegador." })
      ]));
    });
  }

  // ---------------------------------------------------------------- theme
  var THEMES = ["magenta", "azul", "claro"];
  var THEME_ALIASES = { dark: "magenta", light: "claro" };   // legacy saved values
  function normalizeTheme(saved) {
    if (saved && THEME_ALIASES[saved]) saved = THEME_ALIASES[saved];
    return (saved && THEMES.indexOf(saved) !== -1) ? saved : "magenta";
  }
  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("se-console-theme"); } catch (e) {}
    var theme = normalizeTheme(saved);
    document.documentElement.setAttribute("data-theme", theme);
    var sel = document.getElementById("sel-theme");
    if (sel) sel.value = theme;
  }
  function setTheme(next) {
    if (THEMES.indexOf(next) === -1) return;
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("se-console-theme", next); } catch (e) {}
  }

  // ---------------------------------------------------------------- init token ui
  function initTokenUI() {
    var inp = document.getElementById("inp-token");
    var btn = document.getElementById("btn-save-token");
    if (inp) {
      try { inp.value = sessionStorage.getItem("se-console-token") || ""; } catch (e) {}
    }
    if (btn) {
      btn.addEventListener("click", function () {
        setToken((document.getElementById("inp-token") && document.getElementById("inp-token").value) || "");
        alert("Token guardado en sessionStorage");
      });
    }
  }


  // ---------------------------------------------------------------- boot
  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) {
      t.addEventListener("click", function () { go(t.getAttribute("data-view")); });
    });
    document.getElementById("sel-theme").addEventListener("change", function () {
      setTheme(this.value);
    });
    document.getElementById("sel-lang").addEventListener("change", function () {
      setLang(this.value);
    });
    initLang();
    var btn = document.getElementById("btn-refresh");
    btn.addEventListener("click", function () {
      btn.classList.add("is-busy");
      go(state.view === "project" ? "overview" : state.view);
      setTimeout(function () { btn.classList.remove("is-busy"); }, 400);
    });
    go("overview");
    initTokenUI();
    renderFooterMeta();
    startHeartbeat();
  });
})();
