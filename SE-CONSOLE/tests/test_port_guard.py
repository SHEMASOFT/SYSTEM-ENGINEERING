"""T28: a second console must refuse to start instead of fighting for the port."""

from __future__ import annotations

import os
import socket
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE_ROOT = os.path.dirname(HERE)
sys.path.insert(0, CONSOLE_ROOT)

from console import server  # noqa: E402


class PortGuardTests(unittest.TestCase):
    def test_occupied_port_is_refused_with_a_next_action(self):
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            port = blocker.getsockname()[1]
            httpd, error = server.bind_console("127.0.0.1", port)
            self.assertIsNone(httpd)
            self.assertIsNotNone(error)
            self.assertIn("--port", error)
            self.assertIn(str(port), error)

    def test_free_port_binds_and_can_be_released(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        httpd, error = server.bind_console("127.0.0.1", port)
        self.assertIsNone(error, error)
        self.assertIsNotNone(httpd)
        httpd.server_close()

    def test_main_uses_the_bind_guard(self):
        source = open(os.path.join(CONSOLE_ROOT, "console", "server.py"), encoding="utf-8").read()
        self.assertIn("bind_console(BIND_HOST, args.port)", source)
        self.assertNotIn("ThreadingHTTPServer((BIND_HOST, BIND_PORT), ConsoleHandler)", source)


if __name__ == "__main__":
    unittest.main()
