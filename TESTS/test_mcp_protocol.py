"""JSON-RPC 2.0 compliance tests for the SE MCP servers.

OpenCode V2 rejects responses whose ``id`` is ``null``. A server that answers
a notification (a message without ``id``) therefore breaks the transport even
though the request itself succeeded. These tests pin the contract: notifications
must be ignored and ``ping`` must answer with an empty result.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402


REPO_ROOT = Path(support.REPO_ROOT)
SERVERS = ("memory_server.py", "skill_server.py")


def _readline(proc: subprocess.Popen, timeout: float = 20.0) -> str:
    """Read one stdout line with a timeout (Windows has no select on pipes)."""
    lines: queue.Queue = queue.Queue()

    def _reader() -> None:
        lines.put(proc.stdout.readline())

    threading.Thread(target=_reader, daemon=True).start()
    return lines.get(timeout=timeout)


class McpProtocolTests(unittest.TestCase):
    def _run_session(self, server: str) -> None:
        proc = subprocess.Popen(
            [sys.executable, f"SCRIPTS/se_core/mcp/{server}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
        )
        try:
            def send(message: dict) -> None:
                proc.stdin.write(json.dumps(message) + "\n")
                proc.stdin.flush()

            send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"project_root": str(REPO_ROOT)},
                }
            )
            init = json.loads(_readline(proc))
            self.assertEqual(init.get("id"), 1)
            self.assertIn("result", init)

            # A notification must produce no response: the next line we read
            # has to be the reply to the ping that follows it.
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            ping = json.loads(_readline(proc))
            self.assertEqual(ping.get("id"), 2, f"{server} answered a notification: {ping}")
            self.assertEqual(ping.get("result"), {})

            send({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
            tools = json.loads(_readline(proc))
            self.assertEqual(tools.get("id"), 3)
            self.assertGreater(len(tools.get("result", {}).get("tools", [])), 0)
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()

    def test_servers_ignore_notifications_and_answer_ping(self):
        for server in SERVERS:
            with self.subTest(server=server):
                self._run_session(server)


if __name__ == "__main__":
    unittest.main()
