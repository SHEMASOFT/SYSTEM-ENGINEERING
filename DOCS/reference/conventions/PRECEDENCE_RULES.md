# Precedence Rules

Adopted in ADR-0018. Define how configuration and assets resolve across scopes and why gates
can never be degraded.

## OpenCode configuration precedence

`built-in < GLOBAL < PROJECT < LOCAL (env)`

- **built-in**: OpenCode defaults.
- **GLOBAL**: `~/.config/opencode/` and SYSTEM-ENGINEERING global assets generated to
  `~/.config/opencode/` (agents, commands, skills, AGENTS.md).
- **PROJECT**: `<project>/.opencode/` and `<project>/opencode.json`.
- **LOCAL**: user-level, per-machine, unversioned (`local-` prefix).

Project values override global values in deep-merged config; LOCAL overrides PROJECT for a
specific machine only. Versioned contracts always live at GLOBAL or PROJECT, never LOCAL.

## Master System precedence

`CORE < DOMAIN packs < PROJECT` — **strictly additive**.

- CORE defines gates and invariants (permissions, lifecycle).
- DOMAIN packs may only add capabilities, never relax a gate.
- PROJECT may scope but never exceed the union of CORE + DOMAIN.

## Gate non-degradation (invariant)

- A gate's strength cannot be reduced by any scope: `G0..G8` and their permission/payload
  checks are fixed by CORE.
- Creation of agents/commands/gates is **additive**: the intersection with task
  `authorized_actions` is computed, never the union (ADR-0019).
- DESTRUCTIVE actions cannot be granted by DOMAIN packs or PROJECT config.

## Permission mapping

- Task permission model is the source; OpenCode tool permissions are derived and must be a
  subset (never a superset).
- Project policy keys (`*.required-permissions`) override at PROJECT scope; GLOBAL defaults
  apply otherwise.

## Collision resolution

- A PROJECT asset that shadows a GLOBAL asset is an error in `se validate` unless declared
  `override: true` with a documented reason.
- Naming (NAMING_CONVENTIONS.md) makes shadowing explicit by construction (project prefix).
- When an override exists, the project must prove gate equivalence via tests.

## Enforcement

- `se validate` implements precedence + collision + additive checks.
- `se doctor` compares declared vs effective precedence at runtime.