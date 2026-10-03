# Architecture

`collect.py` reads kernel observations and produces a `Snapshot`.
`diagnose.py` applies deterministic rules to that model without accessing the system.
`desktop.py` selects optional current-mode observations for both commands.
`wayland.py` reads standard Wayland outputs through `wayland-info`.
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

## Classroom context

The guided session stores a user-reported connection path separately from Linux
observations. No connector name, monitor identity or visual symptom establishes
a physical topology. The `room_monitors_only` symptom does not imply success or
prove the cause of the problem. It selects classroom control checks and mode
trials instead of laptop mirroring when the computer output is active; existing
unknown-state and disabled-output handling takes precedence.

The initial symptom and connection survive later changes. After a completed
manual direct-connection test the path becomes unknown until the user describes
it again. Initial/latest snapshots summarize enabled computer outputs and their
observed modes, including internal screens; unknown enablement remains explicit.
These counts cannot identify displays hidden behind a shared AV system. All
context remains in memory and is printed in the guided summary; the doctor JSON
schema, automatic transaction protocol and recovery deadlines are unchanged.

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

## Applying a fix: shared recovery and KDE/Wayland activation

The default guided flow remains manual. `--try-fix` offers scoped activation at
the `activate` step and KDE/GNOME mode trials at the `mode` step.
`kde_fix.py` builds an `ActivationPlan` independently of the
public diagnostic model. It records mode IDs/lists, output IDs, activation,
position, scale, rotation, priority and replication state for all KDE outputs,
plus available optional display controls. The snapshot stays in memory. Raw
identity data and profile paths are not retained or written to reports.

The planner requires a connected, disabled external target, unique DRM/KDE name
matching, a valid retained mode, and a second active output verified against DRM.
It rejects cloning or follow-preferred-mode behavior on the target and active
screens, negative positions and inconsistent output priorities. KDE X11,
uncertain identities and missing data fall back
to manual guidance. Source of command syntax and state fields:
[KDE doctor](https://github.com/KDE/libkscreen/blob/master/src/doctor/doctor.cpp) and
[KDE configuration serializer](https://github.com/KDE/libkscreen/blob/master/src/configserializer.cpp).

`automatic.py` launches `fix_worker.py` in a new process session, with no terminal
stdio and a private inherited Unix socket. A per-user abstract Unix socket lock
prevents concurrent BeamFix attempts. The helper rebuilds the plan after approval,
requires equality with the preview, then requests an apply acknowledgment from the
still-live UI. It alone executes `output.NAME.enable` and the next output priority
in one `kscreen-doctor` call. No shell is used. The known-safe output name is matched
explicitly; DRM names are not passed straight to a write command.

A fresh read must match the expected activation with the surrounding layout
unchanged. Only then does the helper start its monotonic 15-second confirmation
deadline. The UI clears pretyped terminal input and accepts only a fresh `1` plus
Enter. Before accepting keep, the helper checks both the state and deadline again.
Command return codes alone never establish success. A confirmation arriving too
late, including one whose verification exceeds the deadline, cannot commit.

On timeout, EOF, rejected confirmation or exception after starting a write, the
helper attempts the inverse operation. The target must still match the expected
configuration; other settings must not have changed. It disables only that output
and verifies equality with the original snapshot. A configuration already equal
to the original is also verified as restored. Transient unavailable reads get a
bounded retry. Hot-unplug, conflicting changes or failed read-back yield an explicit
attention result, never a claim of recovery. Stale full configurations are not
replayed over user changes. Settings outside the activation scope are observed
where available but never written by BeamFix.

The helper ignores terminal-related signals and survives abrupt UI death; socket
EOF requests undo. It cannot survive SIGKILL, logout or compositor failure. No
on-disk recovery journal or reboot recovery is provided. Each KDE operation has a
five-second timeout; recovery can continue beyond the visual confirmation window.
KDE's command interface has no compare-and-swap transaction: reads and writes have
a small race window. Identical devices swapped between observations cannot be
distinguished by connector state. Users should leave cables and settings unchanged
during the attempt. Future backends must preserve these explicit boundaries.

Plans carry an explicit `backend` tag. `fix_backends.py` only selects KDE or GNOME
when the reported Linux Wayland desktop is unambiguous; it never tries another
desktop's write interface after a failure. The helper decodes the corresponding
plan type and uses that backend for the entire transaction. A `recovering` event
lets the UI wait for the bounded multi-call GNOME undo rather than assume the
shorter KDE operation time. The per-user lock is shared by both backends.

The guided summary includes the automatic attempt's recovery result and fresh
observations. Only `kept` resolves the session; refusal, undo or uncertain recovery
ends with exit `2`, with manual checks available on the next run. Tests include
real OS process death/IPC on simulated displays. Live configuration parsing has
been verified, but real-projector activation/undo remains open.

Restarting the graphical session, installing drivers and modifying system files
are outside this increment.

To add a rule, use a stable code, state the evidence, make uncertainty explicit
and add a test case that distinguishes a fault from a normal state.

## GNOME/Wayland activation

`gnome_fix.py` reads Mutter's `GetCurrentState` through `busctl --user --json=short`.
It validates the exact D-Bus signature and typed variant values; it never parses
human-readable GVariant text or evaluates tool output. Service autostart and
interactive authorization are disabled. An absent tool/service or a denied
`ApplyMonitorsConfigAllowed` property yields manual guidance. Each operation is
bounded by a bus timeout and a five-second process timeout. No Python D-Bus binding
is required at runtime. This follows Mutter's
[DisplayConfig interface](https://github.com/GNOME/mutter/blob/main/data/dbus-interfaces/org.gnome.Mutter.DisplayConfig.xml)
and [configuration implementation](https://github.com/GNOME/mutter/blob/main/src/backends/meta-monitor-manager.c).

The private state stores connected physical monitors, mode definitions, active
logical monitors, primary status, positions, transforms, scales, layout mode and
supported underscan/color/RGB settings. Volatile `is-current` flags become the
active logical mode; the serial stays outside the comparable state. A digest of
each monitor specification detects changed identity without retaining raw serial
or product strings in the plan. No raw identity or digest is reported or saved.

All connected monitors must match Linux uniquely, including inactive ones. The
only additional connector spelling normalization is native Mutter's `HDMI-N`
for Linux `HDMI-A-N`, as specified by its
[connector table](https://github.com/GNOME/mutter/blob/main/src/backends/meta-connector.c).
Normalization is checked for uniqueness on both sides, including disconnected
DRM connectors on other GPUs. Arbitrary aliases, output swaps, missing active
modes or conflicting observations are never guessed.

GNOME does not provide an inactive logical monitor to simply enable. The plan
therefore chooses exactly one advertised preferred, non-interlaced fixed-refresh
mode for the disabled target, uses its preferred supported scale (or the required
global scale), and places it adjacent to the rightmost active screen. Existing
screens retain their full logical configuration. Rotations and physical/logical
layout units are accounted for. Non-integral resulting dimensions, cloned logical
groups, leases, unknown logical settings, ambiguous modes and unknown color/RGB
settings are refused. The preview explains the resolution, scale, position and
session-only lifetime before authorization.

Each write reads permission and a fresh state/serial, requires equality with the
expected starting state, then submits the complete desired logical layout to
`ApplyMonitorsConfig` with method `0` (verify) and method `1` (temporary). Both
calls use the same fresh serial: a concurrent Mutter configuration change causes
rejection instead of replaying stale settings. Existing monitor properties and
layout mode are included where supported. Method `2` (persistent) is never used.
An accepted visual confirmation keeps the temporary configuration for the current
session; there is no native persistent-confirmation dialog or profile write.

Undo uses a new serial and the original logical layout, omitting the newly enabled
target. The shared helper verifies the complete state before and after undo. If
the inventory or settings differ, it reports uncertain recovery and does not
overwrite the intervening state. This remains subject to helper/compositor loss
and the other shared recovery limitations.

Tests cover native naming, mode/scale/layout validation, typed transport and serial
races. A fake Mutter service using test-only PyGObject runs on a separate real
D-Bus session to verify busctl encoding, property reads, apply/undo and rejection.
Both backend tags are tested through detached helper processes and UI death.
These tests are not evidence of successful projection or compatibility with every
GNOME version. A real GNOME session/projector test is still outstanding.

## Current-mode observation

Both commands use `collect_doctor`, which first runs the DRM collector. On Linux
KDE graphical sessions it queries `kscreen-doctor --json`. A structurally valid
KDE response is retained even when individual outputs are ambiguous or conflict
with DRM. If that query is unavailable or its top-level response cannot be read,
Linux Wayland sessions fall back to `wayland-info -i wl_output`. Other Wayland
desktops use that standard path directly; detection depends on session type,
not a desktop allowlist. Nongraphical and non-Linux sessions launch neither tool.
Only KDE is currently supported for active-mode observation on X11.

Each subprocess has no input, discards stderr and has a five-second timeout
(up to ten seconds when KDE times out before a Wayland fallback). The Wayland
query preserves the session environment and sets `LC_ALL=C` for text parsing.
Missing tools, failed queries and malformed data produce explicit unverified
results without losing the DRM snapshot. Nothing is installed automatically.

The guided troubleshooter repeats observation after each completed step, but not
after a skipped step. Descriptions retained in attempts include the current mode
and its provenance or an explicit inactive/unverified state. A mode-change step
uses only the selected connector's fresh observation and asks the user to check
it before making a manual change. Unknown modes do not block the basic guided
checks or change guided exit codes. Listed/reported modes never count as visual
success. No previous mode is reused when a later reading is unavailable.

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
`reported`, `inactive` or `unknown`), `source`, `reason`, and optional `mode` containing `width`,
`height` and `refresh_hz`. Existing `modes` still means the DRM names, without Hz.
An unknown current-mode observation returns exit code `2`; a listed mode never
sets `visual_confirmation` or proves the image is visible. No unsupported/red
classification is inferred from the available KDE data, including custom modes.
Raw desktop responses and unrelated identity/profile data are discarded.

### Standard Wayland boundaries

The adapter follows the [standard wl_output protocol](https://wayland.freedesktop.org/docs/html/apa.html#protocol-spec-wl_output)
through the installed `wayland-info` utility. Its human-readable output is not a
versioned data format: only recognized named `wl_output` blocks, mode dimensions,
Hz and `current` flags are accepted. Preferred modes and logical/scaled geometry
are not substituted for the current mode. Multiple current entries, invalid or
zero refresh, missing names and unfamiliar record layouts remain unknown.
Name matching strips only the DRM card prefix and requires uniqueness on both
sides; aliases and outputs without names are not guessed. A same-name match is
a correlation within the current session, not proof of persistent device identity.

A match requires Linux to report connected and enabled; conflicting or unknown
DRM state stays unknown. An output absent from Wayland is labelled inactive only
when DRM independently reports disabled/disconnected. Otherwise its mode is
unknown: `wl_output` is not an inventory of physical connectors. Virtual outputs
may advertise synthetic sizes or rates and are not added to the DRM inventory.

A readable mode uses the new JSON v1 state `reported`, source `wayland-info`, and
the existing `mode` shape. Consumers must handle this additional state. This
means reported by the session, not verified against an available-mode list; it
is shown with a neutral `REPORTED` label. Like `listed`, it does not itself make
`doctor` return `2` or provide visual confirmation. Raw output, descriptions,
make/model and unrelated interface data are discarded. The DRM mode list is
preserved independently. No output-management or settings changes are performed.

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

## KDE mode sequences

`kde_modes.py` uses the shared KDE validation with an enabled external target
and another active screen independently verified against DRM. It builds up to
five `ModePlan` values sharing one original configuration. Candidate selection
excludes the current resolution/refresh pair, exact duplicate pairs, unsafe mode
IDs, fractional logical sizes and overlaps with other active screens. It orders
by refresh distance from 60 Hz, then sizes up to 1080p, descending pixel area and
ID. Selection is deterministic even if the mode list is reordered.

Each plan changes only `currentModeId`. Positions, scales, rotations, activation,
priority and all other captured controls remain part of the expected-state
comparison. `KDEModeBackend` rebuilds the candidate after approval, rereads the
state immediately before each write, and applies or restores one exact mode ID
with `output.NAME.mode.ID`. The command syntax and ID lookup follow
[KDE doctor](https://github.com/KDE/libkscreen/blob/master/src/doctor/doctor.cpp).
Mode IDs containing CLI separators are refused rather than substituted with a
size/refresh string. The command has a five-second limit and no shell. KDE's
read/write race and device-identity limitations still apply; no promise about
persistence across sessions is made.

`ModePlan.action = "mode"` is explicit in the worker message. Unknown action and
backend combinations are rejected. Activation plans retain their existing wire
shape. `change` dispatches the worker's write and inverse operation by action;
all actions share the independent deadline, lock, fresh checks and recovery.

For a mode trial, the worker returns `next` only after receiving a timely Next
and verifying rollback. The terminal client cannot turn timeout or ordinary undo
into permission for another trial. `run_mode_sequence` advances only on that
status; other statuses end the sequence, and final Next yields `exhausted` after
verified restoration. It requires every plan to share the same target/backend
and original configuration. Each worker acquires the shared lock and revalidates
its plan; intervening changes between workers cause refusal. Summary details
retain every attempted mode and result, without saving a report automatically.

The sequence and terminal decisions are shared orchestration. `mode_trials.py`
owns the common limit, ranking and overlap check. Backend selection routes KDE
and GNOME explicitly, without cross-desktop fallback. Tests exercise simulated
state, real terminal input, sockets, helper timeout, terminal death, restoration
and exhaustion. They do not establish physical projector behavior.

## GNOME mode sequences

`gnome_modes.py` builds `GNOMEModePlan` objects using the shared GNOME inventory
validation with an already active external target and another verified active
screen. The plan changes only the target logical monitor's mode ID. The original
layout, identities, monitor inventory, supported modes, scale, transforms,
primary status, color/underscan/RGB settings and inactive outputs remain in the
before/expected comparison. Volatile current flags and serials stay outside it.

Candidates are distinct resolution/refresh pairs, skipping the current pair,
interlaced modes, variable-refresh modes and modes that do not support the
existing scale. `logical_size` handles rotated and physical/logical layouts.
Each candidate must have integral, bounded logical dimensions, no overlapping
rectangles and one connected graph of screens sharing edges of positive length.
This conservative check skips size changes that create gaps without moving other
screens. Mutter's verification remains authoritative for hardware limits and
other configuration constraints; a rejected verification ends the sequence.

`GNOMEModeBackend` rebuilds the selected candidate before each trial. It shares
`GNOMEBackend.apply_change` with activation: read permission and a fresh state,
require the expected starting layout, verify the desired layout with method 0,
then apply it temporarily with method 1 and the same fresh serial. Undo submits
the complete original layout with a newly read serial. Method 2 is never used.
The API contracts are defined by Mutter's
[DisplayConfig interface](https://github.com/GNOME/mutter/blob/main/data/dbus-interfaces/org.gnome.Mutter.DisplayConfig.xml).
Mode IDs are typed D-Bus string arguments, including IDs with punctuation or
leading hyphens; they are not interpreted as shell code or command-line options.

The worker routes `backend=gnome, action=mode` to this backend while retaining the
shared lock, deadline and explicit-next recovery contract. A fresh identity or
mode list mismatch invalidates the preview. Failed undo or changed external
state yields attention and never advances. The terminal preview names GNOME and
explains the session-only change; default troubleshooting and X11 remain manual.

Tests cover fixed/variable/interlaced modes, scale constraints, primary displays,
rotations, physical layouts, overlap/gaps, stale serials, denied writes, explicit
next, exhaustion and helper death. The private-bus harness additionally runs a
full detached sequence through production busctl calls to a fake Mutter service,
verifying Next/Keep, cancellation and refusal of a swapped device. This verifies
transport and orchestration, not a live GNOME compositor or physical projector.
The Fedora Workstation/GNOME field checklist remains pending.


## Optional DRM signal observation (0.3.5)

`collect_doctor` adds `signal.py` after the existing mode observation. Its optional
`drm_info -j` subprocess reads DRM state without a shell, stdin, privilege
escalation or modesetting. A five-second timeout, output-size validation, strict
JSON parsing (including duplicate-key rejection), and field validation preserve
basic diagnostics when the helper fails. Supplemental availability does not change
the basic doctor exit code. The additive `Connector.signal` object retains its own
coverage states. It is not consumed by repair planners.

Matching uses an exact `/dev/dri/cardN` key plus the `connector_id` read from the
corresponding sysfs directory. It never joins by display names, ordering or EDID.
Sysfs ID/status/enabled observations bracket the query and must agree with the
snapshot. A changed or ambiguous identity is rejected. These are sequential reads,
not an atomic hardware snapshot: identical replacements or changes away and back
between reads cannot be excluded.

Current timings require a unique connector CRTC_ID, a unique CRTC and ACTIVE=1.
They are checked against desktop resolution/Hz when available. A listed mode is
never substituted for unavailable current timing. Clock is in kHz; nominal Hz is
calculated from the timing totals with interlace/doublescan/vscan accounted for.
All timing fields and flags survive exact deduplication, including alternatives
with the same nominal resolution/Hz. Raw mode names and mode-type preference flags
are omitted; the repair sequence is unchanged.

An allowlist admits only max bpc, Colorspace, color format, Broadcast RGB,
HDR_OUTPUT_METADATA presence, Content Protection, HDCP Content Type and link-status.
The HDR blob reference becomes a boolean; no blob contents or ID is retained.
Properties carry source, interpretation, state and a note. The actual_bpc field
is explicitly unavailable. Neither AUTO values nor missing values are interpreted
as concrete transmitted formats. EDID, serials, device metadata, arbitrary
properties, framebuffer details and raw responses are never serialized.

Doctor accepts optional enumerated --visual-result and --connection annotations,
placed in user_context with source=user_reported. They do not alter findings,
exit codes or visual_confirmation=not_performed. Guided summaries show signal
observations alongside initial/latest enabled outputs. JSON includes all listed
detailed timings for manual comparison of failed and working sessions.

Contracts consulted:
- [drm_info JSON serializer](https://gitlab.freedesktop.org/emersion/drm_info/-/blob/master/json.c)
- [drm_info command interface](https://gitlab.freedesktop.org/emersion/drm_info/-/blob/master/main.c)
- [Linux DRM connector properties](https://www.kernel.org/doc/html/latest/gpu/drm-kms.html#standard-connector-properties)
- [Linux connector sysfs implementation](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_sysfs.c)

Live read-only verification on the development KDE computer used a temporary
build of upstream drm_info 2.10.0. It reported an active HDMI timing and properties,
34 listed timings, and an inactive built-in screen. It did not verify projection,
Fedora/GNOME behavior or actual transmitted color depth. The optional helper is
not bundled with BeamFix.

## Optional local graphical interface (0.4.0)

`gui.py` provides a loopback-only HTTP transport and explicit guided state machine.
It reuses `collect_doctor`, `diagnose`, troubleshooting steps and backend planners.
`web/` holds dependency-free HTML, CSS, JavaScript and SVG situation illustrations.
The CLI imports the GUI only for `gui`; diagnostics and terminal troubleshooting
continue without a browser or GUI server.

A lock serializes state transitions. Each request carries a session revision;
confirmation additionally requires the current trial nonce and an unexpired
worker deadline. Preview stores server-owned plans. Apply runs the existing
`automatic` client on a background thread; the independent recovery worker and
its IPC contract are unchanged. Missing browser heartbeats cancel confirmation,
and a guarded sequence refuses another trial after cancellation. No server API
accepts arbitrary commands, shell text or a client-created display plan.

The HTTP handler serves allowlisted packaged assets, requires a per-launch header
secret for APIs, validates Host/Origin, restricts request size and sets CSP.
The GUI report keeps observed diagnostics separate from reported visual results.
Packaging includes the assets in wheels and in a pure-Python portable bundle;
its user installer adds independent command and desktop-menu entry points.
