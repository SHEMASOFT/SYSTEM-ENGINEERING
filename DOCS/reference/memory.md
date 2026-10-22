# Memory

Memory is where SYSTEM-ENGINEERING records what a project has already learned --
decisions, discoveries, constraints, capabilities, verifications, checkpoints,
session summaries -- so the next session starts from knowledge instead of
re-deriving it.

This page documents the storage model, the `se memory` commands, the optional
semantic reranker, and the convention for injecting memory at the start of a
session. The decision behind it is ADR-0027.

## Storage model

Memory has exactly one source of truth and one disposable cache.

| Layer | Location | Role |
| --- | --- | --- |
| Canonical records | `<project>/memories/MEM-XXXX.json` | The truth. One JSON file per memory, validated against `memory_record` |
| Derived index | `<root>/.se/memory/index.db` | Cache. SQLite + FTS5, gitignored, rebuildable at any time |

Rules that follow from that split:

- **The index is never a source of truth.** Deleting it is a valid recovery, not
  data loss: the next search rebuilds it from the JSON. An unusable index file is
  dropped and rebuilt once, and if that fails, search falls back to a pure-Python
  scan instead of failing.
- **It is optional.** Without SQLite FTS5 the engine still works: the scan
  fallback produces the same contract, only slower.
- **One index per engine root**, not per project, so a cross-project search is a
  single query and no cache is written inside a managed project workspace.
- **Memory IDs are project-scoped.** `MEM-0001` exists in more than one project.
  Operations on a single record require an explicit `--project`, and an unscoped
  lookup resolves to nothing rather than guessing a project. `se memory query`
  is the operation that reaches across projects.

### Record fields worth knowing

| Field | Meaning |
| --- | --- |
| `type` | `decision`, `architecture`, `discovery`, `constraint`, `capability`, `verification`, `checkpoint`, `relationship`, `session`, `prompt` |
| `state` | `active` (default), `archived`, `needs_review`, `deprecated` |
| `topic_key` | Upsert key, not identity. Saving again under the same key revises that record in place and grows `revision_count` |
| `duplicate_count`, `last_seen_at` | Set only when a save is opted into exact dedupe (`--dedupe`) |
| `review_after` | ISO date after which the memory should be revisited |
| `supersedes`, `superseded_by`, `related_memories` | Relation graph; `supersedes` is written from both sides so the pair cannot drift |

`deprecated` is a soft delete: the file is kept, and the record stays out of
`query` and `search` unless it is asked for by name (`query --state deprecated`).
A deprecated record neither captures a `topic_key` nor satisfies exact dedupe.

## Commands

```text
se memory add       --project P --type T --content '<json>' [--tags ...] [--scope ...]
                    [--confidence 0..1] [--related MEM,MEM] [--supersedes MEM]
                    [--topic-key KEY] [--review-after DATE] [--state S] [--dedupe]
se memory query     [--project P] [--type T,T] [--tags a,b] [--by A] [--since D] [--until D]
                    [--tags-mode any|all] [--state S] [--limit N] [--offset N]
se memory get       --memory-id MEM-XXXX [--project P]
se memory search    --query 'text' [--project P] [--type T,T] [--limit N] [--offset N]
                    [--candidates N] [--semantic | --no-semantic]
se memory index     [--rebuild]
se memory link      --memory-id MEM-XXXX --related-id MEM-XXXX --project P
                    [--relation related|supersedes|superseded_by]
se memory update    --memory-id MEM-XXXX --project P --updates '<json>'
se memory supersede --memory-id MEM-XXXX --new-id MEM-XXXX --project P
```

`add` always creates a record unless a key or dedupe says otherwise: `--topic-key`
revises the existing record for that key, and `--dedupe` counts an identical
record instead of copying it. Both are opt-in, because identical text can still
be two genuinely distinct memories.

### Search

`search` is **lexical first**: every term must match (AND), and hits are compact
(`memory_id`, `type`, `score`, `snippet`) so the answer is cheap and the full
record is one `se memory get` away. Scores are backend-relative -- negated bm25
on the index, term frequency on the fallback -- so they order results within one
result set and are not comparable across backends.

## The semantic reranker (optional)

Semantic retrieval is a **reranker, not a retriever**: recall stays lexical, and
embeddings only reorder a bounded window of the candidates lexical search already
returned. A model can therefore promote a memory you would have had to scroll to,
but it can never surface one the lexical pass did not find.

It is off unless a model is installed, and it never touches the network:

1. Put a word-vector text file (the classic `token v1 v2 ...` format, with or
   without its `count dim` header) at `<root>/.se/models/word-vectors.vec`, or
   point `SE_MEMORY_EMBEDDINGS` at one somewhere else.
2. Search. With a model present, `search` reranks automatically; `--no-semantic`
   disables it, and `--semantic` demands it and fails when no model is installed.
3. Watch the reported line. Every search states the reranker that answered (or
   why none did), so an empty result is never confused with a missing model.

Ordering is reciprocal rank fusion of the lexical and semantic rankings, so the
two incomparable score scales are never mixed by arithmetic. Each hit reports
`score` (fused), `lexical_score` (what the backend produced) and `semantic_score`
(the measured similarity), which makes any reordering explainable.

Dependencies and limits:

- The reference path is **pure Python** and always works. `numpy` is an optional
  accelerator, not a requirement; it changes how large a model fits in memory,
  not the ranking.
- A model too large for the dependency-free path is refused with the fix in the
  message (`pip install numpy`) instead of exhausting the machine.
- An explicitly configured path that cannot be read is an error, not a silent
  absence: a typo must not look like "no model installed".
- `--candidates N` (default 50) is the cost bound: it is how many lexical hits
  the reranker is allowed to see, and therefore the boundary of what it can
  promote.

## Session-start convention

Memory is injected through the existing read-only intelligence pipeline; there is
no separate memory service and no extra tool to call.

**At the start of a session**, state what the session is about:

```bash
se intelligence --project PROJECTS/EXAMPLE --memory "topic one" --memory "topic two"
```

This adds a `relevance` block to the report's `memory_context`:

| Field | Meaning |
| --- | --- |
| `queries` | The topics that were searched (a topic nothing can be matched from is dropped) |
| `hits` | Matching memories, in the order the topics were given, each with a snippet |
| `backend` | `fts5`, `scan`, `mixed`, or `null` when nothing was searched |
| `reranker` | The embedding reranker applied, or `null` when none was |

The report still contains what it always did -- totals, types and the most recent
memories -- so `se intelligence` without `--memory` is unchanged.

Behaviour worth knowing:

- Each topic is one query with the same AND semantics as `se memory search`, and
  the merged list is deduplicated and capped at `--memory-limit` (default 10), so
  the injected context stays bounded whatever the caller asks for.
- An unmatched topic is not a failure and an empty hit list is a valid answer;
  `backend` tells you a search engine was there.
- The run stays read-only for project state. The only thing it may touch is the
  disposable index cache under `.se/`, exactly as `se memory search` does.

**At the end of a session**, persist what was learned so the next session starts
warmer:

```bash
se memory add --project PROJECTS/EXAMPLE --type session \
  --content '{"title": "...", "summary": "...", "decisions": [...], "next": [...]}'

se memory add --project PROJECTS/EXAMPLE --type prompt \
  --content '{"title": "...", "prompt": "..."}'
```

Use `--topic-key session-<n>` to revise one running summary instead of
accumulating a session record per restart.

## Shared memory via MCP (SE-MEMORY-SERVER)

SYSTEM-ENGINEERING exposes its memory engine as an MCP server (`se-memory-server`)
so any compatible runtime (OpenCode, Codex, Claude Code, Pi) can search, read,
and save memories without duplicating the engine.

### Tools

| Tool | Permission | Description |
|---|---|---|
| `memory_search` | READ | Search by text. Returns compact hits (id, type, score, snippet). |
| `memory_get` | READ | Full content of a memory by ID. |
| `memory_list` | READ | List memories with filters (types, tags, limit). |
| `memory_save` | WRITE | Save a memory (decision, discovery, constraint, etc.). |
| `memory_checkpoint` | WRITE | Save a checkpoint for task resumption. |

### Registration

The adapter generates `.opencode/mcp/memory-server.json` (portable, `${SE_ROOT}`
placeholders). The Node launcher resolves `python3` or `python` at startup, so the
same entry works on Windows, WSL, Linux and macOS. To activate in OpenCode, add to
`opencode.jsonc`:

```json
"se-memory-server": {
  "type": "local",
  "command": [
    "node",
    "SCRIPTS/se_core/mcp/launch.mjs",
    "SCRIPTS/se_core/mcp/memory_server.py"
  ],
  "environment": {},
  "cwd": "."
}
```

For global config (any directory), use absolute paths:

```json
"se-memory-server": {
  "type": "local",
  "command": [
    "node",
    "D:/servidor-ia/SYSTEM-ENGINEERING/SCRIPTS/se_core/mcp/launch.mjs",
    "D:/servidor-ia/SYSTEM-ENGINEERING/SCRIPTS/se_core/mcp/memory_server.py"
  ],
  "environment": {},
  "cwd": "D:/servidor-ia/SYSTEM-ENGINEERING"
}
```

### Storage scopes

| Scope | Location | When used |
|---|---|---|
| Project | `PROJECTS/<p>/memories/` | Work within a managed project |
| Repo/global | `MEMORY/` (repo root) | Work in the repo without a project |
| External | `~/.se/memory/` | Work outside any repo |

### Concurrency

- File lock via atomic `O_CREAT|O_EXCL` (cross-platform).
- ID generation retries if the target file already exists.
- Upserts by `topic_key` are serialized.
- SQLite index is derived and rebuildable (`se memory index --rebuild`).

### Permissions

- `READ`: search, get, list.
- `WRITE_MEMORY`: save, checkpoint.
- No general filesystem access. No CLI exposure.

## Related

- [architecture.md](architecture.md) -- layers and boundaries
- [commands.md](commands.md) -- the wider command surface
- [schemas.md](schemas.md) -- how the `memory_record` schema is validated
- ADR-0027 -- why memory is internal, and the decisions behind each field
