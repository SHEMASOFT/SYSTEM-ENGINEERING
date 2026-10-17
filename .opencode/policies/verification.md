# Policy: Verification

Principle: **SMALLEST PROOF THAT DECIDES**, never **RUN EVERYTHING TO FEEL SAFE**.

1. Scope the proof to the change, not to the repository. Verify the surface that actually
   changed (files, symbols, contracts) before widening the blast radius.
2. Order checks cheapest-decisive first: targeted test(s) for the changed module, then
   `se doctor` / `se validate` for canon invariants, then the full suite last.
3. One run per change. Re-running the same checks against an unchanged revision produces no
   new information; it only costs.
4. Never re-establish a fact already verified in the same session against the same revision.
5. Escalate to the full test suite only when the change is cross-cutting (schemas, contracts,
   paths, doctor, CLI dispatch), a gate or release requires it, or a scoped run failed.
6. Bound every tool output: counts, `--stat`, `tail`, `path:line`, or explicit line ranges.
   Do not load whole generated sources or logs that will not be used.
7. When a CodeGraph index exists, derive scope from it (`affected` / blast radius maps changed
   symbols to affected tests). Without an index, map module to test by naming convention.
   Scope derivation is an accelerator, never a hard dependency of the system.
8. Verification is evidence (see `POLICIES/evidence.md`): record the exact command and its
   observed result.
9. A skipped, unavailable, or timed-out check is reported as SKIPPED / UNAVAILABLE / UNKNOWN,
   never as PASS.
10. Keep escalation bounded: one batch of at most three decisive checks before widening. If
    more than roughly five sequential lookups are required to find the scope, delegate the
    mapping instead of widening inline.
