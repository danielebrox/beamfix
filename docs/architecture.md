# Architecture

`collect.py` reads kernel observations and produces a `Snapshot`.
`diagnose.py` applies deterministic rules to that model without accessing the system.
`desktop.py` optionally enriches the `doctor` snapshot with current KDE modes.
`cli.py` presents results or exports JSON to stdout.
`models.py` defines shared data and result types.

## Guided troubleshooting

`troubleshoot.py` adds the interactive command while preserving the behavior and
JSON schema of `doctor`. `next_step` chooses a step using the snapshot, selected
output, reported symptom and codes of completed or skipped steps. It does not
read the system or apply changes. The order of steps is deterministic.

`run` handles questions, readings and the summary. The collector and input/output
functions can be replaced in tests. After each step reported as completed, it
collects a snapshot and asks for the visual result. DRM state alone never yields
a successful outcome. Skipped steps are recorded as unverified.

Output selection is explicit even when only one output is listed. If an output
disappears or the connection moves to another port, the guided flow requests a
new selection. The connector name is used only to track the session: it is not
a persistent projector identity and cannot detect two devices being swapped on
the same port between readings.

The number of steps is bounded: each step code is offered at most once per
session, even if the output changes. Unknown data require another reading; if
they remain insufficient, the flow stops without inferring a fault. EOF, Ctrl+C
and the `0` option produce a summary with an unconfirmed outcome. Nothing is
saved automatically; manual changes remain under the user's control.

## Collection and tests

The initial backend is read-only. Tests inject a temporary DRM tree to simulate
disconnected ports, missing data and multiple GPUs without hardware. Unknown
states remain distinct from disconnected states; unreadable modes remain
distinct from an empty list. A card name is not a stable device identity.

## Observation boundaries

The `status`, `enabled` and `modes` fields follow the
[Linux kernel DRM sysfs implementation](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_sysfs.c).
In particular, `modes` lists mode names and does not provide the current refresh
rate. X11 detection does not rely on `DISPLAY` alone, since that variable is also
present in some Wayland sessions through XWayland.

## Extending BeamFix to apply fixes

A future GNOME, KDE or X11 backend must first query the desktop and obtain a
complete configuration that can be restored. A fix will have a precondition,
a specific action, state verification and a rollback. DRM names cannot simply
be reused as compositor identifiers.

A fresh reading is required before any change: data may have become stale after
hot-plugging. Rollback must survive a UI crash and account for disconnections and
changes made by the user in the meantime. The interface will request visual
confirmation within a timeout. Restarting the graphical session, installing
drivers or modifying system files is outside the scope of the initial MVP.

To add a rule, use a stable code, state the evidence, make uncertainty explicit
and add a test case that distinguishes a fault from a normal state.

## Current-mode observation

For `doctor`, `collect_doctor` first runs the DRM collector, then optionally reads
KDE using `kscreen-doctor --json`. Other desktops and nongraphical sessions do not
launch KScreen. The subprocess has no input, discards stderr and has a five-second
timeout. Missing tools, failed queries and malformed data produce explicit
unverified results without losing the DRM snapshot. The guided troubleshooter
continues to use the DRM collector alone.

The parser follows KDE's [configuration serializer](https://github.com/KDE/libkscreen/blob/master/src/configserializer.cpp):
`outputs`, `name`, `connected`, `enabled`, `currentModeId`, and the mode list's
`id`, `size` and `refreshRate`. It uses mode pixel dimensions, not the logical or
rotated output geometry. Refresh values are retained numerically in Hz and shown
to two decimals. Mode identity, not rounded rates or preferred-mode status,
determines the current resolution/refresh pair.

Connector matching strips only the Linux `cardN-` prefix. Both sides must have
exactly one match; duplicate names across GPUs, duplicate KDE outputs and X11
aliases remain unverified. Contradictory DRM/KDE state also remains unverified;
the two observations are not atomic and the connection may have changed.
Disabled/disconnected outputs never expose a retained mode as currently active.
Missing, duplicate or invalid current modes are unknown, not proof of incompatibility.

`Connector.current_mode` is an additive JSON v1 field with `state` (`listed`,
`inactive` or `unknown`), `source`, `reason`, and optional `mode` containing `width`,
`height` and `refresh_hz`. Existing `modes` still means the DRM names, without Hz.
An unknown current-mode observation returns exit code `2`; a listed mode never
sets `visual_confirmation` or proves the image is visible. No unsupported/red
classification is inferred from the available KDE data, including custom modes.
Raw desktop responses and unrelated identity/profile data are discarded.

## Terminal presentation

`terminal.py` owns terminal rendering, separate from diagnostic and troubleshooting
rules. It uses standard ANSI palette colours rather than forcing a background or
fixed RGB theme. A shared `Terminal` renders headings, status labels, choices,
wrapped text and action instructions. Reports show the overall result and next
steps before connector and system details.

Colour is automatic only on a terminal and is disabled by `NO_COLOR`,
`TERM=dumb`, `--plain` or redirected output. Decorative characters fall back to
ASCII when the output encoding cannot represent them. `--plain` works before or
after the subcommand. The JSON path bypasses the renderer entirely.

All device and environment text is sanitized before styling. Line wrapping counts
terminal cells, including wide characters and combining marks, and preserves long
connector names by wrapping rather than truncating them. Labels carry status even
without colour; an enabled or connected output never becomes visual confirmation.

Presentation tests cover narrow terminals, colour and plain output, unsupported
encodings, control characters, clean JSON and guided success/interruption paths.
The README preview uses simulated data, not a successful hardware projection.

## Language and compatibility

User-facing text, documentation and GitHub contributions use English. The 0.2.1
language update changes human-readable messages and suggestions, including those
in JSON reports. Commands, diagnostic codes, JSON field names, schema version
and exit codes remain unchanged. Tools consuming the report should use structured
fields and diagnostic codes rather than matching human-readable messages.
