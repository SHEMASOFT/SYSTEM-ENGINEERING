"""OpenCode adapter tests (CHECKPOINT-004).

Hermetic: generation always targets a temporary directory; the adapter never
writes project workspaces (guard: no output under a path segment named PROJECTS).
Idempotence: two runs produce byte-identical results.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.cli import build_parser  # noqa: E402
from se_core.opencode.generator import generate  # noqa: E402
from se_core.opencode.mappings import build_command_markdown  # noqa: E402
from se_core.opencode.validators import audit_adapter  # noqa: E402
from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

EXPECTED_AGENTS = {
    "shema-ai-coordinador", "explorer", "analyst", "architect", "planner", "implementer",
    "tester", "reviewer", "security", "documentation", "devops", "visual",
}
EXPECTED_COMMANDS = {
    "init", "explore", "new", "update", "transition", "plan", "implement",
    "verify", "review", "release", "doctor", "validate", "gate", "capabilities",
    "context", "health", "auto", "intent", "handoff", "archive", "restore",
    "execute", "observe", "orchestrate",
}


def _tree(root: Path) -> dict:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class OpenCodeAdapterGenerationTests(unittest.TestCase):
    def generate_to(self, target: Path, dry_run=False):
        return generate(support.REPO_ROOT, target, dry_run=dry_run)

    def test_twelve_agents_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.generate_to(Path(tmp))
            self.assertEqual(result["status"], "PASS")
            agent_files = {p.name for p in (Path(tmp) / "agents").glob("*.md")}
            self.assertEqual(agent_files, {f"{r}.md" for r in EXPECTED_AGENTS})
            self.assertEqual(result["counts"]["agents"], 12)

    def test_twenty_four_commands_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.generate_to(Path(tmp))
            self.assertEqual(result["status"], "PASS")
            command_files = {p.name for p in (Path(tmp) / "commands").glob("*.md")}
            self.assertEqual(command_files, {f"{c}.md" for c in EXPECTED_COMMANDS})
            self.assertEqual(result["counts"]["commands"], 24)

    def test_canonical_skills_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.generate_to(Path(tmp))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["counts"]["skills"], 7)
            skill_files = {
                p.parent.name: p.name for p in (Path(tmp) / "skills").glob("*/*")
            }
            self.assertEqual(
                skill_files,
                {
                    "checkpoint-release": "SKILL.md",
                    "verification-review": "SKILL.md",
                    "visual-frontend-engineering": "SKILL.md",
                    "dbg-systematic": "SKILL.md",
                    "rev-adversarial": "SKILL.md",
                    "impl-tdd": "SKILL.md",
                    "work-mode-selection": "SKILL.md",
                },
            )

    def test_skills_byte_identical_to_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.generate_to(Path(tmp))
            for name in ("checkpoint-release", "verification-review",
                         "visual-frontend-engineering", "dbg-systematic",
                         "rev-adversarial", "impl-tdd", "work-mode-selection"):
                generated = (Path(tmp) / "skills" / name / "SKILL.md").read_bytes()
                canonical = Path(support.REPO_ROOT) / "SKILLS" / name / "SKILL.md"
                self.assertEqual(
                    generated, canonical.read_bytes(), f"skill {name} must pass through stably"
                )

    def test_config_generated_and_valid(self):
        schemas = support.schemas()
        with tempfile.TemporaryDirectory() as tmp:
            result = self.generate_to(Path(tmp))
            self.assertEqual(result["status"], "PASS")
            config_path = Path(tmp) / "adapter-manifest.json"
            self.assertTrue(config_path.exists())
            config = json.loads(config_path.read_text(encoding="utf-8"))
            errors = validate(config, schemas["adapter_manifest"])
            self.assertEqual(errors, [], f"{errors}")
            self.assertEqual(config["adapter_id"], "opencode")
            self.assertEqual(config["target"], "opencode")
            self.assertEqual(len(config["output"]["artifacts"]), 58)

    def test_capabilities_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.generate_to(Path(tmp))
            config = json.loads(
                (Path(tmp) / "adapter-manifest.json").read_text(encoding="utf-8")
            )
            caps = config.get("capabilities")
            self.assertIsInstance(caps, dict, "adapter must declare capabilities explicitly")
            for capability in ("agents", "commands", "skills"):
                self.assertEqual(caps.get(capability), "SUPPORTED", capability)
            self.assertEqual(caps.get("workflows"), "UNSUPPORTED")
            allowed = {"SUPPORTED", "PARTIAL", "UNSUPPORTED"}
            self.assertTrue(set(caps.values()) <= allowed, caps)

    def test_agents_md_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.generate_to(Path(tmp))
            for role in EXPECTED_AGENTS:
                text = (Path(tmp) / "agents" / f"{role}.md").read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"), role)
                # Heading uses display name derived from description (before first colon) or role title-cased
                lines = text.splitlines()
                heading_line = next((l for l in lines if l.startswith("# ")), "")
                self.assertTrue(heading_line.startswith("# "), f"{role}: missing heading")
                expected_display = role.replace('-', ' ').title()
                # For shema-ai-coordinador, description starts with "SHEMA-AI Coordinador:"
                if role == "shema-ai-coordinador":
                    expected_display = "SHEMA-AI Coordinador"
                self.assertEqual(heading_line, f"# {expected_display}", f"{role}: heading mismatch")
                expected_mode = "mode: primary" if role == "shema-ai-coordinador" else "mode: subagent"
                for line in ("description:", expected_mode):
                    self.assertTrue(any(l.startswith(line) for l in text.splitlines()), f"{role}: {line}")
                self.assertFalse(
                    any(l.startswith("permission:") for l in text.splitlines()),
                    f"{role}: legacy 'permission' field must not be emitted (V2 uses 'permissions')",
                )

    def test_commands_md_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.generate_to(Path(tmp))
            for name in EXPECTED_COMMANDS:
                text = (Path(tmp) / "commands" / f"{name}.md").read_text(encoding="utf-8")
                lines = text.splitlines()
                keys = {l.split(":")[0].strip() for l in lines if ":" in l}
                self.assertIn("description", keys, name)
                self.assertIn("agent", keys, name)
                self.assertIn("se " + name, text, name)

    def test_full_plan_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.generate_to(Path(tmp))
            paths = {entry["path"] for entry in result["files"]}
            self.assertEqual(len(paths), 58)
            self.assertIn("adapter-manifest.json", paths)
            self.assertIn("AGENTS.md", paths)

    def test_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            self.generate_to(Path(tmp1))
            self.generate_to(Path(tmp2))
            self.assertEqual(_tree(Path(tmp1)), _tree(Path(tmp2)))

    def test_rerun_on_same_dir_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.generate_to(Path(tmp))
            second = self.generate_to(Path(tmp))
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(
                {f["action"] for f in second["files"]},
                {"unchanged"},
            )
            self.assertEqual(_tree(Path(tmp)), _tree(Path(tmp)))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.generate_to(Path(tmp), dry_run=True)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["dry_run"])
            self.assertEqual(list(Path(tmp).rglob("*")), [])
            self.assertEqual(len(result["files"]), 58)

    def test_never_writes_into_projects(self):
        schemas = support.schemas()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "PROJECTS"
            with self.assertRaises(ValueError):
                generate(support.REPO_ROOT, output)

    def test_output_inside_projects_segment_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "x" / "projects" / "nested"
            with self.assertRaises(ValueError):
                generate(support.REPO_ROOT, output)

    def test_generated_files_byte_identical_across_configs_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.generate_to(Path(tmp))
            config = json.loads((Path(tmp) / "adapter-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(config["output"]["generated_files"]), 57)
            hashes = config["metadata"]["content_hashes"]
            self.assertEqual(len(hashes), 57)
            for rel, digest in hashes.items():
                content = (Path(tmp) / rel).read_bytes()
                import hashlib

                self.assertEqual(hashlib.sha256(content).hexdigest(), digest, rel)

    def test_cli_dry_run_reports_pass(self):
        code, out = support.run_cli("adapter", "opencode", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("Status: PASS", out)
        self.assertIn("12 generated", out)
        self.assertIn("24 generated", out)

    def test_cli_generates_into_custom_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            code, out = support.run_cli("adapter", "opencode", "--output", str(output))
            self.assertEqual(code, 0, out)
            self.assertTrue((output / "adapter-manifest.json").exists())
            self.assertEqual(len(list((output / "agents").glob("*.md"))), 12)


class AdapterConformanceAuditTests(unittest.TestCase):
    """AUTO-08: the generated/deployed tree must conform to its own manifest."""

    def generate_tree(self, tmp):
        target = Path(tmp)
        result = generate(support.REPO_ROOT, target)
        self.assertEqual(result["status"], "PASS", result.get("errors"))
        return target

    def manifest_of(self, target):
        return json.loads((target / "adapter-manifest.json").read_text(encoding="utf-8"))

    def write_manifest(self, target, config):
        (target / "adapter-manifest.json").write_text(
            json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def audit(self, target):
        return audit_adapter(Path(support.REPO_ROOT), target, schemas=support.schemas())

    def test_freshly_generated_tree_conforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            self.assertEqual(self.audit(target), [])

    def test_deployed_opencode_tree_conforms(self):
        errors = audit_adapter(
            Path(support.REPO_ROOT),
            Path(support.REPO_ROOT) / ".opencode",
            schemas=support.schemas(),
        )
        self.assertEqual(errors, [], f"{errors}")

    def test_detects_content_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            victim = target / "agents" / "planner.md"
            victim.write_text(
                victim.read_text(encoding="utf-8") + "\nhand edited\n", encoding="utf-8"
            )
            errors = self.audit(target)
            self.assertTrue(
                any("content hash mismatch" in e and "planner.md" in e for e in errors),
                errors,
            )

    def test_detects_missing_generated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            (target / "commands" / "gate.md").unlink()
            errors = self.audit(target)
            self.assertTrue(
                any("missing on disk" in e and "commands/gate.md" in e for e in errors), errors
            )

    def test_detects_undeclared_file_in_owned_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            (target / "agents" / "rogue.md").write_text("---\ndescription: x\n---\n", encoding="utf-8")
            errors = self.audit(target)
            self.assertTrue(
                any("undeclared file" in e and "agents/rogue.md" in e for e in errors), errors
            )

    def test_ignores_runtime_files_outside_owned_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            (target / "package.json").write_text("{}\n", encoding="utf-8")
            (target / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
            deps = target / "node_modules" / "left-pad"
            deps.mkdir(parents=True)
            (deps / "index.js").write_text("module.exports = 1;\n", encoding="utf-8")
            self.assertEqual(self.audit(target), [])

    def test_detects_legacy_singular_skill_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            (target / "skill" / "impl-tdd").mkdir(parents=True)
            errors = self.audit(target)
            self.assertTrue(any("legacy singular" in e for e in errors), errors)

    def test_detects_skill_not_byte_identical_even_when_hash_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            rel = "skills/impl-tdd/SKILL.md"
            victim = target / rel
            victim.write_text(
                victim.read_text(encoding="utf-8") + "\n<!-- tampered -->\n", encoding="utf-8"
            )
            config = self.manifest_of(target)
            # Hash the bytes actually on disk, so only the canonical-equality rule can fire.
            config["metadata"]["content_hashes"][rel] = hashlib.sha256(
                victim.read_bytes()
            ).hexdigest()
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(
                any("not byte-identical to canonical" in e for e in errors), errors
            )
            self.assertFalse(
                any("content hash mismatch" in e for e in errors), errors
            )

    def test_detects_capability_provider_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            config = self.manifest_of(target)
            config["capability_plan"]["available"].append("firecrawl")
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(any("collision (CP-020)" in e for e in errors), errors)

    def test_detects_capability_spelled_like_a_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            config = self.manifest_of(target)
            config["capability_plan"]["mapping"].append(
                {"provider": "firecrawl", "capabilities": ["scrape"], "availability": "available"}
            )
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(any("lacks domain.operation form" in e for e in errors), errors)

    def test_detects_capability_plan_not_mirroring_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            config = self.manifest_of(target)
            config["capability_plan"]["available"].remove("research.synthesis")
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(any("does not mirror the registry" in e for e in errors), errors)

    def test_detects_unknown_provider_in_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            config = self.manifest_of(target)
            config["capability_plan"]["mapping"].append(
                {"provider": "acme-search", "capabilities": ["web.search"],
                 "availability": "available"}
            )
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(any("unknown provider 'acme-search'" in e for e in errors), errors)

    def test_detects_adapter_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            config = self.manifest_of(target)
            config["adapter_version"] = "9.9.9"
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(any("adapter_version '9.9.9'" in e for e in errors), errors)

    def test_detects_empty_content_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            config = self.manifest_of(target)
            config["metadata"]["content_hashes"] = {}
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(any("content_hashes is empty" in e for e in errors), errors)

    def test_detects_generated_file_missing_frontmatter_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.generate_tree(tmp)
            rel = "commands/gate.md"
            victim = target / rel
            victim.write_text("# gate\n\nno frontmatter\n", encoding="utf-8")
            config = self.manifest_of(target)
            config["metadata"]["content_hashes"][rel] = hashlib.sha256(
                victim.read_bytes()
            ).hexdigest()
            self.write_manifest(target, config)
            errors = self.audit(target)
            self.assertTrue(
                any("no frontmatter description" in e and rel in e for e in errors), errors
            )

    def test_missing_manifest_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = audit_adapter(Path(support.REPO_ROOT), Path(tmp))
            self.assertTrue(any("missing adapter-manifest.json" in e for e in errors), errors)


class CommandExecutionLineTests(unittest.TestCase):
    """The generated `## Execution` line must be a valid CLI invocation.

    `build_command_markdown` used to emit `se <name> --project $ARGUMENTS` for
    every command. For commands whose `--project` lives on the subcommands
    (CMD-0019 handoff, CMD-0024 orchestrate) that line exits 2 with
    `invalid choice`, so the generated slash command never worked.
    """

    def _commands(self):
        return load_json(Path(support.REPO_ROOT) / "COMMANDS" / "commands.json")["commands"]

    @staticmethod
    def _execution_line(command):
        for line in build_command_markdown(command).splitlines():
            if line.startswith("se "):
                return line
        raise AssertionError(f"no Execution line generated for {command['name']}")

    @staticmethod
    def _declares_subcommand(command):
        return any(arg.get("name") == "subcommand" for arg in command.get("arguments", []))

    def test_execution_line_follows_cli_shape_per_command(self):
        for cmd in self._commands():
            expected = (
                f"se {cmd['name']} $ARGUMENTS" if self._declares_subcommand(cmd)
                else f"se {cmd['name']} --project $ARGUMENTS"
            )
            self.assertEqual(self._execution_line(cmd), expected, cmd["name"])

    def test_only_subcommand_commands_dropped_the_top_level_project_flag(self):
        changed = [
            cmd["name"] for cmd in self._commands()
            if self._execution_line(cmd) != f"se {cmd['name']} --project $ARGUMENTS"
        ]
        self.assertEqual(sorted(changed), ["handoff", "orchestrate"])

    def test_orchestrate_execution_line_parses_with_real_parser(self):
        args = build_parser().parse_args(
            shlex.split("orchestrate list --project PROJECTS/workflow-demo")
        )
        self.assertEqual(args.command, "orchestrate")
        self.assertEqual(args.orchestrate_command, "list")

    def test_handoff_execution_line_parses_with_real_parser(self):
        args = build_parser().parse_args(
            shlex.split("handoff load --project PROJECTS/workflow-demo")
        )
        self.assertEqual(args.command, "handoff")
        self.assertEqual(args.subcommand, "load")

    def test_pre_fix_template_is_still_rejected(self):
        """Guards the regression: the old template must keep exiting with code 2."""
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                build_parser().parse_args(
                    shlex.split("orchestrate --project PROJECTS/workflow-demo")
                )
        self.assertEqual(ctx.exception.code, 2)


class AgentDelegationInstructionsTests(unittest.TestCase):
    """The coordinator's generated agent file must carry the delegation contract."""

    def test_generated_coordinator_agent_contains_delegation_section(self):
        from se_core.opencode.generator import generate
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            generate(support.REPO_ROOT, out)
            agent_md = (out / "agents" / "shema-ai-coordinador.md").read_text(encoding="utf-8")
        self.assertIn("## Delegation", agent_md)
        self.assertIn("background: true", agent_md)
        self.assertIn("Never poll", agent_md)
        self.assertIn("stay synchronous", agent_md)


class AgentOverviewNotInstructionSourceTests(unittest.TestCase):
    """Control test (B9): `.opencode/AGENTS.md` is an overview, NOT an
    instruction source consumed by OpenCode. Empirically verified that OpenCode
    injects only the agent definition file + Code Mode + personal instructions;
    `.opencode/AGENTS.md` is never loaded. This test guards that the overview
    stays free of operational delegation instructions."""

    def test_agents_md_overview_carries_no_operational_instructions(self):
        from se_core.opencode.generator import generate
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            generate(support.REPO_ROOT, out)
            agents_md = (out / "AGENTS.md").read_text(encoding="utf-8")
            agent_md = (out / "agents" / "shema-ai-coordinador.md").read_text(encoding="utf-8")
        for keyword in ("background: true", "Never poll", "subagent", "invoke", "Delegation", "Communication"):
            self.assertNotIn(keyword, agents_md, f"AGENTS.md must not contain '{keyword}'")
        self.assertIn("## Delegation", agent_md)
        self.assertIn("## Communication", agent_md)


if __name__ == "__main__":
    unittest.main()
