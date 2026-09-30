import contextlib
import io
import json
import subprocess
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

from beamfix.cli import main
from beamfix.desktop import add_current_modes
from beamfix.models import Connector, Snapshot, VideoMode
from beamfix.terminal import Terminal, render_doctor
from beamfix.troubleshoot import describe, next_step, run
from beamfix.wayland import add_wayland_modes, apply_wayland_modes, parse_outputs


# Same field layout as wayland-info -i wl_output, with synthetic device data.
def output(name='HDMI-A-1', width=1920, height=1080, rate='59.940', flags='current'):
    return ("interface: 'wl_output',                                  version:  4, name: 66\n"
            f"\tname: {name}\n\tdescription: PRIVATE_DESCRIPTION\n"
            "\tx: 0, y: 0, scale: 2,\n"
            "\tphysical_width: 500 mm, physical_height: 300 mm,\n"
            "\tmake: 'PRIVATE_MAKE', model: 'PRIVATE_MODEL',\n"
            "\tsubpixel_orientation: unknown, output_transform: normal,\n"
            f"\tmode:\n\t\twidth: {width} px, height: {height} px, refresh: {rate} Hz,\n"
            f"\t\tflags: {flags}\n")


def snapshot(desktop='GNOME', **changes):
    c = Connector('card0-HDMI-A-1', 'external', 'connected', 'enabled', ('1920x1080',))
    return Snapshot('Linux', 'test', 'wayland', desktop, connectors=[replace(c, **changes)])


class WaylandParsingTests(unittest.TestCase):
    def test_current_mode_is_reported_not_listed(self):
        data = apply_wayland_modes(snapshot(), output())
        observation = data.connectors[0].current_mode
        self.assertEqual(observation.state, 'reported')
        self.assertEqual(observation.source, 'wayland-info')
        self.assertEqual(observation.mode, VideoMode(1920, 1080, 59.94))
        self.assertEqual(data.connectors[0].modes, ('1920x1080',))
        self.assertNotIn('PRIVATE', json.dumps(asdict(data)))

    def test_preferred_is_not_current_and_scale_does_not_change_pixels(self):
        preferred = output(width=3840, height=2160, rate='120.000', flags='preferred').split('\tmode:', 1)[1]
        raw = output() + '\tmode:' + preferred
        self.assertEqual(parse_outputs(raw), [('HDMI-A-1', VideoMode(1920, 1080, 59.94))])
        self.assertEqual(parse_outputs(output(flags='current, preferred'))[0][1].refresh_hz, 59.94)

    def test_missing_zero_or_invalid_mode_is_unknown(self):
        invalid = [output(rate='0.000'), output(width=0), output(height=-1), output(rate='nan'),
                   output(rate='inf'), output(rate='60,000'), output(rate='-60.000'),
                   output(width=2147483648), output(rate='2147483.648'), output(flags='preferred'),
                   output(flags='not-current'), output().replace('\t\tflags: current\n', ''),
                   output().replace('width:', 'unknown-format:'), output().split('\tmode:', 1)[0],
                   output() + '\tmode:' + output().split('\tmode:', 1)[1]]
        for raw in invalid:
            with self.subTest(raw=raw):
                obs = apply_wayland_modes(snapshot(), raw).connectors[0].current_mode
                self.assertEqual(obs.state, 'unknown')
                self.assertIsNone(obs.mode)

    def test_empty_missing_name_unmatched_name_and_other_interface_are_unknown(self):
        for raw in ('', 'invalid', output(name='WL-1'), output().replace('\tname: HDMI-A-1\n', ''),
                    output().replace("'wl_output'", "'xdg_output'")):
            obs = apply_wayland_modes(snapshot(), raw).connectors[0].current_mode
            self.assertEqual(obs.state, 'unknown')
            self.assertIsNone(obs.mode)

    def test_duplicate_wayland_or_drm_names_are_ambiguous(self):
        self.assertEqual(apply_wayland_modes(snapshot(), output() * 2).connectors[0].current_mode.state, 'unknown')
        data = snapshot()
        data.connectors.append(replace(data.connectors[0], name='card1-HDMI-A-1'))
        apply_wayland_modes(data, output())
        self.assertTrue(all(c.current_mode.state == 'unknown' for c in data.connectors))

    def test_each_output_gets_its_own_mode(self):
        data = snapshot()
        data.connectors.append(replace(data.connectors[0], name='card1-DP-1'))
        apply_wayland_modes(data, output('DP-1', rate='144.000') + output())
        self.assertEqual([c.current_mode.mode.refresh_hz for c in data.connectors], [59.94, 144])

    def test_absence_is_inactive_only_with_drm_evidence(self):
        for changes in ({'enabled': 'disabled'}, {'status': 'disconnected'}):
            self.assertEqual(apply_wayland_modes(snapshot(**changes), '').connectors[0].current_mode.state, 'inactive')
        self.assertEqual(apply_wayland_modes(snapshot(), '').connectors[0].current_mode.state, 'unknown')

    def test_disagreement_or_unknown_drm_does_not_report_active_mode(self):
        for changes in ({'enabled': 'disabled'}, {'status': 'disconnected'},
                        {'enabled': 'unknown'}, {'status': 'unknown'}):
            obs = apply_wayland_modes(snapshot(**changes), output()).connectors[0].current_mode
            self.assertEqual(obs.state, 'unknown')
            self.assertIsNone(obs.mode)

    def test_later_missing_observation_never_reuses_old_mode(self):
        data = apply_wayland_modes(snapshot(), output())
        apply_wayland_modes(data, '')
        self.assertEqual(data.connectors[0].current_mode.state, 'unknown')
        self.assertIsNone(data.connectors[0].current_mode.mode)


class WaylandQueryTests(unittest.TestCase):
    @patch('beamfix.wayland.shutil.which', return_value='/usr/bin/wayland-info')
    @patch('beamfix.wayland.subprocess.run')
    def test_desktops_share_one_read_only_query(self, query, which):
        query.return_value = subprocess.CompletedProcess([], 0, output())
        for desktop in ('GNOME', 'Hyprland', 'X-Cinnamon', 'sway', 'unknown'):
            with self.subTest(desktop=desktop):
                self.assertEqual(add_current_modes(snapshot(desktop)).connectors[0].current_mode.state, 'reported')
        self.assertEqual(query.call_count, 5)
        args, kwargs = query.call_args
        self.assertEqual(args[0], ['/usr/bin/wayland-info', '-i', 'wl_output'])
        self.assertEqual(kwargs['timeout'], 5)
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(kwargs['env']['LC_ALL'], 'C')
        self.assertFalse(kwargs['check'])

    @patch('beamfix.desktop._query_kde', return_value=(None, 'Unavailable'))
    @patch('beamfix.desktop.add_wayland_modes')
    def test_kde_unavailable_uses_wayland(self, wayland, kde):
        data = snapshot('KDE')
        add_current_modes(data)
        wayland.assert_called_once_with(data)

    @patch('beamfix.desktop.shutil.which', side_effect=lambda name: '/usr/bin/' + name)
    def test_failed_kde_query_really_falls_back_to_standard_output(self, which):
        for failure in (subprocess.CompletedProcess([], 1, ''),
                        subprocess.CompletedProcess([], 0, 'invalid JSON'),
                        subprocess.CompletedProcess([], 0, '{}')):
            with self.subTest(failure=failure), patch('beamfix.desktop.subprocess.run', side_effect=[
                failure, subprocess.CompletedProcess([], 0, output()),
            ]) as query:
                obs = add_current_modes(snapshot('KDE')).connectors[0].current_mode
                self.assertEqual(obs.state, 'reported')
                self.assertEqual(obs.mode.refresh_hz, 59.94)
                self.assertEqual(query.call_args_list[0].args[0], ['/usr/bin/kscreen-doctor', '--json'])
                self.assertEqual(query.call_args_list[1].args[0], ['/usr/bin/wayland-info', '-i', 'wl_output'])

    @patch('beamfix.desktop.add_wayland_modes')
    def test_kde_valid_response_keeps_richer_or_conflicting_observations(self, wayland):
        raw = {'outputs': [{'name': 'HDMI-A-1', 'connected': True, 'enabled': True,
                            'currentModeId': '1', 'modes': [{'id': '1', 'size': {'width': 1920, 'height': 1080}, 'refreshRate': 60}]}]}
        with patch('beamfix.desktop._query_kde', return_value=(raw, None)):
            self.assertEqual(add_current_modes(snapshot('KDE')).connectors[0].current_mode.state, 'listed')
            raw['outputs'][0]['enabled'] = False
            self.assertEqual(add_current_modes(snapshot('KDE')).connectors[0].current_mode.state, 'unknown')
        wayland.assert_not_called()

    @patch('beamfix.wayland.subprocess.run')
    def test_x11_headless_and_non_linux_do_not_launch_wayland(self, query):
        for session, system in (('x11', 'Linux'), ('tty', 'Linux'), ('wayland', 'Darwin')):
            data = snapshot()
            data.session, data.system = session, system
            self.assertEqual(add_current_modes(data).connectors[0].current_mode.state, 'unknown')
            add_wayland_modes(data)
        query.assert_not_called()

    @patch('beamfix.wayland.shutil.which', return_value=None)
    @patch('beamfix.wayland.subprocess.run')
    def test_missing_tool_preserves_basic_diagnostics(self, query, which):
        data = add_current_modes(snapshot())
        self.assertEqual(data.connectors[0].status, 'connected')
        self.assertIn('not installed', data.connectors[0].current_mode.reason)
        query.assert_not_called()

    @patch('beamfix.wayland.shutil.which', return_value='/usr/bin/wayland-info')
    def test_query_failures_preserve_drm_without_stale_mode(self, which):
        for failure in (subprocess.TimeoutExpired('wayland-info', 5), OSError(), UnicodeError()):
            with self.subTest(failure=failure), patch('beamfix.wayland.subprocess.run', side_effect=failure):
                data = add_wayland_modes(apply_wayland_modes(snapshot(), output()))
                self.assertEqual(data.connectors[0].current_mode.state, 'unknown')
                self.assertIsNone(data.connectors[0].current_mode.mode)
                self.assertEqual(data.connectors[0].modes, ('1920x1080',))
        with patch('beamfix.wayland.subprocess.run', return_value=subprocess.CompletedProcess([], 1, output())):
            self.assertEqual(add_wayland_modes(snapshot()).connectors[0].current_mode.state, 'unknown')


class WaylandPresentationTests(unittest.TestCase):
    def test_reported_mode_has_neutral_label_and_json_provenance(self):
        data = apply_wayland_modes(snapshot(), output())
        lines = []
        render_doctor(data, [], 0, terminal=Terminal(write=lines.append, plain=True))
        text = ' '.join(' '.join(lines).split())
        self.assertIn('[REPORTED]', text)
        self.assertIn('1920 x 1080 @ 59.94 Hz', text)
        self.assertNotIn('[LISTED]', text)
        self.assertNotIn('[CONFIRMED]', text)
        with patch('beamfix.cli.collect', return_value=data), contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(['doctor', '--json']), 0)
        report = json.loads(stream.getvalue())
        self.assertEqual(report['visual_confirmation'], 'not_performed')
        self.assertEqual(report['snapshot']['connectors'][0]['current_mode']['state'], 'reported')
        self.assertEqual(report['snapshot']['connectors'][0]['current_mode']['source'], 'wayland-info')

    def test_guided_mode_instruction_never_claims_mode_is_listed(self):
        data = apply_wayland_modes(snapshot(), output())
        step = next_step(data, data.connectors[0].name, 'black', {'input', 'mirror'})
        self.assertIn('Wayland reports 1920 x 1080 @ 59.94 Hz', step.reason)
        self.assertIn('available mode list is not verified', step.reason)
        self.assertNotIn('KDE', step.reason)
        self.assertIn('reported by Wayland', describe(data, data.connectors[0].name))

    def test_guided_before_after_and_visual_confirmation_remain_distinct(self):
        data = [apply_wayland_modes(snapshot(), output(rate=rate)) for rate in ('30.000', '60.000')]
        answers = iter(['2', '1', '1', '5'])
        lines = []
        with patch('beamfix.troubleshoot.collect', side_effect=data):
            code = run(read=lambda _: next(answers), write=lines.append)
        self.assertEqual(code, 2)
        summary = ' '.join('\n'.join(lines).split('SUMMARY', 1)[1].split())
        self.assertIn('@ 30.00 Hz', summary)
        self.assertIn('@ 60.00 Hz', summary)
        self.assertIn('Visual result: cannot be verified', summary)
        self.assertNotIn('Expected image confirmed by the user', summary)


if __name__ == '__main__':
    unittest.main()
