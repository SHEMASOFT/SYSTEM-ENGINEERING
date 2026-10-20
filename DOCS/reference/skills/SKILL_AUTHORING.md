# Skill Authoring (skills.auth) — ENABLE-1 (ARCH-ECOSYSTEM-002, F2)

Guía para **autores** de nuevas skills del Master System. Define el contrato que
toda skill canónica debe cumplir para ser instalable viab el adapter de OpenCode y
para aportar una capability gobernada (CP-020) sin tocar CORE.

> Complementa: `ARCH-ECOSYSTEM-002-01-DECISION.md` (§I Skills), `SCHEMAS/skill-contract
> .schema.json`, `TESTS/test_skills.py`, `DOCS/reference/governance/CAPABILITY_GOVERNANCE.md` y
> `DOCS/reference/opencode-adapter.md`.

## 1. Estructura y ciclo de vida

```
SKILLS/<skill-name>/
  SKILL.md     <- cuerpo documental (frontmatter + secciones REQUIRED_SECTIONS)
  SKILL.json   <- sidecar de contrato (skill-contract schema)
```

| Paso | Qué se hace | Verificación |
|---|---|---|
| 1 | Reservar / confirmar Skill ID (SK-000x) sin colisiones | grep `SK-00`; registry de IDs; auditoría |
| 2 | Redactar `SKILL.md` con el frontmatter y las 11 secciones | `validate_skill` + REQUIRED_SECTIONS |
| 3 | Declarar el contrato en `SKILL.json` (capabilities del registry, nunca providers) | schema `skill_contract` + `se capabilities --check` |
| 4 | Añadir la skill a `CANONICAL_SKILLS` en `TESTS/test_skills.py` | `test_skills` verde |
| 5 | Regenerar el adapter (`.opencode`) | `se adapter opencode` → idempotente (Wrote 0 en re-ejecución) |
| 6 | Validar e integrar | `se validate`, `se doctor`, suite completa |

> Nota: `skill_catalog_install` copia solo `SKILL.md` y `SKILL.json` del origen; los demás archivos no se instalan.

## 2. Frontmatter (SKILL.md)

| Campo | Regla |
|---|---|
| `name` | Debe ser igual al folder (`validate_skill`; falla si no coincide). |
| `description` | Obligatoria (OpenCode filtra skills sin description). Una oración *when to use*. |
| `metadata` | Obligatoria (contrato SE): `system: system-engineering`, `schema_version: "1"`, `adapter: opencode`. |

Secciones obligatorias del cuerpo (`REQUIRED_SECTIONS`):

`purpose`, `when_to_use`, `when_not_to_use`, `inputs`, `preconditions`,
`procedure`, `evidence`, `validation`, `failure_modes`, `outputs`, `restrictions`.

## 3. Sidecar SKILL.json — contrato

- `skill_id`: patrón `^SK-\d{4}$` (**único**; no reusar IDs de otras skills, incluso
  si la otra iniciativa solo los tenía planificados).
- `name` == folder; `version` == `0.1.0` (versión inicial de toda skill nueva).
- `skill_kind` (opcional): `knowledge` \| `behavioral` \| `workflow`.
- `scope.target`: `project` \| `global`.
- `capabilities.required` / `capabilities.optional`: **IDs del capability registry**
  (`CORE/capabilities/capabilities.json`), nunca nombres de providers concretos
  (principio CP-020). `se capabilities --check` rechaza IDs desconocidos.
- `constraints.write`: `allowed` \| `forbidden`. `forbidden` ⇒ la skill es READ_ONLY
  (igual que `verification-review`).
- `metadata`: mínimo `checkpoint`, `adapter`. Campos de ecosistema
  (`ecosystem`, etc.) opcionales y aditivos.

## 4. Capacidades vs providers

Una skill declara **capabilities** semánticas. El registry decide el carrier real.
Ejemplo: `structured.reasoning` (no `sequential-thinking`), `documentation.lookup`
(no `context7`), `browser.screenshot` (no `playwright`). Si la capability no existe
en el registry, el proceso provider-incorporation (CP-020 §provider incorporation:
ADR + registry + `--check` limpio + tests) aplica antes de declararla.

## 5. READ_ONLY y evidencia

- `constraints.write = forbidden` ⇒ la skill nunca modifica el workspace; el resolver
  la marca en el plan como DENY para `write`.
- Las skills de proceso (workflow/behavioral, p.ej. `dbg-systematic`, `impl-tdd`)
  suelen ser `allowed` pero **su cierre es verificación demostrable**: EVD
  comprobable, nunca "de palabra".
- "No se encontró evidencia" no equivale a "se verificó que no existe" (regla
  `verification-review`).

## 6. Integración con tests y adapter

- `TESTS/test_skills.py`:
  - `CANONICAL_SKILLS` (orden alfabético) incluye la skill nueva.
  - `test_required_skills_exist_and_validate`, `test_required_sections_present`,
    `test_sidecar_contracts_valid` la cubren automáticamente.
  - `test_bootstrap_installs_selected_skills` valida la instalación hermenéutica.
- `.opencode/skill/<name>/SKILL.md` **byte-identical** al canónico (check en
  `test_opencode_adapter.py`).
- Idempotencia: re-ejecutar `se adapter opencode` debe reportar cambios nulos.

## 7. Ejemplos canónicos

- READ_ONLY knowledge: `verification-review` (SK-0002).
- Workflow de proceso: `dbg-systematic` (SK-0004).
- Behavioral reviewer: `rev-adversarial` (SK-0005).
- Behavioral test-first: `impl-tdd` (SK-0006).