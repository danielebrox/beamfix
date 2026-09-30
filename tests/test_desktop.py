import contextlib
import io
import json
import subprocess
import unittest
from dataclasses import asdict
from unittest.mock import patch

from beamfix.cli import main
from beamfix.desktop import add_current_modes, apply_kde_modes
from beamfix.models import Connector, Snapshot
from beamfix.terminal import Terminal, render_doctor


def snapshot(*connectors):
    return Snapshot("Linux", "test", "wayland", "KDE", connectors=list(connectors) or [
        Connector("card0-HDMI-A-1", "external", "connected", "enabled", ("1920x1080",)),
    ])


def mode(identifier="1", width=1920, height=1080, rate=59.94):
    return {"id": identifier, "size": {"width": width, "height": height}, "refreshRate": rate}


def output(**changes):
    data = {"name": "HDMI-A-1", "connected": True, "enabled": True,
            "currentModeId": "1", "modes": [mode()]}
    data.update(changes)
    return data


class ModeObservationTests(unittest.TestCase):
    def observe(self, raw, data=None):
        return apply_kde_modes(data or snapshot(), {"outputs": [raw]}).connectors[0].current_mode

    def test_resolution_and_rate_are_one_current_mode(self):
        observation = self.observe(output(modes=[mode(), mode("2", rate=60), mode("3", rate=120)]))
        self.assertEqual(observation.state, "listed")
        self.assertEqual((observation.mode.width, observation.mode.height, observation.mode.refresh_hz),
                         (1920, 1080, 59.94))

    def test_current_mode_id_wins_over_preferred_mode_and_size(self):
        observation = self.observe(output(
            currentModeId="2", modes=[mode(), mode("2", 3840, 2160, 60)], preferredModes=["1"],
            size={"width": 1920, "height": 1080}, scale=2, rotation=2,
        ))
        self.assertEqual((observation.mode.width, observation.mode.height), (3840, 2160))

    def test_disabled_panel_does_not_report_retained_mode_as_active(self):
        data = snapshot(Connector("card0-eDP-1", "internal", "connected", "disabled", ("1920x1080",)))
        observation = self.observe(output(name="eDP-1", enabled=False, modes=[mode(rate=144.003)]), data)
        self.assertEqual(observation.state, "inactive")
        self.assertIsNone(observation.mode)

    def test_disconnected_output_is_inactive(self):
        data = snapshot(Connector("card0-HDMI-A-1", "external", "disconnected", "disabled", ()))
        observation = self.observe(output(connected=False, enabled=False), data)
        self.assertEqual(observation.state, "inactive")

    def test_unlisted_current_id_is_unknown_not_unsupported(self):
        observation = self.observe(output(currentModeId="custom"))
        self.assertEqual(observation.state, "unknown")
        self.assertIsNone(observation.mode)

    def test_custom_modes_are_only_claimed_as_listed_by_kde(self):
        custom = mode()
        custom["custom"] = True
        observation = self.observe(output(modes=[custom]))
        self.assertEqual(observation.state, "listed")
        self.assertIn("KDE", observation.reason)
        self.assertNotIn("supported", observation.reason)

    def test_duplicate_mode_ids_are_ambiguous(self):
        self.assertEqual(self.observe(output(modes=[mode(), mode(rate=120)])).state, "unknown")

    def test_invalid_modes_never_become_green(self):
        invalid = [None, {}, mode(width=0), mode(height=-1), mode(width=True), mode(width="1920"),
                   mode(rate=True), mode(rate="60"), mode(rate=0), mode(rate=-1),
                   mode(rate=float("nan")), mode(rate=float("inf")), mode(rate=10**400)]
        for item in invalid:
            with self.subTest(item=item):
                self.assertEqual(self.observe(output(modes=[item])).state, "unknown")

    def test_missing_and_malformed_fields_keep_uncertainty(self):
        for changes in ({"currentModeId": None}, {"modes": None}, {"modes": {}},
                        {"connected": "true"}, {"enabled": 1}, {"enabled": None}):
            with self.subTest(changes=changes):
                self.assertEqual(self.observe(output(**changes)).state, "unknown")
        for payload in (None, [], {}, {"outputs": None}, {"outputs": [None]}, {"outputs": []}):
            with self.subTest(payload=payload):
                self.assertEqual(apply_kde_modes(snapshot(), payload).connectors[0].current_mode.state, "unknown")

    def test_duplicate_connector_names_across_gpus_are_not_guessed(self):
        data = snapshot(
            Connector("card0-HDMI-A-1", "external", "connected", "enabled", ()),
            Connector("card1-HDMI-A-1", "external", "connected", "enabled", ()),
        )
        apply_kde_modes(data, {"outputs": [output()]})
        self.assertTrue(all(c.current_mode.state == "unknown" for c in data.connectors))

    def test_duplicate_desktop_outputs_are_not_guessed(self):
        data = apply_kde_modes(snapshot(), {"outputs": [output(), output()]})
        self.assertEqual(data.connectors[0].current_mode.state, "unknown")

    def test_x11_alias_is_not_assumed_to_match_drm_name(self):
        self.assertEqual(self.observe(output(name="HDMI-0")).state, "unknown")

    def test_conflicting_connection_or_enablement_is_unknown(self):
        for raw in (output(connected=False), output(enabled=False)):
            self.assertEqual(self.observe(raw).state, "unknown")

    def test_unique_outputs_receive_their_own_modes(self):
        data = snapshot(
            Connector("card0-HDMI-A-1", "external", "connected", "enabled", ()),
            Connector("card1-DP-1", "external", "connected", "enabled", ()),
        )
        apply_kde_modes(data, {"outputs": [output(name="DP-1", modes=[mode(rate=144)]), output()]})
        self.assertEqual([c.current_mode.mode.refresh_hz for c in data.connectors], [59.94, 144])

    def test_raw_private_fields_are_not_retained(self):
        raw = output(edid="PRIVATE_EDID", serial="PRIVATE_SERIAL", iccProfilePath="PRIVATE_PATH")
        data = apply_kde_modes(snapshot(), {"outputs": [raw]})
        self.assertNotIn("PRIVATE", json.dumps(asdict(data)))


class DesktopQueryTests(unittest.TestCase):
    @patch("beamfix.desktop.subprocess.run")
    @patch("beamfix.desktop.shutil.which", return_value="/usr/bin/kscreen-doctor")
    def test_only_json_read_is_executed_with_timeout(self, which, run):
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps({"outputs": [output()]}))
        data = add_current_modes(snapshot())
        self.assertEqual(data.connectors[0].current_mode.state, "listed")
        run.assert_called_once_with(["/usr/bin/kscreen-doctor", "--json"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, encoding="utf-8", timeout=5, check=False)

    @patch("beamfix.desktop.subprocess.run")
    def test_other_desktops_and_headless_sessions_do_not_spawn_kde(self, run):
        for desktop, session, system in (("GNOME", "x11", "Linux"), ("KDE", "tty", "Linux"),
                                          ("KDE", "wayland", "Darwin"), ("NotKDE", "x11", "Linux")):
            data = snapshot()
            data.desktop, data.session, data.system = desktop, session, system
            self.assertEqual(add_current_modes(data).connectors[0].current_mode.state, "unknown")
        run.assert_not_called()

    @patch("beamfix.desktop.subprocess.run")
    @patch("beamfix.desktop.shutil.which", return_value=None)
    def test_missing_tool_preserves_drm(self, which, run):
        data = add_current_modes(snapshot())
        self.assertEqual(data.connectors[0].status, "connected")
        self.assertEqual(data.connectors[0].current_mode.state, "unknown")
        run.assert_not_called()

    @patch("beamfix.desktop.shutil.which", return_value="/usr/bin/kscreen-doctor")
    def test_failures_leave_basic_diagnostics_available(self, which):
        failures = [subprocess.TimeoutExpired("kscreen-doctor", 5), OSError(), UnicodeError()]
        for failure in failures:
            with self.subTest(failure=type(failure)), patch("beamfix.desktop.subprocess.run", side_effect=failure):
                data = add_current_modes(snapshot())
                self.assertEqual(data.connectors[0].current_mode.state, "unknown")
                self.assertEqual(data.connectors[0].modes, ("1920x1080",))
        for result in (subprocess.CompletedProcess([], -6, ""), subprocess.CompletedProcess([], 0, "not JSON")):
            with patch("beamfix.desktop.subprocess.run", return_value=result):
                self.assertEqual(add_current_modes(snapshot()).connectors[0].current_mode.state, "unknown")


class ModePresentationTests(unittest.TestCase):
    def test_green_mode_pair_and_yellow_unverified_mode(self):
        for current_id, color, expected in (("1", "32", "1920 x 1080 @ 59.94 Hz"),
                                            ("missing", "33", "[UNVERIFIED]")):
            data = apply_kde_modes(snapshot(), {"outputs": [output(currentModeId=current_id)]})
            lines = []
            ui = Terminal(write=lines.append, is_tty=True, environ={})
            render_doctor(data, [], 0 if current_id == "1" else 2, terminal=ui)
            rendered = "\n".join(lines)
            self.assertIn(expected, rendered)
            self.assertIn(f"\x1b[{color}m", rendered)
            self.assertNotIn("\x1b[31m", rendered)
            self.assertNotIn("[CONFIRMED]", rendered)

    def test_current_mode_unknown_returns_incomplete_exit_code(self):
        data = apply_kde_modes(snapshot(), {"outputs": [output(currentModeId="missing")]})
        with patch("beamfix.cli.collect", return_value=data), contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(["doctor", "--json"]), 2)
        report = json.loads(stream.getvalue())
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["visual_confirmation"], "not_performed")
        self.assertEqual(report["snapshot"]["connectors"][0]["current_mode"]["state"], "unknown")

    def test_known_mode_is_serialized_without_changing_existing_mode_list(self):
        data = apply_kde_modes(snapshot(), {"outputs": [output()]})
        with patch("beamfix.cli.collect", return_value=data), contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(["doctor", "--json"]), 0)
        connector = json.loads(stream.getvalue())["snapshot"]["connectors"][0]
        self.assertEqual(connector["modes"], ["1920x1080"])
        self.assertEqual(connector["current_mode"]["mode"], {"width": 1920, "height": 1080, "refresh_hz": 59.94})


if __name__ == "__main__":
    unittest.main()
