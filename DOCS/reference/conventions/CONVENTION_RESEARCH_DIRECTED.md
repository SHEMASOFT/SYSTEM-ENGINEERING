# Convention: research.directed

**Guard: ARCH-ECOSYSTEM-002, F4 · P3 — documental.** Investigación **dirigida y con
alcance** para explorar/decidir: qué se busca, qué es evidencia, qué queda abierto — en
vez de exploración abierta sin pregunta.

## Principio

La investigación es dirigida si declara **pregunta(s)**, **dominios** y **criterio de
cierre**. Un "research" sin pregunta no produce decisión; produce ruido.

## Reglas

1. Formular la pregunta explícita (p.ej. `Q: qué capacidad se necesita para X?`).
2. Acotar dominios (`context7`, docs, repos, greps) y el tipo de evidencia que zanja
   (benchmark, ADR, `se validate`, suite).
3. Registrar hallazgos y **conclusiones** con su status: CERRADA (criterio cumplido),
   ABIERTA (queda duda). Nunca presentar duda como certeza.
4. La conclusión alimenta la DECISIÓN (ADR/WORK/ARCH) o el descubrimiento (gaps).
5. Verificación: el documento de investigación lista pregunta, evidencia y conclusión,
   y traza a donde la decisión quedó registrada.

Referencias: `DOCS/CONVENTION_RESEARCH_DIRECTED.md` ·
`TEMPLATES/convention.research.directed.example.md`.