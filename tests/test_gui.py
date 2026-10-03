import http.client
import json
import threading
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from beamfix.gui import Application, Conflict, Server, demo_snapshot
from beamfix.fix_worker import FixResult


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(reader=demo_snapshot)

    def action(self, action, **kwargs):
        return self.app.action({'action': action, 'revision': self.app.revision, **kwargs})

    def start(self, symptom='no_signal', connection='direct'):
        self.action('start', symptom=symptom, connection=connection)
        self.action('target', target='card0-HDMI-A-1')

    def test_manual_success_requires_explicit_projector_observation(self):
        self.start()
        self.assertEqual(self.app.step.code, 'input')
        self.assertNotEqual(self.app.session.outcome, 'resolved')
        self.action('done')
        self.assertEqual(self.app.phase, 'observe')
        self.action('observe', observation='resolved')
        self.assertEqual(self.app.session.outcome, 'resolved')
        self.assertEqual(self.app.report()['visual_confirmation'], 'not_performed')

    def test_room_symptom_and_skips_never_suggest_mirroring_or_infer_success(self):
        self.start('room_monitors_only', 'room')
        self.assertEqual(self.app.step.code, 'room_input')
        while self.app.phase == 'step':
            self.assertNotEqual(self.app.step.code, 'mirror')
            self.action('skip')
        self.assertEqual(self.app.session.outcome, 'unresolved')
        self.assertTrue(all(not a.performed for a in self.app.session.attempts))

    def test_stale_action_is_rejected_without_mutation(self):
        self.start()
        with self.assertRaises(Conflict):
            self.app.action({'action': 'done', 'revision': 0})
        self.assertFalse(self.app.session.attempts)

    def test_unidentified_output_stays_unidentified(self):
        self.action('start', symptom='black', connection='unknown')
        self.action('target', target=None)
        self.assertIsNone(self.app.session.target)
        self.assertEqual(self.app.step.code, 'input')

    def test_internal_or_unknown_output_rejected(self):
        self.action('start', symptom='black', connection='unknown')
        for target in ('card0-eDP-1', 'HDMI;false'):
            with self.assertRaises(ValueError):
                self.action('target', target=target)

    def test_hotplug_requires_reselection_before_observation(self):
        self.start()
        new = demo_snapshot()
        new.connectors[1] = replace(new.connectors[1], name='card0-DP-1')
        self.app.reader = lambda: new
        self.action('done')
        self.assertEqual(self.app.phase, 'target')
        self.assertIsNone(self.app.session.target)
        self.action('target', target='card0-DP-1')
        self.assertEqual(self.app.phase, 'observe')
        self.assertIn('card0-DP-1', self.app.session.attempts[-1].after)

    def test_direct_test_requires_fresh_connection_description(self):
        self.start('room_monitors_only', 'room')
        while self.app.step.code != 'direct':
            self.action('skip')
        self.action('done')
        self.assertEqual(self.app.session.connection_path, 'unknown')
        with self.assertRaises(ValueError):
            self.action('observe', observation='black')
        self.action('observe', observation='black', connection='direct')
        self.assertEqual(self.app.session.initial_connection, 'room')
        self.assertEqual(self.app.session.connection_path, 'direct')

    def test_demo_never_prepares_or_applies_real_changes(self):
        self.app = Application(demo=True)
        self.start()
        self.action('skip')
        self.assertEqual(self.app.step.code, 'mode')
        with patch('beamfix.fix_backends.prepare_modes') as prepare:
            self.action('preview')
            self.assertFalse(prepare.called)
            with self.assertRaises(Conflict):
                self.action('apply')
        self.assertIn('Demonstration', self.app.notice)

    def test_unsupported_backend_keeps_manual_guidance(self):
        self.start()
        self.action('skip')
        self.action('preview')
        self.assertEqual(self.app.phase, 'step')
        self.assertIn('backend', self.app.notice)

    def test_read_failure_does_not_record_completed_step(self):
        self.start()
        self.app.reader = lambda: (_ for _ in ()).throw(OSError())
        with self.assertRaises(OSError):
            self.action('done')
        self.assertFalse(self.app.session.attempts)
        self.assertEqual(self.app.phase, 'step')

    def confirmation_thread(self, seconds=1, modes=True):
        result = []
        plan = SimpleNamespace(description='Simulated attempt', action='mode' if modes else 'activation')
        thread = threading.Thread(target=lambda: result.append(self.app.confirm(plan, 1, 1, seconds)))
        thread.start()
        deadline = time.monotonic()+1
        while self.app.phase != 'confirm' and thread.is_alive() and time.monotonic()<deadline:
            time.sleep(.005)
        return thread, result

    def test_keep_requires_current_trial_nonce_and_revision(self):
        thread, result = self.confirmation_thread()
        try:
            with self.assertRaises(Conflict):
                self.action('decision', nonce='old', decision='keep')
            self.action('decision', nonce=self.app.confirmation['nonce'], decision='keep')
        finally:
            thread.join(2)
        self.assertEqual(result, ['keep'])

    def test_timeout_and_browser_heartbeat_loss_request_undo(self):
        thread, result = self.confirmation_thread(.04)
        thread.join(1)
        self.assertEqual(result, ['undo'])
        self.app.last_seen = time.monotonic()-5
        thread, result = self.confirmation_thread()
        thread.join(1)
        self.assertEqual(result, ['undo'])

    def test_close_and_stop_during_confirmation_request_undo(self):
        for close in (True, False):
            self.app = Application(reader=demo_snapshot)
            thread, result = self.confirmation_thread()
            self.app.close() if close else self.action('stop')
            thread.join(1)
            self.assertEqual(result, ['undo'])

    def test_next_not_allowed_for_activation_and_old_confirmations_expire(self):
        thread, result = self.confirmation_thread(modes=False)
        try:
            nonce = self.app.confirmation['nonce']
            with self.assertRaises(ValueError):
                self.action('decision', nonce=nonce, decision='next')
            self.action('decision', nonce=nonce, decision='undo')
        finally:
            thread.join(1)
        thread, result = self.confirmation_thread()
        try:
            with self.assertRaises(Conflict):
                self.action('decision', nonce=nonce, decision='keep')
        finally:
            self.app.close()
            thread.join(1)

    def test_preview_needs_explicit_apply_and_result_is_preserved(self):
        self.start()
        self.action('skip')
        plan = SimpleNamespace(description='Simulated mode', action='mode')
        with patch('beamfix.fix_backends.prepare_modes', return_value=[plan]), \
             patch('beamfix.automatic.run_mode_sequence', return_value=FixResult('reverted', 'Original mode verified.', True)) as run:
            self.action('preview')
            self.assertFalse(run.called)
            self.action('apply')
            self.app.worker.join(1)
            self.assertTrue(run.called)
        self.assertEqual(self.app.phase, 'summary')
        self.assertEqual(self.app.session.outcome, 'not_confirmed')
        self.assertEqual(self.app.result.status, 'reverted')
        self.assertIn('Original mode verified', self.app.session.attempts[0].automatic_result if len(self.app.session.attempts)==1 else self.app.session.attempts[-1].automatic_result)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = Server(Application(demo=True))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()

    def tearDown(self):
        self.server.app.close()
        self.server.shutdown()
        self.thread.join(1)
        self.server.server_close()

    def request(self, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        default = {'X-BeamFix-Token': self.server.token}
        if data is not None:
            default['Content-Type'] = 'application/json'
        default.update(headers or {})
        connection.request('POST' if data is not None else 'GET', path,
                           body=json.dumps(data) if data is not None else None, headers=default)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_auth_host_and_origin_checks(self):
        for headers in ({'X-BeamFix-Token':''}, {'Host':'attacker.invalid'},
                        {'Origin':'https://attacker.invalid'}, {'X-BeamFix-Token':'wrong'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('/api/state',headers=headers)[0],403)
                self.assertEqual(self.request('/api/action',{},headers=headers)[0],403)
        self.assertEqual(self.request('/api/state')[0],200)

    def test_only_allowlisted_assets_are_served_without_auth(self):
        for path in ('/','/license','/notice','/app.js','/style.css','/no_signal.svg','/black.svg','/desktop.svg','/room_monitors_only.svg'):
            status,body,headers=self.request(path,headers={'X-BeamFix-Token':''})
            self.assertEqual(status,200)
            self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        for path in ('/../pyproject.toml','/beamfix/gui.py','/api/unknown','/.env'):
            self.assertEqual(self.request(path)[0],404)

    def test_http_guided_workflow_and_stale_requests(self):
        def action(action, **kwargs):
            status, body, _ = self.request('/api/action', {'action':action,'revision':self.server.app.revision,**kwargs})
            self.assertEqual(status,200,body)
            return json.loads(body)
        state=action('start',symptom='room_monitors_only',connection='room')
        self.assertEqual(state['phase'],'target')
        state=action('target',target='card0-HDMI-A-1')
        self.assertEqual(state['step']['code'],'room_input')
        self.assertEqual(self.request('/api/action',{'action':'done','revision':0})[0],409)
        action('done')
        state=action('observe',observation='resolved')
        self.assertEqual(state['session']['outcome'],'resolved')

    def test_wrong_content_type_and_body_rejected(self):
        self.assertEqual(self.request('/api/action',[],headers={})[0],400)
        self.assertEqual(self.request('/api/action',{},headers={'Content-Type':'text/plain'})[0],400)
        self.assertEqual(self.request('/api/action',{'large':'x'*5000})[0],400)


if __name__ == '__main__':
    unittest.main()
