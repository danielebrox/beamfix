"""Conservative KDE activation plans. No writes happen while preparing a plan."""

import copy
import math
import re
import shutil
import subprocess
from dataclasses import dataclass

from .collect import collect
from .desktop import _query_kde, _video_mode


class Unavailable(Exception):
    """The observation does not support this narrowly scoped automatic action."""


# Capture layout and mode state separately from the public diagnostic model.
# Optional settings are included in the comparison, never changed or reported.
CONTROL_KEYS = (
    "id", "name", "connected", "enabled", "currentModeId", "pos", "scale",
    "rotation", "priority", "replicationSource", "clones", "followPreferredMode",
    "overscan", "vrrPolicy", "rgbRange", "hdrEnabled", "sdrBrightness",
    "wcgEnabled", "autoRotatePolicy", "colorProfileSource", "brightness",
    "colorPowerPreference", "dimming", "maxBitsPerColor",
)
REQUIRED = CONTROL_KEYS[:12]


def configuration(data):
    if not isinstance(data, dict) or not isinstance(data.get("outputs"), list) or not data["outputs"]:
        raise Unavailable("KDE did not provide a complete output configuration.")
    outputs = {}
    ids = set()
    for raw in data["outputs"]:
        if not isinstance(raw, dict) or any(k not in raw for k in REQUIRED):
            raise Unavailable("KDE output settings are incomplete; use Display settings.")
        name, identifier = raw["name"], raw["id"]
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name)
                or name == "activeOutput" or name in outputs
                or type(identifier) is not int or identifier < 0 or identifier in ids):
            raise Unavailable("KDE outputs cannot be identified without ambiguity.")
        ids.add(identifier)
        if any(type(raw[k]) is not bool for k in ("connected", "enabled", "followPreferredMode")):
            raise Unavailable("KDE output activation state is unreadable.")
        pos = raw["pos"]
        if (not isinstance(pos, dict) or any(type(pos.get(k)) is not int or pos[k] < 0 for k in ("x", "y"))
                or type(raw["scale"]) not in (int, float) or not 0 < raw["scale"] <= 100
                or not math.isfinite(raw["scale"]) or type(raw["rotation"]) is not int
                or raw["rotation"] not in (1, 2, 4, 8, 16, 32, 64, 128)
                or type(raw["priority"]) is not int or raw["priority"] < 0
                or type(raw["replicationSource"]) is not int
                or not isinstance(raw["clones"], list)
                or any(type(i) is not int for i in raw["clones"])):
            raise Unavailable("KDE layout settings are incomplete or invalid.")
        if not isinstance(raw.get("currentModeId"), str) or not isinstance(raw.get("modes"), list):
            raise Unavailable("KDE mode settings are unreadable.")
        modes = {}
        for mode in raw["modes"]:
            if (not isinstance(mode, dict) or not isinstance(mode.get("id"), str)
                    or not mode["id"] or mode["id"] in modes or _video_mode(mode) is None):
                raise Unavailable("KDE returned an ambiguous or invalid mode list.")
            modes[mode["id"]] = {k: copy.deepcopy(mode[k]) for k in ("size", "refreshRate")}
        item = {k: copy.deepcopy(raw[k]) for k in CONTROL_KEYS if k in raw}
        item["modes"] = modes
        outputs[name] = item
    return outputs


@dataclass(frozen=True)
class ActivationPlan:
    connector: str
    output: str
    before: dict
    backend: str = "kde"

    @property
    def expected(self):
        after = copy.deepcopy(self.before)
        after[self.output]["enabled"] = True
        after[self.output]["priority"] = 1 + sum(o["enabled"] for o in self.before.values())
        return after

    @property
    def description(self):
        output = self.before[self.output]
        mode = output["modes"][output["currentModeId"]]
        size = mode["size"]
        return (f"Enable {self.output} using its retained KDE mode: "
                f"{size['width']} x {size['height']} @ {mode['refreshRate']:.2f} Hz. "
                "Keep the existing screen layout and other active screens. "
                "This does not set up mirroring.")


def validated_configuration(snapshot, target, data, *, enabled):
    if snapshot.system != "Linux" or snapshot.session != "wayland" or "KDE" not in snapshot.desktop.upper().split(":"):
        raise Unavailable("This backend requires a KDE Wayland session.")
    if snapshot.errors:
        raise Unavailable("Linux observations are incomplete; read them again before trying a fix.")
    matches = [c for c in snapshot.connectors if c.name == target]
    if len(matches) != 1:
        raise Unavailable("Select one identifiable external output first.")
    connector = matches[0]
    if (connector.kind != "external" or connector.status != "connected"
            or connector.enabled != ("enabled" if enabled else "disabled") or not connector.modes):
        state = "enabled" if enabled else "disabled"
        raise Unavailable(f"This fix requires a connected, {state} external output with readable modes.")
    name = re.sub(r"^card\d+-", "", connector.name)
    if sum(re.sub(r"^card\d+-", "", c.name) == name for c in snapshot.connectors) != 1:
        raise Unavailable("This connector name occurs on more than one GPU.")
    before = configuration(data)
    output = before.get(name)
    if output is None or not output["connected"] or output["enabled"] != enabled:
        raise Unavailable("KDE and Linux do not agree on the selected output.")
    if (output["currentModeId"] not in output["modes"] or output["followPreferredMode"]
            or output["replicationSource"] or output["clones"]):
        raise Unavailable("A retained mode without automatic mode selection or cloning is required.")
    active = [o for o in before.values() if o["enabled"]]
    if (not any(o["name"] != name for o in active)
            or any(not o["connected"] or o["currentModeId"] not in o["modes"] for o in active)
            or sorted(o["priority"] for o in active) != list(range(1, len(active) + 1))
            or any(o["priority"] != 0 for o in before.values() if not o["enabled"])):
        raise Unavailable("Another active screen and a consistent KDE output order are required.")
    if any(o["clones"] or o["replicationSource"] or o["followPreferredMode"] for o in active):
        raise Unavailable("Automatic changes require active screens without cloning or automatic mode selection.")
    for other in active:
        drm = [c for c in snapshot.connectors if re.sub(r"^card\d+-", "", c.name) == other["name"]]
        if len(drm) != 1 or drm[0].status != "connected" or drm[0].enabled != "enabled":
            raise Unavailable("The other active screens cannot be verified against Linux.")
    return name, before


def plan_activation(snapshot, target, data):
    name, before = validated_configuration(snapshot, target, data, enabled=False)
    return ActivationPlan(target, name, before)


class KDEBackend:
    def query(self):
        data, error = _query_kde()
        if error:
            raise Unavailable(error)
        return data

    def prepare(self, target):
        return plan_activation(collect(), target, self.query())

    def state(self):
        return configuration(self.query())

    def set_enabled(self, plan, enabled):
        executable = shutil.which("kscreen-doctor")
        if executable is None:
            raise Unavailable("kscreen-doctor is no longer available.")
        arguments = [executable, f"output.{plan.output}.{'enable' if enabled else 'disable'}"]
        if enabled:
            arguments.append(f"output.{plan.output}.priority.{plan.expected[plan.output]['priority']}")
        try:
            result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Unavailable("KDE did not complete the output change within five seconds.") from error
        if result.returncode != 0:
            raise Unavailable("KDE reported an error while applying the output change.")
        # A zero status is NOT proof of success. The worker always reads back.
