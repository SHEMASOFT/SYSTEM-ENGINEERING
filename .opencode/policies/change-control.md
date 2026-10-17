# Policy: Change Control

1. Every material change is traceable to at least one requirement and one task.
2. Material architectural changes require an ADR (`decisions/ADR-*.json`) recorded
   **before** dependent implementation.
3. Changes to requirements after approval require a new revision and re-approval; do not
   silently edit approved requirements.
4. Changes are verified by evidence before being marked DONE.
5. The Master System's own CORE and SCHEMAS are versioned; changes to them require:
   - an ADR,
   - updated tests,
   - a passing `doctor` and full test run.
6. Commits are created only after validation succeeds. Never push automatically.
