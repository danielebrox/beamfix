"""Read kernel DRM observations. No subprocesses, network, or system writes."""

import os
import platform
import re
from pathlib import Path
from collections.abc import Mapping

from .models import Connector, GPU, Snapshot


def connector_kind(name: str) -> str:
    port = name.split("-", 1)[1]
    if port.startswith(("eDP-", "LVDS-", "DSI-", "DPI-", "SPI-")):
        return "internal"
    if port.startswith(("Virtual-", "Writeback-")):
        return "virtual"
    if port.startswith(("HDMI-", "DP-", "DVI-", "VGA-", "USB-")):
        return "external"
    return "unknown"


def _read(path: Path, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path.parent.name}/{path.name}: {type(exc).__name__}")
        return None


def _state(path: Path, allowed: set[str], errors: list[str]) -> str:
    value = _read(path, errors)
    if value is None:
        return "unknown"
    if value not in allowed:
        errors.append(f"{path.parent.name}/{path.name}: valore non riconosciuto")
        return "unknown"
    return value


def collect(
    drm_root: Path = Path("/sys/class/drm"),
    *,
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
) -> Snapshot:
    env = os.environ if environ is None else environ
    session = env.get("XDG_SESSION_TYPE", "").lower()
    if session not in {"wayland", "x11", "tty"}:
        session = "unknown"
    snapshot = Snapshot(
        system=platform.system() if system is None else system,
        kernel=platform.release(),
        session=session,
        desktop=env.get("XDG_CURRENT_DESKTOP", "unknown"),
    )
    if snapshot.system != "Linux":
        snapshot.errors.append("Questa versione supporta soltanto Linux.")
        return snapshot
    try:
        entries = sorted(drm_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        snapshot.errors.append(f"DRM non accessibile: {type(exc).__name__}")
        return snapshot
    for entry in entries:
        if re.fullmatch(r"card\d+", entry.name):
            try:
                driver = (entry / "device" / "driver").resolve(strict=True).name
            except OSError:
                driver = None  # Optional: virtual/platform devices may omit it.
            snapshot.gpus.append(GPU(entry.name, driver))
        elif re.fullmatch(r"card\d+-.+", entry.name):
            status = _state(entry / "status", {"connected", "disconnected", "unknown"}, snapshot.errors)
            enabled = _state(entry / "enabled", {"enabled", "disabled"}, snapshot.errors)
            raw_modes = _read(entry / "modes", snapshot.errors)
            modes = None if raw_modes is None else tuple(dict.fromkeys(raw_modes.splitlines()))
            snapshot.connectors.append(Connector(entry.name, connector_kind(entry.name), status, enabled, modes))
    if not snapshot.connectors:
        snapshot.errors.append("Nessun connettore DRM osservabile in questo ambiente.")
    return snapshot
