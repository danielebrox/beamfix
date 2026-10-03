"""Small, dependency-free terminal presentation with a plain-text fallback."""

import os
import shutil
import sys
import unicodedata
from collections.abc import Callable, Mapping

from .models import Finding, Snapshot


def safe(value: str) -> str:
    """Keep device/environment data from injecting terminal control sequences."""
    return "".join(char if char.isprintable() else "?" for char in value)


def cells(value: str) -> int:
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1 for c in value)


def wrap(value: str, width: int) -> list[str]:
    """Wrap on words, splitting long tokens by terminal cells rather than bytes."""
    lines: list[str] = []
    line = ""
    for word in value.split():
        if line and cells(line) + 1 + cells(word) > width:
            lines.append(line)
            line = ""
        if line:
            line += " " + word
            continue
        for char in word:
            if line and cells(line) + cells(char) > width:
                lines.append(line)
                line = ""
            line += char
    if line or not lines:
        lines.append(line)
    return lines


class Terminal:
    # Use the terminal's own ANSI palette, including light and Omarchy themes.
    TONES = {"accent": "1;36", "title": "1", "info": "36", "ok": "32", "warning": "33", "error": "31", "muted": "39"}

    def __init__(
        self, *, write: Callable[[str], None] | None = None, plain: bool = False,
        width: int | None = None, environ: Mapping[str, str] | None = None,
        is_tty: bool | None = None, encoding: str | None = None,
    ):
        env = os.environ if environ is None else environ
        tty = (write is None and sys.stdout.isatty()) if is_tty is None else is_tty
        self.decorated = tty and not plain and env.get("TERM") != "dumb"
        self.color = self.decorated and "NO_COLOR" not in env
        self.unicode = False
        if self.decorated:
            try:
                "─│".encode(encoding or sys.stdout.encoding or "ascii")
                self.unicode = True
            except (UnicodeError, LookupError):
                pass
        self.width = max(8, min(96, width if width is not None else shutil.get_terminal_size((88, 24)).columns))
        self.write = write or print

    def paint(self, value: str, tone: str = "title") -> str:
        return f"\x1b[{self.TONES[tone]}m{value}\x1b[0m" if self.color else value

    def text(self, value: str = "", tone: str = "muted", indent: int = 2) -> None:
        for line in wrap(safe(value), self.width - indent):
            self.write(" " * indent + self.paint(line, tone))

    def blank(self) -> None:
        self.write("")

    def banner(self, mode: str, version: str) -> None:
        self.blank()
        self.text(f"BEAMFIX  /  v{version}", "accent")
        self.text(mode, "title")
        self.write("  " + self.paint(("─" if self.unicode else "-") * (self.width - 4), "accent"))

    def section(self, title: str) -> None:
        self.blank()
        self.text(title, "accent")

    def field(self, label: str, value: str, tone: str = "muted") -> None:
        self.text(f"{label}: {value}", tone)

    def status(self, label: str, message: str, tone: str = "info") -> None:
        self.text(f"[{label}] {message}", tone)

    def option(self, number: int, label: str) -> None:
        prefix = f"  [{number}] "
        for index, line in enumerate(wrap(safe(label), self.width - len(prefix))):
            self.write((self.paint(prefix, "accent" if number else "muted") if index == 0 else " " * len(prefix)) + line)

    def prompt(self) -> str:
        return self.paint("  > ", "accent")

    def step(self, number: int, title: str, reason: str, instruction: str) -> None:
        self.section(f"TRY {number:02d}")
        self.text("Step: " + title, "title")
        self.blank()
        self.field("Why", reason)
        self.blank()
        self.text("WHAT TO DO", "accent")
        # A left rail keeps the action distinct without a box that can overflow.
        rail = "│ " if self.unicode else "| "
        for line in wrap(safe(instruction), self.width - 4):
            self.write("  " + self.paint(rail, "accent") + line)


def render_doctor(snapshot: Snapshot, findings: list[Finding], exit_code: int, *, plain: bool = False, terminal: Terminal | None = None) -> None:
    from . import __version__

    ui = terminal or Terminal(plain=plain)
    ui.banner("Display health check", __version__)
    ui.text("Read-only diagnostics. No settings are changed.")
    ui.section("AT A GLANCE")
    warnings = sum(f.severity == "warning" for f in findings)
    if exit_code == 2:
        ui.status("UNKNOWN", "Some observations are incomplete or unknown.", "warning")
    elif warnings:
        ui.status("CHECK", f"{warnings} warning{'s' if warnings != 1 else ''} to review.", "warning")
    else:
        ui.status("INFO", "No issues detected by the available checks.")
    ui.text("An enabled output does not confirm a visible image.")

    ui.section("NEXT STEPS")
    if not findings:
        ui.text("If the image is missing or incorrect, start the guided checks.")
    for finding in findings:
        ui.status("CHECK" if finding.severity == "warning" else "INFO", finding.message,
                  "warning" if finding.severity == "warning" else "info")
        if finding.connector:
            ui.field("Output", finding.connector)
        ui.field("Try", finding.suggestion)
        ui.blank()
    ui.field("Guide", "beamfix troubleshoot", "accent")

    ui.section("DISPLAYS")
    if not snapshot.connectors:
        ui.status("UNKNOWN", "No connectors could be observed.", "warning")
    kinds = {"internal": "built-in screen", "external": "external output", "virtual": "virtual output", "unknown": "unclassified output"}
    for index, connector in enumerate(snapshot.connectors):
        if index:
            ui.blank()
        ui.text(f"{connector.name} / {kinds.get(connector.kind, connector.kind)}", "title")
        tone = "ok" if connector.status == "connected" else "warning" if connector.status == "unknown" else "muted"
        ui.status(connector.status.upper(), "Connection reported by Linux", tone)
        tone = "warning" if connector.enabled == "unknown" or (connector.status == "connected" and connector.enabled == "disabled" and connector.kind == "external") else "muted"
        ui.field("Output", connector.enabled, tone)
        observation = connector.current_mode
        if observation is not None:
            if observation.state in {"listed", "reported"} and observation.mode is not None:
                mode = observation.mode
                tone = "ok" if observation.state == "listed" else "info"
                ui.field("Current mode", f"{mode.width} x {mode.height} @ {mode.refresh_hz:.2f} Hz", tone)
                ui.status(observation.state.upper(), observation.reason, tone)
            elif observation.state == "inactive":
                ui.field("Current mode", "Inactive")
            else:
                ui.field("Current mode", "Unknown", "warning")
                ui.status("UNVERIFIED", observation.reason, "warning")
        modes = "unavailable" if connector.modes is None else (", ".join(connector.modes) or "none listed")
        ui.field("Available modes", modes)
        if connector.signal is not None:
            from .signal import signal_lines

            for line in signal_lines(connector.signal):
                ui.text(line)
    ui.text("Listed modes are not necessarily the mode currently in use.")
    if any(c.current_mode is not None for c in snapshot.connectors):
        ui.text("Current mode: configured pixel resolution and Hz, not desktop scaling or live refresh measurements.")
        ui.text("A listed or reported mode does not guarantee that the projected image is visible or correct.")

    ui.section("SYSTEM")
    ui.field("System", safe(snapshot.system) + " / kernel " + safe(snapshot.kernel))
    ui.field("Session", safe(snapshot.session) + " / " + safe(snapshot.desktop))
    for gpu in snapshot.gpus:
        ui.field("GPU", safe(gpu.card) + " / " + safe(gpu.driver or "driver unavailable"))
    if snapshot.errors:
        ui.section("MISSING DATA")
        for error in snapshot.errors:
            ui.status("UNKNOWN", error, "warning")
    ui.blank()
    ui.text("No changes applied. Image quality requires visual confirmation.")
