import copy
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

from beamfix.automatic import confirm_in_terminal, run_activation
from beamfix.cli import main
from beamfix.fix_worker import Channel, FixResult, activation_lock, rollback, transact
from beamfix.kde_fix import KDEBackend, Unavailable, configuration, plan_activation
from beamfix.models import Connector, Snapshot
from beamfix.troubleshoot import offer_activation, run
from beamfix.terminal import Terminal


def raw_output(name, identifier, enabled):
    return {"name": name, "id": identifier, "connected": True, "enabled": enabled,
            "currentModeId": "1", "pos": {"x": 0, "y": 0}, "scale": 1,
            "rotation": 1, "priority": 1 if enabled else 0, "replicationSource": 0,
            "clones": [], "followPreferredMode": False,
            "modes": [{"id": "1", "size": {"width": 1920, "height": 1080}, "refreshRate": 60}]}


def fixture():
    data = {"outputs": [raw_output("eDP-1", 1, True), raw_output("HDMI-A-1", 2, False)]}
    snapshot = Snapshot("Linux", "test", "wayland", "KDE", connectors=[
        Connector("card0-eDP-1", "internal", "connected", "enabled", ("1920x1080",)),
        Connector("card0-HDMI-A-1", "external", "connected", "disabled", ("1920x1080",)),
    ])
    return snapshot, data


def make_plan():
    snapshot, data = fixture()
    return plan_activation(snapshot, "card0-HDMI-A-1", data)


class MemoryBackend:
    def __init__(self, plan):
        self.plan = plan
        self.current = copy.deepcopy(plan.before)
        self.writes = []

    def prepare(self, target):
        return self.plan

    def state(self):
        return copy.deepcopy(self.current)

    def set_enabled(self, plan, enabled):
        self.writes.append(enabled)
        self.current = copy.deepcopy(plan.expected if enabled else plan.before)


class PlanTests(unittest.TestCase):
    def test_plan_preserves_layout_and_only_enables_selected_output(self):
        plan = make_plan()
        self.assertFalse(plan.before[plan.output]["enabled"])
        self.assertTrue(plan.expected[plan.output]["enabled"])
        self.assertEqual(plan.before["eDP-1"], plan.expected["eDP-1"])
        for key in ("currentModeId", "pos", "scale", "rotation"):
            self.assertEqual(plan.before[plan.output][key], plan.expected[plan.output][key])
        self.assertIn("1920 x 1080 @ 60.00 Hz", plan.description)

    def test_rejects_unsupported_session_and_uncertain_drm(self):
        snapshot, data = fixture()
        variants = [replace(snapshot, session="x11"), replace(snapshot, desktop="GNOME"),
                    replace(snapshot, errors=["unreadable"])]
        for attribute, value in (("kind", "internal"), ("status", "unknown"),
                                 ("enabled", "enabled"), ("modes", None)):
            variants.append(replace(snapshot, connectors=[snapshot.connectors[0],
                                 replace(snapshot.connectors[1], **{attribute: value})]))
        variants.append(replace(snapshot, connectors=snapshot.connectors + [
            replace(snapshot.connectors[1], name="card1-HDMI-A-1")]))
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(Unavailable):
                plan_activation(variant, "card0-HDMI-A-1", data)

    def test_rejects_incomplete_ambiguous_and_nonreversible_configurations(self):
        snapshot, base = fixture()
        for field, value in (("currentModeId", "missing"), ("connected", False), ("enabled", True),
                             ("replicationSource", 1), ("followPreferredMode", True), ("clones", [1]),
                             ("name", "HDMI-A-1.enable"), ("scale", float("nan")), ("scale", 10 ** 400),
                             ("rotation", True), ("id", 1), ("priority", 1), ("pos", {}),
                             ("pos", {"x": -1920, "y": 0})):
            data = copy.deepcopy(base)
            data["outputs"][1][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(Unavailable):
                plan_activation(snapshot, "card0-HDMI-A-1", data)
        for field in ("pos", "scale", "clones", "followPreferredMode"):
            data = copy.deepcopy(base)
            del data["outputs"][1][field]
            with self.subTest(missing=field), self.assertRaises(Unavailable):
                plan_activation(snapshot, "card0-HDMI-A-1", data)

    def test_other_active_screen_must_be_verified(self):
        snapshot, data = fixture()
        data["outputs"][0]["enabled"] = False
        data["outputs"][0]["priority"] = 0
        with self.assertRaises(Unavailable):
            plan_activation(snapshot, "card0-HDMI-A-1", data)
        snapshot, data = fixture()
        snapshot.connectors[0] = replace(snapshot.connectors[0], enabled="unknown")
        with self.assertRaises(Unavailable):
            plan_activation(snapshot, "card0-HDMI-A-1", data)

    def test_raw_identity_data_are_not_in_plan(self):
        snapshot, data = fixture()
        data["outputs"][1].update(edid="private", serial="private", iccProfilePath="private")
        self.assertNotIn("private", json.dumps(asdict(plan_activation(snapshot, "card0-HDMI-A-1", data))))

    def test_mode_and_output_order_do_not_create_false_changes(self):
        _, data = fixture()
        before = configuration(data)
        data["outputs"].reverse()
        self.assertEqual(configuration(data), before)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()
        self.backend = MemoryBackend(self.plan)
        self.channel = Mock()
        self.channel.receive.side_effect = [{"action": "apply"}, {"action": "keep"}]

    def test_explicit_confirmation_keeps_verified_activation(self):
        result = transact(self.plan, self.backend, self.channel)
        self.assertEqual(result.status, "kept")
        self.assertEqual(self.backend.writes, [True])

    def test_refusal_timeout_eof_and_malformed_decision_restore(self):
        for decision in ({"action": "undo"}, {}, EOFError(), TimeoutError(), ValueError()):
            with self.subTest(decision=decision):
                backend = MemoryBackend(self.plan)
                self.channel.receive.side_effect = [{"action": "apply"}, decision]
                result = transact(self.plan, backend, self.channel)
                self.assertEqual(result.status, "reverted")
                self.assertEqual(backend.writes, [True, False])
                self.assertEqual(backend.current, self.plan.before)

    def test_late_confirmation_cannot_keep(self):
        result = transact(self.plan, self.backend, self.channel, seconds=0)
        self.assertEqual(result.status, "reverted")

    def test_dead_terminal_before_apply_never_writes(self):
        self.channel.receive.side_effect = EOFError()
        result = transact(self.plan, self.backend, self.channel)
        self.assertFalse(result.attempted)
        self.assertEqual(self.backend.writes, [])

    def test_changed_plan_after_preview_never_writes(self):
        self.backend.plan = replace(self.plan, connector="card1-HDMI-A-1")
        result = transact(self.plan, self.backend, self.channel)
        self.assertEqual(result.status, "refused")
        self.assertEqual(self.backend.writes, [])

    def test_no_effect_is_not_success_even_with_zero_exit(self):
        self.backend.set_enabled = Mock()
        result = transact(self.plan, self.backend, self.channel)
        self.assertEqual(result.status, "reverted")
        self.assertNotIn("Expected image confirmed", result.detail)
        self.channel.receive.assert_called_once()

    def test_apply_error_after_partial_success_still_rolls_back(self):
        original = self.backend.set_enabled

        def change(plan, enabled):
            original(plan, enabled)
            if enabled:
                raise Unavailable("Command timed out")

        self.backend.set_enabled = change
        result = transact(self.plan, self.backend, self.channel)
        self.assertEqual(result.status, "reverted")
        self.assertEqual(self.backend.writes, [True, False])

    def test_external_change_is_not_overwritten_or_called_restored(self):
        def decision(timeout):
            if not self.backend.writes:
                return {"action": "apply"}
            self.backend.current["eDP-1"]["scale"] = 2
            return {"action": "keep"}

        self.channel.receive.side_effect = decision
        result = transact(self.plan, self.backend, self.channel)
        self.assertEqual(result.status, "attention")
        self.assertEqual(self.backend.writes, [True])
        self.assertEqual(self.backend.current["eDP-1"]["scale"], 2)

    def test_disconnection_never_redirects_rollback(self):
        self.backend.current = self.plan.expected
        del self.backend.current[self.plan.output]
        result = rollback(self.backend, self.plan)
        self.assertEqual(result.status, "attention")
        self.assertEqual(self.backend.writes, [])

    def test_recovery_retries_unavailable_query_and_verifies_undo(self):
        self.backend.current = self.plan.expected
        self.backend.state = Mock(side_effect=[Unavailable("temporarily unreadable"),
                                              self.plan.expected, self.plan.before])
        self.assertEqual(rollback(self.backend, self.plan).status, "reverted")
        self.assertEqual(self.backend.writes, [False])

    def test_failed_undo_never_claims_restoration(self):
        self.backend.current = self.plan.expected
        self.backend.set_enabled = Mock(side_effect=Unavailable("rejected"))
        self.assertEqual(rollback(self.backend, self.plan).status, "attention")

    def test_concurrent_attempt_is_refused(self):
        with activation_lock():
            with self.assertRaises(Unavailable):
                with activation_lock():
                    self.fail("Second lock acquired")
        with activation_lock():
            pass

    def test_backend_passes_only_fixed_activation_arguments_without_shell(self):
        with patch("beamfix.kde_fix.shutil.which", return_value="/usr/bin/kscreen-doctor"), \
                patch("beamfix.kde_fix.subprocess.run", return_value=Mock(returncode=0)) as command:
            KDEBackend().set_enabled(self.plan, True)
        self.assertEqual(command.call_args.args[0], ["/usr/bin/kscreen-doctor",
                         "output.HDMI-A-1.enable", "output.HDMI-A-1.priority.2"])
        self.assertNotIn("shell", command.call_args.kwargs)
        self.assertEqual(command.call_args.kwargs["timeout"], 5)


class GuidedAutomaticTests(unittest.TestCase):
    def test_preview_manual_skip_and_exit_do_not_launch_worker(self):
        from beamfix.troubleshoot import StopSession
        for answer, expected in (("2", "manual"), ("3", "skip"), ("0", "exit")):
            with self.subTest(answer=answer), patch("sys.stdin.isatty", return_value=True), \
                    patch("beamfix.kde_fix.KDEBackend.prepare", return_value=make_plan()), \
                    patch("beamfix.automatic.run_activation") as start:
                ui = Terminal(write=lambda _: None)
                if expected == "exit":
                    with self.assertRaises(StopSession):
                        offer_activation("card0-HDMI-A-1", lambda _: answer, ui, snapshot=fixture()[0])
                else:
                    self.assertEqual(offer_activation("card0-HDMI-A-1", lambda _: answer, ui, snapshot=fixture()[0]), expected)
                start.assert_not_called()

    def test_unavailable_preconditions_fall_back_without_asking_for_approval(self):
        with patch("sys.stdin.isatty", return_value=True), \
                patch("beamfix.kde_fix.KDEBackend.prepare", side_effect=Unavailable("Not supported")), \
                patch("beamfix.automatic.run_activation") as start:
            read = Mock()
            self.assertEqual(offer_activation("card0-HDMI-A-1", read, Terminal(write=lambda _: None),
                                             snapshot=fixture()[0]), "manual")
            read.assert_not_called()
            start.assert_not_called()

    def test_piped_input_cannot_start_automatic_attempt(self):
        with patch("sys.stdin.isatty", return_value=False), patch("beamfix.kde_fix.KDEBackend.prepare") as prepare:
            self.assertEqual(offer_activation("card0-HDMI-A-1", Mock(), Terminal(write=lambda _: None)), "manual")
            prepare.assert_not_called()

    def session(self, result):
        snapshot, _ = fixture()
        answers = iter(["1", "4", "1"])
        output = []
        with patch("beamfix.troubleshoot.offer_activation", return_value=result):
            code = run(snapshot_reader=lambda: snapshot, read=lambda _: next(answers),
                       write=output.append, try_fix=True)
        return code, " ".join(output)

    def test_only_kept_result_resolves(self):
        for status, code in (("kept", 0), ("reverted", 2), ("attention", 2), ("refused", 2)):
            result, output = self.session(FixResult(status, "Recovery detail", status != "refused"))
            self.assertEqual(result, code)
            self.assertIn("Recovery detail", output)
            self.assertNotIn("has not applied changes", output)

    def test_manual_fallback_preserves_existing_flow(self):
        snapshot, _ = fixture()
        answers = iter(["1", "4", "1", "1", "1"])
        with patch("beamfix.troubleshoot.offer_activation", return_value="manual"):
            self.assertEqual(run(snapshot_reader=lambda: snapshot, read=lambda _: next(answers),
                                 write=lambda _: None, try_fix=True), 0)

    def test_flag_dispatches_opt_in(self):
        with patch("beamfix.troubleshoot.run", return_value=2) as guided:
            self.assertEqual(main(["troubleshoot", "--try-fix"]), 2)
            guided.assert_called_once_with(plain=False, try_fix=True)


# Real OS processes and IPC, with a fake display backend. No graphical APIs are
# called by the harness. This exercises the same worker serve/main and UI client.
HARNESS = r'''
import json, os, sys
from pathlib import Path
from beamfix.fix_backends import decode_plan
from beamfix import fix_worker
path = Path(os.environ["BEAMFIX_TEST_STATE"])
plan = decode_plan(json.loads(Path(os.environ["BEAMFIX_TEST_PLAN"]).read_text()))
class Backend:
    def prepare(self, target):
        return plan
    def state(self):
        return json.loads(path.read_text())
    def set_enabled(self, plan, enabled):
        new = plan.expected if enabled else plan.before
        temp = path.with_suffix(".new")
        temp.write_text(json.dumps(new))
        temp.replace(path)
fix_worker.KDEBackend = Backend
fix_worker.GNOMEBackend = Backend
fix_worker.main()
'''


class ProcessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.plan = make_plan()
        self.state = self.directory / "state.json"
        self.plan_file = self.directory / "plan.json"
        self.state.write_text(json.dumps(self.plan.before))
        self.plan_file.write_text(json.dumps(asdict(self.plan)))
        self.environment = {**os.environ, "BEAMFIX_TEST_STATE": str(self.state),
                            "BEAMFIX_TEST_PLAN": str(self.plan_file)}
        self.processes = []
        self.addCleanup(self.reap)

    def reap(self):
        for process in self.processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def launch(self):
        parent, child = socket.socketpair()
        process = subprocess.Popen([sys.executable, "-c", HARNESS, str(child.fileno())],
                                   pass_fds=(child.fileno(),), start_new_session=True,
                                   env=self.environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        child.close()
        self.addCleanup(parent.close)
        channel = Channel(parent)
        channel.send({"plan": asdict(self.plan)})
        self.assertEqual(channel.receive(5)["event"], "armed")
        channel.send({"action": "apply"})
        self.assertEqual(channel.receive(5)["event"], "confirm")
        return process, parent, channel

    def test_worker_restores_on_ui_socket_loss_and_survives_hangup(self):
        process, parent, _ = self.launch()
        self.assertEqual(json.loads(self.state.read_text()), self.plan.expected)
        os.kill(process.pid, signal.SIGHUP)
        parent.close()
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertEqual(json.loads(self.state.read_text()), self.plan.before)

    def test_worker_keeps_only_explicit_confirmation(self):
        process, _, channel = self.launch()
        channel.send({"action": "keep"})
        result = channel.receive(5)
        self.assertEqual(result["status"], "kept")
        process.wait(timeout=5)
        self.assertEqual(json.loads(self.state.read_text()), self.plan.expected)

    def test_worker_deadline_is_independent_of_ui(self):
        # Shorten only the test worker's wait, keeping its real socket timeout.
        short = HARNESS.replace("fix_worker.main()", "original = fix_worker.transact\n"
                                "fix_worker.transact = lambda *a: original(*a, seconds=0.15)\nfix_worker.main()")
        with patch(__name__ + ".HARNESS", short):
            process, _, channel = self.launch()
            result = channel.receive(5)
            if result.get("event") == "recovering":
                result = channel.receive(5)
        self.assertEqual(result["status"], "reverted")
        process.wait(timeout=5)
        self.assertEqual(json.loads(self.state.read_text()), self.plan.before)

    def test_actual_parent_process_death_triggers_recovery(self):
        # The holder dies without a Python finally block, leaving its detached
        # worker to detect EOF. This catches inherited-fd and process-group bugs.
        holder = r'''
import json, os, socket, subprocess, sys, time
from pathlib import Path
from beamfix.fix_worker import Channel
parent, child = socket.socketpair()
p = subprocess.Popen([sys.executable, "-c", os.environ["BEAMFIX_TEST_HARNESS"], str(child.fileno())],
                     pass_fds=(child.fileno(),), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
child.close()
c = Channel(parent)
c.send({"plan": json.loads(Path(os.environ["BEAMFIX_TEST_PLAN"]).read_text())})
assert c.receive(5)["event"] == "armed"
c.send({"action": "apply"})
assert c.receive(5)["event"] == "confirm"
print(p.pid, flush=True)
time.sleep(10)
'''
        process = subprocess.Popen([sys.executable, "-c", holder],
                                   env={**self.environment, "BEAMFIX_TEST_HARNESS": HARNESS},
                                   stdout=subprocess.PIPE, text=True)
        self.processes.append(process)
        import select
        self.assertTrue(select.select([process.stdout], [], [], 5)[0])
        worker_pid = int(process.stdout.readline())
        process.kill()
        process.wait(timeout=5)
        process.stdout.close()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and json.loads(self.state.read_text()) != self.plan.before:
            time.sleep(0.02)
        self.assertEqual(json.loads(self.state.read_text()), self.plan.before, f"worker {worker_pid}")

    def test_ui_client_uses_real_worker_handshake_and_confirmation(self):
        original = subprocess.Popen

        def spawn(arguments, **kwargs):
            process = original([sys.executable, "-c", HARNESS, arguments[-1]],
                               **{**kwargs, "env": self.environment})
            self.processes.append(process)
            return process

        with patch("beamfix.automatic.subprocess.Popen", side_effect=spawn):
            result = run_activation(self.plan, lambda seconds: 0 < seconds <= 15)
        self.assertEqual(result.status, "kept")
        self.assertEqual(json.loads(self.state.read_text()), self.plan.expected)

    def test_ui_keyboard_interrupt_requests_verified_undo(self):
        original = subprocess.Popen

        def spawn(arguments, **kwargs):
            process = original([sys.executable, "-c", HARNESS, arguments[-1]],
                               **{**kwargs, "env": self.environment})
            self.processes.append(process)
            return process

        with patch("beamfix.automatic.subprocess.Popen", side_effect=spawn):
            result = run_activation(self.plan, Mock(side_effect=KeyboardInterrupt))
        self.assertEqual(result.status, "reverted")
        self.assertEqual(json.loads(self.state.read_text()), self.plan.before)


class TerminalConfirmationTests(unittest.TestCase):
    def test_stale_input_is_discarded_and_only_fresh_one_enter_keeps(self):
        for answer, expected in ((b"1\n", True), (b"2\n", False), (b"1 1\n", False), (None, False)):
            with self.subTest(answer=answer):
                master, slave = os.openpty()
                try:
                    os.write(master, b"1\n")  # pretyped input must never confirm
                    stdin = Mock()
                    stdin.fileno.return_value = slave
                    sent = False

                    def render(line):
                        nonlocal sent
                        if not sent and "Press Enter" in line:
                            sent = True
                            if answer is not None:
                                os.write(master, answer)

                    with patch("sys.stdin", stdin):
                        self.assertEqual(confirm_in_terminal(Terminal(write=render), 0.15), expected)
                finally:
                    os.close(master)
                    os.close(slave)
