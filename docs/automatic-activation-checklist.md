# KDE and GNOME Wayland automatic activation: field checklist

Status: pending real-projector validation. Automated tests use simulated displays.

Use a KDE/Wayland session with `kscreen-doctor`, or GNOME/Wayland with `busctl`
and an accessible Mutter DisplayConfig service. Keep a visible working screen and
a connected external projector disabled in Display settings. Keep the same
connection throughout each attempt. KDE requires a retained configured mode;
GNOME requires one preferred mode and a supported scale. Otherwise the tool should
offer manual instructions. Record KDE and GNOME results separately.

Run `python3 -m beamfix troubleshoot --try-fix` from the project directory.

1. Select the projector explicitly. Check that the preview names the correct
   output and resolution/Hz. On GNOME, also check the proposed scale and position
   to the right, and that the change is described as temporary for this session.
   Choosing manual or skip must not change it.
2. Try activation. Confirm the working screen stays active and its position,
   scaling, rotation and resolution remain as before. Verify the projector image.
3. Answer `1` and Enter before the deadline. The output should remain active and
   the summary should explicitly report visual confirmation.
4. Reset the projector to disabled manually. Repeat and choose `2`; check that
   the output is disabled again and the original configuration is verified.
5. Repeat without answering. Check undo after the confirmation window. Repeat
   once more and close the terminal while the confirmation question is visible.
6. Test a disconnected projector and an already enabled output: neither is an
   eligible target for this activation action. The internal panel is never a target.
7. During a separate controlled attempt, disconnect the projector. Expect an
   explicit unverified recovery/changed-connection result, with no write directed
   at another output. Inspect Display settings before reconnecting or retrying.
8. During a separate controlled attempt, change another display setting. Expect
   the helper to withhold stale undo and report that manual inspection is needed.

9. On GNOME, check that the existing primary screen stays primary and that existing
   fractional scaling/rotation are preserved. Check the HDMI name mapping if the
   Linux connector is `HDMI-A-N` while GNOME reports `HDMI-N`.
10. On GNOME, verify that the successful attempt is temporary and does not rewrite
    the saved display profile. GNOME X11 must fall back to manual guidance.

Record desktop/Plasma/GNOME version, GPU/driver, projector, connection type (including
adapters), retained/preferred mode, observed result and any recovery failure. Do not mark
this checklist complete based only on simulated tests or live read-only parsing.

## KDE and GNOME mode-sequence field checks (0.3.3)

Status: pending physical validation. Both mode backends are implemented.
The planned portable field-test system is Fedora Workstation with GNOME.
Record the actual Fedora and GNOME versions. Use BeamFix 0.3.3 or later,
GNOME Wayland and `busctl` with JSON support (or KDE Wayland with `kscreen-doctor`).
The activation checks above remain applicable independently.

Use a connected, enabled external projector and another active screen. Put the
terminal on the other screen. Use a separate-screen layout, without cloning.
Run `python3 -m beamfix troubleshoot --try-fix`, report No signal or black screen,
and complete or skip the input check to reach the mode preview.

1. Check that the preview names only the selected external output, has no more
   than five distinct alternatives, and excludes its current resolution/Hz pair.
   Choosing manual or skip must not write display settings.
2. Start a trial. Check the actual projector resolution/Hz and confirm that the
   other screen's mode, position, scale, rotation and primary status remain unchanged.
3. Choose Next. Verify restoration to the original mode before the next trial.
   Confirm a later trial with 1 and Enter; only that confirmed mode should remain.
4. Restart from a known baseline and test Stop, silence, Ctrl+C and terminal
   closure separately. Each must restore and end the sequence, never advance.
5. Reject all candidates with Next. Check that the original configuration is
   restored, the summary lists every trial and no visual success is claimed.
6. In separate controlled attempts, disconnect the projector or change a display
   setting. Check that the sequence stops and reports changed/uncertain state;
   it must not apply another candidate or overwrite unrelated settings.
7. Record projector switching/settling time. If 15 seconds is too short to judge
   the image reliably, record that as a usability failure for follow-up.

8. On GNOME, verify that the selected mode supports the existing scale and that
   fractional scaling, rotation, primary screen and positions remain unchanged.
   A layout with the projector to the left may exclude smaller resolutions to
   avoid a gap; manual fallback with no eligible candidate is an expected result.
9. On GNOME, check that confirmed changes remain temporary for the session and
   that BeamFix does not rewrite the saved display profile. Test denial or an
   unsupported session: manual guidance must remain available without KDE writes.

Record mode order, each visual outcome and every undo result. Simulated tests
alone do not complete these checks.

## Shared classroom-system checks (0.3.4)

Status: pending on the portable Fedora Workstation GNOME computer and a real
classroom system. Simulated tests do not establish physical compatibility.

1. Describe the actual connection, or choose unknown. Select the computer output
   feeding the classroom system; do not assume each physical display is listed.
2. If room monitors work but the projector does not, choose that symptom. Check
   room source/projector blank controls if accessible, then reach mode trials.
   Do not change installed classroom wiring. Confirm that laptop mirroring is
   not offered for this symptom.
3. For each completed manual step or automatic trial, record what appears on the
   projector separately from the room monitors. Only a correct projector image
   should receive a success confirmation. Record any effect on the room monitors.
4. Measure time from a mode change to a stable projector image. Record delayed
   relocking and transient connection changes. If 15 seconds is insufficient,
   let the attempt restore and stop; record this as an unresolved usability issue.
5. Check the summary's initial symptom, initial/latest user-reported connection,
   computer output counts, modes, visual results and automatic recovery details.
   The output count must not be presented as the physical room display count.
6. If a direct connection is accessible, perform that manual test and describe
   the new path when prompted. Verify the initial room context remains in the
   summary. Skip this test when it requires inaccessible equipment or changing
   installed classroom wiring.

## Read-only signal report checks (0.3.5)

Use the actual Fedora Workstation GNOME classroom computer. Ensure the optional
`drm_info` tool is available in the same terminal environment as BeamFix.

**Before the classroom visit:** explicitly mention the `drm_info` requirement in
setup/handoff instructions and check its availability on the portable computer.
BeamFix's Python installation does not install it. If it is missing, basic
diagnostics still work, but signal properties and detailed timings are unavailable.

1. Collect `beamfix doctor --json --connection room --visual-result room_monitors_only`
   while the projector fails but room monitors work. Redirect the output to a file
   if you want to retain it. Use the actual symptom/path if different.
2. When the projector actually works, collect a second report with
   `--visual-result projector_visible`; record any changed cables/ports/room controls.
3. Check each connector's signal coverage before comparing values. Missing data
   must not turn into zero, RGB, eight-bit output, SDR or disabled HDCP assumptions.
4. Compare configured timings, property requests/limits and driver statuses.
   Preserve timing variants at equal resolution/Hz; distinguish listed from current.
5. Record Fedora/GNOME version, driver, drm_info version and any unavailable fields.
   A difference is an investigative lead, not proof of causation. These reports do
   not measure the signal received by a projector hidden behind classroom equipment.
