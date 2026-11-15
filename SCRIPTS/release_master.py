"""Release helper for the Master System version.

The script automates the mechanical part of a release, never the decision:

* ``--check`` verifies that every active version reference agrees with
  ``VERSION`` and that the published git tags agree with it too.
* ``--check --ci`` reports a drift of the release state as operational
  (exit 3) instead of blocking (exit 1).
* ``--bump patch|minor --reason ...`` updates those references, regenerates the
  OpenCode adapter, rebases the documentation baseline, and runs validation.
* ``--dry-run`` shows the plan without writing.

Historical references (ADRs, old changelog entries, integration notes) are never
rewritten. The operator still decides whether a change is a patch, a minor, or
no release at all.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from se_core.paths import load_json, now_utc, repo_root

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
README_VERSION_RE = re.compile(
    r"(?m)^(?P<prefix>> Version )(?P<version>\d+\.\d+\.\d+)"
    r"(?P<dash> [\u2014-] Status:)"
)
VERSIONING_VERSION_RE = re.compile(
    r"(?P<prefix>Current version: \*\*)(?P<version>\d+\.\d+\.\d+)(?P<suffix>\*\*)"
)
CHANGELOG_VERSION_RE = re.compile(r"(?m)^## \[(?P<version>\d+\.\d+\.\d+)\]")

# CI exit codes. They mirror INTEGRATIONS/ci/scripts/se_ci_common.py, the
# canonical home of the CI exit-code contract: SCRIPTS/ must not depend on
# INTEGRATIONS/, so the values are mirrored here and parity-tested
# (TESTS/test_release_master_tags.py). No new exit code is invented.
EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_USAGE = 2
EXIT_OPERATIONAL = 3


class ReleaseError(RuntimeError):
    """A release precondition or update failed."""


def normalize_version(version: str) -> str:
    value = str(version).strip()
    if not SEMVER_RE.fullmatch(value):
        raise ReleaseError(f"invalid SemVer version: {version!r}")
    return value


def version_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = normalize_version(version).split(".")
    return int(major), int(minor), int(patch)


def read_version(root: Path | str | None = None) -> str:
    root = Path(root) if root is not None else repo_root()
    try:
        return normalize_version((root / "VERSION").read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReleaseError(f"cannot read VERSION: {exc}") from exc


def bump_version(version: str, part: str) -> str:
    major, minor, patch = version_tuple(version)
    if part == "patch":
        patch += 1
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ReleaseError(f"unknown bump kind: {part!r}")
    return f"{major}.{minor}.{patch}"


def plan_release(root: Path | str, part: str) -> str:
    """Return the next version, refusing a major jump while still on ``0.x``."""
    current = read_version(root)
    if part == "major" and version_tuple(current)[0] == 0:
        raise ReleaseError(
            "major bump from 0.x is not allowed by the versioning strategy; "
            "use a minor bump"
        )
    return bump_version(current, part)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseError(f"cannot read {path}: {exc}") from exc


def _json_text(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _write_text_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _replace_version_value(
    text: str, pattern: re.Pattern, version: str, label: str
) -> str:
    def replacement(match: re.Match) -> str:
        return (
            match.group("prefix")
            + version
            + (match.groupdict().get("dash") or match.groupdict().get("suffix") or "")
        )

    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise ReleaseError(f"{label}: current version marker not found")
    return updated


def _changelog_release(
    text: str, version: str, reason: str, released_on: str | None = None
) -> str:
    if any(
        match.group("version") == version
        for match in CHANGELOG_VERSION_RE.finditer(text)
    ):
        return text
    marker = "## [Unreleased]"
    marker_at = text.find(marker)
    if marker_at < 0:
        raise ReleaseError("MASTER SYSTEM/CHANGELOG.md: ## [Unreleased] not found")
    line_end = text.find("\n", marker_at)
    if line_end < 0:
        line_end = len(text) - 1
    released_on = released_on or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bullet = reason.strip().replace("\n", "\n  ")
    block = f"\n## [{version}] - {released_on}\n\n### Changed\n\n- {bullet}\n"
    return text[: line_end + 1] + block + text[line_end + 1 :]


def plan_updates(
    root: Path | str,
    new_version: str,
    reason: str,
    *,
    update_changelog: bool = True,
) -> dict[Path, str]:
    """Compute every text update before writing anything.

    Building the full update set first makes the operation all-or-nothing for the
    version markers: a missing README/current-version marker fails before any file
    is touched.
    """
    root = Path(root)
    current = read_version(root)
    new_version = normalize_version(new_version)
    if version_tuple(new_version) <= version_tuple(current):
        raise ReleaseError(
            f"new version {new_version} must be greater than current {current}"
        )
    if not reason.strip():
        raise ReleaseError("a release reason is required")

    updates: dict[Path, str] = {}

    updates[root / "VERSION"] = new_version + "\n"

    system = load_json(root / "SYSTEM.json")
    system["master_system_version"] = new_version
    updates[root / "SYSTEM.json"] = _json_text(system)

    updates[root / "MASTER SYSTEM" / "VERSION"] = new_version + "\n"

    manifest = load_json(root / "MASTER SYSTEM" / "MANIFEST.json")
    manifest["master_system_version"] = new_version
    manifest["updated_at"] = now_utc()
    updates[root / "MASTER SYSTEM" / "MANIFEST.json"] = _json_text(manifest)

    readme = _text(root / "README.md")
    updates[root / "README.md"] = _replace_version_value(
        readme, README_VERSION_RE, new_version, "README.md"
    )

    versioning = _text(root / "DOCS" / "reference" / "versioning.md")
    updates[root / "DOCS" / "reference" / "versioning.md"] = _replace_version_value(
        versioning, VERSIONING_VERSION_RE, new_version, "DOCS/reference/versioning.md"
    )

    if update_changelog:
        changelog = _text(root / "MASTER SYSTEM" / "CHANGELOG.md")
        updates[root / "MASTER SYSTEM" / "CHANGELOG.md"] = _changelog_release(
            changelog, new_version, reason
        )

    return updates


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _rebase_coverage(root: Path, new_version: str, reason: str, actor: str) -> list[str]:
    baseline = root / "DOCS" / "coverage-baseline.json"
    if not baseline.exists():
        return []
    from se_core.commands import _record_coverage_baseline_rebase

    result = _record_coverage_baseline_rebase(
        root, actor, f"release {new_version}: {reason.strip()}"
    )
    if result.get("error"):
        raise ReleaseError(f"coverage baseline rebase failed: {result['error']}")
    if not result.get("written"):
        return []
    return [
        "DOCS/coverage-baseline.json",
        "DOCS/coverage-baseline.log.jsonl",
    ]


def apply_release(
    root: Path | str,
    new_version: str,
    reason: str,
    *,
    regenerate_adapter: bool = True,
    update_changelog: bool = True,
    rebase_coverage: bool = True,
    actor: str = "operator",
) -> list[str]:
    """Write a release and return the repository-relative paths it changed."""
    root = Path(root)
    updates = plan_updates(
        root, new_version, reason, update_changelog=update_changelog
    )
    for path, text in updates.items():
        _write_text_lf(path, text)

    changed = [_relative(root, path) for path in updates]

    if regenerate_adapter:
        from se_core.opencode.generator import generate

        result = generate(root, root / ".opencode")
        if result.get("status") != "PASS":
            errors = "; ".join(result.get("errors", [])[:5])
            raise ReleaseError(f"OpenCode adapter generation failed: {errors}")
        changed.append(".opencode/adapter-manifest.json")

    if rebase_coverage:
        changed.extend(
            _rebase_coverage(root, normalize_version(new_version), reason, actor)
        )

    return sorted(set(changed))


def check_reference_consistency(root: Path | str | None = None) -> list[str]:
    """Compare every active version reference with ``VERSION``.

    These are the references the release machinery rewrites: the working tree
    must be coherent with itself.
    """
    root = Path(root) if root is not None else repo_root()
    issues: list[str] = []
    try:
        version = read_version(root)
    except ReleaseError as exc:
        return [str(exc)]

    def check_text(relative: str, pattern: re.Pattern, label: str) -> None:
        path = root / relative
        if not path.exists():
            issues.append(f"{label}: missing")
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"{label}: unreadable ({exc})")
            return
        match = pattern.search(text)
        if not match:
            issues.append(f"{label}: current version marker not found")
        elif match.group("version") != version:
            issues.append(
                f"{label}: {match.group('version')} != VERSION ({version})"
            )

    def check_json(relative: str, key: str) -> dict:
        path = root / relative
        if not path.exists():
            issues.append(f"{relative}: missing")
            return {}
        try:
            data = load_json(path)
        except Exception as exc:  # noqa: BLE001 - report, never crash the check
            issues.append(f"{relative}: unreadable ({exc})")
            return {}
        actual = data.get(key)
        if actual != version:
            issues.append(f"{relative}: {key} {actual!r} != VERSION ({version})")
        return data if isinstance(data, dict) else {}

    check_json("SYSTEM.json", "master_system_version")
    check_json("MASTER SYSTEM/MANIFEST.json", "master_system_version")

    dist_version = root / "MASTER SYSTEM" / "VERSION"
    if not dist_version.exists():
        issues.append("MASTER SYSTEM/VERSION: missing")
    else:
        try:
            actual = dist_version.read_text(encoding="utf-8").strip()
        except OSError as exc:
            issues.append(f"MASTER SYSTEM/VERSION: unreadable ({exc})")
        else:
            if actual != version:
                issues.append(f"MASTER SYSTEM/VERSION: {actual} != VERSION ({version})")

    adapter = check_json(".opencode/adapter-manifest.json", "adapter_version")
    if adapter:
        actual = adapter.get("engine_version")
        if actual != version:
            issues.append(
                f".opencode/adapter-manifest.json: engine_version {actual!r} "
                f"!= VERSION ({version})"
            )

    check_text("README.md", README_VERSION_RE, "README.md")
    check_text(
        "DOCS/reference/versioning.md",
        VERSIONING_VERSION_RE,
        "DOCS/reference/versioning.md",
    )
    return issues


# --------------------------------------------------------------------------- #
# Release state (the published git tags)
# --------------------------------------------------------------------------- #


def _git_runner():
    """The read-only git runner used to inspect the release state."""
    from se_core.upgrade import default_git_runner

    return default_git_runner()


def _is_git_checkout(root: Path) -> bool:
    """True when ``root`` is the root of a git working tree.

    A directory that is merely *inside* another repository is not this
    repository: its tags would be the tags of somebody else.
    """
    result = _git_runner()(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(root), timeout=30
    )
    if getattr(result, "returncode", 1) != 0:
        return False
    top = (getattr(result, "stdout", "") or "").strip()
    if not top:
        return False
    try:
        return Path(top).resolve() == root.resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return False


def _tagged_version(root: Path, tag: str) -> str | None:
    """The ``VERSION`` file inside the commit the tag publishes."""
    result = _git_runner()(
        ["git", "show", f"{tag}:VERSION"], cwd=str(root), timeout=30
    )
    if getattr(result, "returncode", 1) != 0:
        return None
    return (getattr(result, "stdout", "") or "").strip() or None


def check_release_consistency(root: Path | str | None = None) -> list[str]:
    """Compare the published release tags with ``VERSION``.

    The active references prove that the working tree is coherent; the tags
    prove that a release was actually published for that version. Without this
    comparison a stale ``VERSION`` (a tag newer than it) or a tag published
    from a commit that never bumped ``VERSION`` stays invisible: the check
    reports PASS on a repository whose release state is wrong.
    """
    root = Path(root) if root is not None else repo_root()
    try:
        version = read_version(root)
    except ReleaseError as exc:
        return [str(exc)]

    if not _is_git_checkout(root):
        # Outside a git checkout there is no release state to judge.
        return []

    from se_core.upgrade import list_local_tags, parse_semver

    listed = list_local_tags(_git_runner(), cwd=str(root))
    if listed.get("error"):
        return [f"git tags: cannot list the release tags ({listed['error']})"]

    published: dict[tuple[int, int, int], str] = {}
    for tag in listed.get("tags") or []:
        parsed = parse_semver(tag)
        if parsed is None:
            continue
        published.setdefault(parsed, tag)

    if not published:
        return ["git tags: no release tag found in this repository"]

    issues: list[str] = []
    current = version_tuple(version)
    owner = published.get(current)
    if owner is None:
        issues.append(
            f"git tags: no release tag publishes VERSION ({version}) "
            f"(expected 'v{version}')"
        )
    for parsed in sorted(published):
        if parsed <= current:
            continue
        tag = published[parsed]
        newer = ".".join(str(part) for part in parsed)
        issues.append(f"git tag {tag}: {newer} != VERSION ({version})")
        tagged = _tagged_version(root, tag)
        if tagged and tagged != newer:
            issues.append(f"git tag {tag}: tagged VERSION is {tagged} != {newer}")
    if owner is not None:
        tagged = _tagged_version(root, owner)
        if tagged and tagged != version:
            issues.append(f"git tag {owner}: tagged VERSION is {tagged} != {version}")
    return issues


def check_consistency(root: Path | str | None = None) -> list[str]:
    """Every consistency issue: the active references and the release state."""
    return check_reference_consistency(root) + check_release_consistency(root)


def check_exit_code(
    reference_issues, release_issues, *, ci: bool = False
) -> int:
    """Map the two consistency dimensions onto the CI exit-code contract.

    * A drift of the active references (the working tree disagrees with
      ``VERSION``) blocks everywhere: it is a validation failure of the change
      under test.
    * A drift of the release state (the published tags disagree with
      ``VERSION``) blocks the operator-facing check, but in CI mode it is
      operational (exit 3): the tags are published outside the pull request,
      so a historical drift must not redden the pipeline forever.
    """
    if reference_issues:
        return EXIT_VALIDATION
    if release_issues:
        return EXIT_OPERATIONAL if ci else EXIT_VALIDATION
    return EXIT_OK


def _git_dirty(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(f"git status failed: {result.stderr.strip()}")
    return result.stdout.strip() or None


def _run_command(label: str, command: list[str], root: Path) -> tuple[int, str]:
    print(f"Running {label}...")
    result = subprocess.run(
        command,
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if label == "tests":
        print("\n".join(output.splitlines()[-8:]))
    elif output:
        print(output)
    return result.returncode, output


def run_validation(root: Path, *, run_tests: bool) -> list[str]:
    commands = [
        ("validate", [sys.executable, "SCRIPTS/se.py", "validate"]),
        ("doctor", [sys.executable, "SCRIPTS/se.py", "doctor"]),
    ]
    if run_tests:
        commands.append(("tests", [sys.executable, "TESTS/run_tests.py"]))
    failures = []
    for label, command in commands:
        code, _ = _run_command(label, command, root)
        if code != EXIT_OK:
            failures.append(label)
    # The release tag is published after the merge, so an unpublished or a
    # stale tag is operational here: it must not block the release preparation.
    code, _ = _run_command(
        "release",
        [sys.executable, "SCRIPTS/release_master.py", "--check", "--ci"],
        root,
    )
    if code not in (EXIT_OK, EXIT_OPERATIONAL):
        failures.append("release")
    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check or apply Master System version references.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify every active version reference against VERSION",
    )
    mode.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        help="advance VERSION and synchronise the active references",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="release reason recorded in CHANGELOG and the coverage ledger",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --bump: print the plan without writing",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help=(
            "with --check: report a drift of the published release state as "
            "operational (exit 3) instead of blocking (exit 1)"
        ),
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="with --bump: run validate and doctor only, not the full test suite",
    )
    parser.add_argument(
        "--skip-changelog",
        action="store_true",
        help="with --bump: leave MASTER SYSTEM/CHANGELOG.md untouched",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="with --bump: allow a working tree with uncommitted changes",
    )
    parser.add_argument(
        "--actor",
        default="operator",
        help="actor recorded in the coverage baseline ledger (default: operator)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    root = repo_root()

    if args.ci and not args.check:
        parser.error("--ci is only valid with --check")

    if args.check:
        if args.dry_run:
            parser.error("--dry-run is only valid with --bump")
        reference = check_reference_consistency(root)
        release = check_release_consistency(root)
        code = check_exit_code(reference, release, ci=args.ci)
        if code == EXIT_OK:
            print(f"Release check: PASS (VERSION {read_version(root)})")
            return EXIT_OK
        if code == EXIT_OPERATIONAL:
            print("Release check: OPERATIONAL")
            print("  The active references agree with VERSION, but the published")
            print("  release state does not:")
            for issue in release:
                print(f"  - {issue}")
            return EXIT_OPERATIONAL
        print("Release check: FAIL")
        for issue in reference + release:
            print(f"  - {issue}")
        return EXIT_VALIDATION

    if not args.reason.strip():
        parser.error("--reason is required with --bump")

    try:
        current = read_version(root)
        new_version = plan_release(root, args.bump)
        print(f"Release: {current} -> {new_version} ({args.bump})")
        if args.dry_run:
            print("Dry run: no files written.")
            return 0

        if not args.allow_dirty:
            dirty = _git_dirty(root)
            if dirty:
                raise ReleaseError(
                    "working tree is not clean; commit or stash the changes "
                    "first (or use --allow-dirty)"
                )

        changed = apply_release(
            root,
            new_version,
            args.reason,
            update_changelog=not args.skip_changelog,
            actor=args.actor,
        )
        print("Updated:")
        for path in changed:
            print(f"  - {path}")

        failures = run_validation(root, run_tests=not args.skip_tests)
        if failures:
            print(f"Release validation: FAIL ({', '.join(failures)})")
            return 1
        print(
            f"Release {new_version} prepared. Review the diff, commit it, "
            f"and tag v{new_version} after merge."
        )
        return 0
    except ReleaseError as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
