import tempfile
import gc
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import main

class NewAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = main.App(self.root, Path(self.temp.name))
    def tearDown(self):
        self.root.destroy()
        self.app = None
        self.root = None
        gc.collect()
        self.temp.cleanup()
    def test_close_to_tray_preserves_running_policy(self):
        self.app.tray = Mock()
        self.app.policy.start()
        self.app.hide_window()
        self.assertTrue(self.app.policy.running)
        self.assertEqual(self.root.state(), 'withdrawn')
    def test_close_without_tray_keeps_window_visible(self):
        self.app.tray = None
        with patch('main.messagebox.showwarning'):
            self.app.hide_window()
        self.assertNotEqual(self.root.state(), 'withdrawn')
    def test_camera_error_never_counts_as_identity_failure(self):
        self.app.policy.start()
        self.app.accept_result(self.app.epoch, 'auto', None, 'Camera unavailable')
        self.assertEqual(self.app.policy.failures, 0)
    def test_locked_session_cancels_active_camera_and_grace(self):
        self.app.policy.start()
        self.app.policy.grace_until = 1
        cancel = Mock()
        self.app.job = {'cancel': cancel}
        self.app.on_session_change(False, 10)
        cancel.set.assert_called_once()
        self.assertIsNone(self.app.policy.grace_until)
    def test_unlock_reschedules_check_and_ignores_old_camera_result(self):
        self.app.policy.start()
        token = self.app.epoch
        self.app.job = {'cancel': Mock()}
        self.app.on_session_change(False, 10)
        self.app.accept_result(token, 'auto', False, 'Old result')
        self.assertEqual(self.app.policy.failures, 0)
        self.app.on_session_change(True, 20)
        self.assertEqual(self.app.next_check, 20 + self.app.settings['interval_seconds'])
        self.assertEqual(self.app.camera_state, 'Ready')
    def test_camera_is_not_started_while_locked(self):
        self.app.policy.start()
        self.app.next_check = 0
        with patch('main.session_unlocked', return_value=False), patch.object(self.app, 'launch_scan') as scan:
            self.app.tick()
        scan.assert_not_called()
    def test_real_lock_unavailable_without_validation(self):
        self.app.policy.checks = 3
        with patch.object(self.app, 'authorize', return_value=True), patch('main.messagebox.showinfo'):
            self.app.arm()
        self.assertFalse(self.app.policy.armed)

    def test_awake_does_not_suppress_lock(self):
        self.app.policy.start()
        self.app.policy.armed = True
        self.app.awake.until = 1000
        self.app.policy.result(False, 0)
        self.app.policy.result(False, 1)
        with patch('main.lock_windows') as lock:
            self.app.enforce(16)
        lock.assert_called_once()

    def test_pause_when_protection_is_off_does_not_report_paused(self):
        with patch.object(self.app, 'authorize', return_value=True), \
                patch('main.simpledialog.askinteger', return_value=5):
            self.app.pause_protection()
        self.assertEqual(self.app.policy.pause_until, 0)
        self.assertNotIn('paused', self.app.status.get().lower())

    def test_resume_when_protection_is_off_does_not_report_resumed(self):
        with patch.object(self.app, 'authorize', return_value=True):
            self.app.resume_protection()
        self.assertFalse(self.app.policy.running)
        self.assertNotIn('resumed', self.app.status.get().lower())

    def test_setup_register_cancel_ends_setup(self):
        self.app.setup_active = True
        with patch('main.messagebox.askyesno', return_value=True), patch.object(self.app, 'enroll'):
            self.app.setup_register()
        self.assertFalse(self.app.setup_active)

    def test_setup_test_cancel_ends_setup(self):
        self.app.setup_active = True
        with patch('main.messagebox.askyesno', return_value=True), patch.object(self.app, 'manual_test'):
            self.app.setup_test()
        self.assertFalse(self.app.setup_active)

    def test_tray_exit_stops_tick_after_window_is_destroyed(self):
        self.app.messages.put(('tray', 'exit'))
        with patch('main.session_unlocked', return_value=True), \
                patch.object(self.app, 'show_window'), patch.object(self.app, 'close_app'), \
                patch.object(self.root, 'winfo_exists', return_value=False), \
                patch.object(self.app, 'refresh') as refresh, patch.object(self.root, 'after') as after:
            self.app.tick()
        refresh.assert_not_called()
        after.assert_not_called()
