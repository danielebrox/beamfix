"""GNOME mode trials with a stable layout and temporary, verified D-Bus writes."""

import copy
from dataclasses import dataclass

from .collect import collect
from .gnome_fix import GNOMEBackend, integer, logical_size, require, validated_configuration
from .kde_fix import Unavailable
from .mode_trials import MAX_MODE_TRIALS, mode_rank, overlaps


@dataclass(frozen=True)
class GNOMEModePlan:
    connector: str
    output: str
    before: dict
    mode_id: str
    backend: str = "gnome"
    action: str = "mode"

    @property
    def expected(self):
        state = copy.deepcopy(self.before)
        for item in state["logical"]:
            if item["output"] == self.output:
                item["mode"] = self.mode_id
        return state

    @property
    def description(self):
        mode = self.before["monitors"][self.output]["modes"][self.mode_id]
        target = next(item for item in self.before["logical"] if item["output"] == self.output)
        return (f"Try {mode['width']} x {mode['height']} @ {mode['hz']:.2f} Hz on {self.output}, "
                f"keeping scale {target['scale']:g} and position ({target['x']}, {target['y']}). "
                "The change is temporary for this session; no display profile is saved.")


def valid_layout(state):
    """Require exact, bounded, non-overlapping rectangles joined by edges."""
    rectangles = []
    for item in state["logical"]:
        width, height = logical_size(state, item)
        require(integer(item["x"] + width) and integer(item["y"] + height),
                "The proposed desktop exceeds supported coordinates.")
        rectangles.append((item["x"], item["y"], width, height))
    for i, a in enumerate(rectangles):
        require(not any(overlaps(a, b) for b in rectangles[i + 1:]),
                "GNOME mode trials require non-overlapping screens.")

    def adjacent(a, b):
        return (((a[0] + a[2] == b[0] or b[0] + b[2] == a[0])
                 and max(a[1], b[1]) < min(a[1] + a[3], b[1] + b[3]))
                or ((a[1] + a[3] == b[1] or b[1] + b[3] == a[1])
                    and max(a[0], b[0]) < min(a[0] + a[2], b[0] + b[2])))

    visited, pending = {0}, [0]
    while pending:
        current = pending.pop()
        for other in range(len(rectangles)):
            if other not in visited and adjacent(rectangles[current], rectangles[other]):
                visited.add(other)
                pending.append(other)
    require(len(visited) == len(rectangles),
            "GNOME mode trials must preserve a connected desktop without gaps between screens.")


def plan_modes(snapshot, target, reply):
    name, state = validated_configuration(snapshot, target, reply, enabled=True)
    valid_layout(state)
    logical = next(item for item in state["logical"] if item["output"] == name)
    modes = state["monitors"][name]["modes"]
    current = modes[logical["mode"]]
    seen = {(current["width"], current["height"], current["hz"])}
    candidates = []
    ordered = sorted(modes.items(), key=lambda item: mode_rank(
        item[1]["width"], item[1]["height"], item[1]["hz"], item[0]))
    for mode_id, mode in ordered:
        signature = mode["width"], mode["height"], mode["hz"]
        if (signature in seen or mode["interlaced"] or mode["rate_mode"] != "fixed"
                or logical["scale"] not in mode["scales"]):
            continue
        plan = GNOMEModePlan(target, name, state, mode_id)
        try:
            valid_layout(plan.expected)
        except Unavailable:
            continue
        seen.add(signature)
        candidates.append(plan)
        if len(candidates) == MAX_MODE_TRIALS:
            break
    require(candidates, "No distinct GNOME modes can be tried at the current scale and screen positions; use Display settings.")
    return tuple(candidates)


class GNOMEModeBackend(GNOMEBackend):
    def __init__(self, mode_id=None):
        self.mode_id = mode_id

    def prepare_modes(self, target):
        snapshot = collect()
        require(snapshot.system == "Linux" and snapshot.session == "wayland"
                and "GNOME" in snapshot.desktop.upper().split(":"),
                "This backend requires a GNOME Wayland session.")
        self.allowed()
        return plan_modes(snapshot, target, self.query())

    def prepare(self, target):
        for plan in self.prepare_modes(target):
            if plan.mode_id == self.mode_id:
                return plan
        raise Unavailable("The previewed GNOME mode is no longer an eligible trial.")

    def set_mode(self, plan, forward):
        self.apply_change(plan, forward)
