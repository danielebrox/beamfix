"""Explicit automatic-backend selection; never send writes to a fallback desktop."""

from .gnome_fix import GNOMEActivationPlan, GNOMEBackend
from .kde_fix import ActivationPlan, KDEBackend, Unavailable
from .kde_modes import ModePlan, plan_modes


def prepare_modes(snapshot, target):
    backend = backend_for(snapshot)
    if isinstance(backend, KDEBackend):
        from .collect import collect
        return plan_modes(collect(), target, backend.query())
    raise Unavailable("Automatic mode trials are currently available on KDE Wayland only; use manual mode checks on GNOME.")


def backend_for(snapshot):
    desktops = set(snapshot.desktop.upper().split(":"))
    if snapshot.system != "Linux" or snapshot.session != "wayland":
        raise Unavailable("Automatic activation requires a supported Linux Wayland session.")
    supported = desktops & {"KDE", "GNOME"}
    if supported == {"KDE"}:
        return KDEBackend()
    if supported == {"GNOME"}:
        return GNOMEBackend()
    raise Unavailable("This desktop has no unambiguous automatic activation backend; use manual checks.")


def decode_plan(payload):
    if not isinstance(payload, dict):
        raise Unavailable("Invalid automatic activation plan.")
    kind = payload.get("backend")
    action = payload.get("action", "activation")
    if action == "mode" and kind == "kde":
        return ModePlan(**payload)
    if action != "activation":
        raise Unavailable("Unknown automatic display action.")
    if kind == "kde":
        return ActivationPlan(**payload)
    if kind == "gnome":
        return GNOMEActivationPlan(**payload)
    raise Unavailable("Unknown automatic activation backend.")
