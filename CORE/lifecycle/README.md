# CORE / Lifecycle

Source of truth: [`lifecycle.json`](lifecycle.json).

- Nine ordered project states: `DRAFT`, `DISCOVERY`, `PLANNING`, `ACTIVE`,
  `VERIFICATION`, `ACCEPTANCE`, `RELEASED`, `OPERATING`, `ARCHIVED`.
- `DRAFT` is the initial state; `ARCHIVED` is terminal.
- `BLOCKED` is **not** a lifecycle state. It is a condition (see `conditions.BLOCKED`)
  that applies to projects and tasks, requires a reason, and requires a resolution path.
- Transitions are guarded by gates (`G0`–`G8`). See `CORE/gates/gates.json`.

The high-level conceptual flow described in the mission (INTAKE, BASELINE,
ARCHITECTURE, REVIEW, LEARNING, ...) is expressed through these states, the gate
conditions, and the task/artifact models rather than as separate states. This keeps the
state machine small and testable.

Rule: an agent or command may **not** advance a state unless the transition's gates pass.
