# Roadmap

## 0.1 — Local diagnostics (implemented)

- `doctor` CLI and JSON v1 output.
- DRM, GPU/driver and session context collection.
- Initial rules and handling of incomplete data.
- Tests with simulated hardware and CI configuration.

## 0.2 — Guided troubleshooting (implemented)

- `troubleshoot` command for a connected projector with a missing or unexpected image.
- Distinction between No signal, a black screen and a desktop without the presentation.
- Explicit output selection; no automatic identification of a device as a projector.
- One manual step at a time, a fresh reading and a question about the visual result.
- A flow adapted to state and symptom; completed or skipped steps are not repeated.
- A summary with before/after observations, skipped steps and confirmed or uncertain results.
- Simulated tests for missing data, multiple displays, connection changes and interruptions.

Field validation remains: complete a session with a real projector, checking that
the instructions match the desktop and that the summary is useful in a classroom.
Simulated tests do not establish hardware compatibility or successful projection.

### 0.2.1 — English interface and documentation (implemented)

- English command help, diagnostics, collection errors, guided steps and summaries.
- English README, architecture documentation and roadmap.
- English as the working language for GitHub contributions.
- Existing commands, diagnostic codes, JSON schema and exit codes preserved.

### 0.2.2 — Clearer terminal interaction (implemented)

- Terminal palette colours with explicit status labels and a plain-text fallback.
- Diagnostic overview and next steps before hardware details.
- Numbered choices and distinct reason, action and verification sections.
- Narrow-terminal wrapping, safe device text and unchanged JSON output.
- `--plain`, `NO_COLOR` and `TERM=dumb` support without new runtime dependencies.

### 0.2.3 — Current display modes on KDE (implemented)

- Read configured pixel resolution and Hz together through `kscreen-doctor --json`.
- Green modes listed by KDE, inactive outputs, and yellow unverified observations.
- Unique output matching; no guesses across GPU duplicates or connector aliases.
- Optional read-only backend with timeout and preserved basic DRM diagnostics.
- Additive `current_mode` JSON data; incomplete mode observations return `2`.
- Checked on KDE/Wayland; other desktops and unmatched KDE/X11 names remain unverified.

### 0.2.4 — Current modes in guided troubleshooting (implemented)

- Read KDE modes during output selection and after every completed guided step.
- Include configured resolution and refresh rate in before/after summaries.
- Adapt manual mode-change instructions to the selected output's observed mode.
- Keep basic guided checks available when current-mode data cannot be obtained.
- Preserve explicit visual confirmation and existing troubleshooting exit codes.
- Simulated coverage for changing modes, missing observations and backend refresh.

Real-projector field validation remains open; these changes do not apply settings.

### 0.2.5 — Standard Wayland observation (implemented)

- Desktop-independent `wl_output` reading through optional `wayland-info`.
- Distinguish a Wayland `reported` mode from a KDE `listed` mode in CLI and JSON.
- Preserve KDE's richer response; use Wayland when its query is unavailable.
- Conservative matching, DRM state checks, timeouts and explicit unknown states.
- Integrate reported modes into guided instructions and before/after summaries.
- Verified both paths on KDE/Wayland; simulated coverage for other desktops.

Real GNOME, Hyprland and Cinnamon Wayland sessions remain to be tested. A generic
X11/RandR backend and shared Wayland output-management support remain future work.

## 0.3 — First backend for applying fixes (implemented; field validation open)

- Opt-in `troubleshoot --try-fix` on KDE/Wayland, with manual fallback.
- Preview and explicit approval to activate one connected, disabled external output.
- Retained mode and layout, another verified active screen, fresh preconditions.
- Independent helper owns activation, a 15-second visual confirmation window and undo.
- Read-back verification, conservative handling of external changes and failed recovery.
- Simulated transaction tests plus real subprocess/IPC tests for UI death and timeout.
- Live read-only configuration parsing checked on the development computer.

Real-projector activation and rollback remain unverified. Complete the
[field checklist](automatic-activation-checklist.md) before treating this backend
as classroom-ready. General mode selection and mirroring remain future work.

### 0.3.1 — GNOME Wayland activation (implemented; field validation open)

- Select KDE or GNOME explicitly from the current Wayland desktop.
- GNOME/Mutter DisplayConfig through optional `busctl` JSON, without Python dependencies.
- Preview one preferred mode and a position to the right of existing screens.
- Preserve existing modes, layout, primary screen, scale and supported color settings.
- Verify and apply temporary configurations using fresh Mutter serials; no saved profile.
- Share the independent visual-confirmation and recovery helper with KDE.
- Test typed calls against a simulated Mutter service on a private real D-Bus bus.
- Test both backends' helper processes for timeout, UI death and recovery.

A real GNOME session and physical projector still require field validation.
Cloning, leased monitors, uncertain observations and unsupported settings stay manual.

### 0.3.2 — Bounded KDE mode trials (implemented; field validation open)

- Opt-in mode sequence for a connected, enabled external output on KDE Wayland.
- Preview up to five distinct listed resolution/refresh pairs, excluding the current pair.
- Another verified active screen, exact restorable mode IDs and unchanged layout.
- Explicit Keep, Next or Stop; silence and terminal loss restore and stop.
- Verified restoration to the same baseline before every requested next trial.
- Per-trial summary, bounded exhaustion and conservative handling of external changes.
- Shared confirmation/recovery and sequence control, ready for another mode backend.
- Simulated planner, UI, transaction and detached-process recovery tests.

### 0.3.3 — GNOME mode trials (implemented; field validation open)

- Share the bounded sequence, mode ordering, Keep/Next/Stop decisions and recovery.
- Use GNOME's exact mode IDs with fixed refresh, no interlacing and the existing scale.
- Preserve positions, transforms, primary screen and captured color/underscan settings.
- Skip candidates that overlap screens, create gaps or require fractional-size rounding.
- Verify and apply temporary layouts through Mutter using fresh serials; no saved profile.
- Restore and verify the original layout before an explicit next trial.
- Cover mode selection, UI, helper death and typed D-Bus writes in simulated tests.
- Run a complete detached sequence against an isolated fake Mutter service.

The next validation priority is the **portable Fedora Workstation computer with
GNOME and a real projector**. Both backends are implemented; compatibility with
that machine and physical activation/mode switching remain unverified. Record
Fedora/GNOME versions, GPU/driver, connection, mode outcomes and recovery results
using the field checklist.

### 0.3.4 — Shared classroom systems (implemented; field validation open)

- Ask for the connection path, retaining unknown and user-reported provenance.
- Add the symptom: room monitors show the image but the projector does not.
- Guide room-source/projector blank checks and then modes, without laptop mirroring
  for that symptom; retain unknown-state and activation prerequisites.
- Confirm the image on the projector itself in manual and automatic flows.
- Summarize initial symptom, initial/latest connection and enabled computer outputs
  with their observed modes; do not infer the downstream physical display count.
- Refresh the user-reported path after a completed direct-connection test.
- Preserve the existing automatic confirmation deadline and recovery procedures.

Validate on the Fedora Workstation GNOME classroom system. Record settling time
before changing timeouts. Read-only signal-format diagnostics and optional local
profiles remain possible future increments, not implemented features.

### 0.3.5 — Read-only signal diagnostics (implemented; classroom validation open)

- Optional drm_info reader, matched by GPU node and sysfs connector ID.
- Allowlisted color, maximum-depth, HDR-reference and HDCP/link properties with
  explicit requested/limit/driver-status meanings and missing-data states.
- Active CRTC timing and listed detailed alternatives, preserving distinct timings
  with the same resolution/Hz without changing the automatic trial planners.
- Additive JSON signal data and compact initial/latest guided summaries.
- Optional user-reported connection and visual-result labels for comparing reports.
- Simulated parser, matching, conflict, privacy, query and report tests; real
  read-only development-machine check using a temporary upstream helper build.

Verify on Fedora Workstation GNOME in the actual classroom. Effective wire-format
measurement, changing color parameters, EDID identification, automatic timing
variants and saved room profiles remain outside this release.

## 0.4 — Everyday use (GUI and packaging implemented; field validation open)

- Offline browser GUI sharing diagnostics, guided steps and recovery worker.
- Four SVG situation examples, classroom connection context and explicit output selection.
- Manual checks, automatic previews, timed Keep/Next/Stop and session exports.
- Independent CLI plus wheel, source archive and offline portable Linux bundle.
- User installer with application-menu entry and reversible removal.

Validate browser rendering, keyboard operation, installed launchers and real
Fedora/GNOME projector recovery before classroom acceptance. Broader desktop
support, automatic mirroring/extension and HDMI audio remain future increments.

## Before a public release

Choose a license and distribution method. Test real projectors, direct HDMI,
USB-C adapters and docks; document the desktops, GPUs and drivers verified.
Do not promise universal compatibility or repair of physical faults.
