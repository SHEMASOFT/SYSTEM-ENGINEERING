"""Capability governance tests (CHECKPOINT-020).

Coverage sections (CP-020):
  A  capability registry + declarative provider mapping
  B  provider -> capability mapping (filesystem, documentation.lookup, structured.reasoning)
  C  skill required capabilities resolve REQUIRED (documentation.lookup + context7 -> RESOLVED)
  D  skill optional capabilities resolve OPTIONAL
  E  task allow/require keeps filesystem.write ALLOWED (implementation task)
  F  task deny produces DENY
  G  READ_ONLY forbids filesystem.write and allows read/search
  H  inheritance + precedence across project / agent / skill / task
  I  conflict detection (required-but-denied, required-but-unavailable)
  J  unavailable capability resolution
  K  backward compatibility (absent policies remain valid)
  L  adapter integration (capability_plan in manifest, CLI)
  M  existing skills keep working and verification-review represents READ_ONLY
  N  doctor / validate cover capability governance

Hermetic: no network, temporary directories only.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: E402  (sys.path already added by test runner)

from se_core import capabilities as caps  # noqa: E402
from se_core.schemas import load_schemas, validate  # noqa: E402

PROJECT_CONTEXT = {
    "schema_version": "1",
    "project_id": "PRJ-TEST-0001",
    "domains": ["software"],
    "master_system_version": "0.8.0",
}


def project(**over):
    data = dict(PROJECT_CONTEXT)
    data.update(over)
    return data


def skill(**over):
    data = {"skill_id": "SK-TEST", "name": "test-skill", "version": "0.1.0", "description": "test"}
    data.update(over)
    return data


def task(**over):
    data = {"task_id": "TASK-0001", "type": "implementation"}
    data.update(over)
    return data


def agent(**over):
    data = {"agent_id": "AG-TEST", "name": "tester", "permissions": ["READ"]}
    data.update(over)
    return data


class RegistryTests(unittest.TestCase):
    def test_expected_capabilities_and_providers(self):
        self.assertEqual(
            caps.known_capabilities(support.REPO_ROOT),
            {"filesystem.read", "filesystem.search", "filesystem.write",
             "documentation.lookup", "structured.reasoning",
             "browser.preview", "browser.snapshot", "browser.screenshot",
             "visual.review",
             "web.search", "web.scrape", "web.extract", "research.synthesis"},
        )
        self.assertEqual(
            set(caps.known_providers(support.REPO_ROOT)),
            {"filesystem", "context7", "sequential-thinking",
             "playwright", "deepseek-vision",
             "firecrawl", "perplexity"},
        )
        # visual.review is registered with availability "unknown" (no provider key
        # observable in this environment) -> known but intentionally NOT available.
        self.assertEqual(
            caps.available_capabilities(support.REPO_ROOT),
            {"filesystem.read", "filesystem.search", "filesystem.write",
             "documentation.lookup", "structured.reasoning",
             "browser.preview", "browser.snapshot", "browser.screenshot",
             "web.search", "web.scrape", "web.extract", "research.synthesis"},
        )
        self.assertNotEqual(caps.known_capabilities(support.REPO_ROOT),
                            caps.available_capabilities(support.REPO_ROOT))

    def test_provider_capability_mapping(self):
        mapping = caps.provider_capabilities(support.REPO_ROOT)
        self.assertEqual(mapping["filesystem"], ["filesystem.read", "filesystem.search", "filesystem.write"])
        self.assertEqual(mapping["context7"], ["documentation.lookup"])
        self.assertEqual(mapping["sequential-thinking"], ["structured.reasoning"])
        self.assertEqual(mapping["playwright"], ["browser.preview", "browser.screenshot", "browser.snapshot"])
        self.assertEqual(mapping["deepseek-vision"], ["visual.review"])
        self.assertEqual(mapping["firecrawl"], ["web.extract", "web.scrape"])
        self.assertEqual(mapping["perplexity"], ["research.synthesis", "web.search"])

    def test_registry_validates_against_schema(self):
        schemas = support.schemas()
        self.assertEqual(caps.validate_registry(support.REPO_ROOT, schemas=schemas), [])

    def test_registry_with_unknown_provider_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CORE" / "capabilities").mkdir(parents=True)
            registry = caps.load_registry()
            registry["capabilities"].append({
                "id": "mystery.capability",
                "description": "test",
                "operation": "read",
                "provider": "mystery-provider",
                "availability": "available",
            })
            (root / "CORE" / "capabilities" / "capabilities.json").write_text(
                json.dumps(registry, indent=2), encoding="utf-8"
            )
            errors = caps.validate_registry(root, schemas=support.schemas())
            self.assertTrue(any("unknown provider 'mystery-provider'" in e for e in errors), errors)

    def test_plan_view_deterministic(self):
        self.assertEqual(caps.capability_plan_view(support.REPO_ROOT),
                         caps.capability_plan_view(support.REPO_ROOT))


class SkillPolicyTests(unittest.TestCase):
    def test_required_capability_resolves_required(self):
        plan = caps.resolve_plan(
            skill=skill(capabilities={"required": ["documentation.lookup"]})
        )
        entry = plan["capabilities"]["documentation.lookup"]
        self.assertEqual(entry["status"], "REQUIRED")
        self.assertIn("skill", entry["sources"])
        self.assertTrue(entry["available"])
        self.assertEqual(plan["status"], "PASS")

    def test_skill_requires_with_context7_resolved(self):
        # Mandatory scenario: skill requires documentation.lookup, context7 available -> RESOLVED.
        plan = caps.resolve_plan(
            skill=skill(capabilities={"required": ["documentation.lookup"]})
        )
        registry = caps.load_registry(support.REPO_ROOT)
        context7 = next(p for p in registry["providers"] if p["id"] == "context7")
        self.assertEqual(context7["availability"], "available")
        self.assertEqual(plan["capabilities"]["documentation.lookup"]["status"], "REQUIRED")
        self.assertEqual(plan["status"], "PASS")

    def test_optional_capability_resolves_optional(self):
        plan = caps.resolve_plan(
            skill=skill(capabilities={"optional": ["structured.reasoning"]})
        )
        entry = plan["capabilities"]["structured.reasoning"]
        self.assertEqual(entry["status"], "OPTIONAL")
        self.assertIn("skill", entry["sources"])

    def test_unknown_skill_capability_rejected(self):
        known = caps.known_capabilities(support.REPO_ROOT)
        ops = caps.operation_map(support.REPO_ROOT)
        errors = caps.validate_skill_policy(
            skill(capabilities={"required": ["wizardry.cast"]}), known, ops
        )
        self.assertTrue(any("unknown capability 'wizardry.cast'" in e for e in errors), errors)


class TaskPolicyTests(unittest.TestCase):
    def test_implementation_task_allows_write(self):
        # Mandatory scenario: implementation task + filesystem.write -> ALLOWED.
        plan = caps.resolve_plan(task=task(capability_policy={"allows": ["filesystem.write"]}))
        entry = plan["capabilities"]["filesystem.write"]
        self.assertIn(entry["status"], ("ALLOW", "REQUIRED"))
        self.assertIn("task", entry["sources"])
        self.assertEqual(plan["status"], "PASS")

    def test_task_requires_write_resolves_required(self):
        plan = caps.resolve_plan(task=task(capability_policy={"requires": ["filesystem.write"]}))
        self.assertEqual(plan["capabilities"]["filesystem.write"]["status"], "REQUIRED")
        self.assertEqual(plan["status"], "PASS")

    def test_task_deny_produces_deny(self):
        plan = caps.resolve_plan(task=task(capability_policy={"denies": ["filesystem.write"]}))
        self.assertEqual(plan["capabilities"]["filesystem.write"]["status"], "DENY")

    def test_read_only_denies_write_allows_read_search(self):
        # Mandatory scenario: READ_ONLY + filesystem.write -> DENIED.
        plan = caps.resolve_plan(task=task(capability_policy={"mode": "READ_ONLY"}))
        self.assertEqual(plan["capabilities"]["filesystem.write"]["status"], "DENY")
        self.assertEqual(plan["capabilities"]["filesystem.read"]["status"], "ALLOW")
        self.assertEqual(plan["capabilities"]["filesystem.search"]["status"], "ALLOW")

    def test_read_only_required_write_conflicts(self):
        plan = caps.resolve_plan(
            task=task(capability_policy={"mode": "READ_ONLY", "requires": ["filesystem.write"]})
        )
        self.assertEqual(plan["status"], "CONFLICT")
        self.assertTrue(any("READ_ONLY" in c for c in plan["conflicts"]), plan["conflicts"])

    def test_read_only_cannot_require_write(self):
        known = caps.known_capabilities(support.REPO_ROOT)
        ops = caps.operation_map(support.REPO_ROOT)
        errors = caps.validate_task_policy(
            task(capability_policy={"mode": "READ_ONLY", "requires": ["filesystem.write"]}),
            known, ops,
        )
        self.assertTrue(any("READ_ONLY" in e for e in errors), errors)

    def test_requires_and_denies_overlap_rejected(self):
        known = caps.known_capabilities(support.REPO_ROOT)
        ops = caps.operation_map(support.REPO_ROOT)
        errors = caps.validate_task_policy(
            task(capability_policy={"requires": ["filesystem.read"],
                                   "denies": ["filesystem.read"]}),
            known, ops,
        )
        self.assertTrue(any("requires and denies" in e for e in errors), errors)


class ResolutionTests(unittest.TestCase):
    def test_inheritance_precedence_project_agent_skill(self):
        plan = caps.resolve_plan(
            project=project(profiles={"capability": ["structured.reasoning", "filesystem.read"]}),
            agent=agent(capability_requires=["filesystem.search"]),
            skill=skill(capabilities={"required": ["filesystem.read"]}),
        )
        self.assertEqual(plan["status"], "PASS")
        self.assertEqual(plan["capabilities"]["structured.reasoning"]["status"], "REQUIRED")
        self.assertIn("project", plan["capabilities"]["structured.reasoning"]["sources"])
        self.assertEqual(plan["capabilities"]["filesystem.search"]["status"], "REQUIRED")
        self.assertIn("agent", plan["capabilities"]["filesystem.search"]["sources"])
        self.assertEqual(plan["capabilities"]["filesystem.read"]["status"], "REQUIRED")

    def test_required_by_skill_but_denied_by_task_conflicts(self):
        plan = caps.resolve_plan(
            skill=skill(capabilities={"required": ["filesystem.write"]}),
            task=task(capability_policy={"denies": ["filesystem.write"]}),
        )
        self.assertEqual(plan["status"], "CONFLICT")
        entry = plan["capabilities"]["filesystem.write"]
        self.assertEqual(entry["status"], "DENY")
        self.assertTrue(any("required by skill" in c for c in plan["conflicts"]), plan["conflicts"])

    def test_skill_forbids_write_but_task_requires_conflicts(self):
        plan = caps.resolve_plan(
            skill=skill(capabilities={}, constraints={"write": "forbidden"}),
            task=task(capability_policy={"requires": ["filesystem.write"]}),
        )
        self.assertEqual(plan["status"], "CONFLICT")
        self.assertTrue(any("forbids writes" in c for c in plan["conflicts"]), plan["conflicts"])

    def test_required_but_unavailable_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CORE" / "capabilities").mkdir(parents=True)
            registry = caps.load_registry()
            for cap in registry["capabilities"]:
                if cap["id"] == "documentation.lookup":
                    cap["availability"] = "unavailable"
            (root / "CORE" / "capabilities" / "capabilities.json").write_text(
                json.dumps(registry, indent=2), encoding="utf-8"
            )
            plan = caps.resolve_plan(
                root=root, project=project(profiles={"capability": ["documentation.lookup"]})
            )
            self.assertEqual(plan["status"], "CONFLICT")
            entry = plan["capabilities"]["documentation.lookup"]
            self.assertFalse(entry["available"])
            self.assertTrue(any("not available" in c for c in plan["conflicts"]), plan["conflicts"])

    def test_unknown_requirement_ignored_by_resolver(self):
        plan = caps.resolve_plan(task=task(capability_policy={"requires": ["wizardry.cast"]}))
        self.assertEqual(plan["status"], "PASS")


class BackwardCompatibilityTests(unittest.TestCase):
    def test_skill_without_capabilities_valid(self):
        known = caps.known_capabilities(support.REPO_ROOT)
        self.assertEqual(caps.validate_skill_policy(skill(), known, caps.operation_map()), [])

    def test_task_without_policy_resolves_pass(self):
        plan = caps.resolve_plan(task=task())
        self.assertEqual(plan["status"], "PASS")

    def test_agent_without_declaration_valid(self):
        known = caps.known_capabilities(support.REPO_ROOT)
        self.assertEqual(caps.validate_agent_policy(agent(), known, {}), [])

    def test_dotted_capability_profile_validates(self):
        schemas = support.schemas()
        over = {
            "profiles": {
                "capability": ["filesystem.read", "documentation.lookup"],
                "toolchain": {"providers": ["context7", "filesystem"]},
            }
        }
        self.assertEqual(validate(support.manifest(**over), schemas["project"]), [])
        self.assertEqual(validate(project(**over), schemas["project_context"]), [])

    def test_existing_canonical_contracts_still_validate(self):
        schemas = support.schemas()
        for sidecar in sorted((support.REPO_ROOT / "SKILLS").glob("*/SKILL.json")):
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(validate(data, schemas["skill_contract"]), [],
                             f"{sidecar}: {validate(data, schemas['skill_contract'])}")
        for contract in sorted((support.REPO_ROOT / "AGENTS").glob("*/agent.json")):
            data = json.loads(contract.read_text(encoding="utf-8"))
            self.assertEqual(validate(data, schemas["agent"]), [],
                             f"{contract}: {validate(data, schemas['agent'])}")

    def test_check_policies_canonical_passes(self):
        self.assertEqual(caps.check_policies(support.REPO_ROOT), [])


class AdapterTests(unittest.TestCase):
    def test_manifest_carries_capability_plan(self):
        from se_core.opencode.generator import generate

        with tempfile.TemporaryDirectory() as tmp:
            result = generate(support.REPO_ROOT, Path(tmp))
            self.assertEqual(result["status"], "PASS")
            config = json.loads((Path(tmp) / "adapter-manifest.json").read_text(encoding="utf-8"))
            plan = config.get("capability_plan")
            self.assertIsInstance(plan, dict)
            self.assertEqual(len(plan["available"]), 12)
            self.assertEqual(len(plan["mapping"]), 7)
            providers = {entry["provider"] for entry in plan["mapping"]}
            self.assertEqual(providers, {"filesystem", "context7", "sequential-thinking",
                                         "playwright", "deepseek-vision",
                                         "firecrawl", "perplexity"})
            self.assertEqual(validate(config, support.schemas()["adapter_manifest"]), [])

    def test_cli_capabilities_report(self):
        code, out = support.run_cli("capabilities")
        self.assertEqual(code, 0, out)
        self.assertIn("filesystem.read", out)
        self.assertIn("documentation.lookup", out)
        self.assertIn("sequential-thinking", out)

    def test_cli_capabilities_check_passes(self):
        code, out = support.run_cli("capabilities", "--check")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)

    def test_cli_plan_for_managed_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = support.make_project(Path(tmp) / "p")
            support.write_json(
                project_dir / "PROJECT.json",
                support.manifest(profiles={"capability": ["filesystem.read"]}),
            )
            code, out = support.run_cli("capabilities", "--project", str(project_dir))
            self.assertEqual(code, 0, out)
            self.assertIn("Capability Plan: PASS", out)
            self.assertIn("REQUIRED", out)


class SkillsCanonicalTests(unittest.TestCase):
    def test_verification_review_represents_read_only(self):
        sidecar = json.loads(
            (support.REPO_ROOT / "SKILLS" / "verification-review" / "SKILL.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(sidecar.get("constraints", {}).get("write"), "forbidden")
        self.assertIn("filesystem.read", sidecar.get("capabilities", {}).get("required", []))

    def test_checkpoint_release_declares_capabilities(self):
        sidecar = json.loads(
            (support.REPO_ROOT / "SKILLS" / "checkpoint-release" / "SKILL.json")
            .read_text(encoding="utf-8")
        )
        self.assertIn("filesystem.search", sidecar.get("capabilities", {}).get("required", []))


class DoctorValidationTests(unittest.TestCase):
    def test_doctor_capability_check_passes(self):
        from se_core.doctor import run_doctor

        report = run_doctor(support.REPO_ROOT)
        by_id = {r["id"]: r for r in report["results"]}
        self.assertEqual(by_id["capabilities"]["status"], "PASS", by_id["capabilities"])
        self.assertEqual(report["summary"]["FAIL"], 0, report["results"])

    def test_validate_checks_registry(self):
        code, out = support.run_cli("validate")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()