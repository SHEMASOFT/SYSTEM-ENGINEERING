#!/usr/bin/env python3
"""Verify that the SE checkout matches the release the product declares.

Contract verified here (and only this):

1. ``PROJECT.json`` declares ``master_system_version`` as ``X.Y.Z``.
2. The checked-out SE ``VERSION`` is exactly that version.
3. A local git tag publishes that exact version (``vX.Y.Z`` preferred, then ``X.Y.Z``).
4. With ``--require-exact-tag``, ``HEAD`` is the commit that tag points to.
5. With ``--remote <name>``, the same tag exists on that remote.

This proves *tag existence and version agreement*. It does NOT prove
cryptographic integrity or trusted provenance: git tags are mutable refs and
this adapter performs no signature verification. See INTEGRATIONS/ci/README.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from se_ci_common import (
    STATUS_PASS,
    OperationalError,
    check_python_version,
    emit,
    load_json,
    make_report,
    operational_report,
    resolve_project,
    resolve_se_root,
)

STEP = "version"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def normalize_tag(tag) -> str:
    text = str(tag).strip()
    if text.startswith("refs/tags/"):
        text = text[len("refs/tags/") :]
    if text.endswith("^{}"):
        text = text[:-3]
    return text


def find_tag_for_version(tags, version):
    """Mirror of ``se_core.upgrade.find_tag_for_version`` (parity-tested).

    Prefers ``v<version>`` and falls back to ``<version>``; returns ``None``
    when no tag publishes that exact version.
    """
    if not version:
        return None
    normalized = {normalize_tag(tag) for tag in tags or []}
    for candidate in (f"v{version}", str(version)):
        if candidate in normalized:
            return candidate
    return None


def _git(se_root: Path, *arguments: str, timeout: int = 30) -> str:
    argv = ["git", *arguments]
    try:
        completed = subprocess.run(
            argv,
            cwd=str(se_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise OperationalError(
            f"cannot verify the release: git is not available ({exc})",
            code="GIT_MISSING",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OperationalError(
            f"git {' '.join(arguments)} timed out after {timeout}s", code="GIT_TIMEOUT"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-800:]
        raise OperationalError(
            f"git {' '.join(arguments)} failed in {se_root}: {detail}", code="GIT_FAILED"
        )
    return (completed.stdout or "").strip()


def local_tags(se_root: Path) -> list:
    output = _git(se_root, "tag", "--list")
    return [line.strip() for line in output.splitlines() if line.strip()]


def remote_tags(se_root: Path, remote: str) -> list:
    output = _git(se_root, "ls-remote", "--tags", "--refs", remote)
    tags = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            tags.append(normalize_tag(parts[1]))
    return tags


def tag_commit(se_root: Path, tag: str) -> str:
    return _git(se_root, "rev-list", "-n", "1", tag)


def head_commit(se_root: Path) -> str:
    return _git(se_root, "rev-parse", "HEAD")


def declare_version(project) -> str:
    manifest = load_json(project / "PROJECT.json")
    version = manifest.get("master_system_version")
    if not isinstance(version, str) or not SEMVER.match(version):
        raise OperationalError(
            "PROJECT.json master_system_version is missing or not X.Y.Z "
            f"(got {version!r}); the SE release to verify cannot be resolved",
            code="VERSION_DECLARED",
        )
    return version


def engine_version(se_root: Path) -> str:
    path = se_root / "VERSION"
    try:
        version = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise OperationalError(f"cannot read {path}: {exc}", code="VERSION_ENGINE") from exc
    if not SEMVER.match(version):
        raise OperationalError(
            f"SE VERSION is not X.Y.Z (got {version!r})", code="VERSION_ENGINE"
        )
    return version


def run(args) -> dict:
    project = None
    details = {}
    try:
        check_python_version()
        se_root = resolve_se_root(args.se_root)
        project = resolve_project(args.project)

        declared = declare_version(project)
        engine = engine_version(se_root)
        details = {"declared_version": declared, "se_version": engine}
        if declared != engine:
            raise OperationalError(
                f"version mismatch: PROJECT.json declares {declared} but the SE checkout "
                f"is {engine}; check out the release that the product pins",
                code="VERSION_MISMATCH",
            )

        tags = local_tags(se_root)
        tag = find_tag_for_version(tags, declared)
        if tag is None:
            raise OperationalError(
                f"declared version {declared} has no local release tag "
                f"(expected 'v{declared}' or '{declared}'); fetch tags or publish the release",
                code="RELEASE_UNRESOLVED",
            )
        details["tag"] = tag
        details["tag_source"] = "local"

        if args.expected_ref:
            expected = normalize_tag(args.expected_ref)
            if expected != tag:
                raise OperationalError(
                    f"--expected-ref {args.expected_ref!r} does not match the release tag "
                    f"{tag!r} for declared version {declared}",
                    code="REF_MISMATCH",
                )
            details["expected_ref"] = args.expected_ref

        if args.require_exact_tag:
            tagged = tag_commit(se_root, tag)
            head = head_commit(se_root)
            if tagged != head:
                raise OperationalError(
                    f"the checked-out commit {head[:12]} is not the release tag {tag} "
                    f"({tagged[:12]}); check out the tag itself",
                    code="HEAD_NOT_TAGGED",
                )
            details["exact_tag"] = True

        if args.remote:
            published = remote_tags(se_root, args.remote)
            if find_tag_for_version(published, declared) is None:
                raise OperationalError(
                    f"declared version {declared} has no tag on remote '{args.remote}'; "
                    "the required release cannot be resolved",
                    code="RELEASE_UNPUBLISHED",
                )
            details["remote"] = args.remote
            details["tag_source"] = "local+remote"

        details["provenance_guarantee"] = "tag-existence-only (no signature verification)"
        return make_report(
            STEP,
            STATUS_PASS,
            project=project,
            summary=f"SE release {tag} matches PROJECT.json ({declared})",
            details=details,
        )
    except OperationalError as exc:
        return operational_report(STEP, exc, project=project, details=details)
    except Exception as exc:  # noqa: BLE001 - never let an adapter bug look like a PASS
        return operational_report(
            STEP,
            OperationalError(f"unexpected adapter error: {exc}", code="ADAPTER_ERROR"),
            project=project,
            details=details,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the SE release pinned by the product PROJECT.json."
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Product checkout containing PROJECT.json (default: current directory).",
    )
    parser.add_argument(
        "--se-root",
        default=None,
        help="SYSTEM-ENGINEERING checkout (default: the checkout containing this script).",
    )
    parser.add_argument(
        "--expected-ref",
        default=None,
        help="Ref requested by the caller; must match the resolved release tag.",
    )
    parser.add_argument(
        "--require-exact-tag",
        action="store_true",
        help="Fail unless HEAD is the commit the release tag points to (CI checkouts use this).",
    )
    parser.add_argument(
        "--remote",
        default=None,
        help="Remote name whose published tags must contain the release (e.g. origin).",
    )
    parser.add_argument("--json", action="store_true", help="Emit se-ci.report/1 JSON.")
    parser.add_argument("--output", default=None, help="Write the JSON report to this path.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return emit(run(args), as_json=args.json, output=args.output)


if __name__ == "__main__":
    sys.exit(main())
