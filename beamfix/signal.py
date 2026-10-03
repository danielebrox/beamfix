"""Optional, read-only DRM signal observations. Never apply a display setting.

Input contract: drm_info's json.c, using /dev/dri/cardN plus the sysfs
connector_id, not display names or enumeration order. Retain an allowlist only.
"""

import json
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from .models import SignalDetails, SignalProperty, SignalTiming

SOURCE = "drm_info"
MAX_JSON_BYTES = 8 * 1024 * 1024
# name: (DRM property name, interpretation, parser type)
PROPERTIES = {
    "max_bpc": ("max bpc", "limit", "range"),
    "colorspace": ("Colorspace", "requested", "enum"),
    "color_format": ("color format", "requested", "enum"),
    "rgb_range": ("Broadcast RGB", "requested", "enum"),
    "hdr_metadata_present": ("HDR_OUTPUT_METADATA", "requested", "blob"),
    "content_protection": ("Content Protection", "driver_status", "enum"),
    "hdcp_content_type": ("HDCP Content Type", "requested", "enum"),
    "link_status": ("link-status", "driver_status", "enum"),
}
NOTES = {
    "max_bpc": "Configured upper limit, not the transmitted bit depth.",
    "colorspace": "Colorimetry request; does not identify RGB/YCbCr sampling on the wire.",
    "color_format": "Format request; AUTO does not identify the selected wire format.",
    "rgb_range": "RGB range request; Automatic does not identify the selected range.",
    "hdr_metadata_present": "Nonzero metadata reference, not proof that the projector displays HDR.",
    "content_protection": "Driver-reported HDCP state/request, not evidence that HDCP caused a fault.",
    "hdcp_content_type": "Requested HDCP content type, not proof of successful authentication.",
    "link_status": "Driver-reported link state, not evidence of a visible image downstream.",
}


def uint(value, maximum=2**32 - 1):
    return type(value) is int and 0 <= value <= maximum


def unavailable_properties(reason):
    values = {key: SignalProperty("unavailable", meaning, SOURCE, note=reason)
              for key, (_, meaning, _) in PROPERTIES.items()}
    values["actual_bpc"] = SignalProperty("unavailable", "unmeasured", SOURCE,
        note="This backend does not measure the transmitted bit depth.")
    return values


def unavailable(reason, state="unavailable"):
    return SignalDetails(state, SOURCE, reason, unavailable_properties(reason),
                         current_timing_reason=reason)


def parse_property(properties, key):
    name, meaning, kind = PROPERTIES[key]
    if not isinstance(properties, dict) or name not in properties:
        return SignalProperty("unavailable", meaning, SOURCE,
                              note="The driver did not expose this property in the observation.")
    prop = properties[name]
    invalid = SignalProperty("invalid", meaning, SOURCE, note="The property has an unsupported or invalid value.")
    if not isinstance(prop, dict):
        return invalid
    raw, value = prop.get("raw_value"), prop.get("value")
    if not uint(raw):
        return invalid
    if kind == "blob":
        if prop.get("type") != 16:
            return invalid
        value = raw != 0  # Do not retain blob IDs, data or EDID.
    else:
        if not uint(value) or value != raw:
            return invalid
        spec = prop.get("spec")
        if kind == "range":
            if (prop.get("type") != 2 or not isinstance(spec, dict)
                    or not uint(spec.get("min"), 64) or not uint(spec.get("max"), 64)
                    or not 1 <= spec["min"] <= value <= spec["max"]):
                return invalid
        else:
            if prop.get("type") != 8 or not isinstance(spec, list):
                return invalid
            matches = [entry for entry in spec if isinstance(entry, dict)
                       and type(entry.get("value")) is int and entry["value"] == value]
            if len(matches) != 1:
                return invalid
            value = matches[0].get("name")
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_ .:/+-]{1,80}", value):
                return invalid
    return SignalProperty("reported", meaning, SOURCE, value, NOTES[key])


def parse_timing(raw):
    if not isinstance(raw, dict):
        return None
    keys = ("hdisplay", "vdisplay", "hsync_start", "hsync_end", "htotal", "hskew",
            "vsync_start", "vsync_end", "vtotal", "vscan")
    if not all(uint(raw.get(key), 65535) for key in keys):
        return None
    if not uint(raw.get("clock")) or not raw["clock"] or not uint(raw.get("flags")):
        return None
    if not (0 < raw["hdisplay"] <= raw["hsync_start"] <= raw["hsync_end"] <= raw["htotal"]
            and 0 < raw["vdisplay"] <= raw["vsync_start"] <= raw["vsync_end"] <= raw["vtotal"]):
        return None
    hz = raw["clock"] * 1000 / (raw["htotal"] * raw["vtotal"])
    if raw["flags"] & 16:  # DRM_MODE_FLAG_INTERLACE
        hz *= 2
    if raw["flags"] & 32:  # DRM_MODE_FLAG_DBLSCAN
        hz /= 2
    if raw["vscan"] > 1:
        hz /= raw["vscan"]
    return SignalTiming(raw["clock"], *(raw[key] for key in keys), raw["flags"], round(hz, 6))


def unique_id(items, identifier):
    if not uint(identifier) or not identifier or not isinstance(items, list):
        return None
    matches = [item for item in items if isinstance(item, dict)
               and type(item.get("id")) is int and item["id"] == identifier]
    return matches[0] if len(matches) == 1 else None


def current_timing(device, connector):
    props = connector.get("properties")
    prop = props.get("CRTC_ID") if isinstance(props, dict) else None
    # Atomic connector routing is required: no guessing from the first mode or
    # an encoder's possible CRTC bitmask.
    if (not isinstance(prop, dict) or prop.get("type") != 64
            or not uint(prop.get("value")) or not uint(prop.get("raw_value"))
            or prop["raw_value"] != prop["value"]):
        return None, "No unambiguous atomic CRTC routing was reported."
    crtc = unique_id(device.get("crtcs"), prop["value"])
    if crtc is None:
        return None, "The selected CRTC was absent or ambiguous."
    crtc_props = crtc.get("properties")
    active = crtc_props.get("ACTIVE") if isinstance(crtc_props, dict) else None
    if (not isinstance(active, dict) or active.get("type") != 2
            or type(active.get("value")) is not int or active["value"] != 1
            or type(active.get("raw_value")) is not int or active["raw_value"] != 1):
        return None, "An active CRTC could not be verified."
    timing = parse_timing(crtc.get("mode"))
    return timing, ("Configured CRTC timing; not a measurement of the wire signal."
                    if timing else "The current CRTC timing was missing or invalid.")


def apply_signal_data(snapshot, data, identities):
    """Parse a single observation; caller brackets it with sysfs state reads."""
    result = []
    for connector in snapshot.connectors:
        details = unavailable("No unique DRM device and connector ID could be matched.")
        identity = identities.get(connector.name)
        if connector.status == "disconnected" or connector.enabled == "disabled":
            details = unavailable("Linux reports this output as inactive; retained settings are not an active signal.", "inactive")
        elif connector.status != "connected" or connector.enabled != "enabled":
            details = unavailable("Linux connection or enablement is unknown.")
        elif identity is not None and isinstance(data, dict):
            card, identifier = identity
            device = data.get("/dev/dri/" + card)
            raw = unique_id(device.get("connectors"), identifier) if isinstance(device, dict) else None
            # Reject ambiguous sysfs mappings too, even within the same card.
            if raw is not None and list(identities.values()).count(identity) == 1:
                if type(raw.get("status")) is not int or raw["status"] != 1:
                    details = unavailable("DRM and sysfs disagree about the connection; collect again.", "inconsistent")
                else:
                    values = unavailable_properties("Not exposed by this backend.")
                    values.update({key: parse_property(raw.get("properties"), key) for key in PROPERTIES})
                    timing, reason = current_timing(device, raw)
                    timing_state = "reported" if timing else "unavailable"
                    observed = connector.current_mode
                    if timing and observed and observed.state in {"reported", "listed"} and observed.mode:
                        mode = observed.mode
                        if ((timing.width, timing.height) != (mode.width, mode.height)
                                or abs(timing.nominal_refresh_hz - mode.refresh_hz) > 0.1):
                            timing, timing_state = None, "inconsistent"
                            reason = "DRM timing and desktop mode disagree; collect again."
                    modes = raw.get("modes")
                    parsed = [parse_timing(item) for item in modes] if isinstance(modes, list) else []
                    valid = tuple(dict.fromkeys(t for t in parsed if t is not None))
                    invalid = sum(t is None for t in parsed)
                    details = SignalDetails("observed", SOURCE,
                        "Driver properties and configured timings; downstream projection is unverified.", values,
                        timing, timing_state, reason, valid,
                        ("partial" if invalid else "reported") if isinstance(modes, list) else "unavailable", invalid)
        result.append(replace(connector, signal=details))
    snapshot.connectors = result
    return snapshot


def read_identities(snapshot, root):
    identities = {}
    for connector in snapshot.connectors:
        match = re.fullmatch(r"(card[0-9]+)-[A-Za-z0-9-]+", connector.name)
        if not match:
            continue
        path = root / connector.name
        try:
            identifier = (path / "connector_id").read_text(encoding="ascii").strip()
            status = (path / "status").read_text(encoding="ascii").strip()
            enabled = (path / "enabled").read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            continue
        if (re.fullmatch(r"[0-9]{1,10}", identifier) and 0 < int(identifier) < 2**32
                and status == connector.status and enabled == connector.enabled):
            identities[connector.name] = (match[1], int(identifier))
    return identities


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def query_signal():
    executable = shutil.which("drm_info")
    if executable is None:
        return None, "Optional drm_info is not installed; basic diagnostics remain available."
    try:
        result = subprocess.run([executable, "-j"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        return None, "drm_info did not respond within 5 seconds."
    except OSError:
        return None, "drm_info could not be started."
    if result.returncode != 0:
        return None, "DRM information is inaccessible in this session; no privilege escalation was attempted."
    if len(result.stdout) > MAX_JSON_BYTES:
        return None, "drm_info output exceeded the supported size."
    try:
        data = json.loads(result.stdout, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        return None, "drm_info returned invalid or ambiguous JSON."
    if not isinstance(data, dict):
        return None, "drm_info returned an unsupported JSON structure."
    return data, None


def add_signal_details(snapshot, *, drm_root=Path("/sys/class/drm")):
    if not snapshot.connectors:
        return snapshot
    if snapshot.system != "Linux":
        reason = "Signal diagnostics require Linux DRM."
        snapshot.connectors = [replace(c, signal=unavailable(reason)) for c in snapshot.connectors]
        return snapshot
    before = read_identities(snapshot, drm_root)
    data, error = query_signal()
    if error:
        snapshot.connectors = [replace(c, signal=unavailable(error)) for c in snapshot.connectors]
        return snapshot
    after = read_identities(snapshot, drm_root)
    apply_signal_data(snapshot, data, before)
    snapshot.connectors = [replace(c, signal=unavailable(
        "Connector identity or state changed during collection; collect again.", "inconsistent"))
        if c.name in before and before.get(c.name) != after.get(c.name) else c
        for c in snapshot.connectors]
    return snapshot


def signal_lines(details):
    """Compact human-readable view. JSON retains complete timing alternatives."""
    if details.state != "observed":
        return [f"Signal details [{details.state}; {details.source}]: {details.reason}"]
    lines = [f"Signal details ({details.source}): driver settings, not measurements on the cable."]
    for key, prop in details.properties.items():
        if prop.state == "reported":
            value = str(prop.value).lower() if type(prop.value) is bool else str(prop.value)
            lines.append(f"{key} [{prop.meaning}]: {value}. {prop.note}")
    missing = [key for key, prop in details.properties.items() if prop.state != "reported"]
    if missing:
        lines.append("Unavailable or invalid: " + ", ".join(missing) + ".")
    timing = details.current_timing
    if timing:
        lines.append(f"Configured timing: {timing.width} x {timing.height}, {timing.pixel_clock_khz} kHz pixel clock; "
                     f"H {timing.hsync_start}/{timing.hsync_end}/{timing.htotal}, "
                     f"V {timing.vsync_start}/{timing.vsync_end}/{timing.vtotal}, flags {timing.flags}.")
    else:
        lines.append(f"Current timing [{details.current_timing_state}]: {details.current_timing_reason}")
    lines.append(f"Listed detailed timings [{details.listed_timings_state}]: {len(details.listed_timings)}; "
                 f"invalid entries omitted: {details.invalid_listed_timings}. Full details in doctor --json.")
    return lines
