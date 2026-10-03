import copy
import json
import os
import subprocess
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, patch

import test_automatic as activation_tests
from beamfix.automatic import confirm_mode_in_terminal, run_activation, run_mode_sequence
from beamfix.fix_backends import decode_plan, prepare_modes
from beamfix.fix_worker import FixResult, transact
from beamfix.kde_fix import Unavailable
from beamfix.kde_modes import KDEModeBackend, MAX_MODE_TRIALS, plan_modes
from beamfix.terminal import Terminal
from beamfix.troubleshoot import offer_modes, run


def fixture():
    snapshot, data = activation_tests.fixture()
    snapshot.connectors[1] = replace(snapshot.connectors[1], enabled="enabled")
    target = data["outputs"][1]
    target.update(enabled=True, priority=2, pos={"x": 1920, "y": 0})
    target["modes"].extend([
        {"id": "2", "size": {"width": 1280, "height": 720}, "refreshRate": 60},
        {"id": "3", "size": {"width": 1024, "height": 768}, "refreshRate": 60},
        {"id": "4", "size": {"width": 1920, "height": 1080}, "refreshRate": 50},
    ])
    return snapshot, data


def plans():
    snapshot, data = fixture()
    return plan_modes(snapshot, "card0-HDMI-A-1", data)


class MemoryBackend(activation_tests.MemoryBackend):
    set_mode = activation_tests.MemoryBackend.set_enabled


class ModePlanningTests(unittest.TestCase):
    def test_alternatives_preserve_everything_except_target_mode(self):
        sequence = plans()
        self.assertEqual([p.mode_id for p in sequence], ["2", "3", "4"])
        for plan in sequence:
            restored = copy.deepcopy(plan.expected)
            restored[plan.output]["currentModeId"] = "1"
            self.assertEqual(restored, plan.before)
            self.assertEqual(decode_plan(asdict(plan)), plan)
        self.assertIn("1280 x 720 @ 60.00 Hz", sequence[0].description)
        self.assertIn("1920 x 1080 @ 50.00 Hz", sequence[2].description)

    def test_deduplicates_skips_current_and_limits_trials_deterministically(self):
        snapshot, data = fixture()
        modes = data["outputs"][1]["modes"]
        modes.append({**copy.deepcopy(modes[1]), "id": "duplicate"})
        modes.extend({"id": str(n), "size": {"width": 800 + n, "height": 600}, "refreshRate": 60}
                     for n in range(10, 20))
        first = plan_modes(snapshot, snapshot.connectors[1].name, data)
        modes.reverse()
        second = plan_modes(snapshot, snapshot.connectors[1].name, data)
        self.assertEqual(first, second)
        self.assertEqual(len(first), MAX_MODE_TRIALS)
        self.assertEqual(len({json.dumps(p.before[p.output]["modes"][p.mode_id], sort_keys=True) for p in first}), MAX_MODE_TRIALS)

    def test_rejects_inactive_internal_ambiguous_and_only_active_screen(self):
        snapshot, data = fixture()
        for attr, value in (("enabled", "disabled"), ("kind", "internal"), ("status", "disconnected")):
            altered = replace(snapshot, connectors=[snapshot.connectors[0], replace(snapshot.connectors[1], **{attr: value})])
            with self.subTest(attr=attr), self.assertRaises(Unavailable):
                plan_modes(altered, snapshot.connectors[1].name, data)
        data["outputs"][0].update(enabled=False, priority=0)
        data["outputs"][1]["priority"] = 1
        with self.assertRaises(Unavailable):
            plan_modes(snapshot, snapshot.connectors[1].name, data)

    def test_unsafe_ids_clones_missing_modes_and_nonintegral_geometry(self):
        snapshot, original = fixture()
        for attr, value in (("currentModeId", "missing"), ("followPreferredMode", True),
                            ("replicationSource", 1), ("clones", [1]), ("scale", 1.3)):
            data = copy.deepcopy(original)
            data["outputs"][1][attr] = value
            with self.subTest(attr=attr), self.assertRaises(Unavailable):
                plan_modes(snapshot, snapshot.connectors[1].name, data)
        data = copy.deepcopy(original)
        target = data["outputs"][1]
        for mode in target["modes"][1:]:
            mode["id"] += ".enable"
        with self.assertRaises(Unavailable):
            plan_modes(snapshot, snapshot.connectors[1].name, data)
        target["currentModeId"] = "1.0"
        target["modes"][0]["id"] = "1.0"
        with self.assertRaises(Unavailable):
            plan_modes(snapshot, snapshot.connectors[1].name, data)

    def test_skips_candidates_overlapping_other_screens(self):
        snapshot, data = fixture()
        data["outputs"][1]["pos"] = {"x": 0, "y": 0}
        data["outputs"][0]["pos"] = {"x": 1920, "y": 0}
        data["outputs"][1]["modes"].append({"id": "big", "size": {"width": 3840, "height": 2160}, "refreshRate": 60})
        self.assertNotIn("big", [p.mode_id for p in plan_modes(snapshot, snapshot.connectors[1].name, data)])
        data["outputs"][0]["pos"] = {"x": 0, "y": 0}
        with self.assertRaises(Unavailable):
            plan_modes(snapshot, snapshot.connectors[1].name, data)

    def test_rotation_and_fractional_scale_are_preserved(self):
        snapshot, data = fixture()
        data["outputs"][1].update(scale=1.25, rotation=2)
        sequence = plan_modes(snapshot, snapshot.connectors[1].name, data)
        self.assertEqual([p.mode_id for p in sequence], ["2", "4"])
        self.assertEqual(sequence[0].expected["HDMI-A-1"]["rotation"], 2)

    def test_gnome_mode_trials_use_gnome_without_querying_kde(self):
        snapshot, _ = fixture()
        with patch("beamfix.kde_fix.KDEBackend.query") as query, \
                patch("beamfix.gnome_modes.GNOMEModeBackend.prepare_modes", return_value="gnome-plans") as prepare:
            self.assertEqual(prepare_modes(replace(snapshot, desktop="GNOME"), snapshot.connectors[1].name), "gnome-plans")
            prepare.assert_called_once_with(snapshot.connectors[1].name)
        query.assert_not_called()
        with self.assertRaises(Unavailable):
            decode_plan({**asdict(plans()[0]), "backend": "unsupported"})

    def test_exact_mode_commands_apply_and_restore_without_shell(self):
        plan = plans()[0]
        backend = KDEModeBackend(plan.mode_id)
        for forward, state, identifier in ((True, plan.before, "2"), (False, plan.expected, "1")):
            with patch.object(backend, "state", return_value=state), \
                    patch("beamfix.kde_modes.shutil.which", return_value="/usr/bin/kscreen-doctor"), \
                    patch("beamfix.kde_modes.subprocess.run", return_value=Mock(returncode=0)) as command:
                backend.set_mode(plan, forward)
                self.assertEqual(command.call_args.args[0], ["/usr/bin/kscreen-doctor", f"output.HDMI-A-1.mode.{identifier}"])
                self.assertNotIn("shell", command.call_args.kwargs)
                self.assertEqual(command.call_args.kwargs["timeout"], 5)
        with patch.object(backend, "state", return_value={}), \
                patch("beamfix.kde_modes.subprocess.run") as command, self.assertRaises(Unavailable):
            backend.set_mode(plan, True)
        command.assert_not_called()

    def test_fresh_planning_rejects_mode_removed_after_preview(self):
        snapshot, data = fixture()
        backend = KDEModeBackend("2")
        with patch("beamfix.kde_modes.collect", return_value=snapshot), patch.object(backend, "query", return_value=data):
            self.assertEqual(backend.prepare(snapshot.connectors[1].name), plans()[0])
            data["outputs"][1]["modes"] = [m for m in data["outputs"][1]["modes"] if m["id"] != "2"]
            with self.assertRaises(Unavailable):
                backend.prepare(snapshot.connectors[1].name)


class ModeTransactionTests(unittest.TestCase):
    def setUp(self):
        self.plan = plans()[0]
        self.backend = MemoryBackend(self.plan)
        self.channel = Mock()

    def test_only_timely_explicit_next_advances_after_verified_undo(self):
        for decision, status in (("keep", "kept"), ("next", "next"), ("undo", "reverted"), ("bad", "reverted")):
            backend = MemoryBackend(self.plan)
            self.channel.receive.side_effect = [{"action": "apply"}, {"action": decision}]
            result = transact(self.plan, backend, self.channel)
            self.assertEqual(result.status, status)
            self.assertEqual(backend.current, self.plan.expected if decision == "keep" else self.plan.before)
        for decision in (TimeoutError(), EOFError(), {"action": "next"}):
            self.channel.receive.side_effect = [{"action": "apply"}, decision]
            result = transact(self.plan, self.backend, self.channel, seconds=0)
            self.assertEqual(result.status, "reverted")

    def test_next_never_overwrites_external_changes_or_failed_recovery(self):
        def receive(timeout):
            if not self.backend.writes:
                return {"action": "apply"}
            self.backend.current["eDP-1"]["scale"] = 2
            return {"action": "next"}
        self.channel.receive.side_effect = receive
        result = transact(self.plan, self.backend, self.channel)
        self.assertEqual(result.status, "attention")
        self.assertEqual(self.backend.writes, [True])

    def test_failed_command_or_no_effect_never_advances(self):
        for change in (Mock(), Mock(side_effect=Unavailable("command failed"))):
            self.backend.set_mode = change
            self.channel.receive.side_effect = [{"action": "apply"}, {"action": "next"}]
            result = transact(self.plan, self.backend, self.channel)
            self.assertEqual(result.status, "reverted")
            self.assertEqual(self.channel.receive.call_count, 1)
            self.channel.reset_mock()

    def test_each_trial_starts_from_original_and_second_can_be_kept(self):
        sequence = plans()
        state = copy.deepcopy(sequence[0].before)
        calls = []
        def attempt(plan, confirm):
            nonlocal state
            self.assertEqual(state, plan.before)
            backend = MemoryBackend(plan)
            channel = Mock()
            channel.receive.side_effect = [{"action": "apply"}, {"action": "next" if not calls else "keep"}]
            result = transact(plan, backend, channel)
            state = backend.current
            calls.append(plan)
            return result
        result = run_mode_sequence(sequence, Mock(), run_attempt=attempt)
        self.assertEqual(result.status, "kept")
        self.assertEqual(len(calls), 2)
        self.assertEqual(state, sequence[1].expected)
        self.assertIn("Trial 1/3", result.detail)
        self.assertIn("Trial 2/3", result.detail)

    def test_stop_error_and_exhaustion_bound_the_sequence(self):
        for status in ("reverted", "attention", "refused", "kept"):
            attempt = Mock(return_value=FixResult(status, "detail", True))
            self.assertEqual(run_mode_sequence(plans(), Mock(), run_attempt=attempt).status, status)
            attempt.assert_called_once()
        attempt = Mock(return_value=FixResult("next", "restored", True))
        result = run_mode_sequence(plans(), Mock(), run_attempt=attempt)
        self.assertEqual(result.status, "exhausted")
        self.assertEqual(attempt.call_count, 3)
        for invalid in ((), plans() * 3, [plans()[0], replace(plans()[1], output="eDP-1")]):
            attempt.reset_mock()
            self.assertEqual(run_mode_sequence(invalid, Mock(), run_attempt=attempt).status, "refused")
            attempt.assert_not_called()


class ModeInterfaceTests(unittest.TestCase):
    def test_terminal_clears_stale_input_and_distinguishes_next_from_silence(self):
        for answer, decision in ((b"1\n", "keep"), (b"2\n", "next"), (b"0\n", "undo"),
                                 (b"garbage\n", "undo"), (b"1 2\n", "undo"), (None, "undo")):
            master, slave = os.openpty()
            try:
                os.write(master, b"1\n")
                stdin = Mock()
                stdin.fileno.return_value = slave
                def render(line):
                    if answer and "Press Enter" in line:
                        os.write(master, answer)
                with patch("sys.stdin", stdin):
                    self.assertEqual(confirm_mode_in_terminal(Terminal(write=render), 0.1), decision)
            finally:
                os.close(master)
                os.close(slave)

    def test_preview_manual_skip_and_nonterminal_do_not_start(self):
        for answer, result in (("2", "manual"), ("3", "skip")):
            with patch("sys.stdin.isatty", return_value=True), \
                    patch("beamfix.fix_backends.prepare_modes", return_value=plans()), \
                    patch("beamfix.automatic.run_mode_sequence") as start:
                self.assertEqual(offer_modes("card0-HDMI-A-1", lambda _: answer,
                                            Terminal(write=lambda _: None), snapshot=fixture()[0]), result)
                start.assert_not_called()
        with patch("sys.stdin.isatty", return_value=False), patch("beamfix.fix_backends.prepare_modes") as prepare:
            self.assertEqual(offer_modes("target", Mock(), Terminal(write=lambda _: None), snapshot=fixture()[0]), "manual")
            prepare.assert_not_called()

    def test_guided_flow_offers_modes_before_mirroring_and_reports_confirmation(self):
        for status, code in (("kept", 0), ("exhausted", 2), ("attention", 2), ("reverted", 2)):
            answers = iter(["1", "4", "1", "2"])  # no signal, unknown path, output, skip input
            output = []
            with patch("beamfix.troubleshoot.offer_modes", return_value=FixResult(status, "trial history", True)) as offer:
                self.assertEqual(run(snapshot_reader=lambda: fixture()[0], read=lambda _: next(answers),
                                     write=output.append, try_fix=True), code)
            offer.assert_called_once()
            self.assertIn("trial history", "\n".join(output))


class ModeProcessRecoveryTests(activation_tests.ProcessRecoveryTests):
    def setUp(self):
        # Inherit real socket/process-death checks using simulated mode writes.
        harness = activation_tests.HARNESS.replace(
            "fix_worker.main()", "Backend.set_mode = Backend.set_enabled\n"
            "fix_worker.KDEModeBackend = lambda mode_id: Backend()\nfix_worker.main()")
        for patcher in (patch.object(activation_tests, "HARNESS", harness),
                        patch.object(activation_tests, "make_plan", lambda: plans()[0])):
            patcher.start()
            self.addCleanup(patcher.stop)
        super().setUp()

    def test_next_result_requires_real_worker_undo(self):
        process, _, channel = self.launch()
        channel.send({"action": "next"})
        result = channel.receive(5)
        if result.get("event") == "recovering":
            result = channel.receive(5)
        self.assertEqual(result["status"], "next")
        process.wait(timeout=5)
        self.assertEqual(json.loads(self.state.read_text()), self.plan.before)

    def test_client_maps_next_to_undo_and_next_rather_than_keep(self):
        original = subprocess.Popen

        def spawn(arguments, **kwargs):
            process = original([activation_tests.sys.executable, "-c", activation_tests.HARNESS, arguments[-1]],
                               **{**kwargs, "env": self.environment})
            self.processes.append(process)
            return process

        with patch("beamfix.automatic.subprocess.Popen", side_effect=spawn):
            result = run_activation(self.plan, lambda seconds: "next")
        self.assertEqual(result.status, "next")
        self.assertEqual(json.loads(self.state.read_text()), self.plan.before)
