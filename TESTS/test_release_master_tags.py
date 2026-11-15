"""The published release tags must agree with ``VERSION``.

``release_master.py --check`` compared the active version references
(``VERSION``, ``SYSTEM.json``, ``README.md``, ...) with each other, but never
with the published git tags. A ``VERSION`` that no release published, or a tag
published from a commit that never bumped ``VERSION``, stayed invisible: the
check reported PASS on a repository whose release state was wrong.

The contract asserted here:

* a tag that publishes ``VERSION`` makes the release state coherent;
* a tag newer than ``VERSION`` is a real inconsistency and is reported;
* the tagged commit must carry the version the tag claims to publish;
* the two dimensions (working tree vs. release state) are reported apart, so
  CI can treat a historical tag drift as operational (exit 3) while a broken
  working tree stays a validation failure (exit 1);
* the exit codes are the ones the CI adapter already uses.

Hermetic: every repository is a temporary directory; no network.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

import release_master  # noqa: E402
from release_master import (  # noqa: E402
    EXIT_OK,
    EXIT_OPERATIONAL,
    EXIT_USAGE,
    EXIT_VALIDATION,
    check_consistency,
    check_exit_code,
    check_reference_consistency,
    check_release_consistency,
)

EM_DASH = "\u2014"


def git(root: Path, *arguments: str) -> str:
    """Run a git command in ``root`` and return its output."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed in {root}: {result.stderr.strip()}"
        )
    return result.stdout


def make_repository(root: Path, version: str = "1.2.3") -> Path:
    """A git checkout whose active references all declare ``version``."""
    root = Path(root)
    (root / "MASTER SYSTEM").mkdir(parents=True)
    (root / "DOCS" / "reference").mkdir(parents=True)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "MASTER SYSTEM" / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"> Version {version} {EM_DASH} Status: **foundation / development**.\n",
        encoding="utf-8",
    )
    (root / "DOCS" / "reference" / "versioning.md").write_text(
        f"# Versioning\n\nCurrent version: **{version}**\n", encoding="utf-8"
    )
    support.write_json(root / "SYSTEM.json", {
        "schema_version": "1",
        "name": "SYSTEM ENGINEERING",
        "master_system_version": version,
    })
    support.write_json(root / "MASTER SYSTEM" / "MANIFEST.json", {
        "schema_version": "1",
        "name": "MASTER SYSTEM",
        "master_system_version": version,
        "updated_at": "2026-01-01T00:00:00Z",
    })
    support.write_json(root / ".opencode" / "adapter-manifest.json", {
        "adapter_id": "opencode",
        "adapter_version": version,
        "engine_version": version,
    })
    git(root, "init", "--quiet")
    git(root, "config", "user.email", "tester@example.invalid")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "tag.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "release")
    return root


class ReleaseTagConsistencyTests(unittest.TestCase):
    """The published tags must agree with the declared version."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _repository(self, version: str = "1.2.3") -> Path:
        return make_repository(self.root / "repo", version)

    def test_a_tag_that_publishes_the_version_is_coherent(self):
        root = self._repository("1.2.3")
        git(root, "tag", "v1.2.3")

        self.assertEqual(check_release_consistency(root), [])

    def test_a_tag_newer_than_the_version_is_reported(self):
        root = self._repository("1.2.3")
        git(root, "tag", "v1.2.4")

        issues = check_release_consistency(root)

        self.assertTrue(
            any("v1.2.4" in issue for issue in issues),
            f"the newer tag must be reported: {issues!r}",
        )

    def test_a_version_without_a_release_tag_is_reported(self):
        root = self._repository("1.2.3")
        git(root, "tag", "v1.0.0")

        issues = check_release_consistency(root)

        self.assertTrue(
            any(
                "no release tag publishes VERSION (1.2.3)" in issue for issue in issues
            ),
            f"the missing tag must be reported: {issues!r}",
        )

    def test_a_tag_published_without_a_version_bump_is_reported(self):
        """The tagged commit must carry the version the tag claims to publish."""
        root = self._repository("1.2.3")
        git(root, "tag", "v1.2.4")

        issues = check_release_consistency(root)

        self.assertTrue(
            any("tagged VERSION is 1.2.3 != 1.2.4" in issue for issue in issues),
            f"the tagged content must be reported: {issues!r}",
        )

    def test_a_repository_without_tags_is_reported(self):
        root = self._repository("1.2.3")

        issues = check_release_consistency(root)

        self.assertTrue(
            any("no release tag" in issue for issue in issues),
            f"the missing tags must be reported: {issues!r}",
        )

    def test_a_directory_outside_a_repository_has_no_release_findings(self):
        """There is no release state to judge outside a git checkout."""
        root = self.root / "loose"
        root.mkdir()
        (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")

        self.assertEqual(check_release_consistency(root), [])

    def test_the_two_dimensions_are_reported_apart(self):
        root = self._repository("1.2.3")
        git(root, "tag", "v1.2.4")

        self.assertEqual(check_reference_consistency(root), [])
        self.assertTrue(check_release_consistency(root))
        self.assertEqual(check_consistency(root), check_release_consistency(root))


class ReleaseCheckExitCodeTests(unittest.TestCase):
    """A drift of the release state is operational in CI, never a silent pass."""

    def test_the_classification_of_the_two_dimensions(self):
        self.assertEqual(check_exit_code([], [], ci=False), EXIT_OK)
        self.assertEqual(check_exit_code([], [], ci=True), EXIT_OK)
        # A broken working tree blocks everywhere.
        self.assertEqual(
            check_exit_code(["reference drift"], [], ci=False), EXIT_VALIDATION
        )
        self.assertEqual(
            check_exit_code(["reference drift"], [], ci=True), EXIT_VALIDATION
        )
        self.assertEqual(
            check_exit_code(["reference drift"], ["release drift"], ci=True),
            EXIT_VALIDATION,
        )
        # The published tags are published outside the pull request.
        self.assertEqual(
            check_exit_code([], ["release drift"], ci=False), EXIT_VALIDATION
        )
        self.assertEqual(
            check_exit_code([], ["release drift"], ci=True), EXIT_OPERATIONAL
        )


class ReleaseCheckCommandTests(unittest.TestCase):
    """``--check`` must compare the tags; ``--ci`` must not redden the pipeline."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repository = make_repository(self.root / "repo")

    def _run(self, *arguments: str):
        original = release_master.repo_root
        release_master.repo_root = lambda: self.repository
        self.addCleanup(setattr, release_master, "repo_root", original)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = release_master.main(list(arguments))
        return code, out.getvalue()

    def test_check_passes_when_the_tag_publishes_the_version(self):
        git(self.repository, "tag", "v1.2.3")

        code, out = self._run("--check")

        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("Release check: PASS", out)

    def test_check_fails_on_a_release_drift(self):
        git(self.repository, "tag", "v1.2.4")

        code, out = self._run("--check")

        self.assertEqual(code, EXIT_VALIDATION, out)
        self.assertIn("Release check: FAIL", out)
        self.assertIn("v1.2.4", out)

    def test_ci_check_reports_the_release_drift_as_operational(self):
        git(self.repository, "tag", "v1.2.4")

        code, out = self._run("--check", "--ci")

        self.assertEqual(code, EXIT_OPERATIONAL, out)
        self.assertIn("v1.2.4", out)

    def test_ci_check_still_fails_on_a_reference_drift(self):
        git(self.repository, "tag", "v1.2.3")
        (self.repository / "README.md").write_text(
            "> Version 1.2.2\n", encoding="utf-8"
        )

        code, out = self._run("--check", "--ci")

        self.assertEqual(code, EXIT_VALIDATION, out)
        self.assertIn("README.md", out)

    def test_ci_is_rejected_outside_the_check_mode(self):
        with self.assertRaises(SystemExit) as raised:
            self._run("--bump", "patch", "--ci")

        self.assertEqual(raised.exception.code, EXIT_USAGE)


class CiExitCodeParityTests(unittest.TestCase):
    """The exit codes are the ones the CI adapter already publishes."""

    def test_the_exit_codes_match_the_ci_adapter(self):
        adapter = support.REPO_ROOT / "INTEGRATIONS" / "ci" / "scripts"
        sys.path.insert(0, str(adapter))
        try:
            import se_ci_common
        finally:
            sys.path.remove(str(adapter))

        self.assertEqual(release_master.EXIT_OK, se_ci_common.EXIT_OK)
        self.assertEqual(release_master.EXIT_VALIDATION, se_ci_common.EXIT_VALIDATION)
        self.assertEqual(release_master.EXIT_USAGE, se_ci_common.EXIT_USAGE)
        self.assertEqual(
            release_master.EXIT_OPERATIONAL, se_ci_common.EXIT_OPERATIONAL
        )


if __name__ == "__main__":
    unittest.main()
