"""Read standard wl_output observations through optional wayland-info."""

import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import replace

from .models import CurrentMode, Snapshot, VideoMode


def parse_outputs(text: str) -> list[tuple[str, VideoMode | None]]:
    """Accept only named wl_output blocks with one valid current mode.

    wayland-info has a human-readable, not a versioned machine-readable format.
    Unrecognized or incomplete records deliberately remain unknown. Other
    interfaces and identifying fields (description, make/model) are discarded.
    """
    outputs = []
    for block in re.split(r"(?=^interface:)", text, flags=re.MULTILINE):
        lines = block.splitlines()
        if not lines or not re.fullmatch(
            r"interface: 'wl_output',\s+version:\s+\d+,\s+name:\s+\d+", lines[0]
        ):
            continue
        names = re.findall(r"^\tname: ([A-Za-z0-9_-]+)$", block, re.MULTILINE)
        if not names:
            continue
        # Do not mistake the preferred mode or the logical/scaled size for current.
        sections = re.findall(r"^\tmode:\n((?:\t\t[^\n]*\n?)*)", block, re.MULTILINE)
        current = []
        valid = len(names) == 1 and bool(sections)
        for section in sections:
            match = re.fullmatch(
                r"\t\twidth: ([0-9]{1,10}) px, height: ([0-9]{1,10}) px, "
                r"refresh: ([0-9]{1,7}\.[0-9]{3}) Hz,\n"
                r"\t\tflags: ([a-z, ]*)\n?", section,
            )
            if match is None:
                valid = False
                continue
            width, height, rate, flags = match.groups()
            flags = {flag.strip() for flag in flags.split(",") if flag.strip()}
            if not flags <= {"current", "preferred"}:
                valid = False
            if "current" in flags:
                mode = VideoMode(int(width), int(height), float(rate))
                if not (0 < mode.width <= 2147483647 and 0 < mode.height <= 2147483647
                        and 0 < mode.refresh_hz <= 2147483.647):
                    valid = False
                current.append(mode)
        mode = current[0] if valid and len(current) == 1 else None
        outputs.extend((name, mode) for name in names)
    return outputs


def apply_wayland_modes(snapshot: Snapshot, text: str) -> Snapshot:
    outputs = parse_outputs(text)
    port_names = [re.sub(r"^card\d+-", "", c.name) for c in snapshot.connectors]
    counts = Counter(port_names)
    connectors = []
    for connector, name in zip(snapshot.connectors, port_names):
        matching = [mode for output_name, mode in outputs if output_name == name]
        reason = "No unique named Wayland output matches this Linux connector; absence does not mean disconnected."
        observation = CurrentMode("unknown", "wayland-info", reason)
        if counts[name] == 1 and len(matching) == 1:
            if connector.status != "connected" or connector.enabled != "enabled":
                observation = CurrentMode("unknown", "wayland-info",
                    "Wayland advertises an output that Linux does not confirm as connected and enabled; read again.")
            elif matching[0] is None:
                observation = CurrentMode("unknown", "wayland-info",
                    "Wayland did not provide one readable current mode with a known positive refresh rate.")
            else:
                observation = CurrentMode("reported", "wayland-info",
                    "Current mode reported by Wayland; the available mode list is not verified.", matching[0])
        elif not matching and (connector.status == "disconnected" or connector.enabled == "disabled"):
            observation = CurrentMode("inactive", "drm", "Linux reports this output as disconnected or disabled.")
        connectors.append(replace(connector, current_mode=observation))
    snapshot.connectors = connectors
    return snapshot


def _unavailable(snapshot: Snapshot, reason: str) -> Snapshot:
    snapshot = apply_wayland_modes(snapshot, "")
    snapshot.connectors = [replace(c, current_mode=CurrentMode("unknown", "wayland-info", reason))
        if c.current_mode.state == "unknown" else c for c in snapshot.connectors]
    return snapshot


def add_wayland_modes(snapshot: Snapshot) -> Snapshot:
    if snapshot.system != "Linux" or snapshot.session != "wayland":
        return _unavailable(snapshot, "Standard Wayland observation requires a Linux Wayland session.")
    executable = shutil.which("wayland-info")
    if executable is None:
        return _unavailable(snapshot, "wayland-info is not installed; basic Linux diagnostics remain available.")
    try:
        result = subprocess.run(
            [executable, "-i", "wl_output"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, encoding="utf-8", timeout=5, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired:
        return _unavailable(snapshot, "Wayland did not respond within 5 seconds; read again in the desktop session.")
    except (OSError, UnicodeError):
        return _unavailable(snapshot, "Wayland display data could not be read from this session.")
    if result.returncode != 0:
        return _unavailable(snapshot, "wayland-info could not query the session; run BeamFix from your desktop terminal.")
    return apply_wayland_modes(snapshot, result.stdout)
