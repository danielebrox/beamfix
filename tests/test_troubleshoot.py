import contextlib
import io
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from beamfix.cli import main
from beamfix.models import Connector, CurrentMode, Snapshot, VideoMode
from beamfix.troubleshoot import describe, next_step, run


def port(name="card0-HDMI-A-1", status="connected", enabled="enabled", modes=("1920x1080",), kind="external"):
    return Connector(name, kind, status, enabled, modes)


def snapshot(*ports, errors=()):
    return Snapshot("Linux", "test", "wayland", "KDE", connectors=list(ports), errors=list(errors))


def with_mode(width=1920, height=1080, rate=60):
    return replace(port(), current_mode=CurrentMode(
        "listed", "kscreen-doctor", "Current mode is listed as available by KDE.",
        VideoMode(width, height, rate),
    ))


class PlanningTests(unittest.TestCase):
    def plan(self, connector, symptom="no_signal", tried=()):
        return next_step(snapshot(connector), connector.name, symptom, set(tried))

    def test_disconnected_does_not_offer_desktop_changes(self):
        c = port(status="disconnected", enabled="disabled", modes=())
        tried = set()
        while step := self.plan(c, tried=tried):
            self.assertIn(step.code, {"input", "reconnect", "direct", "cable"})
            tried.add(step.code)
        self.assertEqual(len(tried), 4)

    def test_unknown_is_not_treated_as_disconnected(self):
        c = port(status="unknown")
        self.assertEqual(self.plan(c).code, "refresh")
        self.assertIsNone(self.plan(c, tried={"refresh"}))

    def test_missing_modes_are_distinct_from_empty(self):
        self.assertEqual(self.plan(port(modes=None)).code, "refresh")
        self.assertEqual(self.plan(port(modes=())).code, "reconnect")

    def test_inactive_output_first_requires_activation(self):
        c = port(enabled="disabled")
        self.assertEqual(self.plan(c).code, "activate")
        self.assertEqual(self.plan(c, tried={"activate"}).code, "reconnect")

    def test_desktop_symptom_targets_presentation(self):
        self.assertEqual(self.plan(port(), "desktop").code, "presentation")
        self.assertEqual(self.plan(port(), "desktop", {"presentation"}).code, "mirror")
        self.assertIsNone(self.plan(port(), "desktop", {"presentation", "mirror"}))

    def test_unidentified_target_does_not_use_another_monitor(self):
        data = snapshot(port(enabled="disabled"))
        self.assertEqual(next_step(data, None, "black", set()).code, "input")

    def test_internal_panel_is_not_a_target(self):
        data = snapshot(port(name="card0-eDP-1", kind="internal"))
        self.assertEqual(next_step(data, None, "black", set()).code, "refresh")

    def test_mode_step_uses_selected_output_and_fresh_rate(self):
        selected = replace(with_mode(rate=59.94), name="card1-DP-1")
        data = snapshot(with_mode(3840, 2160, 144), selected)
        step = next_step(data, selected.name, "black", {"input", "mirror"})
        self.assertEqual(step.code, "mode")
        self.assertIn("1920 x 1080 @ 59.94 Hz", step.reason)
        self.assertIn("still 1920 x 1080 @ 59.94 Hz", step.instruction)
        self.assertNotIn("3840", step.instruction)
        self.assertNotIn("does not know", step.reason)

    def test_unverified_mode_keeps_manual_guidance(self):
        for observation in (None, CurrentMode("unknown", "kscreen-doctor", "KDE unavailable.")):
            with self.subTest(observation=observation):
                step = self.plan(replace(port(), current_mode=observation), tried={"input", "mirror"})
                self.assertEqual(step.code, "mode")
                self.assertIn("does not know", step.reason)
                self.assertIn("note the current mode", step.instruction)

    def test_inactive_mode_does_not_show_retained_resolution(self):
        c = replace(port(enabled="disabled"), current_mode=CurrentMode(
            "inactive", "kscreen-doctor", "Disabled", VideoMode(1920, 1080, 60)))
        self.assertEqual(self.plan(c).code, "activate")
        description = describe(snapshot(c), c.name)
        self.assertIn("Current mode: inactive", description)
        self.assertNotIn("60.00 Hz", description)

    def test_unknown_mode_shows_reason_without_retained_values(self):
        c = replace(port(), current_mode=CurrentMode(
            "unknown", "kscreen-doctor", "No unique KDE output matches this Linux connector.",
            VideoMode(1920, 1080, 60)))
        description = describe(snapshot(c), c.name)
        self.assertIn("Current mode: unverified", description)
        self.assertIn("No unique KDE output", description)
        self.assertNotIn("60.00 Hz", description)


class GuidedSessionTests(unittest.TestCase):
    def session(self, snapshots, answers):
        output = []
        reader = Mock(side_effect=snapshots)
        answer_iter = iter(answers)

        def read(prompt):
            try:
                value = next(answer_iter)
            except StopIteration:
                self.fail("Unexpected extra question: " + "\n".join(output))
            if isinstance(value, BaseException):
                raise value
            return value

        code = run(snapshot_reader=reader, read=read, write=output.append)
        return code, "\n".join(output), reader.call_count

    def test_activation_confirmed_by_user(self):
        code, output, reads = self.session(
            [snapshot(port(enabled="disabled")), snapshot(port())], ["1", "1", "1", "1"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(reads, 2)
        self.assertIn("Expected image confirmed by the user", output)
        self.assertIn("Before: 'card0-HDMI-A-1': connected, output disabled", output)
        self.assertIn("After: 'card0-HDMI-A-1': connected, output enabled", output)

    def test_summary_preserves_resolution_and_rate_before_and_after(self):
        code, output, reads = self.session(
            [snapshot(with_mode(3840, 2160, 30)), snapshot(with_mode(1920, 1080, 59.94))],
            ["2", "1", "2", "2", "1", "1"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(reads, 2)
        summary = " ".join(output.split("SUMMARY", 1)[1].split())
        self.assertIn("Current mode: 3840 x 2160 @ 30.00 Hz", summary)
        self.assertIn("Current mode: 1920 x 1080 @ 59.94 Hz", summary)
        self.assertIn("Visual result: expected image confirmed", summary)

    def test_known_mode_never_confirms_visual_success(self):
        data = snapshot(with_mode())
        code, output, _ = self.session([data, data], ["2", "1", "1", "5"])
        self.assertEqual(code, 2)
        self.assertIn("Visual result: cannot be verified", output)
        self.assertNotIn("Expected image confirmed by the user", output)

    def test_lost_mode_observation_does_not_reuse_previous_mode(self):
        unknown = replace(port(), current_mode=CurrentMode("unknown", "kscreen-doctor", "KDE unavailable."))
        code, output, _ = self.session(
            [snapshot(with_mode()), snapshot(unknown)], ["2", "1", "1", "3", "2", "0"],
        )
        self.assertEqual(code, 2)
        after = " ".join(output.split("New reading:", 1)[1].split("VERIFY", 1)[0].split())
        self.assertIn("Current mode: unverified. KDE unavailable.", after)
        self.assertIn("does not know the resolution", after)

    def test_unavailable_kde_does_not_block_visual_confirmation(self):
        unknown = replace(port(), current_mode=CurrentMode("unknown", "kscreen-doctor", "KDE unavailable."))
        data = snapshot(unknown)
        code, output, reads = self.session([data, data], ["2", "1", "1", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(reads, 2)
        self.assertIn("Expected image confirmed by the user", output)

    def test_default_reader_refreshes_desktop_modes_after_action(self):
        answers = iter(["2", "1", "1", "1"])
        with patch("beamfix.desktop.collect", side_effect=[snapshot(port()), snapshot(port())]) as drm, \
                patch("beamfix.desktop.add_current_modes", side_effect=[
                    snapshot(with_mode(rate=30)), snapshot(with_mode(rate=60)),
                ]) as desktop:
            output = []
            self.assertEqual(run(read=lambda _: next(answers), write=output.append), 0)
        self.assertEqual(drm.call_count, 2)
        self.assertEqual(desktop.call_count, 2)
        text = " ".join("\n".join(output).split())
        self.assertIn("@ 30.00 Hz", text)
        self.assertIn("@ 60.00 Hz", text)

    def test_enabled_output_does_not_count_as_visual_success(self):
        code, output, reads = self.session(
            [snapshot(port(enabled="disabled")), snapshot(port())],
            ["1", "1", "1", "3", "0"],
        )
        self.assertEqual(code, 2)
        self.assertEqual(reads, 2)
        self.assertNotIn("Expected image confirmed by the user", output)
        self.assertIn("The projected screen is black", output)

    def test_failed_activation_is_not_repeated(self):
        data = snapshot(port(enabled="disabled"))
        code, output, reads = self.session([data, data], ["1", "1", "1", "2", "2", "2", "2"])
        self.assertEqual(code, 1)
        self.assertEqual(reads, 2)
        self.assertEqual(output.count("Step: Enable the output"), 1)
        self.assertIn("skipped, not verified", output)

    def test_reconnect_changes_next_step_to_activation(self):
        code, output, reads = self.session(
            [snapshot(port(status="disconnected", enabled="disabled", modes=())),
             snapshot(port(enabled="disabled")), snapshot(port())],
            ["1", "1", "2", "1", "2", "1", "1"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(reads, 3)
        self.assertIn("Step: Enable the output", output)

    def test_symptom_change_routes_to_presentation(self):
        data = snapshot(port())
        code, output, reads = self.session([data, data, data], ["1", "1", "1", "4", "1", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(reads, 3)
        self.assertIn("Step: Show the presentation", output)

    def test_selects_one_of_several_displays(self):
        data = snapshot(port(), port(name="card1-DP-1", enabled="disabled"))
        code, output, _ = self.session([data], ["1", "2", "0"])
        self.assertEqual(code, 2)
        self.assertIn("Observed state: 'card1-DP-1'", output)
        self.assertIn("Step: Enable the output", output)

    def test_unknown_target_keeps_uncertainty(self):
        code, output, _ = self.session([snapshot(port())], ["1", "2", "2", "2", "2", "2"])
        self.assertEqual(code, 2)
        self.assertIn("Insufficient data", output)
        self.assertNotIn("Step: Enable", output)

    def test_missing_drm_does_not_claim_success(self):
        data = snapshot(errors=["DRM unavailable"])
        code, output, reads = self.session([data, data], ["1", "1", "2"])
        self.assertEqual(code, 2)
        self.assertEqual(reads, 2)
        self.assertIn("Insufficient data", output)
        self.assertIn("data are missing", output)

    def test_visual_result_can_be_confirmed_despite_incomplete_data(self):
        data = snapshot(errors=["DRM unavailable"])
        code, output, _ = self.session([data, data], ["1", "1", "1"])
        self.assertEqual(code, 0)
        self.assertIn("data are missing", output)

    def test_unknown_state_gets_one_refresh(self):
        data = snapshot(port(status="unknown"))
        code, output, reads = self.session([data, data], ["1", "1", "1", "2"])
        self.assertEqual(code, 2)
        self.assertEqual(reads, 2)
        self.assertEqual(output.count("Step: Read the data again"), 1)

    def test_no_visual_verification_is_not_success(self):
        data = snapshot(port())
        code, output, _ = self.session([data, data], ["2", "1", "1", "5"])
        self.assertEqual(code, 2)
        self.assertIn("Visual result: cannot be verified", output)

    def test_hotplug_requires_explicit_new_target(self):
        old = snapshot(port())
        new = snapshot(port(name="card1-DP-1", enabled="disabled"))
        code, output, _ = self.session([old, new], ["1", "1", "1", "1", "2", "0"])
        self.assertEqual(code, 2)
        self.assertIn("identify the projector again", output)
        self.assertIn("Step: Enable the output", output)

    def test_moving_to_another_port_requires_reselection(self):
        old = snapshot(port(), port(name="card1-DP-1", status="disconnected", enabled="disabled"))
        new = snapshot(port(status="disconnected"), port(name="card1-DP-1", enabled="disabled"))
        code, output, _ = self.session([old, new], ["1", "1", "1", "2", "2", "0"])
        self.assertEqual(code, 2)
        self.assertIn("identify the projector again", output)
        self.assertIn("Observed state: 'card1-DP-1'", output)

    def test_skips_do_not_rescan_or_repeat(self):
        data = snapshot(port())
        code, output, reads = self.session([data], ["2", "1"] + ["2"] * 6)
        self.assertEqual(code, 1)
        self.assertEqual(reads, 1)
        self.assertEqual(output.count("Step: "), 6)

    def test_eof_and_keyboard_interrupt_produce_summary(self):
        for interruption in (EOFError(), KeyboardInterrupt()):
            with self.subTest(interruption=type(interruption)):
                code, output, reads = self.session([], [interruption])
                self.assertEqual(code, 2)
                self.assertEqual(reads, 0)
                self.assertIn("Troubleshooting interrupted", output)

    def test_interruption_after_action_preserves_attempt(self):
        data = snapshot(port())
        code, output, _ = self.session([data, data], ["1", "1", "1", EOFError()])
        self.assertEqual(code, 2)
        self.assertIn("Check power and input: performed", output)
        self.assertIn("Visual result: not confirmed", output)

    def test_invalid_answers_reprompt_without_losing_state(self):
        code, output, reads = self.session([], ["abc", "-1", "99", "0"])
        self.assertEqual(code, 2)
        self.assertEqual(reads, 0)
        self.assertEqual(output.count("Enter the number"), 3)

    def test_cli_dispatch_and_exit_code(self):
        with patch("beamfix.troubleshoot.run", return_value=1) as guided:
            self.assertEqual(main(["troubleshoot"]), 1)
            guided.assert_called_once_with(plain=False, try_fix=False)

    def test_existing_doctor_still_available(self):
        with patch("beamfix.cli.collect", return_value=snapshot(port())), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["doctor", "--json"]), 0)
        self.assertIn('"visual_confirmation": "not_performed"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
