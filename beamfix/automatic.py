"""Terminal client for the independent activation/recovery worker."""

import os
import select
import socket
import subprocess
import sys
import termios
import time
from dataclasses import asdict
from pathlib import Path

from .fix_worker import Channel, FixResult


def confirm_in_terminal(ui, seconds):
    """Only a fresh explicit 1 + Enter keeps the temporary configuration."""
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return False
    termios.tcflush(fd, termios.TCIFLUSH)
    ui.section("VERIFY THE AUTOMATIC ATTEMPT")
    ui.text(f"You have up to {max(0, int(seconds))} seconds. Can you see the image you wanted to project?")
    ui.option(1, "Yes: keep this activation")
    ui.option(2, "No / cannot verify: undo activation")
    ui.text("Press Enter after your choice. No answer also undoes the activation.")
    sys.stdout.flush()
    ready, _, _ = select.select([fd], [], [], max(0, seconds))
    if not ready:
        return False
    # os.read avoids an unbounded readline on partial/noncanonical input.
    answer = os.read(fd, 1024)
    return answer.strip() == b"1" and b"\n" in answer


def confirm_mode_in_terminal(ui, seconds):
    """Silence, interruption and malformed input stop the sequence after undo."""
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return "undo"
    termios.tcflush(fd, termios.TCIFLUSH)
    ui.section("CAN YOU SEE THE EXPECTED IMAGE?")
    ui.text(f"You have up to {max(0, int(seconds))} seconds.")
    ui.option(1, "Yes: keep this mode and finish")
    ui.option(2, "No: restore, then try the next mode")
    ui.option(0, "Stop and restore the original mode")
    ui.text("Press Enter after your choice. No answer restores the original mode and stops.")
    sys.stdout.flush()
    if not select.select([fd], [], [], max(0, seconds))[0]:
        return "undo"
    answer = os.read(fd, 1024)
    if b"\n" not in answer:
        return "undo"
    return {b"1": "keep", b"2": "next"}.get(answer.strip(), "undo")


def run_mode_sequence(plans, confirm, *, run_attempt=None):
    """Backend-independent sequence; only a worker-verified next can advance."""
    from .kde_modes import MAX_MODE_TRIALS
    run_attempt = run_attempt or run_activation
    if not plans or len(plans) > MAX_MODE_TRIALS:
        return FixResult("refused", "The mode sequence is empty or exceeds the trial limit.")
    first = plans[0]
    if any(p.before != first.before or p.connector != first.connector or p.backend != first.backend
           or p.output != first.output or getattr(p, "action", None) != "mode" for p in plans):
        return FixResult("refused", "The mode sequence does not share one target and original configuration.")
    details = []
    attempted = False
    for index, plan in enumerate(plans, 1):
        result = run_attempt(plan, lambda seconds: confirm(plan, index, len(plans), seconds))
        attempted = attempted or result.attempted
        details.append(f"Trial {index}/{len(plans)}: {plan.description} {result.detail}")
        if result.status != "next":
            return FixResult(result.status, "\n".join(details), attempted)
    details.append("No mode was visually confirmed. The original configuration is verified; no more trials remain.")
    return FixResult("exhausted", "\n".join(details), attempted)


def run_activation(plan, confirm):
    parent, child = socket.socketpair()
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "beamfix.fix_worker", str(child.fileno())],
            cwd=Path(__file__).resolve().parent.parent,
            pass_fds=(child.fileno(),), start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        child.close()
        channel = Channel(parent)
        channel.send({"plan": asdict(plan)})
        message = channel.receive(20)
        if message.get("event") == "armed":
            channel.send({"action": "apply"})
            message = channel.receive(30)
        if message.get("event") == "confirm":
            try:
                decision = confirm(max(0, message["deadline"] - time.monotonic()))
            except (KeyboardInterrupt, EOFError):
                decision = False
            action = "keep" if decision is True else "undo"
            if getattr(plan, "action", "activation") == "mode" and decision in ("keep", "next", "undo"):
                action = decision
            channel.send({"action": action})
            message = channel.receive(10)
        if message.get("event") == "recovering":
            # GNOME verifies and applies the complete logical layout through
            # multiple bounded D-Bus calls, including fresh serial checks.
            message = channel.receive(65)
        if message.get("event") != "result":
            raise ValueError("Invalid worker response")
        return FixResult(message["status"], message["detail"], message["attempted"])
    except (OSError, EOFError, ValueError, KeyError, KeyboardInterrupt):
        return FixResult("attention", "The recovery worker's result is unavailable. "
                         "Its timeout remains active if it is still running. Check Display settings.", process is not None)
    finally:
        parent.close()  # EOF requests rollback even if the UI itself failed.
        child.close()
        if process is not None:
            # Never terminate the worker during recovery.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
