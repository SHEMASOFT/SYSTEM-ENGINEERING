# Naming Conventions

Adopted in ADR-0018. These conventions separate GLOBAL assets from PROJECT assets so that
names never silently collide in OpenCode.

## Scope names

| Scope | Owner | Prefix |
|-------|-------|--------|
| GLOBAL | SYSTEM-ENGINEERING (contracts) / `~/.config/opencode` | **none** |
| PROJECT | PROJECTS/&lt;P&gt;/`.opencode` | **`<project>`**, e.g. `shema`, `shemaseg` |
| LOCAL | per-machine, unversioned | `local-` |

## Agents

- **GLOBAL**: unprefixed role names derived from contracts, e.g.
  `coordinator`, `explorer`, `analyst`, `architect`, `planner`, `implementer`,
  `tester`, `reviewer`, `security`, `documentation`, `devops`, `visual`.
- **PROJECT**: prefixed with the project slug, e.g. `shema-reviewer`,
  `shema-security`, `shemaseg-explorer`.
- Domain additions inside a domain pack use the domain prefix, e.g. `security-*`.

## Commands

- **GLOBAL**: `/init`, `/explore`, `/plan`, `/implement`, `/verify`, `/review`,
  `/release`, `/doctor`, `/validate`, `/gate` (wrappers over `se.py`).
- **PROJECT**: `/shema-review`, `/shema-explore` (prefix to avoid shadowing global
  `/review` when semantics differ).

## Skills

- **GLOBAL**: `SKILLS/<name>/SKILL.md` with lowercase hyphenated `name`.
- **PROJECT**: `.opencode/skill/<project>-<name>/SKILL.md`.

## Directory form

- Canonical singular form: `agent/`, `command/`, `skill/`.
- OpenCode also accepts plural (`agents/`, `commands/`, `skills/`); legacy assets using the
  plural form are read for compatibility but new generated assets use the singular form.

## Enforcement

- `se validate` runs a collision check: a PROJECT asset that shadows a GLOBAL asset is a
  validation failure unless declared as an explicit, documented override.
- Names must be lowercase, hyphen-separated, and unique within their scope.