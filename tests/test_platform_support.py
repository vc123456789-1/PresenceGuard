import unittest
import os
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import platform_support as platform

class PlatformTests(unittest.TestCase):
    def test_awake_expires_and_releases_on_same_thread(self):
        request = Mock(return_value=True)
        awake = platform.KeepAwake(request)
        awake.start(2, 100)
        self.assertEqual(request.call_args_list[0].args, (True,))
        awake.tick(219)
        self.assertEqual(request.call_count, 1)
        awake.tick(220)
        self.assertEqual(request.call_args_list[-1].args, (False,))
        self.assertIsNone(awake.until)

    def test_awake_accepts_seconds_minutes_and_hours(self):
        for value, unit, duration in ((45, 'seconds', 45), (2, 'minutes', 120), (1.5, 'hours', 5400)):
            with self.subTest(unit=unit):
                request = Mock(return_value=True)
                awake = platform.KeepAwake(request)
                awake.start(value, 100, unit)
                self.assertEqual(awake.until, 100 + duration)
                awake.tick(100 + duration)
                self.assertIsNone(awake.until)
                self.assertEqual(request.call_args_list[-1].args, (False,))

    def test_awake_stop_and_change_duration(self):
        request = Mock(return_value=True)
        awake = platform.KeepAwake(request)
        awake.start(30, 100, 'seconds')
        awake.start(2, 110, 'minutes')
        self.assertEqual(awake.until, 230)
        awake.stop()
        self.assertIsNone(awake.until)
        self.assertEqual(request.call_args_list[-1].args, (False,))
        awake.tick(1000)
        self.assertEqual(request.call_count, 3)

    def test_invalid_awake_values_do_not_request_power(self):
        for value, unit in ((0, 'seconds'), ('nan', 'minutes'), (-1, 'hours'), (25, 'hours'), (30, 'days')):
            with self.subTest(value=value, unit=unit):
                request = Mock(return_value=True)
                awake = platform.KeepAwake(request)
                with self.assertRaises(ValueError):
                    awake.start(value, 0, unit)
                request.assert_not_called()
                self.assertIsNone(awake.until)

    def test_failed_awake_request_does_not_stay_active(self):
        awake = platform.KeepAwake(Mock(return_value=False))
        with self.assertRaises(RuntimeError):
            awake.start(1, 0)
        self.assertIsNone(awake.until)

    @unittest.skipUnless(os.name == 'nt', 'Windows tray API')
    def test_tray_requires_add_success_but_tolerates_modify_before_add(self):
        from pystray._win32 import win32
        tray = platform.Tray(lambda action: None)
        tray.icon._hwnd = 1
        with patch.object(win32, 'Shell_NotifyIcon', return_value=0):
            tray.icon._message(win32.NIM_MODIFY, 0)
            with self.assertRaises(RuntimeError):
                tray.icon._message(win32.NIM_ADD, 0)

    def test_signal_is_consumed_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'show.request'
            platform.request_open(path)
            self.assertTrue(platform.consume_open(path))
            self.assertFalse(platform.consume_open(path))

if __name__ == '__main__': unittest.main()
