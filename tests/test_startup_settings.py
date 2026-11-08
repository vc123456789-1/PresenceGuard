import gc
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest import TestCase
from unittest.mock import patch
import main
from guard import load_settings


def widgets(root):
    for child in root.winfo_children():
        yield child
        yield from widgets(child)


class StartupSettingsTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = main.App(self.root, Path(self.tmp.name))

    def tearDown(self):
        self.root.destroy()
        self.app = self.root = None
        gc.collect()
        self.tmp.cleanup()

    def test_availability_requires_the_installed_executable(self):
        installed = Path(self.tmp.name) / 'Programs' / 'PresenceGuard' / 'PresenceGuard.exe'
        with patch.dict(main.os.environ, {'LOCALAPPDATA': self.tmp.name}), \
             patch.object(main.sys, 'frozen', True, create=True), \
             patch.object(main.sys, 'executable', str(installed)):
            self.assertTrue(main.startup_available())
            with patch.object(main.sys, 'executable', str(Path(self.tmp.name) / 'portable' / 'PresenceGuard.exe')):
                self.assertFalse(main.startup_available())
            with patch.object(main.sys, 'frozen', False, create=True):
                self.assertFalse(main.startup_available())

    def test_portable_shows_unavailable_and_saves_interval_without_changing_startup(self):
        self.app.settings['startup'] = True
        with patch.object(self.app, 'authorize', return_value=True), \
             patch('main.startup_available', return_value=False, create=True), \
             patch('main.configure_startup') as configure:
            self.app.open_settings()
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
            all_widgets = list(widgets(dialog))
            startup = next(w for w in all_widgets if isinstance(w, ttk.Checkbutton) and w.cget('text') == 'Start with Windows')
            self.assertIn('disabled', startup.state())
            self.assertTrue(any('Install PresenceGuard' in str(w.cget('text')) for w in all_widgets if isinstance(w, ttk.Label)))
            entry = next(w for w in all_widgets if isinstance(w, ttk.Entry))
            entry.delete(0, tk.END)
            entry.insert(0, '2')
            next(w for w in all_widgets if isinstance(w, ttk.Button) and w.cget('text') == 'Save').invoke()
            configure.assert_not_called()
        saved = load_settings(Path(self.tmp.name) / 'settings.json')
        self.assertEqual(saved['interval_seconds'], 120)
        self.assertTrue(saved['startup'])

    def test_installed_can_enable_startup(self):
        with patch.object(self.app, 'authorize', return_value=True), \
             patch('main.startup_available', return_value=True, create=True), \
             patch('main.configure_startup') as configure:
            self.app.open_settings()
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
            all_widgets = list(widgets(dialog))
            startup = next(w for w in all_widgets if isinstance(w, ttk.Checkbutton) and w.cget('text') == 'Start with Windows')
            self.assertNotIn('disabled', startup.state())
            startup.invoke()
            next(w for w in all_widgets if isinstance(w, ttk.Button) and w.cget('text') == 'Save').invoke()
            configure.assert_called_once_with(True)
        self.assertTrue(load_settings(Path(self.tmp.name) / 'settings.json')['startup'])
