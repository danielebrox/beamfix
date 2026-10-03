"""Read-only mode observation: KDE when available, standard Wayland otherwise."""

import json
import math
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import replace

from .collect import collect
from .models import Connector, CurrentMode, Snapshot, VideoMode
from .wayland import add_wayland_modes


def _port(connector: Connector) -> str:
    return re.sub(r"^card\d+-", "", connector.name)


def _fallback(connector: Connector, reason: str) -> CurrentMode:
    if connector.status == "disconnected" or connector.enabled == "disabled":
        return CurrentMode("inactive", "drm", "Linux reports this output as disconnected or disabled.")
    return CurrentMode("unknown", "kscreen-doctor", reason)


def _unavailable(snapshot: Snapshot, reason: str) -> Snapshot:
    snapshot.connectors = [replace(c, current_mode=_fallback(c, reason)) for c in snapshot.connectors]
    return snapshot


def _video_mode(raw: object) -> VideoMode | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("size"), dict):
        return None
    width, height = raw["size"].get("width"), raw["size"].get("height")
    rate = raw.get("refreshRate")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        return None
    if type(rate) not in (int, float):
        return None
    try:
        refresh = float(rate)
    except OverflowError:
        return None
    if not math.isfinite(refresh) or refresh <= 0:
        return None
    return VideoMode(width, height, refresh)


def _assess(connector: Connector, output: dict) -> CurrentMode:
    def unknown(reason: str) -> CurrentMode:
        return CurrentMode("unknown", "kscreen-doctor", reason)

    connected, enabled = output.get("connected"), output.get("enabled")
    if type(connected) is not bool:
        return unknown("KDE did not provide a valid connection state.")
    if connector.status != "unknown" and connected != (connector.status == "connected"):
        return unknown("KDE and Linux disagree about the connection; run doctor again.")
    if not connected:
        return CurrentMode("inactive", "kscreen-doctor", "KDE reports this output as disconnected.")
    if type(enabled) is not bool:
        return unknown("KDE did not provide a valid enabled state.")
    if connector.enabled != "unknown" and enabled != (connector.enabled == "enabled"):
        return unknown("KDE and Linux disagree about output activation; run doctor again.")
    if not enabled:
        # KDE may retain a currentModeId while an output is disabled.
        return CurrentMode("inactive", "kscreen-doctor", "KDE reports this output as disabled.")
    mode_id, modes = output.get("currentModeId"), output.get("modes")
    if not isinstance(mode_id, str) or not mode_id or not isinstance(modes, list):
        return unknown("KDE did not provide a current mode ID and mode list.")
    matching = [m for m in modes if isinstance(m, dict) and m.get("id") == mode_id]
    if len(matching) != 1:
        return unknown("The current mode cannot be uniquely matched to KDE's mode list.")
    mode = _video_mode(matching[0])
    if mode is None:
        return unknown("The current mode has incomplete or invalid resolution/refresh data.")
    return CurrentMode("listed", "kscreen-doctor", "Current mode is listed as available by KDE.", mode)


def apply_kde_modes(snapshot: Snapshot, data: object) -> Snapshot:
    """Join only unique connector names; no guessing across GPU or X11 aliases."""
    if not isinstance(data, dict) or not isinstance(data.get("outputs"), list):
        return _unavailable(snapshot, "KDE returned an unreadable display configuration.")
    outputs = data["outputs"]
    port_counts = Counter(_port(c) for c in snapshot.connectors)
    connectors = []
    for connector in snapshot.connectors:
        name = _port(connector)
        matching = [o for o in outputs if isinstance(o, dict) and o.get("name") == name]
        if port_counts[name] != 1 or len(matching) != 1:
            observation = _fallback(connector, "No unique KDE output matches this Linux connector.")
        else:
            observation = _assess(connector, matching[0])
        connectors.append(replace(connector, current_mode=observation))
    snapshot.connectors = connectors
    return snapshot


def _query_kde() -> tuple[object, str | None]:
    executable = shutil.which("kscreen-doctor")
    if executable is None:
        return None, "kscreen-doctor is not installed; basic Linux diagnostics remain available."
    try:
        result = subprocess.run(
            [executable, "--json"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, encoding="utf-8", timeout=5, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "KDE did not respond within 5 seconds; read again in the desktop session."
    except (OSError, UnicodeError):
        return None, "KDE display data could not be read from this session."
    if result.returncode != 0:
        return None, "KDE display data could not be read; run BeamFix from your desktop terminal."
    try:
        data = json.loads(result.stdout)
    except (ValueError, RecursionError):
        return None, "KDE returned invalid display data."
    if not isinstance(data, dict) or not isinstance(data.get("outputs"), list):
        return None, "KDE returned an unreadable display configuration."
    return data, None


def add_current_modes(snapshot: Snapshot) -> Snapshot:
    if not snapshot.connectors:
        return snapshot
    reason = "Current-mode detection requires Wayland or a supported KDE session."
    if snapshot.system == "Linux":
        if "KDE" in snapshot.desktop.upper().split(":") and snapshot.session in {"wayland", "x11"}:
            data, reason = _query_kde()
            if reason is None:
                # Preserve ambiguous or conflicting observations from a valid KDE
                # response. A fallback must not conceal a possible hot-plug race.
                return apply_kde_modes(snapshot, data)
        if snapshot.session == "wayland":
            return add_wayland_modes(snapshot)
    return _unavailable(snapshot, reason)


def collect_doctor() -> Snapshot:
    from .signal import add_signal_details

    return add_signal_details(add_current_modes(collect()))
