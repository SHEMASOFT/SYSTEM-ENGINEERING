"""Domain pack contract tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

EXPECTED_DOMAINS = {
    "software", "security", "cloud", "ai-data", "media",
    "design", "architecture", "automation", "social-media",
}


class DomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = support.schemas()
        cls.files = sorted((support.REPO_ROOT / "DOMAINS").glob("*/domain.json"))
        cls.domains = {path.parent.name: load_json(path) for path in cls.files}

    def test_all_domains_present(self):
        self.assertEqual(set(self.domains), EXPECTED_DOMAINS)

    def test_domains_validate_against_contract(self):
        for name, domain in self.domains.items():
            errors = validate(domain, self.schemas["domain"])
            self.assertEqual(errors, [], f"{name}: {errors}")

    def test_directory_matches_id(self):
        for name, domain in self.domains.items():
            self.assertEqual(domain["id"], name)

    def test_software_pack_is_full(self):
        self.assertEqual(self.domains["software"]["status"], "FULL")

    def test_other_packs_are_minimal_stubs(self):
        for name, domain in self.domains.items():
            if name != "software":
                self.assertEqual(domain["status"], "MINIMAL", name)

    def test_gate_additions_reference_real_gates(self):
        for name, domain in self.domains.items():
            for addition in domain["gate_additions"]:
                self.assertRegex(addition["gate"], r"^G[0-8]$", name)


if __name__ == "__main__":
    unittest.main()
