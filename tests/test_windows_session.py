import os
import queue
import unittest

from windows_session import SessionMonitor


@unittest.skipUnless(os.name == 'nt', 'Windows session notifications')
class SessionMonitorTests(unittest.TestCase):
    def test_real_registration_and_simulated_messages(self):
        import ctypes
        from ctypes import wintypes
        events = queue.Queue()
        monitor = SessionMonitor(events)
        self.assertTrue(monitor.start(), monitor.error)
        try:
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.PostMessageW.restype = wintypes.BOOL
            self.assertTrue(user.PostMessageW(monitor.hwnd, 0x02B1, 7, 0))
            self.assertFalse(events.get(timeout=2))
            self.assertTrue(user.PostMessageW(monitor.hwnd, 0x02B1, 8, 0))
            self.assertTrue(events.get(timeout=2))
        finally:
            monitor.stop()
        self.assertFalse(monitor.is_alive())


if __name__ == '__main__':
    unittest.main()
