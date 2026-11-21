"""SE-CONSOLE :: project memory (persistent workspace memory).

Per-project, developer-facing scratchpad that lives outside the canonical
SE tree so it never pollutes `se` state. It is the answer to:

    "I was working on UI, the installer, and I still need to connect X and Y
     -- where did I leave off two months ago?"

Each managed project gets a JSON sidecar file:

    PROJECTS/<project>/.se-console/memory.json

containing:

    {
      "project": "PROJECTS/SHEMASEG",
      "updated_at": "2026-11-21T10:00:00Z",
      "updated_by": "se-console-local-operator",
      "current_focus": "Implementar login UI",
      "next_steps": [
        {"id": "n1", "text": "Conectar API de autenticación con el backend", "done": false},
        {"id": "n2", "text": "Revisar gate G6 de aceptación", "done": false}
      ],
      "notes": [
        {"id": "m1", "text": "Recordar que el endpoint de login está en /api/auth/login", "created_at": "..."}
      ],
      "context": "Estoy arreglando la UI del login y el instalador. Falta conectar el módulo de pagos."
    }

The console never writes to canonical SE artifacts. This file is purely an
operator memory aid. It is read-only for `se`; only the console writes it.

Design rules:
  * Never write to canonical SE artifacts (PROJECT.json, gates, records, etc.).
  * Every entry carries an `id` and timestamps so the user can trace when
    something was noted.
  * `current_focus` answers "what am I working on right now?"
  * `next_steps` answers "what comes next?" in priority order.
  * `notes` is a free-form notebook for anything the developer wants to remember.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

SE_CONSOLE_DIR = ".se-console"
MEMORY_FILE = "memory.json"


def _memory_dir(project_rel: str, se_root: str) -> str:
    return os.path.join(se_root, project_rel.replace("/", os.sep), SE_CONSOLE_DIR)


def _memory_path(project_rel: str, se_root: str) -> str:
    return os.path.join(_memory_dir(project_rel, se_root), MEMORY_FILE)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _actor() -> str:
    return "se-console-local-operator"


def _empty_memory(project_rel: str) -> dict[str, Any]:
    return {
        "project": project_rel,
        "updated_at": _now(),
        "updated_by": _actor(),
        "current_focus": "",
        "next_steps": [],
        "notes": [],
        "context": "",
    }


def load_memory(project_rel: str, se_root: str) -> dict[str, Any]:
    """Return the memory for a project, or an empty skeleton if none exists."""
    path = _memory_path(project_rel, se_root)
    if not os.path.isfile(path):
        return _empty_memory(project_rel)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Backwards compat: ensure all expected keys exist.
        base = _empty_memory(project_rel)
        base.update(data)
        return base
    except (OSError, json.JSONDecodeError):
        return _empty_memory(project_rel)


def save_memory(project_rel: str, se_root: str, data: dict[str, Any]) -> dict[str, Any]:
    """Persist memory for a project. Creates the .se-console dir if needed."""
    mdir = _memory_dir(project_rel, se_root)
    os.makedirs(mdir, exist_ok=True)
    path = _memory_path(project_rel, se_root)
    data = dict(data)
    data["project"] = project_rel
    data["updated_at"] = _now()
    data["updated_by"] = _actor()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def upsert_next_step(
    project_rel: str, se_root: str, step_text: str, step_id: str | None = None
) -> dict[str, Any]:
    """Add a next-step item. Returns the updated memory."""
    mem = load_memory(project_rel, se_root)
    step_id = step_id or f"n{int(time.time() * 1000)}"
    mem["next_steps"].append(
        {"id": step_id, "text": step_text, "done": False, "created_at": _now()}
    )
    return save_memory(project_rel, se_root, mem)


def mark_step_done(
    project_rel: str, se_root: str, step_id: str, done: bool = True
) -> dict[str, Any] | None:
    """Toggle a next-step item done/undone. Returns updated memory or None."""
    mem = load_memory(project_rel, se_root)
    for step in mem.get("next_steps", []):
        if step.get("id") == step_id:
            step["done"] = bool(done)
            step["updated_at"] = _now()
            return save_memory(project_rel, se_root, mem)
    return None


def delete_step(project_rel: str, se_root: str, step_id: str) -> dict[str, Any] | None:
    """Remove a next-step item. Returns updated memory or None."""
    mem = load_memory(project_rel, se_root)
    before = len(mem.get("next_steps", []))
    mem["next_steps"] = [s for s in mem.get("next_steps", []) if s.get("id") != step_id]
    if len(mem["next_steps"]) == before:
        return None
    return save_memory(project_rel, se_root, mem)


def add_note(
    project_rel: str, se_root: str, text: str, note_id: str | None = None
) -> dict[str, Any]:
    """Add a free-form note. Returns the updated memory."""
    mem = load_memory(project_rel, se_root)
    note_id = note_id or f"m{int(time.time() * 1000)}"
    mem["notes"].append(
        {
            "id": note_id,
            "text": text,
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    return save_memory(project_rel, se_root, mem)


def update_note(
    project_rel: str, se_root: str, note_id: str, text: str
) -> dict[str, Any] | None:
    """Update an existing note's text. Returns updated memory or None."""
    mem = load_memory(project_rel, se_root)
    for note in mem.get("notes", []):
        if note.get("id") == note_id:
            note["text"] = text
            note["updated_at"] = _now()
            return save_memory(project_rel, se_root, mem)
    return None


def delete_note(project_rel: str, se_root: str, note_id: str) -> dict[str, Any] | None:
    """Remove a note. Returns updated memory or None."""
    mem = load_memory(project_rel, se_root)
    before = len(mem.get("notes", []))
    mem["notes"] = [n for n in mem.get("notes", []) if n.get("id") != note_id]
    if len(mem["notes"]) == before:
        return None
    return save_memory(project_rel, se_root, mem)


def set_focus(
    project_rel: str, se_root: str, focus: str
) -> dict[str, Any]:
    """Set the current focus sentence. Returns updated memory."""
    mem = load_memory(project_rel, se_root)
    mem["current_focus"] = focus
    return save_memory(project_rel, se_root, mem)


def set_context(
    project_rel: str, se_root: str, context: str
) -> dict[str, Any]:
    """Set the free-form context/notes summary. Returns updated memory."""
    mem = load_memory(project_rel, se_root)
    mem["context"] = context
    return save_memory(project_rel, se_root, mem)
