"""Receive Windows session changes on a private message thread.

The queue receives False for lock and True for unlock. Consumers must update
their UI on the UI thread. No operating-system lock request is made here.
"""
import ctypes
from ctypes import wintypes
import os
import threading
import uuid


class SessionMonitor:
    def __init__(self, events):
        self.events = events
        self.hwnd = None
        self.error = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._thread = None

    def start(self):
        if os.name != 'nt':
            self.error = 'Session notifications require Windows.'
            return False
        if self._thread is not None:
            return self.hwnd is not None
        self._thread = threading.Thread(target=self._run, name='PresenceGuard-session', daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            self._stopped.set()
            self.error = 'Timed out registering session notifications.'
            return False
        return self.hwnd is not None

    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    def stop(self):
        self._stopped.set()
        hwnd = self.hwnd
        if hwnd is not None:
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.PostMessageW.restype = wintypes.BOOL
            user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self):
        user = kernel = wts = None
        name = 'PresenceGuardSession_' + uuid.uuid4().hex
        instance = None
        registered = False
        session_registered = False
        try:
            user = ctypes.WinDLL('user32', use_last_error=True)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            wts = ctypes.WinDLL('wtsapi32', use_last_error=True)
            result_type = ctypes.c_ssize_t
            callback_type = ctypes.WINFUNCTYPE(result_type, wintypes.HWND, wintypes.UINT,
                                               wintypes.WPARAM, wintypes.LPARAM)

            class WNDCLASS(ctypes.Structure):
                _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', callback_type),
                            ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                            ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                            ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                            ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]

            user.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.DefWindowProcW.restype = result_type
            user.PostQuitMessage.argtypes = [ctypes.c_int]

            @callback_type
            def window_proc(hwnd, message, wparam, lparam):
                nonlocal session_registered
                if message == 0x02B1:  # WM_WTSSESSION_CHANGE
                    if wparam == 7:
                        self.events.put(False)
                    elif wparam == 8:
                        self.events.put(True)
                    return 0
                if message == 0x0002:  # WM_DESTROY
                    if session_registered:
                        wts.WTSUnRegisterSessionNotification(hwnd)
                        session_registered = False
                    user.PostQuitMessage(0)
                    return 0
                return user.DefWindowProcW(hwnd, message, wparam, lparam)

            kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel.GetModuleHandleW.restype = wintypes.HMODULE
            instance = kernel.GetModuleHandleW(None)
            user.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
            user.RegisterClassW.restype = wintypes.ATOM
            wc = WNDCLASS(0, window_proc, 0, 0, instance, None, None, None, None, name)
            if not user.RegisterClassW(ctypes.byref(wc)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                            wintypes.HINSTANCE, wintypes.LPVOID]
            user.CreateWindowExW.restype = wintypes.HWND
            user.DestroyWindow.argtypes = [wintypes.HWND]
            user.DestroyWindow.restype = wintypes.BOOL
            hwnd = user.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0,
                                        wintypes.HWND(-3), None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            wts.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
            wts.WTSRegisterSessionNotification.restype = wintypes.BOOL
            wts.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
            wts.WTSUnRegisterSessionNotification.restype = wintypes.BOOL
            if not wts.WTSRegisterSessionNotification(hwnd, 0):
                user.DestroyWindow(hwnd)
                raise ctypes.WinError(ctypes.get_last_error())
            session_registered = True
            self.hwnd = hwnd
            self._ready.set()
            if self._stopped.is_set():
                user.DestroyWindow(hwnd)
            user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user.GetMessageW.restype = ctypes.c_int
            user.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user.DispatchMessageW.restype = result_type
            message = wintypes.MSG()
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.hwnd = None
            self._ready.set()
            if registered:
                user.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
                user.UnregisterClassW(name, instance)
