"""Tests for ``se install`` (operator setup for a runtime).

Hermetic: every external boundary (platform, executable lookup, subprocess runner)
is injected, so these tests never spawn the real ``opencode`` CLI and never mutate a
real OpenCode configuration.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core import install  # noqa: E402
from se_core import lifecycle_state as lc  # noqa: E402


class DetectOsTests(unittest.TestCase):
    def test_windows(self):
        self.assertEqual(install.detect_os("win32"), "windows")

    def test_linux(self):
        for value in ("linux", "linux2"):
            self.assertEqual(install.detect_os(value), "linux")

    def test_macos(self):
        self.assertEqual(install.detect_os("darwin"), "macos")

    def test_current_platform_is_supported(self):
        self.assertIn(install.detect_os(), install.SUPPORTED_OS)

    def test_unknown_platform_raises(self):
        with self.assertRaises(ValueError):
            install.detect_os("plan9")


class LoadMcpTemplatesTests(unittest.TestCase):
    def test_loads_all_four_servers(self):
        templates = install.load_mcp_templates(support.REPO_ROOT)
        keys = [t["key"] for t in templates]
        self.assertEqual(
            keys, ["context7", "filesystem", "memory-server", "skill-server"]
        )

    def test_template_records_expose_command_and_args(self):
        by_key = {t["key"]: t for t in install.load_mcp_templates(support.REPO_ROOT)}
        self.assertTrue(by_key["context7"]["command"])
        self.assertIsInstance(by_key["context7"]["args"], list)
        self.assertIsInstance(by_key["filesystem"]["env"], dict)

    def test_context7_is_pinned_to_a_working_release(self):
        # 4.4.4 ships an exports map pointing at dist/index.mjs, which is
        # missing from the published tarball; npx exits before the handshake.
        by_key = {t["key"]: t for t in install.load_mcp_templates(support.REPO_ROOT)}
        self.assertIn("@upstash/context7-mcp@4.4.0", by_key["context7"]["args"])

    def test_registered_name_can_differ_from_key(self):
        by_key = {t["key"]: t for t in install.load_mcp_templates(support.REPO_ROOT)}
        self.assertEqual(by_key["skill-server"]["key"], "skill-server")
        self.assertEqual(by_key["skill-server"]["name"], "se-skill-server")

    def test_template_path_is_relative(self):
        for template in install.load_mcp_templates(support.REPO_ROOT):
            self.assertFalse(Path(template["template"]).is_absolute())
            self.assertTrue(template["template"].startswith("TEMPLATES/"))


class SelectServersTests(unittest.TestCase):
    def setUp(self):
        self.templates = install.load_mcp_templates(support.REPO_ROOT)

    def test_all_by_default(self):
        self.assertEqual(
            install.select_servers(self.templates),
             ["context7", "filesystem", "memory-server", "skill-server"],
        )

    def test_with_selects_subset(self):
        self.assertEqual(
            install.select_servers(self.templates, with_list="filesystem,context7"),
            ["context7", "filesystem"],
        )

    def test_with_accepts_spaces(self):
        self.assertEqual(
            install.select_servers(self.templates, with_list=" filesystem , skill-server "),
            ["filesystem", "skill-server"],
        )

    def test_unknown_server_raises(self):
        with self.assertRaises(ValueError):
            install.select_servers(self.templates, with_list="filesystem,nope")


class BuildPlanTests(unittest.TestCase):
    def _plan(self, **over):
        kwargs = dict(
            os_name="windows",
            se_root=support.REPO_ROOT,
            project=support.REPO_ROOT,
            dry_run=True,
        )
        kwargs.update(over)
        return install.build_plan(**kwargs)

    def test_plan_core_fields(self):
        plan = self._plan()
        self.assertEqual(plan["os"], "windows")
        self.assertEqual(plan["scope"], "project")
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["status"], "PASS")
        self.assertIn("se_root", plan)
        self.assertIn("project", plan)

    def test_plan_lists_servers(self):
        plan = self._plan()
        self.assertEqual(
            plan["servers"],
             ["context7", "filesystem", "memory-server", "skill-server"],
        )

    def test_global_scope_recorded(self):
        plan = self._plan(scope="global")
        self.assertEqual(plan["scope"], "global")

    def test_env_vars_from_templates(self):
        plan = self._plan()
        self.assertIn("CONTEXT7_API_KEY", plan["env_vars"])
        self.assertIn("SE_ROOT", plan["env_vars"])
        self.assertIn("SE_PROJECT_ROOT", plan["env_vars"])

    def test_no_register_recorded(self):
        plan = self._plan(register=False)
        self.assertFalse(plan["register"])


class RenderPlanTests(unittest.TestCase):
    def _plan(self, **over):
        kwargs = dict(
            os_name="linux",
            se_root=support.REPO_ROOT,
            project=support.REPO_ROOT,
            dry_run=True,
        )
        kwargs.update(over)
        return install.build_plan(**kwargs)

    def test_render_mentions_os_and_dry_run(self):
        text = install.render_plan(self._plan())
        self.assertIn("OS: linux", text)
        self.assertIn("dry-run", text)

    def test_render_lists_servers(self):
        text = install.render_plan(self._plan())
        self.assertIn("context7", text)
        self.assertIn("skill-server", text)

    def test_render_is_deterministic(self):
        plan = self._plan()
        self.assertEqual(install.render_plan(plan), install.render_plan(plan))

    def test_render_no_register_note(self):
        text = install.render_plan(self._plan(register=False))
        self.assertIn("--no-register", text)


class CliInstallDryRunTests(unittest.TestCase):
    def test_dry_run_exit_zero_and_mentions_os(self):
        code, out = support.run_cli("install", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("OS:", out)
        self.assertIn("dry-run", out)

    def test_dry_run_in_temp_project_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = support.run_cli("install", "--project", tmp, "--dry-run")
            self.assertEqual(code, 0, out)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_dry_run_json_envelope(self):
        import json

        code, out = support.run_cli("install", "--dry-run", "--json")
        self.assertEqual(code, 0, out)
        envelope = json.loads(out)
        self.assertEqual(envelope["report"], "se.report/1")
        self.assertEqual(envelope["operation"], "install")
        self.assertIn("details", envelope)
        self.assertEqual(envelope["details"]["os"], install.detect_os())

    def test_all_and_with_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code, _ = support.run_cli("install", "--dry-run", "--all", "--with", "context7")
        self.assertEqual(code, 2)


class ResolvePythonInterpreterTests(unittest.TestCase):
    def test_prefers_python3(self):
        which = lambda name: "/usr/bin/" + name
        self.assertEqual(install.resolve_python_interpreter(which), "python3")

    def test_falls_back_to_python(self):
        self.assertEqual(
            install.resolve_python_interpreter(lambda name: name == "python"), "python"
        )

    def test_none_when_missing(self):
        self.assertIsNone(install.resolve_python_interpreter(lambda name: None))


class PreflightTests(unittest.TestCase):
    def test_all_present_in_declared_order(self):
        which = lambda name: "/usr/bin/" + name
        # With context7 and filesystem selected, node should be included
        items = install.preflight_dependencies("linux", which=which, selected_servers=["context7", "filesystem"])
        self.assertEqual(
            [i["name"] for i in items],
            ["python", "node", "opencode"],
        )
        for item in items:
            self.assertEqual(item["status"], "PASS", item)
            self.assertTrue(item["guidance"])

    def test_node_skipped_when_not_needed(self):
        which = lambda name: "/usr/bin/" + name
        # Without context7/filesystem, node should be skipped
        items = install.preflight_dependencies("linux", which=which, selected_servers=["skill-server"])
        self.assertEqual(
            [i["name"] for i in items],
            ["python", "opencode"],
        )

    def test_missing_reports_warn_with_detail_and_guidance(self):
        items = {i["name"]: i for i in install.preflight_dependencies("windows", which=lambda name: None)}
        self.assertEqual(items["opencode"]["status"], "WARN")
        self.assertIn("not found", items["opencode"]["detail"])
        self.assertIn("opencode", items["opencode"]["guidance"].lower())

    def test_guidance_is_os_specific(self):
        which = lambda name: None
        win = {i["name"]: i for i in install.preflight_dependencies("windows", which=which, selected_servers=["context7"])}
        mac = {i["name"]: i for i in install.preflight_dependencies("macos", which=which, selected_servers=["context7"])}
        self.assertNotEqual(win["node"]["guidance"], mac["node"]["guidance"])

    def test_python_uses_resolved_interpreter(self):
        which = lambda name: name == "python"
        items = {i["name"]: i for i in install.preflight_dependencies("linux", which=which)}
        self.assertEqual(items["python"]["status"], "PASS")
        self.assertIn("python", items["python"]["detail"])


class BuildPlanPreflightTests(unittest.TestCase):
    def test_plan_carries_preflight_and_missing_dependencies(self):
        preflight = [
            {"name": "python", "status": "PASS", "detail": "python3", "guidance": "g", "purpose": "p"},
            {"name": "codegraph", "status": "WARN", "detail": "not found", "guidance": "g", "purpose": "p"},
        ]
        plan = install.build_plan(
            os_name="windows", se_root=support.REPO_ROOT, project=support.REPO_ROOT,
            dry_run=True, preflight=preflight,
        )
        self.assertEqual(plan["preflight"], preflight)
        self.assertEqual(plan["missing_dependencies"], ["codegraph"])


class RenderPreflightTests(unittest.TestCase):
    def test_render_shows_warn_detail_and_guidance(self):
        preflight = [
            {"name": "codegraph", "status": "WARN", "detail": "not found",
             "guidance": "Install CodeGraph.", "purpose": "p"},
        ]
        plan = install.build_plan(
            os_name="windows", se_root=support.REPO_ROOT, project=support.REPO_ROOT,
            dry_run=True, preflight=preflight,
        )
        text = install.render_plan(plan)
        self.assertIn("[WARN] codegraph: not found", text)
        self.assertIn("Install CodeGraph.", text)


class CliPreflightTests(unittest.TestCase):
    def test_dry_run_shows_preflight_section(self):
        code, out = support.run_cli("install", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("Preflight:", out)


class ResolvePlaceholdersTests(unittest.TestCase):
    def setUp(self):
        self.context = {"se_root": "/se", "se_project_root": "/proj", "project_id": "PRJ-X"}

    def test_resolves_paths_and_project_id_in_args_mode(self):
        self.assertEqual(install.resolve_placeholders("${SE_ROOT}", self.context, env_mode=False), "/se")
        self.assertEqual(install.resolve_placeholders("${SE_PROJECT_ROOT}", self.context, env_mode=False), "/proj")
        self.assertEqual(install.resolve_placeholders("{{project_id}}", self.context, env_mode=False), "PRJ-X")

    def test_unknown_env_ref_is_left_literal_in_args_mode(self):
        self.assertEqual(install.resolve_placeholders("${OTHER}", self.context, env_mode=False), "${OTHER}")

    def test_unknown_env_ref_becomes_runtime_reference_in_env_mode(self):
        self.assertEqual(
            install.resolve_placeholders("${CONTEXT7_API_KEY}", self.context, env_mode=True),
            "{env:CONTEXT7_API_KEY}",
        )


class BuildRegistrationsTests(unittest.TestCase):
    def setUp(self):
        self.templates = {t["key"]: t for t in install.load_mcp_templates(support.REPO_ROOT)}

    def _preflight(self, missing=()):
        return [
            {"name": name, "status": "WARN" if name in missing else "PASS",
             "detail": "x", "guidance": "g", "purpose": "p"}
            for name in ("python", "node", "opencode", "codegraph")
        ]

    def _build(self, keys, **over):
        kwargs = dict(
            se_root="/se", project="/proj", project_id="PRJ-X",
            interpreter="python3", scope="project", register=True,
            preflight=self._preflight(),
        )
        kwargs.update(over)
        return install.build_registrations([self.templates[k] for k in keys], **kwargs)

    def test_plain_local_command(self):
        reg = self._build(["skill-server"])[0]
        self.assertEqual(
            reg["command"],
            ["opencode", "mcp", "add", "se-skill-server", "--",
             "python3", "/se/SCRIPTS/se_core/mcp/skill_server.py"],
        )
        self.assertEqual(reg["status"], "planned")

    def test_args_placeholder_resolved(self):
        by_key = {r["server"]: r for r in self._build(["filesystem"])}
        self.assertEqual(
            by_key["filesystem"]["command"],
            ["opencode", "mcp", "add", "filesystem", "--",
             "npx", "-y", "@modelcontextprotocol/server-filesystem", "/proj"],
        )

    def test_env_flag_uses_runtime_reference_and_sorts_keys(self):
        # Synthetic template so the ordering of multiple env entries is pinned
        # independently of any real server's env set.
        template = {
            "key": "synthetic", "name": "synthetic", "command": "tool",
            "args": ["serve"],
            "env": {"Z_LAST": "${Z_LAST}", "A_FIRST": "${A_FIRST}"},
        }
        kwargs = dict(
            se_root="/se", project="/proj", project_id="PRJ-X",
            interpreter="python3", scope="project", register=True,
            preflight=self._preflight(),
        )
        [reg] = install.build_registrations([template], **kwargs)
        self.assertEqual(
            reg["command"],
            ["opencode", "mcp", "add",
             "--env", "A_FIRST={env:A_FIRST}",
             "--env", "Z_LAST={env:Z_LAST}",
             "synthetic", "--", "tool", "serve"],
        )

    def test_secret_env_ref_becomes_env_substitution(self):
        reg = self._build(["context7"])[0]
        self.assertIn("--env", reg["command"])
        self.assertIn("CONTEXT7_API_KEY={env:CONTEXT7_API_KEY}", reg["command"])

    def test_interpreter_python_fallback(self):
        reg = self._build(["skill-server"], interpreter="python")[0]
        self.assertEqual(reg["command"][reg["command"].index("--") + 1], "python")

    def test_global_scope_inserts_flag(self):
        reg = self._build(["filesystem"], scope="global")[0]
        self.assertEqual(reg["command"][:4], ["opencode", "mcp", "add", "--global"])

    def test_missing_dependency_skips_server(self):
        # context7 depends on node; if node is missing, context7 should be skipped
        reg = self._build(["context7"], preflight=self._preflight(missing=("node",)))[0]
        self.assertEqual(reg["status"], "skipped")
        self.assertIn("missing dependency: node", reg["reason"])

    def test_no_register_skips_everything(self):
        regs = self._build(["filesystem", "context7"], register=False)
        self.assertTrue(all(r["status"] == "skipped" for r in regs))
        self.assertTrue(all("--no-register" in r["reason"] for r in regs))


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or FakeResult(0)

    def __call__(self, command):
        self.calls.append(list(command))
        return self.result


class ExecuteRegistrationsTests(unittest.TestCase):
    def test_planned_servers_are_executed_and_status_updates(self):
        regs = [
            {"server": "a", "name": "a", "status": "planned", "reason": None,
             "command": ["opencode", "mcp", "add", "a", "--", "x"]},
            {"server": "b", "name": "b", "status": "planned", "reason": None,
             "command": ["opencode", "mcp", "add", "b", "--", "y"]},
        ]
        codes = iter([0, 2])
        calls = []

        def runner(command):
            calls.append(command)
            return FakeResult(next(codes), stderr="boom")

        install.execute_registrations(regs, runner)
        self.assertEqual([r["status"] for r in regs], ["registered", "skipped"])
        self.assertIn("boom", regs[1]["reason"])
        self.assertTrue(all(command[0] == "opencode" for command in calls))

    def test_skipped_servers_are_not_executed(self):
        regs = [{"server": "c", "name": "c", "status": "skipped", "reason": "x",
                 "command": ["opencode", "mcp", "add", "c"]}]
        calls = []

        def runner(command):
            calls.append(command)
            return FakeResult(0)

        install.execute_registrations(regs, runner)
        self.assertEqual(calls, [])


class ProjectIdTests(unittest.TestCase):
    def test_reads_project_id_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            support.write_json(root / "PROJECT.json", {"project_id": "PRJ-9"})
            self.assertEqual(install.read_project_id(root), "PRJ-9")

    def test_falls_back_to_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(install.read_project_id(Path(tmp)), Path(tmp).name)


class AdapterSelectionTests(unittest.TestCase):
    def test_skipped_without_flag(self):
        entry = install.plan_adapter_selection(support.REPO_ROOT, support.REPO_ROOT, generate=False)
        self.assertEqual(entry["status"], "skipped")

    def test_planned_for_consumer_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = install.plan_adapter_selection(support.REPO_ROOT, Path(tmp), generate=True)
            self.assertEqual(entry["status"], "planned")

    def test_refuses_the_se_repository_itself(self):
        entry = install.plan_adapter_selection(support.REPO_ROOT, support.REPO_ROOT, generate=True)
        self.assertEqual(entry["status"], "BLOCKED")
        self.assertIn(".opencode", entry["reason"])


class CliRegistrationTests(unittest.TestCase):
    def test_with_selects_subset_in_plan(self):
        code, out = support.run_cli("install", "--with", "skill-server", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("Servers to register (1): skill-server", out)

    def test_no_register_writes_nothing_and_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = support.run_cli("install", "--no-register", "--project", tmp)
            self.assertEqual(code, 0, out)
            self.assertIn("--no-register", out)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_dry_run_json_lists_registration_commands(self):
        import json

        code, out = support.run_cli("install", "--dry-run", "--json")
        self.assertEqual(code, 0, out)
        details = json.loads(out)["details"]
        commands = {r["server"]: r["command"] for r in details["registrations"]}
        self.assertIn("skill-server", commands)
        # Planned registrations carry the opencode argv. Servers whose external
        # dependency is missing in this environment (the CLI probes real binaries)
        # are skipped and carry no command, which is environment-dependent by
        # design; skill-server only needs python, so it is planned everywhere.
        self.assertTrue(all((not command) or command[0] == "opencode" for command in commands.values()))
        self.assertNotEqual(commands["skill-server"], [])
        self.assertIn("opencode", commands["skill-server"][:3])

    def test_generate_adapter_refused_in_se_repo(self):
        code, out = support.run_cli(
            "install", "--dry-run", "--generate-adapter", "--project", str(support.REPO_ROOT)
        )
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED", out)


# --------------------------------------------------------------------------- #
# T5: resolved spec + lifecycle-state recording + `--global` runtime probe
# --------------------------------------------------------------------------- #


class ResolvedServerSpecTests(unittest.TestCase):
    def _template(self, **over):
        data = {
            "key": "demo",
            "name": "demo",
            "command": "python",
            "args": ["-m", "demo", "${SE_ROOT}/x"],
            "env": {"KEY": "${CONTEXT7_API_KEY}", "PATH_REF": "${SE_PROJECT_ROOT}/data"},
            "template": "TEMPLATES/mcp/demo.json.tmpl",
        }
        data.update(over)
        return data

    def _spec(self, **over):
        kwargs = dict(se_root="/se", project="/proj", project_id="PRJ-X", interpreter="python3")
        kwargs.update(over)
        return install.resolved_server_spec(self._template(), **kwargs)

    def test_spec_shape_is_plain_dict(self):
        spec = self._spec()
        self.assertEqual(spec["name"], "demo")
        self.assertEqual(spec["command"], ["python3", "-m", "demo", "/se/x"])
        self.assertEqual(
            spec["environment"],
            {"KEY": "{env:CONTEXT7_API_KEY}", "PATH_REF": "/proj/data"},
        )

    def test_python_interpreter_substituted(self):
        spec = self._spec(interpreter="python")
        self.assertEqual(spec["command"][0], "python")

    def test_placeholder_resolution_matches_registrations(self):
        spec = self._spec()
        template = self._template()
        registration = install.build_registrations(
            [template],
            se_root="/se", project="/proj", project_id="PRJ-X",
            interpreter="python3", scope="project", register=True,
            preflight=[{"name": "python", "status": "PASS", "detail": "x", "guidance": "g", "purpose": "p"}],
        )[0]
        self.assertIn("demo", registration["command"])
        self.assertEqual(spec["command"], registration["command"][registration["command"].index("--") + 1:])


class RecordLifecycleStateTests(unittest.TestCase):
    def test_state_written_after_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            runner = FakeRunner()
            args = types.SimpleNamespace(**{
                "project": str(project), "global": False, "no_register": False,
                "generate_adapter": False, "dry_run": False, "json": False, "with_": None,
            })
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = install.run(args, platform_name="windows", runner=runner,
                                   which=lambda name: name in ("python", "opencode"))
            self.assertEqual(code, 0, buffer.getvalue())
            self.assertTrue(lc.state_path(project).exists())
            state = lc.load_state(project)
            self.assertIsNotNone(state)
            self.assertIn("se-skill-server", state["servers"])
            self.assertEqual(len(state["servers"]["se-skill-server"]["declared"]), 64)
            self.assertTrue(state["se_version"])
            self.assertEqual(state["os"], "windows")

    def test_dry_run_writes_no_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            args = types.SimpleNamespace(**{
                "project": str(project), "global": False, "no_register": False,
                "generate_adapter": False, "dry_run": True, "json": False, "with_": None,
            })
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = install.run(args, platform_name="windows", runner=FakeRunner(),
                                   which=lambda name: name in ("python", "opencode"))
            self.assertEqual(code, 0, buffer.getvalue())
            self.assertFalse(lc.state_path(project).exists())


class ProbeGlobalSupportTests(unittest.TestCase):
    def test_probe_detects_global_from_help(self):
        runner = FakeRunner(FakeResult(0, stdout="--global  Register into the user config"))
        self.assertTrue(install.probe_global_support(runner))

    def test_probe_misses_global(self):
        runner = FakeRunner(FakeResult(0, stdout="--url   Register a remote server"))
        self.assertFalse(install.probe_global_support(runner))

    def test_probe_scans_stderr_too(self):
        runner = FakeRunner(FakeResult(0, stdout="", stderr="supports --global"))
        self.assertTrue(install.probe_global_support(runner))


class GlobalScopeRunTests(unittest.TestCase):
    def _args(self, project, global_scope):
        return types.SimpleNamespace(**{
            "project": str(project), "global": global_scope, "no_register": False,
            "generate_adapter": False, "dry_run": False, "json": False, "with_": None,
        })

    def test_global_supported_proceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            runner = FakeRunner(FakeResult(0, stdout="--global"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = install.run(self._args(project, True), platform_name="windows",
                                   runner=runner, which=lambda name: name in ("python", "opencode"))
            self.assertEqual(code, 0, buffer.getvalue())
            self.assertTrue(lc.state_path(project).exists())
            state = lc.load_state(project)
            self.assertEqual(state["servers"]["se-skill-server"]["scope"], "global")

    def test_global_unsupported_blocks_without_registering(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            runner = FakeRunner(FakeResult(0, stdout="--url only"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = install.run(self._args(project, True), platform_name="windows",
                                   runner=runner, which=lambda name: name in ("python", "opencode"))
            self.assertEqual(code, 1, buffer.getvalue())
            self.assertIn("does not support --global", buffer.getvalue())
            self.assertEqual(len(runner.calls), 1)
            self.assertFalse(lc.state_path(project).exists())


if __name__ == "__main__":
    unittest.main()


class EnvironmentTargetTests(unittest.TestCase):
    """Fase 2: env target detection, path translation and real binary probes."""

    def test_detect_env_target_windows(self):
        self.assertEqual(install.detect_env_target("win32"), "windows")

    def test_detect_env_target_wsl(self):
        self.assertEqual(install.detect_env_target("linux", wsl_distro="Ubuntu"), "wsl")

    def test_detect_env_target_plain_linux(self):
        self.assertEqual(install.detect_env_target("linux", wsl_distro=""), "linux")

    def test_translate_windows_to_wsl(self):
        self.assertEqual(install.translate_host_path("D:\\a\\b", "windows", "wsl"), "/mnt/d/a/b")
        self.assertEqual(install.translate_host_path("D:\\", "windows", "wsl"), "/mnt/d")

    def test_translate_wsl_to_windows(self):
        self.assertEqual(install.translate_host_path("/mnt/d/a/b", "wsl", "windows"), "D:\\a\\b")

    def test_translate_same_env_is_noop(self):
        self.assertEqual(install.translate_host_path("D:\\a", "windows", "windows"), "D:\\a")

    def test_path_mapper_none_when_same(self):
        self.assertIsNone(install.path_mapper_for("windows", "windows"))
        self.assertIsNone(install.path_mapper_for("windows", "auto"))
        self.assertIsNotNone(install.path_mapper_for("windows", "wsl"))

    def test_python_interpreter_prefers_portable_spelling(self):
        both = lambda name: name in ("python", "python3")
        self.assertEqual(install.resolve_python_interpreter(both, env_target="windows"), "python3")
        self.assertEqual(install.resolve_python_interpreter(both, env_target="wsl"), "python3")
        only_python = lambda name: name == "python"
        self.assertEqual(install.resolve_python_interpreter(only_python, env_target="windows"), "python")

    def test_probe_reports_stub_failure_with_remedy(self):
        class R:
            returncode = 1
            stdout = ""
            stderr = "Error: @opencode/cli's postinstall script was not run.\n"

        ok, version, detail = install.probe_command_version(
            "opencode", runner=lambda cmd, timeout=20: R()
        )
        self.assertFalse(ok)
        self.assertIn("postinstall", detail)
        status, _note, remedy = install.classify_opencode(
            ok=ok, version=version, detail=detail, os_name="windows"
        )
        self.assertEqual(status, "WARN")
        self.assertIn("npm rebuild -g @opencode/cli", remedy)

    def test_probe_reports_v1(self):
        class R:
            returncode = 0
            stdout = "1.19.0\n"
            stderr = ""

        ok, version, _ = install.probe_command_version(
            "opencode", runner=lambda cmd, timeout=20: R()
        )
        status, note, _remedy = install.classify_opencode(
            ok=ok, version=version, detail=None, os_name="linux"
        )
        self.assertEqual(status, "WARN")
        self.assertIn("v1", note.lower())

    def test_probe_reports_v2_pass(self):
        class R:
            returncode = 0
            stdout = "opencode v2.0.27\n"
            stderr = ""

        ok, version, _ = install.probe_command_version(
            "opencode", runner=lambda cmd, timeout=20: R()
        )
        status, _note, _remedy = install.classify_opencode(
            ok=ok, version=version, detail=None, os_name="windows"
        )
        self.assertEqual(status, "PASS")

    def test_preflight_probe_marks_broken_opencode(self):
        which = lambda name: name in ("opencode", "python")

        def fake_probe(command):
            if command == "opencode":
                return False, None, "postinstall script was not run"
            return True, "v1.0", None

        items = install.preflight_dependencies(
            "windows", which=which, selected_servers=[], probe=fake_probe
        )
        item = next(i for i in items if i["name"] == "opencode")
        self.assertEqual(item["status"], "WARN")
        self.assertIn("npm rebuild", item["guidance"])

    def test_resolved_spec_uses_path_mapper(self):
        template = {"name": "x", "command": "python3", "args": ["${SE_ROOT}/s.py"], "env": {}}
        mapper = install.path_mapper_for("windows", "wsl")
        spec = install.resolved_server_spec(
            template, se_root="D:\\se", project="D:\\se",
            project_id="p", interpreter="python3", path_mapper=mapper,
        )
        self.assertEqual(spec["command"], ["python3", "/mnt/d/se/s.py"])
