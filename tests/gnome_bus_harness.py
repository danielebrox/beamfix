"""Run only inside dbus-run-session: a fake Mutter service on an isolated bus.

PyGObject is a test dependency of this helper, not a BeamFix runtime dependency.
The service has no graphics access and stores all state in memory.
"""

import copy
from pathlib import Path
import sys
import threading
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gi.repository import Gio, GLib

from beamfix.fix_worker import transact
from beamfix.gnome_fix import GNOMEBackend, OBJECT, SERVICE, configuration
from beamfix.kde_fix import Unavailable
from test_gnome import fixture, make_plan, variant


XML = '''<node><interface name="org.gnome.Mutter.DisplayConfig">
<method name="GetCurrentState">
<arg direction="out" type="u"/>
<arg direction="out" type="a((ssss)a(siiddada{sv})a{sv})"/>
<arg direction="out" type="a(iiduba(ssss)a{sv})"/>
<arg direction="out" type="a{sv}"/>
</method>
<method name="ApplyMonitorsConfig">
<arg direction="in" type="u"/><arg direction="in" type="u"/>
<arg direction="in" type="a(iiduba(ssa{sv}))"/><arg direction="in" type="a{sv}"/>
</method>
<property name="ApplyMonitorsConfigAllowed" type="b" access="read"/>
</interface></node>'''


class FakeMutter:
    def __init__(self):
        self.reply = fixture()[1]
        self.allowed = True
        self.race_after_verify = False
        self.reject_verify = False
        self.calls = []
        self.loop = GLib.MainLoop()
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                           "RequestName", GLib.Variant("(su)", (SERVICE, 4)), None,
                           Gio.DBusCallFlags.NONE, 1000, None)
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self.registration = self.bus.register_object(OBJECT, info, self.call, self.get_property, None)
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()

    def get_property(self, connection, sender, path, interface, name):
        return GLib.Variant("b", self.allowed)

    def native_state(self):
        data = copy.deepcopy(self.reply["data"])

        def props(values):
            return {key: GLib.Variant(value["type"], value["data"]) for key, value in values.items()}

        for monitor in data[1]:
            for mode in monitor[1]:
                mode[6] = props(mode[6])
            monitor[2] = props(monitor[2])
        for logical in data[2]:
            logical[6] = props(logical[6])
        data[3] = props(data[3])
        return GLib.Variant("(" + self.reply["type"] + ")", tuple(data))

    def call(self, connection, sender, path, interface, method, parameters, invocation):
        try:
            if method == "GetCurrentState":
                invocation.return_value(self.native_state())
                return
            serial, how, layouts, properties = parameters.unpack()
            self.calls.append((serial, how, layouts, properties))
            if not self.allowed or serial != self.reply["data"][0]:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.AccessDenied", "Stale serial or permission denied")
                return
            if self.reject_verify and how == 0:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", "Rejected test layout")
                return
            assert how in (0, 1), "Persistent writes are forbidden in this test"
            proposed = copy.deepcopy(self.reply)
            monitors = {monitor[0][0]: monitor for monitor in proposed["data"][1]}
            for monitor in monitors.values():
                for mode in monitor[1]:
                    mode[6].pop("is-current", None)
            new_layouts = []
            for x, y, scale, transform, primary, members in layouts:
                specs = []
                for name, mode_id, settings in members:
                    monitor = monitors[name]
                    matches = [mode for mode in monitor[1] if mode[0] == mode_id]
                    assert len(matches) == 1 and scale in matches[0][5]
                    matches[0][6]["is-current"] = variant("b", True)
                    for key, value in settings.items():
                        source = "is-underscanning" if key == "underscanning" else key
                        monitor[2][source] = variant("b" if key == "underscanning" else "u", value)
                    specs.append(monitor[0])
                new_layouts.append([x, y, scale, transform, primary, specs, {}])
            proposed["data"][2] = new_layouts
            if "layout-mode" in properties:
                proposed["data"][3]["layout-mode"] = variant("u", properties["layout-mode"])
            configuration(proposed)
            if how == 1:
                proposed["data"][0] += 1
                self.reply = proposed
            elif self.race_after_verify:
                self.race_after_verify = False
                self.reply["data"][0] += 1
            invocation.return_value(GLib.Variant("()", ()))
        except Exception as error:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", str(error))

    def close(self):
        self.loop.quit()
        self.thread.join(timeout=2)
        self.bus.unregister_object(self.registration)


def main():
    service = FakeMutter()
    try:
        backend = GNOMEBackend()
        plan = make_plan()
        backend.allowed()
        assert backend.state() == plan.before
        with patch("beamfix.gnome_fix.collect", return_value=fixture()[0]):
            assert backend.prepare(plan.connector) == plan
            channel = Mock()
            channel.receive.side_effect = [{"action": "apply"}, {"action": "undo"}]
            result = transact(plan, backend, channel)
            assert result.status == "reverted", result
            assert backend.state() == plan.before
            assert [(serial, method) for serial, method, *_ in service.calls] == [(42, 0), (42, 1), (43, 0), (43, 1)]

            channel.receive.side_effect = [{"action": "apply"}, {"action": "keep"}]
            result = transact(plan, backend, channel)
            assert result.status == "kept", result
            assert backend.state() == plan.expected
            backend.set_enabled(plan, False)
            assert backend.state() == plan.before

        service.race_after_verify = True
        try:
            backend.set_enabled(plan, True)
            raise AssertionError("Stale serial was accepted")
        except Unavailable:
            assert backend.state() == plan.before

        service.reject_verify = True
        before_calls = len(service.calls)
        try:
            backend.set_enabled(plan, True)
            raise AssertionError("Rejected verification was applied")
        except Unavailable:
            assert len(service.calls) == before_calls + 1
            assert backend.state() == plan.before
        service.reject_verify = False

        # A mode ID is data, not a busctl option, even when it starts with '--'.
        service.reply["data"][1][1][1][0][0] = "--system"
        with patch("beamfix.gnome_fix.collect", return_value=fixture()[0]):
            option_plan = backend.prepare("card0-HDMI-A-1")
            backend.set_enabled(option_plan, True)
            assert backend.state() == option_plan.expected
            backend.set_enabled(option_plan, False)
            assert backend.state() == option_plan.before

            # Intervening user changes must not be replayed over by full-layout undo.
            def decision(timeout):
                if backend.state() == option_plan.before:
                    return {"action": "apply"}
                service.reply["data"][2][0][2] = 2.0
                service.reply["data"][0] += 1
                return {"action": "keep"}

            channel.receive.side_effect = decision
            before_calls = len(service.calls)
            result = transact(option_plan, backend, channel)
            assert result.status == "attention", result
            assert len(service.calls) == before_calls + 2  # verify + apply only, no undo

        service.allowed = False
        try:
            backend.allowed()
            raise AssertionError("Disallowed configuration was accepted")
        except Unavailable:
            pass
        print("GNOME private-bus integration passed: typed state, temporary apply, undo, keep, stale serial, denial")
    finally:
        service.close()


if __name__ == "__main__":
    main()
