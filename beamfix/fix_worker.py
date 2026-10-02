"""Detached owner of a temporary display change and its rollback deadline.

The terminal process only sends a plan and a visual decision. This process owns
the write, the deadline, and the inverse operation, including on terminal death.
"""

import errno
import json
import os
import signal
import socket
import struct
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from .fix_backends import decode_plan
from .gnome_fix import GNOMEBackend
from .kde_fix import KDEBackend, Unavailable
from .kde_modes import KDEModeBackend


CONFIRM_SECONDS = 15


@dataclass(frozen=True)
class FixResult:
    status: str
    detail: str
    attempted: bool = False


class Channel:
    def __init__(self, connection):
        self.connection = connection

    def send(self, message):
        payload = json.dumps(message, allow_nan=False).encode("utf-8")
        if len(payload) > 2_000_000:
            raise ValueError("Oversized activation message")
        self.connection.settimeout(2)
        self.connection.sendall(struct.pack("!I", len(payload)) + payload)

    def receive(self, timeout):
        deadline = time.monotonic() + timeout

        def exact(length):
            data = bytearray()
            while len(data) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                part = self.connection.recv(length - len(data))
                if not part:
                    raise EOFError
                data.extend(part)
            return data

        length, = struct.unpack("!I", exact(4))
        if length > 2_000_000:
            raise ValueError("Oversized activation message")
        message = json.loads(exact(length))
        if not isinstance(message, dict):
            raise ValueError("Invalid activation message")
        return message


@contextmanager
def activation_lock():
    # Linux abstract sockets need no files or stale-lock cleanup. One temporary
    # activation per uid, even across multiple terminals or graphical sessions.
    lock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            lock.bind(f"\0beamfix-activation-{os.getuid()}")
        except OSError as error:
            reason = ("Another BeamFix automatic attempt is already running." if error.errno == errno.EADDRINUSE
                      else "The independent recovery lock is unavailable in this environment.")
            raise Unavailable(reason) from error
        yield
    finally:
        lock.close()


def change(backend, plan, forward):
    if getattr(plan, "action", "activation") == "mode":
        backend.set_mode(plan, forward)
    else:
        backend.set_enabled(plan, forward)


def rollback(backend, plan):
    # Retry unavailable reads; never blindly replay an old full configuration.
    for _ in range(2):
        try:
            current = backend.state()
            if current == plan.before:
                return FixResult("reverted", "The original output configuration is verified.", True)
            if current != plan.expected:
                return FixResult("attention", "The connection or settings changed outside this attempt. "
                                 "Automatic rollback was withheld; check Display settings.", True)
            change(backend, plan, False)
            if backend.state() == plan.before:
                return FixResult("reverted", "The original output configuration was restored and verified.", True)
        except (Unavailable, OSError):
            continue
    return FixResult("attention", "The original configuration could not be verified. "
                     "Check Display settings before continuing.", True)


def transact(plan, backend, channel, *, seconds=CONFIRM_SECONDS):
    attempted = False
    committed = False
    requested_next = False
    reason = "No visual confirmation was received."
    result = FixResult("refused", "The automatic change was not started.")
    try:
        # Rebuild from fresh DRM and desktop data after user approval, under the lock.
        if backend.prepare(plan.connector) != plan:
            raise Unavailable("The configuration changed after the preview; no change was applied.")
        # Ask the still-live UI for authorization to start after revalidation.
        # If it died during preparation, no display write is needed.
        channel.send({"event": "armed"})
        if channel.receive(5).get("action") != "apply":
            raise Unavailable("The attempt was cancelled before any change.")
        attempted = True
        change(backend, plan, True)
        if backend.state() != plan.expected:
            raise Unavailable("The desktop did not report the expected change and unchanged surrounding layout.")
        deadline = time.monotonic() + seconds
        channel.send({"event": "confirm", "deadline": deadline})
        decision = channel.receive(max(0, deadline - time.monotonic()))
        if decision.get("action") == "keep" and time.monotonic() < deadline:
            if backend.state() != plan.expected:
                raise Unavailable("The configuration changed before confirmation could be accepted.")
            if time.monotonic() >= deadline:
                reason = "The confirmation deadline expired during verification."
            else:
                committed = True
                result = FixResult("kept", "Expected image confirmed by the user; configuration kept.", True)
        else:
            requested_next = (getattr(plan, "action", "activation") == "mode"
                              and decision.get("action") == "next" and time.monotonic() < deadline)
            reason = "The user requested the next mode." if requested_next else "The change was not confirmed within the time limit."
    except (EOFError, TimeoutError, ConnectionError):
        reason = "The terminal closed or the confirmation deadline expired."
        result = FixResult("refused", reason)
    except Exception as error:
        reason = str(error) if isinstance(error, Unavailable) else "The automatic attempt was interrupted by an error."
        result = FixResult("refused", reason)
    finally:
        if attempted and not committed:
            try:
                channel.send({"event": "recovering"})
            except (OSError, ValueError):
                pass
            try:
                recovery = rollback(backend, plan)
                status = "next" if requested_next and recovery.status == "reverted" else recovery.status
                result = FixResult(status, reason + " " + recovery.detail, True)
            except Exception:
                result = FixResult("attention", "Recovery failed unexpectedly. Check Display settings.", True)
    return result


def serve(connection):
    channel = Channel(connection)
    try:
        message = channel.receive(10)
        plan = decode_plan(message["plan"])
        with activation_lock():
            if getattr(plan, "action", "activation") == "mode":
                backend = KDEModeBackend(plan.mode_id)
            else:
                backend = GNOMEBackend() if plan.backend == "gnome" else KDEBackend()
            result = transact(plan, backend, channel)
    except Exception as error:
        result = FixResult("refused", str(error) if isinstance(error, Unavailable) else
                           "The recovery worker could not prepare the attempt.")
    try:
        channel.send({"event": "result", **asdict(result)})
    except (OSError, ValueError):
        pass  # The UI may have died; recovery has already been attempted.


def main():
    # A terminal hangup or Ctrl+C must not stop recovery. SIGKILL, logout and
    # compositor failure cannot be recovered by a userspace helper.
    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, signal.SIG_IGN)
    with socket.socket(fileno=int(sys.argv[1])) as connection:
        serve(connection)


if __name__ == "__main__":
    main()
