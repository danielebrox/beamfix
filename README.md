# BeamFix

Local diagnostics for monitors and projectors on Linux. The goal is a simple
workflow: connect the projector, run BeamFix, try a fix and confirm the result.

**Status: v0.4.1 — offline graphical interface, portable packaging and independent CLI (experimental).** The `doctor` command collects data and
reports potential issues; `troubleshoot` guides one step at a time and checks the
outcome with the user. Opt in with `troubleshoot --try-fix` to try reversible
activation of a disabled external output on KDE or GNOME Wayland, or a bounded sequence
of mode trials on an already active KDE or GNOME output. Real-projector validation
of automatic activation remains open. The optional graphical interface runs locally
in your browser and shares the existing diagnostics and recovery worker.

![BeamFix diagnostic report and guided troubleshooting](docs/images/cli-preview.svg)

*Example terminal output using simulated display data. Actual colours follow your
terminal theme.*

## Quick start

Requires Linux and Python 3.11 or later. From the repository directory:

**For advanced signal diagnostics, install the optional `drm_info` tool.**
This is also required on the Fedora Workstation GNOME classroom computer to
collect signal properties and detailed timings. Installing BeamFix does not
install `drm_info`. Without it, BeamFix explicitly reports signal details as
unavailable and keeps basic diagnostics working.

```bash
python3 -m beamfix doctor
python3 -m beamfix doctor --json
python3 -m beamfix troubleshoot
```

No additional Python runtime dependencies, Internet access, external services or
API keys are needed. For current modes, both commands optionally use installed
`kscreen-doctor` on KDE, or `wayland-info` on Wayland sessions. BeamFix does not
install these tools automatically or require `sudo`. `doctor` and the default
`troubleshoot` command do not change desktop settings. The optional automatic
activation enables the selected output: KDE reuses its retained mode; GNOME uses
its preferred mode and adds it to the right of the desktop. During activation, existing active
screens keep their modes. GNOME activation additionally requires `busctl` with
JSON support and access to Mutter's DisplayConfig service. Nothing is installed
automatically.

To install the command in a virtual environment (requires `venv` and `pip`):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/beamfix doctor
.venv/bin/beamfix troubleshoot
```

Installation may download build tools; BeamFix itself runs offline. If you have
already installed an earlier version, run `.venv/bin/python -m pip install .`
again to update the command in the virtual environment. Running
`python3 -m beamfix` from the repository directory uses the local source directly.

## Graphical interface and offline package (0.4.1)

![BeamFix graphical interface with simulated display data](docs/images/gui-preview.jpg)

*Browser preview using demonstration data; not a projector hardware test.*

```bash
python3 -m beamfix gui
python3 -m beamfix gui --demo  # simulated data; no automatic changes
```

The GUI runs entirely on this computer, without Internet access, browser plugins,
external assets or Python runtime dependencies. Choose one of four illustrated
situations, identify the output, follow a manual check or preview an automatic
attempt, then confirm the image on the projector itself. Diagnostics and session
summaries can be saved explicitly as JSON. The CLI remains fully independent.

Download the [experimental 0.4.1 release](https://github.com/danielebrox/beamfix/releases/tag/v0.4.1).
For another Linux computer, extract the **portable asset**
`beamfix-0.4.1-linux-portable.tar.gz` and run:

```bash
cd beamfix-0.4.1
python3 launch.py gui        # portable: no installation
python3 install.py          # optional user installation and application-menu entry
```

The installed menu entry is **BeamFix**; commands are `beamfix`, `beamfix gui`
and `beamfix-gui`. The installer uses `~/.local`, refuses unrelated existing
launchers and needs no `sudo`, pip or network. Python 3.11+ and a modern browser
must already be installed. Optional desktop tools are supplied by the distribution.
Uninstall with `python3 install.py --uninstall` from the extracted bundle.

A standard wheel and source distribution are also built. See the
[GUI and packaging guide](docs/graphical-interface.md) for installation, recovery
behavior, compatibility boundaries and the Fedora/GNOME field checklist.

## Current resolution and refresh rate

On KDE, `doctor` reads the current configuration through `kscreen-doctor --json`
and shows the configured mode for each uniquely matched Linux output:

```text
Current mode: 3840 x 2160 @ 60.00 Hz
[LISTED] Current mode is listed as available by KDE.
```

The resolution and refresh rate are checked together using the current mode ID.
The green `LISTED` label means that KDE includes this mode in its available
list; it does not guarantee that the projector displays a correct image or that
the mode was advertised by the monitor rather than added manually.

On other Linux Wayland desktops, and when the KDE query is unavailable, BeamFix
reads standard `wl_output` data using `wayland-info -i wl_output`. This path does
not depend on the desktop name. If `wayland-info` is installed and the session
exposes uniquely matching output names and a readable current mode, it shows:

```text
Current mode: 3840 x 2160 @ 60.00 Hz
[REPORTED] Current mode reported by Wayland; the available mode list is not verified.
```

`REPORTED` is informational (cyan), distinct from green `LISTED`. Standard Wayland
reports the session's current mode but does not guarantee an alternative-mode
list or expose disabled outputs. Virtual outputs may report synthetic values.
BeamFix retains the independent Linux DRM observations and never treats absence
from Wayland as proof of disconnection. It does not guess aliases or match names
that are duplicated across GPUs. Missing names, unknown/zero refresh rates,
unreadable records and conflicting Linux/Wayland state remain `UNVERIFIED`.

KDE's valid configuration response takes precedence, including any ambiguous or
conflicting entries: a fallback must not conceal those uncertainties. The
Wayland fallback is used when the KDE command is absent, fails, times out or
returns an unreadable configuration. On KDE/X11 only the KDE backend is used;
other X11 desktops retain basic DRM diagnostics. A generic RandR backend is not
yet implemented. Both queries are read-only with a five-second timeout each.

Disabled/disconnected outputs are labelled `Inactive` when supported by the
observations. Previous modes are never reused as a fresh reading. Yellow
`UNVERIFIED` means that the current mode cannot be established, not that it is
incompatible. Missing optional tools never prevent the basic DRM diagnostics.

The values describe pixel resolution and refresh rate reported by the session,
not the scaled desktop size or instantaneous refresh under variable refresh rate
(VRR). An unverified current mode makes `doctor` return `2` (incomplete
observation), while preserving the other diagnostic results. A readable
`REPORTED` mode alone does not make the observation incomplete or establish
visual success.

Both backends have been checked on KDE/Wayland, including agreement on the
current mode. Other Wayland desktops are covered by simulated tests only;
compatibility still requires real-session testing. The `wayland-info` adapter
parses its text output conservatively; an unsupported output format remains
unverified. Older Wayland outputs without names cannot be matched.

## Terminal presentation

The CLI uses your terminal's colour palette, with clear section headings,
numbered choices and wrapped text. Diagnostic reports put the overall result and
next steps before hardware details. Guided checks separate the reason for each
step, what to do, and verification of the result.

- Cyan highlights headings, choices and the next action.
- Amber marks warnings, unknown data and unconfirmed outcomes.
- Green marks a detected connection, a current mode listed by KDE, or an image
  explicitly confirmed by the user; the accompanying label always says which one.
- Status labels remain meaningful without colour. No special fonts are required.

Colours are enabled automatically in a terminal. Redirected or piped output is
plain text. Set `NO_COLOR` to disable colour, or pass `--plain` to also remove
decorative characters:

```bash
python3 -m beamfix doctor --plain
python3 -m beamfix troubleshoot --plain
```

`TERM=dumb` also selects plain output. JSON output is always unstyled. The CLI
keeps normal terminal scrolling and numbered input; it does not clear the screen
or require an additional terminal UI library.

## Guided troubleshooting: projector connected, image missing or unexpected

Run `python3 -m beamfix troubleshoot` in a terminal on the computer connected to
the projector. Use the numbered options to describe what you see: No signal, a
black screen, or the desktop without the presentation. Then select the projector
output. If you cannot identify it, you can say so instead of guessing another monitor.

BeamFix suggests one step relevant to the available data: checking the projector
input or connection, enabling the output, selecting the presentation screen,
mirroring, or trying another video mode. You make any changes manually in your
desktop settings: in this default workflow BeamFix neither applies nor rolls them back.

When available, the guided readings also include the selected output's configured
resolution and refresh rate. When suggesting a different mode, BeamFix shows
the observed mode and asks you to check it in Display settings before changing
it. Each completed step queries the desktop again, and the summary retains the before/after
values, including changes in refresh rate at the same resolution. An inactive
output or an unavailable mode is labelled explicitly; previous values are never
carried forward as a new observation. If current-mode data are unavailable, the basic
guided checks continue. A mode listed by KDE or reported by Wayland does not confirm a correct image.

After you choose Done, BeamFix reads the state again and asks what you see. If the
symptom changes, the next step changes accordingly. A completed or skipped step
is not offered again within the same session. If a connection change requires
identifying a new output, BeamFix asks you to select it explicitly. You can skip
unavailable steps and exit at any time with `0` or Ctrl+C.

The summary distinguishes completed and skipped steps, before/after observations
and visual results. A solution is confirmed only when you report seeing the
expected image; an enabled output is not enough. A failed step alone does not
prove a hardware fault, and a skipped step does not rule out any cause.

Exit codes for `troubleshoot`: `0` means the user confirmed the expected image;
`1` means the problem remains after the available steps; `2` means insufficient
data or visual verification, or an interrupted session. These meanings differ
from the exit codes for `doctor`. The summary stays in the terminal and is not
saved or sent automatically. The guided command has no JSON option; a technical
report is available through `doctor --json`.

## First automatic attempt: enable a disabled output on KDE or GNOME Wayland

```bash
python3 -m beamfix troubleshoot --try-fix
```

The guided flow selects the backend for the current desktop and offers automatic
activation only when Linux and that desktop agree that the selected external
output is connected but disabled. It requires an interactive terminal, uniquely
identified outputs, readable settings and another verified active screen.
Unsupported or incomplete configurations keep the manual instructions available.

| Desktop | Required tool | Proposed action |
| --- | --- | --- |
| KDE Wayland | `kscreen-doctor` | Enable the target with its retained mode and position; place it last in KDE's output priority order. |
| GNOME Wayland | `busctl` with JSON support | Use the target's unique preferred mode and extend the desktop to the right, showing resolution, Hz, scale and position before approval. |

BeamFix previews the action, then asks whether to try it, use manual instructions
or skip. It rereads the configuration after approval. Existing active screens keep
their positions, scaling, rotation, primary status and modes. This first action
does not configure mirroring. GNOME changes are temporary for the current session;
even after confirmation, BeamFix does not save a persistent display profile.

The KDE backend requires a valid retained mode, consistent output priorities and
nonnegative positions; cloning and automatic preferred-mode selection are refused.
The GNOME backend uses Mutter's DisplayConfig interface, checks permission, and
asks Mutter to verify each configuration before applying it with a fresh serial.
It supports logical/physical layouts and supported scales that yield exact pixel
dimensions. Mirrored groups, leased monitors, ambiguous preferred modes, unknown
color settings or mismatched Linux/GNOME state fall back to manual guidance.
Native GNOME HDMI names (`HDMI-1`) are matched to Linux `HDMI-A-1` using Mutter's
documented naming table; ambiguous names across GPUs are still refused. Other
aliases are not guessed. GNOME X11 and other desktops remain manual.

After the desktop reports the expected state, answer **1 and Enter** to confirm the
expected image within 15 seconds. Other answers, no answer, Ctrl+C or closing the
terminal request automatic undo. A separate process owns the change and deadline,
so an abrupt failure of the terminal process also requests undo. A fresh desktop read
must verify the configuration before the change can be kept. A detected or enabled
output alone is never success.

Undo disables the same output and verifies the original configuration. Each desktop
command/query has a five-second limit; recovery may take additional time after the
confirmation window. Do not change cables or Display settings during the attempt.
If outputs disappear or settings change outside the attempt, BeamFix withholds
the stale undo and explicitly asks you to check Display settings. An unavailable
or failed recovery is never reported as restored. Logout, compositor failure or
killing the recovery process itself cannot be covered by this helper.

Only one automatic attempt per user can run at a time. Recovery data stay in
process memory and are not written to a report. The attempt ends with a summary:
exit `0` only for verified activation plus explicit visual confirmation, otherwise
`2`. Run the default `beamfix troubleshoot` to continue manual checks afterward.

The KDE planner has been checked against the development computer's live data
without changing the displays. Both backends have simulated activation, undo,
timeout and terminal-process death tests using real helper processes. GNOME's
typed D-Bus calls also run against a simulated Mutter service on an isolated real
D-Bus session, including stale-serial rejection. **A real GNOME session and
real-projector activation/rollback have not been verified yet.** See the
[field checklist](docs/automatic-activation-checklist.md) for that remaining check.

## Signal diagnostics (0.3.5)

Both `doctor` and guided before/after summaries now include optional, read-only
signal observations through `drm_info -j`. Install your distribution's `drm_info`
package to enable them (on Fedora, the package is named `drm_info`). BeamFix does
not install tools, elevate privileges or change display settings for this read.
Without the tool or device access, signal details explicitly remain unavailable;
basic diagnostics continue. The optional query has a five-second timeout.

The report distinguishes:

- `max_bpc`: a configured upper limit, **not measured transmitted bit depth**.
- Colorspace, color format and RGB range: driver properties requesting settings;
  `Default` or `AUTO` does not establish the format actually sent on the cable.
- HDR metadata presence: a metadata reference, **not proof of visible HDR**.
- Content Protection / HDCP content type and link status: reported driver state
  or requests, **not a diagnosis of the cause of a missing picture**.
- Current detailed timing: a verified active CRTC's configured timing, including
  pixel clock, synchronization intervals, totals and flags; not a wire measurement.
- Listed detailed timings: available kernel entries, preserving timing differences
  even at identical resolution/Hz. Complete alternatives are in JSON. Listing a
  timing does not establish projector compatibility.

Each signal property includes source, state, interpretation and a note. Missing,
invalid and conflicting data remain explicit. Actual transmitted bit depth is
unavailable in this backend. A separate `signal` object is added per connector;
existing JSON v1 fields and basic diagnostic exit-code semantics remain intact.
Optional missing properties do not themselves indicate a display fault or turn
an otherwise complete basic observation into exit code 2. Check the signal object's
coverage when comparing reports. This observation does not broaden automatic
mode trials, which still deduplicate by resolution/Hz and keep existing safeguards.

To collect comparable reports in the classroom, add your visual result and
connection description. These labels are user-reported, not inferred:

```bash
beamfix doctor --json --connection room --visual-result room_monitors_only > room-failed.json
# Run the second command only when you can actually see the image on the projector:
beamfix doctor --json --connection room --visual-result projector_visible > room-working.json
```

Run both on the same computer and port if possible, and note any cable or room
control changes. The shell redirection saves the reports at your request; BeamFix
itself does not save or upload them. `visual_confirmation` remains `not_performed`
for doctor; the separate `user_context` records your annotation. No comparison
can establish a fault from one differing setting alone.

## Classroom systems (0.3.4)

The guided flow asks how the computer is connected: directly, through a dock or
adapter, through a classroom socket/shared AV system, or an unknown path. This
is user-reported context, not a detected topology. Select the computer output
feeding the room system even if the projector is not listed separately.

Choose **The classroom monitors show the image, but the projector does not**
when applicable. BeamFix starts with the room's source and projector blank/mute
controls, where accessible, then offers alternative modes for an active output.
It does not suggest laptop mirroring for this symptom. Unknown or disabled
computer outputs still require their existing diagnostic or activation checks.
Reconnect guidance concerns the computer end; a direct-connection test can be
skipped when it would require changing installed classroom wiring.

Confirm success only when the **projector itself** shows the expected image.
The summary retains the initial symptom, initial/latest user-reported connection,
per-step visual outcomes and initial/latest computer output counts and modes.
Computer output counts do not reveal how many physical screens a room system
feeds. Completing a direct-connection test asks for the connection path again.

Automatic attempts retain the 15-second confirmation window and existing undo
behavior. If the projector has not settled in time, do not confirm based on a
working room monitor. Let the attempt restore and stop, and record the delay in
the [field checklist](docs/automatic-activation-checklist.md). Classroom timing
and compatibility still require real Fedora/GNOME testing. EDID identification and saved room profiles remain future work. Signal diagnostics
were added separately in 0.3.5, as described above.

## Automatic mode trials on KDE and GNOME Wayland

Run `python3 -m beamfix troubleshoot --try-fix`, select No signal or a black
screen, and explicitly select the external output. For an already active output,
after checking the projector input, BeamFix offers up to five alternative
resolution/refresh combinations before the manual mirroring step. It shows the
whole sequence before asking for approval. Disabled outputs use the activation
workflow above; it does not automatically chain activation into mode trials.

The sequence uses only exact mode IDs from the current desktop configuration. It skips the
current resolution/refresh combination and duplicates. It orders alternatives
by refresh closest to 60 Hz, then prioritizes sizes up to 1920 x 1080, largest
first. This is a troubleshooting order, not evidence of projector compatibility.
Modes that would overlap another screen or require rounding the logical size at
the existing scale are omitted. The list is bounded, not an exhaustive search.

Every trial requires another active screen verified against Linux. Keep the
terminal on that screen. Output positions, scaling, rotation and priority stay
unchanged. Cloned or overlapping screens, ambiguous names and unreadable settings
fall back to manual guidance. KDE also refuses automatic preferred-mode selection.
GNOME requires each candidate to support the existing scale, use fixed refresh
and non-interlaced output, and keep the desktop connected without creating gaps
between screens. It omits alternatives that fail these checks. Depending on the
layout, only refresh-rate changes may be eligible; BeamFix does not reposition
other screens to make a different resolution fit.

After each applied mode, a fresh read must match the expected configuration.
Within 15 seconds, answer **1 and Enter** to keep the mode and finish, **2 and
Enter** to restore and try the next mode, or **0 and Enter** to restore and stop.
Silence, invalid input, Ctrl+C and terminal closure restore and stop. Only an
explicit Next received in time, followed by verified restoration, permits
another trial. Each trial starts from the same original configuration and checks
the complete plan again. Changed cables/settings or uncertain recovery stop the
sequence. If no candidate is confirmed, the original configuration is verified
and the summary reports no visual success, with exit code `2`.

The summary includes each attempted mode and its recovery result. A successful
sequence returns `0` only after explicit visual confirmation. The shared helper
has the same recovery limits described above. The mode command does not promise
session-only persistence on KDE; check Display settings for saved behavior.

On **GNOME Wayland, including the intended Fedora Workstation test system**, mode
trials use `busctl` with JSON support and Mutter's DisplayConfig service, as does
automatic activation. Each change is verified and applied with a fresh serial.
Even after confirmation it remains temporary for the current session: BeamFix
does not save a display profile. GNOME X11 falls back to manual instructions.

From the project directory on Fedora, check `python3 -m beamfix --version`
(requires 0.3.3 or later), then run `python3 -m beamfix troubleshoot --try-fix`
in a terminal on the laptop screen. Keep both the laptop screen and projector
output enabled in an extended layout. Select the projector explicitly. If the
projector output is disabled, complete the separate activation workflow first.

Tests cover simulated mode trials, real helper process death, and a full detached
GNOME mode sequence over an isolated D-Bus service. **A real GNOME session and
physical projector still require field validation.** Follow the
[field checklist](docs/automatic-activation-checklist.md) and record Fedora/GNOME
versions and the actual hardware; simulated results do not certify compatibility.

## What BeamFix checks today

- Operating system, kernel, reported session type and desktop.
- DRM graphics cards and driver names, when available.
- Connectors, connection state, output enablement and listed video modes.
- Current resolution and Hz through KDE or standard Wayland, with explicit source and status.
- Connected but disabled outputs, missing modes and inaccessible data.
- An English terminal report or JSON with a schema version and diagnostic codes.

BeamFix reads `/sys/class/drm`, optional KDE/Wayland and `drm_info` observations, and two session variables:
`XDG_SESSION_TYPE` and `XDG_CURRENT_DESKTOP`. Only the required output-state, mode, allowlisted signal-property and timing fields are retained; raw tool responses, descriptions, EDID data, serial numbers,
profile paths, hostnames, accounts and system logs are not included in reports.
GNOME automatic attempts additionally read Mutter state over the local session
bus. The private in-memory plan holds a digest of monitor identity for swap
detection; raw identity strings are discarded and no digest is added to reports.
Reports are not saved or sent
automatically. Reports still contain hardware and environment details: review
them before sharing.

## Limitations

An enabled output does not prove that the image is visible or correct. This
version can read resolution and Hz from KDE or Wayland, but does not measure
instantaneous refresh, scaling, audio or cable quality. Optional HDCP properties report driver state, not downstream image visibility. It cannot reliably distinguish a monitor from a projector.
USB-C may appear as DisplayPort: the DRM connector type does not identify the
physical cable.

The data are a kernel observation and may be incomplete or change during
connection. A listed mode is not necessarily the active mode. BeamFix does not
force a display rescan. Basic DRM checks are independent of the desktop; current-mode
observation uses KDE or standard Wayland backends. Compatibility with specific drivers and devices
requires hardware testing.

Exit codes for `doctor`: `0` means no issues were detected by the available
checks; `1` indicates warnings; `2` indicates incomplete observations or an
unknown state. CLI syntax errors also return `2`. A `doctor` exit code of `0`
does not mean that projection has been visually verified. Disconnected ports
may be normal; interpret warnings in relation to the display you expected to find.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests use simulated devices and do not modify the graphics system. GitHub Actions
runs tests and verifies installation on Python 3.11 and 3.14.
The GNOME transport integration test also needs `dbus-run-session`, `busctl` and
system Python (`/usr/bin/python3`) with PyGObject. These are test tools, not new
Python dependencies for BeamFix. The test starts its own isolated bus and a fake
Mutter service. It skips when those tools are absent; CI installs them and sets
`BEAMFIX_REQUIRE_DBUS_TESTS=1` so it cannot silently skip this check.
See the [architecture](docs/architecture.md) and [roadmap](docs/roadmap.md).

The interface, documentation and GitHub contributions use English. Keep commit
messages, issue descriptions and pull requests in English as well.

## License and contributions

BeamFix is free software under [GNU GPL version 3 only](LICENSE)
(`GPL-3.0-only`), without warranty. You may use, modify, share and sell copies
under those terms. Distributed covered derivatives must preserve the GPL
freedoms and provide corresponding source as required by the license.

See [LICENSING.md](LICENSING.md) for commercial distribution and
[CONTRIBUTING.md](CONTRIBUTING.md) before proposing contributions.
