# Conformance

Versioned evidence that the distribution satisfies the Master System's own rules.

Status: **pending** — produced on the first release run of `se doctor` / `se validate`.

Expected evidence here:

- `doctor-report.json` — health report of the distribution vs contracts.
- `validate-report.json` — schema/conformance results for decisions, agents and docs.
- `collision-report.json` — precedence/collision check (ADR-0018).

Reports are regenerated per release and pinned along with the snapshot version
(`MASTER SYSTEM/VERSION`).