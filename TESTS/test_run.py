"""`se run` tests: the RUN artifact and its start/checkpoint/close command group."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from se_core.paths import load_json  # noqa: E402
from se_core.schemas import validate  # noqa: E402

RUNTIME_KEYS = (
    "adapter",
    "harness",
    "model",
    "provider",
    "platform",
    "python",
    "environment",
    "source",
    "captured_at",
)


class RunStartTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")
        self.schemas = support.schemas()

    def tearDown(self):
        self._tmp.cleanup()

    def start(self, *extra):
        return support.run_cli("run", "start", "--project", str(self.project), *extra)

    def read(self, ident="RUN-0001"):
        return load_json(self.project / "runs" / f"{ident}.json")

    def test_start_creates_running_run_with_runtime(self):
        code, out = self.start(
            "--objective", "Ship the RUN artifact", "--scope", "run lifecycle",
            "--task", "TASK-0001,TASK-0002", "--author", "alice",
        )
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: started RUN-0001", out)
        self.assertTrue((self.project / "runs" / "RUN-0001.json").exists())
        data = self.read()
        self.assertEqual(data["run_id"], "RUN-0001")
        self.assertEqual(data["project_id"], "PRJ-TEST-001")
        self.assertEqual(data["state"], "RUNNING")
        self.assertEqual(data["author"], "alice")
        self.assertEqual(data["intent"]["objective"], "Ship the RUN artifact")
        self.assertEqual(data["intent"]["scope"], "run lifecycle")
        self.assertEqual(data["execution"]["tasks"], ["TASK-0001", "TASK-0002"])
        runtime = data["runtime"]
        for key in RUNTIME_KEYS:
            self.assertIn(key, runtime, f"runtime missing {key}")
        self.assertIn(runtime["source"], {"observed", "declared", "unknown"})
        self.assertTrue(runtime["captured_at"])
        self.assertEqual(validate(data, self.schemas["run"]), [])

    def test_start_without_optional_args_does_not_crash(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        data = self.read()
        self.assertEqual(data["state"], "RUNNING")
        self.assertEqual(data["intent"]["objective"], "To be defined.")
        self.assertEqual(validate(data, self.schemas["run"]), [])

    def test_start_with_agent_does_not_crash(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, out = self.start("--agent", "tester")
        self.assertEqual(code, 0, out)
        runtime = self.read()["runtime"]
        self.assertIn(runtime["source"], {"observed", "declared", "unknown"})
        # agent contracts carry no llm_config, so the model stays unknown
        self.assertEqual(runtime["model"], "unknown")

    def test_new_run_is_schema_valid(self):
        code, out = support.run_cli(
            "new", "run", "--project", str(self.project), "--title", "Manual run"
        )
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: created RUN-0001", out)
        data = self.read()
        self.assertEqual(data["state"], "PENDING")
        self.assertEqual(data["intent"]["objective"], "Manual run")
        self.assertEqual(validate(data, self.schemas["run"]), [])


class RuntimeCaptureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = support.make_project(self.root / "proj")

    def tearDown(self):
        self._tmp.cleanup()

    def capture(self, root, env=None):
        from se_core import commands

        with mock.patch.object(commands, "repo_root", return_value=root):
            with mock.patch.dict(os.environ, env or {}, clear=True):
                return commands._capture_runtime(self.project)

    def test_unknown_when_manifest_absent_and_no_env(self):
        empty_root = self.root / "empty-root"
        empty_root.mkdir(parents=True, exist_ok=True)
        runtime = self.capture(empty_root)
        self.assertEqual(runtime["source"], "unknown")
        self.assertEqual(runtime["adapter"], "unknown")
        self.assertEqual(runtime["harness"], "unknown")
        self.assertEqual(runtime["model"], "unknown")
        self.assertEqual(runtime["provider"], "unknown")
        self.assertEqual(runtime["environment"], "local")
        self.assertTrue(runtime["captured_at"])

    def test_observed_from_adapter_manifest(self):
        adapter_dir = self.root / "root-with-adapter" / ".opencode"
        support.write_json(adapter_dir / "adapter-manifest.json", {"adapter_id": "testadapt"})
        runtime = self.capture(self.root / "root-with-adapter")
        self.assertEqual(runtime["source"], "observed")
        self.assertEqual(runtime["adapter"], "testadapt")
        self.assertEqual(runtime["harness"], "testadapt")

    def test_declared_from_environment(self):
        empty_root = self.root / "empty-root"
        empty_root.mkdir(parents=True, exist_ok=True)
        runtime = self.capture(
            empty_root, {"SE_ADAPTER": "envadapt", "SE_MODEL": "m-1", "CI": "1"}
        )
        self.assertEqual(runtime["source"], "declared")
        self.assertEqual(runtime["adapter"], "envadapt")
        self.assertEqual(runtime["model"], "m-1")
        self.assertEqual(runtime["environment"], "ci")

    def test_never_raises_on_unreadable_manifest(self):
        broken_root = self.root / "broken-root"
        manifest = broken_root / ".opencode" / "adapter-manifest.json"
        support.write_json(manifest, {})
        manifest.write_text("{ this is not json", encoding="utf-8")
        runtime = self.capture(broken_root, {"SE_HARNESS": "h-1"})
        self.assertEqual(runtime["source"], "declared")
        self.assertEqual(runtime["harness"], "h-1")


class RunCheckpointCloseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")
        self.schemas = support.schemas()
        code, out = support.run_cli(
            "run", "start", "--project", str(self.project), "--objective", "O"
        )
        self.assertEqual(code, 0, out)

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, ident="RUN-0001"):
        return load_json(self.project / "runs" / f"{ident}.json")

    def checkpoint(self, *extra):
        return support.run_cli(
            "run", "checkpoint", "--project", str(self.project), "--run", "RUN-0001", *extra
        )

    def close(self, *extra):
        return support.run_cli(
            "run", "close", "--project", str(self.project), "--run", "RUN-0001", *extra
        )

    def test_checkpoint_updates_checkpoint_fields(self):
        code, out = self.checkpoint(
            "--next-step", "Continue with the parser",
            "--completed", "TASK-0001,TASK-0002",
            "--pending", "TASK-0003",
            "--state", "RUNNING",
        )
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: checkpoint recorded for RUN-0001", out)
        data = self.read()
        checkpoint = data["checkpoint"]
        self.assertTrue(checkpoint["at"])
        self.assertEqual(checkpoint["state"], "RUNNING")
        self.assertEqual(checkpoint["next_step"], "Continue with the parser")
        self.assertEqual(checkpoint["completed"], ["TASK-0001", "TASK-0002"])
        self.assertEqual(checkpoint["pending"], ["TASK-0003"])
        self.assertTrue(data["updated_at"])
        self.assertEqual(data["state"], "RUNNING")
        self.assertEqual(validate(data, self.schemas["run"]), [])

    def test_checkpoint_missing_run_fails(self):
        code, out = support.run_cli(
            "run", "checkpoint", "--project", str(self.project), "--run", "RUN-9999"
        )
        self.assertNotEqual(code, 0, out)
        self.assertIn("FAIL:", out)
        self.assertIn("RUN-9999", out)

    def test_close_sets_state(self):
        code, out = self.close("--state", "COMPLETED", "--summary", "All green.", "--by", "alice")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: closed RUN-0001 (COMPLETED)", out)
        data = self.read()
        self.assertEqual(data["state"], "COMPLETED")
        self.assertEqual(data["recovery"]["notes"], "All green.")
        self.assertTrue(data["updated_at"])
        self.assertEqual(validate(data, self.schemas["run"]), [])

    def test_close_invalid_state_fails(self):
        code, out = self.close("--state", "ARCHIVED")
        self.assertNotEqual(code, 0, out)
        self.assertIn("FAIL:", out)
        self.assertEqual(self.read()["state"], "RUNNING")

    def test_close_missing_run_fails(self):
        code, out = support.run_cli(
            "run", "close", "--project", str(self.project),
            "--run", "RUN-9999", "--state", "COMPLETED",
        )
        self.assertNotEqual(code, 0, out)
        self.assertIn("FAIL:", out)


class RunIdempotencyAuditRevisionTests(unittest.TestCase):
    """Optional --idempotency-key / --expected-revision on `se run` + audit coverage."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")
        self.run_file = self.project / "runs" / "RUN-0001.json"
        self.log_file = self.project / "mutation-log.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def start(self, *extra):
        return support.run_cli("run", "start", "--project", str(self.project), *extra)

    def checkpoint(self, *extra):
        return support.run_cli(
            "run", "checkpoint", "--project", str(self.project), "--run", "RUN-0001", *extra
        )

    def close(self, *extra):
        return support.run_cli(
            "run", "close", "--project", str(self.project), "--run", "RUN-0001", *extra
        )

    def log_entries(self):
        if not self.log_file.exists():
            return []
        entries = []
        for line in self.log_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def revision(self, path=None):
        return hashlib.sha256((path or self.run_file).read_bytes()).hexdigest()

    # --- audit coverage -------------------------------------------------

    def test_start_without_flags_appends_mutation_log_entry(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        entries = self.log_entries()
        self.assertEqual(len(entries), 1, out)
        entry = entries[0]
        self.assertEqual(entry["record_type"], "run")
        self.assertEqual(entry["record_id"], "RUN-0001")
        self.assertEqual(entry["by"], "tester")  # project owner fallback
        self.assertTrue(entry["at"])
        self.assertTrue(entry["changes"])
        # no key supplied -> legacy entry shape must not change
        self.assertNotIn("key", entry)
        self.assertNotIn("action", entry)

    def test_checkpoint_appends_mutation_log_entry(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        code, out = self.checkpoint("--next-step", "Keep going")
        self.assertEqual(code, 0, out)
        entries = self.log_entries()
        self.assertEqual(len(entries), 2, out)
        self.assertEqual(entries[0]["record_id"], "RUN-0001")
        self.assertEqual(entries[1]["record_type"], "run")
        self.assertEqual(entries[1]["record_id"], "RUN-0001")
        self.assertEqual(entries[1]["by"], "tester")
        self.assertTrue(entries[1]["changes"])

    def test_close_by_actor_is_recorded(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        code, out = self.close("--state", "COMPLETED", "--by", "alice")
        self.assertEqual(code, 0, out)
        entries = self.log_entries()
        self.assertEqual(len(entries), 2, out)
        self.assertEqual(entries[1]["by"], "alice")

    # --- idempotency ----------------------------------------------------

    def test_start_same_key_creates_only_one_run(self):
        code, out = self.start("--idempotency-key", "key-start-1")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: started RUN-0001", out)
        code, out = self.start("--idempotency-key", "key-start-1")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: replayed run.start (RUN-0001); idempotency key already applied", out)
        runs = sorted(p.name for p in (self.project / "runs").glob("RUN-*.json"))
        self.assertEqual(runs, ["RUN-0001.json"], f"replay created a second run: {runs}")
        # the replay must not append a second audit entry either
        keyed = [e for e in self.log_entries() if e.get("key") == "key-start-1"]
        self.assertEqual(len(keyed), 1)

    def test_start_different_keys_create_two_runs(self):
        code, out = self.start("--idempotency-key", "key-a")
        self.assertEqual(code, 0, out)
        code, out = self.start("--idempotency-key", "key-b")
        self.assertEqual(code, 0, out)
        runs = sorted(p.name for p in (self.project / "runs").glob("RUN-*.json"))
        self.assertEqual(runs, ["RUN-0001.json", "RUN-0002.json"], runs)

    def test_start_with_key_records_action_and_key(self):
        code, out = self.start("--idempotency-key", "key-c")
        self.assertEqual(code, 0, out)
        entries = self.log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].get("action"), "run.start")
        self.assertEqual(entries[0].get("key"), "key-c")

    def test_same_key_on_a_different_action_is_not_a_replay(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        code, out = self.checkpoint("--idempotency-key", "shared", "--next-step", "one")
        self.assertEqual(code, 0, out)
        self.assertIn("checkpoint recorded", out)
        # The same key on a DIFFERENT action is a different idempotent request:
        # it must apply, not replay the checkpoint.
        code, out = self.close("--idempotency-key", "shared", "--state", "COMPLETED")
        self.assertEqual(code, 0, out)
        self.assertNotIn("replayed", out)
        data = json.loads(self.run_file.read_text(encoding="utf-8"))
        self.assertEqual(data["state"], "COMPLETED")

    def test_key_recorded_by_close_does_not_short_circuit_start(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        code, out = self.close("--idempotency-key", "k-close", "--state", "COMPLETED")
        self.assertEqual(code, 0, out)
        # A key recorded by run.close must not swallow a run.start: a NEW run
        # must still be created, and the call must not report a replay.
        code, out = self.start("--idempotency-key", "k-close")
        self.assertEqual(code, 0, out)
        self.assertNotIn("replayed", out)
        runs = sorted((self.project / "runs").glob("RUN-*.json"))
        self.assertEqual(len(runs), 2, out)

    def test_close_replay_does_not_append_second_state_change(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        code, out = self.close("--state", "COMPLETED", "--by", "alice",
                               "--idempotency-key", "key-close-1")
        self.assertEqual(code, 0, out)
        entries_after_first = len(self.log_entries())
        raw_after_first = self.run_file.read_bytes()
        code, out = self.close("--state", "COMPLETED", "--by", "alice",
                               "--idempotency-key", "key-close-1")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: replayed run.close (RUN-0001); idempotency key already applied", out)
        self.assertEqual(len(self.log_entries()), entries_after_first, out)
        self.assertEqual(self.run_file.read_bytes(), raw_after_first)

    def test_checkpoint_replay_does_not_rewrite_run(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        code, out = self.checkpoint("--next-step", "One", "--idempotency-key", "key-ckpt-1")
        self.assertEqual(code, 0, out)
        raw_after_first = self.run_file.read_bytes()
        entries_after_first = len(self.log_entries())
        code, out = self.checkpoint("--next-step", "Two", "--idempotency-key", "key-ckpt-1")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: replayed run.checkpoint (RUN-0001); idempotency key already applied", out)
        self.assertEqual(self.run_file.read_bytes(), raw_after_first)
        self.assertEqual(len(self.log_entries()), entries_after_first)

    def test_malformed_log_does_not_crash_key_lookup(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.write_text("{ not json at all\n\x00garbage\n", encoding="utf-8")
        code, out = self.start("--idempotency-key", "key-after-garbage")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: started RUN-0001", out)
        self.assertTrue(self.run_file.exists())

    # --- expected revision ---------------------------------------------

    def test_checkpoint_expected_revision_correct_succeeds(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        expected = self.revision()
        code, out = self.checkpoint("--next-step", "Go", "--expected-revision", expected)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: checkpoint recorded for RUN-0001", out)
        self.assertEqual(load_json(self.run_file)["checkpoint"]["next_step"], "Go")

    def test_checkpoint_expected_revision_wrong_fails_without_write(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        raw_before = self.run_file.read_bytes()
        entries_before = len(self.log_entries())
        wrong = "0" * 64
        code, out = self.checkpoint("--next-step", "Go", "--expected-revision", wrong)
        self.assertNotEqual(code, 0, out)
        self.assertIn("FAIL:", out)
        self.assertIn(wrong, out)
        self.assertIn(self.revision(), out)
        self.assertEqual(self.run_file.read_bytes(), raw_before, "refusal wrote to the run file")
        self.assertEqual(len(self.log_entries()), entries_before, "refusal recorded an audit key")

    def test_close_expected_revision_wrong_fails_without_write(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        raw_before = self.run_file.read_bytes()
        wrong = "f" * 64
        code, out = self.close("--state", "FAILED", "--expected-revision", wrong)
        self.assertNotEqual(code, 0, out)
        self.assertIn("FAIL:", out)
        self.assertIn(wrong, out)
        self.assertIn(self.revision(), out)
        self.assertEqual(self.run_file.read_bytes(), raw_before)

    def test_close_expected_revision_correct_succeeds(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        expected = self.revision()
        code, out = self.close("--state", "COMPLETED", "--expected-revision", expected)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: closed RUN-0001 (COMPLETED)", out)

    # --- triangulation: check ordering ----------------------------------

    def test_retry_with_stale_revision_but_known_key_still_replays(self):
        # The console captures the revision before the first attempt; after a
        # successful write that revision is stale, so the retry must be decided
        # by the idempotency key, not by the revision refusal.
        code, out = self.start()
        self.assertEqual(code, 0, out)
        stale = self.revision()
        code, out = self.checkpoint(
            "--next-step", "One", "--idempotency-key", "key-retry",
            "--expected-revision", stale,
        )
        self.assertEqual(code, 0, out)
        code, out = self.checkpoint(
            "--next-step", "Two", "--idempotency-key", "key-retry",
            "--expected-revision", stale,
        )
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: replayed run.checkpoint (RUN-0001); idempotency key already applied", out)

    def test_revision_refusal_does_not_consume_the_key(self):
        code, out = self.start()
        self.assertEqual(code, 0, out)
        code, out = self.checkpoint(
            "--next-step", "Nope", "--idempotency-key", "key-refused",
            "--expected-revision", "0" * 64,
        )
        self.assertNotEqual(code, 0, out)
        # the same key must still be usable once the caller retries correctly
        correct = self.revision()
        code, out = self.checkpoint(
            "--next-step", "Yes", "--idempotency-key", "key-refused",
            "--expected-revision", correct,
        )
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: checkpoint recorded for RUN-0001", out)
        keyed = [e for e in self.log_entries() if e.get("key") == "key-refused"]
        self.assertEqual(len(keyed), 1)


class RunUpdateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = support.make_project(Path(self._tmp.name) / "proj")
        code, out = support.run_cli("run", "start", "--project", str(self.project))
        self.assertEqual(code, 0, out)

    def tearDown(self):
        self._tmp.cleanup()

    def update(self, *ops, by=None):
        argv = ["update", "run", "RUN-0001", "--project", str(self.project), *ops]
        if by:
            argv += ["--by", by]
        return support.run_cli(*argv)

    def test_update_run_accepted(self):
        code, out = self.update("--set", "author=alice")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS: updated RUN-0001", out)
        data = load_json(self.project / "runs" / "RUN-0001.json")
        self.assertEqual(data["author"], "alice")

    def test_update_state_is_controlled(self):
        code, out = self.update("--set", "state=COMPLETED")
        self.assertEqual(code, 1, out)
        self.assertIn("require --by", out)
        code, out = self.update("--set", "state=COMPLETED", by="alice")
        self.assertEqual(code, 0, out)
        data = load_json(self.project / "runs" / "RUN-0001.json")
        self.assertEqual(data["state"], "COMPLETED")


class StatusRunsEnvelopeTests(unittest.TestCase):
    """`se status --json` must surface RUNs like every other record type.

    The console reads RUNs from disk, but the CLI's aggregate read model is a
    contract of its own: a first-class record type missing from it is invisible
    to every other consumer.
    """

    def test_envelope_exposes_the_runs_root_key(self):
        from se_core.reporting import build_envelope

        env = build_envelope("status", "PASS", runs=[{"run_id": "RUN-0001"}])
        self.assertEqual(env["runs"], [{"run_id": "RUN-0001"}])

    def test_envelope_defaults_runs_to_an_empty_list(self):
        from se_core.reporting import build_envelope

        self.assertEqual(build_envelope("status", "PASS")["runs"], [])


if __name__ == "__main__":
    unittest.main()
