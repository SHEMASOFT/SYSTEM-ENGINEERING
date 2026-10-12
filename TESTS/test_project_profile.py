"""Project Profile tests (ARCH-ADAPT-001).

The `profiles` block is optional and additive. Toolchain Profile ("what you work
with") and Capability Profile ("what capabilities the project needs") are distinct.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.schemas import validate  # noqa: E402


class ProjectProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()

    def assert_valid(self, instance, schema_name):
        errors = validate(instance, self.schemas[schema_name])
        self.assertEqual(errors, [], f"expected valid, got {errors}")

    def assert_invalid(self, instance, schema_name):
        errors = validate(instance, self.schemas[schema_name])
        self.assertNotEqual(errors, [], "expected validation errors but got none")

    def full_profiles(self):
        return {
            "work": {"type": "brownfield", "scale": "medium", "risk": "high"},
            "domain": ["security", "software"],
            "toolchain": {
                "languages": ["python"],
                "frameworks": [],
                "platforms": ["windows"],
                "integrations": ["opencode"],
                "tools": ["git"],
            },
            "capability": ["multi-tenant", "offline-first"],
        }

    def test_project_without_profiles_is_valid(self):
        self.assert_valid(support.manifest(), "project")

    def test_project_with_profiles_is_valid(self):
        self.assert_valid(support.manifest(profiles=self.full_profiles()), "project")

    def test_project_context_with_profiles_is_valid(self):
        ctx = {
            "schema_version": "1",
            "project_id": "PRJ-TEST-001",
            "domains": ["software"],
            "master_system_version": "0.1.0",
            "profiles": self.full_profiles(),
        }
        self.assert_valid(ctx, "project_context")

    def test_invalid_work_type_rejected(self):
        profiles = self.full_profiles()
        profiles["work"]["type"] = "sideways"
        self.assert_invalid(support.manifest(profiles=profiles), "project")

    def test_unknown_profile_key_rejected(self):
        profiles = self.full_profiles()
        profiles["nonsense"] = {}
        self.assert_invalid(support.manifest(profiles=profiles), "project")

    def test_unknown_toolchain_key_rejected(self):
        profiles = self.full_profiles()
        profiles["toolchain"]["databases"] = ["postgres"]
        self.assert_invalid(support.manifest(profiles=profiles), "project")

    def test_toolchain_and_capability_are_separate(self):
        # Toolchain = what you work with; Capability = what the project needs.
        profiles = {"toolchain": {"languages": ["python"]}, "capability": ["multi-tenant"]}
        self.assert_valid(support.manifest(profiles=profiles), "project")


if __name__ == "__main__":
    unittest.main()
