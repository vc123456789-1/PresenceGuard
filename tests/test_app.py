import importlib.util
import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

if importlib.util.find_spec('main'):
    import main
else:
    main = None


class AppTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(main, 'Falta implementar main.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = main.App(self.root, Path(self.tmp.name))

    def tearDown(self):
        if hasattr(self, 'root'):
            self.root.destroy()
            self.app = None
            self.root = None
            gc.collect()
            self.tmp.cleanup()

    def test_window_defaults_are_safe(self):
        self.assertFalse(self.app.policy.armed)
        self.assertFalse(self.app.policy.running)
        self.assertEqual(self.app.settings['interval_seconds'], 180)
        self.assertFalse(self.app.pin.exists())

    def test_no_pin_means_no_start_when_setup_cancelled(self):
        with patch.object(self.app, 'authorize', return_value=False):
            self.app.start_protection()
        self.assertFalse(self.app.policy.running)

    def test_no_pin_means_no_pause(self):
        with patch.object(self.app, 'authorize', return_value=False):
            self.app.pause_protection()
        self.assertEqual(self.app.policy.pause_until, 0)

    def test_late_worker_result_ignored(self):
        self.app.policy.start()
        old = self.app.epoch
        self.app.invalidate()
        self.app.accept_result(old, 'auto', False, 'resultado viejo')
        self.assertEqual(self.app.policy.failures, 0)

    def test_manual_failure_never_requests_windows_lock(self):
        self.app.policy.start()
        self.app.policy.armed = True
        with patch('main.lock_windows') as lock:
            for _ in range(3):
                self.app.accept_result(self.app.epoch, 'test', False, 'simulado')
            self.app.enforce(10**20)
            lock.assert_not_called()

    def test_simulation_does_not_call_windows_lock(self):
        self.app.policy.start()
        self.app.policy.result(False, 0)
        self.app.policy.result(False, 1)
        with patch('main.lock_windows') as lock:
            self.app.enforce(16)
            lock.assert_not_called()
        self.assertIn('TEST MODE', self.app.status.get())

    def test_stopped_policy_never_calls_windows_lock(self):
        self.app.policy.start()
        self.app.policy.armed = True
        self.app.policy.result(False, 0)
        self.app.policy.result(False, 1)
        self.app.policy.stop()
        with patch('main.lock_windows') as lock:
            self.app.enforce(50)
            lock.assert_not_called()

    def test_manual_test_cancels_old_grace_after_pin(self):
        self.app.policy.start()
        self.app.policy.result(False, 0)
        self.app.policy.result(False, 1)
        with patch.object(self.app, 'authorize', return_value=True), patch.object(self.app, 'launch_scan'):
            self.app.manual_test()
        self.assertIsNone(self.app.policy.grace_until)

    def test_preview_binary_ppm_is_accepted_by_tk(self):
        import cv2
        import numpy as np
        ok, image = cv2.imencode('.ppm', np.zeros((30, 40, 3), np.uint8))
        self.assertTrue(ok)
        picture = tk.PhotoImage(data=image.tobytes(), master=self.root)
        self.assertEqual((picture.width(), picture.height()), (40, 30))

    def test_armed_policy_requests_lock_only_after_grace(self):
        self.app.policy.start()
        self.app.policy.armed = True
        self.app.policy.result(False, 0)
        self.app.policy.result(False, 1)
        with patch('main.lock_windows') as lock:
            self.app.enforce(15)
            lock.assert_not_called()
            self.app.enforce(16)
            lock.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
