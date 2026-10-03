"""Loopback-only browser UI; the existing detached worker owns display recovery."""

import argparse
import hmac
import json
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

from . import __version__
from .desktop import collect_doctor
from .diagnose import diagnose
from .troubleshoot import (Attempt, CONNECTION_PATHS, SYMPTOMS, Session, candidates,
                           describe, insufficient, next_step, target_connector)


class Conflict(ValueError):
    """A stale browser action must never confirm another step or trial."""


class Application:
    def __init__(self, reader=None, *, demo=False):
        self.reader = reader or (demo_snapshot if demo else collect_doctor)
        self.demo = demo
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.session = Session()
        self.phase = "home"
        self.revision = 0
        self.step = None
        self.plans = []
        self.notice = ""
        self.result = None
        self.confirmation = None
        self.decision = None
        self.cancelled = False
        self.last_seen = time.monotonic()
        self.worker = None

    def changed(self):
        self.revision += 1

    def report(self):
        snapshot = self.session.snapshot
        if snapshot is None:
            return None
        findings = diagnose(snapshot)
        uncertain = any(c.status == "unknown" or (c.current_mode and c.current_mode.state == "unknown")
                        for c in snapshot.connectors)
        code = 2 if snapshot.errors or uncertain else (1 if any(f.severity == "warning" for f in findings) else 0)
        return {"schema_version": 1, "beamfix_version": __version__, "mode": "read_only",
                "visual_confirmation": "not_performed", "snapshot": asdict(snapshot),
                "findings": [asdict(f) for f in findings], "exit_code": code}

    def state(self, *, heartbeat=True):
        with self.lock:
            if heartbeat:
                self.last_seen = time.monotonic()
                self.condition.notify_all()
            confirmation = None
            if self.confirmation:
                confirmation = {**self.confirmation,
                                "seconds": max(0, self.confirmation["deadline"] - time.monotonic())}
                del confirmation["deadline"]
            return {"version": __version__, "demo": self.demo, "revision": self.revision,
                    "phase": self.phase, "report": self.report(),
                    "symptoms": SYMPTOMS, "connections": CONNECTION_PATHS,
                    "session": asdict(self.session), "step": asdict(self.step) if self.step else None,
                    "outputs": [{"name": c.name, "description": describe(self.session.snapshot, c.name)}
                                for c in candidates(self.session.snapshot)] if self.session.snapshot else [],
                    "preview": [p.description for p in self.plans], "notice": self.notice,
                    "result": asdict(self.result) if self.result else None,
                    "confirmation": confirmation}

    def advance(self):
        self.plans = []
        self.notice = ""
        self.step = next_step(self.session.snapshot, self.session.target, self.session.symptom,
                              {a.step.code for a in self.session.attempts}, try_modes=True,
                              connection_path=self.session.connection_path)
        self.phase = "step" if self.step else "summary"
        if not self.step:
            self.session.outcome = "insufficient" if insufficient(self.session) else "unresolved"

    @staticmethod
    def choice(data, name, options):
        value = data.get(name)
        if not isinstance(value, str) or value not in options:
            raise ValueError(f"Choose a valid {name}.")
        return value

    def action(self, data):
        with self.lock:
            action = data.get("action")
            if data.get("revision") != self.revision:
                raise Conflict("The state changed. Review the current step before choosing again.")
            self.last_seen = time.monotonic()
            if action == "decision" and self.phase == "confirm":
                if data.get("nonce") != self.confirmation["nonce"]:
                    raise Conflict("This confirmation has expired.")
                allowed = {"keep", "undo", "next"} if self.confirmation["modes"] else {"keep", "undo"}
                decision = self.choice(data, "decision", allowed)
                if time.monotonic() >= self.confirmation["deadline"]:
                    raise Conflict("The confirmation deadline has passed; recovery is in progress.")
                self.decision = decision
                self.phase = "running"
                self.changed()
                self.condition.notify_all()
                return self.state()
            if action == "stop" and self.phase in {"running", "confirm"}:
                self.cancelled = True
                self.decision = "undo"
                self.phase = "running"
                self.changed()
                self.condition.notify_all()
                return self.state()
            if self.phase in {"running", "confirm"}:
                raise Conflict("Wait for the attempt and recovery to finish.")
            if action == "refresh" and self.phase in {"home", "summary"}:
                self.session.snapshot = self.reader()
            elif action == "start" and self.phase in {"home", "summary"}:
                symptom = self.choice(data, "symptom", SYMPTOMS)
                connection = self.choice(data, "connection", CONNECTION_PATHS)
                snapshot = self.reader()
                self.session = Session(symptom=symptom, initial_symptom=symptom,
                                       connection_path=connection, initial_connection=connection,
                                       snapshot=snapshot, initial_snapshot=snapshot)
                self.phase = "target"
                self.result = None
                self.notice = ""
                self.plans = []
                self.step = None
            elif action == "target" and self.phase == "target":
                target = data.get("target")
                if target is not None and (not isinstance(target, str) or not target_connector(self.session.snapshot, target)):
                    raise ValueError("Choose an external output from the current reading.")
                self.session.target = target
                if self.session.attempts and self.session.attempts[-1].performed:
                    self.session.attempts[-1].after = describe(self.session.snapshot, target)
                    self.phase = "observe"
                else:
                    self.advance()
            elif action in {"done", "skip"} and self.phase in {"step", "preview"}:
                before = describe(self.session.snapshot, self.session.target)
                snapshot = self.reader() if action == "done" else self.session.snapshot
                self.session.attempts.append(Attempt(self.step, action == "done", before))
                self.plans = []
                if action == "skip":
                    self.advance()
                else:
                    previous = self.session.snapshot
                    self.session.snapshot = snapshot
                    self.session.attempts[-1].after = describe(snapshot, self.session.target)
                    # Any topology change requests explicit identification again.
                    old = {(c.name, c.status) for c in candidates(previous)}
                    new = {(c.name, c.status) for c in candidates(snapshot)}
                    self.phase = "target" if old != new else "observe"
                    if old != new:
                        self.session.target = None
                    if self.step.code == "direct":
                        self.session.connection_path = "unknown"
            elif action == "observe" and self.phase == "observe":
                observation = self.choice(data, "observation", {*SYMPTOMS, "resolved", "unverified"})
                if self.step.code == "direct":
                    self.session.connection_path = self.choice(data, "connection", CONNECTION_PATHS)
                self.session.attempts[-1].observation = (
                    "expected image confirmed on the projector" if observation == "resolved" else
                    "cannot be verified" if observation == "unverified" else SYMPTOMS[observation])
                if observation in {"resolved", "unverified"}:
                    self.session.outcome = "resolved" if observation == "resolved" else "insufficient"
                    self.phase = "summary"
                else:
                    self.session.symptom = observation
                    self.advance()
            elif action == "preview" and self.phase == "step" and self.step.code in {"activate", "mode"}:
                from .fix_backends import backend_for, prepare_modes
                from .kde_fix import Unavailable
                if self.demo:
                    self.notice = "Demonstration data only. Automatic display changes are unavailable."
                else:
                    try:
                        self.plans = (prepare_modes(self.session.snapshot, self.session.target)
                                      if self.step.code == "mode" else
                                      [backend_for(self.session.snapshot).prepare(self.session.target)])
                        self.phase = "preview"
                    except Unavailable as error:
                        self.notice = str(error)
            elif action == "apply" and self.phase == "preview" and self.plans and not self.demo:
                self.phase = "running"
                self.cancelled = False
                self.result = None
                self.worker = threading.Thread(target=self.run_attempt, daemon=True)
                self.worker.start()
            elif action == "manual" and self.phase == "preview":
                self.plans = []
                self.phase = "step"
            elif action == "stop":
                self.session.outcome = "interrupted"
                self.phase = "summary"
                self.plans = []
            elif action == "home" and self.phase in {"home", "summary"}:
                self.phase = "home"
                self.notice = ""
            else:
                raise Conflict("That action is not available in the current step.")
            self.changed()
            return self.state()

    def confirm(self, plan, index, total, seconds):
        with self.condition:
            if self.cancelled or time.monotonic() - self.last_seen > 4:
                return "undo"
            self.decision = None
            self.confirmation = {"nonce": secrets.token_urlsafe(18), "deadline": time.monotonic() + seconds,
                                 "description": plan.description, "index": index, "total": total,
                                 "modes": getattr(plan, "action", "activation") == "mode"}
            self.phase = "confirm"
            self.changed()
            while (self.decision is None and not self.cancelled
                   and time.monotonic() < self.confirmation["deadline"]
                   and time.monotonic() - self.last_seen <= 4):
                self.condition.wait(timeout=min(0.25, max(0, self.confirmation["deadline"] - time.monotonic())))
            decision = self.decision if not self.cancelled and time.monotonic() < self.confirmation["deadline"] else "undo"
            self.confirmation = None
            self.phase = "running"
            self.changed()
            return decision or "undo"

    def run_attempt(self):
        from .automatic import run_activation, run_mode_sequence
        from .fix_worker import FixResult
        with self.lock:
            plans = list(self.plans)
            step = self.step
            before = describe(self.session.snapshot, self.session.target)
        def guarded_attempt(plan, confirm):
            with self.lock:
                if self.cancelled or time.monotonic() - self.last_seen > 4:
                    return FixResult("refused", "The browser is no longer active. No new trial was started.")
            return run_activation(plan, confirm)

        try:
            if getattr(plans[0], "action", "activation") == "mode":
                result = run_mode_sequence(plans, self.confirm, run_attempt=guarded_attempt)
            else:
                result = guarded_attempt(plans[0], lambda seconds: self.confirm(plans[0], 1, 1, seconds) == "keep")
        except Exception:
            result = FixResult("attention", "The attempt failed unexpectedly. Check Display settings; recovery is unverified.", True)
        # Never block delivery of a recovery result on a slow desktop query.
        with self.lock:
            self.result = result
            self.session.attempts.append(Attempt(step, result.attempted, before,
                observation="expected image confirmed on the projector" if result.status == "kept" else "not confirmed",
                automatic_result=result.detail))
            self.session.outcome = "resolved" if result.status == "kept" else "not_confirmed"
            self.phase = "summary"
            self.confirmation = None
            self.plans = []
            self.changed()

    def close(self):
        with self.condition:
            self.cancelled = True
            self.decision = "undo"
            self.condition.notify_all()


def demo_snapshot():
    from .models import Connector, CurrentMode, Snapshot, VideoMode
    mode = CurrentMode("reported", "demo", "Simulated data, not a device reading.", VideoMode(1920, 1080, 60))
    return Snapshot("Linux", "demo", "wayland", "DEMO", connectors=[
        Connector("card0-eDP-1", "internal", "connected", "enabled", ("1920x1080",), mode),
        Connector("card0-HDMI-A-1", "external", "connected", "enabled", ("1920x1080", "1280x720"), mode)])


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, app, port=0):
        self.app = app
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.url = self.origin + "/#" + self.token


class Handler(BaseHTTPRequestHandler):
    # No general filesystem serving, redirects, CORS or access logs containing tokens.
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def send(self, status, payload, content_type="application/json"):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload, ensure_ascii=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def allowed(self, api=False):
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            self.send(403, {"error": "Invalid host."})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            self.send(403, {"error": "Cross-origin requests are refused."})
            return False
        token = self.headers.get("X-BeamFix-Token", "")
        if api and not hmac.compare_digest(token.encode("utf-8"), self.server.token.encode("utf-8")):
            self.send(403, {"error": "Open the launch URL shown by BeamFix."})
            return False
        return True

    def do_GET(self):
        if not self.allowed(self.path.startswith("/api/")):
            return
        if self.path == "/api/state":
            self.send(200, self.server.app.state())
            return
        if self.path in {"/license", "/notice"}:
            name = "LICENSE.txt" if self.path == "/license" else "NOTICE.txt"
            self.send(200, files("beamfix").joinpath(name).read_bytes(), "text/plain; charset=utf-8")
            return
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  **{f"/{name}.svg": (f"{name}.svg", "image/svg+xml") for name in SYMPTOMS}}
        if self.path not in assets:
            self.send(404, {"error": "Not found."})
            return
        name, mime = assets[self.path]
        self.send(200, files("beamfix").joinpath("web", name).read_bytes(), mime)

    def do_POST(self):
        if not self.allowed(api=True):
            return
        if self.path not in {"/api/action", "/api/quit"}:
            self.send(404, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096 or self.headers.get("Content-Type") != "application/json":
                raise ValueError("Expected a small JSON request.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            if self.path == "/api/quit":
                self.server.app.close()
                self.send(200, {"closed": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send(200, self.server.app.action(data))
        except Conflict as error:
            self.send(409, {"error": str(error)})
        except (ValueError, UnicodeError) as error:
            self.send(400, {"error": str(error)})
        except Exception:
            self.send(500, {"error": "The operation could not finish. No success was inferred; retry the reading or use the CLI."})


def run(*, no_browser=False, demo=False, port=0):
    app = Application(demo=demo)
    try:
        server = Server(app, port)
    except OSError as error:
        print(f"Could not start the local interface: {error}")
        return 2
    print(f"BeamFix {__version__} — {'demonstration' if demo else 'local interface'}", flush=True)
    print(f"Open {server.url}", flush=True)
    print("Keep this process running. Use Quit BeamFix in the page or Ctrl+C to stop.", flush=True)
    if not no_browser:
        def open_browser():
            try:
                if not webbrowser.open(server.url):
                    print("No browser opened automatically. Copy the launch URL above into your browser.", flush=True)
            except webbrowser.Error:
                print("Open the launch URL above in your browser.", flush=True)
        threading.Thread(target=open_browser, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()
        # The detached worker still owns its timeout if this UI exits mid-recovery.
        if app.worker:
            app.worker.join(timeout=1)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Open BeamFix's offline local graphical interface.")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Use simulated readings; disable automatic changes.")
    args = parser.parse_args()
    return run(no_browser=args.no_browser, demo=args.demo)
