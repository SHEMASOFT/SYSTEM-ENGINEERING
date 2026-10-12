# Policy: Evidence

Principle: **CLAIM -> EVIDENCE**, never **CLAIM -> TRUST THE AGENT**.

1. Evidence is a first-class artifact (`SCHEMAS/evidence/evidence.schema.json`).
2. Every requirement marked VERIFIED and every deliverable task marked DONE must link to
   at least one evidence record.
3. Evidence must record:
   - `type` (test, screenshot, video, log, security, performance, deployment, uat, review),
   - `result` (PASS, FAIL, WARN, INFO),
   - `collected_at`, `collected_by`,
   - how it was produced (`command` or description) and where it is (`location`).
4. FAIL results must never be hidden or overwritten; resolve them or record an explicit,
   owner-approved acceptance.
5. Evidence must be reproducible where feasible; prefer commands over screenshots alone.
6. A claim without evidence is UNVERIFIED.
7. Epistemic rule: a statement may only be marked `FACT` when it is backed by linked
   evidence. `ASSUMPTION` and `UNKNOWN` must never be silently promoted to `FACT`, and no
   factual default may be substituted for missing information.
8. Checksum semantics (EDG-1): when a `checksum` is declared on an EVIDENCE or ARTIFACT, it is
   the SHA-256 of the raw bytes at `location`, with no normalization. A missing `location`
   makes a checksum non-assertable; a mismatch on re-computation is informational (update the
   checksum or re-create the record). A checksum alone is not an authenticity guarantee.
9. Execution receipts (EEX-1): for evidence supporting gates (G4/G5), recording an execution
   receipt in `metadata.execution` is RECOMMENDED. A receipt is epistemic metadata that lives
   in the EVIDENCE record and participates in the traceability graph; it is not the
   `mutation-log.jsonl` (accountability, ADR-0013). The EVIDENCE record remains the epistemic
   source.
