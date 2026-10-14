"""SE-CONSOLE :: idle timeout (lifecycle) tests -- DESIGN-5C option A.

What this file proves
---------------------
The console can stop itself once the client that was reading it has gone away.
Three states matter, and a naive implementation gets at least one wrong:

  I1  no client has EVER connected  -> it does NOT stop. The watch is DISARMED
      until the first request, so a headless `python -m console.server` cannot
      vanish before anyone has opened it.
  I2  a client connected, then left -> it DOES stop, on its own, and says so.
  I3  a client keeps pinging        -> it does NOT stop, and it stops only after
      the pinging really stops. Without I3, "it stopped" would be
      indistinguishable from "it never worked".

The trigger is deliberately the ABSENCE of a request rather than an unload
event, which is why this survives a browser crash or a kill -- cases where
`pagehide`/`sendBeacon` never fires at all (DESIGN-5C section 4).

The read-only surface is untouched: the heartbeat is a `GET`, and I2b asserts
that no POST exception was quietly added alongside it.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE_ROOT = os.path.dirname(HERE)
sys.path.insert(0, CONSOLE_ROOT)

#: Marker written ONLY when the watch actually fires; the startup line also
#: mentions the timeout, so tests must not match on those words alone.
STOP_MARKER = "no client for"

WORKING_SE = '''import json, sys
print(json.dumps({"report": "se.report/1", "status": "PASS", "details": {}}))
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_fixture(root: str) -> None:
    """A minimal SE root whose `se` answers, so preflight passes fast."""
    os.makedirs(os.path.join(root, "SCRIPTS"), exist_ok=True)
    with open(os.path.join(root, "SYSTEM.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "SYSTEM-ENGINEERING (idle fixture)", "status": "ACTIVE"}, fh)
    with open(os.path.join(root, "VERSION"), "w", encoding="utf-8") as fh:
        fh.write("0.0.0-fixture\n")
    with open(os.path.join(root, "SCRIPTS", "se.py"), "w", encoding="utf-8") as fh:
        fh.write(WORKING_SE)


class Server:
    """A console subprocess whose output goes to a file we can poll.

    Readiness is detected from the LOG, never by making a request: a request
    would arm the idle watch, and I1 needs the opposite of that.
    """

    def __init__(self, se_root: str, idle_timeout: float, log_path: str) -> None:
        self.port = _free_port()
        self.log_path = log_path
        self._log = open(log_path, "w+", encoding="utf-8")  # noqa: SIM115
        env = dict(
            os.environ,
            SE_ROOT=se_root,
            SE_CONSOLE_PORT=str(self.port),
            PYTHONUNBUFFERED="1",
        )
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "console.server", "--idle-timeout", str(idle_timeout)],
            cwd=CONSOLE_ROOT,
            env=env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def log(self) -> str:
        self._log.flush()
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    def alive(self) -> bool:
        return self.proc.poll() is None

    def wait_for_start(self, tries: int = 120) -> bool:
        for _ in range(tries):
            if "console on http://" in self.log():
                return True
            if not self.alive():
                return False
            time.sleep(0.5)
        return False

    def wait_for_exit(self, seconds: float = 25.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not self.alive():
                return True
            time.sleep(0.25)
        return False

    def _request(self, req: urllib.request.Request, timeout: int = 10):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # connection refused right after shutdown, etc.
            return None, f"ERR {type(e).__name__}: {e}"

    def get(self, path: str, timeout: int = 10):
        return self._request(
            urllib.request.Request(
                f"http://127.0.0.1:{self.port}{path}",
                headers={"Accept": "application/json"},
            ),
            timeout,
        )

    def post(self, path: str, body: bytes = b"{}", timeout: int = 10):
        return self._request(
            urllib.request.Request(
                f"http://127.0.0.1:{self.port}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout,
        )

    def stop(self) -> None:
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
        self._log.close()


class IdleWatchUnitTest(unittest.TestCase):
    """The watch's own semantics: no subprocess, no waiting on a poll."""

    def test_disabled_never_expires(self) -> None:
        from console.server import IdleWatch

        w = IdleWatch(0)
        w.touch()
        time.sleep(0.05)
        self.assertFalse(w.expired(), "timeout 0 must mean 'never stop'")

    def test_unarmed_never_expires(self) -> None:
        from console.server import IdleWatch

        w = IdleWatch(0.05)
        time.sleep(0.1)
        self.assertFalse(w.expired(), "a watch nobody has touched must not fire")

    def test_armed_expires_when_quiet(self) -> None:
        from console.server import IdleWatch

        w = IdleWatch(0.05)
        w.touch()
        self.assertFalse(w.expired())
        time.sleep(0.08)
        self.assertTrue(w.expired())

    def test_touch_postpones_expiry(self) -> None:
        from console.server import IdleWatch

        w = IdleWatch(0.2)
        for _ in range(5):
            w.touch()
            time.sleep(0.05)
        self.assertFalse(w.expired(), "a live client must keep the console alive")


class IdleTimeoutEndToEndTest(unittest.TestCase):
    """The real server process, stopped by its own watchdog or not."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="se-console-idle-")
        self.root = os.path.join(self.tmp, "SE")
        make_fixture(self.root)
        self.servers: list[Server] = []

    def tearDown(self) -> None:
        for s in self.servers:
            s.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, idle_timeout: float) -> Server:
        log_path = os.path.join(self.tmp, f"console-{len(self.servers)}.log")
        s = Server(self.root, idle_timeout, log_path)
        self.servers.append(s)
        self.assertTrue(s.wait_for_start(), f"console never started; log:\n{s.log()}")
        return s

    def test_I1_no_client_ever_means_no_stop(self) -> None:
        s = self.start(2)
        # Longer than the timeout PLUS the 5s poll interval, with zero requests.
        time.sleep(9)
        self.assertTrue(
            s.alive(),
            "the console stopped although no client had ever connected "
            f"(the watch must stay disarmed); log:\n{s.log()}",
        )
        self.assertNotIn(STOP_MARKER, s.log())
        # ...and it really is serving, so I1 is not passing by accident.
        status, _ = s.get("/api/health")
        self.assertEqual(status, 200)

    def test_I2_stops_after_the_client_leaves(self) -> None:
        s = self.start(2)
        status, body = s.get("/api/heartbeat")
        self.assertEqual(status, 200, body)
        self.assertIn("lifecycle heartbeat", body)

        # I2b: the new route opened NO POST exception -- still GET-only.
        post_status, post_body = s.post("/api/heartbeat")
        self.assertEqual(post_status, 405, f"POST must stay refused: {post_body}")
        self.assertIn("only GET/HEAD/OPTIONS", post_body)

        self.assertTrue(
            s.wait_for_exit(30),
            f"the console did not stop after its client left; log:\n{s.log()}",
        )
        self.assertIn(STOP_MARKER, s.log())

    def test_I3_pinging_keeps_it_alive_then_it_stops(self) -> None:
        s = self.start(2)
        for _ in range(10):
            status, _ = s.get("/api/heartbeat")
            self.assertEqual(status, 200)
            self.assertTrue(s.alive(), "a heartbeating console must stay up")
            time.sleep(1)
        self.assertNotIn(
            STOP_MARKER,
            s.log(),
            "the console stopped even though the client kept pinging",
        )
        # And the liveness above was real: once the pinging stops, it goes.
        self.assertTrue(
            s.wait_for_exit(30),
            f"it did not stop once the pinging stopped; log:\n{s.log()}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
