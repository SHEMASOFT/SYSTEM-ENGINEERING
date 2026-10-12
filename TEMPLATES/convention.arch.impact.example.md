# arch.impact — ejemplo

```markdown
## Impacto

**IN-SCOPE**
- SKILLS/dbg-systematic/, rev-adversarial/, impl-tdd/ (nuevos, aditivos)
- TESTS/test_skills.py, TESTS/test_opencode_adapter.py (conteos skills)
- DOCS/CONVENTION_*.md nuevos; TEMPLATES/convention.*.example.* nuevos
- SCRIPTS/se_core/commands.py (validate: WARN informativo no bloqueante; G5 GUIDE)

**OUT-OF-SCOPE (verificado al cierre)**
- CORE/ (schemas, gates, capabilities): no se toca
- AGENTS/* : sin cambios (mismo AG-0009)
- PROJECTS/<project> (external workspaces): not touched
- MCP/OpenCode global: no se instala nada
```