# PresenceGuard

PresenceGuard is a small Windows app that checks whether a registered person is at the computer. It runs locally and can request a Windows lock after two failed checks and a 15-second grace period when real locking has been explicitly enabled for the current session. A normal Windows lock keeps your apps and session open. PresenceGuard does not close programs or sign you out.

**Every launch starts in test mode.** Test mode never locks Windows. Real locking requires explicit in-app confirmation for the current session. The face matching and experimental photo challenge have not been independently validated as security controls. A printed photo, phone, video, poor lighting, camera problem or other condition may defeat a check or cause a false rejection. Do not rely on this app as your only security measure. Use a Windows password or PIN. PresenceGuard cannot prevent someone with access to the account from stopping or changing it.

## Install

On Windows x64, run `PresenceGuard-Setup-x64.exe`. The installer includes the application, Python runtime, libraries and models. It installs for the current user under `%LOCALAPPDATA%\Programs\PresenceGuard` and creates a Start menu shortcut. It offers a desktop shortcut and an uninstaller; administrator rights are not normally needed. Python, pip and a terminal are not required for everyday use.

For a portable copy, extract `PresenceGuard-Portable-x64.zip` to a stable folder and open `PresenceGuard.exe` inside the extracted `PresenceGuard` folder. The portable ZIP contains the executable application, not just source code. Do not run directly from inside the ZIP. Both distributions still use the current user's local data folder. Installing and running on a clean Windows system without Python remains unverified unless separately recorded in the test report.

## First use

1. Open PresenceGuard and create a local PIN. This is not your Windows PIN. Keep your Windows sign-in credentials available.
2. Choose the camera and register your face. Capture all three phases: normal light, dim light and different angles. Use one person in view. Images stay in memory and are discarded; only protected feature vectors are stored.
3. Run the camera test with normal and dim light, glasses if used, and different positions. Also test a different person and printed and phone-displayed photos in a supervised session. The program cannot certify the results itself.
4. Review your test results. To enable real locking for this session, first complete three consecutive successful manual camera tests with photo protection enabled. Then select **Enable real lock**, enter your PIN, and confirm your identity and photo tests and the real-lock warning. Select **Start** if protection is off. Restarting the app returns it to test mode; installation and startup never enable real locking automatically.

The main window has General, Settings and Keep PC awake sections. General shows the protection status, check interval and last check, with Start, Stop and Enable real lock controls. Settings contains camera, face registration, test and PIN controls. Protection is checked every three minutes by default. At that interval, two failed checks and the grace period may take roughly four minutes from starting protection; camera timing varies. Settings can change the interval using seconds, minutes or hours. Low-light enhancement is applied consistently during registration and checks. It cannot recover detail in total darkness. Photo protection is experimental: a blink challenge is separate from identity matching, and it is not a proven defence against photos, screens or video.

Closing the window hides it in the Windows notification area while protection continues. Open it from the tray icon, including the hidden-icons menu. If the tray cannot start, the window remains available. Pause and exit are protected by the local PIN. The Windows lock screen remains the real lock screen; PresenceGuard does not unlock Windows or store the Windows password.

## Keep PC awake

In the Keep PC awake section, enter a duration and choose seconds, minutes or hours, then select Start. The default is 30 minutes; allowed durations are from 1 second to 24 hours. The selected duration is saved for the next launch, but Keep PC awake always starts off. Stop ends the current request. Remaining time is shown in the window.

This optional request prevents automatic system sleep for the selected period while allowing the display to turn off. It does not prevent a Windows lock and does not change the power plan. Turning it off, expiration and exiting release the request. Manual sleep and lid-close actions remain under Windows control.

- **Background processes:** a Windows lock normally leaves existing applications and background jobs running. Jobs can still stop for unrelated reasons, including power loss or application behavior.
- **Remote tasks:** services running on another computer continue according to that computer's state and connection. A local lock does not guarantee remote completion.
- **Interactive desktop automation:** automation that requires the visible, interactive desktop may fail or pause while Windows is locked. Do not assume that a visual agent can operate the locked desktop.

## Privacy and data

No telemetry or image upload is implemented. No pictures of unknown people are saved. PresenceGuard keeps settings, PIN verifier, local history and encrypted face templates in the current user's local data folder. Face vectors are encrypted using Windows DPAPI for the current Windows account. DPAPI does not protect data against an attacker who can operate as that account. Backups copied to another account or machine may not decrypt. The PIN uses a salted key-derivation function; it is never the Windows PIN. Source distributions and installers should not contain personal data.

Old LBPH registrations are not compatible with the new embedding model. Register again if upgrading. Do not copy old face data into a source archive.

## Models and limitations

The application uses OpenCV YuNet `face_detection_yunet_2023mar.onnx` for detection and five-point alignment, and OpenCV SFace `face_recognition_sface_2021dec.onnx` for local identity embeddings. Both run on CPU without an NVIDIA GPU or internet connection. The SFace cosine threshold is an initial example value, not a calibrated security threshold. The model comparison, exact hashes, license terms, source links and unresolved rights question are in [docs/MODELS.md](docs/MODELS.md).

**No claim of accuracy or photo/video resistance is made for this application.** Owner and impostor acceptance/rejection tests, webcam testing, low-light conditions, RAM measurements and a clean-machine installation must be recorded separately. Real locking needs a supervised validation session; never run automated lock tests unattended.

## Explore and run the source

The application code is in `main.py` (window and controls), `guard.py` (PIN and protection rules), `vision.py` (camera and face matching), `platform_support.py` (tray and power request), and `windows_session.py` (session notifications). Automated tests are in `tests/`. Model versions, sources and licenses are in `docs/MODELS.md` and `models/`.

To run the source on Windows x64 with Python 3.12, open PowerShell in the source folder and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py
```

The tests do not request a Windows lock. The source application also starts in test mode; real locking requires the same in-app steps and explicit confirmation.

## Building from source

On a Windows x64 build machine, install 64-bit Python 3.12 and Inno Setup 6.4.3, then run `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`. You can pass `-InnoCompiler` with the path to `ISCC.exe` if it is not on PATH. The script installs pinned build dependencies and creates the portable ZIP and installer in `release/`. This installer was built with Inno Setup 6.4.3. Its bundled license permits commercial use, while its publisher requests that commercial users purchase a license regardless of version; review the publisher guidance before commercial distribution: https://jrsoftware.org/ishelp/topic_purchase.htm. Users of the built application need none of those tools. The source archive and portable executable archive are separate deliverables.

For verification results and untested items, see the accompanying test report. Do not put personal face data, PIN records or logs in a release archive or public repository.
