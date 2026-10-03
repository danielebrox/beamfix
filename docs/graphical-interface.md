# Graphical interface and portable packaging

BeamFix 0.4.0 adds an offline browser interface alongside the existing CLI.
It is a local Linux application: the page and all illustrations are shipped in
the package, and diagnostic data stay on the computer. No account, Internet
connection, web service, browser extension, GTK, Qt or Electron runtime is needed.
A modern browser and Python 3.11 or later must already be installed.

## Start from source

```bash
python3 -m beamfix gui
python3 -m beamfix gui --no-browser
python3 -m beamfix gui --demo
```

The first command opens the default browser. If it cannot be opened, copy the
launch URL printed in the terminal. Keep the process running. `--demo` uses
simulated data and cannot prepare or apply automatic changes. A persistent banner
and exported report label distinguish demonstration data from observations.

Use **Quit BeamFix** to stop the local service, or Ctrl+C in the launch terminal.
Closing a browser tab leaves the service running; reopen the printed launch URL
if needed. Closing a tab during an unconfirmed attempt requests undo; loss of the
browser heartbeat also requests undo. A previously confirmed change is retained.

## Guided workflow

1. Choose the illustration matching the projector: No signal, black projection,
   desktop without the presentation, or classroom monitors working without an
   image on the projector. Illustrations are examples, not detected conditions.
2. Describe the connection path, including classroom/shared AV systems or unknown.
3. Explicitly identify the external computer output, or select “I am not sure”.
4. Follow the shared manual troubleshooting instructions. **Done** collects a new
   reading before asking for the visual result. **Skip** remains unverified.
5. For eligible activation/mode steps, preview the exact automatic proposal,
   then explicitly approve it. The preview itself makes no changes.
6. Confirm the expected image on the projector itself. A working room monitor
   alone is not sufficient. Automatic trials have a 15-second confirmation limit.

The existing detached worker owns read-back, timeout and recovery. The browser
cannot change the deadline or invent a plan. Each confirmation is tied to a
fresh trial nonce and revision. A late or stale action cannot confirm another
trial. No reply, loss of the browser heartbeat or **Stop** requests undo; only
an explicit **Next** plus verified restoration allows another mode trial.
Display commands and restoration may take additional time. Do not change cables
or settings during an attempt. If the state changes externally, the worker may
refuse stale restoration: follow the result and check Display settings.

A four-second missing heartbeat is treated conservatively as lost interaction.
Browser throttling, suspending the computer or backgrounding the page may cancel
an attempt early. Keep the page visible on the other active screen. Logout,
compositor failure or killing the recovery worker itself cannot be covered.

Diagnostics show the most recent collected snapshot, not continuous monitoring.
Automatic summaries preserve the worker's recovery result and the pre-attempt
snapshot; they explicitly do not claim a fresh post-attempt diagnostic reading.
Use **Read diagnostics again** for that reading. Reports download only when the
user requests them. Session exports include the user-reported visual result,
connection and attempts; diagnostic JSON keeps `visual_confirmation: not_performed`.

## Portable Linux bundle

Extract `beamfix-0.4.1-linux-portable.tar.gz` anywhere in your user files:

```bash
cd beamfix-0.4.1
python3 launch.py gui
python3 launch.py doctor
python3 launch.py troubleshoot --try-fix
```

This route needs no pip, package registry, virtual environment, sudo or Internet.
It contains Python source and browser assets, not a bundled Python interpreter.
It is architecture-independent at the application level; installed Python,
browser and optional desktop tools still need to support the target machine.

To install the same bundle for the current user:

```bash
python3 install.py
```

The installer creates:

- `~/.local/bin/beamfix` — all CLI subcommands, including `gui`.
- `~/.local/bin/beamfix-gui` — graphical entry point.
- `~/.local/share/applications/beamfix.desktop` — **BeamFix** in the menu.
- A private application directory under `~/.local/share/beamfix`.

If `~/.local/bin` is not in PATH, use the full command path or add it to your
shell configuration. The menu uses an absolute path and does not depend on PATH
containing that directory. The installer prints the exact paths. A custom
`--prefix` is available for testing; desktop-menu discovery is only expected
when its `share/applications` directory belongs to the desktop's application path.

Run the installer again from a newer extracted bundle to update a managed
installation. Unrelated commands/entries and symlink launchers are refused rather
than overwritten. Do not run it while a BeamFix session or recovery is active.
Keep the extracted installer for removal:

```bash
python3 install.py --uninstall
```

Removal deletes only the managed launchers and installed bundle, leaving saved
reports alone. The development checkout and portable archive remain available.
The package is experimental and released under GPL-3.0-only. It includes the
license and copyright notices, which the user installer also preserves. See
[licensing](../LICENSING.md) for distribution and commercial-use details.

## Standard Python packaging

For environments managed with pip/pipx, install the supplied wheel. Both command
entry points and the HTML/CSS/JavaScript/SVG assets are in the wheel. For example,
from a virtual environment:

```bash
python -m pip install --no-deps /path/to/beamfix-0.4.1-py3-none-any.whl
beamfix gui
beamfix doctor --json
```

Build all three artifacts with installed setuptools and wheel:

```bash
python3 scripts/build_release.py
```

The builder does not download dependencies. Output is in `dist/`: wheel, source
archive, offline portable archive and SHA-256 checksums. An AppImage, Flatpak,
RPM or DEB is not part of this release. Avoid claiming universal compatibility.

## Compatibility and field acceptance

| Component | Requirement / boundary |
| --- | --- |
| GUI and CLI | Linux, Python 3.11+, browser only for the GUI |
| Basic diagnostics | Readable Linux DRM data; missing values remain unknown |
| Current mode | Optional `kscreen-doctor` on KDE or `wayland-info` on Wayland |
| Signal details | Optional distribution package `drm_info`; no elevation |
| Automatic changes | Existing conservative KDE/GNOME Wayland backends only |
| GNOME automatic changes | `busctl` with JSON support and Mutter DisplayConfig |
| Other desktops / X11 | Available readings and manual guidance; no new write backend |

Portability of the page does not establish compatibility of display changes.
The priority acceptance target is the **Fedora Workstation GNOME portable
computer with the actual classroom/projector**. Before classroom use:

- Extract the portable package offline and check `python3 launch.py --version`.
- Open the GUI from source, portable bundle and installed menu as applicable.
- Check illustrations, text, keyboard focus and diagnostic data on the laptop.
- Install the distribution's optional `drm_info` for signal comparison.
- Run the [existing automatic-activation checklist](automatic-activation-checklist.md),
  including Keep, Stop, timeout and closing the browser tab during a trial.
- Test the shared-classroom symptom and confirm the projector itself, recording
  settling times, actual Fedora/GNOME versions and recovery results.

Tests with simulated devices and isolated D-Bus do not satisfy physical acceptance.

## Local HTTP boundary

The service binds an OS-selected port on `127.0.0.1` only. API calls require a
per-launch random token, sent in a custom header. The launch fragment is removed
from the address bar and retained in that tab's session storage. Host and Origin
checks reject other sites; no CORS is granted. There is no general filesystem
server, shell endpoint or user-supplied display plan. Only packaged assets and
allowlisted state transitions are available. Static content uses a restrictive
Content Security Policy and no external resources. This is a single-user local
interface, not a network server for deployment or remote administration.

## Publishing tested packages

CI builds and checks the artifacts on Python 3.11 and 3.14. Only a push to `main`
whose commit message explicitly includes `[release]` publishes a GitHub prerelease,
and only after both test jobs succeed. Add `docs/releases/<version>.md` before
requesting a release. The publishing job downloads the tested Python 3.11 artifacts,
verifies their SHA-256 checksums and targets that exact commit. Existing releases
are never overwritten. Ordinary pushes and pull requests only run checks.
