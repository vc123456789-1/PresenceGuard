import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import main


class RealLockActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = main.App(self.root, Path(self.temp.name))
        self.app.model.touch()

    def tearDown(self):
        self.root.destroy()
        self.app = self.root = None
        gc.collect()
        self.temp.cleanup()

    def activate(self, answers=(True,), authorized=True):
        with patch.object(self.app, 'authorize', return_value=authorized), \
             patch('main.messagebox.showinfo'), patch('main.messagebox.showerror'), \
             patch('main.messagebox.askyesno', side_effect=answers):
            self.app.arm()

    def test_arm_does_not_require_pin(self):
        with patch.object(self.app, 'authorize', return_value=False) as authorize, \
             patch('main.messagebox.askyesno', return_value=True):
            self.app.arm()
        authorize.assert_not_called()
        self.assertTrue(self.app.policy.armed)

    def test_can_arm_without_manual_camera_test(self):
        self.app.policy.checks = 0
        self.activate()
        self.assertTrue(self.app.policy.armed)
        self.assertTrue(self.app.policy.running)

    def test_busy_camera_shows_short_message_without_cancelling(self):
        from unittest.mock import Mock
        cancel = Mock()
        self.app.job = {'cancel': cancel}
        with patch('main.messagebox.showinfo') as show, patch('main.messagebox.askyesno') as confirm:
            self.app.arm()
        show.assert_called_once_with('Real lock', 'Wait for the camera check to finish.', parent=self.root)
        confirm.assert_not_called()
        cancel.set.assert_not_called()
        self.assertFalse(self.app.policy.armed)

    def test_cannot_arm_without_registered_face(self):
        self.app.model.unlink()
        self.activate()
        self.assertFalse(self.app.policy.armed)

    def test_can_arm_when_photo_challenge_is_disabled(self):
        self.app.settings['anti_photo'] = False
        self.activate()
        self.assertTrue(self.app.policy.armed)

    def test_cannot_arm_if_real_lock_not_confirmed(self):
        self.activate((False,))
        self.assertFalse(self.app.policy.armed)
        self.assertFalse(self.app.policy.running)

    def test_arm_with_confirmations_never_locks_immediately(self):
        self.app.policy.start()
        self.app.policy.grace_until = 1
        with patch('main.lock_windows') as lock:
            self.activate()
            self.assertTrue(self.app.policy.armed)
            self.assertIsNone(self.app.policy.grace_until)
            lock.assert_not_called()

    def test_cancelled_manual_check_resets_positive_checks(self):
        self.app.policy.checks = 1
        self.app.accept_result(self.app.epoch, 'test', None, 'Cancelled')
        self.assertEqual(self.app.policy.checks, 0)

    def test_new_instance_starts_in_test_mode_after_activation(self):
        self.activate()
        other_root = tk.Tk()
        other_root.withdraw()
        try:
            other = main.App(other_root, Path(self.temp.name))
            self.assertFalse(other.policy.armed)
            other = None
        finally:
            other_root.destroy()
            gc.collect()

if __name__ == '__main__':
    unittest.main()
