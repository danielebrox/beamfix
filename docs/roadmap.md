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
