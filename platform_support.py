"""Small Windows integrations. UI work stays on the Tk thread."""
import ctypes
import os
import threading
from pathlib import Path
from guard import awake_seconds


def power_request(active):
    if os.name != 'nt':
        return False
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED. No display request is made.
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if active else 0x80000000))


class KeepAwake:
    def __init__(self, request=power_request):
        self.request = request
        self.until = None

    def start(self, value, now, unit='minutes'):
        duration = awake_seconds(value, unit)
        if not self.request(True):
            raise RuntimeError('Windows could not keep the PC awake.')
        self.until = now + duration

    def stop(self):
        if self.until is not None:
            self.request(False)
            self.until = None

    def tick(self, now):
        if self.until is not None and now >= self.until:
            self.stop()


def request_open(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def consume_open(path):
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return False


class Tray:
    def __init__(self, enqueue):
        import pystray
        from PIL import Image, ImageDraw
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), fill='#285785')
        draw.ellipse((20, 17, 44, 41), fill='white')
        draw.arc((14, 31, 50, 60), 180, 360, fill='white', width=5)
        def item(label, action, default=False):
            return pystray.MenuItem(label, lambda icon, entry: enqueue(action), default=default)
        menu = pystray.Menu(item('Open PresenceGuard', 'open', True),
                            item('Status', 'status'), item('Settings', 'settings'),
                            item('Pause protection', 'pause'), item('Resume protection', 'resume'),
                            item('Exit', 'exit'))
        if os.name == 'nt':
            from pystray import _win32
            class CheckedIcon(pystray.Icon):
                def _message(self, code, flags, **kwargs):
                    data = _win32.win32.NOTIFYICONDATAW(
                        cbSize=ctypes.sizeof(_win32.win32.NOTIFYICONDATAW),
                        hWnd=self._hwnd, hID=id(self), uFlags=flags, **kwargs)
                    result = _win32.win32.Shell_NotifyIcon(code, data)
                    if code == _win32.win32.NIM_ADD and not result:
                        raise RuntimeError('Windows could not create the tray icon.')
            icon_type = CheckedIcon
        else:
            icon_type = pystray.Icon
        self.icon = icon_type('PresenceGuard', image, 'PresenceGuard', menu)

    def start(self):
        ready = threading.Event()
        errors = []
        def setup(icon):
            try:
                icon.visible = True
            except Exception as exc:
                errors.append(exc)
            finally:
                ready.set()
        self.icon.run_detached(setup=setup)
        if not ready.wait(3) or errors or not self.icon.visible:
            try:
                self.icon.stop()
            except Exception:
                pass
            raise RuntimeError('Windows could not create the tray icon.')

    def notify(self, message):
        self.icon.notify(message, 'PresenceGuard')

    def stop(self):
        self.icon.stop()
