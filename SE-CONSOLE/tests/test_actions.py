"""SE-CONSOLE :: DESIGN-5B action-surface tests (hermetic).

Why this file exists
--------------------
5B turns the console from GET-only into an authenticated, allowlisted action
surface that DELEGATES to `se`. The security claims (token, Origin, Host, hard
validation before any subprocess) and the idempotency/concurrency claims are
exactly the kind of behaviour that must be demonstrated, not asserted in prose.

Pattern follows tests/test_degraded.py: SE_ROOT points at a temporary fixture
and the console runs on an ephemeral port, so nothing here touches the
canonical SYSTEM-ENGINEERING tree.

One deliberate difference from test_degraded: the fixture's SCRIPTS/se.py is a
thin wrapper around the REAL `se_core` from the sibling SYSTEM-ENGINEERING
checkout. `run checkpoint` / `run close` must genuinely apply (idempotency
replay, expected-revision refusal, mutation log) -- a fake `se` would only
test the console's imagination of the engine's behaviour.

The token is generated in a throwaway HOME, so the suite never writes to the
real `~/.config/se-console/token`; the production path is exercised by the
end-to-end demo instead.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
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


def _resolve_se_scripts() -> str:
    """Locate the real `se` engine's SCRIPTS directory.

    Two layouts are supported, and the console must be testable in whichever one
    it ships in:

    * vendored -- the console lives inside the SE repo (``<SE>/SE-CONSOLE``), so
      the engine is ``<console-parent>/SCRIPTS``;
    * sibling  -- the console is checked out next to ``SYSTEM-ENGINEERING``, so the
      engine is ``<console-parent>/SYSTEM-ENGINEERING/SCRIPTS``.

    ``SE_ENGINE_SCRIPTS`` overrides both. Hardcoding only the sibling layout made
    this file un-runnable in the layout the console actually ships in.
    """
    override = os.environ.get("SE_ENGINE_SCRIPTS")
    if override:
        return override
    parent = os.path.dirname(CONSOLE_ROOT)
    candidates = [
        os.path.join(parent, "SCRIPTS"),
        os.path.join(parent, "SYSTEM-ENGINEERING", "SCRIPTS"),
    ]
    for candidate in candidates:
        if os.path.isdir(os.path.join(candidate, "se_core")):
            return candidate
    return candidates[0]


SE_ENGINE_SCRIPTS = _resolve_se_scripts()

#: ``Path.home()`` reads HOME on POSIX and USERPROFILE on Windows. The suite fakes
#: the home directory so the operator token is never written to the real one, so it
#: must override whichever variable the running platform actually honours.
HOME_VARS = ("HOME", "USERPROFILE")


@contextlib.contextmanager
def fake_home(path: str):
    """Point the home directory at ``path`` for the duration of the block."""
    saved = {name: os.environ.get(name) for name in HOME_VARS}
    for name in HOME_VARS:
        os.environ[name] = path
    try:
        yield
    finally:
        for name, previous in saved.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


def _home_env(path: str) -> dict:
    """``os.environ`` with every home variable pointing at ``path``."""
    return {**os.environ, **{name: path for name in HOME_VARS}}


ACTIONS_LOG = os.path.join(CONSOLE_ROOT, "artifacts", "actions.jsonl")

PROJECT_REL = "PROJECTS/TESTPROJ"
RUN_ID = "RUN-0001"
TOKEN_HEADER = "X-SE-Console-Token"

sys.path.insert(0, CONSOLE_ROOT)

from console import auth, read_model, se_cli  # noqa: E402

# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------

BASELINE_RUN = {
    "schema_version": "1",
    "run_id": RUN_ID,
    "project_id": "PRJ-TEST",
    "state": "RUNNING",
    "created_at": "2026-10-07T10:00:00+00:00",
    "updated_at": "2026-10-07T10:00:00+00:00",
    "checkpoint": {
        "state": "RUNNING",
        "next_step": "baseline",
        "at": "2026-10-07T10:00:00+00:00",
    },
    "recovery": {},
}

#: The fixture `se`: real engine, fixture root. Mirrors how SE itself boots
#: (SCRIPTS/se.py inserts SCRIPTS on sys.path and delegates to se_core.cli).
SE_WRAPPER = (
    "import sys\n"
    "sys.path.insert(0, {scripts!r})\n"
    "from se_core.cli import main\n"
    "if __name__ == '__main__':\n"
    "    sys.exit(main())\n"
).format(scripts=SE_ENGINE_SCRIPTS)


def _write_json(path: str, data: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # newline="\n": byte-level assertions compare the file against
    # json.dumps(...).encode("utf-8"). Text mode translates "\n" to os.linesep, so
    # on Windows the same JSON would produce different bytes and fail the compare.
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2)


def make_fixture(root: str) -> None:
    os.makedirs(os.path.join(root, "SCRIPTS"), exist_ok=True)
    # The console validates PROJECT.json against SE's OWN schema, resolved
    # relative to SE_ROOT. Without SCHEMAS/ in the fixture every project would
    # read as INVALID rather than MANAGED -- which is not what we are testing.
    schemas_src = os.path.join(os.path.dirname(SE_ENGINE_SCRIPTS), "SCHEMAS")
    if os.path.isdir(schemas_src):
        shutil.copytree(schemas_src, os.path.join(root, "SCHEMAS"))
    _write_json(os.path.join(root, "SYSTEM.json"), {"name": "fixture", "status": "ACTIVE"})
    with open(os.path.join(root, "VERSION"), "w", encoding="utf-8") as fh:
        fh.write("0.0.0-fixture\n")
    _write_json(
        os.path.join(root, PROJECT_REL, "PROJECT.json"),
        {
            # Must satisfy SCHEMAS/project/project.schema.json, or the console
            # classifies the project INVALID instead of MANAGED.
            "schema_version": "1",
            "project_id": "PRJ-TEST",
            "name": "TESTPROJ",
            "description": "Action-surface fixture.",
            "owner": "tester",
            "domains": ["software"],
            "criticality": "unknown",
            "lifecycle_state": "ACTIVE",
            "blocked": False,
            "version": "0.1.0",
            "created_at": "2026-10-07T10:00:00Z",
            "updated_at": "2026-10-07T10:00:00Z",
            "master_system_version": "0.10.0",
        },
    )
    _write_json(os.path.join(root, PROJECT_REL, "runs", f"{RUN_ID}.json"), BASELINE_RUN)
    with open(os.path.join(root, "SCRIPTS", "se.py"), "w", encoding="utf-8") as fh:
        fh.write(SE_WRAPPER)


def free_port(preferred: int) -> int:
    for p in range(preferred, preferred + 200):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("no free port")


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# Module-level handles, filled by setUpModule.
TMP = ""
ROOT = ""
TOKEN = ""
PORT = 0
PROC: subprocess.Popen | None = None
SERVER_LOG = ""


def setUpModule() -> None:  # noqa: N802
    global TMP, ROOT, TOKEN, PORT, PROC
    if not os.path.isdir(SE_ENGINE_SCRIPTS):
        raise RuntimeError(
            "sibling SYSTEM-ENGINEERING checkout not found at "
            f"{SE_ENGINE_SCRIPTS}; the action tests need the real se engine"
        )
    TMP = tempfile.mkdtemp(prefix="se-console-actions-")
    ROOT = os.path.join(TMP, "SE")
    make_fixture(ROOT)

    # Generate the token in a throwaway home: production writes to
    # <home>/.config/se-console/token, but a test suite must not create files in
    # the operator's real home directory.
    fake_home_dir = os.path.join(TMP, "home")
    with fake_home(fake_home_dir):
        TOKEN = auth.load_token()
    if not TOKEN:
        raise RuntimeError("auth.load_token() produced no token")

    PORT = free_port(9050)
    env = dict(_home_env(fake_home_dir), SE_ROOT=ROOT, SE_CONSOLE_PORT=str(PORT))
    PROC = subprocess.Popen(
        [sys.executable, "-m", "console.server"],
        cwd=CONSOLE_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if not _wait_for_health():
        log = _stop_server()
        raise RuntimeError(f"console never came up; log:\n{log}")


def tearDownModule() -> None:  # noqa: N802
    _stop_server()
    shutil.rmtree(TMP, ignore_errors=True)


def _stop_server() -> str:
    global PROC
    if PROC is None:
        return ""
    PROC.terminate()
    try:
        out = PROC.communicate(timeout=15)[0] or ""
    except Exception:
        PROC.kill()
        out = ""
    PROC = None
    return out


def _wait_for_health(tries: int = 120) -> bool:
    for _ in range(tries):
        if PROC is not None and PROC.poll() is not None:
            return False
        try:
            status, _ = _get("/api/health", timeout=5)
        except Exception:
            status = None
        if status == 200:
            return True
        time.sleep(0.5)
    return False


def _get(path: str, timeout: int = 60):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}{path}", timeout=timeout
        ) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


class ConsoleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # Canonical fixture state is reset before every test, so the suite is
        # order-independent: an applying test can never mask a refusing one.
        _write_json(os.path.join(ROOT, PROJECT_REL, "runs", f"{RUN_ID}.json"), BASELINE_RUN)
        for name in ("mutation-log.jsonl",):
            path = os.path.join(ROOT, PROJECT_REL, name)
            if os.path.exists(path):
                os.remove(path)

    # -- raw IO ---------------------------------------------------------
    def post(
        self,
        payload=None,
        *,
        token: str | None = None,
        origin: str | None = None,
        host: str | None = None,
        raw: bytes | None = None,
        path: str = "/api/action",
    ):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers[TOKEN_HEADER] = token
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=120)
        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            text = resp.read().decode("utf-8", "replace")
            status = resp.status
            allow = resp.getheader("Allow")
        finally:
            conn.close()
        return status, (json.loads(text) if text else None), allow

    def run_path(self) -> str:
        return os.path.join(ROOT, PROJECT_REL, "runs", f"{RUN_ID}.json")

    def run_bytes(self) -> bytes:
        with open(self.run_path(), "rb") as fh:
            return fh.read()

    def run_data(self) -> dict:
        return json.loads(self.run_bytes().decode("utf-8"))

    def mutation_entries(self) -> list[dict]:
        path = os.path.join(ROOT, PROJECT_REL, "mutation-log.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def audit_entries(self) -> list[dict]:
        if not os.path.exists(ACTIONS_LOG):
            return []
        out = []
        with open(ACTIONS_LOG, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    # -- payloads -------------------------------------------------------
    def checkpoint_payload(self, **over) -> dict:
        body = {
            "action": "run.checkpoint",
            "project": PROJECT_REL,
            "run": RUN_ID,
            "params": {"next_step": "drive the action surface", "pending": "TASK-2"},
            "idempotency_key": "test-key-checkpoint-0001",
        }
        body.update(over)
        return body

    def close_payload(self, **over) -> dict:
        body = {
            "action": "run.close",
            "project": PROJECT_REL,
            "run": RUN_ID,
            "params": {
                "state": "COMPLETED",
                "summary": "closed by the action-surface test",
                "by": "tester",
            },
            "idempotency_key": "test-key-close-0001",
        }
        body.update(over)
        return body

    def attest_payload(self, **over) -> dict:
        body = {
            "action": "transition.attest",
            "project": PROJECT_REL,
            "params": {
                "to": "NEXT_STATE",
                "attest": "confirmed",
                "conditions": ["C1", "C2"],
                "by": "tester",
            },
            "idempotency_key": "test-key-attest-0001",
        }
        body.update(over)
        return body

    def assert_se_not_invoked(self) -> None:
        """A refused request must leave every observable SE trace untouched."""
        self.assertEqual(self.run_bytes(), json.dumps(BASELINE_RUN, indent=2).encode("utf-8"))
        self.assertEqual(self.mutation_entries(), [])


# --------------------------------------------------------------------------
# The second gate: the argv every action is delegated with
# --------------------------------------------------------------------------


class AllowlistTests(unittest.TestCase):
    """`_action_allows` decides which argv shapes may be delegated to `se`.

    It reads the shape from the entry itself, so every entry declares its own
    prefix length and which flags may repeat. Nothing here starts a server:
    this is the pure function that used to refuse `transition.attest` outright,
    because its prefix is one token and the comparison window was two.
    """

    def attest_argv(self, conditions=("C1", "C2")) -> list[str]:
        args = [
            "transition",
            "--project", PROJECT_REL,
            "--to", "NEXT_STATE",
            "--attest", "confirmed",
        ]
        for condition in conditions:
            args += ["--condition", condition]
        return args

    def test_attest_argv_is_allowed_through(self):
        self.assertEqual(se_cli._action_allows(self.attest_argv()), "transition.attest")

    def test_every_repeatable_flag_may_repeat(self):
        """`--condition` is declared repeatable, so several must be allowed."""
        self.assertEqual(
            se_cli._action_allows(self.attest_argv(conditions=("C1", "C2", "C3"))),
            "transition.attest",
        )

    def test_a_flag_that_is_not_repeatable_may_not_repeat(self):
        argv = self.attest_argv()
        argv += ["--to", "ANOTHER_STATE"]  # --to is single-valued
        self.assertIsNone(se_cli._action_allows(argv))

    def test_a_required_flag_must_be_present(self):
        self.assertIsNone(se_cli._action_allows(self.attest_argv(conditions=())))

    def test_an_unknown_flag_is_refused(self):
        argv = self.attest_argv() + ["--evil", "value"]
        self.assertIsNone(se_cli._action_allows(argv))

    def test_a_flag_shaped_value_is_refused(self):
        argv = self.attest_argv(conditions=("C1",))
        argv[argv.index("--attest") + 1] = "--to"
        self.assertIsNone(se_cli._action_allows(argv))

    def test_a_truncated_argv_is_refused(self):
        self.assertIsNone(se_cli._action_allows(["transition", "--project"]))

    def test_the_two_token_prefixes_still_work(self):
        self.assertEqual(
            se_cli._action_allows(
                ["run", "checkpoint", "--project", PROJECT_REL, "--run", RUN_ID]
            ),
            "run.checkpoint",
        )
        self.assertEqual(
            se_cli._action_allows(
                [
                    "run", "close", "--project", PROJECT_REL, "--run", RUN_ID,
                    "--state", "COMPLETED",
                ]
            ),
            "run.close",
        )

    def test_read_only_verbs_are_not_actions(self):
        """A read-only verb must fall through, not be mistaken for a write."""
        self.assertIsNone(se_cli._action_allows(["health", "--project", PROJECT_REL]))
        self.assertIsNone(se_cli._action_allows(["doctor"]))
        self.assertIsNone(se_cli._action_allows(["review", "--project", PROJECT_REL]))


# --------------------------------------------------------------------------
# A2/5B security: authentication, Origin, Host
# --------------------------------------------------------------------------


class AuthTests(ConsoleTestCase):
    def setUp(self):
        super().setUp()
        # `guard()` reads the token through auth.load_token(), which resolves the
        # home directory. Point it at the throwaway home for the duration of the
        # test, otherwise the direct guard tests would CREATE a fresh token in the
        # operator's real home -- exactly what this suite promises not to do.
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(fake_home(os.path.join(TMP, "home")))

    def test_token_file_is_created_0600_outside_the_repo(self):
        # The token is generated under the throwaway HOME by setUpModule, so the
        # assertion must look THERE: `auth.token_path()` resolves the operator's
        # REAL home, which this suite deliberately never writes to.
        self.assertTrue(
            auth.token_path().as_posix().endswith(".config/se-console/token"),
            auth.token_path(),
        )
        path = os.path.join(TMP, "home", ".config", "se-console", "token")
        self.assertFalse(path.startswith(CONSOLE_ROOT))
        self.assertTrue(os.path.isfile(path), path)
        if os.name != "nt":
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600, f"token file mode is {oct(mode)}, expected 0o600")
        # On Windows os.open(..., 0o600) does not apply POSIX mode bits: the token
        # inherits the profile ACL and st_mode reports 0o666. Declared gap, not a
        # hidden one -- ACL hardening is a separate follow-up. The part this test
        # can prove on every platform (outside the repository) is asserted above.
        self.assertEqual(len(TOKEN), 43)  # token_urlsafe(32) -> 43 chars

    def test_post_without_token_is_refused_and_se_not_invoked(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(self.checkpoint_payload())
        self.assertEqual(status, 401, body)
        self.assertEqual(body["status"], "ERROR")
        self.assertEqual(len(self.audit_entries()), before, "refused request was audited")
        self.assert_se_not_invoked()

    def test_post_with_wrong_token_is_refused(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(self.checkpoint_payload(), token="not-the-token")
        self.assertEqual(status, 401, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_cross_site_origin_is_refused_403(self):
        status, body, _ = self.post(
            self.checkpoint_payload(),
            token=TOKEN,
            origin="http://evil.example",
        )
        self.assertEqual(status, 403, body)
        self.assert_se_not_invoked()

    def test_same_origin_variants_are_accepted_by_the_guard(self):
        # Proves the 403 above is Origin VALIDATION, not a blanket refusal.
        for origin in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            reason = auth.guard(
                {TOKEN_HEADER: TOKEN, "Origin": origin, "Host": f"127.0.0.1:{PORT}"},
                method="POST",
                path="/api/action",
                port=PORT,
            )
            self.assertIsNone(reason, f"{origin} refused: {reason}")

    def test_absent_origin_is_allowed(self):
        reason = auth.guard(
            {TOKEN_HEADER: TOKEN, "Host": f"127.0.0.1:{PORT}"},
            method="POST",
            path="/api/action",
            port=PORT,
        )
        self.assertIsNone(reason, reason)

    def test_rebound_host_is_refused_403(self):
        status, body, _ = self.post(
            self.checkpoint_payload(),
            token=TOKEN,
            host="attacker.example:8777",
        )
        self.assertEqual(status, 403, body)
        self.assert_se_not_invoked()

    def test_wrong_port_host_is_refused_403(self):
        status, body, _ = self.post(
            self.checkpoint_payload(),
            token=TOKEN,
            host=f"127.0.0.1:{PORT + 1}",
        )
        self.assertEqual(status, 403, body)
        self.assert_se_not_invoked()

    @unittest.skipIf(
        os.name == "nt",
        "chmod 000 does not make a file unreadable on Windows and os.geteuid "
        "does not exist there; the premise needs POSIX permissions",
    )
    def test_unreadable_token_file_fails_closed(self):
        # Fail-closed is the load-bearing property: an error must never be an
        # "allow".
        with fake_home(os.path.join(TMP, "no-such-home")):
            path = auth.token_path()
            os.makedirs(path.parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(TOKEN)
            os.chmod(path, 0o000)
            try:
                reason = auth.guard(
                    {TOKEN_HEADER: TOKEN}, method="POST", path="/api/action", port=PORT
                )
                if os.geteuid() == 0:
                    self.skipTest("running as root: chmod 000 does not block reads")
                self.assertIsNotNone(reason, "unreadable token file must refuse")
            finally:
                os.chmod(path, 0o600)

    def test_missing_token_file_on_unwritable_home_fails_closed(self):
        with fake_home(os.path.join(TMP, "not-a-dir")):
            with open(os.environ["HOME"], "w", encoding="utf-8") as fh:
                fh.write("a file, not a directory")
            reason = auth.guard(
                {TOKEN_HEADER: TOKEN}, method="POST", path="/api/action", port=PORT
            )
            self.assertIsNotNone(reason, "a token path that cannot be created must refuse")
            self.assertNotEqual(reason, "")


# --------------------------------------------------------------------------
# Hard validation before any subprocess
# --------------------------------------------------------------------------


class ValidationTests(ConsoleTestCase):
    def test_malformed_json_body_is_400(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(None, token=TOKEN, raw=b"{not json")
        self.assertEqual(status, 400, body)
        self.assertEqual(body["status"], "ERROR")
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_action_outside_the_catalog_is_refused(self):
        before = len(self.audit_entries())
        for action in ("run.start", "run.transition", "update.record", "se.wipe"):
            with self.subTest(action=action):
                payload = self.checkpoint_payload(action=action)
                status, body, _ = self.post(payload, token=TOKEN)
                self.assertEqual(status, 400, body)
                self.assertIn("catalog", body["message"])
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_project_path_with_dotdot_is_refused(self):
        for bad in ("PROJECTS/../etc", "PROJECTS/TESTPROJ/../../evil", "../PROJECTS/X"):
            with self.subTest(project=bad):
                status, body, _ = self.post(
                    self.checkpoint_payload(project=bad), token=TOKEN
                )
                self.assertEqual(status, 400, body)
        self.assert_se_not_invoked()

    def test_invalid_run_id_is_refused(self):
        for bad in ("RUN-1", "RUN-0001-EXTRA", "TASK-0001", ""):
            with self.subTest(run=bad):
                status, body, _ = self.post(
                    self.checkpoint_payload(run=bad), token=TOKEN
                )
                self.assertEqual(status, 400, body)
        self.assert_se_not_invoked()

    def test_close_with_invalid_state_is_refused(self):
        status, body, _ = self.post(
            self.close_payload(params={"state": "PENDING"}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assert_se_not_invoked()

    def test_close_without_state_is_refused(self):
        status, body, _ = self.post(
            self.close_payload(params={"summary": "no state"}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assert_se_not_invoked()

    def test_unknown_param_is_refused(self):
        status, body, _ = self.post(
            self.checkpoint_payload(params={"next_step": "x", "evil": "y"}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assert_se_not_invoked()

    def test_param_value_that_looks_like_a_flag_is_refused(self):
        status, body, _ = self.post(
            self.checkpoint_payload(params={"next_step": "--json"}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assert_se_not_invoked()

    # --- transition.attest validation --------------------------------------
    def test_attest_missing_to_is_refused(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(
            self.attest_payload(params={"attest": "confirmed", "conditions": ["C1"]}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_attest_missing_attest_is_refused(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(
            self.attest_payload(params={"to": "NEXT", "conditions": ["C1"]}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_attest_missing_conditions_is_refused(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(
            self.attest_payload(params={"to": "NEXT", "attest": "confirmed"}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_attest_empty_conditions_is_refused(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(
            self.attest_payload(params={"to": "NEXT", "attest": "confirmed", "conditions": []}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_attest_conditions_must_be_list(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(
            self.attest_payload(params={"to": "NEXT", "attest": "confirmed", "conditions": "C1"}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_attest_condition_value_looks_like_flag_is_refused(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(
            self.attest_payload(params={"to": "NEXT", "attest": "confirmed", "conditions": ["--condition"]}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()

    def test_attest_unknown_param_is_refused(self):
        before = len(self.audit_entries())
        status, body, _ = self.post(
            self.attest_payload(params={"to": "NEXT", "attest": "confirmed", "conditions": ["C1"], "evil": "y"}), token=TOKEN
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(len(self.audit_entries()), before)
        self.assert_se_not_invoked()


# --------------------------------------------------------------------------
# Delegation: se really applies, and the console really audits
# --------------------------------------------------------------------------


class DelegationTests(ConsoleTestCase):
    def test_checkpoint_applies_and_writes_an_audit_line(self):
        before = len(self.audit_entries())
        payload = self.checkpoint_payload(
            expected_revision=sha256_file(self.run_path())
        )
        status, body, _ = self.post(payload, token=TOKEN)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "PASS", body)
        self.assertEqual(body["action"], "run.checkpoint")
        self.assertEqual(body["idempotency_key"], payload["idempotency_key"])

        # se applied it: the canonical file changed.
        data = self.run_data()
        self.assertEqual(data["checkpoint"]["next_step"], "drive the action surface")
        self.assertEqual(data["checkpoint"]["pending"], ["TASK-2"])
        entries = self.mutation_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "run.checkpoint")
        self.assertEqual(entries[0]["key"], payload["idempotency_key"])

        # the console recorded the delegation.
        audit = self.audit_entries()
        self.assertEqual(len(audit), before + 1, "expected exactly one new audit line")
        line = audit[-1]
        self.assertEqual(line["action"], "run.checkpoint")
        self.assertEqual(line["project"], PROJECT_REL)
        self.assertEqual(line["run"], RUN_ID)
        self.assertEqual(line["idempotency_key"], payload["idempotency_key"])
        self.assertEqual(line["expected_revision"], payload["expected_revision"])
        self.assertEqual(line["exit_code"], 0)
        self.assertEqual(line["argv"][:3], ["se", "run", "checkpoint"])
        self.assertTrue(line["actor"])
        self.assertTrue(line["at"])

    def test_attest_is_delegated_and_audited(self):
        """A well-formed attest must reach the engine, not the read-only gate.

        The argv gate is what stands between a valid request and `se`. Two of
        its assumptions used to fail for `transition.attest`: the prefix window
        was fixed at two tokens while this action's prefix is one, and the
        flags an entry declares as `repeatable` were refused on their second
        occurrence. Either way the request never left the console, so nothing
        was audited and the client only saw a refusal.
        """
        before = len(self.audit_entries())
        status, body, _ = self.post(self.attest_payload(), token=TOKEN)
        self.assertEqual(status, 200, body)
        self.assertNotIn(
            "refused: 'transition'", json.dumps(body), "argv gate refused a valid attest"
        )
        # The verdict is the engine's, relayed verbatim: not a console refusal.
        # (The fixture's lifecycle does not satisfy every gate, so the engine's
        # own answer is a FAIL -- what matters here is that it answered.)
        self.assertIn(body["status"], ("PASS", "FAIL"), body)
        self.assertIn("exit_code", body["result"], body)

        # The console recorded the delegation, so `se` really ran.
        audit = self.audit_entries()
        self.assertEqual(len(audit), before + 1, "expected exactly one new audit line")
        line = audit[-1]
        self.assertEqual(line["action"], "transition.attest")
        self.assertEqual(line["project"], PROJECT_REL)
        self.assertEqual(line["argv"][:2], ["se", "transition"])

    def test_replay_of_the_same_idempotency_key_has_no_duplicate_effect(self):
        payload = self.checkpoint_payload(
            expected_revision=sha256_file(self.run_path())
        )
        first_status, first, _ = self.post(payload, token=TOKEN)
        self.assertEqual(first_status, 200, first)
        self.assertEqual(first["status"], "PASS")
        after_first = self.run_bytes()

        second_status, second, _ = self.post(payload, token=TOKEN)
        self.assertEqual(second_status, 200, second)
        self.assertEqual(second["status"], "PASS", second)
        self.assertIn("replayed", json.dumps(second.get("result", {})))

        # no duplicate effect: the run file is byte-identical and the engine's
        # own mutation log still carries the key exactly once.
        self.assertEqual(self.run_bytes(), after_first)
        keyed = [e for e in self.mutation_entries() if e.get("key") == payload["idempotency_key"]]
        self.assertEqual(len(keyed), 1, f"key replayed into the log: {keyed}")

    def test_wrong_expected_revision_is_refused_and_the_file_is_unchanged(self):
        before_bytes = self.run_bytes()
        payload = self.checkpoint_payload(expected_revision="0" * 64)
        status, body, _ = self.post(payload, token=TOKEN)
        # se refuses before writing; the console relays the refusal verbatim.
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "FAIL", body)
        self.assertEqual(body["result"]["exit_code"], 1)
        self.assertIn("NO WRITE", body["result"]["output"])
        self.assertEqual(self.run_bytes(), before_bytes, "run file was modified")
        self.assertEqual(self.mutation_entries(), [])

    def test_run_close_applies_the_final_state(self):
        payload = self.close_payload(expected_revision=sha256_file(self.run_path()))
        status, body, _ = self.post(payload, token=TOKEN)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "PASS", body)
        self.assertEqual(body["action"], "run.close")
        data = self.run_data()
        self.assertEqual(data["state"], "COMPLETED")
        self.assertEqual(data["recovery"]["notes"], "closed by the action-surface test")
        entries = self.mutation_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "run.close")

    def test_engine_side_failure_is_relayed_not_hidden(self):
        # Well-formed request, but the run does not exist: se fails and the
        # console must NOT pretend the action succeeded.
        payload = self.checkpoint_payload(run="RUN-9999")
        status, body, _ = self.post(payload, token=TOKEN)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "FAIL", body)
        self.assertEqual(body["result"]["exit_code"], 1)


# --------------------------------------------------------------------------
# Surface shape: POST only on /api/action, GET routes untouched
# --------------------------------------------------------------------------


class SurfaceShapeTests(ConsoleTestCase):
    def test_get_to_action_route_is_405(self):
        status, body = _get("/api/action")
        self.assertEqual(status, 405, body[:300])
        self.assertIn("POST", body)

    def test_post_to_another_api_route_is_still_405(self):
        status, body, allow = self.post({}, path="/api/record")
        self.assertEqual(status, 405, body)
        self.assertEqual(allow, "GET, HEAD, OPTIONS")

    def test_put_on_action_route_is_still_405(self):
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        try:
            conn.request("PUT", "/api/action", body=b"{}")
            resp = conn.getresponse()
            status = resp.status
            allow = resp.getheader("Allow")
            resp.read()
        finally:
            conn.close()
        self.assertEqual(status, 405)
        self.assertIn("POST", allow or "")

    def test_existing_get_routes_still_answer(self):
        status, body = _get("/api/health")
        self.assertEqual(status, 200, body[:300])
        health = json.loads(body)
        self.assertEqual(health["status"], "OK")
        self.assertTrue(health["se_available"])

        status, body = _get("/api/projects", timeout=180)
        self.assertEqual(status, 200, body[:300])
        listing = json.loads(body)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["managed"], 1)

        status, body = _get("/api/provenance")
        self.assertEqual(status, 200, body[:300])
        self.assertIn("fingerprint", json.loads(body))

        status, body = _get("/api/record?rel_path=../../etc&type=OBJECTIVE&id=X")
        self.assertEqual(status, 400, body[:300])

        status, body = _get("/api/nope")
        self.assertEqual(status, 404, body[:300])

    def test_health_route_emits_no_cors_headers(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=60) as r:
            headers = {k.lower() for k in r.headers}
        self.assertNotIn("access-control-allow-origin", headers)


# --------------------------------------------------------------------------
# A3: intervention point -> enabled actions (DESIGN-5B §2.2)
# --------------------------------------------------------------------------


class AttentionMappingTests(unittest.TestCase):
    @staticmethod
    def attention(**overrides) -> dict:
        args = dict(
            gates=[
                {
                    "id": "G1",
                    "name": "Build",
                    "failing": [{"id": "C1"}],
                    "manual": [{"id": "C2"}],
                }
            ],
            review={"gaps": ["a gap"], "link_notes": [], "findings": []},
            records={
                "RUN": {
                    "records": [
                        {
                            "id": "RUN-0001",
                            "data": {
                                "state": "BLOCKED",
                                "checkpoint": {"blocked": ["TASK-1"]},
                                "recovery": {},
                            },
                        },
                        {
                            "id": "RUN-0002",
                            "data": {
                                "state": "FAILED",
                                "checkpoint": {},
                                "recovery": {"notes": "boom"},
                            },
                        },
                        {
                            "id": "RUN-0003",
                            "data": {
                                "state": "RUNNING",
                                "checkpoint": {},
                                "recovery": {"handoff": "to ops"},
                            },
                        },
                        {
                            "id": "RUN-0004",
                            "data": {
                                "state": "RUNNING",
                                "checkpoint": {"next_step": "fine"},
                                "recovery": {},
                            },
                        },
                    ],
                    "invalid": [],
                }
            },
            discovery={"present": False},
            deep_env={"warnings": []},
            manifest_v={"ok": True, "errors": []},
        )
        args.update(overrides)
        return read_model.build_attention(**args)

    def items_for(self, needle: str) -> list[dict]:
        return [i for i in self.attention()["items"] if needle in json.dumps(i)]

    def test_blocked_run_offers_checkpoint_and_close(self):
        items = [i for i in self.items_for("RUN-0001") if "blocked" in i["title"]]
        self.assertTrue(items, "blocked RUN produced no attention item")
        self.assertEqual(items[0]["actions"], ["run.checkpoint", "run.close"])

    def test_failed_run_offers_checkpoint_and_close(self):
        items = self.items_for("RUN-0002 failed")
        self.assertTrue(items)
        self.assertEqual(items[0]["actions"], ["run.checkpoint", "run.close"])

    def test_pending_handoff_offers_checkpoint_only(self):
        items = self.items_for("RUN-0003 handoff")
        self.assertTrue(items)
        self.assertEqual(items[0]["actions"], ["run.checkpoint"])

    def test_intervention_free_run_is_not_an_attention_item(self):
        self.assertEqual(self.items_for("RUN-0004"), [])

    def test_non_actionable_items_carry_an_empty_action_list(self):
        attention = self.attention()
        for item in attention["items"]:
            if item["area"] == "run":
                # RUN items ARE actionable (DESIGN-5B §2.2); they are covered by
                # the tests above. This test is about everything else.
                continue
            if item["area"] == "gate" and item["actions"]:
                # Gate items with MANUAL conditions are actionable (DESIGN-5B §2.2);
                # they offer transition.attest actions.
                continue
            with self.subTest(title=item["title"]):
                self.assertEqual(item["actions"], [])
        # sanity: the fixture really produced gate/integrity/discovery items
        areas = {i["area"] for i in attention["items"]}
        self.assertTrue({"gate", "integrity", "discovery"} <= areas, areas)

    def test_every_attention_item_exposes_an_actions_key(self):
        # Consistency contract: callers must never hit a KeyError on items
        # produced by any branch of build_attention.
        for item in self.attention()["items"]:
            self.assertIn("actions", item)
            self.assertIsInstance(item["actions"], list)
            for action_id in item["actions"]:
                self.assertIn(action_id, ("run.checkpoint", "run.close", "transition.attest"))




class ActionSurfaceUITests(unittest.TestCase):
    """The SHIPPED assets must wire the action surface.

    Honest scope: these assert on the served assets, not on browser behaviour.
    No browser is available in this environment, so this proves the wiring
    shipped -- it does NOT prove the buttons work against a real DOM. The
    behaviour is covered end-to-end by the HTTP tests above.
    """

    def _asset(self, path: str) -> str:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=60) as r:
            return r.read().decode("utf-8", "replace")

    def test_served_js_wires_the_action_surface(self):
        js = self._asset("/assets/console.js")
        self.assertIn("/api/action", js)
        self.assertIn("X-SE-Console-Token", js)
        self.assertIn("sessionStorage", js)
        # the token must never be persisted beyond the session
        self.assertNotIn('localStorage.setItem("se-console-token"', js)
        # the copy claiming the console cannot act must be gone
        self.assertNotIn("No hay accion de edicion", js)

    def test_served_homepage_exposes_the_token_input(self):
        html = self._asset("/")
        self.assertIn('id="inp-token"', html)
        self.assertIn('type="password"', html)
        self.assertIn("/assets/console.js", html)

    def test_run_id_is_matched_by_shape_not_by_the_wrong_word(self):
        # Regression guard: the first cut matched the literal word RUN in
        # "RUN RUN-0001 blocked" and produced run="RUN", which the engine
        # rejects. The asset must match the id shape instead.
        js = self._asset("/assets/console.js")
        self.assertIn("/RUN-\\d+/", js)
        self.assertNotIn("item.title.match(/RUN (", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
