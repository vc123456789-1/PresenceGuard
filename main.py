"""PresenceGuard: local Windows presence checks, starting in test mode."""
import ctypes
import math
from ctypes import wintypes
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from guard import Policy, PinGate, load_settings, write_json, seconds, awake_seconds
from vision import run_camera
from platform_support import KeepAwake, Tray, request_open, consume_open
from windows_session import SessionMonitor

DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PresenceGuardV1'


def startup_path():
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'Microsoft/Windows/Start Menu/Programs/Startup/PresenceGuard.lnk'


def configure_startup(enabled):
    if os.name != 'nt':
        raise RuntimeError('Startup is available on Windows only.')
    path = startup_path()
    legacy = path.with_name('PresenceGuard v1.lnk')
    if enabled:
        if not getattr(sys, 'frozen', False):
            raise RuntimeError('Install PresenceGuard before enabling startup.')
        exe = Path(sys.executable).resolve()
        installed = (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Programs' / 'PresenceGuard' / 'PresenceGuard.exe').resolve()
        if os.path.normcase(str(exe)) != os.path.normcase(str(installed)):
            raise RuntimeError('Startup is available only for the installed app.')
        path.parent.mkdir(parents=True, exist_ok=True)
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        command = ("$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut(" + quote(path) + "); "
                   "$s.TargetPath=" + quote(exe) + "; $s.Arguments='--startup'; "
                   "$s.WorkingDirectory=" + quote(exe.parent) + "; $s.Save()")
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                       check=True, timeout=20, capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not path.is_file():
            raise RuntimeError('Could not create the startup shortcut.')
    elif path.exists():
        path.unlink()
    if legacy.exists():
        legacy.unlink()


def session_unlocked():
    if os.name != 'nt':
        return True
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    desktop = user.OpenInputDesktop(0, False, 1)
    if not desktop:
        return False
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        return bool(user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))) and name.value.casefold() == 'default'
    finally:
        user.CloseDesktop(desktop)


def lock_windows():
    if os.name != 'nt' or not ctypes.windll.user32.LockWorkStation():
        raise RuntimeError('Windows did not accept the lock request.')


class App:
    def __init__(self, root, data_dir=DATA):
        self.root, self.data = root, Path(data_dir)
        self.settings = load_settings(self.data / 'settings.json')
        self.pin = PinGate(self.data / 'pin.json')
        self.model = self.data / 'face.dat'
        self.policy = Policy()
        self.awake = KeepAwake()
        self.epoch, self.job = 0, None
        self.messages = queue.Queue()
        self.session_events = queue.Queue()
        self.session_monitor = SessionMonitor(self.session_events)
        self.next_check = time.monotonic() + self.settings['interval_seconds']
        self.preview = self.preview_image = None
        self.tray = None
        self.tray_notice = False
        self.setup_active = False
        self.session_is_unlocked = True
        self.last_check = 'Never'
        self.camera_state = 'Ready'
        self.status = tk.StringVar(value='Test mode. Set up PresenceGuard to begin.')
        self.summary, self.timer = tk.StringVar(), tk.StringVar()
        self.awake_value = tk.StringVar(value='%g' % self.settings['awake_duration'])
        self.awake_unit = tk.StringVar(value=self.settings['awake_unit'])
        self._awake_save_job = None
        root.title('PresenceGuard')
        root.option_add('*Font', '{Segoe UI} 9')
        style = ttk.Style(root)
        style.configure('.', font=('Segoe UI', 9))
        root.geometry('450x380')
        root.minsize(440, 370)
        frame = ttk.Frame(root, padding=10)
        frame.pack(fill='both', expand=True)

        general = ttk.LabelFrame(frame, text='General', padding=8)
        general.pack(fill='x', pady=(0, 6))
        ttk.Label(general, textvariable=self.summary, justify='left').grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Button(general, text='Start', command=self.start_protection).grid(row=1, column=0, sticky='w', pady=(6, 0))
        ttk.Button(general, text='Stop', command=self.stop_protection).grid(row=1, column=1, sticky='w', padx=5, pady=(6, 0))
        ttk.Button(general, text='Enable real lock', command=self.arm).grid(row=1, column=2, sticky='w', padx=5, pady=(6, 0))

        settings = ttk.LabelFrame(frame, text='Settings', padding=8)
        settings.pack(fill='x', pady=(0, 6))
        for col, (label, command) in enumerate((('Settings', self.open_settings), ('Register face', self.enroll),
                                                 ('Test camera', self.manual_test), ('Change PIN', self.change_pin))):
            ttk.Button(settings, text=label, command=command).grid(row=0, column=col, padx=(0, 5))

        awake = ttk.LabelFrame(frame, text='Keep PC awake', padding=8)
        awake.pack(fill='x')
        ttk.Label(awake, text='Duration:').grid(row=0, column=0, sticky='w')
        duration_entry = ttk.Entry(awake, textvariable=self.awake_value, width=8)
        duration_entry.grid(row=0, column=1, sticky='w', padx=5)
        unit_box = ttk.Combobox(awake, textvariable=self.awake_unit, values=('seconds', 'minutes', 'hours'), state='readonly', width=9)
        unit_box.grid(row=0, column=2, sticky='w')
        ttk.Button(awake, text='Start', command=self.start_keep_awake).grid(row=1, column=0, sticky='w', pady=(6, 0))
        ttk.Button(awake, text='Stop', command=self.stop_keep_awake).grid(row=1, column=1, columnspan=2, sticky='w', padx=5, pady=(6, 0))
        ttk.Label(awake, textvariable=self.timer).grid(row=2, column=0, columnspan=3, sticky='w', pady=(6, 0))
        ttk.Label(awake, text='Prevents sleep while background tasks run. Windows can still lock.',
                  wraplength=405).grid(row=3, column=0, columnspan=3, sticky='w', pady=(4, 0))
        self.awake_value.trace_add('write', self.schedule_awake_save)
        self.awake_unit.trace_add('write', self.schedule_awake_save)
        ttk.Label(frame, textvariable=self.status, wraplength=420).pack(anchor='w', pady=(6, 0))
        self.refresh()
        root.protocol('WM_DELETE_WINDOW', self.hide_window)
        root.after(150, self.tick)

    def start_tray(self):
        try:
            tray = Tray(lambda action: self.messages.put(('tray', action)))
            tray.start()
            self.tray = tray
        except Exception:
            self.tray = None
            self.log('Tray icon unavailable. Keep this window open.')

    def hide_window(self):
        self.flush_awake_duration()
        if not self.tray:
            self.root.deiconify()
            messagebox.showwarning('PresenceGuard', 'The tray icon is unavailable. The window will remain open.', parent=self.root)
            return
        self.root.withdraw()
        if not self.tray_notice:
            self.tray_notice = True
            try:
                self.tray.notify('PresenceGuard is still running in the notification area.')
            except Exception:
                pass

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def refresh(self):
        now = time.monotonic()
        state = 'Paused' if self.policy.paused(now) else ('On' if self.policy.running else 'Off')
        mode = 'Real lock' if self.policy.armed else 'Test mode'
        next_text = '%d s' % max(0, self.next_check-now) if self.policy.running and self.session_is_unlocked else '—'
        self.summary.set('Protection: %s (%s)\nCheck every: %g s    Last check: %s\nNext check: %s    Camera: %s' %
                         (state, mode, self.settings['interval_seconds'], self.last_check, next_text, self.camera_state))
        remaining = max(0, math.ceil(self.awake.until - now)) if self.awake.until is not None else 0
        hours, rem = divmod(remaining, 3600)
        minutes, seconds_left = divmod(rem, 60)
        if hours:
            text = '%dh %02dm %02ds' % (hours, minutes, seconds_left)
        elif minutes:
            text = '%dm %02ds' % (minutes, seconds_left)
        else:
            text = '%ds' % seconds_left
        self.timer.set('Remaining: ' + text)

    def log(self, text):
        self.status.set(text)
        try:
            self.data.mkdir(parents=True, exist_ok=True)
            path = self.data / 'events.log'
            if path.exists() and path.stat().st_size > 256_000:
                path.replace(self.data / 'events.previous.log')
            with path.open('a', encoding='utf-8') as handle:
                handle.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
        except OSError:
            self.status.set(text + ' History could not be saved.')

    def boot(self):
        if not self.session_monitor.start():
            self.log('Session notifications unavailable. Checking session state instead.')
        self.start_tray()
        if not self.pin.exists():
            self.setup()
        elif self.model.exists():
            self.policy.start()
            self.log('Test mode started. Real lock is off.')

    def setup(self):
        if not self.pin.exists() and not self.authorize():
            return
        if messagebox.askyesno('Setup', 'Choose a camera, register your face, then test it. Continue?', parent=self.root):
            self.setup_active = True
            self.open_settings()

    def ask_new_pin(self):
        value = simpledialog.askstring('Create PIN', 'Choose 6 to 12 digits. This is not your Windows PIN.', show='*', parent=self.root)
        if value is None:
            return None
        repeated = simpledialog.askstring('Confirm PIN', 'Enter the PIN again:', show='*', parent=self.root)
        if repeated != value:
            messagebox.showerror('PIN', 'PINs do not match.', parent=self.root)
            return None
        return value

    def authorize(self):
        try:
            if not self.pin.exists():
                value = self.ask_new_pin()
                if value is None:
                    return False
                self.pin.create(value)
                self.log('PIN created.')
                return True
            value = simpledialog.askstring('PresenceGuard', 'Enter your PIN:', show='*', parent=self.root)
            if value is None:
                return False
            if self.pin.check(value):
                return True
            messagebox.showerror('PIN', 'Incorrect PIN or waiting period active.', parent=self.root)
        except (OSError, ValueError) as exc:
            messagebox.showerror('PIN', str(exc), parent=self.root)
        return False

    def invalidate(self):
        self.epoch += 1
        if self.job:
            self.job['cancel'].set()
        self.policy.clear()

    def start_protection(self):
        if not self.authorize():
            return
        if not self.model.is_file():
            messagebox.showinfo('Register face', 'Register your face first.', parent=self.root)
            return
        self.policy.start()
        self.policy.pause_until = 0
        self.next_check = time.monotonic() + self.settings['interval_seconds']
        self.log('Protection enabled in ' + ('real lock mode.' if self.policy.armed else 'test mode.'))

    def pause_protection(self):
        if not self.policy.running:
            self.log('Protection is off.')
            return
        if not self.authorize():
            return
        minutes = simpledialog.askinteger('Pause protection', 'Pause for how many minutes? (1–240)', minvalue=1, maxvalue=240, parent=self.root)
        if minutes is not None:
            self.invalidate()
            self.policy.pause(minutes, time.monotonic())
            self.log('Protection paused temporarily.')

    def resume_protection(self):
        if not self.policy.running:
            self.log('Protection is off.')
            return
        if self.authorize():
            self.invalidate()
            self.policy.pause_until = 0
            self.next_check = time.monotonic()
            self.log('Protection resumed.')

    def stop_protection(self):
        if self.authorize():
            self.invalidate()
            self.policy.stop()
            self.log('Protection disabled.')

    def schedule_awake_save(self, *_):
        if self._awake_save_job is not None:
            self.root.after_cancel(self._awake_save_job)
        self._awake_save_job = self.root.after(500, self._save_awake_if_valid)

    def _save_awake_if_valid(self):
        self._awake_save_job = None
        try:
            self.save_awake_duration()
        except (ValueError, OSError):
            pass

    def flush_awake_duration(self):
        if self._awake_save_job is not None:
            self.root.after_cancel(self._awake_save_job)
            self._awake_save_job = None
            self._save_awake_if_valid()

    def save_awake_duration(self):
        unit = self.awake_unit.get()
        value = self.awake_value.get().strip()
        awake_seconds(value, unit)
        fresh = self.settings.copy()
        fresh.update(awake_duration=float(value.replace(',', '.')), awake_unit=unit)
        write_json(self.data / 'settings.json', fresh)
        self.settings = fresh

    def start_keep_awake(self):
        try:
            self.save_awake_duration()
            self.awake.start(self.awake_value.get().strip(), time.monotonic(), self.awake_unit.get())
            self.log('Keep PC awake started.')
            self.refresh()
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror('Keep PC awake', str(exc), parent=self.root)

    def stop_keep_awake(self):
        self.awake.stop()
        self.log('Keep PC awake stopped.')
        self.refresh()

    def change_pin(self):
        if not self.authorize():
            return
        value = self.ask_new_pin()
        if value is not None:
            try:
                self.pin.replace(value)
                self.log('PIN changed.')
            except (OSError, ValueError) as exc:
                messagebox.showerror('PIN', str(exc), parent=self.root)

    def enroll(self):
        if self.job or not self.authorize():
            return
        if self.model.exists() and not messagebox.askyesno('Register face', 'Replace your face registration?', parent=self.root):
            return
        self.invalidate()
        self.policy.stop()
        self.policy.checks = 0
        self.launch_scan('enroll')

    def manual_test(self):
        if not self.job and self.authorize():
            self.invalidate()
            self.next_check = time.monotonic() + self.settings['interval_seconds']
            self.launch_scan('test')

    def arm(self):
        if self.job or not self.authorize():
            return
        if not self.model.is_file():
            messagebox.showinfo('Real lock', 'Register your face first.', parent=self.root)
            return
        if self.policy.checks < 3:
            messagebox.showinfo('Real lock', 'Complete three successful camera tests first.', parent=self.root)
            return
        if not self.settings['anti_photo']:
            messagebox.showinfo('Real lock', 'Enable experimental photo protection in Settings first.', parent=self.root)
            return
        verified = messagebox.askyesno(
            'Confirm validation',
            'Have you tested your face, another person, and printed and phone photos? '
            'Photo protection is experimental and can fail.', parent=self.root)
        if not verified:
            return
        confirmed = messagebox.askyesno(
            'Enable real lock',
            'Enable Windows locking for this session? Two failed checks start a 15-second grace period. '
            'You will need your Windows sign-in to unlock.', parent=self.root)
        if not confirmed:
            return
        self.invalidate()
        self.policy.arm(confirmed=True)
        self.next_check = time.monotonic() + self.settings['interval_seconds']
        self.log('Real lock enabled for this session. Start protection if it is off.')
        self.refresh()

    def launch_scan(self, kind):
        if self.job:
            return
        if kind != 'enroll' and not self.model.exists():
            self.log('Register your face first.')
            return
        self.epoch += 1
        token = self.epoch
        cancel, sample = threading.Event(), threading.Event()
        self.job = dict(token=token, kind=kind, cancel=cancel, sample=sample, born=time.monotonic())
        self.camera_state = 'In use'
        self.preview = tk.Toplevel(self.root)
        self.preview.title('PresenceGuard — camera')
        self.preview_label = ttk.Label(self.preview)
        self.preview_label.pack()
        self.preview_text = tk.StringVar(value='Opening camera...')
        ttk.Label(self.preview, textvariable=self.preview_text, wraplength=480).pack(padx=10, pady=10)
        if kind == 'enroll':
            ttk.Button(self.preview, text='Capture phase', command=sample.set).pack(pady=5)
        ttk.Button(self.preview, text='Cancel', command=cancel.set).pack(pady=5)
        self.preview.protocol('WM_DELETE_WINDOW', cancel.set)
        settings = self.settings.copy()
        def emit(image, text):
            if self.messages.qsize() < 2:
                self.messages.put(('frame', token, image, text))
        def worker():
            try:
                ok, text = run_camera(kind, self.model, settings, cancel, sample, emit)
            except Exception:
                ok, text = None, 'Camera or face model unavailable. Check the camera and permissions.'
            self.messages.put(('done', token, kind, ok, text))
        threading.Thread(target=worker, daemon=True, name='PresenceGuard-camera').start()

    def accept_result(self, token, kind, ok, text):
        if token != self.epoch:
            return
        now = time.monotonic()
        self.log(text)
        self.camera_state = 'Unavailable' if ok is None else 'Ready'
        if kind == 'enroll':
            self.policy.checks = 0
            if self.setup_active and ok is True:
                self.root.after(100, self.setup_test)
            elif self.setup_active:
                self.setup_active = False
            return
        if ok is None:
            if kind == 'test':
                self.policy.checks = 0
            self.next_check = now + self.settings['interval_seconds']
            return
        self.last_check = time.strftime('%H:%M:%S')
        outcome = self.policy.result(ok is True, now, automatic=kind == 'auto')
        self.next_check = now + (2 if outcome == 'retry' else self.settings['interval_seconds'])
        if outcome == 'grace':
            self.root.bell()
            self.log('Not recognized twice. Lock decision in 15 seconds.')
        elif kind == 'test':
            self.status.set(text + ' Successful tests: %d/3.' % self.policy.checks)
            if self.setup_active:
                self.setup_active = False
                if ok:
                    messagebox.showinfo('Setup', 'Ready. Enable protection to begin in test mode.', parent=self.root)

    def setup_test(self):
        if messagebox.askyesno('Setup', 'Face registered. Test the camera now?', parent=self.root):
            self.manual_test()
            if self.job is None:
                self.setup_active = False
        else:
            self.setup_active = False

    def enforce(self, now):
        action = self.policy.action(now)
        if action == 'simulate_lock':
            self.log('TEST MODE: Windows would have been locked.')
        elif action == 'lock':
            try:
                lock_windows()
                self.log('Lock requested from Windows.')
            except RuntimeError as exc:
                self.policy.stop()
                self.log(str(exc))
        if action:
            self.next_check = now + self.settings['interval_seconds']

    def on_session_change(self, unlocked, now):
        if unlocked == self.session_is_unlocked:
            return
        self.session_is_unlocked = unlocked
        if not unlocked:
            self.invalidate()
            self.camera_state = 'Closing while locked'
            self.log('Windows session locked. Closing the camera.')
        else:
            self.next_check = now + self.settings['interval_seconds']
            self.camera_state = 'Ready'
            self.log('Windows session unlocked.')

    def tick(self):
        now = time.monotonic()
        while not self.session_events.empty():
            self.on_session_change(self.session_events.get_nowait(), now)
        self.on_session_change(session_unlocked(), now)
        self.awake.tick(now)
        try:
            if consume_open(self.data / 'show.request'):
                self.show_window()
        except OSError:
            pass
        while not self.messages.empty():
            item = self.messages.get_nowait()
            if item[0] == 'tray':
                action = item[1]
                self.show_window()
                {'open': lambda: None, 'status': lambda: None, 'settings': self.open_settings,
                 'pause': self.pause_protection, 'resume': self.resume_protection, 'exit': self.close_app}[action]()
                try:
                    if not self.root.winfo_exists():
                        return
                except tk.TclError:
                    return
                continue
            token = item[1]
            if item[0] == 'done':
                if self.job and self.job['token'] == token:
                    self.job = None
                    if self.preview and self.preview.winfo_exists():
                        self.preview.destroy()
                    self.preview = self.preview_image = None
                self.accept_result(token, item[2], item[3], item[4])
            elif token == self.epoch and self.preview and self.preview.winfo_exists():
                self.preview_image = tk.PhotoImage(data=item[2])
                self.preview_label.configure(image=self.preview_image)
                self.preview_text.set(item[3])
        if self.job and now - self.job['born'] > 130 and not self.job['cancel'].is_set():
            self.invalidate()
            self.log('Camera timed out. Check the camera driver.')
        if self.session_is_unlocked:
            self.enforce(now)
            if self.policy.running and not self.policy.paused(now) and not self.job and self.policy.grace_until is None and now >= self.next_check:
                self.launch_scan('auto')
        self.refresh()
        self.root.after(150, self.tick)

    def open_settings(self):
        if self.job or not self.authorize():
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('Settings')
        dialog.transient(self.root)
        dialog.grab_set()
        def cancel_settings():
            self.setup_active = False
            dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW', cancel_settings)
        frame = ttk.Frame(dialog, padding=10)
        frame.pack()
        value = tk.StringVar(value=str(self.settings['interval_seconds']/60))
        unit = tk.StringVar(value='minutes')
        ttk.Label(frame, text='Check every:').grid(row=0, column=0, sticky='w')
        ttk.Entry(frame, textvariable=value, width=10).grid(row=0, column=1)
        ttk.Combobox(frame, textvariable=unit, values=('seconds', 'minutes', 'hours'), state='readonly', width=10).grid(row=0, column=2)
        flags = {}
        for row, (key, title) in enumerate((('low_light', 'Low light'), ('anti_photo', 'Photo protection — Experimental'), ('startup', 'Start with Windows')), 1):
            flags[key] = tk.BooleanVar(value=self.settings[key])
            ttk.Checkbutton(frame, text=title, variable=flags[key]).grid(row=row, column=0, columnspan=3, sticky='w', pady=5)
        camera = tk.StringVar(value=str(self.settings['camera']))
        ttk.Label(frame, text='Camera number (0–10):').grid(row=4, column=0, sticky='w')
        ttk.Spinbox(frame, from_=0, to=10, textvariable=camera, width=8).grid(row=4, column=1)
        def save():
            try:
                fresh = self.settings.copy()
                fresh.update({key: var.get() for key, var in flags.items()})
                fresh.update(interval_seconds=seconds(value.get(), unit.get()), camera=int(camera.get()))
                if not 0 <= fresh['camera'] <= 10:
                    raise ValueError('Choose a camera number from 0 to 10.')
                configure_startup(fresh['startup'])
                write_json(self.data / 'settings.json', fresh)
                self.settings = fresh
                self.invalidate()
                self.policy.armed = False
                self.policy.checks = 0
                self.next_check = time.monotonic() + fresh['interval_seconds']
                self.log('Settings saved. Test again before enabling real lock.')
                dialog.destroy()
                if self.setup_active:
                    self.root.after(100, self.setup_register)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                messagebox.showerror('Settings', str(exc), parent=dialog)
        ttk.Button(frame, text='Save', command=save).grid(row=5, column=0, columnspan=3, pady=14)

    def setup_register(self):
        if messagebox.askyesno('Setup', 'Camera selected. Register your face now?', parent=self.root):
            self.enroll()
            if self.job is None:
                self.setup_active = False
        else:
            self.setup_active = False

    def close_app(self):
        if self.pin.exists() and not self.authorize():
            return
        self.flush_awake_duration()
        self.invalidate()
        self.policy.stop()
        self.awake.stop()
        self.session_monitor.stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()


def main():
    if os.name != 'nt':
        raise SystemExit('PresenceGuard requires Windows.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel.CreateMutexW(None, False, 'Local\\PresenceGuardV1')
    if not handle:
        raise OSError('Could not start PresenceGuard.')
    if ctypes.get_last_error() == 183:
        try:
            request_open(DATA / 'show.request')
        finally:
            kernel.CloseHandle(handle)
        return
    root = tk.Tk()
    try:
        app = App(root)
        root.after(350, app.boot)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror('PresenceGuard', str(exc), parent=root)
    finally:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()
