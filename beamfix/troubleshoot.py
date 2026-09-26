"""Guided, read-only troubleshooting with explicit human visual verification."""

from collections.abc import Callable
from dataclasses import dataclass, field

from .collect import collect
from .models import Connector, Snapshot


@dataclass(frozen=True)
class Step:
    code: str
    title: str
    reason: str
    instruction: str


STEPS = {
    "input": Step(
        "input", "Check power and input",
        "Detection by the computer does not confirm which input the projector is displaying.",
        "Check that the projector is on and select the input for the connected cable "
        "(for example, HDMI 1 or HDMI 2).",
    ),
    "reconnect": Step(
        "reconnect", "Reconnect the projector",
        "Reconnecting lets us check whether Linux detects the display and its video modes.",
        "Disconnect and reconnect the projector cable, checking the connections "
        "on any adapter as well. Wait a few seconds.",
    ),
    "direct": Step(
        "direct", "Try without a dock or adapter",
        "A direct connection may help isolate a problem along the connection path.",
        "If you have a compatible connection, connect the projector directly "
        "to the computer. If this is not possible or it is already connected directly, skip this step.",
    ),
    "cable": Step(
        "cable", "Try another cable",
        "Comparing with another cable helps narrow down the problem; the current data do not prove a fault.",
        "If you have one available, try another compatible cable. Otherwise, skip this step.",
    ),
    "activate": Step(
        "activate", "Enable the output in Display settings",
        "Linux detects the selected display but reports its output as disabled.",
        "Open your desktop's Display settings, identify the projector and enable it. "
        "Keep the computer's screen on as well. Apply the change and use the desktop's confirmation prompt if offered.",
    ),
    "presentation": Step(
        "presentation", "Show the presentation on the projector",
        "You can see the desktop: the connection produces an image, but the content may be on the other screen.",
        "In your presentation settings, select the projector screen, "
        "or move the window to that screen and start the presentation.",
    ),
    "mirror": Step(
        "mirror", "Try screen mirroring",
        "Mirroring lets you check whether the expected content also appears on the projector.",
        "In Display settings, choose Duplicate or Mirror, if available, "
        "keeping the computer's screen active. Note the previous setting "
        "so you can restore it, and use the desktop's confirmation prompt if offered.",
    ),
    "mode": Step(
        "mode", "Try another mode offered by the desktop",
        "The output appears active, but BeamFix does not know the resolution and refresh rate currently in use.",
        "In the projector's Display settings, note the current mode and try "
        "another mode offered by the desktop. Keep the computer's screen "
        "active; if the result is worse, restore the previous mode. Skip if there are no alternatives.",
    ),
    "refresh": Step(
        "refresh", "Read the data again",
        "Display data are incomplete or unknown: there is not enough information to choose a fix.",
        "Check that you started BeamFix in the Linux session on the computer connected "
        "to the projector. Wait a few seconds and choose Done to read the data again.",
    ),
}


@dataclass
class Attempt:
    step: Step
    performed: bool
    before: str
    after: str | None = None
    observation: str | None = None


@dataclass
class Session:
    symptom: str = "no_signal"
    target: str | None = None
    snapshot: Snapshot | None = None
    attempts: list[Attempt] = field(default_factory=list)
    outcome: str = "interrupted"


SYMPTOMS = {
    "no_signal": "The projector shows No signal",
    "black": "The projected screen is black",
    "desktop": "I can see the desktop, but not the presentation",
}


def candidates(snapshot: Snapshot) -> list[Connector]:
    # An unclassified connector is not proof that no external display exists.
    return [c for c in snapshot.connectors if c.kind in {"external", "unknown"}]


def target_connector(snapshot: Snapshot, target: str | None) -> Connector | None:
    return next((c for c in candidates(snapshot) if c.name == target), None)


def next_step(snapshot: Snapshot, target: str | None, symptom: str, tried: set[str]) -> Step | None:
    """Choose one applicable test; never infer visual success or repeat a test."""
    connector = target_connector(snapshot, target)
    if not candidates(snapshot):
        codes = ["refresh"]
    elif connector is None:
        codes = ["input", "reconnect", "direct", "cable"]
    elif connector.status == "unknown":
        codes = ["refresh"]
    elif connector.status == "disconnected":
        codes = ["input", "reconnect", "direct", "cable"]
    elif connector.enabled == "unknown" or connector.modes is None:
        codes = ["refresh"]
    elif not connector.modes:
        codes = ["reconnect", "direct", "cable"]
    elif connector.enabled == "disabled":
        # Do not propose resolution/duplication changes for an inactive output.
        codes = ["activate", "reconnect", "direct", "cable"]
    elif symptom == "desktop":
        codes = ["presentation", "mirror"]
    else:
        codes = ["input", "mirror", "mode", "reconnect", "direct", "cable"]
    return next((STEPS[code] for code in codes if code not in tried), None)


def describe(snapshot: Snapshot, target: str | None) -> str:
    connector = target_connector(snapshot, target)
    if connector is None:
        return "Target display not identified."
    status = {"connected": "connected", "disconnected": "disconnected", "unknown": "connection unknown"}
    enabled = {"enabled": "output enabled", "disabled": "output disabled", "unknown": "output state unknown"}
    modes = "modes unreadable" if connector.modes is None else f"{len(connector.modes)} listed modes"
    return f"{connector.name!r}: {status[connector.status]}, {enabled[connector.enabled]}, {modes}."


class StopSession(Exception):
    pass


def choose(prompt: str, options: list[tuple[str, str]], read: Callable[[str], str], write: Callable[[str], None]) -> str:
    write(prompt)
    for index, (_, label) in enumerate(options, 1):
        write(f"  {index}. {label}")
    write("  0. Exit and show the summary")
    while True:
        value = read("> ").strip()
        if value == "0":
            raise StopSession
        if value.isascii() and value.isdecimal() and len(value) <= len(str(len(options))):
            index = int(value) - 1
            if 0 <= index < len(options):
                return options[index][0]
        write("Enter the number of one of the options.")


def select_target(snapshot: Snapshot, read: Callable[[str], str], write: Callable[[str], None]) -> str | None:
    ports = candidates(snapshot)
    if not ports:
        write("No external output can be identified from the available data.")
        return None
    options = [(c.name, describe(snapshot, c.name)) for c in ports]
    options.append(("", "I am not sure / the projector is not listed"))
    write("Output names do not reliably identify the device or physical cable.")
    return choose("Which output corresponds to the projector? You can compare it with Display settings.", options, read, write) or None


def insufficient(session: Session) -> bool:
    snapshot = session.snapshot
    if snapshot is None or snapshot.errors:
        return True
    connector = target_connector(snapshot, session.target)
    return connector is None or connector.status == "unknown" or (
        connector.status == "connected" and (connector.enabled == "unknown" or connector.modes is None)
    )


def summarize(session: Session, write: Callable[[str], None]) -> int:
    labels = {
        "resolved": "Expected image confirmed by the user.",
        "unresolved": "The problem remains: there are no more guided steps available.",
        "insufficient": "Insufficient data to continue with targeted diagnostics.",
        "interrupted": "Troubleshooting interrupted; resolution not confirmed.",
    }
    write("\nSummary — " + labels[session.outcome])
    for number, attempt in enumerate(session.attempts, 1):
        state = "performed" if attempt.performed else "skipped, not verified"
        write(f"{number}. {attempt.step.title}: {state}.")
        if attempt.performed:
            write("   Before: " + attempt.before)
            if attempt.after is not None:
                write("   After: " + attempt.after)
            write("   Visual result: " + (attempt.observation or "not confirmed"))
    if not session.attempts:
        write("No steps performed.")
    if session.snapshot is not None:
        write("Latest reading: " + describe(session.snapshot, session.target))
        if session.snapshot.errors:
            write("Some data are missing; run beamfix doctor for details.")
    if session.outcome != "resolved":
        write("Failed or skipped steps do not rule out a fault in the cable, adapter or projector.")
        write("For further investigation, keep this summary and the report from beamfix doctor --json.")
    write("BeamFix has not applied changes or saved reports automatically.")
    return 0 if session.outcome == "resolved" else (1 if session.outcome == "unresolved" else 2)


def run(
    *,
    snapshot_reader: Callable[[], Snapshot] | None = None,
    read: Callable[[str], str] | None = None,
    write: Callable[[str], None] | None = None,
) -> int:
    snapshot_reader = snapshot_reader or collect
    read = read or input
    write = write or print
    session = Session()
    write("BeamFix — guided troubleshooting: projector connected, image missing or unexpected")
    write("I will suggest one step at a time. You make any changes in your settings; "
          "BeamFix reads the data again and asks what you see. You can skip a step or exit with 0.")
    try:
        session.symptom = choose("What do you see on the projector?", list(SYMPTOMS.items()), read, write)
        session.snapshot = snapshot_reader()
        session.target = select_target(session.snapshot, read, write)
        while True:
            write("\nObserved state: " + describe(session.snapshot, session.target))
            tried = {a.step.code for a in session.attempts}
            step = next_step(session.snapshot, session.target, session.symptom, tried)
            if step is None:
                session.outcome = "insufficient" if insufficient(session) else "unresolved"
                break
            write("\nStep: " + step.title)
            write("Why: " + step.reason)
            write(step.instruction)
            action = choose("When you are ready:", [("done", "Done: read the state again"), ("skip", "Skip this step")], read, write)
            attempt = Attempt(step, action == "done", describe(session.snapshot, session.target))
            session.attempts.append(attempt)
            if action == "skip":
                continue
            previous = session.snapshot
            session.snapshot = snapshot_reader()
            # Hot-plug can change names. Never silently switch to another monitor.
            old_ports = {(c.name, c.status) for c in candidates(previous)}
            new_ports = {(c.name, c.status) for c in candidates(session.snapshot)}
            current_target = target_connector(session.snapshot, session.target)
            newly_connected = any(status == "connected" and (name, status) not in old_ports for name, status in new_ports)
            if (session.target is not None and target_connector(session.snapshot, session.target) is None) or (
                session.target is None and old_ports != new_ports
            ) or (
                newly_connected and current_target is not None and current_target.status != "connected"
            ):
                write("The connection list has changed: identify the projector again.")
                session.target = None
                session.target = select_target(session.snapshot, read, write)
            attempt.after = describe(session.snapshot, session.target)
            write("New reading: " + attempt.after)
            write("Linux state alone does not confirm that the image is visible.")
            observed = choose("What do you see now?", [
                ("resolved", "I can see the image I wanted to project"),
                *SYMPTOMS.items(),
                ("unverified", "I cannot verify the image"),
            ], read, write)
            attempt.observation = "expected image confirmed" if observed == "resolved" else (
                "cannot be verified" if observed == "unverified" else SYMPTOMS[observed]
            )
            if observed == "resolved":
                session.outcome = "resolved"
                break
            if observed == "unverified":
                session.outcome = "insufficient"
                break
            session.symptom = observed
    except (EOFError, KeyboardInterrupt, StopSession):
        write("\nClosing guided troubleshooting.")
    return summarize(session, write)
