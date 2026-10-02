import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, patch

from beamfix.fix_backends import backend_for, decode_plan
from beamfix.fix_worker import transact
from beamfix.gnome_fix import (GNOMEBackend, STATE_SIGNATURE, APPLY_SIGNATURE,
                              apply_arguments, configuration, plan_activation)
from beamfix.kde_fix import KDEBackend, Unavailable
from beamfix.models import Connector, Snapshot
import test_automatic as automatic_tests


def variant(signature, data):
    return {"type": signature, "data": data}


def fixture():
    specs = [["eDP-1", "Vendor", "Panel", "private-panel-serial"],
             ["HDMI-1", "Vendor", "Projector", "private-projector-serial"]]
    mode = lambda active: ["1920x1080@60", 1920, 1080, 60.0, 1.0, [1.0, 1.5, 2.0],
                           {"is-preferred": variant("b", True), **({"is-current": variant("b", True)} if active else {})}]
    physical = [[spec, [mode(index == 0)], {"is-builtin": variant("b", index == 0),
                 "is-underscanning": variant("b", False), "color-mode": variant("u", 0),
                 "rgb-range": variant("u", 1)}] for index, spec in enumerate(specs)]
    logical = [[0, 0, 1.0, 0, True, [specs[0]], {}]]
    properties = {"layout-mode": variant("u", 1), "supports-changing-layout-mode": variant("b", True)}
    reply = {"type": STATE_SIGNATURE, "data": [42, physical, logical, properties]}
    snapshot = Snapshot("Linux", "test", "wayland", "ubuntu:GNOME", connectors=[
        Connector("card0-eDP-1", "internal", "connected", "enabled", ("1920x1080",)),
        Connector("card0-HDMI-A-1", "external", "connected", "disabled", ("1920x1080",)),
    ])
    return snapshot, reply


def make_plan(reply=None):
    snapshot, default = fixture()
    return plan_activation(snapshot, "card0-HDMI-A-1", reply or default)


def activate_reply(reply):
    result = copy.deepcopy(reply)
    result["data"][0] += 1
    result["data"][1][1][1][0][6]["is-current"] = variant("b", True)
    result["data"][2].append([1920, 0, 1.0, 0, False, [result["data"][1][1][0]], {}])
    return result


class GNOMEPlanningTests(unittest.TestCase):
    def test_only_documented_hdmi_spelling_is_matched_without_gpu_ambiguity(self):
        snapshot, reply = fixture()
        self.assertEqual(make_plan(reply).output, "HDMI-1")
        duplicate = copy.deepcopy(reply["data"][1][1])
        duplicate[0][0] = "HDMI-A-1"
        reply["data"][1].append(duplicate)
        with self.assertRaises(Unavailable):
            plan_activation(snapshot, "card0-HDMI-A-1", reply)
        _, reply = fixture()
        reply["data"][1][1][0][0] = "HDMI-2"
        with self.assertRaises(Unavailable):
            make_plan(reply)

    def test_adds_only_target_and_preserves_primary_layout_and_settings(self):
        plan = make_plan()
        self.assertEqual(plan.backend, "gnome")
        self.assertEqual(plan.added, {"output": "HDMI-1", "x": 1920, "y": 0, "scale": 1.0,
                                      "transform": 0, "primary": False, "mode": "1920x1080@60"})
        self.assertIn(plan.before["logical"][0], plan.expected["logical"])
        self.assertEqual(plan.before["monitors"], plan.expected["monitors"])
        self.assertIn("temporary for this session", plan.description)
        self.assertNotIn("private-", json.dumps(asdict(plan)))

    def test_realistic_current_flags_and_serial_change_match_expected(self):
        _, reply = fixture()
        self.assertEqual(configuration(activate_reply(reply))[1], make_plan().expected)

    def test_serial_is_fresh_transport_state_not_restorable_layout(self):
        _, reply = fixture()
        plan = make_plan(reply)
        reply["data"][0] += 1
        self.assertEqual(plan, make_plan(reply))

    def test_rotation_and_fractional_scale_determine_right_edge(self):
        _, reply = fixture()
        reply["data"][2][0][2] = 1.5
        reply["data"][2][0][3] = 1
        plan = make_plan(reply)
        self.assertEqual(plan.added["x"], 720)
        self.assertEqual(plan.before["logical"][0]["transform"], 1)

    def test_physical_layout_does_not_divide_by_scale(self):
        _, reply = fixture()
        reply["data"][3]["layout-mode"] = variant("u", 2)
        reply["data"][2][0][2] = 2.0
        self.assertEqual(make_plan(reply).added["x"], 1920)

    def test_global_scale_is_preserved_or_rejected_if_unsupported(self):
        _, reply = fixture()
        reply["data"][3]["global-scale-required"] = variant("b", True)
        reply["data"][2][0][2] = 1.5
        self.assertEqual(make_plan(reply).added["scale"], 1.5)
        reply["data"][1][1][1][0][5] = [1.0]
        with self.assertRaises(Unavailable):
            make_plan(reply)

    def test_multiple_active_screens_place_target_after_rightmost_edge(self):
        snapshot, reply = fixture()
        other = copy.deepcopy(reply["data"][1][0])
        other[0] = ["DP-2", "Vendor", "Monitor", "id"]
        reply["data"][1].append(other)
        reply["data"][2].append([1920, 200, 1.0, 0, False, [other[0]], {}])
        snapshot.connectors.append(Connector("card0-DP-2", "external", "connected", "enabled", ("1920x1080",)))
        plan = plan_activation(snapshot, "card0-HDMI-A-1", reply)
        self.assertEqual((plan.added["x"], plan.added["y"]), (3840, 200))

    def test_unknown_identity_unsupported_session_and_drm_conflicts_refuse(self):
        snapshot, reply = fixture()
        variants = [replace(snapshot, session="x11"), replace(snapshot, desktop="KDE"),
                    replace(snapshot, system="FreeBSD"), replace(snapshot, errors=["unreadable"])]
        for field, value in (("kind", "internal"), ("status", "unknown"), ("enabled", "enabled"), ("modes", None)):
            variants.append(replace(snapshot, connectors=[snapshot.connectors[0],
                               replace(snapshot.connectors[1], **{field: value})]))
        variants.append(replace(snapshot, connectors=snapshot.connectors + [
            replace(snapshot.connectors[1], name="card1-HDMI-A-1")]))
        variants.append(replace(snapshot, connectors=[replace(snapshot.connectors[0], enabled="disabled"),
                                                     snapshot.connectors[1]]))
        for data in variants:
            with self.subTest(data=data), self.assertRaises(Unavailable):
                plan_activation(data, "card0-HDMI-A-1", reply)

    def test_unsupported_cloning_lease_and_conflicting_current_flags_refuse(self):
        _, base = fixture()
        variants = []
        data = copy.deepcopy(base)
        data["data"][2][0][5].append(data["data"][1][1][0])
        variants.append(data)
        data = copy.deepcopy(base)
        data["data"][1][1][2]["is-for-lease"] = variant("b", True)
        variants.append(data)
        data = copy.deepcopy(base)
        data["data"][1][1][1][0][6]["is-current"] = variant("b", True)
        variants.append(data)
        data = copy.deepcopy(base)
        data["data"][2][0][6] = {"unknown-layout-option": variant("b", True)}
        variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(Unavailable):
                make_plan(data)

    def test_no_guess_of_preferred_mode_or_invalid_scale(self):
        _, base = fixture()
        for field, value in (("is-preferred", False), ("is-interlaced", True)):
            data = copy.deepcopy(base)
            data["data"][1][1][1][0][6][field] = variant("b", value)
            with self.subTest(field=field), self.assertRaises(Unavailable):
                make_plan(data)
        for scale in (0, float("nan"), 10**400, True, 1.7):
            data = copy.deepcopy(base)
            data["data"][2][0][2] = scale
            with self.subTest(scale=scale), self.assertRaises(Unavailable):
                make_plan(data)
        data = copy.deepcopy(base)
        mode = copy.deepcopy(data["data"][1][1][1][0])
        mode[0] = "second-preferred-mode"
        data["data"][1][1][1].append(mode)
        with self.assertRaises(Unavailable):
            make_plan(data)

    def test_rounding_unknown_rgb_and_primary_mismatch_refuse(self):
        _, base = fixture()
        data = copy.deepcopy(base)
        data["data"][2][0][4] = False
        with self.assertRaises(Unavailable):
            make_plan(data)
        data = copy.deepcopy(base)
        data["data"][1][1][2]["rgb-range"] = variant("u", 0)
        with self.assertRaises(Unavailable):
            make_plan(data)
        data = copy.deepcopy(base)
        data["data"][1][1][1][0][1] = 1919
        data["data"][1][1][1][0][4] = 1.5
        with self.assertRaises(Unavailable):
            make_plan(data)

    def test_rejects_malformed_busctl_envelopes_without_evaluation(self):
        _, base = fixture()
        for data in (None, {}, {"type": STATE_SIGNATURE, "data": []},
                     {"type": "s", "data": ["__import__('os')"]},
                     {**base, "data": [True, *base["data"][1:]]}):
            with self.subTest(data=data), self.assertRaises(Unavailable):
                configuration(data)

    def test_swapped_device_and_changed_settings_are_different_states(self):
        _, reply = fixture()
        before = configuration(reply)[1]
        reply["data"][1][1][0][3] = "different-device"
        self.assertNotEqual(configuration(reply)[1], before)


class GNOMETransportTests(unittest.TestCase):
    def test_native_commands_are_typed_bounded_and_noninteractive(self):
        _, reply = fixture()
        with patch("beamfix.gnome_fix.shutil.which", return_value="/usr/bin/busctl"), \
                patch("beamfix.gnome_fix.subprocess.run", return_value=Mock(returncode=0, stdout=json.dumps(reply))) as call:
            self.assertEqual(GNOMEBackend().query(), reply)
        command = call.call_args.args[0]
        self.assertIn("--user", command)
        self.assertIn("--auto-start=no", command)
        self.assertIn("--allow-interactive-authorization=no", command)
        self.assertEqual(command[command.index("--") + 1], "call")
        self.assertEqual(command[-1], "GetCurrentState")
        self.assertNotIn("shell", call.call_args.kwargs)
        self.assertEqual(call.call_args.kwargs["timeout"], 5)

    def test_missing_tool_failure_timeout_and_bad_json_are_unavailable(self):
        with patch("beamfix.gnome_fix.shutil.which", return_value=None), self.assertRaises(Unavailable):
            GNOMEBackend().query()
        for effect in (Mock(returncode=1, stdout=""), Mock(returncode=0, stdout="not-json"),
                       subprocess.TimeoutExpired("busctl", 5), OSError("gone")):
            with self.subTest(effect=effect), patch("beamfix.gnome_fix.shutil.which", return_value="busctl"), \
                    patch("beamfix.gnome_fix.subprocess.run", side_effect=[effect]), self.assertRaises(Unavailable):
                GNOMEBackend().query()

    def test_apply_permission_must_be_explicitly_true(self):
        for reply in (None, {}, variant("b", False), variant("b", 1), variant("b", [True])):
            backend = GNOMEBackend()
            backend._request = Mock(return_value=reply)
            with self.subTest(reply=reply), self.assertRaises(Unavailable):
                backend.allowed()

    def test_verifies_then_applies_temporary_with_fresh_serial_and_full_layout(self):
        _, reply = fixture()
        reply["data"][0] = 79
        plan = make_plan()
        backend = GNOMEBackend()
        backend.allowed = Mock()
        backend.query = Mock(return_value=reply)
        backend._request = Mock()
        backend.set_enabled(plan, True)
        calls = backend._request.call_args_list
        self.assertEqual(len(calls), 2)
        verify, apply = [call.args[2] for call in calls]
        self.assertEqual(verify[:4], [APPLY_SIGNATURE, "79", "0", "2"])
        self.assertEqual(apply[:4], [APPLY_SIGNATURE, "79", "1", "2"])
        self.assertIn("eDP-1", apply)
        self.assertIn("HDMI-1", apply)

    def test_verification_error_prevents_apply(self):
        _, reply = fixture()
        backend = GNOMEBackend()
        backend.allowed = Mock()
        backend.query = Mock(return_value=reply)
        backend._request = Mock(side_effect=Unavailable("verification rejected"))
        with self.assertRaises(Unavailable):
            backend.set_enabled(make_plan(), True)
        backend._request.assert_called_once()

    def test_changed_configuration_prevents_even_verification(self):
        _, reply = fixture()
        backend = GNOMEBackend()
        backend.allowed = Mock()
        backend.query = Mock(return_value=activate_reply(reply))
        backend._request = Mock()
        with self.assertRaises(Unavailable):
            backend.set_enabled(make_plan(), True)
        backend._request.assert_not_called()

    def test_undo_uses_new_serial_and_restores_all_existing_settings(self):
        _, reply = fixture()
        backend = GNOMEBackend()
        backend.allowed = Mock()
        backend.query = Mock(return_value=activate_reply(reply))
        backend._request = Mock()
        backend.set_enabled(make_plan(), False)
        arguments = backend._request.call_args.args[2]
        self.assertEqual(arguments[:4], [APPLY_SIGNATURE, "43", "1", "1"])
        self.assertIn("eDP-1", arguments)
        self.assertNotIn("HDMI-1", arguments)

    def test_color_underscan_and_layout_properties_are_preserved(self):
        _, reply = fixture()
        reply["data"][1][0][2]["is-underscanning"] = variant("b", True)
        reply["data"][1][0][2]["color-mode"] = variant("u", 1)
        reply["data"][1][0][2]["rgb-range"] = variant("u", 2)
        arguments = apply_arguments(42, 1, make_plan(reply).before)
        encoded = " ".join(arguments)
        for piece in ("underscanning b true", "color-mode u 1", "rgb-range u 2", "layout-mode u 1"):
            self.assertIn(piece, encoded)
        with self.assertRaises(Unavailable):
            apply_arguments(42, 2, make_plan().before)


class BackendSelectionTests(unittest.TestCase):
    def test_selects_explicit_desktop_without_cross_desktop_fallback(self):
        snapshot, _ = fixture()
        self.assertIsInstance(backend_for(snapshot), GNOMEBackend)
        self.assertIsInstance(backend_for(replace(snapshot, desktop="KDE")), KDEBackend)
        for desktop in ("GNOME:KDE", "X-Cinnamon", "sway", "unknown", "GNOME-Classic"):
            with self.subTest(desktop=desktop), self.assertRaises(Unavailable):
                backend_for(replace(snapshot, desktop=desktop))
        with self.assertRaises(Unavailable):
            backend_for(replace(snapshot, session="x11"))

    def test_plan_roundtrip_and_unknown_backends(self):
        for plan in (make_plan(), automatic_tests.make_plan()):
            self.assertEqual(decode_plan(json.loads(json.dumps(asdict(plan)))), plan)
        with self.assertRaises(Unavailable):
            decode_plan({**asdict(make_plan()), "backend": "unknown"})


class GNOMEWorkerTests(automatic_tests.ProcessRecoveryTests):
    """The real helper process must route and recover a serialized GNOME plan."""

    def setUp(self):
        super().setUp()
        self.plan = make_plan()
        self.state.write_text(json.dumps(self.plan.before))
        self.plan_file.write_text(json.dumps(asdict(self.plan)))


class PrivateBusTests(unittest.TestCase):
    def test_gnome_transport_on_isolated_real_dbus(self):
        python = "/usr/bin/python3"
        ready = (Path(python).exists() and shutil.which("busctl") and shutil.which("dbus-run-session")
                 and subprocess.run([python, "-c", "from gi.repository import Gio, GLib"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
        if not ready:
            if os.environ.get("BEAMFIX_REQUIRE_DBUS_TESTS") == "1":
                self.fail("Private D-Bus integration test prerequisites are missing")
            self.skipTest("Optional test tools: busctl, dbus-run-session, system Python with PyGObject")
        harness = Path(__file__).with_name("gnome_bus_harness.py")
        result = subprocess.run(["dbus-run-session", "--", python, str(harness)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GNOME private-bus integration passed", result.stdout)
