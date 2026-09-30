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

## 0.3 — First backend for applying fixes

Choose a single desktop environment after the first test on the development
computer. Detect the current configuration, propose enabling an output and show
an action preview. Apply one change at a time, with automatic rollback and visual
confirmation. Verify timeout, crash and projector disconnection behavior.

## 0.4 — Everyday use

An interface with Diagnose and Try a fix actions; mirroring/extension and selection
of a compatible mode using backend data. Add HDMI audio diagnostics and a second
desktop environment only after verifying the first.

## Before a public release

Choose a license and distribution method. Test real projectors, direct HDMI,
USB-C adapters and docks; document the desktops, GPUs and drivers verified.
Do not promise universal compatibility or repair of physical faults.
