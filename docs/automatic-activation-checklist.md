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

## KDE mode-sequence field checks (0.3.2)

Status: pending. GNOME mode sequences are not implemented yet; the planned
portable field-test system is Fedora Workstation with GNOME. Complete the GNOME
mode backend before using this sequence checklist on that computer. The GNOME
activation checks above remain applicable independently.

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

Record mode order, each visual outcome and every undo result. Simulated tests
alone do not complete these checks.
