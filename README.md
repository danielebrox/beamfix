# BeamFix

Local diagnostics for monitors and projectors on Linux. The goal is a simple
workflow: connect the projector, run BeamFix, try a fix and confirm the result.

**Status: guided troubleshooting, v0.2.2.** The `doctor` command collects data and
reports potential issues; `troubleshoot` guides one step at a time and checks the
outcome with the user. Automatic fixes and a graphical interface are on the roadmap.

![BeamFix diagnostic report and guided troubleshooting](docs/images/cli-preview.svg)

*Example terminal output using simulated display data. Actual colours follow your
terminal theme.*

## Quick start

Requires Linux and Python 3.11 or later. From the repository directory:

```bash
python3 -m beamfix doctor
python3 -m beamfix doctor --json
python3 -m beamfix troubleshoot
```

No additional runtime dependencies, Internet access, external services or API keys
are needed. BeamFix does not require `sudo` and does not change the resolution,
drivers or desktop configuration.

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

## Terminal presentation

The CLI uses your terminal's colour palette, with clear section headings,
numbered choices and wrapped text. Diagnostic reports put the overall result and
next steps before hardware details. Guided checks separate the reason for each
step, what to do, and verification of the result.

- Cyan highlights headings, choices and the next action.
- Amber marks warnings, unknown data and unconfirmed outcomes.
- Green marks a detected connection or an image explicitly confirmed by the user;
  the accompanying label always says which one.
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
desktop settings: BeamFix neither applies nor rolls them back.

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

## What BeamFix checks today

- Operating system, kernel, reported session type and desktop.
- DRM graphics cards and driver names, when available.
- Connectors, connection state, output enablement and listed video modes.
- Connected but disabled outputs, missing modes and inaccessible data.
- An English terminal report or JSON with a schema version and diagnostic codes.

BeamFix reads `/sys/class/drm` and two session variables:
`XDG_SESSION_TYPE` and `XDG_CURRENT_DESKTOP`. It does not collect raw EDID data,
serial numbers, hostnames, accounts or system logs. Reports are not saved or sent
automatically. Reports still contain hardware and environment details: review
them before sharing.

## Limitations

An enabled output does not prove that the image is visible or correct. This
version does not measure the current refresh rate, resolution, scaling, audio,
HDCP or cable quality. It cannot reliably distinguish a monitor from a projector.
USB-C may appear as DisplayPort: the DRM connector type does not identify the
physical cable.

The data are a kernel observation and may be incomplete or change during
connection. A listed mode is not necessarily the active mode. BeamFix does not
force a display rescan. The backend is independent of the desktop; compatibility
with specific drivers and devices requires hardware testing.

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
See the [architecture](docs/architecture.md) and [roadmap](docs/roadmap.md).

The interface, documentation and GitHub contributions use English. Keep commit
messages, issue descriptions and pull requests in English as well.

The project is under private development. A distribution license has not yet
been selected.
