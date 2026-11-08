import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import main


@unittest.skipUnless(os.name == 'nt', 'Windows startup shortcuts')
class StartupTests(unittest.TestCase):
    def test_repeat_enable_replaces_one_shortcut_and_removes_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            shortcut = Path(d) / 'PresenceGuard.lnk'
            legacy = shortcut.with_name('PresenceGuard v1.lnk')
            legacy.touch()
            exe = Path(os.environ['LOCALAPPDATA']) / 'Programs/PresenceGuard/PresenceGuard.exe'
            commands = []
            def simulate_run(command, **kwargs):
                commands.append(command[-1])
                shortcut.touch()
            with patch.object(main, 'startup_path', return_value=shortcut), \
                    patch.object(main.sys, 'frozen', True, create=True), \
                    patch.object(main.sys, 'executable', str(exe)), \
                    patch.object(main.subprocess, 'run', side_effect=simulate_run):
                main.configure_startup(True)
                main.configure_startup(True)
                self.assertEqual(list(Path(d).glob('*.lnk')), [shortcut])
                self.assertFalse(legacy.exists())
                self.assertTrue(all(str(exe) in cmd and '--startup' in cmd for cmd in commands))
                main.configure_startup(False)
                self.assertEqual(list(Path(d).glob('*.lnk')), [])

    def test_unfrozen_source_cannot_create_startup(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(main, 'startup_path', return_value=Path(d) / 'PresenceGuard.lnk'), \
                patch.object(main.sys, 'frozen', False, create=True), \
                patch.object(main.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                main.configure_startup(True)
            run.assert_not_called()

    def test_portable_executable_cannot_create_startup(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(main, 'startup_path', return_value=Path(d) / 'PresenceGuard.lnk'), \
                patch.object(main.sys, 'frozen', True, create=True), \
                patch.object(main.sys, 'executable', 'C:/Portable/PresenceGuard/PresenceGuard.exe'), \
                patch.object(main.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                main.configure_startup(True)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
