# Test report — PresenceGuard 1.1 review build

## Safety status

Every launch starts in test mode. Real Windows locking requires a registered face and one explicit confirmation for the current session; confirming also starts protection if it is stopped. Settings, face registration, pausing or stopping protection, and exit remain protected by the in-app PIN. A manual camera test is optional, and experimental photo protection is enabled by default but is not required to activate locking. The user reported testing both an unregistered person and printed or phone-displayed photos. The test conditions, detailed outcomes and error rates have not been independently recorded here. Automated tests mock lock requests and did not lock the computer. The software is not independently validated as a security product.

## Automated tests

Run on the build machine with `python -m unittest discover -s tests -v`. The initial unchanged project passed 41 tests. The updated tests cover interval limits; salted PIN verification and progressive persistent waits; test-mode lock simulation; pause and keep-awake policy; energy-request expiration and release through mocks; unavailable camera and cancellation; empty, dark and multiple-face input; local DPAPI template round-trip; startup shortcut logic with simulated PowerShell; and lock/unlock state transitions. A Windows session-notification registration and synthetic message test does not lock the session. The user encountered a startup error while running the portable executable: the earlier settings dialog attempted to create a startup shortcut before saving the other settings. The current portable dialog disables that option and saves other settings without changing any existing startup entry. Automated GUI tests cover the portable and installed settings paths; the tests mock shortcut creation. The current suite passed 91 tests. No automated Windows lock was requested.

The model files were loaded using OpenCV and synthetic image input. That is a resource and inference smoke test, not an accuracy test. In the source application, the three sections were inspected on screen. The 30-minute timer was started; a five-second duration expired; and stopping a running timer was checked. A real Windows power request was accepted and then released on the same thread.

A real tray icon was created. Closing the application window hid it while the process stayed active; reopening was checked using the same signal that another instance would send. A synthetic Win32 tray click also queued the open action. The installed startup shortcut was created and checked to point to the installed executable with --startup. Actual startup after a Windows sign-in was not tested. A physical double-click, the hidden-icons menu and notifications remain to be verified. Camera drivers may block a read; cancellation requests release, but its completion depends on the driver returning.

## Not performed

- Independently observed and recorded owner recognition in normal and dim light, with glasses and angles.
- Independently observed and recorded rejection of another person and printed or phone-displayed photographs and video.
- Camera occupied, disconnected or permission denied on a physical device.
- Full recognition latency, memory consumption and threshold calibration on the target laptop.
- Supervised real lock and unlock, whether background processes continue through that real lock, and visual automation on a locked desktop.
- Installation, uninstall, startup and portable operation on a clean Windows x64 machine without Python.

No acceptance, rejection or anti-spoofing rates can be claimed. SFace's starting threshold is an example, not a calibrated threshold. Photo protection is a blink heuristic and may be bypassed. The license files and the open question about the provenance of SFace weights are explained in `MODELS.md`.

Source archives exclude user PIN files, face templates and history. Old versions may have left an unencrypted LBPH model in the user's local data folder; it is not imported or included in these distributions. The user may remove it after reviewing any needed backup.
