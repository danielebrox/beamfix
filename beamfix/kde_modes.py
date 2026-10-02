"""Bounded KDE mode trials; every candidate restores to the same baseline."""

import copy
import re
import shutil
import subprocess
from dataclasses import dataclass

from .collect import collect
from .kde_fix import KDEBackend, Unavailable, validated_configuration


MAX_MODE_TRIALS = 5


def mode_label(mode):
    size = mode["size"]
    return f"{size['width']} x {size['height']} @ {mode['refreshRate']:.2f} Hz"


@dataclass(frozen=True)
class ModePlan:
    connector: str
    output: str
    before: dict
    mode_id: str
    backend: str = "kde"
    action: str = "mode"

    @property
    def expected(self):
        after = copy.deepcopy(self.before)
        after[self.output]["currentModeId"] = self.mode_id
        return after

    @property
    def description(self):
        return f"Try {mode_label(self.before[self.output]['modes'][self.mode_id])} on {self.output}."


def rectangle(output, mode_id):
    size = output["modes"][mode_id]["size"]
    width, height = size["width"], size["height"]
    if output["rotation"] in (2, 8, 32, 128):
        width, height = height, width
    width, height = width / output["scale"], height / output["scale"]
    # Avoid depending on compositor-specific rounding of fractional geometry.
    if not width.is_integer() or not height.is_integer():
        raise Unavailable("Mode trials require exact logical screen dimensions at the current scale.")
    return output["pos"]["x"], output["pos"]["y"], width, height


def overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def plan_modes(snapshot, target, data):
    name, before = validated_configuration(snapshot, target, data, enabled=True)
    output = before[name]
    current_id = output["currentModeId"]
    # The doctor CLI uses dots as syntax separators. Only exact safe mode IDs
    # can be applied AND undone; never fall back to a resolution string.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", current_id):
        raise Unavailable("The current KDE mode cannot be restored by its exact ID.")
    others = [rectangle(o, o["currentModeId"]) for n, o in before.items() if o["enabled"] and n != name]
    if any(overlaps(rectangle(output, current_id), other) for other in others):
        raise Unavailable("Mode trials require separate, non-overlapping screens.")
    current = output["modes"][current_id]
    seen = {(current["size"]["width"], current["size"]["height"], current["refreshRate"])}
    candidates = []
    # Prefer rates closest to 60 Hz, then larger resolutions up to 1080p.
    # This is a trial order, never a claim that a listed mode will work.
    ordered = sorted(output["modes"].items(), key=lambda item: (
        abs(item[1]["refreshRate"] - 60),
        item[1]["size"]["width"] > 1920 or item[1]["size"]["height"] > 1080,
        -item[1]["size"]["width"] * item[1]["size"]["height"], item[0]))
    for mode_id, mode in ordered:
        signature = (mode["size"]["width"], mode["size"]["height"], mode["refreshRate"])
        if signature in seen or not re.fullmatch(r"[A-Za-z0-9_-]+", mode_id):
            continue
        try:
            bounds = rectangle(output, mode_id)
        except Unavailable:
            continue
        if any(overlaps(bounds, other) for other in others):
            continue
        seen.add(signature)
        candidates.append(ModePlan(target, name, before, mode_id))
        if len(candidates) == MAX_MODE_TRIALS:
            break
    if not candidates:
        raise Unavailable("No distinct alternative modes can be tried while preserving this screen layout.")
    return tuple(candidates)


class KDEModeBackend(KDEBackend):
    def __init__(self, mode_id):
        self.mode_id = mode_id

    def prepare(self, target):
        plans = plan_modes(collect(), target, self.query())
        for plan in plans:
            if plan.mode_id == self.mode_id:
                return plan
        raise Unavailable("The previewed mode is no longer an eligible trial.")

    def set_mode(self, plan, forward):
        expected_start = plan.before if forward else plan.expected
        if self.state() != expected_start:
            raise Unavailable("The configuration changed before the mode command; check Display settings.")
        mode_id = plan.mode_id if forward else plan.before[plan.output]["currentModeId"]
        executable = shutil.which("kscreen-doctor")
        if executable is None:
            raise Unavailable("kscreen-doctor is no longer available.")
        if (not re.fullmatch(r"[A-Za-z0-9_-]+", mode_id)
                or mode_id not in plan.before[plan.output]["modes"]):
            raise Unavailable("The requested KDE mode ID is invalid.")
        try:
            result = subprocess.run([executable, f"output.{plan.output}.mode.{mode_id}"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Unavailable("KDE did not complete the mode change within five seconds.") from error
        if result.returncode != 0:
            raise Unavailable("KDE reported an error while changing the mode.")
