"""Release automation tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from release_master import (  # noqa: E402
    ReleaseError,
    apply_release,
    bump_version,
    check_consistency,
    plan_release,
)

EM_DASH = "\u2014"


class ReleaseMasterTests(unittest.TestCase):
    def _root(self, version: str = "0.10.1") -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "MASTER SYSTEM").mkdir()
        (root / "DOCS" / "reference").mkdir(parents=True)

        (root / "VERSION").write_text(version + "\n", encoding="utf-8")
        (root / "MASTER SYSTEM" / "VERSION").write_text(
            version + "\n", encoding="utf-8"
        )
        (root / "README.md").write_text(
            f"> Version {version} {EM_DASH} Status: **foundation / development**.\n",
            encoding="utf-8",
        )
        (root / "DOCS" / "reference" / "versioning.md").write_text(
            f"# Versioning\n\nCurrent version: **{version}**\n",
            encoding="utf-8",
        )
        (root / "MASTER SYSTEM" / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- old entry\n\n"
            "## [0.10.0] - 2026-09-22\n\n- previous release\n",
            encoding="utf-8",
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
        return root

    def test_bump_version(self):
        self.assertEqual(bump_version("0.10.1", "patch"), "0.10.2")
        self.assertEqual(bump_version("0.10.1", "minor"), "0.11.0")
        self.assertEqual(bump_version("0.10.1", "major"), "1.0.0")
        with self.assertRaises(ReleaseError):
            bump_version("0.10.1", "nope")

    def test_major_from_zero_is_refused(self):
        with self.assertRaises(ReleaseError):
            plan_release(self._root(), "major")

    def test_check_consistency_passes(self):
        self.assertEqual(check_consistency(self._root()), [])

    def test_check_detects_distribution_drift(self):
        root = self._root()
        (root / "MASTER SYSTEM" / "VERSION").write_text("0.10.0\n", encoding="utf-8")

        issues = check_consistency(root)

        self.assertTrue(any("MASTER SYSTEM/VERSION" in issue for issue in issues))

    def test_check_detects_readme_drift(self):
        root = self._root()
        (root / "README.md").write_text("> Version 0.10.0\n", encoding="utf-8")

        issues = check_consistency(root)

        self.assertTrue(any("README.md" in issue for issue in issues))

    def test_check_detects_adapter_drift(self):
        root = self._root()
        support.write_json(root / ".opencode" / "adapter-manifest.json", {
            "adapter_id": "opencode",
            "adapter_version": "0.10.0",
            "engine_version": "0.10.0",
        })

        issues = check_consistency(root)

        self.assertTrue(any("adapter_version" in issue for issue in issues))

    def test_apply_release_updates_active_references(self):
        root = self._root()

        changed = apply_release(
            root,
            "0.10.2",
            "test release",
            regenerate_adapter=False,
            rebase_coverage=False,
        )

        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(), "0.10.2")
        self.assertEqual(
            (root / "MASTER SYSTEM" / "VERSION").read_text(encoding="utf-8").strip(),
            "0.10.2",
        )
        self.assertIn(
            '"master_system_version": "0.10.2"',
            (root / "SYSTEM.json").read_text(encoding="utf-8"),
        )
        self.assertIn(
            '"master_system_version": "0.10.2"',
            (root / "MASTER SYSTEM" / "MANIFEST.json").read_text(encoding="utf-8"),
        )
        self.assertIn(
            f"> Version 0.10.2 {EM_DASH} Status:",
            (root / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Current version: **0.10.2**",
            (root / "DOCS" / "reference" / "versioning.md").read_text(encoding="utf-8"),
        )
        changelog = (root / "MASTER SYSTEM" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.10.2] - ", changelog)
        self.assertIn("- test release", changelog)
        self.assertIn("- old entry", changelog)
        self.assertIn("VERSION", changed)
        self.assertIn("README.md", changed)
        self.assertIn("MASTER SYSTEM/CHANGELOG.md", changed)

    def test_apply_release_is_all_or_nothing(self):
        root = self._root()
        (root / "README.md").write_text("no version marker\n", encoding="utf-8")

        with self.assertRaises(ReleaseError):
            apply_release(
                root,
                "0.10.2",
                "test release",
                regenerate_adapter=False,
                rebase_coverage=False,
            )

        self.assertEqual(
            (root / "VERSION").read_text(encoding="utf-8").strip(), "0.10.1"
        )

    def test_repository_is_consistent(self):
        self.assertEqual(check_consistency(support.REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
