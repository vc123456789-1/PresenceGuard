import gc
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import main
from guard import load_settings
from platform_support import KeepAwake

class AwakeUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = main.App(self.root, Path(self.temp.name))
        self.request = Mock(return_value=True)
        self.app.awake = KeepAwake(self.request)
    def tearDown(self):
        self.app.awake.stop()
        self.root.destroy()
        self.app = self.root = None
        gc.collect()
        self.temp.cleanup()
    def test_start_stop_and_restart_use_the_selected_units(self):
        self.app.awake_value.set('90')
        self.app.awake_unit.set('seconds')
        with patch('main.time.monotonic', return_value=100):
            self.app.start_keep_awake()
        self.assertEqual(self.app.awake.until, 190)
        self.assertEqual(load_settings(Path(self.temp.name)/'settings.json')['awake_unit'], 'seconds')
        self.app.stop_keep_awake()
        self.assertIsNone(self.app.awake.until)
        self.assertFalse(self.request.call_args.args[0])
        self.app.awake_value.set('2')
        self.app.awake_unit.set('hours')
        with patch('main.time.monotonic', return_value=200):
            self.app.start_keep_awake()
        self.assertEqual(self.app.awake.until, 7400)
    def test_valid_duration_is_saved_without_starting(self):
        self.app.awake_value.set('12')
        self.app.awake_unit.set('minutes')
        self.app.save_awake_duration()
        saved = load_settings(Path(self.temp.name)/'settings.json')
        self.assertEqual((saved['awake_duration'], saved['awake_unit']), (12, 'minutes'))
        self.assertIsNone(self.app.awake.until)
    def test_hide_saves_the_last_valid_duration_immediately(self):
        self.app.tray = Mock()
        self.app.awake_value.set('42')
        self.app.awake_unit.set('seconds')
        self.app.hide_window()
        saved = load_settings(Path(self.temp.name) / 'settings.json')
        self.assertEqual((saved['awake_duration'], saved['awake_unit']), (42, 'seconds'))

    def test_remaining_shows_minutes_and_seconds_and_expiry(self):
        self.app.awake.until = 190
        with patch('main.time.monotonic', return_value=108):
            self.app.refresh()
        self.assertIn('1m 22s', self.app.timer.get())
        self.app.awake.tick(190)
        with patch('main.time.monotonic', return_value=190):
            self.app.refresh()
        self.assertIn('0s', self.app.timer.get())
    def test_invalid_duration_does_not_request_power(self):
        self.app.awake_value.set('0')
        with patch('main.messagebox.showerror'):
            self.app.start_keep_awake()
        self.request.assert_not_called()

if __name__ == '__main__': unittest.main()
