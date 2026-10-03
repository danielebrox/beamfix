import copy
import json
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, patch

import test_automatic as activation_tests
import test_gnome
import test_modes as kde_tests
from beamfix.automatic import run_mode_sequence
from beamfix.fix_backends import decode_plan, prepare_modes
from beamfix.fix_worker import FixResult, transact
from beamfix.gnome_fix import APPLY_SIGNATURE, configuration
from beamfix.gnome_modes import GNOMEModeBackend, plan_modes
from beamfix.kde_fix import Unavailable
from beamfix.mode_trials import MAX_MODE_TRIALS
from beamfix.terminal import Terminal
from beamfix.troubleshoot import offer_modes, run


def fixture():
    snapshot, reply = test_gnome.fixture()
    snapshot.desktop = 'GNOME'
    snapshot.connectors[1] = replace(snapshot.connectors[1], enabled='enabled')
    reply = test_gnome.activate_reply(reply)
    modes = reply['data'][1][1][1]
    modes.extend([
        ['1280x720@60', 1280, 720, 60.0, 1.0, [1.0, 1.5, 2.0], {}],
        ['1024x768@60', 1024, 768, 60.0, 1.0, [1.0, 1.5, 2.0], {}],
        ['1920x1080@50', 1920, 1080, 50.0, 1.0, [1.0, 1.5, 2.0], {}],
    ])
    return snapshot, reply


def plans():
    snapshot, reply = fixture()
    return plan_modes(snapshot, 'card0-HDMI-A-1', reply)


def applied_reply(reply, mode_id):
    result = copy.deepcopy(reply)
    result['data'][0] += 1
    for mode in result['data'][1][1][1]:
        mode[6].pop('is-current', None)
        if mode[0] == mode_id:
            mode[6]['is-current'] = test_gnome.variant('b', True)
    return result


class GNOMEModePlanningTests(unittest.TestCase):
    def test_only_target_mode_changes_and_plan_roundtrips(self):
        sequence = plans()
        self.assertEqual([p.mode_id for p in sequence], ['1280x720@60', '1024x768@60', '1920x1080@50'])
        for plan in sequence:
            self.assertEqual(decode_plan(json.loads(json.dumps(asdict(plan)))), plan)
            self.assertEqual(configuration(applied_reply(fixture()[1], plan.mode_id))[1], plan.expected)
            expected = copy.deepcopy(plan.before)
            next(i for i in expected['logical'] if i['output'] == 'HDMI-1')['mode'] = plan.mode_id
            self.assertEqual(plan.expected, expected)
            self.assertIn('temporary for this session', plan.description)
            self.assertNotIn('private-', json.dumps(asdict(plan)))

    def test_deduplication_limit_and_input_order(self):
        snapshot, reply = fixture()
        modes = reply['data'][1][1][1]
        duplicate = copy.deepcopy(modes[1])
        duplicate[0] = 'duplicate'
        modes.append(duplicate)
        modes.extend([[str(n), 800 + n, 600, 60.0, 1.0, [1.0], {}] for n in range(10, 20)])
        first = plan_modes(snapshot, snapshot.connectors[1].name, reply)
        modes.reverse()
        reply['data'][0] += 1
        second = plan_modes(snapshot, snapshot.connectors[1].name, reply)
        self.assertEqual(first, second)
        self.assertEqual(len(first), MAX_MODE_TRIALS)
        signatures = {(p.before['monitors'][p.output]['modes'][p.mode_id]['width'],
                       p.before['monitors'][p.output]['modes'][p.mode_id]['height'],
                       p.before['monitors'][p.output]['modes'][p.mode_id]['hz']) for p in first}
        self.assertEqual(len(signatures), MAX_MODE_TRIALS)

    def test_skips_interlaced_variable_and_unsupported_scale(self):
        snapshot, reply = fixture()
        modes = reply['data'][1][1][1]
        modes[1][6]['is-interlaced'] = test_gnome.variant('b', True)
        modes[2][6]['refresh-rate-mode'] = test_gnome.variant('s', 'variable')
        self.assertEqual([p.mode_id for p in plan_modes(snapshot, snapshot.connectors[1].name, reply)], ['1920x1080@50'])
        modes[3][4:6] = [2.0, [2.0]]
        with self.assertRaisesRegex(Unavailable, 'No distinct GNOME modes'):
            plan_modes(snapshot, snapshot.connectors[1].name, reply)

    def test_fractional_scale_rotation_global_scale_and_physical_layout(self):
        snapshot, reply = fixture()
        for monitor in reply['data'][1]:
            for mode in monitor[1]:
                mode[5].append(1.25)
        reply['data'][2][1][2:4] = [1.25, 1]
        sequence = plan_modes(snapshot, snapshot.connectors[1].name, reply)
        self.assertEqual([p.mode_id for p in sequence], ['1280x720@60', '1920x1080@50'])
        self.assertEqual(sequence[0].expected['logical'][0]['scale'], 1.25)
        self.assertEqual(sequence[0].expected['logical'][0]['transform'], 1)
        reply['data'][3]['global-scale-required'] = test_gnome.variant('b', True)
        reply['data'][2][0][2] = 1.25
        reply['data'][2][1][0] = 1536
        self.assertTrue(plan_modes(snapshot, snapshot.connectors[1].name, reply))
        reply['data'][3]['layout-mode'] = test_gnome.variant('u', 2)
        reply['data'][2][1][0] = 1920
        self.assertEqual(len(plan_modes(snapshot, snapshot.connectors[1].name, reply)), 3)

    def test_left_target_skips_shrinking_gap_and_growing_overlap(self):
        snapshot, reply = fixture()
        reply['data'][2][0][0] = 1920
        reply['data'][2][1][0] = 0
        reply['data'][1][1][1].append(['4k', 3840, 2160, 60.0, 1.0, [1.0], {}])
        sequence = plan_modes(snapshot, snapshot.connectors[1].name, reply)
        self.assertEqual([p.mode_id for p in sequence], ['1920x1080@50'])
        for x in (10, 1930):
            reply['data'][2][0][0] = x
            with self.assertRaises(Unavailable):
                plan_modes(snapshot, snapshot.connectors[1].name, reply)

    def test_rejects_unmatched_internal_inactive_and_only_active_target(self):
        snapshot, reply = fixture()
        for attr, value in (('kind', 'internal'), ('enabled', 'disabled'), ('status', 'unknown'), ('modes', None)):
            changed = replace(snapshot, connectors=[snapshot.connectors[0], replace(snapshot.connectors[1], **{attr: value})])
            with self.subTest(attr=attr), self.assertRaises(Unavailable):
                plan_modes(changed, snapshot.connectors[1].name, reply)
        duplicate = replace(snapshot, connectors=snapshot.connectors + [replace(snapshot.connectors[1], name='card1-HDMI-A-1')])
        with self.assertRaises(Unavailable):
            plan_modes(duplicate, snapshot.connectors[1].name, reply)
        reply['data'][1][0][1][0][6].pop('is-current')
        reply['data'][2] = [reply['data'][2][1]]
        reply['data'][2][0][4] = True
        with self.assertRaisesRegex(Unavailable, 'Another active screen'):
            plan_modes(snapshot, snapshot.connectors[1].name, reply)

    def test_primary_external_settings_remain_unchanged(self):
        snapshot, reply = fixture()
        reply['data'][2][0][4], reply['data'][2][1][4] = False, True
        reply['data'][1][1][2]['color-mode'] = test_gnome.variant('u', 1)
        reply['data'][1][1][2]['rgb-range'] = test_gnome.variant('u', 3)
        reply['data'][1][1][2]['is-underscanning'] = test_gnome.variant('b', True)
        plan = plan_modes(snapshot, snapshot.connectors[1].name, reply)[0]
        self.assertEqual(plan.before['monitors'], plan.expected['monitors'])
        self.assertTrue(next(i for i in plan.expected['logical'] if i['output'] == plan.output)['primary'])

    def test_cloned_leased_unknown_and_overflowing_layout_fall_back(self):
        snapshot, base = fixture()
        for mutator in (
            lambda r: r['data'][2][0][5].append(r['data'][1][1][0]),
            lambda r: r['data'][1][1][2].update({'is-for-lease': test_gnome.variant('b', True)}),
            lambda r: r['data'][2][1][6].update({'unknown': test_gnome.variant('b', True)}),
            lambda r: r['data'][2][1].__setitem__(0, 2**31 - 1),
        ):
            reply = copy.deepcopy(base)
            mutator(reply)
            with self.assertRaises(Unavailable):
                plan_modes(snapshot, snapshot.connectors[1].name, reply)


class GNOMEModeTransportTests(unittest.TestCase):
    def test_fresh_serial_temporary_verify_apply_and_undo(self):
        _, reply = fixture()
        plan = plans()[0]
        backend = GNOMEModeBackend(plan.mode_id)
        backend.allowed = Mock()
        backend._request = Mock()
        backend.query = Mock(return_value=reply)
        backend.set_mode(plan, True)
        self.assertEqual([c.args[2][:4] for c in backend._request.call_args_list],
                         [[APPLY_SIGNATURE, '43', '0', '2'], [APPLY_SIGNATURE, '43', '1', '2']])
        backend._request.reset_mock()
        backend.query.return_value = applied_reply(reply, plan.mode_id)
        backend.set_mode(plan, False)
        self.assertEqual([c.args[2][:4] for c in backend._request.call_args_list],
                         [[APPLY_SIGNATURE, '44', '0', '2'], [APPLY_SIGNATURE, '44', '1', '2']])
        self.assertIn('1920x1080@60', backend._request.call_args.args[2])
        self.assertNotIn(plan.mode_id, backend._request.call_args.args[2])

    def test_changed_state_denial_and_verification_failure_prevent_apply(self):
        backend = GNOMEModeBackend(plans()[0].mode_id)
        backend.allowed = Mock()
        backend.query = Mock(return_value=fixture()[1])
        backend._request = Mock(side_effect=Unavailable('verify rejected'))
        with self.assertRaises(Unavailable):
            backend.set_mode(plans()[0], True)
        backend._request.assert_called_once()
        backend._request.reset_mock()
        backend.query.return_value['data'][2][0][2] = 2.0
        with self.assertRaises(Unavailable):
            backend.set_mode(plans()[0], True)
        backend._request.assert_not_called()
        backend.allowed.side_effect = Unavailable('denied')
        backend.query.reset_mock()
        with self.assertRaises(Unavailable):
            backend.set_mode(plans()[0], True)
        backend.query.assert_not_called()

    def test_prepare_routes_to_gnome_and_revalidates_candidates(self):
        snapshot, reply = fixture()
        with patch('beamfix.gnome_modes.collect', return_value=snapshot), \
                patch('beamfix.gnome_modes.GNOMEModeBackend.allowed'), \
                patch('beamfix.gnome_modes.GNOMEModeBackend.query', return_value=reply), \
                patch('beamfix.kde_fix.KDEBackend.query') as kde:
            self.assertEqual(prepare_modes(snapshot, snapshot.connectors[1].name), plans())
            backend = GNOMEModeBackend('1280x720@60')
            self.assertEqual(backend.prepare(snapshot.connectors[1].name), plans()[0])
            reply['data'][1][1][1] = [m for m in reply['data'][1][1][1] if m[0] != '1280x720@60']
            with self.assertRaises(Unavailable):
                backend.prepare(snapshot.connectors[1].name)
            kde.assert_not_called()


class GNOMEModeTransactionTests(kde_tests.ModeTransactionTests):
    def setUp(self):
        patcher = patch.object(kde_tests, 'plans', plans)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_next_never_overwrites_external_changes_or_failed_recovery(self):
        def receive(timeout):
            if not self.backend.writes:
                return {'action': 'apply'}
            self.backend.current['logical'][1]['scale'] = 2
            return {'action': 'next'}
        self.channel.receive.side_effect = receive
        result = transact(self.plan, self.backend, self.channel)
        self.assertEqual(result.status, 'attention')
        self.assertEqual(self.backend.writes, [True])


class GNOMEModeInterfaceTests(unittest.TestCase):
    def test_preview_names_gnome_and_runs_the_selected_sequence(self):
        output = []
        with patch('sys.stdin.isatty', return_value=True), \
                patch('beamfix.fix_backends.prepare_modes', return_value=plans()), \
                patch('beamfix.automatic.run_mode_sequence', return_value=FixResult('kept', 'confirmed', True)) as start:
            result = offer_modes('card0-HDMI-A-1', lambda _: '1', Terminal(write=output.append), snapshot=fixture()[0])
        self.assertEqual(result.status, 'kept')
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0], plans())
        self.assertIn('modes listed by GNOME', '\n'.join(output))
        self.assertIn('temporary for this session', '\n'.join(output))

    def test_full_guided_gnome_flow_has_correct_success_and_failure_codes(self):
        for status, code in (('kept', 0), ('exhausted', 2), ('attention', 2), ('reverted', 2)):
            answers = iter(['1', '4', '1', '2', '1'])
            output = []
            with patch('sys.stdin.isatty', return_value=True), \
                    patch('beamfix.fix_backends.prepare_modes', return_value=plans()), \
                    patch('beamfix.automatic.run_mode_sequence', return_value=FixResult(status, 'GNOME trial history', True)):
                self.assertEqual(run(snapshot_reader=lambda: fixture()[0], read=lambda _: next(answers),
                                     write=output.append, try_fix=True), code)
            self.assertIn('GNOME trial history', '\n'.join(output))


class GNOMEModeProcessRecoveryTests(activation_tests.ProcessRecoveryTests):
    def setUp(self):
        harness = activation_tests.HARNESS.replace(
            'fix_worker.main()', 'Backend.set_mode = Backend.set_enabled\n'
            'fix_worker.GNOMEModeBackend = lambda mode_id: Backend()\nfix_worker.main()')
        for patcher in (patch.object(activation_tests, 'HARNESS', harness),
                        patch.object(activation_tests, 'make_plan', lambda: plans()[0])):
            patcher.start()
            self.addCleanup(patcher.stop)
        super().setUp()

    def test_next_is_returned_after_verified_original_layout(self):
        process, _, channel = self.launch()
        channel.send({'action': 'next'})
        result = channel.receive(5)
        if result.get('event') == 'recovering':
            result = channel.receive(5)
        self.assertEqual(result['status'], 'next')
        process.wait(timeout=5)
        self.assertEqual(json.loads(self.state.read_text()), self.plan.before)
