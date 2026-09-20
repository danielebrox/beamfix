import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from beamfix.cli import main
from beamfix.collect import collect
from beamfix.diagnose import diagnose
from beamfix.models import Connector, Snapshot


def snapshot(*connectors):
    return Snapshot("Linux", "test", "wayland", "GNOME", connectors=list(connectors))


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def port(self, name="card0-HDMI-A-1", status="connected", enabled="enabled", modes="1920x1080\n"):
        path = self.root / name
        path.mkdir()
        for filename, value in (("status", status), ("enabled", enabled), ("modes", modes)):
            (path / filename).write_text(value, encoding="utf-8")
        return path

    def scan(self, **kwargs):
        return collect(self.root, system="Linux", environ={"XDG_SESSION_TYPE": "wayland"}, **kwargs)

    def test_multiple_gpus_internal_external_and_mst(self):
        for card in ("card0", "card1"):
            (self.root / card).mkdir()
        self.port("card0-eDP-1")
        self.port("card1-DP-1-2", modes="1920x1080\n1920x1080\n1280x720\n")
        self.port("card1-Writeback-1")
        (self.root / "renderD128").touch()
        result = self.scan()
        self.assertEqual(len(result.gpus), 2)
        self.assertEqual([c.kind for c in result.connectors], ["internal", "external", "virtual"])
        self.assertEqual(result.connectors[1].modes, ("1920x1080", "1280x720"))
        self.assertEqual(result.errors, [])

    def test_missing_status_is_unknown_not_disconnected(self):
        port = self.port()
        (port / "status").unlink()
        result = self.scan()
        self.assertEqual(result.connectors[0].status, "unknown")
        self.assertTrue(result.errors)
        self.assertNotIn("no_external_connected", [f.code for f in diagnose(result)])

    def test_missing_modes_distinct_from_empty_modes(self):
        port = self.port()
        (port / "modes").unlink()
        result = self.scan()
        self.assertIsNone(result.connectors[0].modes)
        self.assertNotIn("connected_no_modes", [f.code for f in diagnose(result)])

    def test_unknown_kernel_status_is_preserved(self):
        self.port(status="unknown")
        result = self.scan()
        self.assertEqual(result.connectors[0].status, "unknown")
        self.assertEqual(result.errors, [])

    def test_unrecognized_status_reported(self):
        self.port(status="unexpected")
        result = self.scan()
        self.assertEqual(result.connectors[0].status, "unknown")
        self.assertTrue(result.errors)

    def test_unreadable_attributes_do_not_crash(self):
        self.port()
        with patch.object(Path, "read_text", side_effect=PermissionError):
            result = self.scan()
        self.assertEqual(result.connectors[0].status, "unknown")
        self.assertEqual(len(result.errors), 3)

    def test_missing_and_empty_drm_are_incomplete(self):
        self.assertTrue(self.scan().errors)
        result = collect(self.root / "missing", system="Linux", environ={})
        self.assertTrue(result.errors)

    def test_non_linux_does_not_scan_drm(self):
        with patch.object(Path, "iterdir", side_effect=AssertionError("must not scan")):
            result = collect(self.root, system="Darwin", environ={})
        self.assertTrue(result.errors)
        self.assertEqual(result.connectors, [])

    def test_display_alone_does_not_prove_x11_session(self):
        self.port()
        result = collect(self.root, system="Linux", environ={"DISPLAY": ":0", "API_KEY": "private"})
        self.assertEqual(result.session, "unknown")
        self.assertNotIn("private", repr(result))


class DiagnosisTests(unittest.TestCase):
    def test_disabled_laptop_panel_is_informational(self):
        result = diagnose(snapshot(
            Connector("card0-eDP-1", "internal", "connected", "disabled", ("1920x1080",)),
            Connector("card0-HDMI-A-1", "external", "connected", "enabled", ("1920x1080",)),
        ))
        self.assertEqual([f.severity for f in result], ["info"])

    def test_connected_but_disabled(self):
        result = diagnose(snapshot(Connector("card0-HDMI-A-1", "external", "connected", "disabled", ("1920x1080",))))
        self.assertEqual([f.code for f in result], ["connected_disabled"])

    def test_connected_without_modes(self):
        result = diagnose(snapshot(Connector("card0-DP-1", "external", "connected", "enabled", ())))
        self.assertEqual([f.code for f in result], ["connected_no_modes"])

    def test_unused_port_not_a_fault_when_another_external_is_connected(self):
        result = diagnose(snapshot(
            Connector("card0-DP-1", "external", "disconnected", "disabled", ()),
            Connector("card0-HDMI-A-1", "external", "connected", "enabled", ("1920x1080",)),
        ))
        self.assertEqual(result, [])

    def test_internal_panel_does_not_count_as_external(self):
        result = diagnose(snapshot(
            Connector("card0-eDP-1", "internal", "connected", "enabled", ("1920x1080",)),
            Connector("card0-HDMI-A-1", "external", "disconnected", "disabled", ()),
        ))
        self.assertEqual([f.code for f in result], ["no_external_connected"])


class CLITests(unittest.TestCase):
    def run_cli(self, data, *args):
        output = io.StringIO()
        with patch("beamfix.cli.collect", return_value=data), contextlib.redirect_stdout(output):
            code = main(["doctor", *args])
        return code, output.getvalue()

    def test_json_is_valid_and_does_not_claim_visual_success(self):
        data = snapshot(Connector("card0-DP-1", "external", "connected", "enabled", ("1920x1080",)))
        code, output = self.run_cli(data, "--json")
        report = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["visual_confirmation"], "not_performed")
        self.assertEqual(report["mode"], "read_only")

    def test_warning_and_incomplete_exit_codes(self):
        data = snapshot(Connector("card0-DP-1", "external", "connected", "disabled", ()))
        self.assertEqual(self.run_cli(data)[0], 1)
        data.errors.append("read failed")
        self.assertEqual(self.run_cli(data)[0], 2)
        unknown = snapshot(Connector("card0-DP-1", "external", "unknown", "disabled", ()))
        self.assertEqual(self.run_cli(unknown)[0], 2)

    def test_terminal_control_characters_are_escaped(self):
        data = snapshot()
        data.desktop = "GNOME\x1b[2J\nFAKE"
        _, output = self.run_cli(data)
        self.assertNotIn("\x1b", output)
        self.assertIn("GNOME?[2J?FAKE", output)


if __name__ == "__main__":
    unittest.main()
