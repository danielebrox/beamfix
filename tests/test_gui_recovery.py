"""GUI state transitions connected to the real detached worker with fake displays."""
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_automatic as recovery
from beamfix.gui import Application


class GUIWorkerTests(unittest.TestCase):
    def setUp(self):
        recovery.ProcessRecoveryTests.setUp(self)

    reap = recovery.ProcessRecoveryTests.reap

    def test_gui_keep_stop_and_browser_loss_reach_real_worker(self):
        original = subprocess.Popen
        for decision in ('keep', 'undo', 'browser_lost'):
            with self.subTest(decision=decision):
                self.state.write_text(json.dumps(self.plan.before))
                app = Application(reader=lambda: recovery.fixture()[0])
                def action(name, **kwargs):
                    return app.action({'action': name, 'revision': app.revision, **kwargs})
                def spawn(arguments, **kwargs):
                    process = original([sys.executable, '-c', recovery.HARNESS, arguments[-1]],
                                       **{**kwargs, 'env': self.environment})
                    self.processes.append(process)
                    return process
                with patch('beamfix.fix_backends.KDEBackend.prepare', return_value=self.plan), \
                     patch('beamfix.automatic.subprocess.Popen', side_effect=spawn):
                    action('start', symptom='black', connection='direct')
                    action('target', target=self.plan.connector)
                    action('preview')
                    self.assertEqual(app.phase, 'preview')
                    self.assertEqual(json.loads(self.state.read_text()), self.plan.before)
                    action('apply')
                    deadline = time.monotonic()+3
                    while app.state()['phase'] != 'confirm' and time.monotonic()<deadline:
                        time.sleep(.01)
                    self.assertEqual(app.phase, 'confirm')
                    self.assertEqual(json.loads(self.state.read_text()), self.plan.expected)
                    if decision == 'browser_lost':
                        with app.lock:
                            app.last_seen = time.monotonic()-5
                    elif decision == 'undo':
                        action('stop')
                    else:
                        action('decision', nonce=app.confirmation['nonce'], decision='keep')
                    app.worker.join(4)
                    self.assertFalse(app.worker.is_alive())
                self.assertEqual(app.result.status, 'kept' if decision=='keep' else 'reverted')
                self.assertEqual(json.loads(self.state.read_text()), self.plan.expected if decision=='keep' else self.plan.before)
                self.assertEqual(app.session.outcome, 'resolved' if decision=='keep' else 'not_confirmed')
