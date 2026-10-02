"""GNOME/Mutter activation via its typed DisplayConfig D-Bus interface.

busctl supplies structured JSON; no shell or GVariant text evaluation is used.
Only temporary configurations are applied. The independent worker owns undo.
"""

import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass

from .collect import collect
from .kde_fix import Unavailable


SERVICE = "org.gnome.Mutter.DisplayConfig"
OBJECT = "/org/gnome/Mutter/DisplayConfig"
STATE_SIGNATURE = "ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv}"
APPLY_SIGNATURE = "uua(iiduba(ssa{sv}))a{sv}"


def port_key(name):
    port = re.sub(r"^card\d+-", "", name)
    # Mutter's native connector table names DRM HDMIA "HDMI", whereas sysfs
    # uses "HDMI-A". Normalize this documented spelling only, on both sides;
    # plan_activation still requires a bijection, including across GPU cards.
    return re.sub(r"^HDMI-A-(\d+)$", r"HDMI-\1", port)


def require(condition, message="GNOME returned incomplete or unsupported display settings."):
    if not condition:
        raise Unavailable(message)


def integer(value, low=0, high=2**31 - 1):
    return type(value) is int and low <= value <= high


def number(value, low=0, high=100_000):
    return type(value) in (int, float) and low < value <= high and math.isfinite(value)


def sequence(value, length):
    return isinstance(value, list) and len(value) == length


def property_value(properties, name, signature, default=None):
    require(isinstance(properties, dict))
    if name not in properties:
        return default
    value = properties[name]
    require(isinstance(value, dict) and value.get("type") == signature and "data" in value)
    data = value["data"]
    if signature == "b":
        require(type(data) is bool)
    elif signature == "u":
        require(integer(data, high=2**32 - 1))
    elif signature == "s":
        require(isinstance(data, str))
    return data


def monitor_identity(spec):
    require(sequence(spec, 4) and all(isinstance(part, str) for part in spec))
    require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", spec[0]) is not None)
    # Retain only a comparison digest in the private plan, never raw serials or
    # product names. Unlike a connector alone, this also catches many swaps.
    return hashlib.sha256(json.dumps(spec, ensure_ascii=True).encode()).hexdigest()


def configuration(reply):
    """Return (fresh serial, canonical state), excluding volatile current flags."""
    require(isinstance(reply, dict) and reply.get("type") == STATE_SIGNATURE)
    data = reply.get("data")
    require(sequence(data, 4))
    serial, physical, logical, props = data
    require(integer(serial, high=2**32 - 1) and isinstance(physical, list) and physical
            and isinstance(logical, list) and logical)
    layout_mode = property_value(props, "layout-mode", "u", 1)
    require(layout_mode in (1, 2))
    changing_layout = property_value(props, "supports-changing-layout-mode", "b", False)
    global_scale = property_value(props, "global-scale-required", "b", False)
    require(layout_mode == 1 or changing_layout,
            "GNOME does not expose a restorable physical layout mode.")
    monitors, current = {}, {}
    for entry in physical:
        require(sequence(entry, 3))
        spec, raw_modes, properties = entry
        identity = monitor_identity(spec)
        name = spec[0]
        require(name not in monitors and isinstance(raw_modes, list) and raw_modes)
        require(not property_value(properties, "is-for-lease", "b", False),
                "Monitors reserved for another application require manual configuration.")
        modes, active_ids = {}, []
        for raw_mode in raw_modes:
            require(sequence(raw_mode, 7))
            identifier, width, height, hz, preferred_scale, scales, mode_props = raw_mode
            require(isinstance(identifier, str) and identifier and "\0" not in identifier and identifier not in modes
                    and integer(width, 1) and integer(height, 1) and number(hz)
                    and number(preferred_scale, high=100) and isinstance(scales, list) and scales
                    and all(number(s, high=100) for s in scales) and preferred_scale in scales)
            if property_value(mode_props, "is-current", "b", False):
                active_ids.append(identifier)
            rate_mode = property_value(mode_props, "refresh-rate-mode", "s", "fixed")
            require(rate_mode in ("fixed", "variable"))
            modes[identifier] = {"width": width, "height": height, "hz": hz,
                                 "preferred_scale": preferred_scale, "scales": sorted(scales),
                                 "preferred": property_value(mode_props, "is-preferred", "b", False),
                                 "interlaced": property_value(mode_props, "is-interlaced", "b", False),
                                 "rate_mode": rate_mode}
        require(len(active_ids) <= 1, "GNOME reports more than one current mode for an output.")
        current[name] = active_ids[0] if active_ids else None
        monitor = {"identity": identity, "modes": modes,
                   "builtin": property_value(properties, "is-builtin", "b", False),
                   "settings": {}}
        for source, destination, signature in (("is-underscanning", "underscanning", "b"),
                                                ("color-mode", "color-mode", "u"),
                                                ("rgb-range", "rgb-range", "u")):
            if source in properties:
                monitor["settings"][destination] = property_value(properties, source, signature)
        require(monitor["settings"].get("color-mode", 0) in (0, 1, 2)
                and monitor["settings"].get("rgb-range", 1) in (1, 2, 3),
                "GNOME color or RGB settings cannot be preserved reliably.")
        monitors[name] = monitor
    layouts, assigned = [], set()
    for entry in logical:
        require(sequence(entry, 7))
        x, y, scale, transform, primary, specs, properties = entry
        require(integer(x) and integer(y) and number(scale, high=100) and integer(transform, 0, 7)
                and type(primary) is bool and sequence(specs, 1) and properties == {},
                "GNOME cloning, unknown logical settings or invalid layout require manual configuration.")
        identity = monitor_identity(specs[0])
        name = specs[0][0]
        require(name in monitors and name not in assigned and monitors[name]["identity"] == identity)
        assigned.add(name)
        mode = current[name]
        require(mode is not None and scale in monitors[name]["modes"][mode]["scales"],
                "GNOME's current mode and logical scale cannot be verified.")
        layouts.append({"output": name, "x": x, "y": y, "scale": scale,
                        "transform": transform, "primary": primary, "mode": mode})
    require(sum(item["primary"] for item in layouts) == 1,
            "GNOME must report exactly one primary screen.")
    require(all(current[name] is None for name in monitors if name not in assigned),
            "GNOME reports a current mode on an output outside the active layout.")
    require(not global_scale or len({item["scale"] for item in layouts}) == 1)
    state = {"monitors": monitors, "logical": sorted(layouts, key=lambda item: item["output"]),
             "layout_mode": layout_mode, "changing_layout": changing_layout, "global_scale": global_scale}
    # Reject sizes requiring rounding: we must predict the layout exactly.
    for item in layouts:
        logical_size(state, item)
    return serial, state


def logical_size(state, item):
    mode = state["monitors"][item["output"]]["modes"][item["mode"]]
    width, height = mode["width"], mode["height"]
    if item["transform"] % 2:
        width, height = height, width
    divisor = item["scale"] if state["layout_mode"] == 1 else 1
    width, height = width / divisor, height / divisor
    require(width.is_integer() and height.is_integer() and width > 0 and height > 0,
            "The scaled GNOME layout cannot be reproduced exactly; use Display settings.")
    return int(width), int(height)


@dataclass(frozen=True)
class GNOMEActivationPlan:
    connector: str
    output: str
    before: dict
    added: dict
    backend: str = "gnome"

    @property
    def expected(self):
        state = copy.deepcopy(self.before)
        state["logical"] = sorted(state["logical"] + [copy.deepcopy(self.added)], key=lambda item: item["output"])
        return state

    @property
    def description(self):
        mode = self.before["monitors"][self.output]["modes"][self.added["mode"]]
        return (f"Enable {self.output} using GNOME's preferred mode: "
                f"{mode['width']} x {mode['height']} @ {mode['hz']:.2f} Hz, scale {self.added['scale']:g}. "
                f"Extend the desktop to the right at ({self.added['x']}, {self.added['y']}). "
                "Keep other screens and the primary screen unchanged. This does not set up mirroring. "
                "The change is temporary for this session; no display profile is saved.")


def plan_activation(snapshot, target, reply):
    require(snapshot.system == "Linux" and snapshot.session == "wayland"
            and "GNOME" in snapshot.desktop.upper().split(":"),
            "This backend requires a GNOME Wayland session.")
    require(not snapshot.errors, "Linux observations are incomplete; read them again before trying a fix.")
    matches = [c for c in snapshot.connectors if c.name == target]
    require(len(matches) == 1, "Select one identifiable external output first.")
    target_connector = matches[0]
    require(target_connector.kind == "external" and target_connector.status == "connected"
            and target_connector.enabled == "disabled" and bool(target_connector.modes),
            "This fix requires a connected, disabled external output with readable modes.")
    _, state = configuration(reply)
    by_port = {}
    for output in state["monitors"]:
        key = port_key(output)
        require(key not in by_port, "GNOME connector names are ambiguous after native HDMI name matching.")
        by_port[key] = output
    name = by_port.get(port_key(target))
    active = {item["output"] for item in state["logical"]}
    require(name in state["monitors"] and name not in active and not state["monitors"][name]["builtin"],
            "GNOME and Linux do not agree on the selected external output.")
    # Check the complete connected inventory, including inactive monitors. Never
    # guess aliases beyond Mutter's native HDMI spelling, or select another GPU.
    for output in state["monitors"]:
        matches = [c for c in snapshot.connectors if port_key(c.name) == port_key(output)]
        require(len(matches) == 1 and matches[0].status == "connected"
                and matches[0].enabled == ("enabled" if output in active else "disabled"),
                "GNOME outputs cannot be matched uniquely to the Linux activation state.")
    require(all(port_key(c.name) in by_port
                for c in snapshot.connectors if c.status == "connected"),
            "GNOME's connected output inventory differs from Linux.")
    modes = state["monitors"][name]["modes"]
    preferred = [identifier for identifier, mode in modes.items() if mode["preferred"]]
    require(len(preferred) == 1, "GNOME must advertise one unambiguous preferred mode for this output.")
    mode_id = preferred[0]
    mode = modes[mode_id]
    require(not mode["interlaced"] and mode["rate_mode"] == "fixed",
            "This first GNOME attempt requires a non-interlaced fixed-refresh preferred mode.")
    scale = state["logical"][0]["scale"] if state["global_scale"] else mode["preferred_scale"]
    require(scale in mode["scales"], "The output does not support the required GNOME scale.")
    edge = max(state["logical"], key=lambda item: item["x"] + logical_size(state, item)[0])
    x, y = edge["x"] + logical_size(state, edge)[0], edge["y"]
    added = {"output": name, "x": x, "y": y, "scale": scale,
             "transform": 0, "primary": False, "mode": mode_id}
    width, height = logical_size(state, added)
    require(integer(x + width) and integer(y + height), "The proposed desktop exceeds supported coordinates.")
    return GNOMEActivationPlan(target, name, state, added)


def apply_arguments(serial, method, state):
    """Encode the documented busctl signature as individual argv tokens."""
    require(method in (0, 1), "Only verification and temporary changes are supported.")
    arguments = [APPLY_SIGNATURE, str(serial), str(method), str(len(state["logical"]))]
    for item in state["logical"]:
        arguments.extend([str(item["x"]), str(item["y"]), str(item["scale"]), str(item["transform"]),
                          "true" if item["primary"] else "false", "1", item["output"], item["mode"]])
        properties = state["monitors"][item["output"]]["settings"]
        arguments.append(str(len(properties)))
        for name, value in sorted(properties.items()):
            signature = "b" if name == "underscanning" else "u"
            arguments.extend([name, signature, ("true" if value else "false") if signature == "b" else str(value)])
    if state["changing_layout"]:
        arguments.extend(["1", "layout-mode", "u", str(state["layout_mode"])])
    else:
        arguments.append("0")
    return arguments


class GNOMEBackend:
    def _request(self, operation, member, arguments=()):
        executable = shutil.which("busctl")
        require(executable is not None, "busctl is not installed; manual troubleshooting remains available.")
        command = [executable, "--user", "--json=short", "--timeout=4", "--auto-start=no",
                   "--allow-interactive-authorization=no", "--", operation, SERVICE, OBJECT, SERVICE, member, *arguments]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, encoding="utf-8", timeout=5, check=False)
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
            raise Unavailable("GNOME display configuration is unavailable or timed out.") from error
        require(result.returncode == 0, "GNOME rejected the display request or its DisplayConfig service is unavailable.")
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except (ValueError, RecursionError) as error:
            raise Unavailable("busctl returned unreadable GNOME display data.") from error

    def allowed(self):
        reply = self._request("get-property", "ApplyMonitorsConfigAllowed")
        require(isinstance(reply, dict) and reply.get("type") == "b" and reply.get("data") is True,
                "GNOME does not allow display configuration changes in this session.")

    def query(self):
        reply = self._request("call", "GetCurrentState")
        configuration(reply)  # Validate before use, including by the planner.
        return reply

    def prepare(self, target):
        snapshot = collect()
        require(snapshot.system == "Linux" and snapshot.session == "wayland"
                and "GNOME" in snapshot.desktop.upper().split(":"),
                "This backend requires a GNOME Wayland session.")
        self.allowed()
        return plan_activation(snapshot, target, self.query())

    def state(self):
        return configuration(self.query())[1]

    def set_enabled(self, plan, enabled):
        self.allowed()
        serial, current = configuration(self.query())
        require(current == (plan.before if enabled else plan.expected),
                "GNOME settings changed before the operation; stale settings were not applied.")
        desired = plan.expected if enabled else plan.before
        # Verification does not change the serial. Any concurrent hot-plug or
        # change makes the following apply fail Mutter's own serial check.
        self._request("call", "ApplyMonitorsConfig", apply_arguments(serial, 0, desired))
        self._request("call", "ApplyMonitorsConfig", apply_arguments(serial, 1, desired))
