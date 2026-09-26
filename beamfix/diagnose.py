"""Small, deterministic rules with evidence-backed wording."""

from .models import Finding, Snapshot


def diagnose(snapshot: Snapshot) -> list[Finding]:
    findings: list[Finding] = []
    if snapshot.errors:
        findings.append(Finding(
            "incomplete_observation", "warning", "Data collection is incomplete.",
            "Review the errors; try again in the local Linux session with the display connected.",
        ))
    if snapshot.session not in {"wayland", "x11"}:
        findings.append(Finding(
            "graphical_session_unconfirmed", "info", "Graphical session not confirmed.",
            "For future fixes, run BeamFix from a terminal in the affected desktop session.",
        ))
    external = [c for c in snapshot.connectors if c.kind == "external"]
    if external and all(c.status == "disconnected" for c in external):
        findings.append(Finding(
            "no_external_connected", "warning", "Linux reports no external displays connected to the observed ports.",
            "If you expect a projector, check its power, selected input, cable and adapter. These data do not establish the cause.",
        ))
    for connector in snapshot.connectors:
        if connector.status == "unknown":
            findings.append(Finding(
                "connection_unknown", "warning", "The connection state cannot be determined.",
                "Try again after reconnecting the display; an unknown state does not mean the cable is faulty.", connector.name,
            ))
        if connector.status != "connected":
            continue
        if connector.enabled == "disabled":
            findings.append(Finding(
                "connected_disabled", "info" if connector.kind == "internal" else "warning",
                "The connector is connected but reported as disabled by Linux.",
                "This may be intentional. If you want to use this screen, check that it is enabled in Display settings.", connector.name,
            ))
        if connector.modes == ():
            findings.append(Finding(
                "connected_no_modes", "warning", "The connector is connected with no video modes listed.",
                "Check the connection and run diagnostics again; this may involve the driver, display detection or adapter.", connector.name,
            ))
    return findings
