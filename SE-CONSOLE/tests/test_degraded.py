"""SE-CONSOLE-002A :: degraded-engine regression tests.

Why this file exists
--------------------
POC-001's harness could only ever exercise the console against a *working*
engine, so three honesty defects shipped unnoticed:

  D5a  se_cli.se_available() tested file existence, not executability
  D5b  GET /api/health hardcoded "status": "OK" regardless of the engine
  D5c  the doctor rollup formatted "0 PASS, 0 WARN, 0 FAIL of 0 checks" when
       the engine was unreachable -- text that reads as a flawless result and
       silently converts UNKNOWN into 0, which the console's own contract
       forbids.

These are hermetic: they point SE_ROOT at a fixture whose `se` is deliberately
broken, so the degraded path is verified deterministically instead of waiting
for a real outage to happen. A test that only passes during an incident is not
a regression test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE_ROOT = os.path.dirname(HERE)

#: Canonical SE root exercised by phase C. Portable default: the sibling checkout
#: next to this console. The previous hardcoded Windows literal made phase C
#: unrunnable off Windows, which then overwrote this harness's committed evidence
#: with a truncated run.
SE_ROOT_REAL = os.environ.get("SE_ROOT_REAL") or os.path.join(
    os.path.dirname(CONSOLE_ROOT), "SYSTEM-ENGINEERING"
)

results: list[dict] = []


def check(cid: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append({"id": cid, "name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {cid} {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------------------
# Fixture: a SE root whose engine cannot run
# --------------------------------------------------------------------------

BROKEN_SE = '''import sys
# A stand-in for a SYSTEM-ENGINEERING mid-refactor: the entrypoint exists and
# is executable, but importing it fails. This is the exact shape of the
# SE-AUTOMATION-001C state (se_core/cli.py truncated to 0 bytes).
sys.stderr.write("ImportError: cannot import name 'main' from 'se_core.cli'\\n")
raise SystemExit(1)
'''

WORKING_SE = '''import json, sys
print(json.dumps({"report": "se.report/1", "status": "PASS", "details": {}}))
'''


def make_fixture(root: str, *, broken: bool) -> None:
    os.makedirs(os.path.join(root, "SCRIPTS"), exist_ok=True)
    with open(os.path.join(root, "SYSTEM.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "SYSTEM-ENGINEERING (fixture)", "status": "ACTIVE"}, fh)
    with open(os.path.join(root, "VERSION"), "w", encoding="utf-8") as fh:
        fh.write("0.0.0-fixture\n")
    with open(os.path.join(root, "SCRIPTS", "se.py"), "w", encoding="utf-8") as fh:
        fh.write(BROKEN_SE if broken else WORKING_SE)


class Server:
    def __init__(self, se_root: str, port: int) -> None:
        self.port = port
        env = dict(os.environ, SE_ROOT=se_root, SE_CONSOLE_PORT=str(port))
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "console.server"],
            cwd=CONSOLE_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def get(self, path: str, timeout: int = 90):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            return None, f"ERR {type(e).__name__}: {e}"

    def wait(self, tries: int = 90) -> bool:
        for _ in range(tries):
            st, _ = self.get("/api/health", timeout=5)
            if st == 200:
                return True
            time.sleep(0.5)
        return False

    def stop(self) -> str:
        self.proc.terminate()
        try:
            return self.proc.communicate(timeout=15)[0] or ""
        except Exception:
            self.proc.kill()
            return ""


def free_port(preferred: int) -> int:
    import socket

    for p in range(preferred, preferred + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise SystemExit("no free port")


# --------------------------------------------------------------------------


def run_degraded() -> None:
    print("\n[A] engine broken (exit 1, empty stdout) -- D5a/D5b/D5c")
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "SE_broken")
        make_fixture(root, broken=True)
        srv = Server(root, free_port(8821))
        try:
            if not srv.wait():
                check("D1", "console starts even when the engine is broken", False, "server never came up")
                return
            check("D1", "console starts even when the engine is broken", True,
                  "startup is refused only for misconfiguration, not for an outage")

            st, body = srv.get("/api/health")
            h = json.loads(body)
            check("D5a", "se_available reflects executability, not file existence",
                  h.get("se_available") is False,
                  f"se_available={h.get('se_available')} (se.py exists but cannot import)")
            check("D5b", "/api/health is not green while the engine is down",
                  h.get("status") != "OK" and h.get("status") == "DEGRADED",
                  f"status={h.get('status')}")
            check("D5b2", "the degradation reason is reported, not swallowed",
                  bool((h.get("se_probe") or {}).get("reason")),
                  f"reason={(h.get('se_probe') or {}).get('reason')!r}")

            st, body = srv.get("/api/system", timeout=180)
            sysd = json.loads(body)
            summary = str(sysd["health"]["summary"]["value"])
            check("D5c", "no '0 PASS ... of 0 checks' when the engine is unreachable",
                  "of 0 checks" not in summary,
                  f"summary={summary[:70]!r}")
            check("D5c2", "doctor rollup is tagged UNKNOWN, not DERIVED",
                  sysd["health"]["summary"]["epistemic"] == "UNKNOWN",
                  f"epistemic={sysd['health']['summary']['epistemic']}")
            check("D5c3", "system health state is not HEALTHY",
                  sysd["health"]["state"] != "HEALTHY",
                  f"state={sysd['health']['state']}")
            check("D5c4", "capability availability is UNKNOWN, not 0",
                  sysd["capabilities"]["available_count"]["epistemic"] == "UNKNOWN",
                  f"available_count={sysd['capabilities']['available_count']['value']!r}")
            check("D5d", "engine outage is surfaced in the payload",
                  sysd["health"]["engine"]["value"]["operational"] is False,
                  f"engine={sysd['health']['engine']['value']}")

            st, body = srv.get("/api/projects", timeout=180)
            check("D6", "canonical transcription still works with the engine down",
                  st == 200 and json.loads(body).get("total") is not None,
                  f"HTTP {st}")

            log = ""
        finally:
            log = srv.stop()
        check("D7", "startup log does not claim 'se reachable' when it is not",
              "se reachable" not in log,
              "preflight reports DEGRADED with the real reason"
              if "DEGRADED" in log else f"log={log[:120]!r}")


def run_healthy() -> None:
    print("\n[B] engine working -- the fix must not create a false alarm")
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "SE_ok")
        make_fixture(root, broken=False)
        srv = Server(root, free_port(8831))
        try:
            if not srv.wait():
                check("H1", "console starts with a working engine", False, "never came up")
                return
            check("H1", "console starts with a working engine", True, "")

            st, body = srv.get("/api/health")
            h = json.loads(body)
            check("H2", "se_available true when the engine really works",
                  h.get("se_available") is True, f"se_available={h.get('se_available')}")
            check("H3", "status OK when the engine really works",
                  h.get("status") == "OK", f"status={h.get('status')}")
        finally:
            log = srv.stop()
        check("H4", "startup log says OPERATIONAL for a working engine",
              "OPERATIONAL" in log, "")


def run_record_and_health_contract() -> None:
    """Record drill-down + CMD-0016 relay, against the REAL canonical root."""
    print("\n[C] record drill-down + CMD-0016 contract (real canonical root)")
    se_root = SE_ROOT_REAL
    srv = Server(se_root, free_port(8841))
    try:
        if not srv.wait():
            check("R1", "console starts against the canonical root", False, "never came up")
            return
        st, body = srv.get("/api/record?rel_path=PROJECTS/SHEMASEG&type=OBJECTIVE&id=OBJ-0001")
        rec = json.loads(body) if st == 200 else {}
        check("R1", "valid record returns 200 with the canonical record",
              st == 200 and rec.get("record", {}).get("value", {}).get("id") == "OBJ-0001",
              f"HTTP {st}")
        check("R2", "record is labelled OBSERVED with its canonical path",
              rec.get("record", {}).get("epistemic") == "OBSERVED"
              and "PROJECTS/SHEMASEG" in str(rec.get("record", {}).get("source")),
              f"source={rec.get('record', {}).get('source')}")

        for path, label, cid in [
            ("/api/record?rel_path=../../etc&type=OBJECTIVE&id=X", "traversal", "R3"),
            ("/api/record?rel_path=PROJECTS/SHEMASEG&type=BOGUS&id=X", "unknown type", "R4"),
            ("/api/record?rel_path=PROJECTS/SHEMASEG&type=OBJECTIVE&id=../../x", "bad id", "R5"),
        ]:
            st, _ = srv.get(path, timeout=30)
            check(cid, f"record endpoint refuses {label}", st == 400, f"HTTP {st}")

        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/api/record",
                                         data=b"{}", method=verb)
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            check(f"R6.{verb}", f"{verb} on /api/record is 405", code == 405, f"HTTP {code}")

        st, body = srv.get("/api/project?rel_path=PROJECTS/SHEMASEG", timeout=240)
        det = json.loads(body)
        sh = det.get("se_health") or {}
        check("H5", "project detail carries the CMD-0016 block", bool(sh.get("command_id")),
              f"command_id={(sh.get('command_id') or {}).get('value')}")
        check("H6", "CMD-0016 block cites the command contract as its source",
              "COMMANDS/commands.json" in str((sh.get("source") or {}).get("source")),
              f"source={(sh.get('source') or {}).get('source')}")
        check("H7", "CMD-0016 is never re-derived by the console",
              (sh.get("envelope") or {}).get("epistemic") in ("OBSERVED", "UNKNOWN"),
              f"envelope epistemic={(sh.get('envelope') or {}).get('epistemic')}")

        st, body = srv.get("/api/project?rel_path=PROJECTS/SHEMA", timeout=240)
        unm = json.loads(body)
        ush = unm.get("se_health") or {}
        check("H8", "unmanaged project gets no invented health",
              (ush.get("health") or {}).get("value") == "UNKNOWN",
              f"health={(ush.get('health') or {}).get('value')} reason={(ush.get('reason') or {}).get('value')}")

        st, body = srv.get("/api/system", timeout=300)
        sysd = json.loads(body)
        hc = sysd.get("health_command") or {}
        check("H9", "health_command separates declared from invocable",
              "declared" in hc and "invocable" in hc,
              f"declared={(hc.get('declared') or {}).get('value')} "
              f"invocable={(hc.get('invocable') or {}).get('value')}")
        check("H10", "CMD-0016 mutates=false is read from the contract",
              (hc.get("mutates") or {}).get("value") is False,
              f"mutates={(hc.get('mutates') or {}).get('value')}")
    finally:
        srv.stop()


def main() -> int:
    print("== SE-CONSOLE-002A degraded-engine regression ==")
    run_degraded()
    run_healthy()
    run_record_and_health_contract()
    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    print(f"\n== {passed}/{total} checks passed ==")
    # Phase C needs the canonical root. If it is unavailable, keep this run's
    # evidence local (gitignored) instead of overwriting the committed report.
    out_name = "degraded_report.json"
    if not os.path.exists(os.path.join(SE_ROOT_REAL, "SCRIPTS", "se.py")):
        out_name = "degraded_report.local.json"
        print(f"WARN: canonical root unavailable ({SE_ROOT_REAL}); writing {out_name}")
    out = os.path.join(CONSOLE_ROOT, "artifacts", "evidence", out_name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(
            {"harness": "tests/test_degraded.py", "checks": results,
             "summary": {"total": total, "passed": passed,
                         "failed": total - passed,
                         "status": "PASS" if passed == total else "FAIL"}},
            fh, ensure_ascii=False, indent=2)
    print(f"artifacts/evidence -> {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
