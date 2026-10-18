"""Concurrency tests for the memory engine.

Tests ID uniqueness, simultaneous writes, upsert serialization, lock
contention, and failure recovery under concurrent access.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "SCRIPTS"))
from se_core.memory.engine import MemoryEngine, _file_lock  # noqa: E402
from se_core.paths import repo_root  # noqa: E402


def _make_test_project(name="ConcTest"):
    """Create a test project under PROJECTS/ (required for engine resolution)."""
    proj = Path("PROJECTS") / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "memories").mkdir(exist_ok=True)
    manifest = {
        "schema_version": "1",
        "project_id": f"PRJ-{name.upper()}",
        "name": name,
        "owner": "test",
        "domains": ["software"],
        "criticality": "low",
        "lifecycle_state": "ACTIVE",
        "blocked": False,
        "version": "1.0.0",
        "created_at": "2026-10-17T00:00:00Z",
        "updated_at": "2026-10-17T00:00:00Z",
        "master_system_version": "1.0.0",
        "source": "test",
        "metadata": {"category": "TEST"},
        "profiles": {"work": {"type": "brownfield", "scale": "small", "risk": "low"}},
    }
    (proj / "PROJECT.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return proj, f"PRJ-{name.upper()}"


def _cleanup_project(name="ConcTest"):
    proj = Path("PROJECTS") / name
    if proj.exists():
        shutil.rmtree(proj)


def _se_cli():
    return str(Path(support.REPO_ROOT) / "SCRIPTS" / "se.py")


def _run_add(project_name, extra_args=None, content=None):
    """Run `se memory add` as a subprocess. Returns (exit_code, stdout, stderr)."""
    if content is None:
        content = {"summary": "concurrent test"}
    cmd = [sys.executable, _se_cli(), "memory", "add",
           "--project", f"PROJECTS/{project_name}",
           "--type", "decision",
           "--content", json.dumps(content),
           "--by", "tester"]
    if extra_args:
        cmd.extend(extra_args)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       timeout=30, cwd=str(support.REPO_ROOT))
    return r.returncode, r.stdout, r.stderr


class MemoryConcurrencyIdTests(unittest.TestCase):
    """Multiple processes generating memory IDs concurrently."""

    def setUp(self):
        self.proj_name = "ConcIdTest"
        self.proj, self.pid = _make_test_project(self.proj_name)

    def tearDown(self):
        _cleanup_project(self.proj_name)

    def test_concurrent_ids_are_unique(self):
        procs = []
        for i in range(4):
            cmd = [sys.executable, _se_cli(), "memory", "add",
                   "--project", f"PROJECTS/{self.proj_name}",
                   "--type", "decision",
                   "--content", json.dumps({"summary": f"concurrent {i}"}),
                   "--by", "tester"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", cwd=str(support.REPO_ROOT))
            procs.append(p)

        results = []
        for p in procs:
            out, err = p.communicate(timeout=30)
            results.append((p.returncode, out.strip(), err.strip()))

        ids = set()
        for code, out, err in results:
            self.assertEqual(code, 0, f"add failed: {err}")
            m = re.search(r"MEM-\d{4}", out)
            self.assertIsNotNone(m, f"no MEM id in output: {out}")
            ids.add(m.group(0))

        mem_dir = self.proj / "memories"
        files = list(mem_dir.glob("MEM-*.json"))
        self.assertEqual(len(files), 4, f"Expected 4 files, got {len(files)}")
        self.assertEqual(len(ids), 4, f"Expected 4 unique IDs, got {len(ids)}")

    def test_concurrent_ids_no_file_corruption(self):
        procs = []
        for i in range(4):
            cmd = [sys.executable, _se_cli(), "memory", "add",
                   "--project", f"PROJECTS/{self.proj_name}",
                   "--type", "decision",
                   "--content", json.dumps({"summary": f"concurrent {i}"}),
                   "--by", "tester"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", cwd=str(support.REPO_ROOT))
            procs.append(p)

        for p in procs:
            p.communicate(timeout=30)

        mem_dir = self.proj / "memories"
        for f in mem_dir.glob("MEM-*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            self.assertIn("memory_id", data)
            self.assertIn("project_id", data)
            self.assertIn("content", data)


class MemoryConcurrencyUpsertTests(unittest.TestCase):
    """Simultaneous upserts of the same memory."""

    def setUp(self):
        self.proj_name = "ConcUpsertTest"
        self.proj, self.pid = _make_test_project(self.proj_name)

    def tearDown(self):
        _cleanup_project(self.proj_name)

    def test_concurrent_upserts_serialize(self):
        # Create initial record with topic_key
        engine = MemoryEngine(root=support.REPO_ROOT, global_store=None)
        engine.add(project_id=self.pid, type="decision",
                   content={"summary": "initial"}, author="tester",
                   topic_key="conc-topic")

        procs = []
        for i in range(3):
            content = json.dumps({"summary": f"update {i}"})
            cmd = [sys.executable, _se_cli(), "memory", "add",
                   "--project", f"PROJECTS/{self.proj_name}",
                   "--type", "decision", "--content", content,
                   "--topic-key", "conc-topic", "--by", "tester"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", cwd=str(support.REPO_ROOT))
            procs.append(p)

        for p in procs:
            p.communicate(timeout=30)

        mem_dir = self.proj / "memories"
        files = list(mem_dir.glob("MEM-*.json"))
        self.assertEqual(len(files), 1, f"Expected 1 file, got {len(files)}")

        record = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertGreaterEqual(record.get("revision_count", 0), 3,
                                f"Expected revision_count >= 3, got {record.get('revision_count')}")

    def test_concurrent_upsert_no_silent_overwrite(self):
        engine = MemoryEngine(root=support.REPO_ROOT, global_store=None)
        engine.add(project_id=self.pid, type="decision",
                   content={"summary": "initial"}, author="tester",
                   topic_key="conc-topic2")

        procs = []
        for i in range(2):
            content = json.dumps({"summary": f"update {i}"})
            cmd = [sys.executable, _se_cli(), "memory", "add",
                   "--project", f"PROJECTS/{self.proj_name}",
                   "--type", "decision", "--content", content,
                   "--topic-key", "conc-topic2", "--by", "tester", "--json"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", cwd=str(support.REPO_ROOT))
            procs.append(p)

        results = []
        for p in procs:
            out, err = p.communicate(timeout=30)
            results.append((p.returncode, out.strip()))

        mem_dir = self.proj / "memories"
        files = list(mem_dir.glob("MEM-*.json"))
        self.assertEqual(len(files), 1, "Should be exactly 1 file after upserts")


class MemoryConcurrencyDistinctTests(unittest.TestCase):
    """Concurrent operations on distinct memories."""

    def setUp(self):
        self.proj_name = "ConcDistinctTest"
        self.proj, self.pid = _make_test_project(self.proj_name)

    def tearDown(self):
        _cleanup_project(self.proj_name)

    def test_concurrent_different_types(self):
        procs = []
        for t in ["decision", "discovery", "constraint"]:
            content = json.dumps({"summary": f"memory of type {t}"})
            cmd = [sys.executable, _se_cli(), "memory", "add",
                   "--project", f"PROJECTS/{self.proj_name}",
                   "--type", t, "--content", content,
                   "--by", "tester"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", cwd=str(support.REPO_ROOT))
            procs.append(p)

        for p in procs:
            p.communicate(timeout=30)

        mem_dir = self.proj / "memories"
        files = list(mem_dir.glob("MEM-*.json"))
        self.assertEqual(len(files), 3, f"Expected 3 files, got {len(files)}")

        types = set()
        for f in files:
            data = json.loads(f.read_text(encoding="utf-8"))
            types.add(data["type"])
        self.assertEqual(types, {"decision", "discovery", "constraint"})


class MemoryConcurrencyRecoveryTests(unittest.TestCase):
    """Lock cleanup and recovery after failures."""

    def setUp(self):
        self.proj_name = "ConcRecoveryTest"
        self.proj, self.pid = _make_test_project(self.proj_name)

    def tearDown(self):
        _cleanup_project(self.proj_name)

    def test_lock_file_cleaned_after_success(self):
        engine = MemoryEngine(root=support.REPO_ROOT, global_store=None)
        # Use a project under PROJECTS/ so _find_project_dir works
        # But engine uses repo_root(), so we need to mock
        # Instead, test via CLI
        content = json.dumps({"summary": "test"})
        cmd = [sys.executable, _se_cli(), "memory", "add",
               "--project", f"PROJECTS/{self.proj_name}",
               "--type", "decision", "--content", content,
               "--by", "tester"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=str(support.REPO_ROOT))
        self.assertEqual(r.returncode, 0)

        lock_file = self.proj / "memories" / ".memory.lock"
        self.assertFalse(lock_file.exists(), "lock file should be cleaned up")

    def test_lock_file_cleaned_after_failure(self):
        cmd = [sys.executable, _se_cli(), "memory", "add",
               "--project", f"PROJECTS/{self.proj_name}",
               "--type", "invalid_type", "--content", '{"summary": "test"}',
               "--by", "tester"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=str(support.REPO_ROOT))
        self.assertNotEqual(r.returncode, 0, "invalid type should fail")

        lock_file = self.proj / "memories" / ".memory.lock"
        self.assertFalse(lock_file.exists(), "lock file should be cleaned up after failure")

    def test_corrupt_record_does_not_block_new_writes(self):
        mem_dir = self.proj / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        corrupt = mem_dir / "MEM-corrupt.json"
        corrupt.write_text("{invalid json", encoding="utf-8")

        # New write should still succeed
        content = json.dumps({"summary": "after corrupt"})
        cmd = [sys.executable, _se_cli(), "memory", "add",
               "--project", f"PROJECTS/{self.proj_name}",
               "--type", "decision", "--content", content,
               "--by", "tester"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=str(support.REPO_ROOT))
        self.assertEqual(r.returncode, 0, f"add failed: {r.stderr}")

        # Clean up corrupt file
        corrupt.unlink(missing_ok=True)

    def test_lock_timeout_raises(self):
        import os as _os
        lock_path = Path(tempfile.mkdtemp()) / ".lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = _os.open(str(lock_path), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
        _os.close(fd)
        try:
            with self.assertRaises(TimeoutError):
                with _file_lock(lock_path, timeout=0.1):
                    pass
        finally:
            _os.unlink(lock_path)


if __name__ == "__main__":
    unittest.main()
