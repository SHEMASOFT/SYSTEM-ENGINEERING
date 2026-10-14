"""SE-CONSOLE :: stdlib HTTP server (no third-party dependency).

Why stdlib: the discovery recorded that Node is NOT installed, which rules out
the Next.js route handlers, and the brief requires the minimal professional
stack. `http.server` on top of the same Python that runs `se` gives a
zero-dependency, auditable surface.

Binds to 127.0.0.1 by default: a local-first console must not expose SE state
on the network.

GET-only remains the default. The single, named exception (DESIGN-5B §6) is
`POST /api/action`, which is dispatched only for `api.POST_ROUTES` and only
after `console/auth.py` has authorised the request; every other route answers
405 + Allow to any mutating verb.

Lifecycle (DESIGN-5C, option A): `--idle-timeout SECONDS` lets the console stop
itself once a client that WAS connected has gone quiet. The timeout is OFF by
default and stays DISARMED until the first request arrives, so a console started
by hand -- or one nobody has opened yet -- never vanishes on its own. The stop is
triggered by the ABSENCE of traffic rather than by an unload event, which is
exactly why it also covers a browser crash or a kill, where no `pagehide` handler
ever runs at all.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api, audit, se_cli, se_reader

BIND_HOST = os.environ.get("SE_CONSOLE_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("SE_CONSOLE_PORT", "8777"))

#: Methods accepted on EVERY route. POST is deliberately absent: it is
#: dispatched only for `api.POST_ROUTES`, so a generic 405 must never
#: advertise it where it would be refused (DESIGN-5B §6, layer 2).
ALLOWED_METHODS = ("GET", "HEAD", "OPTIONS")

#: Additional methods accepted on `api.POST_ROUTES` only.
POST_METHODS = ("POST",)

#: Cap on an action request body; the whole catalog payload is tiny.
MAX_ACTION_BODY = 64 * 1024

#: Seconds without a client before the console stops itself. 0 disables it.
#: Off by default: a console started by hand must not vanish on its own.
DEFAULT_IDLE_TIMEOUT = float(os.environ.get("SE_CONSOLE_IDLE_TIMEOUT", "0"))

#: How often the watcher checks. Cheap: it compares two numbers.
IDLE_POLL_SECONDS = 5.0


class IdleWatch:
    """Stop the console once a client that *was* here has gone away.

    DESIGN-5C option A. Two deliberate properties, both load-bearing:

    * **Disarmed until the first request.** A headless
      `python -m console.server` that nobody has opened keeps its previous
      behaviour forever: it cannot stop itself before a client ever arrived.
      Only after someone has connected does "nobody is here" start to mean
      anything.
    * **Any request is activity**, not only `/api/heartbeat`, so the console does
      not stop underneath an operator who is actually reading it.

    The state is two scalars in memory. It is not a store of SE data, so it does
    not contradict the console's "no database, no ledger, no cache" claim.
    """

    def __init__(self, timeout: float) -> None:
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._armed = False
        self._last = time.monotonic()

    def touch(self) -> None:
        """Record that a client is here, and arm the watch."""
        with self._lock:
            self._armed = True
            self._last = time.monotonic()

    def armed(self) -> bool:
        with self._lock:
            return self._armed

    def idle_for(self) -> float:
        with self._lock:
            return time.monotonic() - self._last if self._armed else 0.0

    def expired(self) -> bool:
        """True only when a client has been seen AND has since gone quiet."""
        if self.timeout <= 0:
            return False
        return self.armed() and self.idle_for() >= self.timeout


def start_idle_watch(httpd: ThreadingHTTPServer, watch: IdleWatch) -> None:
    """Shut the server down from a daemon thread once the watch expires.

    `shutdown()` must not be called from the thread running `serve_forever`, so
    it is called from this one and the main thread then returns from
    `serve_forever` normally -- the same clean path SIGINT takes.
    """
    if watch.timeout <= 0:
        return

    def _loop() -> None:
        while True:
            time.sleep(IDLE_POLL_SECONDS)
            if watch.expired():
                sys.stderr.write(
                    f"[se-console] no client for {watch.timeout:g}s "
                    f"(idle timeout); stopping\n"
                )
                httpd.shutdown()
                return

    threading.Thread(target=_loop, name="se-console-idle", daemon=True).start()


def _allow_for(path: str) -> list[str]:
    allow = list(ALLOWED_METHODS)
    if path in api.POST_ROUTES:
        allow.extend(m for m in POST_METHODS if m not in allow)
    return allow


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "se-console"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- helpers ---------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, *, head: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # A read-only console should never be cached as authoritative state.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if not head:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_json(self, status: int, payload: object, *, head: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", head=head)

    def _touch(self) -> None:
        """Tell the lifecycle watch that a client is still here (DESIGN-5C).

        Called for EVERY served request, not only for `/api/heartbeat`, so the
        console cannot stop underneath an operator who is reading it.
        """
        watch = getattr(self.server, "idle", None)
        if watch is not None:
            watch.touch()

    def _not_allowed(self, *, head: bool = False) -> None:
        path, _ = api.parse(self.path)
        allow = _allow_for(path)
        if path in api.POST_ROUTES:
            message = f"{path} accepts POST only"
        else:
            message = "SE-CONSOLE is read-only: only GET/HEAD/OPTIONS are accepted"
        body = json.dumps(
            {
                "status": "ERROR",
                "http_status": 405,
                "message": message,
                "allow": allow,
            },
            indent=2,
        ).encode("utf-8")
        self.send_response(405)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Allow", ", ".join(allow))
        self.end_headers()
        if not head:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(
            "[se-console] %s - %s\n" % (self.address_string(), fmt % args)
        )

    # -- verbs -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._handle(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle(head=True)

    def do_OPTIONS(self) -> None:  # noqa: N802
        path, _ = api.parse(self.path)
        self.send_response(204)
        self.send_header("Allow", ", ".join(_allow_for(path)))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        """POST is dispatched ONLY to `api.POST_ROUTES` (/api/action).

        Every other POST keeps the existing 405 + Allow behaviour, so the
        console stays GET-only-by-default with a single named exception.
        """
        path, _ = api.parse(self.path)
        if path not in api.POST_ROUTES:
            self._not_allowed()
            return
        self._handle_action(path)

    # Any other mutating verb is refused explicitly, not left to 501.
    do_PUT = do_PATCH = do_DELETE = _not_allowed  # noqa: N815

    # -- POST: the action surface ---------------------------------------
    def _handle_action(self, path: str) -> None:
        self._touch()
        length_raw = self.headers.get("Content-Length")
        try:
            length = int(length_raw) if length_raw is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            # Framing we cannot honour: refuse and close, so a body we did
            # not read cannot desynchronise the connection.
            self.close_connection = True
            self._send_json(
                400,
                {
                    "status": "ERROR",
                    "http_status": 400,
                    "message": "missing or invalid Content-Length",
                },
            )
            return
        if length > MAX_ACTION_BODY:
            self.close_connection = True
            self._send_json(
                413,
                {
                    "status": "ERROR",
                    "http_status": 413,
                    "message": f"action body too large (max {MAX_ACTION_BODY} bytes)",
                },
            )
            return
        body = self.rfile.read(length)
        port = self.server.server_address[1]
        try:
            status, payload = api.api_action(
                body=body,
                headers=self.headers,
                method="POST",
                path=path,
                port=port,
            )
        except Exception as exc:  # a crash must not masquerade as success
            status, payload = api._error(
                500, f"console error: {type(exc).__name__}: {exc}"
            )
        self._send_json(status, payload)

    # -- dispatch --------------------------------------------------------
    def _handle(self, *, head: bool) -> None:
        self._touch()
        path, query = api.parse(self.path)

        # POST-only surface: a GET here is 405 (with Allow: POST), not a 404
        # that would pretend the route does not exist.
        if path in api.POST_ROUTES:
            self._not_allowed(head=head)
            return

        if path in api.ROUTES:
            try:
                status, payload = api.ROUTES[path](query)
            except Exception as exc:  # a crash must not masquerade as health
                status, payload = api._error(
                    500, f"console error: {type(exc).__name__}: {exc}"
                )
            self._send_json(status, payload, head=head)
            return

        if path.startswith("/api/"):
            self._send_json(404, {"status": "ERROR", "message": f"no such route: {path}"})
            return

        full, ctype = api.resolve_static(path)
        if full is None:
            self._send_json(
                404,
                {
                    "status": "ERROR",
                    "http_status": 404,
                    "message": f"not found: {path}",
                    "hint": "console serves only the static frontend and /api/* routes",
                },
                head=head,
            )
            return
        try:
            with open(full, "rb") as fh:
                body = fh.read()
        except OSError as exc:
            self._send_json(500, {"status": "ERROR", "message": str(exc)}, head=head)
            return
        self._send(200, body, ctype, head=head)


def preflight() -> int:
    """Startup check.

    Two classes of problem, deliberately handled differently:

    * MISCONFIGURATION (wrong SE_ROOT, no SYSTEM.json) -> refuse to start.
      There is nothing to observe, so serving would be theatre.
    * ENGINE OUTAGE (`se` present but not executable) -> START ANYWAY, degraded.

    The second case matters. This console's purpose is to show the true state of
    SYSTEM-ENGINEERING, and an engine that cannot run is precisely the state an
    operator needs to see. POC-001's preflight conflated the two and, worse,
    printed "se reachable" while the probe had exited non-zero -- a false green
    in a function whose entire job is to not produce one.
    """
    problems = []
    if not os.path.isdir(se_reader.SE_ROOT):
        problems.append(f"SE root not found: {se_reader.SE_ROOT}")
    system_json = os.path.join(se_reader.SE_ROOT, "SYSTEM.json")
    if os.path.isdir(se_reader.SE_ROOT) and not os.path.isfile(system_json):
        problems.append(f"canonical SYSTEM.json not found: {system_json}")
    for p in problems:
        sys.stderr.write(f"[se-console][FATAL] {p}\n")
    if problems:
        return 2

    probe = se_cli.probe_se()
    if probe["operational"]:
        sys.stderr.write("[se-console] se engine: OPERATIONAL\n")
    else:
        sys.stderr.write(
            "[se-console][DEGRADED] se engine NOT operational: %s\n"
            "[se-console][DEGRADED]   %s\n"
            "[se-console][DEGRADED]   the console will serve UNKNOWN for every "
            "governance read rather than invent a value.\n"
            % (probe["reason"] or "unknown reason", probe["detail"] or "")
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m console.server",
        description="SE-CONSOLE :: read-only HTTP console over SYSTEM-ENGINEERING.",
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=DEFAULT_IDLE_TIMEOUT,
        metavar="SECONDS",
        help=(
            "stop the console after SECONDS with no request from any client "
            "(0 = never, the default). The timer stays DISARMED until the first "
            "request arrives, so a console nobody has opened never stops "
            "itself. Env: SE_CONSOLE_IDLE_TIMEOUT."
        ),
    )
    args = parser.parse_args(argv)

    rc = preflight()
    if rc != 0:
        return rc
    # Warm the shared audit once and keep it refreshed, so /api/system does not
    # re-run `se doctor` on every request (see console/audit.py).
    audit.start_background()
    httpd = ThreadingHTTPServer((BIND_HOST, BIND_PORT), ConsoleHandler)
    # The handler reaches the watch through the server instance it already has.
    httpd.idle = IdleWatch(args.idle_timeout)
    state = "OK" if se_cli.probe_se()["operational"] else "DEGRADED (se engine down)"
    if args.idle_timeout > 0:
        idle_note = f"idle timeout {args.idle_timeout:g}s once a client connects"
    else:
        idle_note = "no idle timeout"
    sys.stderr.write(
        f"[se-console] console on http://{BIND_HOST}:{BIND_PORT}  "
        f"(GET-only; POST /api/action is token-authenticated)  "
        f"(se_root={se_reader.SE_ROOT})  health={state}  ({idle_note})\n"
        f"[se-console] warming the shared audit pass (one `se doctor`, then "
        f"refreshed every {audit.DEFAULT_REFRESH_SECONDS}s)\n"
    )
    start_idle_watch(httpd, httpd.idle)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[se-console] stopped\n")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
