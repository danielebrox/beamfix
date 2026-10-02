"""Guided troubleshooting with explicit human visual verification."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import sys

from . import __version__
from .desktop import collect_doctor as collect
from .models import Connector, Snapshot
from .terminal import Terminal


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
    automatic_result: str | None = None


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


def next_step(snapshot: Snapshot, target: str | None, symptom: str, tried: set[str], *, try_modes=False) -> Step | None:
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
        if try_modes:
            codes = ["input", "mode", "mirror", "reconnect", "direct", "cable"]
    step = next((STEPS[code] for code in codes if code not in tried), None)
    if step is not None and step.code == "mode" and connector is not None:
        observation = connector.current_mode
        if observation is not None and observation.state in {"listed", "reported"} and observation.mode is not None:
            mode = observation.mode
            current = f"{mode.width} x {mode.height} @ {mode.refresh_hz:.2f} Hz"
            return replace(step,
                reason=(f"KDE reports {current}, listed as available." if observation.state == "listed" else
                        f"Wayland reports {current}; the available mode list is not verified.")
                       + " This does not confirm a correct projected image.",
                instruction=f"In the projector's Display settings, check that the current mode is still {current} "
                "and note it so you can restore it. Try another mode offered by the desktop, keeping the "
                "computer's screen active. Use the desktop's confirmation prompt if offered; "
                "if the result is worse, restore the previous mode. Skip if there are no alternatives.",
            )
    return step


def describe(snapshot: Snapshot, target: str | None) -> str:
    connector = target_connector(snapshot, target)
    if connector is None:
        return "Target display not identified."
    status = {"connected": "connected", "disconnected": "disconnected", "unknown": "connection unknown"}
    enabled = {"enabled": "output enabled", "disabled": "output disabled", "unknown": "output state unknown"}
    modes = "modes unreadable" if connector.modes is None else f"{len(connector.modes)} listed modes"
    description = f"{connector.name!r}: {status[connector.status]}, {enabled[connector.enabled]}, {modes}."
    observation = connector.current_mode
    if observation is not None and observation.state in {"listed", "reported"} and observation.mode is not None:
        mode = observation.mode
        source = "listed by KDE" if observation.state == "listed" else "reported by Wayland; mode list unverified"
        return description + f" Current mode: {mode.width} x {mode.height} @ {mode.refresh_hz:.2f} Hz ({source})."
    if observation is not None and observation.state == "inactive":
        return description + " Current mode: inactive."
    reason = observation.reason if observation is not None else "No current-mode observation is available."
    return description + " Current mode: unverified. " + reason


class StopSession(Exception):
    pass


def choose(prompt: str, options: list[tuple[str, str]], read: Callable[[str], str], ui: Terminal) -> str:
    ui.section(prompt)
    for index, (_, label) in enumerate(options, 1):
        ui.option(index, label)
    ui.option(0, "Exit and show the summary")
    while True:
        value = read(ui.prompt()).strip()
        if value == "0":
            raise StopSession
        if value.isascii() and value.isdecimal() and len(value) <= len(str(len(options))):
            index = int(value) - 1
            if 0 <= index < len(options):
                return options[index][0]
        ui.status("TRY AGAIN", "Enter the number of one of the options.", "warning")


def select_target(snapshot: Snapshot, read: Callable[[str], str], ui: Terminal) -> str | None:
    write = ui.text
    ports = candidates(snapshot)
    if not ports:
        write("No external output can be identified from the available data.")
        return None
    options = [(c.name, describe(snapshot, c.name)) for c in ports]
    options.append(("", "I am not sure / the projector is not listed"))
    write("Output names do not reliably identify the device or physical cable.")
    return choose("Which output corresponds to the projector? You can compare it with Display settings.", options, read, ui) or None


def insufficient(session: Session) -> bool:
    snapshot = session.snapshot
    if snapshot is None or snapshot.errors:
        return True
    connector = target_connector(snapshot, session.target)
    return connector is None or connector.status == "unknown" or (
        connector.status == "connected" and (connector.enabled == "unknown" or connector.modes is None)
    )


def summarize(session: Session, ui: Terminal) -> int:
    write = ui.text
    labels = {
        "resolved": "Expected image confirmed by the user.",
        "unresolved": "The problem remains: there are no more guided steps available.",
        "insufficient": "Insufficient data to continue with targeted diagnostics.",
        "not_confirmed": "The automatic mode sequence ended without visual confirmation.",
        "interrupted": "Troubleshooting interrupted; resolution not confirmed.",
    }
    ui.section("SUMMARY")
    tone = "ok" if session.outcome == "resolved" else "warning"
    ui.status("CONFIRMED" if session.outcome == "resolved" else "NOT CONFIRMED", labels[session.outcome], tone)
    ui.blank()
    for number, attempt in enumerate(session.attempts, 1):
        state = "performed" if attempt.performed else "skipped, not verified"
        if attempt.automatic_result is not None:
            state = "automatic attempt" if attempt.performed else "not applied"
        ui.text(f"{number}. {attempt.step.title}: {state}.", "title")
        if attempt.automatic_result is not None:
            write("   Automatic attempt: " + attempt.automatic_result)
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
    if any(a.automatic_result is not None for a in session.attempts):
        write("Automatic attempts and recovery results are listed above. No report was saved.")
    else:
        write("BeamFix has not applied changes or saved reports automatically.")
    return 0 if session.outcome == "resolved" else (1 if session.outcome == "unresolved" else 2)


def offer_activation(target, read, ui, *, snapshot=None):
    from .automatic import confirm_in_terminal, run_activation
    from .fix_backends import backend_for
    from .kde_fix import Unavailable

    if not sys.stdin.isatty():
        ui.status("MANUAL", "Automatic activation requires an interactive terminal.", "warning")
        return "manual"
    try:
        plan = backend_for(snapshot or collect()).prepare(target)
    except Unavailable as error:
        ui.status("MANUAL", str(error), "warning")
        return "manual"
    ui.section("AUTOMATIC ACTIVATION PREVIEW")
    ui.text(plan.description)
    ui.text("After activation, confirm the expected image within 15 seconds. Otherwise BeamFix "
            "will try to restore the disabled state. Keep cables and Display settings unchanged during the attempt.")
    action = choose("Try this automatic activation?", [
        ("try", "Try activation with automatic undo"),
        ("manual", "Use the manual instructions instead"),
        ("skip", "Skip activation"),
    ], read, ui)
    if action != "try":
        return action
    ui.text("Checking the configuration and starting the protected attempt...")
    return run_activation(plan, lambda seconds: confirm_in_terminal(ui, seconds))


def offer_modes(target, read, ui, *, snapshot):
    from .automatic import confirm_mode_in_terminal, run_mode_sequence
    from .fix_backends import prepare_modes
    from .kde_fix import Unavailable

    if not sys.stdin.isatty():
        ui.status("MANUAL", "Automatic mode trials require an interactive terminal.", "warning")
        return "manual"
    try:
        plans = prepare_modes(snapshot, target)
    except Unavailable as error:
        ui.status("MANUAL", str(error), "warning")
        return "manual"
    ui.section("AUTOMATIC MODE TRIALS PREVIEW")
    for index, plan in enumerate(plans, 1):
        ui.text(f"{index}. {plan.description}")
    ui.text("These are modes listed by KDE, not verified projector compatibility. Each trial has a "
            "15-second confirmation window. Choose Next to restore the original configuration before "
            "the following trial. No answer restores and stops. Keep cables and Display settings "
            "unchanged, and use the terminal on the other active screen.")
    action = choose("Start this mode sequence?", [
        ("try", "Try these modes with automatic undo"),
        ("manual", "Use the manual instructions instead"),
        ("skip", "Skip mode trials"),
    ], read, ui)
    if action != "try":
        return action

    def confirm(plan, index, total, seconds):
        ui.section(f"MODE TRIAL {index}/{total}")
        ui.text(plan.description)
        return confirm_mode_in_terminal(ui, seconds)

    return run_mode_sequence(plans, confirm)


def run(
    *,
    snapshot_reader: Callable[[], Snapshot] | None = None,
    read: Callable[[str], str] | None = None,
    write: Callable[[str], None] | None = None,
    plain: bool = False,
    terminal: Terminal | None = None,
    try_fix: bool = False,
) -> int:
    snapshot_reader = snapshot_reader or collect
    read = read or input
    ui = terminal or Terminal(write=write, plain=plain)
    write = ui.text
    session = Session()
    ui.banner("Guided projector troubleshooting", __version__)
    ui.text("DESCRIBE  /  TRY  /  VERIFY", "accent")
    if try_fix:
        write("I will suggest one step at a time. On KDE or GNOME Wayland, a disabled external output may be "
              "eligible for automatic activation after a preview and your approval. KDE Wayland also supports "
              "a short sequence of mode trials on an active external output. Other changes are manual. "
              "You can skip a step or exit with 0.")
    else:
        write("I will suggest one step at a time. You make any changes in your settings; "
              "BeamFix reads the data again and asks what you see. You can skip a step or exit with 0.")
    write("When available, readings include pixel resolution and refresh rate from the desktop session. "
          "A listed or reported mode does not confirm a visible image. If these data are unavailable, basic guided checks remain available.")
    try:
        session.symptom = choose("What do you see on the projector?", list(SYMPTOMS.items()), read, ui)
        session.snapshot = snapshot_reader()
        session.target = select_target(session.snapshot, read, ui)
        while True:
            ui.section("CURRENT DISPLAY")
            write("Observed state: " + describe(session.snapshot, session.target))
            tried = {a.step.code for a in session.attempts}
            step = next_step(session.snapshot, session.target, session.symptom, tried, try_modes=try_fix)
            if step is None:
                session.outcome = "insufficient" if insufficient(session) else "unresolved"
                break
            if try_fix and step.code in {"activate", "mode"}:
                offer = offer_activation if step.code == "activate" else offer_modes
                automatic = offer(session.target, read, ui, snapshot=session.snapshot)
                if automatic == "skip":
                    session.attempts.append(Attempt(step, False, describe(session.snapshot, session.target)))
                    continue
                if automatic != "manual":
                    title = "Try automatic output activation" if step.code == "activate" else "Try automatic display modes"
                    attempt = Attempt(replace(step, title=title), automatic.attempted,
                                      describe(session.snapshot, session.target),
                                      automatic_result=automatic.detail)
                    session.attempts.append(attempt)
                    session.snapshot = snapshot_reader()
                    attempt.after = describe(session.snapshot, session.target)
                    attempt.observation = "expected image confirmed" if automatic.status == "kept" else "not confirmed"
                    session.outcome = "resolved" if automatic.status == "kept" else "insufficient"
                    if step.code == "mode" and automatic.status != "kept":
                        session.outcome = "not_confirmed"
                    ui.status("KEPT" if automatic.status == "kept" else "NOT KEPT", automatic.detail,
                              "ok" if automatic.status == "kept" else "warning")
                    if automatic.status != "kept":
                        write("The automatic attempt has ended. Check Display settings if requested above; "
                              "run beamfix troubleshoot to continue with manual checks.")
                    break
            ui.step(len(session.attempts) + 1, step.title, step.reason, step.instruction)
            action = choose("When you are ready:", [("done", "Done: read the state again"), ("skip", "Skip this step")], read, ui)
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
                session.target = select_target(session.snapshot, read, ui)
            attempt.after = describe(session.snapshot, session.target)
            ui.section("VERIFY THE RESULT")
            write("New reading: " + attempt.after)
            write("Linux state alone does not confirm that the image is visible.")
            observed = choose("What do you see now?", [
                ("resolved", "I can see the image I wanted to project"),
                *SYMPTOMS.items(),
                ("unverified", "I cannot verify the image"),
            ], read, ui)
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
        ui.blank()
        write("Closing guided troubleshooting.")
    return summarize(session, ui)
