"""Project topology: MANAGED vs EXTERNAL/INDEPENDENT classification and init-target resolution.

Policy (CHECKPOINT-015/016):
  - MANAGED:  has a PROJECT.json (or is about to receive one) and participates in the SE
              lifecycle (`se init` allowed, doctor/validate scan it).
  - EXTERNAL: independent project, own governance; may physically live under PROJECTS/;
              PROJECT.json is NOT required; SE tooling is read-only for it and doctor/
              validate do not treat a missing PROJECT.json as a defect.
              Category is declared via metadata.category (additive, optional) in the
              manifest when present; a manifest-less directory with independent-project
              artifacts (.opencode/, AGENTS.md, opencode.json, SDD/) classifies as EXTERNAL.
"""

from __future__ import annotations

from pathlib import Path

from .paths import load_json

PROJECT_CATEGORIES = ("MANAGED", "EXTERNAL")

# Root artifacts that signal an independent (EXTERNAL) project and must never be
# silently created over / overwritten in an existing, non-managed project.
PROTECTED_ROOT_ARTIFACTS = ("AGENTS.md", ".opencode", "opencode.json", "SDD")


def is_independent_dir(project_dir) -> bool:
    """True if the directory has independent-project artifacts (no PROJECT.json needed)."""
    project_dir = Path(project_dir)
    return any((project_dir / name).exists() for name in PROTECTED_ROOT_ARTIFACTS)


def project_category(project_dir) -> str | None:
    """Classify a project directory.

    Returns "MANAGED", "EXTERNAL" or None (unclassified). A manifest declaring
    metadata.category wins; an existing manifest without a category defaults to MANAGED
    (backward compatible); a manifest-less independent directory is EXTERNAL.
    """
    project_dir = Path(project_dir)
    manifest_file = project_dir / "PROJECT.json"
    if manifest_file.exists():
        try:
            manifest = load_json(manifest_file)
        except Exception:
            return "MANAGED"
        category = (manifest.get("metadata") or {}).get("category")
        if category in PROJECT_CATEGORIES:
            return category
        return "MANAGED"
    if is_independent_dir(project_dir):
        return "EXTERNAL"
    return None


def project_skip_roots(root) -> list:
    """Directories under PROJECTS/ that SE must not scan or alter.

    EXTERNAL (both declared and manifest-less independent) and unclassified directories
    are returned; MANAGED project directories are not.
    """
    root = Path(root)
    projects_dir = root / "PROJECTS"
    if not projects_dir.is_dir():
        return []
    out = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if project_category(entry) != "MANAGED":
            out.append(entry)
    return out


def resolve_init_target(name: str, cwd: Path, root: Path):
    """Deterministically resolve the `se init <name>` target.

    Rules:
      - absolute paths are used as-is;
      - bare names (no separators) resolve under PROJECTS/<name> when it exists, else to
        cwd/<name> only when that directory already exists (no implicit directory
        creation outside PROJECTS);
      - multi-part relative paths resolve against the current directory.

    Returns (target, code, note): target may be None when code != 0 (caller prints the
    note and returns the code).
    """
    name = str(name or "").strip()
    if not name:
        return None, 2, "a project path is required"
    raw = Path(name)
    if raw.is_absolute():
        return raw, 0, ""
    if len(raw.parts) == 1:
        managed = root / "PROJECTS" / raw.parts[0]
        if managed.exists():
            return managed, 0, "resolved under PROJECTS/"
        cwd_candidate = cwd / raw.parts[0]
        if cwd_candidate.exists():
            return cwd_candidate, 0, "resolved relative to the current directory"
        return None, 2, (
            f"cannot resolve bare project name '{name}': no PROJECTS/{raw.parts[0]} and "
            f"no {cwd_candidate}"
        )
    return cwd / raw, 0, ""