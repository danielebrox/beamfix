"""Fixtures follow upstream drm_info json.c; no real display writes are used."""
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from beamfix.cli import main
from beamfix.models import Connector, CurrentMode, Snapshot, VideoMode
from beamfix.signal import (add_signal_details, apply_signal_data, parse_timing,
                            query_signal, signal_lines, MAX_JSON_BYTES)
from beamfix.terminal import Terminal, render_doctor


def property_value(kind, value, spec=None):
    return {"type": kind, "raw_value": value, "value": None if kind == 16 else value, "spec": spec}


def enum(value, *names):
    return property_value(8, value, [{"value": index, "name": name} for index, name in enumerate(names)])


def timing(clock=148500, htotal=2200):
    return {"clock": clock, "hdisplay": 1920, "hsync_start": 2008, "hsync_end": 2052,
            "htotal": htotal, "hskew": 0, "vdisplay": 1080, "vsync_start": 1084,
            "vsync_end": 1089, "vtotal": 1125, "vscan": 0, "vrefresh": 60,
            "flags": 5, "type": 72, "name": "PRIVATE_MODE_NAME"}


def fixture():
    data = {"/dev/dri/card0": {
        "device": {"serial": "PRIVATE_DEVICE"},
        "connectors": [{"id": 51, "status": 1, "encoder_id": 42,
            "modes": [timing(), timing(150525, 2230)],
            "properties": {
                "CRTC_ID": property_value(64, 61),
                "max bpc": property_value(2, 12, {"min": 8, "max": 16}),
                "Colorspace": enum(0, "Default", "BT2020_RGB"),
                "color format": enum(0, "AUTO", "RGB", "YCbCr420"),
                "Broadcast RGB": enum(0, "Automatic", "Full", "Limited 16:235"),
                "HDR_OUTPUT_METADATA": {**property_value(16, 123), "data": {"PRIVATE_BLOB": "PRIVATE"}},
                "Content Protection": enum(1, "Undesired", "Desired", "Enabled"),
                "HDCP Content Type": enum(0, "HDCP Type0", "HDCP Type1"),
                "link-status": enum(0, "Good", "Bad"),
                "EDID": {"data": "PRIVATE_EDID"},
                "PATH": {"data": "PRIVATE_PATH"},
            }}],
        "crtcs": [{"id": 61, "mode": timing(), "properties": {"ACTIVE": property_value(2, 1)}}],
        "encoders": [{"id": 42, "crtc_id": 61}],
    }}
    snap = Snapshot("Linux", "test", "wayland", "GNOME", connectors=[
        Connector("card0-HDMI-A-1", "external", "connected", "enabled", ("1920x1080",),
                  CurrentMode("reported", "wayland-info", "Observed", VideoMode(1920, 1080, 60)))])
    return snap, data, {"card0-HDMI-A-1": ("card0", 51)}


class SignalParsingTests(unittest.TestCase):
    def observe(self, mutate=None):
        snap, data, identities = fixture()
        if mutate:
            mutate(snap, data, identities)
        return apply_signal_data(snap, data, identities).connectors[0].signal

    def test_limits_requests_and_driver_status_are_not_wire_measurements(self):
        signal = self.observe()
        self.assertEqual(signal.state, "observed")
        self.assertEqual(signal.properties["max_bpc"].value, 12)
        self.assertEqual(signal.properties["max_bpc"].meaning, "limit")
        self.assertEqual(signal.properties["actual_bpc"].state, "unavailable")
        self.assertEqual(signal.properties["color_format"].value, "AUTO")
        self.assertEqual(signal.properties["color_format"].meaning, "requested")
        self.assertEqual(signal.properties["content_protection"].value, "Desired")
        self.assertEqual(signal.properties["content_protection"].meaning, "driver_status")
        self.assertTrue(signal.properties["hdr_metadata_present"].value)
        self.assertNotIn("PRIVATE", json.dumps(asdict(signal)))

    def test_same_resolution_and_refresh_retain_distinct_timings(self):
        signal = self.observe()
        self.assertEqual(len(signal.listed_timings), 2)
        a, b = signal.listed_timings
        self.assertEqual((a.width, a.height, a.nominal_refresh_hz), (b.width, b.height, b.nominal_refresh_hz))
        self.assertNotEqual(a.pixel_clock_khz, b.pixel_clock_khz)
        self.assertEqual(signal.current_timing, a)

    def test_bad_timing_does_not_hide_valid_alternatives(self):
        signal = self.observe(lambda s,d,i: d['/dev/dri/card0']['connectors'][0]['modes'].extend([None, timing(), {**timing(), 'clock': True}]))
        self.assertEqual(signal.listed_timings_state, "partial")
        self.assertEqual(signal.invalid_listed_timings, 2)
        self.assertEqual(len(signal.listed_timings), 2)

    def test_interlaced_doublescan_and_vscan_rates(self):
        self.assertEqual(parse_timing({**timing(), "flags": 16}).nominal_refresh_hz, 120)
        self.assertEqual(parse_timing({**timing(), "flags": 32}).nominal_refresh_hz, 30)
        self.assertEqual(parse_timing({**timing(), "vscan": 2}).nominal_refresh_hz, 30)
        self.assertIsNone(parse_timing({**timing(), "htotal": 1000}))
        self.assertIsNone(parse_timing({**timing(), "vtotal": 0}))

    def test_gpu_and_connector_id_mapping_never_uses_order(self):
        snap, data, ids = fixture()
        other = copy.deepcopy(data['/dev/dri/card0'])
        other['connectors'][0]['properties']['max bpc'] = property_value(2, 8, {'min': 8, 'max': 16})
        data['/dev/dri/card1'] = other
        snap.connectors.append(replace(snap.connectors[0], name='card1-HDMI-A-1'))
        ids['card1-HDMI-A-1'] = ('card1', 51)
        apply_signal_data(snap, data, ids)
        self.assertEqual([c.signal.properties['max_bpc'].value for c in snap.connectors], [12, 8])

    def test_missing_or_duplicate_identity_is_unavailable(self):
        mutations = [lambda s,d,i: i.clear(),
            lambda s,d,i: d['/dev/dri/card0']['connectors'].append(copy.deepcopy(d['/dev/dri/card0']['connectors'][0])),
            lambda s,d,i: i.update({'card0-DP-1': ('card0', 51)})]
        for mutate in mutations:
            self.assertEqual(self.observe(mutate).state, 'unavailable')

    def test_connection_conflict_discards_properties(self):
        signal = self.observe(lambda s,d,i: d['/dev/dri/card0']['connectors'][0].update(status=2))
        self.assertEqual(signal.state, 'inconsistent')
        self.assertIsNone(signal.properties['max_bpc'].value)

    def test_disabled_output_never_reports_retained_settings_as_active(self):
        signal = self.observe(lambda s,d,i: s.connectors.__setitem__(0, replace(s.connectors[0], enabled='disabled')))
        self.assertEqual(signal.state, 'inactive')
        self.assertIsNone(signal.current_timing)
        self.assertIsNone(signal.properties['max_bpc'].value)

    def test_no_current_timing_guess_from_listed_or_inactive_crtc(self):
        for mutate in (
            lambda s,d,i: d['/dev/dri/card0']['connectors'][0]['properties'].pop('CRTC_ID'),
            lambda s,d,i: d['/dev/dri/card0']['crtcs'][0]['properties'].update(ACTIVE=property_value(2,0)),
            lambda s,d,i: d['/dev/dri/card0']['crtcs'].append(copy.deepcopy(d['/dev/dri/card0']['crtcs'][0])),
        ):
            signal = self.observe(mutate)
            self.assertIsNone(signal.current_timing)
            self.assertEqual(len(signal.listed_timings), 2)

    def test_current_timing_conflict_with_desktop_stays_explicit(self):
        signal = self.observe(lambda s,d,i: d['/dev/dri/card0']['crtcs'][0]['mode'].update(clock=74250))
        self.assertEqual(signal.current_timing_state, 'inconsistent')
        self.assertIsNone(signal.current_timing)
        self.assertIn('disagree', signal.current_timing_reason)

    def test_malformed_crtc_reference_is_not_an_integer(self):
        snap, data, ids = fixture()
        data['/dev/dri/card0']['crtcs'][0]['id'] = 1
        prop = data['/dev/dri/card0']['connectors'][0]['properties']['CRTC_ID']
        prop.update(value=1, raw_value=True)
        signal = apply_signal_data(snap, data, ids).connectors[0].signal
        self.assertIsNone(signal.current_timing)

    def test_missing_property_is_not_default_or_false(self):
        signal = self.observe(lambda s,d,i: d['/dev/dri/card0']['connectors'][0]['properties'].pop('HDR_OUTPUT_METADATA'))
        self.assertEqual(signal.properties['hdr_metadata_present'].state, 'unavailable')
        self.assertIsNone(signal.properties['hdr_metadata_present'].value)

    def test_invalid_property_stays_unknown_without_raw_data(self):
        for bad in (None, property_value(2, True, {'min': 8, 'max': 16}),
                    property_value(2, 32, {'min': 8, 'max': 16}), property_value(8, 12)):
            signal = self.observe(lambda s,d,i: d['/dev/dri/card0']['connectors'][0]['properties'].update({'max bpc': bad}))
            self.assertEqual(signal.properties['max_bpc'].state, 'invalid')
            self.assertIsNone(signal.properties['max_bpc'].value)

    def test_enum_must_match_once_and_have_printable_bounded_label(self):
        for spec in ([{'value': 0, 'name': 'Bad\nLabel'}], [],
                     [{'value':0,'name':'AUTO'}, {'value':0,'name':'RGB'}]):
            signal = self.observe(lambda s,d,i: d['/dev/dri/card0']['connectors'][0]['properties']['color format'].update(spec=spec))
            self.assertEqual(signal.properties['color_format'].state, 'invalid')


class SignalQueryTests(unittest.TestCase):
    @patch('beamfix.signal.shutil.which', return_value='/usr/bin/drm_info')
    def test_only_read_query_with_deadline_and_no_shell(self, which):
        with patch('beamfix.signal.subprocess.run', return_value=subprocess.CompletedProcess([],0,b'{}')) as run:
            self.assertEqual(query_signal(), ({}, None))
        run.assert_called_once_with(['/usr/bin/drm_info', '-j'], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)

    def test_missing_tool_does_not_spawn(self):
        with patch('beamfix.signal.shutil.which', return_value=None), patch('beamfix.signal.subprocess.run') as run:
            data, reason = query_signal()
        self.assertIsNone(data)
        self.assertIn('not installed', reason)
        run.assert_not_called()

    @patch('beamfix.signal.shutil.which', return_value='/usr/bin/drm_info')
    def test_invalid_duplicate_oversized_and_denied_output(self, which):
        for code, output in ((0,b'bad'), (0,b'[]'), (0,b'{"x":1,"x":2}'),
                             (0,b'\xff'), (0,b' '*(MAX_JSON_BYTES+1)), (1,b'PRIVATE_ERROR')):
            with patch('beamfix.signal.subprocess.run', return_value=subprocess.CompletedProcess([],code,output)):
                data, reason = query_signal()
                self.assertIsNone(data)
                self.assertIsNotNone(reason)
                self.assertNotIn('PRIVATE',reason)
        for error in (OSError(), subprocess.TimeoutExpired('drm_info',5)):
            with patch('beamfix.signal.subprocess.run', side_effect=error):
                self.assertIsNone(query_signal()[0])

    def test_sysfs_mapping_is_bracketed_and_changed_ids_invalidate(self):
        for changed in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                snap,data,_ = fixture()
                root=Path(directory)
                path=root/snap.connectors[0].name
                path.mkdir()
                for name,value in [('connector_id','51'),('status','connected'),('enabled','enabled')]:
                    (path/name).write_text(value)
                def query():
                    if changed:
                        (path/'connector_id').write_text('52')
                    return data,None
                with patch('beamfix.signal.query_signal',side_effect=query):
                    signal=add_signal_details(snap,drm_root=root).connectors[0].signal
                self.assertEqual(signal.state, 'inconsistent' if changed else 'observed')

    def test_non_linux_never_queries_drm(self):
        snap,_,_=fixture()
        snap.system='Darwin'
        with patch('beamfix.signal.query_signal') as query:
            signal=add_signal_details(snap).connectors[0].signal
        query.assert_not_called()
        self.assertEqual(signal.state,'unavailable')


class SignalReportTests(unittest.TestCase):
    def test_json_preserves_details_context_and_visual_uncertainty(self):
        snap,data,ids=fixture()
        apply_signal_data(snap,data,ids)
        with patch('beamfix.cli.collect',return_value=snap), contextlib.redirect_stdout(io.StringIO()) as stream:
            code=main(['doctor','--json','--visual-result','room_monitors_only','--connection','room'])
        report=json.loads(stream.getvalue())
        self.assertEqual(code,0)
        self.assertEqual(report['visual_confirmation'],'not_performed')
        self.assertEqual(report['user_context']['source'],'user_reported')
        self.assertEqual(report['user_context']['visual_result'],'room_monitors_only')
        self.assertEqual(len(report['snapshot']['connectors'][0]['signal']['listed_timings']),2)
        self.assertNotIn('PRIVATE',stream.getvalue())

    def test_optional_absence_is_explicit_without_changing_basic_exit_code(self):
        snap,_,_=fixture()
        with patch('beamfix.signal.query_signal',return_value=(None,'Optional tool unavailable.')):
            add_signal_details(snap)
        with patch('beamfix.cli.collect',return_value=snap), contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(['doctor','--json']),0)
        report=json.loads(stream.getvalue())
        self.assertEqual(report['snapshot']['connectors'][0]['signal']['state'],'unavailable')

    def test_human_report_is_wrapped_and_explains_limit(self):
        snap,data,ids=fixture()
        apply_signal_data(snap,data,ids)
        lines=[]
        render_doctor(snap,[],0,terminal=Terminal(write=lines.append,plain=True,width=60))
        text=' '.join('\n'.join(lines).split())
        self.assertIn('max_bpc [limit]: 12',text)
        self.assertIn('not the transmitted bit depth',text)
        self.assertNotIn('PRIVATE',text)
        self.assertTrue(all(len(line)<=60 for line in lines))
        self.assertIn('actual_bpc',text)


if __name__=='__main__':
    unittest.main()
