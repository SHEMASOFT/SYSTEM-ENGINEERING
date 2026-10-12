"""System doctor: validates the Master System installation and environment.

Produces PASS / WARN / FAIL results. Never reports PASS for something it could not
actually verify.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

from .paths import load_json, repo_root
from .projects import project_category, project_skip_roots
from .schemas import HAVE_JSONSCHEMA, check_schema, load_schemas

REQUIRED_DIRS = [
    "CORE", "DOMAINS", "AGENTS", "SCHEMAS", "TEMPLATES",
    "COMMANDS", "SCRIPTS", "POLICIES", "DOCS", "TESTS", "INTEGRATIONS",
    # Structurally essential: hard dependencies of check_manifests,
    # check_project_alignment and check_contracts. They used to live only in
    # ALLOWED_ROOT_DIRS, which meant their absence was tolerated as "extra
    # but expected" instead of being reported as a missing part of the layout.
    "MASTER SYSTEM", "PROJECTS", "SKILLS",
    # Vendored console ships with the system:
    "SE-CONSOLE",
    # SE Installer package (unified installer for SE + MCPs + runtimes):
    "SE-INSTALLER",
]

REQUIRED_FILES = [
    "README.md",
    "VERSION",
    "SYSTEM.json",
    ".gitignore",
    "CORE/lifecycle/lifecycle.json",
    "CORE/gates/gates.json",
    "CORE/tasks/task-states.json",
    "CORE/artifacts/artifact-types.json",
    "CORE/policies/permissions.json",
    "CORE/evidence/evidence-types.json",
    "CORE/decisions/decision-types.json",
    "CORE/capabilities/capabilities.json",
    "SCHEMAS/index.json",
    "COMMANDS/commands.json",
]

# --- Root layout contract -------------------------------------------------
#
# The repository root is a governed surface: every entry there is either part of
# the declared layout or a defect. REQUIRED_DIRS/REQUIRED_FILES answer "is the
# layout present?"; the two sets below answer "is anything extra there?". Without
# the second question the root accumulates one-shot patch scripts, test output and
# stray records indefinitely while every presence check stays green.

ALLOWED_ROOT_FILES = {
    ".gitignore",
    ".gitattributes",           # LF normalization: content hashes must be stable on every platform
    "LICENSE",                  # MIT license terms
    "CONTRIBUTING.md",          # contribution guide enforced by CI
    "README.md",
    "SYSTEM.json",
    "VERSION",
    "opencode.jsonc",           # project-level opencode configuration
    "resolver-config.json",     # consumed by se_core.opencode.resolvers.DocumentResolver
    "SECURITY_AUDIT_E1_E7.md",  # audit report, no registered home yet (open decision)
}

ALLOWED_ROOT_DIRS = set(REQUIRED_DIRS) | {
    ".opencode",                # deployed adapter, audited by check_adapter
    ".github",                  # issue/PR templates and CI workflows
}

# Runtime noise: transient by definition, already covered by .gitignore, and not a
# governance signal. Deliberately excluded from the contract instead of reported.
# `.git` belongs here for the same reason as the caches: VCS metadata is repository
# infrastructure, not an entry the layout contract has an opinion about. Registering
# it in ALLOWED_ROOT_DIRS would be wrong — that set answers "is this part of the
# declared system?", and the answer for version-control metadata is no.
IGNORED_ROOT_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", ".atl", ".codegraph", ".codegraph-wsl",
                      # Runtime state produced by `se install` / skills: local operator
                      # scripts, lifecycle state + backups, and memory records. Gitignored
                      # and not part of the source layout contract.
                      ".local", ".se", "MEMORY"}

# Provenance in these locations records what already happened rather than
# telling a reader what to do now, so a forbidden path there is the historical
# record and not live guidance: generated reports, audits and evidence, the
# numbered initiative records, the completed relocation log, the detector's own
# token fixtures, and gitignored tool caches. Rewriting them would falsify the
# record of what was done.
#
# This is a declared, narrow list, not a suppression switch. Anything not named
# here stays a WARN, so an undeclared tree that accumulates host paths still gets
# caught. Measured against this repository, the live reference documents
# (architecture.md, commands.md, development-workflow.md) carry zero hits; the
# probe/test/consolidation reports are declared one by one in RECORD_FILES.
# Everything else stays WARN-on-hit: only a deliberate declaration moves a file
# into the record.
#
# Site-specific provenance (for example a real project workspace whose generated
# evidence carries host paths) is declared LOCALLY, in the gitignored
# `.se/doctor-record-roots.json` file — never in this published list.
RECORD_ROOTS = (
    ".atl",
    "DOCS/checkpoints",
    "DOCS/initiatives",
    "DOCS/reference/audits",
    "DOCS/reference/design",
    "DOCS/reference/evidence",
    "DOCS/reference/reviews",
    "TESTS",
)
RECORD_NAME_PREFIXES = ("move-relocation-",)
# Exactly-named historical reports (not a prefix family: a same-naming sibling
# that was never declared must keep WARNing). These DOCS/reference files record
# probes/tests/consolidation work that predates the declaration; rewriting them
# would falsify what happened, so they are declared records.
RECORD_FILES = frozenset({
    "DOCS/reference/execute-observe-artifact-id-consolidation.md",
    "DOCS/reference/execution-engine-v1-1-security-probe-report.md",
    "DOCS/reference/execution-engine-v1-real-execution-probe-report.md",
    "DOCS/reference/long-run-test-v1-plan.md",
    "DOCS/reference/long-run-test-v1-final-verification.md",
    "DOCS/reference/skills/SKILL_DISCOVERY_OPENCODE.md",
})
IGNORED_ROOT_SUFFIXES = {".pyc", ".log", ".tmp"}

SKIP_DIRS = {".git", "__pycache__", ".workspaces", ".venv", "venv", "node_modules", ".cache",
             # Runtime state, never source: lifecycle state + backups, local operator
             # scripts, and memory records produced while running the system.
             ".se", ".local", "MEMORY"}

# Path-relative directories that are never scanned: the internal working-record
# archive. It holds audits, reviews, evidence, checkpoints and initiative reports
# kept locally for provenance; it is gitignored and not part of the published
# system, so its (host-specific) content must not influence any check.
SKIP_REL_DIRS = {"DOCS/internal"}

SECRET_NAME_PATTERNS = (".env", ".pem", ".key", ".p12", ".pfx", "id_rsa", "id_ed25519")
SECRET_NAME_PREFIXES = ("credentials", "secrets", "tokens")

# Absolute host paths are listed for both the WSL view (/mnt/d/) and the Windows
# view (D:/, D:\\). Listing only the WSL form left a real gap: a Windows host path
# on an operational surface was only caught when the hostname also appeared.
FORBIDDEN_INFRA_TOKENS = (
    "servidor-ia",
    "/mnt/d/",
    "D:/",
    "D:\\",
    "shema_db",
    "shemaseg_db",
    "SHEMA_DB",
)

# .jsonc is included because opencode.jsonc declares MCP server paths; leaving it
# out of the scan made a declared dependency surface unreadable by this check.
TEXT_SUFFIXES = {".md", ".json", ".jsonc", ".py", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini"}

# Documentation and this module legitimately contain secret/infrastructure keywords
# (the policy documents and the check definitions themselves).
PREFIX_SCAN_EXEMPT_SUFFIXES = {".md", ".py"}
SELF_SCAN_EXEMPT = {"SCRIPTS/se_core/doctor.py", "CORE/capabilities/capabilities.json"}

# Operational surfaces: these declare how the system runs, so a forbidden token
# here is an external dependency. Everything else (DOCS, TESTS, fixtures) is
# provenance, reported without failing, so historical evidence is never rewritten
# to satisfy a check.
DEPENDENCY_SURFACE_ROOTS = {
    "MASTER SYSTEM", "SCRIPTS", "SCHEMAS", "CORE", "COMMANDS", "AGENTS",
    "DOMAINS", "SKILLS", "TEMPLATES", "POLICIES", "INTEGRATIONS",
}
DEPENDENCY_SURFACE_FILES = {"SYSTEM.json", "VERSION", "resolver-config.json", "opencode.jsonc"}


def _result(check_id, description, status, detail):
    return {"id": check_id, "description": description, "status": status, "detail": detail}


def _walk(root: Path, skip_roots=()):
    """Yield regular files under `root`, pruning excluded directories during traversal.

    `SKIP_DIRS` and `skip_roots` are pruned in place rather than filtered after the
    fact. `Path.rglob` descends into every directory before the caller can discard
    it, so a repository containing `node_modules/` or nested `.git/` trees paid the
    full I/O cost of files it never yielded. Pruning at traversal time keeps the
    cost proportional to the files the checks actually read.

    `followlinks=False` keeps a symlinked directory out of the result set instead of
    walking outside the repository root.
    """
    root = Path(root)
    skip_resolved = set()
    for s in skip_roots:
        try:
            skip_resolved.add(Path(s).resolve())
        except OSError:
            continue

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        keep = []
        for name in dirnames:
            if name in SKIP_DIRS:
                continue
            try:
                rel_dir = (current / name).relative_to(root).as_posix()
            except ValueError:
                rel_dir = ""
            if rel_dir in SKIP_REL_DIRS:
                continue
            try:
                resolved = (current / name).resolve()
            except OSError:
                continue
            if any(resolved == s or s in resolved.parents for s in skip_resolved):
                continue
            keep.append(name)
        dirnames[:] = keep

        for name in filenames:
            yield current / name


# One traversal, shared by every check that needs the full file list. On a slow
# filesystem (WSL 9p/DrvFs stat() is ~18ms) three independent os.walk passes
# over the same tree cost three times the stat() traffic for an identical
# result. The cache is cleared at the start of each run_doctor() call so it can
# never serve a listing produced by an earlier run in the same process.
_FILE_INDEX_CACHE: dict[tuple[str, tuple[str, ...]], tuple[Path, ...]] = {}


def _file_index(root: Path, skip_roots=()) -> tuple[Path, ...]:
    """Return every regular file under `root`, walked at most once per run.

    Shared by check_json_integrity, check_secrets and check_self_containment so
    the tree is traversed once instead of once per check.
    """
    root = Path(root)
    try:
        resolved_root = str(root.resolve())
    except OSError:
        resolved_root = str(root)
    key = (resolved_root, tuple(sorted(str(s) for s in skip_roots)))
    cached = _FILE_INDEX_CACHE.get(key)
    if cached is None:
        cached = tuple(_walk(root, skip_roots))
        _FILE_INDEX_CACHE[key] = cached
    return cached


def check_structure(root: Path):
    missing = [d for d in REQUIRED_DIRS if not (root / d).is_dir()]
    if missing:
        return "FAIL", f"missing directories: {', '.join(missing)}"
    return "PASS", f"{len(REQUIRED_DIRS)} required directories present"


def check_required_files(root: Path):
    missing = [f for f in REQUIRED_FILES if not (root / f).is_file()]
    if missing:
        return "FAIL", f"missing files: {', '.join(missing)}"
    return "PASS", f"{len(REQUIRED_FILES)} required files present"


def check_root_hygiene(root: Path):
    """Fail closed on entries that do not belong in the repository root.

    Severity is asymmetric on purpose. A loose file at the root is always a
    defect: no legitimate artifact type belongs there, so it is a FAIL that
    forces the file into its registered location. An unexpected directory may be
    a real area that was simply never registered in `REQUIRED_DIRS`, so it is a
    WARN naming the decision the operator still owes -- register it or relocate
    it -- rather than a FAIL that blocks work on a directory nobody misplaced.
    """
    try:
        entries = sorted(Path(root).iterdir(), key=lambda p: p.name)
    except OSError as exc:
        return "FAIL", f"root not readable: {exc}"

    unexpected_files = []
    unexpected_dirs = []
    for entry in entries:
        name = entry.name
        if name in IGNORED_ROOT_NAMES or entry.suffix.lower() in IGNORED_ROOT_SUFFIXES:
            continue
        if entry.is_dir():
            if name not in ALLOWED_ROOT_DIRS:
                unexpected_dirs.append(name)
        elif name not in ALLOWED_ROOT_FILES:
            unexpected_files.append(name)

    if unexpected_files:
        return "FAIL", (
            "unexpected files in repository root: "
            + ", ".join(unexpected_files)
            + "; each file must live under its registered location"
        )
    if unexpected_dirs:
        return "WARN", (
            "unregistered directories in repository root: "
            + ", ".join(unexpected_dirs)
            + "; add them to REQUIRED_DIRS or relocate them"
        )
    return "PASS", (
        f"root layout clean: {len(ALLOWED_ROOT_FILES)} allowed files, "
        f"{len(ALLOWED_ROOT_DIRS)} allowed directories, no unexpected entries"
    )


def check_configuration(root: Path):
    try:
        system = load_json(root / "SYSTEM.json")
    except Exception as exc:
        return "FAIL", f"SYSTEM.json unreadable: {exc}"
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if system.get("master_system_version") != version:
        return "FAIL", f"VERSION ({version}) != SYSTEM.json master_system_version ({system.get('master_system_version')})"
    if not system.get("status"):
        return "FAIL", "SYSTEM.json has no status"
    return "PASS", f"version {version}, status {system.get('status')}"


def check_schema_syntax(root: Path):
    if not HAVE_JSONSCHEMA:
        return "FAIL", "jsonschema is not installed; cannot validate schema syntax"
    try:
        schemas = load_schemas(root)
    except Exception as exc:
        return "FAIL", f"cannot load schemas: {exc}"
    bad = []
    for name, schema in schemas.items():
        try:
            check_schema(schema)
        except Exception as exc:
            bad.append(f"{name}: {exc}")
    if bad:
        return "FAIL", "; ".join(bad)
    return "PASS", f"{len(schemas)} schemas are valid JSON Schema"


def check_schema_index(root: Path):
    try:
        index = load_json(root / "SCHEMAS" / "index.json")
    except Exception as exc:
        return "FAIL", f"SCHEMAS/index.json unreadable: {exc}"
    missing = [rel for rel in index.get("schemas", {}).values() if not (root / rel).is_file()]
    if missing:
        return "FAIL", f"schema index references missing files: {', '.join(missing)}"
    return "PASS", f"{len(index.get('schemas', {}))} schema references resolve"


def check_system_refs(root: Path):
    try:
        system = load_json(root / "SYSTEM.json")
    except Exception as exc:
        return "FAIL", f"SYSTEM.json unreadable: {exc}"
    refs = [v for v in system.values() if isinstance(v, str) and v.endswith(".json")]
    missing = [ref for ref in refs if not (root / ref).exists()]
    try:
        artifact_types = load_json(root / "CORE" / "artifacts" / "artifact-types.json")
        for item in artifact_types.get("artifact_types", []):
            schema = item.get("schema")
            if schema and not (root / schema).exists():
                missing.append(schema)
    except Exception as exc:
        return "FAIL", f"CORE/artifacts/artifact-types.json unreadable: {exc}"
    if missing:
        return "FAIL", f"missing referenced files: {', '.join(sorted(set(missing)))}"
    return "PASS", "SYSTEM.json and artifact-type references resolve"


def check_json_integrity(root: Path):
    bad = []
    count = 0
    skip_roots = project_skip_roots(root)
    for path in _file_index(root, skip_roots):
        if path.suffix == ".json":
            count += 1
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                bad.append(f"{path.relative_to(root)}: {exc}")
    if bad:
        return "FAIL", "; ".join(bad[:5])
    return "PASS", f"{count} JSON files parse"


def check_contracts(root: Path):
    from .opencode.validators import audit_contracts

    try:
        errors, counts = audit_contracts(root)
    except Exception as exc:
        return "FAIL", f"contract audit raised: {exc}"
    if errors:
        return "FAIL", "; ".join(errors[:3])
    return "PASS", (
        f"{counts['agents']} agents, {counts['commands']} commands, "
        f"{counts['skills']} skills, {counts['policies']} policies verified"
    )


def check_adapter(root: Path):
    from tempfile import TemporaryDirectory

    from .opencode.generator import generate
    from .opencode.validators import audit_adapter

    try:
        with TemporaryDirectory() as tmp:
            result = generate(root, Path(tmp), dry_run=True)
            if result["status"] != "PASS":
                return "FAIL", "; ".join(result.get("errors", [])[:5])
            planned = {entry["path"] for entry in result["files"]}
            if "adapter-manifest.json" not in planned or "AGENTS.md" not in planned:
                return "FAIL", "generation plan missing adapter-manifest.json or AGENTS.md"

        deployed = Path(root) / ".opencode"
        if not (deployed / "adapter-manifest.json").exists():
            return "PASS", (
                f"{result['counts']['agents']} agents, {result['counts']['commands']} commands, "
                "config valid (dry-run); no deployed .opencode tree to audit"
            )
        errors = audit_adapter(root, deployed)
        if errors:
            return "FAIL", "; ".join(errors[:5])
        return "PASS", (
            f"{result['counts']['agents']} agents, {result['counts']['commands']} commands, "
            "deployed .opencode tree conforms to its manifest (identity, skill discovery "
            "path, frontmatter, content hashes, capability plan)"
        )
    except Exception as exc:
        return "FAIL", f"adapter check raised: {exc}"


def check_manifests(root: Path):
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
        manifest = load_json(root / "MASTER SYSTEM" / "MANIFEST.json")
        system = load_json(root / "SYSTEM.json")
    except Exception as exc:
        return "FAIL", f"manifest check unreadable: {exc}"
    if manifest.get("master_system_version") != version:
        return "FAIL", (
            f"MASTER SYSTEM/MANIFEST.json ({manifest.get('master_system_version')}) "
            f"!= VERSION ({version})"
        )
    if system.get("master_system_version") != version:
        return "FAIL", f"SYSTEM.json ({system.get('master_system_version')}) != VERSION ({version})"
    return "PASS", f"MANIFEST.json and SYSTEM.json pinned to {version}"


def check_manifest_outputs(root: Path):
    """Validate that all bundle output paths in MANIFEST.json resolve to existing files."""
    try:
        manifest = load_json(root / "MASTER SYSTEM" / "MANIFEST.json")
    except Exception as exc:
        return "FAIL", f"MANIFEST.json unreadable: {exc}"
    
    bundles = manifest.get("bundles", {})
    errors = []
    
    for bundle_name, bundle_info in bundles.items():
        output = bundle_info.get("output")
        if not output:
            continue
        target_path = root / output
        if not target_path.exists():
            errors.append(f"Bundle '{bundle_name}' output '{output}' does not exist")
    
    if errors:
        return "FAIL", "; ".join(errors)
    return "PASS", "All bundle output paths resolve to existing files"


def check_runtime(root: Path):
    if sys.version_info < (3, 10):
        return "FAIL", f"Python {sys.version.split()[0]} < 3.10"
    return "PASS", f"Python {sys.version.split()[0]}"


def check_jsonschema(root: Path):
    if HAVE_JSONSCHEMA:
        return "PASS", "jsonschema importable"
    return "FAIL", "jsonschema not importable"


def check_git_available(root: Path):
    if shutil.which("git"):
        return "PASS", "git executable found"
    return "WARN", "git executable not found on PATH"


def check_git_repo(root: Path):
    if (root / ".git").exists():
        return "PASS", "repository is initialized"
    return "WARN", "no .git directory; repository not initialized"


def check_secrets(root: Path):
    hits = []
    skip_roots = project_skip_roots(root)
    for path in _file_index(root, skip_roots):
        name = path.name.lower()
        if name.endswith(SECRET_NAME_PATTERNS):
            hits.append(str(path.relative_to(root)))
        elif name.startswith(SECRET_NAME_PREFIXES) and path.suffix.lower() not in PREFIX_SCAN_EXEMPT_SUFFIXES:
            hits.append(str(path.relative_to(root)))
    if hits:
        return "FAIL", f"possible secret files: {', '.join(hits[:5])}"
    return "PASS", "no obvious secret files"


def _self_containment_class(rel: str) -> str:
    """Classify a forbidden-token hit as `dependency` or `provenance`.

    A forbidden token on an operational surface means the master system needs
    something outside itself to run, which is a real defect. The same token in a
    report, checkpoint, audit or fixture is the record of where the system ran,
    not a requirement: rewriting that history to silence a check would fabricate
    evidence, so provenance is reported rather than failed.
    """
    top = rel.split("/", 1)[0]
    if top in DEPENDENCY_SURFACE_ROOTS:
        return "dependency"
    if rel in DEPENDENCY_SURFACE_FILES:
        return "dependency"
    return "provenance"


def _self_containment_is_record(rel: str, extra_roots: tuple[str, ...] = ()) -> bool:
    """True when a provenance hit is a declared record rather than guidance.

    Only the explicit RECORD_ROOTS (plus the site-local extra roots declared in
    the gitignored ``.se/doctor-record-roots.json``), RECORD_NAME_PREFIXES and
    RECORD_FILES qualify. Nothing else is inferred from a filename, so a tree
    that starts accumulating host paths without being declared keeps reporting as
    live guidance.
    """
    if rel in RECORD_FILES:
        return True
    roots = RECORD_ROOTS + tuple(extra_roots)
    if any(rel == root or rel.startswith(root + "/") for root in roots):
        return True
    name = rel.rsplit("/", 1)[-1]
    return name.startswith(RECORD_NAME_PREFIXES)


#: Optional, gitignored site-local declarations of extra record roots. Runtime
#: state lives with the machine that produced it: a real project workspace whose
#: generated evidence carries host paths is declared here, not in the published
#: RECORD_ROOTS list. Expected shape: a JSON array of root-relative paths.
LOCAL_RECORD_ROOTS_FILE = ".se/doctor-record-roots.json"


def _load_local_record_roots(root: Path) -> tuple[str, ...]:
    path = Path(root) / LOCAL_RECORD_ROOTS_FILE
    if not path.is_file():
        return ()
    try:
        data = load_json(path)
    except Exception:
        return ()
    if not isinstance(data, list):
        return ()
    roots = []
    for item in data:
        text = str(item).replace("\\", "/").strip().strip("/")
        if text:
            roots.append(text)
    return tuple(roots)


def check_self_containment(root: Path):
    dependency: list[tuple[str, str, int]] = []
    guidance: list[tuple[str, str, int]] = []
    record: list[tuple[str, str, int]] = []
    skip_roots = project_skip_roots(root)
    local_roots = _load_local_record_roots(root)
    for path in _file_index(root, skip_roots):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in SELF_SCAN_EXEMPT:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if _self_containment_class(rel) == "dependency":
            bucket = dependency
        elif _self_containment_is_record(rel, local_roots):
            bucket = record
        else:
            bucket = guidance
        for token in FORBIDDEN_INFRA_TOKENS:
            for lineno, line in enumerate(text.splitlines(), 1):
                if token in line:
                    bucket.append((rel, token, lineno))

    def summarize(label, hits):
        by_token = Counter(tok for _, tok, _ in hits)
        counts = ", ".join(f"{tok}={n}" for tok, n in by_token.most_common())
        sample = "; ".join(f"{rel}:{line}" for rel, _, line in hits[:5])
        more = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
        return f"{len(hits)} {label} hit(s) by token [{counts}]; first: {sample}{more}"

    # A forbidden token on an operational surface is a defect: the system needs
    # something outside itself, so that is a FAIL. The same token in a document
    # a reader would follow as live guidance is not a defect, but it is not
    # clean either -- EXTERNAL projects are already out of scope via
    # project_skip_roots, so every path scanned here belongs to something this
    # system owns, and calling that PASS is how owned documentation quietly
    # accumulates host paths while the check reports green. That is a WARN.
    #
    # A declared record tree is the third state: the reference is the history of
    # what was done, it is not an instruction, and it is reported with its exact
    # count rather than dropped.
    if dependency:
        return "FAIL", summarize("dependency", dependency) + f" | guidance hits: {len(guidance)} | record hits: {len(record)}"
    if guidance:
        return "WARN", summarize("guidance", guidance) + f" | record hits: {len(record)} | none on operational surfaces"
    if record:
        return "PASS", summarize("record", record) + " | none in live guidance or operational surfaces"
    return "PASS", "no external infrastructure references"


def check_capabilities(root: Path):
    from .capabilities import check_policies, validate_registry

    try:
        schemas = load_schemas(root)
    except Exception as exc:
        return "FAIL", f"cannot load schemas: {exc}"
    errors = validate_registry(root, schemas=schemas) + check_policies(root)
    if errors:
        return "FAIL", "; ".join(errors[:3])
    return "PASS", "capability registry and declared policies valid"


def check_project_alignment(root: Path):
    """MANAGED projects must be governed by the current MASTER version.

    Detection-only (WARN): reconciliation is a maintenance action performed by
    `se init <project>`, never an implicit mutation of a validation command.
    """
    try:
        master = str(load_json(root / "SYSTEM.json").get("master_system_version") or "")
    except Exception as exc:
        return "FAIL", f"SYSTEM.json unreadable: {exc}"
    stale = []
    projects_dir = root / "PROJECTS"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if project_category(entry) != "MANAGED":
                continue
            try:
                manifest = load_json(entry / "PROJECT.json")
            except Exception:
                continue
            floor = str(manifest.get("master_system_version") or "")
            if floor != master:
                stale.append(f"{entry.name} ({floor} -> {master})")
    if stale:
        return "WARN", (
            "MANAGED project(s) out of date; run `se init <project>` to reconcile: "
            + "; ".join(stale)
        )
    return "PASS", f"all MANAGED projects aligned to master {master}"


def check_baseline_ledger(root: Path):
    """Report the provenance of the coverage baseline.

    Severity follows what the control actually established, not whether the
    files exist. `consistent` is the only PASS, because it is the only state in
    which the newest ledger entry was compared against the baseline and matched.
    The other three mean the check proved nothing, and this module's contract is
    to never report PASS for something it could not verify:

    - `no_log` -> WARN: the ledger was never created, so the control is inactive.
      `coverage_count_test` still passes against `DOCS/coverage-baseline.json`,
      but that baseline is self-certifying -- nothing records who rewrote it or
      why, and hand-editing it then re-running the guardrail is the exact move
      that destroys the evidence of a lost document. WARN names an operator debt,
      not a broken repository, so it does not block unrelated work.
    - `unverified` -> WARN: a ledger exists but its newest entry recorded no
      change, so it compared nothing. Same debt as `no_log` with an artifact
      present, which is worse in appearance only; it stays WARN because no
      contradiction was found.
    - `drift` -> FAIL: the baseline no longer matches what the last entry said it
      would contain, or the ledger is damaged. A recorded hash disagrees with the
      file, which is a contradiction between two governed artifacts and is
      reported as FAIL rather than downgraded to WARN.

    `drift` as FAIL does not produce false positives. Verification coverage is
    bounded by what the last entry recorded, so an incomplete ledger costs
    detections: a hash nobody logged is never re-checked. That asymmetry can
    only miss a hand edit, never invent one -- the FAIL fires on a positive
    mismatch between two recorded values, not on the absence of a record.
    """
    from .commands import _coverage_baseline_log_status

    try:
        status = _coverage_baseline_log_status(Path(root))
    except Exception as exc:
        return "FAIL", f"baseline ledger check raised: {exc}"

    state = status.get("state")
    detail = status.get("detail") or ""

    if state == "consistent":
        return "PASS", detail
    if state == "no_log":
        return "WARN", (
            f"{detail}; the baseline is self-certifying until a rebase records provenance"
        )
    if state == "unverified":
        return "WARN", (
            f"{detail}; rebase the baseline through the governed path to establish provenance"
        )
    return "FAIL", detail


CHECKS = [
    ("structure", "Project structure", check_structure),
    ("required_files", "Required files", check_required_files),
    ("root_hygiene", "Root layout hygiene", check_root_hygiene),
    ("baseline_ledger", "Coverage baseline provenance ledger", check_baseline_ledger),
    ("configuration", "Configuration consistency", check_configuration),
    ("schema_index", "Schema index references", check_schema_index),
    ("system_refs", "System reference integrity", check_system_refs),
    ("schema_syntax", "Schema syntax", check_schema_syntax),
    ("contracts", "Contract layer", check_contracts),
    ("adapter", "OpenCode adapter", check_adapter),
    ("capabilities", "Capability governance", check_capabilities),
    ("project_alignment", "Project version alignment", check_project_alignment),
    ("manifests", "Distribution manifests", check_manifests),
    ("manifest_outputs", "Manifest output paths", check_manifest_outputs),
    ("json_integrity", "JSON integrity", check_json_integrity),
    ("runtime", "Runtime version", check_runtime),
    ("jsonschema", "jsonschema dependency", check_jsonschema),
    ("git_available", "Git availability", check_git_available),
    ("git_repo", "Git repository", check_git_repo),
    ("secrets", "Secret file scan", check_secrets),
    ("self_containment", "Self-containment scan", check_self_containment),
]


def run_doctor(root=None) -> dict:
    root = Path(root) if root else repo_root()
    _FILE_INDEX_CACHE.clear()
    results = []
    for check_id, description, fn in CHECKS:
        try:
            status, detail = fn(root)
        except Exception as exc:  # pragma: no cover - defensive
            status, detail = "FAIL", f"check raised: {exc}"
        results.append(_result(check_id, description, status, detail))

    summary = {
        "PASS": sum(1 for r in results if r["status"] == "PASS"),
        "WARN": sum(1 for r in results if r["status"] == "WARN"),
        "FAIL": sum(1 for r in results if r["status"] == "FAIL"),
    }
    ok = summary["FAIL"] == 0
    return {"root": str(root), "results": results, "summary": summary, "ok": ok}
