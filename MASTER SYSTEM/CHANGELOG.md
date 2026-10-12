# Changelog

All notable changes to the Master System distribution are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are normalized SemVer (see `DOCS/VERSIONING_STRATEGY.md`).

## [Unreleased]

### Added

- **Ecosystem capability set (ARCH-ECOSYSTEM-002/003)**: three new canonical skills plus
  documentation and informational automation, no CORE changes, no release.
  - **Canonical skills** (each `SKILL.md` + `SKILL.json`): `dbg-systematic` (SK-0004, workflow;
    capabilities filesystem.read/filesystem.search/structured.reasoning), `rev-adversarial`
    (SK-0005, behavioral; `metadata.review_lens` in EVD type=review), `impl-tdd` (SK-0006,
    behavioral, opt-in RED-GREEN-REFACTOR). Capability policy check PASS; validated against
    `skill-contract`.
  - **Skill authoring enablers**: `TEMPLATES/skill/` (SKILL.md.template + SKILL.json.template) and
    `DOCS/SKILL_AUTHORING.md` (frontmatter, REQUIRED_SECTIONS, capabilities, READ_ONLY, tests).
  - **Conventions (documental)**: `spec.delta`, `spec.write`, `rev.code_review`, `conv.convergence`,
    `plan.roles`, `plan` (verification per task), `arch.impact`, `impl.subagent`,
    `research.directed`, review lenses (`metadata.review_lens` seed vocabulary) — each with an
    example under `TEMPLATES/`.
  - **Informational automation (non-blocking, no exit-code changes)**: `se validate` emits WARNs
    for non-vocabulary `spec.delta` verbs and dangling `SK-xxxx` references; `se gate --gate G5`
    prints `GUIDE: MIN_EVIDENCE`.
  - **Tests**: `CANONICAL_SKILLS` 3 -> 6 in `test_skills.py`; adapter counts updated
    (artifacts/paths 34, generated_files/hashes 33); template + convention + WARN coverage added.
  - **Registry**: no new capabilities/providers added — the three skills reuse existing CP-020
    capabilities only.

- **Durable Human Action Requests (`se har` / `se resume`)**: a pending human decision is now a
  first-class, durable artifact instead of a conversation. New `har.schema.json`
  (`SCHEMAS/har/`, registered in `SCHEMAS/index.json`) and a per-project state store
  (`SCRIPTS/se_core/state.py`) with an abstract `StateStore` and a SQLite backend at
  `<project>/.se/state.db` (backend selectable via `SE_STATE_BACKEND`). New CLI:
  `se har create|list|show|answer|cancel|expire` and `se resume <HAR-id>`. Lifecycle is
  `OPEN -> ANSWERED | CANCELLED | EXPIRED`, with an OPEN HAR past `--expires-at` surfaced as
  `STALE` and refused for `answer`; `answer`/`cancel`/`expire` require `OPEN` (no double
  answers); `resume` requires `ANSWERED` and records a recovery audit trail
  (`recovery.last_resumed_*`). Conditions are restricted to MANUAL gate refs (`GX.Y`) and
  validated before any write. Purely additive: no CORE, gate, or existing command semantics
  changed. 16 new tests; full suite 500 passed, `se validate` PASS, `se doctor` PASS=20 WARN=1 FAIL=0.

- **ARCH-CONVERGENCE-001 architectural closure (CHECKPOINT-023)**: SYSTEM-ENGINEERING is confirmed as
  the ENGINEERING CONTROL PLANE, with ECC and RSC held as EXTERNAL PATTERN SOURCES — no framework,
  dependency, or parallel layer adopted. Records the Fusion Architecture Baseline, the ACB-01…10
  admission criteria plus six cost dimensions, and the admission decisions (KEEP 10 · IMPROVE 2 ·
  DESIGN 3 · DEFER 9 · REJECT 4). Entirely documentary: no runtime, no schema/command/agent/skill/gate
  change, no version bump.
  - **DESIGN-01 Execution Integrity (CLOSED, doc + convention)**: `DOCS/adr/ADR-0021-plan-identity.json`
    (EPI-1 plan identity), `DOCS/reference/execution-integrity.md` (EPI-1/EEX-1/EDG-1 conventions;
    not runtime-implemented), and additive points 8 (EDG-1 checksum semantics) and 9 (EEX-1 execution
    receipt) in `POLICIES/evidence.md`.
  - **DESIGN-02 Verification Independence (CLOSED, KEEP CURRENT)**: risk-based analysis only; no
    workspace change (fresh-context verification deferred with no consumer).
  - **DESIGN-03 Durable Engineering State (CLOSED)**: `DOCS/reference/policies/STATE_POLICY.md`
    formalizes the existing state model (DEFER MEMORY + FORMALIZE STATE POLICY + KEEP CURRENT) and
    introduces no infrastructure, record type, or state machine.
  - **Deferred (reopen only on real project evidence + reproducible gap)**: memory, work
    classification/routing, multi-agent orchestration, model routing, continuous learning, harness
    audit/security, workflow first-class.
  - **Closure evidence**: `se validate` PASS, `se doctor` PASS=16 WARN=2 FAIL=0, suite 298 OK;
    documentation-only change control (6 persistent files). CP-023 was read-only, so the closure went
    uncommitted and unregistered until now.

## [0.10.0] - 2026-09-22

### Added

- **Visual Frontend Engineering capability (ARCH-VFE-001)**: provider-agnostic, zero-cost
  capability that builds, renders, screenshots and structurally reviews frontends with verifiable
  visual evidence (builder + screenshot loop + DESIGN.md direction). Components:
  - **Canonical skill** `SKILLS/visual-frontend-engineering/SKILL.md` (SK-0003) + `SKILL.json`
    declaring capabilities (browser.preview/browser.snapshot/browser.screenshot optional,
    visual.review optional) with max-3-rounds stop criteria and explicit evidence contract.
  - **Registry additions** `CORE/capabilities/capabilities.json` (CP-020): providers `playwright`
    (available) and `deepseek-vision` (unknown), capabilities `browser.preview`, `browser.snapshot`,
    `browser.screenshot` (available), `visual.review` (unknown — no provider key observable).
  - **Template** `TEMPLATES/DESIGN.template.md`: minimal Design System spec in Google DESIGN.md
    format (YAML tokens + WCAG contrast + evidence checklist), with attribution to
    Anthropic `frontend-design` (Apache-2.0), Vercel `web-interface-guidelines` (MIT),
    Google DESIGN.md (Apache-2.0).
  - **Demo + evidence** `TESTS/fixtures/vfe-demo/` and runner `SCRIPTS/vfe_capture.py`
    (py-playwright with system Chrome `channel="chrome"`): BEFORE page fails automated structural
    checks (missing alt, contrast 2.32) and AFTER passes (no overflow, landmarks, all contrast
    ≥ 4.5) with viewport + full-page screenshots at 1280×800 and 375×812.
  - **Docs** `DOCS/VISUAL_FRONTEND_ENGINEERING.md` (usage, provider switching, review loop,
    security rules, roadmap).
  - **Backward compatible**: no breaking changes to agents, commands, schemas or gates.
    Minor bump 0.9.0 → 0.10.0 per VERSIONING_STRATEGY (new contract SKILL.md).

## [Unreleased]

### Added

- **Ecosystem capability research (ARCH-ECOSYSTEM-001)**: READ-ONLY documentary series evaluating
  32 capabilities drawn from external ecosystems (Superpowers, BMAD, OpenSpec, Spec Kit, GSD, Kiro,
  Tessl, Spec Kitty, Agent Skills, Ralph Loop) against the real SYSTEM-ENGINEERING state (v0.9.0).
  Decided per capability: 5 BUILD_NATIVE (`dbg.systematic`, `rev.adversarial`, `rev.lenses`,
  `impl.tdd`, `skills.auth`), 11 ADAPT_NATIVE, 14 IMPROVE_EXISTING, 1 HYBRID (`research.directed`
  reusing the already-governed `context7` provider), 2 DEFER (`impl.parallel` via ARCH-WORKFLOW-001
  criteria C1/C2, `skills.registry` pending critical mass). No capability requires installing a
  framework; no implementation, no version bump. Deliverables: `ARCH-ECOSYSTEM-001-0X-*.md`
  (01–05).
- **Capability decision (ARCH-ECOSYSTEM-002)**: resolves P1–P4 from the 001 series. P1 approved —
  native QUICK-WIN skills seed (`dbg.systematic`, `rev.adversarial`, `impl.tdd`) plus `skills.auth`
  guide, to be implemented later by ARCH-ECOSYSTEM-003. P2 — `spec.delta` adopted as **optional**
  document convention (mandatory only with real brownfield demand). P3 — `review_lens` as an open
  convention stored in `metadata` of review EVIDENCE (vocabulary seed; schema promotion deferred
  until a real consumer). P4 — `research.directed` kept as the single HYBRID; formalized provider-
  incorporation policy (ADR + registry + clean `se capabilities --check`) re-affirming CP-020.
  Result: **READY FOR IMPLEMENTATION**, no implementation, no new CORE entities/agents/commands/
  state machines, no external dependencies, no version bump. Deliverables:
  `ARCH-ECOSYSTEM-002-01-DECISION.md`, `ARCH-ECOSYSTEM-002-02-IMPLEMENTATION-PLAN.md`.

## [0.9.0] - 2026-09-22

### Added

- **Capability Governance (CP-020)**: new capability layer above MCPs/tools that governs how
  Agents, Skills and Tasks use *capabilities* instead of concrete provider names.
  - **Canonical registry** `CORE/capabilities/capabilities.json` is the single source of truth for
    the declarative provider → capability mapping (filesystem → read/search/write, context7 →
    documentation.lookup, sequential-thinking → structured.reasoning). Conforming schema
    `SCHEMAS/capability/capability.schema.json`, registered in `SCHEMAS/index.json`.
  - **Contracts** (optional, additive, backward-compatible): `capabilities` (`required`/`optional`)
    and `constraints.write` (`allowed|forbidden`) in `skill-contract.schema.json`;
    `capability_policy` (`mode` READ_ONLY|READ_WRITE + `requires`/`allows`/`denies`) in
    `task.schema.json`; `capability_requires` in `agent-contract.schema.json` (also accepted by the
    legacy agent schema); `profiles.capability` capability ids with dotted names and new
    `profiles.toolchain.providers` in the project contracts; adapter manifest `capability_plan`.
  - **Resolver** `SCRIPTS/se_core/capabilities.py`: deterministic resolution order
    SYSTEM → Project → Agent → Skill → Task (more specific prevails) with explicit ALLOW / DENY /
    OPTIONAL / REQUIRED and conflict detection (required-but-denied, required-but-unavailable,
    write in READ_ONLY). **READ_ONLY** is represented as a real execution-contract restriction
    (read/search ALLOW, write DENY).
  - **Interface**: new command CMD-0014 `capabilities` and `se capabilities` (registry report,
    `--check`, `--project`/`--task` policy check and plan). Validated by `se validate`,
    `se doctor` (new `capabilities` check, PASS 15/2/0) and the adapter (manifest exposes the
    capability plan; `Wrote 0` idempotent). Existing skills declare capabilities explicitly and
    `verification-review` (SK-0002) represents READ_ONLY via `constraints.write: forbidden`.
  - New docs `DOCS/CAPABILITY_GOVERNANCE.md`; new `TESTS/test_capability_governance.py`
    (35 tests, A–N: registry, mapping, inheritance, READ_ONLY, conflicts, backward compat,
    adapter, doctor/validate).

## [0.8.0] - 2026-09-21

### Added

- **Research adaptation & vNEXT (ARCH-ADAPT-001)**: audited the real framework state and adapted
  the closed architecture research into SYSTEM-ENGINEERING. Implemented three **additive,
  optional, backward-compatible** blocks: (1) **Project Profile** — optional `profiles`
  (work/domain/toolchain/capability) in `project.schema.json` and `project-context.schema.json`,
  with the binding rule that *Toolchain Profile = what you work with* and *Capability Profile =
  what the project needs* are distinct; (2) **Adapter capability declaration** — optional
  `capabilities` (`SUPPORTED|PARTIAL|UNSUPPORTED`) in `adapter-manifest.schema.json`, emitted by
  `mappings.build_config` so the Adapter Layer never fakes harness equivalence (agents/commands/
  skills SUPPORTED, policies PARTIAL, workflows UNSUPPORTED); (3) **Skill kind** — optional
  `skill_kind` (`knowledge|behavioral|workflow`) in `skill-contract.schema.json`. Also unified the
  epistemic taxonomy convention (`OBSERVED/FACT`, `VERIFIED`, `INFERRED`, `ASSUMED`, `UNKNOWN`,
  `CONFLICTING`, `STALE`) without auto-promoting agent knowledge to FACT. New docs
  `DOCS/PROJECT_PROFILE.md` and `DOCS/ARCH_ADAPT_001.md`; new `TESTS/test_project_profile.py` plus
  new assertions in adapter/skill tests. Deferred with design (not implemented): Workflow as a
  first-class object, Process Scaling, Context/Continuity (remote host), Artifact Dependency Graph.
  No existing capability removed; no commit. Deliverables: `ARCH-ADAPT-001-0x-*.md` (01–09).

- **Canonical skills v0 (CHECKPOINT-017)**: the first two official SYSTEM-ENGINEERING
  skills, `checkpoint-release` (SK-0001, standardized checkpoint/release preparation and
  validation with FACT/VERIFIED/INFERRED/UNKNOWN/CONFLICTING tagging) and
  `verification-review` (SK-0002, read-only PASS/PARTIAL/BLOCKED/FAIL review that
  distinguishes "no evidence found" from "verified absent"). Each skill has a co-located
  `SKILL.md` (OpenCode frontmatter `name`/`description`/`metadata`) and a sidecar
  `SKILL.json` validating against `SCHEMAS/skill-contract.schema.json`. The OpenCode
  adapter now validates skills more strictly (`description` required, `name` must equal the
  folder) and the frontmatter parser was fixed to support skill bodies after the closing
  `---` (it previously anchored to end-of-file). The repository `.opencode/skills/` layer
  now ships both skills and project bootstrap installs them via `inherited_skills`;
  a managed pilot project inherits both (controlled migration, idempotent regeneration).
  New `TESTS/test_skills.py` (9 tests) plus adapter skill tests; full suite 242 tests OK.

- **Project policy & init hardening (CHECKPOINT-016)**: new MANAGED vs EXTERNAL/INDEPENDENT
  project topology. `metadata.category` (additive, optional) in `project.schema.json` and
  `project-context.schema.json` (`MANAGED` | `EXTERNAL`). New `SCRIPTS/se_core/projects.py`
  classifies projects deterministically (manifest category wins; manifest-less directories
  with `.opencode/`, `AGENTS.md`, `opencode.json` or `SDD/` are EXTERNAL). `se init` is
  hardened: bare names resolve under `PROJECTS/` when present, `TARGET:` is printed before
  writing, initialization of SYSTEM-ENGINEERING infrastructure itself is refused, and standard
  bootstrap/manifest creation over EXTERNAL/INDEPENDENT projects is refused (no `--force`
  bypass; safe rejection preferred). No existing independent artifacts are overwritten
  (`AGENTS.md`/`.opencode`/`opencode.json`/`SDD`/`PROJECT.json`). Idempotent MANAGED bootstrap
  is preserved. Doctor scans (secrets, self-containment, JSON integrity) are category-aware
  and skip EXTERNAL project directories — the previous false FAIL on an unmanaged project
  secrets is gone. `validate --project` no longer treats a missing `PROJECT.json` in an
  EXTERNAL project as a defect. New `DOCS/PROJECT_POLICY.md`, updated `PROJECT_BOOTSTRAP.md`
  and `commands.md`, `TESTS/test_project_policy.py` (27 tests).

- **Workflow decision (ARCH-WORKFLOW-001)**: evaluated "Workflow as a first-class object"
  (persistent, executable, portable across adapters). Result: **DECISION PENDING** — evidence is
  insufficient (ADR-0014 requires at least two real use cases for a generic process engine; the only
  adapter declares `capabilities.workflows=UNSUPPORTED`, so portability cannot be demonstrated; all
  managed projects follow the linear lifecycle). The safe declarative subset (optional
  `CORE/workflows/<id>.json` with `default` = current lifecycle, per ARCH-ADAPT-001·03) remains
  ADAPT and is design-only. Process Scaling, Context/Continuity and Artifact Graph stay DEFERRED
  (conceptual, not technical, dependency). Promotion criteria (C1: ≥2 projects with non-linear
  flows; C2: a harness with workflow support; C3: no-gate-bypass + human attestation) are explicit.
  No implementation; no commit. Documentation only. Deliverable: `ARCH-WORKFLOW-001-DECISION.md`.

### Changed

- **OpenCode adapter manifest rename (CHECKPOINT-012)**: the output manifest generated by
  `se adapter opencode` and `se init <project>` is now `adapter-manifest.json` instead of
  `opencode.json`. The name `opencode.json` is reserved exclusively for OpenCode runtime
  config; the adapter manifest can no longer collide with OpenCode's config schema
  (`ConfigInvalidError`). Existing generated manifests are migrated: project roots
  (a managed project's `opencode.json`) and the repository's own `.opencode/opencode.json`
  become `adapter-manifest.json`; `MASTER-SYSTEM-MANIFEST.json` is regenerated accordingly.

- **Agent frontmatter permission fix (CHECKPOINT-013)**: generated agents (`agent/<role>.md`)
  now emit `permission: {}` instead of a space-joined scalar. OpenCode runtime v1.18.31
  validates `permission` as a `PermissionActionConfig` object; the previous scalar
  (`permission: ANALYZE READ TEST WRITE_DOCS`) broke the runtime config load
  (`Expected PermissionActionConfig`). An empty map inherits the global policy; contract
  authority stays in the canonical contracts and the `## Permissions` body section.

## [0.7.0] - 2026-09-19

### Added

- **Project Bootstrap** (`se init <project>`): nueva capacidad de distribución que instala
  la capa OpenCode de un proyecto (AGENTS.md, opencode.json, `.opencode/`, manifest de
  instalación) a partir de los contratos canónicos — CHECKPOINT-005, sobre ADR-0015/0017.
- `SCRIPTS/se_core/opencode/generator.py::generate_project`: generación selectiva
  (solo agentes solicitados y skills declaradas) e idempotente; proyecto nunca destruido.
- `project.schema.json` extendido con `required_agents` e `inherited_skills` (opcionales);
  nuevo `SCHEMAS/installation-manifest.schema.json` con su entrada en `SCHEMAS/index.json`.
- `MASTER-SYSTEM-MANIFEST.json` por proyecto: verificación de instalación por `content-hash`.
- `DOCS/PROJECT_BOOTSTRAP.md`; `TESTS/test_project_bootstrap.py` (11 tests).

### Changed

- `init` acepta como modo bootstrap un path posicional; el modo creador
  (`--dir --name --owner`) se conserva. `MANIFEST.json` declara `bundles.bootstrap` implementado.

## [0.6.0] - 2026-09-19

### Added

- **OpenCode Adapter** (`se adapter opencode`): nueva capacidad ejecutable que transforma
  contratos canónicos en artefactos OpenCode (`.opencode/`) — ADR-0015/0017/0020.
- Módulo `SCRIPTS/se_core/opencode/` (generator, mappings, validators) + CLI `adapter opencode`
  con `--output` y `--dry-run`.
- `DOCS/OPENCODE_ADAPTER.md`; `MASTER SYSTEM/adapters/opencode/` pasa de "planned" a
  implementado; `INTEGRATIONS/opencode/README.md` actualizado.
- Doctor: nuevos checks `contracts`, `adapter` y `manifests`.
- `TESTS/test_opencode_adapter.py` (15 tests: 12 agentes, 13 comandos, skills, config,
  idempotencia, `--dry-run`, guard de seguridad `PROJECTS`).

### Changed

- Salida determinista: escritura con `newline="\n"` y `metadata.content_hashes` (sha256)
  para detección de drift.

## [0.5.0] - 2026-09-19

### Added

- Canonical contract layer: `SCHEMAS/*-contract.schema.json` is the single
  source of truth for agents and commands; `SCHEMAS/index.json` now maps
  `agent` to `SCHEMAS/agent-contract.schema.json` (ADR-0020).
- Agent contracts migrated to canonical vocabulary (id `AG-XXXX`, version,
  role, description, capabilities, lifecycle) — additive, backward compatible.
- Command contracts migrated to canonical vocabulary (id `CMD-XXXX`, version,
  description, agent, execution_intent, risk_level, permissions, arguments).
- `command-contract.schema.json` extended with optional `version` and `agent`.
- Legacy `AGENTS/_contract/agent.schema.json` retained as a compatibility
  superset and marked legacy (ADR-0020).
- ADR-0020 (canonical contract layer) and `TESTS/test_contract_migration.py`.

## [0.4.0] - 2026-09-19

### Added

- Distribution layer `MASTER SYSTEM/` (MANIFEST.json, VERSION, CHANGELOG.md,
  adapters/, conformance/) per ADR-0016.
- Governance docs: `DOCS/NAMING_CONVENTIONS.md`, `DOCS/VERSIONING_STRATEGY.md`,
  `DOCS/PRECEDENCE_RULES.md`.
- ADRs 0015-0019 (opencode adapter architecture, distribution model, generation
  pipeline, precedence & naming, agent lifecycle).
- `.gitignore` rules for `PROJECTS/`, generated OpenCode assets and `*.env`.

### Changed

- Nothing removed. `DOCS/versioning.md` remains authoritative for versioning.

[0.7.0]: ./
[0.6.0]: ./
[0.5.0]: ./
[0.4.0]: ./