# Workflow Checkpoint & Recovery — SYSTEM ENGINEERING

**Durable workflow progress** — the orchestration engine persists a checkpoint after
every node, so an interrupted or failed run can be resumed instead of restarted.

Decision record: [ADR-0026](../adr/ADR-0026-workflow-checkpoint-recovery.json).
Schema: `SCHEMAS/checkpoint/checkpoint.schema.json`.

---

## Why

A workflow is a DAG of agent nodes. Before this feature the engine was purely
in-memory: if node 4 of 5 failed, everything had to be re-run from node 1, throwing
away verified upstream work. Checkpoints make progress durable on disk.

A checkpoint records **only nodes that provably finished** (status `COMPLETED` or
`FAILED`). It never claims a node completed when its outcome is unknown, so a resume
can never skip work that did not actually happen.

---

## Quick path

```bash
# 1. Run a workflow — a checkpoint is written after every node
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp --workflow WF-0001

# 2. Inspect the checkpoints recorded for that workflow
python SCRIPTS/se.py orchestrate checkpoint list --project PROJECTS/MyApp --workflow WF-0001

# 3. If a node failed, resume from the last checkpoint instead of restarting
python SCRIPTS/se.py orchestrate execute --project PROJECTS/MyApp --workflow WF-0001 \
  --resume-from CP-0003

# 4. Bound growth: keep only the newest 5 checkpoints
python SCRIPTS/se.py orchestrate checkpoint clean --project PROJECTS/MyApp --workflow WF-0001 --keep 5
```

---

## Where checkpoints live

```
PROJECTS/<name>/.workflows/checkpoints/CP-0001.json
PROJECTS/<name>/.workflows/checkpoints/CP-0002.json
...
```

- One JSON document per checkpoint, written **atomically** (no half-written records).
- Ids are monotonic per project: `CP-0001`, `CP-0002`, ...
- The directory is created lazily on the first checkpoint.

---

## Checkpoint format

| Field | Meaning |
|-------|---------|
| `schema_version` | Always `"1"` |
| `checkpoint_id` | `CP-NNNN` |
| `workflow_id` | `WF-NNNN` this checkpoint belongs to |
| `execution_id` | `WEX-NNNN` of the run |
| `completed_nodes` | Resume cursor: node ids that finished, in order |
| `node_results` | Audit trail for `COMPLETED`/`FAILED` nodes only (status, outputs, error, timestamps) |
| `gate_results` | Evaluated gates at the moment of the checkpoint |
| `context` | Accumulated node outputs (what downstream nodes read) |
| `created_at` | UTC timestamp |
| `status` | `IN_PROGRESS` \| `COMPLETED` \| `FAILED` \| `RESUMED` |

Example:

```json
{
  "schema_version": "1",
  "checkpoint_id": "CP-0001",
  "workflow_id": "WF-0001",
  "execution_id": "WEX-1234",
  "completed_nodes": ["fetch-data"],
  "node_results": {
    "fetch-data": {
      "status": "COMPLETED",
      "outputs": { "rows": 120 },
      "started_at": "2026-10-16T10:00:00Z",
      "completed_at": "2026-10-16T10:00:05Z"
    }
  },
  "gate_results": { "G1": { "status": "PASS" } },
  "context": { "rows": 120 },
  "created_at": "2026-10-16T10:00:05Z",
  "status": "IN_PROGRESS"
}
```

---

## Resume semantics

`se orchestrate execute --resume-from CP-XXXX`:

1. Loads the checkpoint and verifies `workflow_id` matches (a checkpoint from another
   workflow is rejected with an error — it never silently resumes the wrong run).
2. Restores `completed_nodes` and the accumulated `context`.
3. Re-uses the original `execution_id`.
4. Executes in the same deterministic order, **skipping** nodes already in
   `completed_nodes` and continuing at the first unfinished node.
5. Downstream nodes still receive their declared `context:` inputs, because the
   restored context carries upstream outputs.

Unknown checkpoint ids and mismatched workflows fail loudly (`ValueError`).

### When checkpoints are written

- After **every** successfully completed node (`IN_PROGRESS`).
- On a node failure (`FAILED`) — the failing node is recorded with its error.
- On a gate that does not pass (`FAILED`) — nothing new ran, so the record shows how
  far the run got before being blocked.
- At the end of a successful run (`COMPLETED`).
- A `--dry-run` writes **no** checkpoints: planning is not execution.

---

## Managing the store

| Command | Effect |
|---------|--------|
| `orchestrate checkpoint list --project P [--workflow WF-NNNN]` | List checkpoints, newest first |
| `orchestrate checkpoint clean --project P [--workflow WF-NNNN] [--keep N]` | Delete all but the newest `N` (default 10) |
| `orchestrate checkpoint delete --project P --checkpoint CP-NNNN` | Delete one checkpoint |

Listing is ordered by `created_at`, with the checkpoint number as a deterministic
tiebreaker (timestamps have second resolution, so ties are common — without the
tiebreaker `clean` could keep the oldest instead of the newest).

---

## Limitations (known, explicit)

- **Local disk only.** The store is a directory inside the project; there is no
  distributed/shared backend.
- **Manual retention.** Nothing prunes checkpoints automatically; call
  `checkpoint clean` (or a scheduled job) to bound growth.
- **Concurrent writers of the same project** can race on the next checkpoint id.
  Atomic writes prevent corruption, but two simultaneous runs of the same workflow
  should be avoided.

---

## Related

- [Workflows](workflows.md) — the DAG model, nodes, edges and gates.
- [ADR-0026](../adr/ADR-0026-workflow-checkpoint-recovery.json) — why this design.
- `SCHEMAS/checkpoint/checkpoint.schema.json` — the record contract.
- `SCRIPTS/se_core/orchestration/checkpoint.py` — `CheckpointManager`.
- `TESTS/test_orchestrate_checkpoint.py` — the behaviour pinned by tests.
